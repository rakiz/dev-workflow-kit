# DESIGN — `backupctl` (fixture D1)

`backupctl` backs up a configured set of directories (N of them) into a
**backup root** as *snapshots*: point-in-time, self-consistent images of
each source directory. It builds on the code already in this directory:

- `synccli.py` — scanning (`scan_files`, `synccli.py:10`), change
  detection (`file_state`, `synccli.py:22`; `changed_files`,
  `synccli.py:36`), and copying (`copy_file`, `synccli.py:62`).
- `snaputil.py` — snapshot naming/listing (`list_snapshots`,
  `snaputil.py:8`), pruning (`prune_snapshots`, `snaputil.py:23`), sizes
  (`snapshot_disk_usage`, `snaputil.py:39`), path confinement
  (`safe_snapshot_path`, `snaputil.py:54`), staleness (`is_stale`,
  `snaputil.py:66`).

Every requirement below names the existing function it builds on, or the
exact override and why.

---

## 1. Layout of the backup root

```
<backup_root>/
  config.json              # list of source dirs, retention policy
  lock                     # flock file: writers exclusive, readers shared (§3)
  store/
    blobs/<xx>/<sha256>    # content-addressed file payloads (dedup)
  snap-YYYYMMDD-HHMMSS-SEQ/
    index.json             # per-source manifest: relpath -> {size, mtime, sha256, blob}
    data/<relpath>         # symlink or hardlink into store/blobs (see §5)
  staging-<pid>-<ts>/      # a run in progress; renamed to snap-… on success
  trash-<name>/            # snapshot being deleted (§6); "trash-" is ignored
                           # by snaputil.list_snapshots (snaputil.py:18 only
                           # accepts names starting with "snap-")
```

Snapshot names are exactly the `snap-` pattern `list_snapshots` already
parses and sorts oldest-first, so `snaputil` keeps working unchanged as
the read-side helper (`snapshot_disk_usage` for `backupctl status`,
`safe_snapshot_path` to resolve any relpath stored in `index.json` —
which also gives us its `..`-confinement guarantee for free).

## 2. What a run does

1. **Lock** (§3).
2. **Recover** leftovers of dead runs (§4).
3. For each configured source directory:
   a. Scan it with `synccli.scan_files` (unchanged; note it already
      skips dot-directories — we keep that behavior and document it as
      "dotfiles at directory level are not backed up").
   b. Build the candidate manifest with `synccli.build_manifest`
      (which uses `file_state`: `(size, mtime)` per file).
   c. Diff against the newest complete snapshot's `index.json` using
      `synccli.changed_files` — identical semantics, no override.
   d. For every changed/new file: read it, hash it (sha256), and if a
      blob with that hash is not already in `store/`, copy it in with
      `synccli.copy_file` **modified** (see override below); then link
      the blob into `staging-…/data/<relpath>`.
   e. Unchanged files get no new blob; their `index.json` entry points
      at the *existing* blob hash.
4. Write `staging-…/index.json` **last**, fsync it and the directory.
5. `os.rename(staging-…, snap-…)` — atomic on the same filesystem.
6. Prune (§6), release lock, print a summary (copied / deduped /
   missing counts).

**Override 1 — `synccli.copy_file` (`synccli.py:62`).** Today it swallows
`OSError` and writes nothing (`except OSError: pass`, lines 68–69). For
sync-into-place that is tolerable; for a snapshot it silently produces
an index that promises a file the snapshot does not contain — exactly
the corruption the brief forbids. `backupctl` uses a variant that
*reports* the failure, records the file as `missing` in the index, and
continues (§7). The dedup path (`shutil.link` of an existing blob) is
new code and does not go through `copy_file` at all.

**Override 2 — `synccli.sync`'s manifest write (`synccli.py:85-86`).**
`sync` writes the manifest *in place over* the old one and *before*
any rename; a crash mid-write leaves a half-written manifest that
`json.load` (line 79) then chokes on. `backupctl` never writes an index
in place over a complete one: indexes are written inside staging and
become visible only via the atomic rename of step 5. The write-and-fsync
order (index last, after all data) is the inverse guarantee.

## 3. Concurrency: scheduler, human, restore

- **Runs serialize.** Every run takes an exclusive `flock(LOCK_EX)` on
  `<backup_root>/lock` (blocking, with a timeout of e.g. 10 min; on
  timeout it exits non-zero with a clear message). Two simultaneous
  runs — scheduler + person — cannot interleave: the second waits or
  fails loudly. Per-run cost of serialization is fine because runs are
  incremental and short (§9).
- **Readers never block and never corrupt.** A restore (or a human, or
  the next run reading the previous index) takes a *shared* flock
  (optional but cheap) and reads only `snap-…` directories, which by
  construction are post-rename and therefore complete. Nothing ever
  mutates a `snap-…` directory after rename; "is the producing run
  finished?" is answered by the directory's name, not by asking.
- **Prune vs. reader** — §6.

## 4. Crash recovery

A run can die anywhere (Ctrl-C, sleep, kill). The invariant that makes
every crash survivable: **the only visible unit of work is the atomic
rename of step 5.** Everything before it lives under `staging-…` (or is
an orphaned blob), everything after it is a complete snapshot.

| Crash point | What is left | Recovery on next run |
|---|---|---|
| During scan/copy | `staging-…` dir, some blobs | Next run deletes every `staging-…` dir older than 1 hour *before* taking meaningful work (it holds the exclusive lock, so no live staging dir can be misjudged; the 1-hour age guard via `snaputil.is_stale`-style mtime comparison covers a lock released by process death). Blobs without any referencing index are garbage-collected by the same pass (§6.5). |
| During index write | `staging-…` with a partial `index.json` | Same: the whole staging dir is discarded. A partial index is never visible to anyone because it was never inside a `snap-…` dir. |
| Mid-rename | — | `rename(2)` is atomic; the snapshot is either fully absent or fully present. |
| Corrupt/half-written `index.json` in a **complete** snapshot (e.g. disk-level damage) | A `snap-…` dir with an unparsable index | Next run: `json.load` fails → it rebuilds the index from the tree: `synccli.scan_files` over `snap-…/data/` plus a re-hash of each file (the tree *is* the ground truth; blobs are content-addressed so re-derivation is exact). It reports `"index recovered by re-scan"` on stderr and proceeds using the rebuilt manifest. Nothing is discarded from the snapshot itself. |

The recovery pass is bounded: one `os.walk` + stat per staging dir and
one parse per complete snapshot index — see §8 for the cost.

## 5. Incremental backup: granularity and what it can miss

**Granularity: whole files, decided by `(size, mtime)`** — exactly
`synccli.file_state` / `synccli.changed_files`. A file is "unchanged"
iff both match the newest snapshot's index entry; unchanged files cost
one `stat` each, no read, no copy (the index entry is carried forward
with its blob hash). New/changed files are read once, hashed, and
stored once — the content-addressed store makes re-backup of identical
content across the N source directories free.

**What this granularity can miss** (stated explicitly):
- Edits that preserve both size and mtime (in-place same-size writes
  that restore the old mtime; mtime granularity is sub-microsecond on
  APFS/HFS+ but coarse on some network filesystems).
- A file changed *and* changed back between two runs.
Mitigation offered but not defaulted: `backupctl run --verify` forces a
sha256 re-check of every file (full read cost, §9). The default trades
these corner cases for one-`stat`-per-unchanged-file runs; this is the
same trade `synccli` makes today (`test_synccli.py:48`,
`test_second_sync_is_noop`, passes on this exact mechanism).

**Snapshot data layout:** `snap-…/data/<relpath>` is a hardlink to
`store/blobs/<xx>/<sha256>` (same filesystem), falling back to a
relative symlink if hardlinks are unavailable. Restores are plain file
copies out of `data/`, resolved via `snaputil.safe_snapshot_path`.

## 6. Retention

- Policy: keep the newest **K** complete snapshots and, independently,
  every snapshot newer than **D** days; config lives in
  `<backup_root>/config.json`. `K ≥ 1` is enforced by construction.
- Deletion never removes the newest snapshot — this is precisely what
  `snaputil.prune_snapshots` (`snaputil.py:23`) already guarantees
  ("only the oldest ones are removed, so the newest snapshot is never
  deleted"), so `backupctl` calls it as-is and additionally checks the
  age rule on its result.
- **Safe while being read:** a doomed snapshot is first
  `os.rename`d to `trash-<name>` (invisible to `list_snapshots`,
  `snaputil.py:18`), then `shutil.rmtree`d (the same call
  `prune_snapshots` makes, `snaputil.py:35`). On POSIX a reader holding
  an open file descriptor — or a process that resolved its paths before
  the rename — keeps reading a consistent, now-unlinked tree to the
  end; a reader that starts *after* the rename simply cannot see the
  snapshot. No torn read is possible in either window.
- A crash between rename and rmtree leaves a `trash-…` dir; the next
  run's recovery pass (§4) rmtree's stale `trash-…` dirs.

## 7. Vanishing / unreadable source files

A file can disappear between `scan_files` listing and the copy, or be
unreadable (permissions) when the copy reaches it. Behavior — identical
for scheduler-started and person-started runs, because the run body is
the same function either way:

- The copy path is attempted via the **modified** `copy_file` (§2,
  Override 1). `FileNotFoundError` / `PermissionError` / any `OSError`
  → the file is recorded in `index.json` as
  `{"relpath": ..., "status": "missing"}` and *omitted from `data/`*.
- The snapshot remains complete and self-consistent **for what it
  contains**: every non-missing index entry has its blob on disk. The
  index never promises a file the snapshot lacks.
- The run **reports** it: one line per missing file on stderr and a
  `missing: k of m` line in the summary; exit code 0 with `missing=0`,
  exit code 3 when any file was missing (so the scheduler can alert
  without treating it as corruption). Missing files are retried
  naturally on the next run (`changed_files` re-diffs them because they
  are absent from the previous index's *copyable* set) — the
  bookkeeping for "which entries still need a retry" is what
  `synccli.collect_stale` (`synccli.py:45`) computes over
  `(path, fresh)` pairs; we reuse it in that role instead of
  hand-rolling the same filter.

## 8. Growth: what scales with what

Let **N** = number of source directories, **F** = files in the largest
tree, **B** = its bytes, and **C** = files changed since the last run.
Measured constants (§9): stat ≈ 270k files/s, sha256 ≈ 600 MB/s,
copy ≈ 196 MB/s.

| Quantity | Bound |
|---|---|
| Per-run time | `O(F/270k) + O(C·(size)/600MB/s + C·overhead)` s — walk+stat all files (F stats), read+hash+store only the C changed. Formula, constants measured. |
| Per-run memory | `O(F)` — the manifest dict (`synccli.build_manifest` holds `{relpath: state}` for one tree at a time; trees are processed sequentially, so it is the *max*, not the *sum*, over the N dirs). At ~150 bytes/entry, 100k files ≈ 15 MB. |
| Per-run disk written | `O(bytes of C changed files)` after the first run; `O(B)` once, for the initial full. Dedup means identical content across the N dirs is stored once. |
| Lock contention | Flat: one lock for all of N — runs serialize regardless of N. |
| Recovery pass cost | `O(S·F + S')` where S = leftover staging dirs (normally 0, at most 1 per crash) and S' = number of complete snapshot indexes parsed (one `json.load` each). |
| Retention/delete | `O(K)` rmtrees per run, K = retention count — flat in N and B. |
| Restore cost | `O(bytes restored)` — plain copy out of `data/`, unchanged by N. |

## 9. First full backup: performance budget

Budget: **≤ 60 s wall clock for the initial full backup of a ~1 GB tree
of ~20k files.** The number is derived from measurements run in this
directory's environment (macOS, APFS, 2 000 × 50 KB files ≈ 102 MB
tree):

| Phase | Measured | Extrapolation to 1 GB / 20k files |
|---|---|---|
| stat walk (`os.walk` + `os.stat`) | 2 000 files / 0.01 s ≈ **270k files/s** | 20k files → **0.07 s** |
| read + sha256 | 102 MB / 0.17 s ≈ **600 MB/s** | 1 GB → **1.7 s** |
| copy to store (`shutil.copyfileobj`, 1 MiB chunks) | 102 MB / 0.52 s ≈ **196 MB/s** | 1 GB → **5.2 s** |
| per-file overhead (open/hash/link, 20k ×) | ≈ 0.09 ms/file (0.17 s / 2 000 minus streaming) | 20k → **~2 s** |

Total ≈ **9 s**, an order of magnitude inside the 60 s budget — the
margin absorbs filesystem variance, fsyncs, and index writing. The
dominant term is the byte-copy, so the budget is robust to per-file
overhead growth but sensitive to disk write bandwidth; on a 100 MB/s
disk the copy alone is 10 s and the total ≈ 14 s, still inside budget.
`copy_file`'s current `fsrc.read()`-whole-file body (`synccli.py:66-67`)
is replaced by chunked `shutil.copyfileobj` in `backupctl`'s variant —
at 196 MB/s measured with chunking, and to avoid a whole-file-sized
read buffer on large blobs.

## 10. Grounding summary (existing → used for)

| Existing artifact | Used for |
|---|---|
| `synccli.scan_files` (`synccli.py:10`) | source & snapshot-tree scanning (§2, §4) |
| `synccli.file_state` (`synccli.py:22`) + `changed_files` (`synccli.py:36`) | incremental change detection at file granularity (§5) |
| `synccli.build_manifest` (`synccli.py:28`) | per-tree manifest construction (§2, §8 memory bound) |
| `synccli.copy_file` (`synccli.py:62`) | blob ingestion — **overridden**: no silent `OSError: pass` (lines 68–69), chunked copy (§2, §9) |
| `synccli.sync` (`synccli.py:72`) | reference flow only — **overridden**: manifest written after data, atomically renamed, never in place (lines 85–86) (§2) |
| `synccli.collect_stale` (`synccli.py:45`) | retry bookkeeping for missing files (§7) |
| `snaputil.list_snapshots` (`snaputil.py:8`) | snapshot discovery/ordering; its `snap-` prefix filter (line 18) also hides `staging-`/`trash-` dirs (§1, §6) |
| `snaputil.prune_snapshots` (`snaputil.py:23`) | retention, reused as-is; its keep-newest guarantee is the "never without a usable snapshot" rule (§6) |
| `snaputil.snapshot_disk_usage` (`snaputil.py:39`) | `backupctl status` sizes (§1) |
| `snaputil.safe_snapshot_path` (`snaputil.py:54`) | restore-side path confinement (§1, §5) |
| `snaputil.is_stale` (`snaputil.py:66`) | mtime-based age checks in the recovery pass (§4) |
| `test_synccli.py` (`test_synccli.py:48`) | validates the (size, mtime) no-op invariant the design leans on (§5) |

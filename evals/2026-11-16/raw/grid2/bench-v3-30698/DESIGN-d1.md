# DESIGN — `backupctl` (fixture D1)

A command-line backup tool for the `evals/` workflow: it watches a configured
set of directories and produces point-in-time snapshots under a backup root.
`backupctl.py` will live alongside `synccli.py` and `snaputil.py` and reuse
them rather than re-implement their coverage. All line references below were
verified against the files in this directory; the existing test suite
(`python3 -m unittest`, 6 tests) passes as of this writing.

---

## 1. Commands and configuration

```
backupctl run     [--config backupctl.json]     # take a snapshot of all configured dirs
backupctl list    <backup_root>                 # snapshots + disk usage
backupctl restore <backup_root> <snapshot> <dest>
backupctl prune   <backup_root> --keep N
```

Config (`backupctl.json`, read by `run` only):

```json
{ "backup_root": "...", "dirs": ["evals/run1", "evals/run2", "..."], "keep": 20 }
```

Three directories today, a few dozen over time: `dirs` is a list; every
per-run cost is stated below as a formula over N (directories), F (total
files across all dirs) and B (total bytes).

## 2. Reused code (grounding)

| Existing artifact | What it does | How `backupctl` uses it |
|---|---|---|
| `synccli.scan_files` (synccli.py:10-19) | `os.walk` returning **sorted** relative paths, skipping dot-names (line 14) | Reused as-is to enumerate each configured directory. Convention stated: dot-files/dot-dirs are not backed up (same rule as `synccli`). |
| `synccli.build_manifest` (synccli.py:28-33) | `{relpath: state}` per directory | Reused as-is per configured directory; the manifest becomes this run's candidate state. |
| `synccli.file_state` (synccli.py:22-25) | `(size, mtime)` change-detection state | Reused, with one override — see §8. |
| `synccli.changed_files` (synccli.py:36-42) | Diff of two state maps, returns changed/new keys | Reused as-is: the "old manifest" is the previous snapshot's index, the "new manifest" is the freshly built one. Its output is exactly the copy set. |
| `synccli.collect_stale` (synccli.py:45-59) | Collect items not yet marked fresh | Reused for the crash sweep (§6): items = `(tmp_dir_name, False)` for every leftover `.tmp-snap-*` directory; `seen` stays empty because the exclusive lock (§4) guarantees no live writer exists. |
| `synccli.copy_file` (synccli.py:62-69) | Copy with parent-dir creation | **Overridden** (§8): it reads the whole file into memory (line 67) and silently swallows every `OSError` (lines 68-69). |
| `snaputil.list_snapshots` (snaputil.py:8-20) | Oldest-first listing of `snap-*` directories under a backup root | Reused by `run` (to find the previous snapshot), `list`, and `prune`. Its prefix filter (line 18) is load-bearing for this design: in-progress runs live in `.tmp-snap-*` directories, which it ignores — so no reader can ever list an incomplete snapshot. |
| `snaputil.prune_snapshots` (snaputil.py:23-36) | Delete all but the newest `keep` snapshots, oldest first | Reused inside `prune`, wrapped in the exclusive lock (§5) and clamped `keep >= 1` (§7). |
| `snaputil.snapshot_disk_usage` (snaputil.py:39-51) | Recursive byte total of one snapshot | Reused by the `list` command. |
| `snaputil.safe_snapshot_path` (snaputil.py:54-63) | Maps an index relpath back inside the snapshot, normalizing `..` away | Reused by `restore`: every path copied back is resolved through it, so a tampered/corrupt index cannot make the restore write outside the snapshot. |
| `snaputil.is_stale` (snaputil.py:66-73) | mtime-based staleness heuristic | **Reviewed, deliberately unused.** It is the heuristic an O_EXCL-lockfile design would need to detect a dead writer's lock. This design does not need it: `flock` releases on process death (§5) and directory-rename commit (§5) replaces mtime sniffing entirely. |
| `test_synccli.py` (all, e.g. TestSync:35-51) | Locks in `synccli` behavior | `synccli.py` is not modified, so these tests keep passing unchanged; `backupctl` gets its own suite (§11). |

## 3. On-disk layout

```
<backup_root>/
  lock                          # empty file, fcntl.flock target (never deleted)
  snap-20261116-223000-07/      # a COMMITTED snapshot (atomic rename, §5)
    index.json                  # committed only after all files are in place
    <mirrored source tree>      # every file of every configured dir, merged
  .tmp-snap-20261116-223000-08/ # an IN-PROGRESS run (invisible to list_snapshots)
```

`index.json` schema:

```json
{
  "schema": 1,
  "started_utc": "...", "finished_utc": "...",
  "files":   { "dir1/rel/path": {"size": 123, "mtime_ns": 169...} },
  "missing": [ {"dir": "dir2", "path": "rel/path", "error": "vanished"} ]
}
```

Invariant the index carries: **`files` contains exactly the paths that exist
in the snapshot directory** — a vanished or unreadable source is recorded in
`missing`, never in `files`. A reader can therefore trust `files` as "these
bytes are present and were complete at commit time".

### Why hardlinks instead of a blob store

Each new snapshot **copies changed files** and **hardlinks unchanged files
from the previous committed snapshot**. Dedup across snapshots comes free,
no reference-counted GC: deleting snapshot S (`rmtree`) only unlinks S's
own directory entries; every other snapshot's hardlinks keep the data alive.
Constraint stated: the backup root must be on one local filesystem (hardlink
requirement) — acceptable for the evals workflow, checked at startup.

## 4. Run pipeline (`backupctl run`)

1. **Lock.** `flock(LOCK_EX)` on `<backup_root>/lock`. Concurrent run (the
   scheduler vs. a person, or two schedulers): the second fails fast with a
   clear message by default, or waits with `--lock wait`. No stale-lock
   recovery is ever needed — the kernel drops `flock` when the holder dies.
2. **Sweep.** `synccli.collect_stale` over leftover `.tmp-snap-*` directories
   (§2); `rmtree` each; report every discarded one (`"discarded incomplete
   snapshot .tmp-snap-… from a dead run"`). Under the exclusive lock no live
   writer exists, so nothing in-flight can be caught.
3. **Load previous index.** Take the newest name from
   `snaputil.list_snapshots`; parse its `index.json`. Corrupt/absent index →
   recovery, §6.
4. **Scan + decide.** For each configured dir: `synccli.build_manifest`
   (reused), then `synccli.changed_files(prev_index_files, new_manifest)`
   (reused) → the copy set. Everything else is unchanged → hardlink from the
   previous snapshot (resolved with `snaputil.safe_snapshot_path` on the
   *previous* snapshot so index entries can never escape it).
5. **Write.** Into `.tmp-snap-<ts>-<seq>/`: copy changed files (§8 copy
   semantics), hardlink unchanged ones, mkdir parents. A file that vanishes
   or is unreadable: §7.
6. **Commit.** Write `index.json.tmp` in the tmp dir → flush → `os.fsync` →
   rename to `index.json` (atomic: readers see all of it or none) → fsync
   the tmp dir → rename `.tmp-snap-…` to `snap-…` (atomic directory rename)
   → fsync the backup root. Only now does `snaputil.list_snapshots` see it.
   Files are **not** individually fsynced: a crash mid-run discards the whole
   tmp dir anyway (§6), so per-file fsync buys nothing.
7. **Report.** One line to stdout: counts of copied / hardlinked / missing
   files, per-dir; exit code 0, or 3 if any file went missing (§7), the same
   either way for scheduler and human.

## 5. Concurrency matrix

| | run | prune | restore | reader (human/next run) |
|---|---|---|---|---|
| **run** | serialized by `LOCK_EX` | serialized | **concurrent, safe** | safe |
| **prune** | serialized | serialized | serialized by `LOCK_SH` | safe |
| **restore** | concurrent | serialized | concurrent | safe |

- `run` vs `restore`: a run only *adds* (writes into its private tmp dir,
  renames once at the end); it never mutates a committed snapshot, so a
  restore reading an older snapshot is untouched. No shared lock needed.
- `restore` vs `prune`: restore holds `flock(LOCK_SH)` on the same lock file
  for the whole copy-back; prune's `LOCK_EX` waits. A killed restore drops
  the lock automatically — retention can never be wedged by a dead reader.
- Readers that don't take the lock (a human with `ls`) are still safe because
  of the commit protocol: an incomplete snapshot is invisible
  (`.tmp-snap-*` prefix ignored by `snaputil.list_snapshots`, snaputil.py:18).

## 6. Crash recovery — what is discarded, re-derived, reported

**Dead run leaves a tmp dir.** Discarded wholesale by the sweep (§4 step 2);
nothing inside it is ever readable as a snapshot. Re-derived: everything —
the next run starts from the last *committed* snapshot. Reported: one line
per discarded tmp dir.

**Corrupt or half-written previous index** (bit rot, disk truncation — the
commit protocol makes *self-inflicted* half-writes impossible, since
`index.json` only ever appears via atomic rename):
- **Discarded:** the corrupt index as change-detection input. The snapshot
  that owns it is left in place (it may still be the only usable backup;
  deletion is the user's call, flagged in the report).
- **Re-derived from the tree:** a fresh manifest via
  `synccli.build_manifest` with *no* previous state — i.e. the next run does
  a full copy of all F files. Correct but slow; that is the deliberate
  trade.
- **Reported:** `WARNING: index of snap-… unreadable (<err>); falling back
  to full backup` on stderr, plus a `degraded: true` field in the run
  summary. Exit code stays 0 — the run itself succeeded.

## 7. Retention and safe deletion

Policy: keep the newest `keep` snapshots (config, default 20), delete older
ones — reusing `snaputil.prune_snapshots` (snaputil.py:23-36), which already
orders oldest-first and never touches the newest. Two design rules on top:

1. **Clamp `keep >= 1`.** `prune_snapshots` with `keep=0` would delete every
   snapshot (lines 31-35 only stop at `len(names) <= keep`). The design
   never lets the last usable snapshot be deleted — "deletion must never
   leave the user without a usable snapshot."
2. **Prune under `LOCK_EX`.** `prune_snapshots` calls `shutil.rmtree`
   (line 35) with no reader awareness; unlinking files out from under a
   reading restore would hand it `ENOENT` mid-read. The exclusive lock
   (§5) closes exactly that window. This is an explicit override of how the
   bare function may be called — the function itself is unchanged.

Deletion is also only ever *started* after step 6 of a run committed a new
snapshot, so the set "newest committed snapshot exists" is an invariant.

## 8. Change detection and file copying — overrides named

**Granularity: `(size, mtime_ns)` per relative path.** "Unchanged" = same
relpath, same size, same `mtime_ns` as the previous snapshot's index.

- **Override 1 — `synccli.file_state` (synccli.py:22-25):** it returns
  `st_mtime` as a float, which round-trips through `JSON.dump/load`
  imprecisely and can produce phantom "changed" verdicts. `backupctl`'s
  state builder uses `st.st_mtime_ns` (integer, exact through JSON).
  Reason: the index is the persistent half of every comparison.
- **What this granularity can miss:** an edit that restores both the file's
  size and its nanosecond mtime — in practice: a same-length in-place write
  followed by `touch -r`, or an mtime set backwards. In that case the new
  snapshot hardlinks the *old* content, so the miss persists across
  snapshots. Escape hatch: `backupctl run --full-verify` hashes every file
  (sha256, chunked) instead of trusting the stat pair, at the cost of one
  full read pass. The default accepts the stat granularity; this paragraph
  is the stated limitation.
- **Override 2 — `synccli.copy_file` (synccli.py:62-69):** two defects for
  this job. (a) Line 67 (`fdst.write(fsrc.read())`) reads the entire source
  file into memory — a multi-GB eval artifact would spike RSS by its own
  size. `backupctl` copies in fixed 1 MiB chunks. (b) Lines 68-69
  (`except OSError: pass`) fail *silently and invisibly*; the manifest then
  records state for a file whose bytes never landed — exactly the
  "index promises files the snapshot does not contain" failure the brief
  forbids. `backupctl`'s copy reports every `OSError` (§7 of the schema:
  the entry goes to `missing`, never to `files`) — identical behavior
  whether the run was scheduler- or human-triggered, because it is the same
  code path.

**Missing/unreadable source file semantics.** A file that vanishes between
listing (`synccli.scan_files`) and copying, or raises `EACCES`/`EIO` when
opened: this snapshot simply does not contain it; the index names it in
`missing` with the errno string; the run summary counts it and exits 3
(still a usable snapshot — a missing file is data loss at the *source*,
not a failed backup). The next run re-attempts it naturally: absence from
the previous `files` map means `synccli.changed_files` classifies it as new
if it reappears.

## 9. Performance budget — first full backup of a ~1 GB / ~40k-file tree

**Budget: ≤ 3 minutes.** Derivation from measurements taken on this machine
(APFS, this directory, tree of 20,040 files / 124.8 MB — 20,000 × 2 KB files
plus 40 × 2 MB files, built and timed with a script against the actual
`synccli`/`snaputil` code):

| Phase | Measured | Source |
|---|---|---|
| scan + stat (`synccli.build_manifest`) | 38,296 files/s (0.52 s for 20,040) | measured |
| copy all files | 23.6 MB/s via `synccli.copy_file`; 16 MB/s via `shutil.copyfile` (5.28 s / 7.83 s for 124.8 MB) | measured |
| (blob-store alternative: sha256) | 82 MB/s | measured — **not needed**: the hardlink design hashes nothing on any run |

For 1 GB / ~40,000 files: scan ≈ 40,000 / 38,296 ≈ 1.0 s; copy ≈ 1024 MB /
(16–24 MB/s) ≈ 43–64 s (per-file open overhead dominates the small-file
half, bulk bandwidth the large-file half; the measured spread brackets both);
index write + two renames + fsyncs ≈ 1 s. Derived total ≈ **45–66 s**; the
budget is 3 minutes ≈ 3× headroom for slower disks and colder caches.

Only the *first* run pays it (subsequent runs copy only the changed set,
§10). The number comes from the two measured throughputs above, not a guess;
the measurement scripts used the actual `synccli.copy_file` /
`synccli.build_manifest` code paths.

## 10. What grows with what — explicit bounds

N = configured directories, F = total files across all dirs,
B = total bytes, C = changed files/bytes since last snapshot, K = retention.

- **Per-run scan work:** one walk over every dir = **O(F)** files, i.e.
  ≈ F / 38,296 s measured; independent of N except that N is the number of
  walk roots (adding a directory adds its files to F, nothing else). Config
  parse and lock acquisition are **O(1) / flat**.
- **Per-run copy work:** **O(C)** — only files whose `(size, mtime_ns)`
  changed are copied; the rest are hardlinked. Copy time ≈
  changed_bytes / (16–24 MB/s) measured. For the expected steady state
  (evals append a few results per run) C ≪ F.
- **Memory:** the in-memory index holds one entry per file: **≈ 150 B × F**
  (relpath + two integers in a dict). 100k files ≈ 15 MB; 1M files ≈ 150 MB —
  the stated ceiling before an on-disk index format would be needed.
  Copying is streamed (§8): memory is flat in B.
- **Disk:** first run ≈ **B**. Each later run adds ≈ **ΔB** (changed bytes;
  hardlinked unchanged files cost ~nothing). Retention caps the store at
  **≤ K × B** worst case (every snapshot rewrites everything), typically
  B + K × ΔB. `prune` runs after each commit, so the bound is enforced
  every run.
- **Flat regardless of N, F, B:** one lock file, one sweep pass, one
  retention decision per run; the CLI's own startup cost.

Nothing is superlinear in N; the only N-coupled serial cost is that all
directories share one lock and one run (per-run time is the *sum* over
dirs). Parallelizing across directories is a deliberate non-goal while N is
"a handful to a few dozen".

## 11. Testing strategy (new `test_backupctl.py`)

Same style as `test_synccli.py` (stdlib `unittest`, tmpdirs). Cases mapped
to the sections above: two concurrent `run`s → one winner, one clean failure
(§5); killed run (`SIGKILL` mid-copy) leaves only a `.tmp-snap-*`, next run
sweeps it and succeeds (§6); truncated previous `index.json` → warning +
full re-copy (§6); vanished source file between listing and copy (patched
`os.stat`/`open`) → in `missing`, exit 3 (§8); `--keep 0` clamps to keeping
the newest (§7); restore while a run is mid-flight reads the previous
snapshot completely (§5); `prune_snapshots` reuse verified against
`snaputil`'s own ordering contract; unchanged-tree second run hardlinks
(`os.stat` st_nlink check) and copies nothing.

## 12. Summary of overrides to existing behavior

| Override | Where | Why |
|---|---|---|
| `file_state` mtime float → `mtime_ns` int | synccli.py:22-25 | exact JSON round-trip; the index is persistent state |
| `copy_file` whole-file read → chunked 1 MiB copy | synccli.py:66-67 | memory must be flat in file size |
| `copy_file` silent `except OSError: pass` → record + report | synccli.py:68-69 | index must never promise bytes that aren't there |
| bare `prune_snapshots(keep)` call → clamp `keep >= 1` + `LOCK_EX` wrapper | snaputil.py:23-36 | never delete the last snapshot; never rmtree under a reader |
| `is_stale` mtime heuristic not carried over | snaputil.py:66-73 | `flock` + atomic rename replace mtime sniffing |

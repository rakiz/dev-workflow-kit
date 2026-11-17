# DESIGN-d1 — `backupctl`

Design for a command-line backup tool that covers a configured set of source
directories and produces point-in-time snapshots under a backup root, built on
the code already in this directory (`synccli.py`, `snaputil.py`).

---

## 1. Goals and non-goals

`backupctl` snapshots N configured source directories into a backup root.
A run may be started by a scheduler or by a person, at any time, possibly
concurrently; a restore (separate tooling) may read a snapshot at any time;
and the process may be killed at any point. The design must guarantee:

1. A snapshot a reader can see is always complete and self-consistent — never a
   mix of two runs, never an index promising files the snapshot lacks.
2. Two concurrent runs, or a run concurrent with a restore or a retention
   delete, cannot corrupt a snapshot or each other.
3. An interrupted run leaves nothing a later reader can mistake for a complete
   snapshot, and the next run proceeds with no manual cleanup.
4. A source file that vanishes or is unreadable yields a defined snapshot
   content and a defined report, independent of who triggered the run.
5. Retention deletes old snapshots without ever leaving the user without a
   usable snapshot and without breaking a concurrent reader.
6. Unchanged files are not re-copied on later runs; the granularity of
   "unchanged" and its blind spots are stated.
7. The initial full backup of a ~1 GB / tens-of-thousands-of-files tree has a
   stated, derived performance budget.
8. Every cost claim is an explicit bound in terms of N (directories), F
   (files), B (bytes), S (snapshots retained).

Non-goals: encryption, remote/object-store targets, network filesystems
(the locking model assumes a local POSIX filesystem), Windows, and a full
backup *catalog* UI. Restore is out of scope but its contract against
concurrent writes is defined (§8).

---

## 2. Grounding — what exists, what we reuse, what we override

All references below are to files in this directory and were verified against
their current contents.

### 2.1 Reused as-is

| Existing artifact | File:lines | How `backupctl` uses it |
|---|---|---|
| `scan_files(root)` — sorted relative paths, skips dot-*directories* | `synccli.py:10-19` | Enumerate a source tree before stat-ing it. |
| `file_state(path)` — `{"size", "mtime"}` | `synccli.py:22-25` | The per-file identity used for change detection and stored in the index. |
| `build_manifest(root)` — `{relpath: state}` | `synccli.py:28-33` | Build the new candidate manifest of a source (wrapped, see §2.2). |
| `changed_files(old, new)` — new + changed rels | `synccli.py:36-42` | Decide which files must be copied vs. re-linked. |
| `list_snapshots(root)` — `snap-*` dirs, oldest first | `snaputil.py:8-20` | Enumerate committed snapshots; also the reason staging dirs must not be named `snap-*`. |
| `prune_snapshots(root, keep)` — delete oldest, keep newest | `snaputil.py:23-36` | Retention, wrapped by the safe-delete protocol (§7). |
| `snapshot_disk_usage(root, name)` — recursive byte sum | `snaputil.py:39-51` | Report snapshot size; input to a size-based retention cap. |
| `safe_snapshot_path(root, name, rel)` — `..`-safe join | `snaputil.py:54-63` | The path contract a restore uses to read files; keeps a stored path inside its snapshot. |
| `is_stale(dir, ref_epoch)` — `mtime <= ref` | `snaputil.py:66-73` | Age predicate used when sweeping abandoned staging dirs. |

The snapshot name format is dictated by `list_snapshots`'s docstring
(`snaputil.py:11-14`): `snap-<date>-<time>-<seq>`. We emit
`snap-%Y%m%d-%H%M%S-%02d`. Because every field is zero-padded, the
lexicographic `sorted()` at `snaputil.py:20` is also chronological, so
"newest snapshot" is just the last element — no separate pointer file exists
to corrupt.

### 2.2 Overridden, with the exact existing behavior named

Each override names the function and lines it replaces and why.

**(a) In-place, non-atomic manifest write.**
`synccli.sync` writes the manifest with a direct `open(..., "w")` +
`json.dump` (`synccli.py:85-86`). A crash mid-write leaves a truncated
`.sync_manifest.json`, and the next `json.load` (`synccli.py:78-79`) raises —
this is precisely the "half-written index left behind by a dead run" the brief
names. **Override:** never write the index in place. Write it to a sibling
`*.tmp` and `os.replace()` it into position, inside a staging directory that is
itself only made visible by a final atomic `os.rename` (§3). A truncated index
can then only ever exist as a `.tmp` inside an invisible staging dir.

**(b) `copy_file` reads the whole file and swallows errors, leaving partial
output.** `synccli.copy_file` (`synccli.py:62-69`) does
`fdst.write(fsrc.read())` — the entire file in memory — and on any `OSError`
passes silently (`synccli.py:68-69`). If the read fails partway, a **truncated
destination file is left behind** and the caller is told nothing, so the
manifest could later claim a file whose bytes are wrong. **Override:** copy in
1 MiB chunks (bounded memory, §10) to `dst.tmp`, then `os.replace` to `dst`; a
failure removes the temp and is reported to the caller rather than swallowed.
The whole-file read also bounds memory by the largest file, which §10 must not
allow.

**(c) `build_manifest`/`file_state` crash on a vanished file.**
`build_manifest` calls `file_state` for every path returned by `scan_files`
(`synccli.py:30-32`), and `file_state` calls `os.stat`
(`synccli.py:24`). A file that disappears between listing and stat raises
`FileNotFoundError` out of `build_manifest` and aborts the run. **Override:**
stat each file under `try/except OSError`, skip and record failures (§6), so a
vanishing source degrades the snapshot instead of killing the run.

**(d) `prune_snapshots` deletes in place with `shutil.rmtree`.**
`snaputil.prune_snapshots` removes the oldest directories directly
(`snaputil.py:35`). A restore that has listed `snap-X` but not yet opened a
file can lose that file mid-restore. **Override:** rename `snap-X` to a
dot-prefixed `.trash-*` name first (atomic, and invisible to
`list_snapshots`, which only matches `snap-`, `snaputil.py:18`), then delete
the trash dir (§7). Readers that already hold open file descriptors keep valid
inodes across the unlink; readers that re-list never see the trashed name.

**(e) No deletion detection.** `changed_files` returns only new and modified
files (`synccli.py:40`); it never reports files present in the old manifest but
absent now. **Override:** the run additionally computes
`old_keys - new_keys` for reporting deletions. This is additive; we still call
`changed_files` for the copy set.

**(f) `collect_stale` is not used.** `synccli.collect_stale`
(`synccli.py:45-59`) filters a `(path, fresh)` list against a `seen` set. The
run's "what still needs action" bookkeeping is a plain set difference over
manifest keys, which is clearer and equivalent; we do not adopt `collect_stale`
and say so rather than silently ignoring it.

---

## 3. On-disk layout and the snapshot commit protocol

```
<backup_root>/
  .backupctl.lock                 # flock target, never removed
  .staging-<utc>-<pid>-<rand>/    # in-progress snapshot (invisible to readers)
  .trash-<snapshot>-<rand>/       # snapshot being deleted
  snap-20261116-120000-00/        # a committed snapshot
      .backup_index.json          # written last, atomically; presence == complete
      <source_id>/                # one subtree per configured source
          <relative path>/...
  snap-20261116-130000-00/
```

`list_snapshots` (`snaputil.py:8-20`) sees only `snap-*` directories. Verified
by measurement: with 200 `snap-*` and 200 `.staging-*` entries in one root,
`list_snapshots` returned exactly the 200 `snap-*` names
(Appendix A, `list_snapshots`). Staging and trash are therefore invisible by
construction, not by convention.

**Commit protocol (per run):**

1. Acquire the global lock (§4). If held, apply the concurrency policy.
2. Sweep leftovers from dead runs (§5).
3. Choose the previous baseline per source (§6.1) and build the new manifest.
4. Create `.staging-<id>/`; for each file: hard-link from the previous
   snapshot if unchanged, else copy (chunked, temp+rename). Track failures.
5. Build the index from the files that actually landed (never from the source
   manifest alone), compute its checksum, write it to
   `.staging-<id>/.backup_index.json.tmp`, `fsync` it, `os.replace` it to
   `.backup_index.json`, `fsync` the staging dir.
6. `os.rename(.staging-<id>, snap-<name>)` — **the single atomic commit**. The
   snapshot becomes visible only at this instant, fully formed.
7. Run retention (§7). Release the lock.

Because step 6 is one `rename(2)` on the same filesystem, a reader either sees
no snapshot or sees the complete one; there is no in-between. Because the index
is created by `os.replace` at step 5, a half-written index cannot exist under
the committed name at all.

### 3.1 Index schema

```json
{
  "schema": 1,
  "snapshot": "snap-20261116-120000-00",
  "created_epoch": 1763300000.0,
  "sources": ["evals", "results"],
  "files": { "evals/run/out.json": {"size": 1234, "mtime": 1763299999.5}, ... },
  "warnings": [ {"kind": "vanished", "path": "results/tmp/x"} ],
  "checksum": "<sha256 over canonical json of files>"
}
```

`files` is exactly the `{relpath: {"size","mtime"}}` shape `build_manifest`
produces (`synccli.py:33`) and the shape `changed_files` consumes
(`synccli.py:39`), so change detection is
`changed_files(prev["files"], new_manifest)` with no translation. Keys are
`<source_id>/<relpath>` so one snapshot can cover all sources while keeping
per-source change detection.

---

## 4. Concurrency

**One global lock, `flock` on `<backup_root>/.backupctl.lock`.** All snapshot
creation *and* all retention deletion happen under it, so run-vs-run and
run-vs-prune are fully serialized. `flock` is released by the kernel when the
process dies, so a killed run never leaves a stuck lock — this is the mechanism
that makes "the next run makes progress without manual cleanup" true for the
lock itself. The lock file is never deleted (deleting it would defeat the lock
via inode replacement).

Policy when the lock is busy (the brief's "timings can collide"):

- Default: fail fast, print `another backupctl run is in progress`, exit 3.
  No partial work is started. This is the safest collision outcome.
- `--wait SECONDS`: block up to the timeout, then fail with exit 3. Lets a
  scheduler retry without a thundering herd.

Restores do not take the lock (they are separate, read-only tooling). They are
protected instead by the commit protocol (they only see committed snapshots)
and the trash-rename delete (§7).

Assumption: `backup_root` is a local POSIX filesystem where `flock`,
`rename(2)`, and hard links are reliable. Network filesystems are a stated
non-goal (§1).

---

## 5. Crash safety and recovery

**Nothing to mistake for complete.** A killed run can leave at most a
`.staging-*` directory, which `list_snapshots` cannot see (§3). A committed
`snap-*` directory is always complete, because commit is the atomic rename at
step 6 after the index was already placed at step 5.

**Leftover sweep (automatic, no manual cleanup).** Holding the lock, every
`.staging-*` and `.trash-*` directory present is by definition abandoned: no
live run can hold the lock and also own a staging dir. At run start the run
renames each to `.trash-*` and `rmtree`s it (same reader-safe pattern as §7),
and reports the count. `is_stale` (`snaputil.py:66-73`) is available as an
age-based predicate if a sweep is ever run outside the lock; under the lock it
is unnecessary. The same sweep runs at the end of a successful run so a run
that itself dies leaves at most one staging dir for the next run to clear.

**Index validation and recovery.** At run start (under the lock) the run
validates every committed snapshot's index: it must parse as JSON, carry
`schema == 1`, and have a `checksum` matching a recomputation over `files`
(canonical `json.dumps(files, sort_keys=True, separators=(",", ":"))`). Then:

- **Valid index** → nothing to do.
- **Missing or corrupt index, tree present and complete** → the index is
  *re-derived from the snapshot tree*: `scan_files` (`synccli.py:10-19`) walks
  the snapshot, `file_state` (`synccli.py:22-25`) stats each file, and a fresh
  index is written with `os.replace`. Note the override detail: `scan_files`
  skips dot-*directories* but not dot-*files* (`synccli.py:14`), so the walk
  must also exclude `.backup_index.json` itself. Report
  `recovered index for snap-X`. Nothing is discarded.
- **Index unreadable and tree empty/partial** → the snapshot is
  *quarantined*: renamed to `.incomplete-<name>` (again invisible to
  `list_snapshots`) and reported. Data is never deleted on a suspicion; it is
  only removed from the visible set. Report `quarantined snap-X (index
  unreadable, tree incomplete)`.

**What is discarded:** abandoned `.staging-*`/`.trash-*` dirs (their partial
contents), and, only when the tree itself is unusable, the snapshot's
*visibility* (quarantine), not its bytes. **What is re-derived:** a snapshot's
index, from the snapshot's own tree. **What is reported:** each sweep count,
each recovered index, each quarantine.

Because commit is atomic, the corrupt-index path is a defense against
post-commit corruption (bit rot, external interference, an older layout), not
against our own crashes — our crashes only ever leave invisible staging.

---

## 6. Change detection, incremental runs, and vanished sources

### 6.1 Baseline selection

The baseline for a source is the **most recent prior committed snapshot whose
index lists that source** (per §3.1 keys). This makes partial runs
(`--source NAME`) correct: a source's "unchanged" comparison always uses the
last snapshot that actually contained it, regardless of interleaving.

### 6.2 Granularity of "unchanged" and its blind spots

"Unchanged" is decided **per file**, on the pair `(size, mtime)` returned by
`file_state` (`synccli.py:22-25`), compared with `changed_files`
(`synccli.py:36-42`). Unchanged files are **hard-linked** from the previous
snapshot's inode into the new snapshot (falling back to a copy if the link
fails); changed/new files are copied.

This granularity **misses**:

- A content change that keeps both size and mtime — e.g. `cp -p`, `rsync -t`,
  `touch -r`, a VCS checkout that restores mtimes, or a same-size in-place edit
  whose mtime is reset. The snapshot then silently re-links stale content.
- Mode/owner/xattr-only changes: `file_state` returns only size and mtime
  (`synccli.py:25`), so a chmod-only change is invisible (we do not back up
  permissions anyway).
- Sub-mtime-resolution edits on filesystems whose mtime granularity is coarser
  than the edit rate. On APFS `st_mtime` carries sub-second precision, so this
  is not a practical concern here.

Mitigation: an optional `--checksum` mode hashes every file and decides on
content instead of `(size, mtime)`. Measured cost: SHA-256 over 1 GiB took
0.495 s (~2.0 GB/s) on this machine (Appendix A), so verifying a 1 GB tree
adds ~0.5 s — affordable as an opt-in, not as the default.

### 6.3 A source file disappears or is unreadable

- **Vanishes between scan and stat:** `build_manifest` is called per file under
  `try/except OSError` (override (c)); the file is skipped and recorded.
- **Vanishes or is unreadable when the copy reaches it:** the overridden copy
  (override (b)) removes its temp and reports failure.

In both cases the file is **simply absent from the snapshot** (never a
zero-byte or truncated placeholder), the index lists exactly the files that
landed, and the file is recorded in `warnings` with `kind` `vanished` or
`unreadable`. The snapshot is still complete and self-consistent — the index
matches the tree — and the run exits 4 (partial) so a scheduler sees the
condition. **The behavior is identical whether the run was triggered by the
scheduler or a person**; only the exit status and the report differ, never an
interactive prompt.

---

## 7. Retention and safe deletion

Policy (configurable; default `keep = 7`):

- Retain the newest K committed snapshots. Newer-than-oldest selection uses
  `list_snapshots` (`snaputil.py:8-20`), which is already chronological.
- Never delete the newest snapshot; `prune_snapshots` already guarantees this
  (`snaputil.py:32-33`), and the run additionally never deletes the snapshot it
  just committed.
- Always keep at least 1 snapshot (a prune with K < 1 is clamped to 1).
- A snapshot containing a `.keep` marker file is exempt (pinning for a restore
  in progress).
- Optional size cap via `snapshot_disk_usage` (`snaputil.py:39-51`) if a byte
  budget is configured.

Safe deletion (override (d)) — for each doomed name, in order:

1. `os.rename(snap-X, .trash-<snap-X>-<rand>)` — atomic and invisible to
   `list_snapshots`, so no new reader can find it.
2. `shutil.rmtree(.trash-...)` — a reader that already opened files keeps
   valid inodes (POSIX unlink semantics); the data dies only when the last
   descriptor closes.
3. `fsync` the backup root.

Because unchanged files are hard-linked across snapshots, deleting an old
snapshot only unlinks directory entries; every inode still referenced by a
newer snapshot survives, so pruning can never break a retained snapshot.

---

## 8. Reader contract (restore and humans)

A reader treats a snapshot as complete iff it is a `snap-*` directory
containing a valid index (§5). It never needs to ask whether the producing run
finished, because visibility *is* completion (§3). Paths are resolved with
`safe_snapshot_path` (`snaputil.py:54-63`), which normalizes `..` so a stored
path cannot escape its snapshot. If a restore is reading a snapshot that is
pruned mid-read, files already opened stay readable; files not yet opened may
be gone, and the restore reports that — which is why the design prunes oldest
first and offers `.keep` pinning.

---

## 9. Reporting and exit codes

The run prints a summary: sources covered, files total, files copied, files
re-linked (unchanged), bytes copied, deleted-from-source count, vanished/
unreadable warnings, staging dirs swept, indexes recovered, snapshots
quarantined, snapshots pruned. Exit codes: `0` clean; `3` another run holds
the lock; `4` completed but partial (vanished/unreadable source files); `1`
fatal (config error, unreadable root, commit failure). The report and codes
are the same for scheduler and human; nothing is interactive.

---

## 10. Scaling bounds — what grows with what

Notation: N = configured sources; F = total files across sources at run time;
B = total bytes; S = snapshots retained; C_f/C_b = files/bytes changed since the
baseline. Measured constants (this machine, APFS, Python 3.10.11; Appendix A):
R_stat ≈ 4.0×10⁴ stats/s; r_copy ≈ 2.6–3.0×10³ files/s; BW_copy ≈ 130–150 MB/s;
memory ≈ 440 B/file for the manifest dict; index ≈ 65 B/file on disk;
copy buffer = 1 MiB.

| Quantity | Bound | Notes |
|---|---|---|
| Per-run wall-clock | `F / R_stat + max(C_f / r_copy, C_b / BW_copy)` | Initial run C = F, B. |
| Per-run memory | `O(F)` ≈ `440 B × F` (+ `O(1 MiB)` copy buffer) | Independent of N and S. |
| Disk, initial snapshot | `B + 65 B × F` | Data + index. |
| Disk, each later snapshot | `C_b + 65 B × F + O(F)` link metadata | Unchanged bytes are shared via hard links; only changed bytes are written. |
| Disk, total with retention | `B + Σ_runs C_b + S × 65 B × F`, `S ≤ K` | "Only ever grows" is bounded by change volume + K indexes, not by `B` per run. |
| Open file descriptors | `O(1)` | One file at a time, chunked. |
| Lock acquisitions / live staging dirs | `1` / `≤ 1` | Flat. |
| Retention decision | `O(S log S)` | Flat w.r.t. F. |
| Config/dir setup | `O(N)` | Total work is `O(F)` because F already sums all sources. |

**Grows with:** F (per-run work and memory), C_b (disk growth per run), S (up to
K indexes). **Stays flat:** copy buffer, fd count, lock/staging count, and
retention bookkeeping — none depends on F or B. Adding directories (N) adds
only `O(N)` setup; it does not change the shape of any bound, because all
per-file work is already summed in F. Concretely: going from 3 to 30 sources
multiplies F by at most 10 and nothing else; memory and per-run time scale with
F, while buffer, descriptors, and bookkeeping are unchanged.

---

## 11. Initial full-backup performance budget

**Budget: ≤ 30 s wall-clock for B = 1 GB, F = 20,000 on this machine class**,
with the derivation below.

`T_full = F/R_stat + max(F/r_copy, B/BW_copy) + index_write`

- scan/stat: `20,000 / 40,000 ≈ 0.50 s` (measured `build_manifest` 0.49–0.53 s).
- copy: `max(20,000 / 2,600, 1,000 / 130) = max(7.7 s, 7.7 s) ≈ 7.7 s`
  (measured copy loop 6.7–8.4 s).
- index write: ~0.02 s (`json.dumps` of a 1.29 MB manifest measured 0.012 s;
  `os.replace` is a metadata op).
- **Total ≈ 8.2 s measured**; the 30 s budget leaves ≈ 3.5× headroom for a cold
  page cache, slower media, or an external scanner.

The copy phase is file-count-bound, not bandwidth-bound, at this size (2.6k
files/s ≈ 130 MB/s of 50 KB files, versus the ~5 GB/s page-cache write
baseline), so the honest scaling term is files-per-second; larger files move
the bottleneck to `B / BW_copy`. A parallel copy would lower the constant but
is not required to meet the budget.

**Incremental runs.** All-unchanged F = 20,000: `0.50 s` stat + hard-link pass.
Measured hard-link creation was ~2.5k links/s — i.e. on APFS a re-link is *not*
faster in wall-clock than the ~3.0k files/s copy (Appendix A). The incremental
win is therefore **disk, not time**: unchanged bytes are never rewritten, so
per-run disk growth is `C_b` (≈ 0 when nothing changed) instead of `B`. This is
stated explicitly because it is counter-intuitive and the brief asks for real
numbers.

---

## 12. Configuration

A small JSON config at `<backup_root>/.backupctl.json` (or `--config`):

```json
{
  "backup_root": "/srv/backups",
  "sources": {"evals": "/srv/evals", "results": "/srv/results"},
  "retention": {"keep": 7, "max_bytes": null},
  "lock_timeout": 0
}
```

`source_id` is the config key; it names the subtree inside each snapshot
(`<snap>/<source_id>/...`) and prefixes index keys. Directory-vs-file sources
and path validation reuse `safe_snapshot_path` semantics for reads.

---

## 13. Test plan

Extend `test_synccli.py` style (plain `unittest`, tempdirs):

- **Atomicity:** kill a run mid-copy (inject a fault after step 4); assert no
  `snap-*` appears, a `.staging-*` exists, the next run sweeps it, and the next
  snapshot is complete.
- **Index recovery:** delete/truncate a committed index; assert the next run
  re-derives it and the snapshot stays valid; empty the tree and assert
  quarantine.
- **Concurrency:** two processes race the lock; assert exactly one builds and
  the other exits 3.
- **Vanished source:** remove a file between `scan_files` and copy; assert it
  is absent, warned, exit 4, and the index matches the tree.
- **Incremental:** snapshot, touch nothing, snapshot again; assert zero copies
  and hard-linked inodes (`st_ino` equality across snapshots).
- **Granularity miss:** same-size edit with restored mtime; assert the run
  reports unchanged (documenting the miss) and that `--checksum` catches it.
- **Safe delete:** open a file in `snap-X`, prune it, assert the open
  descriptor still reads correct bytes and `list_snapshots` no longer shows it.

---

## Appendix A — measurements

Machine: Apple M-series, macOS (Darwin 24.6.0), APFS, Python 3.10.11.
Tree: 20,000 files × 50 KB = 1,000.0 MB across 40 directories.

```
scan_files:                     0.120 s   (166,373 files/s)
build_manifest (stat all):      0.485 s   ( 41,252 files/s)
copy_file loop (existing):      7.652 s   (130.7 MB/s, 2,614 files/s)
write 256 MB (page cache):      0.050 s   (5,105 MB/s)
```

```
build_manifest dict RSS delta:  8.86 MB   (20,000 files -> ~443 B/file)
os.link loop (with makedirs):   9.769 s   (2,047 links/s)
os.link (dirs pre-made):        8.072 s   (2,478 links/s)
copy_file (dirs pre-made):      6.709 s   (2,981 files/s)
chunked temp+rename:            8.438 s   (2,370 files/s)
cp -c clone (subprocess):     128.895 s   (  155 files/s)
changed_files identical:        0.001 s
json dumps / loads (1.29 MB):   0.012 s / 0.008 s
list_snapshots (200 snap + 200 .staging): 0.0004 s, returned 200
sha256 1 GiB:                   0.495 s   (2,068 MB/s)
```

Method: generated the tree with `os.urandom` payloads, imported `synccli` and
called `scan_files`, `build_manifest`, `copy_file`, and `changed_files`
directly; hard-link, chunked-copy, and clone variants measured separately;
`list_snapshots` run against a root populated with 200 `snap-*` and 200
`.staging-*` directories to confirm staging is invisible.

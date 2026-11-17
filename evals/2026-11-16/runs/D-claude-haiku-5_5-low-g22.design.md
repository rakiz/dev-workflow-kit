# DESIGN-d1: `backupctl`

Status: design only. No code written. Every claim about existing code was
checked by reading the file or by running it in this directory (Python 3.10.11,
macOS/APFS). Test suite: `python3 -m unittest` → 6 tests, all pass.

## 1. Summary

`backupctl` takes point-in-time snapshots of N configured directories under a
backup root. Each directory has its own subtree:

```
<backup_root>/<dir-id>/
    .lock                       advisory flock, one writer per directory
    snap-YYYYMMDD-HHMMSS-NN/    committed snapshot: complete, immutable
        MANIFEST.json           authoritative file list + per-file state + skips
        ...file tree...
    tmp-<run-id>/               in-flight run; invisible to readers; swept on start
    trash-<snap>/               snapshot being deleted; swept on start
    snap-....lock               per-snapshot flock; readers hold shared, prune exclusive
```

Core rules:

1. A snapshot becomes visible only by one `rename(tmp-<run>, snap-…)`. That
   rename is the commit point. Nothing else makes a snapshot visible.
2. Committed snapshots are never modified. Unchanged files are hardlinked from
   the previous snapshot; changed or new files are copied.
3. Writers take an exclusive flock per directory; readers take a shared flock
   per snapshot; prune takes an exclusive flock per snapshot. Locks are kernel
   advisory locks, so they are released automatically when a process dies.
4. Anything not in a committed `snap-*` dir with a valid `MANIFEST.json` is
   garbage and is removed at the start of the next run under the lock.

## 2. Grounding: what exists, what is reused, what is overridden

Verified by reading and running the code in this directory.

### 2.1 Reused as-is

| Artifact | Where | Used for |
|---|---|---|
| `snaputil.list_snapshots` | snaputil.py:8-20 | Lists `snap-*` dirs oldest first. It ignores `tmp-*` and `trash-*`, so in-flight and deleted snapshots are invisible to it. Names are fixed-width (`snap-YYYYMMDD-HHMMSS-NN`), so string sort = time order. |
| `synccli.scan_files` (with a new keyword, see 2.2) | synccli.py:10-19 | Sorted relative file listing via `os.walk`. |
| `synccli.changed_files` (extended, see 2.2) | synccli.py:36-42 | Compares old manifest entries with new ones to find files to copy. |
| `synccli.MANIFEST_NAME` | synccli.py:7 | Not reused as the file name; see 2.2 (`MANIFEST.json` is per snapshot). |

### 2.2 Overridden: behavior that must differ

Each override names the function, the current behavior (verified), and why it
must change.

1. **`synccli.copy_file`** (synccli.py:62-69). Current behavior: `fsrc.read()`
   loads the whole file into memory, and `except OSError: pass` swallows read
   errors silently. Verified: a 0-mode source leaves no destination and no
   error. Override: stream in 1 MiB chunks, compute SHA-256 while copying, and
   return a result (`ok`, `vanished`, `unreadable`, `changed_during_copy`) instead
   of swallowing errors. Reason: O(file size) memory is unacceptable for large
   result files, and silent skips are invisible to the reporter.

2. **`synccli.sync`** (synccli.py:72-87). Current behavior, verified: it
   records `src_manifest` for every file, including files `copy_file` skipped.
   Test: first run with an unreadable file copies nothing; after chmod, the
   second run returns `[]`, so the file is never retried, contrary to the
   comment at synccli.py:69 ("next pass will retry"). It also writes the manifest
   with a plain `open(..., "w")` (synccli.py:85-86), which is not atomic, and it
   has no concept of snapshots or deletion. Override: `backupctl` does not call
   `sync`. It builds a new snapshot. A file enters a new manifest only with a
   status of `ok`; skipped files are recorded under `skipped`, which triggers a
   retry next run.

3. **`synccli.changed_files`** (synccli.py:36-42). Current behavior: compares
   `(size, mtime)` only, and never reports deletions. Verified: a same-size
   edit with its mtime restored via `os.utime` is reported as unchanged. Override:
   the state tuple is `(size, mtime_ns, ctime_ns, inode)` (see section 5), and
   deletions are computed separately.

4. **`synccli.file_state`** (synccli.py:22-25). Current behavior: `st_mtime`
   as a float (precision loss) and `os.stat`, which follows symlinks. Override:
   `os.lstat`, integer `st_mtime_ns`/`st_ctime_ns`, and `st_ino`. Symlinks are
   recorded as skipped with reason `symlink` in v1 (see section 7).

5. **`synccli.build_manifest`** (synccli.py:28-33). Current behavior: calls
   `file_state` for every listed path, with no handling for a file that vanished
   between listing and stat. Verified by reading: `os.stat` raises
   `FileNotFoundError`, which is uncaught and crashes the run. Override: vanished
   files become `skipped` entries.

6. **`synccli.scan_files`** skips every directory whose name starts with `.`
   (synccli.py:14). For a backup that silently drops data. Override: add
   `include_hidden=True` as a keyword argument whose default keeps today's
   behavior. The existing test (test_synccli.py:17-18) still passes because it
   only checks `a.txt` and `sub/b.txt`.

7. **`synccli.collect_stale`** (synccli.py:45-59) is not reused. It is
   unused by `sync`, and it walks indices with `range(len(items))`. Nothing in
   the design depends on it.

8. **`snaputil.prune_snapshots`** (snaputil.py:23-36). Current behavior,
   verified by reading: `shutil.rmtree` directly on the snapshot path, with no
   lock, no check for a reader, and no check that another run is writing. A
   reader mid-restore loses files, and the directory is half-deleted if the
   process dies. Override: rename to `trash-<name>` under the directory lock and
   `rmtree` only after taking the snapshot's exclusive flock (section 6).
   Retention rules stay the same: keep the newest K.

9. **`snaputil.safe_snapshot_path`** (snaputil.py:54-63). **Defect, verified.**
   The docstring promises the result stays under the snapshot directory, but
   `os.path.normpath` does not remove leading `..` in a relative path, and
   `os.path.join` discards the prefix when the second argument is absolute.
   Results: `../../etc/passwd` → `/b/snap-x/../../etc/passwd`, and
   `/etc/passwd` → `/etc/passwd`. Override: reject absolute paths and any `..`
   component before joining, then check that `realpath` of the result is inside
   the snapshot directory. Restore uses only this checked version.

10. **`snaputil.snapshot_disk_usage`** (snaputil.py:39-51). Current behavior:
    sums `st_size` of every file, so it reports logical size and counts a
    hardlinked file once per snapshot. That overstates disk use. Override: a
    separate `unique_bytes` function that counts each `(st_dev, st_ino)` once.
    The existing function stays for logical size.

11. **`snaputil.is_stale`** (snaputil.py:66-73) is not reused. It tests the
    directory mtime, which changes when entries are added or removed but not when
    file contents change. It is unfit for "is this file unchanged".

## 3. Commit protocol

Run for directory `d` under the exclusive lock `<root>/<d>/.lock`:

1. Sweep: delete every `tmp-*` and `trash-*` entry under `<root>/<d>/`. This is
   recovery from a dead run (section 4). Take an exclusive flock on each
   `snap-*.lock` before deleting anything it protects. If the lock is held, the
   entry is a live reader's snapshot and not garbage. (Only `tmp-*` and
   `trash-*` are swept, so this is a no-op for committed snapshots.)
2. Choose the base: the newest `snap-*` whose `MANIFEST.json` parses and passes
   its checksum (section 4). It may be absent.
3. Create `tmp-<run-id>/` and write the new tree into it:
   - Walk the source with `scan_files(include_hidden=True)`. Per file: `lstat`.
     If the stat matches the base manifest entry (section 5), hardlink the file
     from the base snapshot's tree. Otherwise stream-copy it and hash it.
   - Each file is `fsync`ed after write. Each directory is `fsync`ed after its
     entries are written.
   - Vanished or unreadable files are recorded under `skipped` (section 7).
4. Write `tmp-<run-id>/MANIFEST.json` through `MANIFEST.json.part`: write,
   `fsync`, then `rename`. The manifest holds: `schema`, `dir_id`,
   `source_root`, `started_at`, `finished_at`, `base` (name or null), `files`
   (path → size, mtime_ns, ctime_ns, inode, sha256, status), `skipped` (path →
   reason), and `manifest_sha256` over the canonical JSON of the other fields.
5. `fsync` the tmp directory and the `<root>/<d>/` directory.
6. Commit: `rename(tmp-<run-id>, snap-<name>)`, then `fsync` `<root>/<d>/`.
   The name is the next run sequence number, as in snaputil's naming scheme.
7. Make the snapshot read-only (`chmod -R a-w`). This is advisory, to prevent
   accidents. Correctness does not depend on it, because hardlinked files share
   an inode and a write through one name would change every snapshot that
   links to it. Writers never open a committed file for writing.

Crash points: before step 6 leaves only `tmp-*`, which step 1 of the next run
removes. After step 6 the snapshot is complete, because the manifest was
written and synced before the rename. There is no intermediate visible state.

## 4. Crash recovery: corrupt or half-written index

- **Half-written manifest in a dead run.** It exists only under `tmp-*` and is
  removed by the next run's sweep (step 1). Nothing reads it.
- **Committed snapshot with an unreadable or mismatched manifest** (for example
  a disk fault after commit). The manifest is parsed and `manifest_sha256` is
  checked. On failure the snapshot is marked invalid, and this is what the run
  does:
  - It is not deleted automatically. Deletion would destroy evidence.
  - It is never used as a base for hardlinks.
  - The run chooses the next-newest valid snapshot as the base. If none is
    valid, the run does a full copy of the tree (no hardlinks).
  - The report lists the invalid snapshot name and reason, and the run exits
    with status 3 (section 8).
- **Missing `MANIFEST.json` in a `snap-*` dir.** Same handling as invalid. It
  cannot be produced by this tool, because the rename happens after the manifest
  is synced.

Re-derivation from the tree is not used for the base. The base is either a
verified manifest or nothing. This avoids trusting a corrupt index. The
existing `synccli` behavior, where `json.load` crashes on a corrupt manifest
(synccli.py:78-79, verified by writing `{"a":` and getting `JSONDecodeError`),
is overridden for this reason.

## 5. Change detection: granularity and what it misses

Granularity is the **file**. A file is unchanged if its `lstat` tuple
`(size, mtime_ns, ctime_ns, st_ino)` equals the tuple stored in the base
manifest. Only then is it hardlinked. Directories are not compared.

- `ctime_ns` cannot be set from user space (`utime` changes ctime to now),
  so restoring an old mtime with `touch -r` does not hide an edit. This closes
  the gap shown in section 2.2 item 3.
- Racy-stat rule (the git-index rule): if a file's `mtime_ns` is within
  2 seconds of the base's `started_at`, the stat tuple cannot prove the file
  is unchanged, because a write could have landed in the same timestamp tick
  after the base was taken. Such files are copied, not hardlinked.
- `st_ino` changes when a file is replaced by rename, so replacement is
  detected even when size and times match.

What this still misses:

- A content edit that leaves size, mtime_ns, ctime_ns, and inode all equal.
  This needs a write that completes within one timestamp tick and no inode or
  ctime change. APFS stores nanosecond timestamps, but the tick is not
  guaranteed to be finer than the write. Such edits are rare but possible.
  Mitigation: `backupctl verify --rehash` re-reads every hardlinked file and
  compares SHA-256 to the base manifest. Its cost is a full read of the tree
  (about 1 GB for the reference tree, roughly 10 s warm on this host, see
  section 9 for basis). It is run on demand, not on every run.
- Files changed by a process that sets mtime and ctime backwards is not
  possible for ctime; the only remaining hole is writes that happen while the
  copy is reading (handled in section 7).
- Deletions are not copied. A deleted file is simply absent from the new
  tree, and the snapshot before it still has it. This is correct for a backup.

## 6. Concurrency

| Actor | Lock | Mode | Held for |
|---|---|---|---|
| backup run, directory d | `<root>/<d>/.lock` | exclusive, blocking with a timeout (default 0 = fail fast with status 4) | whole run, including the sweep |
| restore / reader of snapshot s | `<root>/<d>/snap-s.lock` | shared, non-blocking attempt, then a clear error | the read |
| prune of snapshot s | `snap-s.lock` | exclusive, non-blocking | the rename-then-rmtree |

Behavior:

- Two backup runs for the same directory: the second fails with status 4 and
  does no work. Runs for different directories proceed in parallel, since their
  locks are different files.
- A restore during a backup: the backup writes only `tmp-*` and never touches a
  committed snapshot, so the reader sees a complete image. The reader needs no
  lock for that. It takes the shared snapshot lock so that prune cannot remove
  the snapshot mid-read.
- Prune while a restore reads snapshot s: prune's non-blocking exclusive
  attempt fails, prune skips s, and the report says so. The snapshot is deleted
  by a later prune.
- Process death: the kernel releases flock on exit, so a killed process never
  leaves a stale lock. The sweep (section 3, step 1) removes its `tmp-*`.
- Deletion is two-phase. `rename(snap-s, trash-s)` removes the snapshot from
  `list_snapshots` atomically. The `rmtree` of `trash-s` runs after the
  exclusive lock is held and may be interrupted. The next run's sweep finishes
  it.
- The lock files are a fixed set (one per directory and one per snapshot), so
  lock state does not grow with run count beyond the snapshots that exist.

Known limit: flock is advisory and local. Two machines writing to one backup
root over NFS are not supported in v1.

## 7. Source files that disappear or are unreadable

Per file, in the copy step:

1. `lstat` raises `FileNotFoundError`: the file vanished after listing. Record
   `skipped[path] = "vanished"`. Nothing is written.
2. `open` or read raises `PermissionError` or `OSError` (including EIO):
   record `skipped[path] = "unreadable"`. Any partial destination is removed
   before the next file.
3. A file changed while it was read: compare `lstat` before and after the
   copy. If it changed, retry the copy up to 2 times. If it is still changing,
   keep the last copy, record it in `files` with `status: "changed_during_copy"`,
   and note it in the report. The hash in the manifest matches the bytes that
   were written, so the snapshot is internally consistent even though it may
   not match any single instant of the source.
4. A symlink: recorded as `skipped[path] = "symlink"`. v1 does not copy links.
   Following them could copy outside the source tree and could loop.

Consistency: the manifest lists only files present in the tree, so it never
promises a file the snapshot does not contain. `skipped` is a separate list, so
a reader can tell "deleted before the run" from "missing from the snapshot
because it could not be read".

Same behavior for scheduler and person: the outcome depends only on the file
system, not on TTY or environment. The run's exit status and the report are
identical in both cases. Only the output channel differs (stdout for a person,
the log file for the scheduler).

Retry: a `skipped` file is not in any new base manifest entry, so the next run
sees it as new and copies it. This fixes the no-retry defect in section 2.2
item 2.

## 8. Exit status and report

| Status | Meaning |
|---|---|
| 0 | Snapshot committed, no skips, no invalid bases |
| 2 | Usage or configuration error; nothing written |
| 3 | Snapshot committed, but with skips or an invalid base snapshot (listed in the report) |
| 4 | Another run holds the directory lock; nothing written |
| 5 | Commit failed (I/O error before rename); `tmp-*` left for the sweep |

The report is one JSON document on stdout and in the run log: counts of
copied, hardlinked, skipped (by reason), invalid bases, and the snapshot name.

## 9. Performance budget for the initial full backup

Reference tree: ~1 GB, 20,000 files of 50 KiB each (the "tens of thousands of
files" shape from the brief).

Measured on this host (macOS, APFS, Python 3.10.11, warm page cache, nothing
else running):

| Step | Measurement | Command basis |
|---|---|---|
| Write the reference tree | 4.9 s | fixture generation (not a budget item) |
| Scan + stat (`build_manifest`, existing code) | 0.52 s; walk alone 0.16 s | 20,000 files |
| Full copy (`sync`, existing code, no fsync) | 9.78 s | 1,000 MB → ~102 MB/s |
| No-op sync (`sync`, all unchanged) | 0.55 s | 20,000 stats, 0 copies |
| Per-file write + fsync (2,000 files) | 0.145 ms/file | added by section 3 |
| Hardlink (2,000 files) | 0.307 ms/file | section 3 incremental path |

Derivation for the design's initial full backup:

- Scan 0.52 s
- Copy at measured 9.78 s (streaming with SHA-256 adds CPU cost, not measured;
  the existing read is the same I/O)
- fsync per file: 20,000 × 0.145 ms ≈ 2.9 s
- Manifest and directory syncs: negligible (one file, a few directories)

Sum: ~13.2 s. **Budget: 60 s wall for the initial full backup on this host
class, warm cache.** The 60 s figure is roughly 4.5× the derived sum. The
margin covers the unmeasured SHA-256 cost. Caveat: the fsync number is
measured on APFS and may not reflect real device flushes, and cold-cache or
spinning-disk behavior is not measured, so no budget is claimed for it.
Before the budget is relied on, the SHA-256 streaming copy must be measured
on the same fixture.

No-op incremental on the same tree: scan 0.52 s plus 20,000 hardlinks at
0.307 ms ≈ 6.1 s, so about 6.6 s. This is the case the incremental design is
meant to make cheap, and it is about 2× slower than today's no-op `sync`
(0.55 s) because `sync` does not create a snapshot.

## 10. Scaling: what grows with what

Notation: N = number of configured directories; F_d = files in directory d;
B_d = bytes in directory d; S = retained snapshots per directory (retention K);
c = changed bytes in a run.

| Quantity | Bound | Notes |
|---|---|---|
| Stat work per run | O(Σ F_d) = O(N·F̄) | one `lstat` per file |
| Data copied per run | O(Σ c_d) | only changed or racy files |
| Hardlink work per run | O(Σ F_d) | ~0.31 ms per unchanged file on this host |
| Memory per run | O(max_d F_d × ~200 B) | directories processed one at a time; the per-file manifest entry is estimated, not measured |
| Copy buffer memory | 1 MiB, constant | replaces whole-file read in `copy_file` (synccli.py:67) |
| Disk, one directory | ≤ B_d + Σ over retained runs of c | hardlinks share unchanged data |
| Disk, worst case (all files change every run) | ≤ (K+1)·B_d | the bound a retention policy must plan for |
| Disk, total | Σ_d (≤ (K+1)·B_d) | linear in N |
| Snapshot count | N·K at steady state | retention K per directory |
| Lock files | N + N·K | fixed per directory and per snapshot |
| Run-time for N directories | Σ_d per-dir time | sequential, so wall time is linear in N and F |

Flat quantities: copy buffer memory (1 MiB regardless of N, F, or file size),
and the lock-state footprint per snapshot. Per-run memory is flat in N, because
only one directory's manifest is held at a time.

Retention: K is a parameter, default **7** per directory. Prune runs after a
successful commit, under that directory's lock, and deletes the oldest
snapshots beyond K. The newest valid snapshot is never deleted, even when K is
0. A snapshot counts as valid only if its manifest parses.

## 11. Restore contract (boundary with the separate restore tool)

- Restore reads `MANIFEST.json` first and takes the shared snapshot lock.
- Every path comes from the manifest and goes through the checked
  `safe_snapshot_path` (section 2.2 item 9).
- Restore never writes into a committed snapshot.
- Files in `skipped` are not restored, and the restore report lists them.

## 12. Open items

- Symlinks: v1 records them as skipped. Copying the link itself is a v2 item.
- `verify --rehash` cost on the reference tree is an estimate from the copy
  throughput, not a measurement. It should be measured before it is relied on.
- The SHA-256 streaming copy cost is unmeasured (section 9).
- Multi-host writers are not supported (section 6).

# DESIGN-d1 — `backupctl`

Status: design only. No code written. All existing-code claims were checked by
running them in this directory (Python 3, `python3 -m unittest`: 6 tests pass).

## 1. Summary

`backupctl` takes point-in-time snapshots of N configured directories into a
backup root. Each directory has its own sub-root, its own run lock, and its own
retention. A snapshot becomes visible only through one atomic directory rename,
after its index is durably written. Unchanged files are hardlinked from the
newest committed snapshot. Interrupted runs leave only dot-prefixed staging
directories, which the next run removes under the lock.

## 2. Grounding: what is reused and what is overridden

Reused as-is:

| Existing artifact | Use in `backupctl` |
|---|---|
| `snaputil.list_snapshots` (snaputil.py:8-20) | Lists committed snapshots (`snap-*` dirs). Dot-prefixed staging and trash dirs are invisible to it. Its name-sort order works because names are `snap-YYYYMMDD-HHMMSS-NN`. |
| `synccli.changed_files` (synccli.py:36-42) | Reused for the "new or changed vs. previous index" test. It is applied to the state dicts produced by the new `file_state`, so it sees the new fields. |
| `synccli.MANIFEST_NAME` (synccli.py:7) and the `{relpath: state}` JSON shape (synccli.py:28-33, 85-86) | Index format keeps this shape: a dict of relpath to state, with extra fields added. |

Overridden. Each override names the exact behavior and the reason.

1. **`synccli.file_state` (synccli.py:22-25)** uses `st_mtime` (float). It is
   replaced by a state with `mtime_ns`, `ctime_ns`, and `size`. Float mtime
   loses precision, and `ctime` closes the `touch -r` / `utime` hole. A process
   cannot set `ctime` through `utime`.
2. **`synccli.scan_files` (synccli.py:14)** prunes every directory whose name
   starts with `.`, silently. That would drop `.git` or other dot-directories
   under evals results. Override: include all directories unless excluded by
   explicit config glob. Dot-files are already included today (verified: `.env`
   is returned).
3. **`synccli.copy_file` (synccli.py:62-69)** swallows `OSError` with `pass`
   and writes straight to the destination. Verified: with an unreadable source,
   `sync` returns the file as copied, the destination file does not exist, and
   the manifest still lists it (`sync` writes `src_manifest` at lines 83-86 no
   matter what happened). The next run therefore never retries the file, which
   contradicts the comment "next pass will retry". Override: a new
   `copy_file_checked` returns a status (`ok`, `vanished`, `unreadable`,
   `unstable`); only `ok` files enter the index. It writes to a temp name and
   renames.
4. **`synccli.sync` (synccli.py:72-87)** writes the manifest in place (`open(...,
   "w")`) and crashes on a corrupt manifest (verified: `JSONDecodeError`). Override:
   `backupctl` never calls `sync`. It writes the index to a temp file, fsyncs,
   and renames. A corrupt baseline index is handled per section 7.
5. **`snaputil.prune_snapshots` (snaputil.py:23-36)** deletes with `rmtree` in
   place, so a crash leaves a half-deleted `snap-*` dir that `list_snapshots`
   still reports. It also allows `keep=0`: verified, `keep=0` deleted every
   snapshot. Override: `backupctl` prunes via rename-to-trash (section 6) and
   enforces `keep >= 1` itself. It keeps the same selection rule (oldest first).
6. **`snaputil.safe_snapshot_path` (snaputil.py:54-63)** does not stop path
   traversal, despite its docstring. Verified: `"../../etc/passwd"` maps to `/b/snap-x/../../etc/passwd`,
   and an absolute `"/etc/passwd"` maps to `/etc/passwd` (`os.path.join` discards
   the base). `normpath` does not remove leading `..`. Override: restore rejects
   absolute paths and any `..` component, then checks that the resolved path is
   under the snapshot dir. Index paths are ours, but the check is cheap.
7. **`snaputil.snapshot_disk_usage` (snaputil.py:39-51)** sums logical size, so
   hardlinked files are counted once per snapshot. Override for reporting only:
   count each `(st_dev, st_ino)` once. The true disk cost is in section 8.
8. **`snaputil.is_stale` (snaputil.py:66-73)** compares a directory's mtime. A
   directory mtime changes on entry add/remove, not on file content edits, so it
   is not a change detector. Not used anywhere in `backupctl`.
9. **`synccli.collect_stale` (synccli.py:45-59)** is not used. It is unrelated
   to snapshot change detection.

## 3. Layout

```
<backup_root>/
  <dirname>/                       one sub-root per configured directory
    .lock                          run lock (flock, exclusive)
    .readers                       reader lock (flock, shared; prune takes exclusive)
    snap-20261112-150000-01/       committed snapshot (read-only)
      index.json                   the complete index for this snapshot
      <files...>                   hardlinks to older snapshots when unchanged
    .tmp-snap-<id>/                staging, invisible to list_snapshots
    .trash-snap-<id>/              pruned, invisible to list_snapshots
    .quarantine-snap-<id>/         corrupt committed snapshot, invisible
```

- `<dirname>` is the configured name, validated against `[A-Za-z0-9_-]+`.
- The sequence `NN` is a 2-digit counter that is incremented past any existing
  name with the same timestamp. Names stay unique, and `list_snapshots` still
  sorts them correctly.
- `index.json` schema:
  `{"format": 1, "source": "...", "started_ns": N, "entries": {rel: {"size",
  "mtime_ns", "ctime_ns", "sha256"}}, "skipped": {rel: reason}}`.
  `sha256` is empty for files not hashed (hardlinked from the baseline; see
  section 5).

## 4. Concurrency

Two run-level locks per directory, both `fcntl.flock` on files in the sub-root:

- **`.lock` (exclusive)** is held by every run and every prune. A second run
  waits up to `--lock-timeout` (default 30 s), then exits with code 75
  (`EX_TEMPFAIL`) so the scheduler can retry. Runs on different directories do
  not contend.
- **`.readers` (shared / exclusive)** is held shared by a restore for the whole
  copy-out, and exclusive by prune for the rename-to-trash step only.

Consequences:

- Two runs cannot both create staging dirs, so the staging name collision
  case does not arise.
- A restore never blocks a run. A run never blocks a restore, because runs do
  not take `.readers`.
- Prune waits for readers, and readers do not see a snapshot disappear. Prune
  renames to `.trash-*` under the exclusive `.readers` lock, then releases it and
  does the `rmtree` outside that lock (the trash dir is already invisible).
- `flock` is released by the kernel when the process dies, so a killed run never
  leaves a stale lock. The lock file itself may remain; that is harmless.

## 5. Commit protocol and crash safety

A run for directory D, with exclusive `.lock` held:

1. **Recover** (section 7): delete every `.tmp-*`, `.trash-*` in D. These
   can only belong to a dead run, because the live run holds `.lock`.
2. **Baseline**: newest committed `snap-*` in D, if any. Load its `index.json`.
   If the baseline is missing or unparseable, run as a full run (section 7).
3. **Stage**: `mkdir .tmp-snap-<id>`.
4. **Scan and copy**, one file at a time, in sorted order:
   - Stat the file. On `FileNotFoundError` (vanished during listing), record
     `skipped[rel] = "vanished"` and continue.
   - Unchanged test: `(size, mtime_ns, ctime_ns)` equal to the baseline entry,
     and `mtime_ns` is older than `started_ns - 2 s` (the racy-timestamp guard
     below). If unchanged, `os.link(baseline/rel, staging/rel)`. The entry is
     copied from the baseline (including its `sha256`). Reads no file content.
   - Otherwise copy: open, `read` in 1 MiB chunks into a temp file in staging,
     hash while copying, `fsync` the temp file, `rename` to `rel`. Before the
     final rename, `fstat` again; if `(size, mtime_ns)` differ from the first
     stat, the file changed during copy. Retry once; if still unstable, record
     `skipped[rel] = "unstable"`.
   - Read error (`OSError`, for example `EACCES` or `EIO`): record
     `skipped[rel] = "unreadable: <errno>"` and remove any partial temp file.
5. **Write index**: `index.json.tmp` in staging, `fsync`, `rename` to
   `index.json`. Then `chmod` all files and dirs read-only in staging.
6. **Commit**: `fsync` the staging dir, `rename .tmp-snap-<id>` to `snap-<id>`,
   `fsync` D. This rename is the only point at which a snapshot becomes visible.
7. **Prune** (section 6), if the policy is configured.

Invariants:

- A `snap-*` dir exists only after its index was fsynced. So any committed
  snapshot is complete and self-consistent: every entry in `index.json` is in
  the directory, and every file in the directory is in the index. Skipped files
  are listed under `skipped` and absent from both.
- No reader needs to ask whether a run is finished. A `snap-*` dir is final.
- A run killed at any step leaves only `.tmp-*` content, which is removed on the
  next run. It never leaves a `snap-*` dir.

Racy-timestamp guard. A file modified in the same timestamp tick as the previous
snapshot could keep the same `(size, mtime_ns, ctime_ns)` with different content.
Any file whose `mtime_ns` is within 2 s of `started_ns` of the baseline is
therefore always copied, never hardlinked.

Hardlink safety. Snapshots are read-only after commit. A hardlink can only
change if someone bypasses the permissions (a root user). `backupctl verify`
(optional) rehashes a snapshot against its index.

## 6. Retention

- Policy per directory: `keep = K`, with `K >= 1` enforced by `backupctl`
  (section 2, item 5). Default K = 7 (placeholder; configurable).
- Selection: the oldest `len(committed) - K` snapshots are removed. The newest
  snapshot is never removed, because `K >= 1`.
- Deletion, under the exclusive `.readers` lock:
  1. `rename snap-<id>` to `.trash-snap-<id>` (atomic; readers either hold the
     lock and finish, or start after the rename and find nothing).
  2. Release `.readers`.
  3. `rmtree` the trash dir.
- A crash between 1 and 3 leaves a `.trash-*` dir, which the next run removes.
  Snapshot content is never half-deleted under a `snap-*` name.
- Hardlinked files survive deletion of the snapshot they were linked from. A
  newer snapshot's link keeps the inode alive. So deleting old snapshots never
  breaks newer ones.

## 7. Recovery rules

| Condition at run start | Action | Reported |
|---|---|---|
| `.tmp-*` or `.trash-*` in D | Delete | `recovered: removed <name>` |
| Newest `snap-*` has missing `index.json` or it fails to parse / fails schema | Rename to `.quarantine-snap-*`; run as a full run with no baseline | `warning: quarantined <name>: <reason>` |
| Newest `snap-*` index parses, but a listed file is missing | Quarantine the same way (the index is not trusted) | same |
| Lock held by a live run | Wait up to `--lock-timeout`, then exit 75 | `busy` |

Quarantined dirs are deleted on the next successful commit, and the deletion is
reported. A full run is correct but costs a full copy; that is the price of
recovery, not a data-loss path.

## 8. Source file disappearance and what a snapshot contains

The same code path runs whether the scheduler or a person starts the run. There
is no prompt and no difference in behavior.

- A file that vanishes before stat: not in the snapshot, `skipped = "vanished"`.
- A file that vanishes after stat but before or during read: the copy fails or
  the `fstat` check fails, so it is `unstable` or `unreadable`.
- A directory that vanishes during walk: `os.walk(onerror=...)` records every
  file under it as `vanished`.

Exit codes: `0` all files copied; `2` snapshot committed with one or more
skipped files (the report lists them); `75` lock busy; `1` nothing committed.
A snapshot with skipped files is still committed, because the brief requires
that a run leave an accurate, usable snapshot. The skipped list is in the index.

## 9. Change detection granularity and its misses

Granularity: one file. The state is `(size, mtime_ns, ctime_ns)`.

Edits this can miss:

- A write that keeps size, `mtime_ns`, and `ctime_ns` identical. `ctime` is set by
  the kernel on every write and cannot be forged by `utime`, so this needs a write
  within the same timestamp tick. The racy-timestamp guard (section 5) covers
  that window.
- Changes on filesystems with coarse timestamps (1 s or 2 s granularity). The
  racy guard covers the last 2 s; a deployment on such a filesystem must raise
  the guard window to the filesystem granularity.
- Edits on a different mount that does not update `ctime` (network filesystems,
  some FUSE). Unsupported; the design requires local POSIX semantics.

Measured on this machine: a same-size edit with `mtime` restored by `utime`
was **not** detected by the existing `(size, mtime)` state (verified:
`changed_files` returns `False`). Adding `ctime_ns` closes this case, because
`utime` cannot set `ctime`. This is the reason for the `file_state` override.

Deletions: `changed_files` (synccli.py:36-42) does not report deletions (verified:
`[]` after removing a file). This is correct for snapshots, which are full images:
a deleted file is simply absent from the new index.

Granularity note: `backupctl` never compares content on the unchanged path, so
a content change that keeps all three state fields equal is missed. `verify`
rehashes on demand.

## 10. Performance and the first full backup

Measured on this machine (macOS, APFS, Python 3), a tree of 30,000 files in 300
directories, 33 KiB each, about 0.96 GiB:

| Operation | Measured |
|---|---|
| `synccli.build_manifest` (scan + stat, `synccli.py:28-33`) | 0.81 s (about 27 µs per file) |
| `synccli.sync`, cold (`synccli.py:72-87`) | 13.63 s, copied 30,000 |
| `synccli.sync`, warm, no changes | 0.82 s, copied 0 |
| Streamed copy with 1 MiB chunks, SHA-256, `fsync` per file, rename (the `backupctl` copy path) | 19.53 s |
| Index size per entry (JSON, indent=2, with `ns` fields and sha256) | 201 bytes per entry |

Budget for the first full backup of a ~1 GB, ~30,000-file tree: **60 s wall
clock** on this machine. Derivation: the measured per-file path (copy + hash +
fsync, 19.53 s, plus scan 0.81 s, about 20.3 s) times a 3x margin for slower
disks, which gives 61 s, rounded to 60 s. The 3x margin is a judgement, not a
measurement; the acceptance test is a real run of this tree on the target
machine. If it exceeds 60 s, the first lever is batching `fsync` per directory
instead of per file. Both numbers were taken with the same tree and disk on one
machine, and no other load was running.

Per-run cost for a directory with F files and B changed bytes:

- Stat and compare: O(F), about 27 µs per file measured (the scan figure above).
- Hardlink for unchanged files: O(F), one `link` syscall each. Not measured;
  to be measured in the acceptance test.
- Copy and hash for changed files: O(B), about 19.53 s per 0.96 GiB measured,
  about 49 MiB/s end to end.
- Index write: O(F), 201 bytes per entry (measured), so about 6 MB for 30,000
  files.

## 11. Scaling with N directories and the tree

Let N be the number of configured directories. Let F_d be the file count and
B_d the byte count of directory d. Let K be the retention count.

| Quantity | Growth | Bound |
|---|---|---|
| Work per run (one directory) | O(F_d) stat + O(changed bytes) copy | 27 µs per file measured; about 49 MiB/s copy |
| Work per scheduled pass (all dirs) | O(sum over d of F_d) | 27 µs × total files, plus copy of changed bytes |
| Memory per run | O(F_d) for one directory at a time | One index dict of 201 bytes per entry (measured as JSON; in-memory is larger, estimate ~2x) |
| Memory across N | flat in N | Directories processed sequentially; peak = largest F_d |
| Disk, one directory | B_d + sum of changed bytes over the K-1 older snapshots | Worst case K × B_d (every file changes every run); typical near B_d |
| Disk across N | sum over d | sum over d of (B_d + changed) |
| Lock contention | flat in N | Per directory; runs on different directories never wait on each other |
| Index size on disk | O(F_d) per snapshot | 201 bytes × F_d per snapshot |

The per-run work grows with N only linearly (sum over directories). Memory and
lock contention do not grow with N. The disk bound for retention is the formula
in the table: the hardlink sharing caps retention at B_d plus changes, not K
times B_d, when most files are unchanged.

Accuracy note: the "about 2x" in-memory estimate for the index is not measured.
Acceptance criterion: measure peak RSS on the 30,000-file tree.

## 12. Acceptance tests (to implement)

1. Crash at each commit step (kill after staging, after index write, before
   rename): no `snap-*` dir is created or visible; the next run recovers.
2. Two concurrent runs on one directory: one proceeds, the other exits 75 after
   the timeout. Runs on two directories both succeed.
3. Restore during prune: the restore finishes, the snapshot is gone only after
   the restore releases its reader lock.
4. Unreadable file (chmod 000) and file deleted mid-run: committed snapshot
   lists them under `skipped`; exit code 2; same result under a scheduler
   invocation.
5. `touch -r` edit (same size, same `mtime_ns`): detected through `ctime_ns`.
6. Corrupt newest index: quarantined; full run succeeds; warning printed.
7. First full backup of the 30,000-file tree: wall clock at most 60 s, and peak
   RSS measured and recorded.
8. Dot-directory (`.git`) present: included.

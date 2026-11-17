# `backupctl` Design Specification (D1)

## 1. Overview & Architecture

`backupctl` is a command-line snapshot backup tool for the `evals/` workflow. It backs up $N$ configured source directories (3 today, growing to 24–48 over time) into point-in-time, self-consistent snapshots under a single `backup_root`, reusing and extending the existing `synccli.py` and `snaputil.py` modules in this repository.

### Design Goals
1. **Single-writer, multi-reader isolation**: Concurrent scheduler/human invocations serialize cleanly; readers (`backupctl restore` or external tooling) always observe a complete, immutable snapshot.
2. **Crash safety at any instruction**: Mid-run `SIGINT`, `SIGKILL`, or laptop sleep never exposes a partial snapshot or leaves unrecoverable index corruption.
3. **Incremental efficiency without unpacking**: Unchanged files are hardlinked (`os.link`) from the newest valid snapshot, keeping every published `snap-*` directory a directly browsable, POSIX-restorable tree.
4. **Strict grounding**: Every scanning, manifest, change-detection, copy, and snapshot operation explicitly builds on or overrides named functions in `synccli.py` and `snaputil.py`.

### On-Disk Layout under `backup_root`

```text
backup_root/
├── .locks/
│   ├── backup.lock                 # Exclusive writer lock (flock LOCK_EX)
│   └── snap-<id>.lock              # Per-snapshot reader lease (LOCK_SH) / pruner lock (LOCK_EX)
├── .staging/
│   └── run-<YYYYMMDDTHHMMSSZ>-<pid>-<rand>/
│       ├── manifest.json           # Snapshot-level summary (written & fsynced last)
│       ├── manifests/
│       │   └── <source_id>.json    # Per-source file index
│       └── sources/
│           └── <source_id>/...     # Copied / hardlinked files
├── .trash/
│   └── snap-<id>.<run_id>/         # Atomically hidden doomed snapshots awaiting rmtree
├── index.json                      # Fast cache pointing to latest valid snapshot & source summaries
└── snap-20261116-143000-01/        # Published, immutable snapshot (only visible after atomic rename)
    ├── .COMPLETE                   # Commit marker written inside staging before publish rename
    ├── manifest.json
    ├── manifests/
    │   └── <source_id>.json
    └── sources/
        └── <source_id>/...
```

Key layout invariants:
- **Dot-prefixed internal directories** (`.locks/`, `.staging/`, `.trash/`): `snaputil.list_snapshots(backup_root)` (`snaputil.py:8-20`) matches only directories starting with `"snap-"`. Staging and deleting trees never match `"snap-*"`.
- **Snapshot naming**: `snap-YYYYMMDD-HHMMSS-NN` (UTC timestamp + 2-digit zero-padded sequence `01..99`; if 99 snapshots occur in the same second, wait 1 s before allocating). This matches the `snaputil.py:12` format (`snap-20261112-150000-07`) and guarantees that `sorted(names)` (`snaputil.py:20`) equals chronological order.
- **Clean source trees inside snapshots**: Metadata lives in `manifest.json` and `manifests/<source_id>.json`, never inside `sources/<source_id>/`. Because `synccli.scan_files(root)` (`synccli.py:14`) only skips dot-directories (not dot-files), placing `.sync_manifest.json` inside `sources/<source_id>/` would pollute restored trees and subsequent scans.
- **Configured source mapping**: Each of the $N$ source directories has an explicit, unique `source_id` slug in config (e.g., `evals-unit`, `evals-bench`) mapped to its canonical source path, preventing basename collisions when multiple directories share a leaf name.

---

## 2. Grounding: Reuse & Explicit Overrides of Existing Code

`backupctl` lives alongside `synccli.py` and `snaputil.py`. The table below maps every existing symbol to how `backupctl` uses or overrides it.

| Existing Artifact | Exact Location | Role in `backupctl` | Override / Extension Reason |
|---|---|---|---|
| `synccli.MANIFEST_NAME` | `synccli.py:7` | Replaced for snapshots | `.sync_manifest.json` inside a target data directory collides with `scan_files` (which includes dot-files). Replaced by `manifest.json` + `manifests/<source_id>.json` outside `sources/`. |
| `synccli.scan_files(root)` | `synccli.py:10-19` | **Reused** (wrapped) | Reuses `os.walk` + dot-directory pruning (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`, line 14) + `sorted` relative paths. Wrapped to skip non-regular files (symlinks, FIFOs, sockets) before `lstat`, and to handle missing `root` explicitly instead of silently returning `[]`. |
| `synccli.file_state(path)` | `synccli.py:22-25` | **Overridden** | Currently calls `os.stat(path)` (line 24) and returns `{"size": st.st_size, "mtime": st.st_mtime}` (line 25). Overridden to: (1) use `os.lstat(path)` so broken symlinks do not raise `FileNotFoundError`; (2) store `mtime_ns` (`st.st_mtime_ns` int) instead of float `st_mtime` to avoid IEEE-754 rounding loss; (3) include `mode` (`st.st_mode & 0o777`); and (4) catch `OSError` on vanished files. |
| `synccli.build_manifest(root)` | `synccli.py:28-33` | **Overridden** | Line 32 calls `file_state(os.path.join(root, rel))` with no `try/except`, crashing the entire run if a source file disappears between `scan_files` and `file_state`. Overridden to handle per-file `FileNotFoundError`/`PermissionError` gracefully, omit vanished/unreadable files from the manifest, and record warnings. |
| `synccli.changed_files(old_manifest, new_manifest)` | `synccli.py:36-42` | **Reused + Extended** | Reused directly on projected comparison dicts `{size, mtime_ns, mode}` (so `old_manifest[rel] != state` at line 40 ignores auxiliary fields like `sha256` unless `--verify-checksum` is active). Extended with explicit deletion reporting (`set(old_manifest) - set(new_manifest)`) for run metrics. |
| `synccli.collect_stale(items, seen=None)` | `synccli.py:45-59` | **Reused** | Used directly during retention pruning to filter `(snap_name, is_retained)` pairs against `seen=active_reader_snaps` so snapshots held by readers or retained by policy are never selected for deletion. |
| `synccli.copy_file(src, dst)` | `synccli.py:62-69` | **Overridden** | Three critical defects for backup use: (1) `fdst.write(fsrc.read())` (line 67) loads entire files into RAM (`O(file_size)`); (2) `except OSError: pass` (lines 68–69) silently swallows both source errors and destination `ENOSPC`/`EIO` and returns `None`, leaving `sync()` unaware; (3) does not preserve `mtime_ns`/`mode` or compute `sha256`. Overridden with a 1 MiB streaming copy + inline SHA-256 + `os.utime(..., ns=...)` + `os.chmod`, returning explicit status (`copied`/`vanished`/`unreadable`) and re-raising destination write errors. |
| `synccli.sync(src_root, dst_root, dry_run=False)` | `synccli.py:72-88` | **Overridden** | Writes in-place to `dst_root` (no snapshot isolation), handles only 1 directory, has no locking, crashes on corrupt JSON at `json.load(f)` (line 79), overwrites `.sync_manifest.json` non-atomically (`open(..., "w")` at line 85), and writes `src_manifest` even when `copy_file` failed (lines 83–86). Replaced by `backupctl`'s locked, multi-source staged snapshot pipeline. |
| `snaputil.list_snapshots(backup_root)` | `snaputil.py:8-20` | **Reused** | Used directly as the single source of truth for published snapshots (`snap-*`, oldest first). `backupctl` ensures `backup_root` exists before calling and keeps all non-snapshot dirs dot-prefixed. |
| `snaputil.prune_snapshots(backup_root, keep)` | `snaputil.py:23-36` | **Overridden** | Two safety flaws: (1) when `keep <= 0`, `names[:len(names) - keep]` (line 33) deletes *all* snapshots; (2) `shutil.rmtree` (line 35) runs directly on `backup_root/<name>` without checking reader locks or hiding via `.trash/` first, risking reader `ENOENT` and half-deleted `snap-*` dirs on crash. Overridden with GFS retention (`keep_min >= 1` floor), `LOCK_EX | LOCK_NB` reader-lease check, atomic `os.rename` to `.trash/`, and `rmtree`. |
| `snaputil.snapshot_disk_usage(backup_root, snapshot_name)` | `snaputil.py:39-51` | **Reused** (with physical supplement) | Reused for single-snapshot logical (apparent) bytes. Supplemented with an `st_ino`-deduplicated walker across `snap-*` directories so physical disk usage does not overcount hardlinked inodes, and guarded with `lstat` fallback against broken symlinks (line 50 uses `os.stat`). |
| `snaputil.safe_snapshot_path(backup_root, snapshot_name, rel_path)` | `snaputil.py:54-63` | **Overridden** | Fails its own docstring claim (lines 58–60): `os.path.normpath("../../etc/passwd")` retains leading `..`, and `os.path.normpath("/etc/passwd")` stays absolute so `os.path.join` (line 63) discards `backup_root` and `snapshot_name`. Overridden to reject absolute paths and `..` segments and verify `os.path.commonpath([snap_real, target_real]) == snap_real` after `os.path.realpath`. |
| `snaputil.is_stale(snapshot_dir, ref_epoch)` | `snaputil.py:66-73` | **Overridden** | Line 73 uses `st_mtime <= ref_epoch`, contradicting its own docstring (lines 70–72: *"modified at exactly ref_epoch is not stale"*). Overridden with strict `<` and by reading immutable `created_at_utc` from `manifest.json` for snapshot retention age. |

---

## 3. Concurrency, Isolation, and Atomic Publication

### Writer Serialization (Scheduler vs. Human Collisions)
- Every mutating command (`backup`, `prune`, `verify --repair`) opens `backup_root/.locks/backup.lock` (`O_CREAT | O_RDWR`) and acquires `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` (or waits up to `--wait N` seconds if requested).
- The lockfile is **never unlinked** on exit (unlinking breaks inode identity for concurrent waiters). After acquiring `LOCK_EX`, the holder writes `{"pid": ..., "started_at": ..., "mode": ...}` into the lockfile for diagnostics.
- If `LOCK_EX | LOCK_NB` fails (`BlockingIOError`), the second run exits cleanly with exit code `3` (`EXIT_LOCKED`) and prints the holder's PID and start time. Whether triggered by cron/launchd or a person, two writers never execute simultaneously against the same `backup_root`.

### Snapshot Staging & Atomic Publication
A reader never needs to ask whether a snapshot is finished because **no directory named `snap-*` exists until its entire tree and metadata are complete on disk**:
1. Create staging dir `backup_root/.staging/run-<ts>-<pid>-<rand>/` with `sources/` and `manifests/`.
2. Process each configured source $i \in \{1..N\}$ into `sources/<source_id>/` and write `manifests/<source_id>.json.tmp` -> `flush` + `os.fsync` -> `os.replace` to `manifests/<source_id>.json`.
3. Write `manifest.json.tmp` (recording every `source_id`, file counts, byte counts, `skipped_files`, SHA-256 of each per-source manifest, and `created_at_utc`) -> `flush` + `os.fsync` -> `os.replace` to `manifest.json`.
4. Write `.COMPLETE` marker file (`flush` + `os.fsync`), then call `os.sync()` (flushes staged file/directory metadata in bulk rather than paying 30,000 individual barrier `fsync`s) and `fsync` the staging directory fd.
5. **Atomic publication**: `os.rename(staging_dir, os.path.join(backup_root, snap_name))`, followed by `fsync(backup_root_fd)`. On POSIX within the same filesystem, directory `os.rename` to a non-existent name is atomic.
6. Update `backup_root/index.json` atomically (`index.json.tmp` -> `fsync` -> `os.replace` -> `fsync(backup_root_fd)`).

### Reader Isolation & Concurrent Restore
- **New backups vs. concurrent restores**: Published snapshots are strictly immutable. Unchanged files are hardlinked *from* `snap-<prev>` *into* `.staging/` (incrementing `st_nlink` without altering any bytes or directory entries in `snap-<prev>`), and changed files are written as brand-new inodes inside `.staging/`. An active restore reading `snap-<prev>` sees zero mutations.
- **Prune vs. concurrent restores**:
  1. `backupctl restore <snap_id> <dest>` (and any cooperative external restore script using the documented lock path) opens `backup_root/.locks/<snap_id>.lock` and acquires `fcntl.flock(fd, fcntl.LOCK_SH)` for the duration of the restore.
  2. Before pruning `<snap_id>`, `backupctl` attempts `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` on `.locks/<snap_id>.lock`. If `BlockingIOError` occurs, `<snap_id>` is added to `active_reader_snaps` (passed as `seen` to `synccli.collect_stale`) and **skipped** for this prune cycle.
  3. If separate external tooling reads `snap-<id>` without taking `LOCK_SH`, `backupctl`'s two-phase trash + grace period limits exposure: `prune` atomically renames `snap-<id>` -> `.trash/<snap_id>.<run_id>` (on POSIX, already-open file descriptors and relative lookups from an open dirfd remain valid) and defers `shutil.rmtree` until the `.trash/` entry is older than `trash_grace_seconds` (default `300 s`, checked with strict `<` rather than `snaputil.is_stale`'s `<=`), while `keep_min` / `keep_last` prevents recent snapshots from being pruned at all. Full race-freedom for path-walking restores requires taking the documented `LOCK_SH` lease or running `backupctl restore`.

---

## 4. Crash Safety & Index Recovery

Suppose `backupctl` is killed (`SIGINT`, `SIGKILL`, power loss, laptop sleep) at any point:

| Crash Point | Leftover Artifacts | Next Run Recovery Action |
|---|---|---|
| During copy/hardlink into `.staging/<run_id>/` | Partial files/dirs in `.staging/<run_id>/` | Acquire `backup.lock`; **discard** all `.staging/*` directories (`shutil.rmtree`). No `snap-*` was created. |
| During temp manifest write (`*.tmp.*`) | Orphan `*.tmp.*` in `.staging/` or `backup_root/index.json.tmp.*` | **Discard** leftover `*.tmp.*` files; published files are untouched due to `os.replace`. |
| After `os.rename` to `snap-<new>`, before `index.json` update | Valid `snap-<new>` exists on disk, `index.json` points to `snap-<prev>` (or is half-written if legacy/corrupt) | **Discard** stale/corrupt `index.json`; **re-derive** `index.json` from `snap-<new>/manifest.json`. |
| During `shutil.rmtree` inside `.trash/` | Partial directory inside `.trash/` | Hidden from `snaputil.list_snapshots`; next run **resumes** `rmtree` on `.trash/*`. |
| Corrupt/half-written `index.json` or damaged `snap-<latest>/manifest.json` | Truncated JSON, failed `manifest_sha256`, or missing fields | Defined recovery protocol below. |

### Corrupt or Half-Written Index Recovery Protocol

1. **Detecting index corruption**: On startup (under `backup.lock`), `backupctl` loads `backup_root/index.json` and validates: (a) JSON syntax, (b) `schema_version == 1`, (c) `latest_snapshot` is in `snaputil.list_snapshots(backup_root)`, and (d) `latest_snapshot/manifest.json` parses cleanly and each `manifests/<source_id>.json` matches its recorded `manifest_sha256` and `os.path.exists(".COMPLETE")`.
2. **What is discarded**:
   - All `.staging/*` and `*.tmp.*` files are unlinked/`rmtree`d.
   - If `backup_root/index.json` fails validation, it is unlinked (or moved to `.trash/corrupt-index-<ts>.json` for postmortem, cleaned after grace period).
   - If the newest `snap-*` directory lacks `.COMPLETE` (e.g., an externally interrupted/partial `snap-*` directory), it is moved to `.trash/` and discarded—**unless** it is the only snapshot on disk, in which case step 3 repairs it instead of leaving zero snapshots.
3. **What is re-derived from the tree**:
   - Walk `snaputil.list_snapshots(backup_root)` newest-to-oldest to find the newest usable snapshot `S`.
   - If `S/manifest.json` and `S/manifests/<source_id>.json` pass schema + `manifest_sha256` validation, `index.json` is rebuilt directly from `S/manifest.json` without touching data files.
   - If `S` has `.COMPLETE` (or is the sole snapshot) yet `S/manifest.json` or any `S/manifests/<source_id>.json` is corrupt/half-written: `backupctl` **re-derives** `manifests/<source_id>.json` directly from the on-disk tree `S/sources/<source_id>/` by scanning with `synccli.scan_files`, stating each regular file (`lstat` for `size`, `mtime_ns`, `mode`), streaming SHA-256 of each file on disk, atomically rewriting `S/manifests/<source_id>.json` and `S/manifest.json`, and then atomically writing `backup_root/index.json`.
   - If zero snapshots exist under `backup_root`, baseline is empty `{}` and the run proceeds as an initial full backup.
4. **What the run reports**:
   - Emits structured recovery fields in stderr summary and JSON output (`--json`):
     - `recovery_triggered: true`
     - `discarded_staging: [<run_id>, ...]`
     - `discarded_corrupt_index: true | false`
     - `rebuilt_from_snapshot: "<snap_id>" | "none"`
     - `rehashed_files: <int>` (nonzero only when a snapshot's manifest had to be reconstructed from disk)
   - Never blocks on manual intervention; proceeds directly with the requested backup.

---

## 5. Vanishing & Unreadable Source Files

Unlike `synccli.build_manifest` (`synccli.py:32`, which crashes on `FileNotFoundError`) and `synccli.copy_file` (`synccli.py:68-69`, which silently swallows `OSError` and lets `sync()` lie in `.sync_manifest.json`), `backupctl` handles transient and permission failures deterministically and **identically** whether started by the scheduler or by a human (non-interactive, identical flags and exit codes):

- **File vanishes between `scan_files` and `lstat` or `open` (`FileNotFoundError` / `ENOENT`)**:
  - **Snapshot contents**: Omitted from `sources/<source_id>/` and omitted from `manifests/<source_id>.json["files"]`. Any partial temp file in `.staging/` is unlinked.
  - **Run report**: Appended to `manifest.json["skipped_files"]` with `{"source_id", "rel_path", "reason": "vanished"}` and logged to stderr (`WARN vanished <source_id>/<rel_path>`). Exit code remains `0` (`EXIT_OK`) unless `--strict` is specified (`EXIT_PARTIAL = 4`), since ephemeral temp-file deletion during live `evals/` runs is normal and the resulting snapshot is still self-consistent.
- **File is unreadable when copy reaches it (`PermissionError` / `EACCES` / `EIO` on source)**:
  - **Snapshot contents**: Omitted from `sources/<source_id>/` and omitted from `manifests/<source_id>.json["files"]`—**never** carried over from `snap-<prev>`, because mixing yesterday's file into today's snapshot violates point-in-time consistency.
  - **Run report**: Recorded in `manifest.json["skipped_files"]` with `{"source_id", "rel_path", "reason": "unreadable", "errno": e.errno, "error": str(e)}`, logged to stderr (`ERROR unreadable <source_id>/<rel_path>`), and causes the run to exit `4` (`EXIT_PARTIAL`) after publishing the rest of the consistent snapshot.
- **Source file mutates mid-copy**:
  - After streaming `src` and computing `sha256` + `bytes_written`, `backupctl` re-`lstat`s `src`. If `(st_size, st_mtime_ns)` changed during read, it retries up to 1 time; if it changed again, it records the exact `(bytes_written, post_mtime_ns, mode, sha256)` of the bytes actually written into `.staging/` (or omits if vanished on retry), ensuring `manifest.json` never disagrees with the snapshot bytes on disk.
- **Destination write error (`ENOSPC`, `EROFS`, `EIO` on `dst` or `os.link`)**:
  - Immediately aborts the backup run (`EXIT_IO_ERROR = 5`), deletes `.staging/<run_id>/`, leaves all existing snapshots and `index.json` untouched, and reports the failing path and errno.

---

## 6. Incremental Change Detection & Granularity

### Change Detection Granularity
Building on `synccli.file_state` (`synccli.py:22-25`) and `synccli.changed_files` (`synccli.py:36-42`), `backupctl` decides a file is **unchanged** since the newest valid snapshot `snap-<prev>` if and only if:
1. `rel` exists in `snap-<prev>/manifests/<source_id>.json["files"]`,
2. the backing file exists in `snap-<prev>/sources/<source_id>/<rel>` (sanity-checked via `os.lstat` before `os.link`), and
3. the fast-check tuple `(size, mtime_ns, mode)` matches identically (`st.st_size`, `st.st_mtime_ns` integer nanoseconds, `st.st_mode & 0o777`).

Unchanged files are **hardlinked** (`os.link(prev_file, staging_file)`) rather than copied, and their recorded `sha256` is carried forward into the new manifest without reading file contents. (If `os.link` fails with `EMLINK` link-count exhaustion, `EXDEV`, or `ENOTSUP`, `backupctl` transparently falls back to copying that file.) Deleted source files are simply absent from `new_manifest`, so they are not linked into `.staging/` and are absent from the new snapshot.

An optional `--verify-checksum` flag overrides the fast tuple check and compares streaming `sha256` against `prev_manifest[rel]["sha256"]`.

### Edits the Default Granularity Can Miss
Because default incremental detection compares `(size, mtime_ns, mode)` without re-reading file bytes, it can miss:
1. **Same-size, preserved-mtime edits**: An in-place overwrite of identical byte length followed by `utime` restoring the original `mtime_ns` (or `mmap` writes where the kernel defers/skips mtime updates).
2. **Sub-quantum same-size edits on coarse filesystems**: On filesystems with 1 s (HFS+, ext3) or 2 s (FAT/exFAT) timestamp resolution, two writes of the exact same byte length occurring within the same timestamp tick share `(size, mtime_ns)`.
3. **Silent source bit-rot / storage corruption**: Underlying disk corruption alters file bytes while filesystem metadata (`size`, `mtime_ns`, `mode`) remains unchanged.
4. **Extended attributes (`xattr`) or POSIX ACL changes**: Not included in `(size, mtime_ns, mode)`.

Mitigation: `backupctl backup --verify-checksum` (recommended periodically, e.g., weekly) and `backupctl verify` re-hash files against stored `sha256` digests.

---

## 7. Retention Policy & Safe Deletion

`backupctl` runs retention **only after** the new snapshot has been atomically published and `index.json` updated. If the backup run fails, no existing snapshot is pruned.

### Retention Rules (GFS + Hard Minimum Floor)
Configured via `retention` (overriding `snaputil.prune_snapshots`'s single `keep` argument at `snaputil.py:23-36`):
- `keep_min`: **Hard floor clamped to `max(1, config.keep_min)`** (default `3`). `backupctl` never allows `keep_min = 0` to delete all snapshots—explicitly fixing `snaputil.prune_snapshots(backup_root, 0)` (`snaputil.py:33`), which slices `names[:len(names)]` and deletes everything.
- `keep_last`: Unconditionally keep the `10` newest valid snapshots.
- `keep_daily`: Keep the newest valid snapshot for each of the last `7` UTC calendar days.
- `keep_weekly`: Keep the newest valid snapshot for each of the last `4` ISO weeks.

A snapshot is retained if it matches any of `keep_last`, `keep_daily`, `keep_weekly`, or is needed to satisfy `keep_min` newest valid snapshots. Only snapshots that are valid (pass manifest validation) count toward `keep_min`, ensuring a corrupt snapshot never causes the last usable snapshot to be deleted.

### Safe Deletion Sequence
1. Enumerate snapshots oldest-first via `snaputil.list_snapshots(backup_root)` (`snaputil.py:8-20`).
2. Compute `keep_set` from the retention rules above (plus any snapshot pinned via `.locks/<snap>.pin`).
3. Probe `.locks/<snap>.lock` for non-retained snapshots using `flock(LOCK_EX | LOCK_NB)`; collect held snapshots into `active_reader_snaps`.
4. Select doomed snapshots using `synccli.collect_stale` (`synccli.py:45-59`):
   `doomed = synccli.collect_stale([(s, s in keep_set) for s in all_snaps], seen=active_reader_snaps)`.
5. For each `snap` in `doomed`:
   - Atomically hide it: `os.rename(backup_root/snap, backup_root/.trash/<snap>.<run_id>)`, then `fsync(backup_root_fd)`.
   - Clean up `.trash/` entries whose age exceeds `trash_grace_seconds` (via `shutil.rmtree`), checking age with strict `<` (overriding `snaputil.is_stale`'s `<=` bug at `snaputil.py:73`).

---

## 8. Performance Budget (Initial ~1 GiB Full Backup, Tens of Thousands of Files)

### Measured Primitive Constants (This Host: macOS APFS, Python 3.10.11)
Measured directly by running `synccli.py` and Python streaming/linking primitives against synthetic trees on this machine's filesystem:
- **`synccli.scan_files` (2,000 files)**: `0.0126 s` (`6.3 µs/file`).
- **`synccli.build_manifest` (`scan_files` + `os.stat`, 2,000 files)**: `0.0475 s` (`23.8 µs/file`).
- **`synccli.sync` (`fsrc.read()` whole-file copy, 100 MiB / 2,000 files)**: `0.5445 s` (`183.7 MB/s`, `0.27 ms/file`), but unbounded RAM (`O(max_file_size)`).
- **`shutil.copy2` (100 MiB / 2,000 files)**: `1.2204 s` (`81.9 MB/s`, `0.61 ms/file`) — **rejected** because `copystat` adds `~0.39 ms/file` of `chflags`/`xattr` syscalls (`~11.7 s` extra on 30,000 files).
- **1 MiB chunked copy + inline SHA-256 + `os.utime(..., ns=...)` (with directory-creation cache)**:
  - Fixed per-file overhead (`5,000` 1-byte files): `1.1220 s` $\Rightarrow c_{\text{file}} = \mathbf{0.224\text{ ms/file}}$.
  - Byte streaming + SHA-256 throughput (`256 MiB` sequential): `0.1946 s` ($1,315.7\text{ MiB/s}$ warm) $\Rightarrow c_{\text{byte}} = \mathbf{0.760\text{ ms/MiB}}$ (at cold NVMe/SSD write bandwidth of `350 MiB/s`, $c_{\text{byte,cold}} \approx 2.86\text{ ms/MiB}$).
- **Per-file `os.fsync` (200 files)**: `0.0389 s` (`0.19 ms/file` on APFS; `1–5 ms/file` on Linux `ext4` barriers, which would add `30–150 s` on 30,000 files — **avoided** in favor of staging + single `os.sync()` + directory/manifest `fsync`).
- **JSON manifest (`2,000` entries)**: `0.0043 s` dump (`2.15 µs/entry`), `0.0010 s` load (`0.50 µs/entry`).
- **`os.link` (2,000 files, uncached `makedirs`)**: `0.7478 s` (`0.374 ms/file`).
- **`shutil.rmtree` (2,000 files)**: `0.1459 s` (`0.073 ms/file`).

### Derivation for `1 GiB` (`1,024 MiB`) across `F = 30,000` Files

$$T_{\text{full}}(F, B) = T_{\text{scan/stat}}(F) + F \cdot c_{\text{file}} + B \cdot c_{\text{byte}} + T_{\text{manifest}}(F) + T_{\text{commit}}$$

Plugging in $F = 30{,}000$ files, $B = 1{,}024\text{ MiB}$:
1. **Scan + `lstat` (`synccli.build_manifest` baseline)**: $30{,}000 \times 23.8\text{ µs} = \mathbf{0.71\text{ s}}$.
2. **Per-file copy + inline SHA-256 + `utime` + `chmod`**: $30{,}000 \times 0.224\text{ ms} = \mathbf{6.72\text{ s}}$.
3. **Byte transfer + SHA-256**:
   - Warm / page-cache: $1{,}024 \times 0.760\text{ ms} = \mathbf{0.78\text{ s}}$.
   - Cold SSD (`350 MiB/s`): $1{,}024 \times 2.86\text{ ms} = \mathbf{2.93\text{ s}}$.
4. **Manifest serialize + atomic replace (`~3.6 MiB` JSON)**: $30{,}000 \times 2.15\text{ µs} + 0.02\text{ s} \approx \mathbf{0.09\text{ s}}$.
5. **Commit (`os.sync()` + dir `fsync` + atomic `os.rename`)**: $\mathbf{\approx 0.5\text{ s}}$.

- **Derived Total**: **`8.8 s` (warm)** to **`11.0 s` (cold SSD)** for `1 GiB / 30,000 files` (`~14–16 s` at `50,000` files, dominated by the `0.224 ms/file` syscall term).
- **Performance Budget**: **Target $\le 15\text{ s}$ nominal, $\le 30\text{ s}$ hard ceiling** for an initial `1 GiB / 30,000-file` full backup on local SSD.

---

## 9. Scaling Bounds ($N$ Directories, $F$ Files, $B$ Bytes, $K$ Snapshots)

Let:
- $N$: configured source directories (`3` today, `24..48` over time)
- $F = \sum_{i=1}^N F_i$: total regular files across all $N$ directories; $F_{\max} = \max_i F_i$; $F_{\text{changed}} \le F$
- $B = \sum_{i=1}^N B_i$: total logical bytes; $B_{\text{changed}} \le B$
- $K$: retained snapshot count, bounded by $K_{\max} = \text{keep\_last} + \text{keep\_daily} + \text{keep\_weekly}$ (with defaults `10 + 7 + 4`, $K_{\max} \le 21$, and $\ge \text{keep\_min} \ge 1$)
- $M_{\max}$: size of the largest single file

| Dimension | Scaling Formula / Explicit Bound | Numerical Value (`N=3`, `F=30k`, `B=1 GiB`) | Numerical Value (`N=48`, `F=120k`, `F_max=10k`, `B=4 GiB`, `5%` churn) | What Stays Flat |
|---|---|---|---|---|
| **Full backup time** | $0.25\text{ ms}\cdot F + 0.76\text{–}2.86\text{ ms/MiB}\cdot B + 0.5\text{ s}$ | `8.8–10.9 s` | `33.6–42.2 s` (`F=120k`, `B=4 GiB` initial) | $O(1)$ w.r.t. $K$ (reads 0 old snapshots on full); $O(N)$ overhead is only `~1 ms * N` |
| **Incremental run time** | $0.024\text{ ms}\cdot F + 0.374\text{ ms}\cdot (F-F_{\text{chg}}) + 0.224\text{ ms}\cdot F_{\text{chg}} + 2.86\text{ ms/MiB}\cdot B_{\text{chg}} + 0.5\text{ s}$ | `~12.4 s` (`0%` churn, hardlinks) | `~47.9 s` (`F=120k`, `5%` churn = `6k` files / `200 MiB`) | Independent of $K$ (loads only 1 prior snapshot's manifests, never $K$ manifests) |
| **Peak RAM (RSS)** | $\text{15 MiB (Python)} + \mathbf{1\text{ MiB (copy buf)}} + 450\text{ B}\cdot F_{\max} + 512\text{ B}\cdot N$ | `~20.5 MiB` (if `F_max=10k`) | `~20.5 MiB` (sources streamed one-by-one; $F_{\max}=10\text{k}$) | **Flat in $M_{\max}$** (`1 MiB` chunking), **flat in $K$** (`1` source manifest loaded at a time), **near-flat in $N$** (`512 B * N = 24 KiB` at `N=48`) |
| **Disk: steady-state physical** | $B + \sum_{r=1}^{K_{\max}-1} B_{\text{chg}}(r) + K_{\max}\cdot (268\text{ B}\cdot F + 350\text{ B}\cdot N)$ | `~1.17 GiB` + churn (`K=21`, `0%` churn: `169 MiB` metadata/dirents) | `~4.68 GiB` + `20 * 200 MiB` (`= 8.68 GiB` at `K=21`, `5%` churn/run) | Bounded by $K_{\max} \le 21$; `.locks/` stays $\le (1 + K_{\max})$ empty/64B files (`< 4 KiB`) |
| **Disk: transient `.staging/`** | $B_{\text{chg}} + 140\text{ B}\cdot F + 350\text{ B}\cdot N$ | `~4.2 MiB` (`0%` churn) / `1 GiB` (initial) | `~217 MiB` (`5%` churn) | **Zero** duplicate storage of unchanged bytes (`os.link`) |
| **Prune time per run** | $O(K) \text{ scandir} + 0.073\text{ ms/file}\cdot F_{\text{pruned}}$ | `~2.2 s` per expired snapshot (`30k` files) | `~8.8 s` per expired snapshot (`120k` files) | Number of snapshots scanned is $\le K_{\max} + 1$; steady-state prunes $\le 1$ snapshot/run |

---

## 10. CLI Surface, Exit Codes, & Verification Plan

### CLI Commands
- `backupctl backup --config <path> [--wait SEC] [--verify-checksum] [--strict] [--json]`
- `backupctl restore <snap_id> <dest> [--source <source_id>]` (acquires `LOCK_SH` on `.locks/<snap_id>.lock`, validates every path with overridden `safe_snapshot_path`, streams copies)
- `backupctl list [--config <path>] [--json]` (uses `snaputil.list_snapshots` + `snaputil.snapshot_disk_usage` + `st_ino`-deduplicated physical total)
- `backupctl prune [--config <path>] [--dry-run]`
- `backupctl verify [<snap_id>] [--repair]` (verifies SHA-256 of every file against `manifests/<source_id>.json`)

### Exit Codes
- `0` (`EXIT_OK`): Snapshot completed (may include `vanished` source warnings unless `--strict`).
- `2` (`EXIT_CONFIG_OR_USAGE`): Invalid CLI args or config (`source_id` collision, missing `backup_root` parent).
- `3` (`EXIT_LOCKED`): Another writer holds `backup.lock` (and `--wait` expired or was `0`).
- `4` (`EXIT_PARTIAL`): Snapshot published, but $\ge 1$ source files were `unreadable` (`EACCES`/`EIO`) or `--strict` was set with `vanished` files.
- `5` (`EXIT_IO_ERROR`): Destination write error (`ENOSPC`, `EROFS`, `EIO`) or unrecoverable error; `.staging/` cleaned, no partial snapshot published.

### Verification Plan (Extending `test_synccli.py`)
1. **Unit & grounding tests**: Keep `python3 -m unittest` passing for `test_synccli.py`; add tests covering `backupctl`'s overrides (`safe_snapshot_path` traversal rejection for `../` and `/abs`, `is_stale` boundary `mtime == ref_epoch`, `keep_min >= 1` floor).
2. **Concurrency collision tests**: Spawn two parallel `backupctl backup` processes -> verify `EXIT_LOCKED` (or serialized `--wait`) and zero snapshot corruption; hold `LOCK_SH` on `snap-oldest` while running `prune` -> verify `snap-oldest` is skipped.
3. **Fault-injection / crash-recovery tests**: Kill mid-copy (leaving `.staging/*`), truncate `index.json`, corrupt `snap-<latest>/manifest.json` -> verify next run discards `.staging/*`, re-derives `index.json` / `manifest.json` from the tree, reports recovery fields, and succeeds.
4. **Vanishing & unreadable source tests**: Remove a file and `chmod 0o000` another between scan and copy -> verify neither appears in `snap-<id>/sources/` or `manifests/`, both appear in `skipped_files`, and `EACCES` returns exit code `4`.
5. **Incremental & scale smoke test**: Back up $N=3$ dirs, verify unchanged files share `st_ino` (`os.stat().st_ino`) across snapshots while modified files receive new inodes, and verify peak RSS stays below `30 MiB` when backing up a file larger than `50 MiB`.

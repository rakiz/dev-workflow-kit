# `backupctl` Design Document

## 1. Overview & Architecture

`backupctl` is a command-line backup tool that takes point-in-time snapshots of a configured set of $N$ source directories (e.g., `evals/` result trees) into a `backup_root`. It builds directly on `synccli.py` and `snaputil.py` in this repository while overriding specific behaviors where snapshot atomicity, crash recovery, concurrency safety, streaming I/O, or path safety require it.

### Directory Layout under `backup_root`

```text
<backup_root>/
  .backupctl.lock              # Global writer advisory lock (fcntl.flock LOCK_EX)
  .locks/
    snap-20261117-120000-01.lock   # Per-snapshot reader/pruner lock (LOCK_SH / LOCK_EX)
  .staging/
    run-<pid>-<uuid>/          # In-progress snapshot (invisible to snaputil.list_snapshots)
      data/
        <source_id>/           # Snapshot copy/hardlink of each configured source directory
      .backup_manifest.json    # Committed manifest (written atomically before promotion)
      .backup_report.json      # Run metadata (skipped files, recoveries, timings)
  .trash/
    snap-20261110-080000-01/   # Renamed out of snap-* before rmtree
  snap-20261117-120000-01/     # Committed, immutable snapshot (visible to list_snapshots)
    data/
      <source_id>/
    .backup_manifest.json
    .backup_report.json
```

Snapshot directory names follow `snaputil.list_snapshots` (`snaputil.py:8-20`): `snap-YYYYMMDD-HHMMSS-NN` (date, time, and monotonic per-second sequence number `01..99` computed under `.backupctl.lock`).

---

## 2. Grounding: Reused Code & Explicit Overrides

### Reused as-is
- **`synccli.scan_files(root)`** (`synccli.py:10-19`): Walks `root` and returns a sorted list of relative file paths.
- **`synccli.file_state(path)`** (`synccli.py:22-25`): Returns `{"size": st.st_size, "mtime": st.st_mtime}` for change detection.
- **`synccli.changed_files(old_manifest, new_manifest)`** (`synccli.py:36-42`): Identifies new or modified files by comparing `(size, mtime)` dicts.
- **`snaputil.list_snapshots(backup_root)`** (`snaputil.py:8-20`): Lists committed `snap-*` directories in oldest-first sorted order. Because in-progress runs stage under `.staging/` and deleted snapshots move to `.trash/`, `list_snapshots` naturally returns only complete, non-deleted snapshots.
- **`snaputil.snapshot_disk_usage(backup_root, snapshot_name)`** (`snaputil.py:39-51`): Used when reporting the *logical/apparent* size of a single snapshot. (Physical deduplicated disk usage is computed separately by tracking unique `(st_dev, st_ino)` pairs, because `snapshot_disk_usage` counts hardlinked inodes in every snapshot.)

### Explicit Overrides (and Why)
1. **`synccli.build_manifest(root)` (`synccli.py:28-33`)**:
   - *Current behavior*: Calls `file_state(os.path.join(root, rel))` for every path from `scan_files(root)` without catching `OSError`. A file that vanishes between `os.walk` and `os.stat` aborts the entire run with `FileNotFoundError`.
   - *Override*: Wrap `file_state` in `try ... except OSError`, recording vanished/unreadable paths in the run's skip list and omitting them from the manifest.
2. **`synccli.copy_file(src, dst)` (`synccli.py:62-69`)**:
   - *Current behavior*:
     - Line 67: `fdst.write(fsrc.read())` buffers the entire file in RAM (OOM risk on large files).
     - Lines 68–69: `except OSError: pass` silently ignores copy failures and returns `None`, allowing the caller to record an uncopied file in the manifest.
   - *Override*: Stream in fixed `1 MiB` (`1048576` byte) chunks via `shutil.copyfileobj`; return a boolean/status (`copied=True/False`) or raise a structured error, unlink any partial `dst` file on `OSError`, and never add a failed file to the committed manifest.
3. **`synccli.sync(src_root, dst_root, dry_run=False)` (`synccli.py:72-87`)**:
   - *Current behavior*: Reads `.sync_manifest.json` with unguarded `json.load(f)` (line 79, crashes on corrupt JSON), mutates `dst_root` in place, copies `src_manifest` entries that may have failed in `copy_file`, and overwrites `.sync_manifest.json` non-atomically via `open(..., "w")` (lines 85–86).
   - *Override*: Stage into `.staging/run-<pid>-<uuid>/`, hardlink unchanged files from the previous valid snapshot, stream-copy changed files, construct the new manifest *only* from files that succeeded, write `.backup_manifest.json` atomically (`write .tmp` -> `fsync` -> `os.replace`), and atomically `os.rename` the staging dir into `backup_root/snap-...`.
4. **`snaputil.prune_snapshots(backup_root, keep)` (`snaputil.py:23-36`)**:
   - *Current behavior*: Computes `doomed = names[:len(names) - keep]` (line 33; if `keep == 0`, Python slice `names[:len(names)]` deletes *all* snapshots) and calls `shutil.rmtree` directly on `snap-*` (line 35) without checking for active readers.
   - *Override*: Enforce `keep >= 1`; acquire `LOCK_EX | LOCK_NB` on `.locks/<snap_name>.lock` per doomed snapshot (skipping any snapshot currently held by a reader's `LOCK_SH`), `os.rename` to `.trash/<snap_name>`, and then `shutil.rmtree` inside `.trash/`.
5. **`snaputil.safe_snapshot_path(backup_root, snapshot_name, rel_path)` (`snaputil.py:54-63`)**:
   - *Current behavior*: `os.path.normpath(rel_path)` followed by `os.path.join(...)` (lines 62–63) does **not** prevent path traversal despite its docstring: `os.path.normpath("../../etc/passwd")` keeps leading `..`, and an absolute `rel_path` like `"/etc/passwd"` causes `os.path.join` to discard `backup_root` and `snapshot_name` entirely.
   - *Override*: Reject absolute paths (`os.path.isabs(rel_path)`), normalize, reject any path equal to `".."` or starting with `".." + os.sep`, and verify `os.path.realpath(joined)` is strictly prefixed by `os.path.realpath(snapshot_dir) + os.sep`.
6. **`snaputil.is_stale(snapshot_dir, ref_epoch)` (`snaputil.py:66-73`)**:
   - *Current behavior*: Uses `<= ref_epoch` (line 73), contradicting its docstring ("modified at exactly `ref_epoch` is not stale"), and relies on directory `st_mtime` rather than snapshot commit metadata.
   - *Override*: Do not use `is_stale` for retention or freshness; use snapshot name ordering (`snaputil.list_snapshots`) and strict `<` timestamp comparisons against manifest/report timestamps if age-based checks are needed.

---

## 3. Concurrency, Atomicity & Reader Isolation

### Writer-Writer Collisions (Scheduler vs. Human)
- On startup, `backupctl` opens `backup_root/.backupctl.lock` and acquires an advisory exclusive lock via `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` (or blocks up to `--lock-timeout` seconds if requested).
- If the lock is held by another `backupctl` run and timeout expires (or non-blocking mode is used), the second run exits cleanly with a dedicated exit code (`3`, "another backup is already in progress") without touching `.staging/`, `snap-*`, or `.trash/`.
- Sequence numbers (`-NN`) and `.staging/` cleanup run exclusively under `.backupctl.lock`.

### Reader-Writer & Reader-Pruner Isolation
- **Committed snapshots are immutable**: Writers never modify an existing `snap-*` directory. All work happens in `backup_root/.staging/run-<pid>-<uuid>/` (same filesystem as `backup_root` so `os.rename` is an atomic POSIX `rename(2)`).
- **A reader never sees a half-finished snapshot**: Because `snaputil.list_snapshots` (`snaputil.py:18`) only matches `snap-*`, `.staging/` is invisible until the final `os.rename(staging_dir, snap_dir)` completes, after `.backup_manifest.json` has been `fsync`ed and `os.replace`d inside `staging_dir`.
- **Restore/reader locking protocol**: Any reader (`backupctl restore`, restore tooling, or the next `backupctl` run reading the base snapshot) acquires a shared lock `fcntl.flock(LOCK_SH)` on `backup_root/.locks/<snap_name>.lock` before opening files in `snap_name/` and holds it until reading finishes. Readers never contend with writers creating a *new* snapshot.

---

## 4. Crash Safety & Index Recovery

A process may be killed (`SIGKILL`, `SIGINT`, laptop sleep/power loss) at any point:
1. **Crash during staging (before final `os.rename`)**:
   - `snap-*` is untouched; `list_snapshots` does not see `.staging/`.
   - On the next run, after acquiring `.backupctl.lock`, `backupctl` removes all directories under `.staging/` and `.trash/` (guaranteed orphaned because the global writer lock is held). No manual cleanup is required.
2. **Crash during manifest write inside staging**:
   - Staging manifest is written to `.backup_manifest.json.tmp`, `fsync`ed, and atomically `os.replace`d to `.backup_manifest.json`. If interrupted, the staging dir is discarded on next startup.
3. **Corrupt or half-written index in a committed `snap-*` directory**:
   - If `backupctl` encounters a committed snapshot whose `.backup_manifest.json` is missing, truncated, fails `json.loads()`, or fails schema validation (must be a dict mapping valid relative paths to `{"size": int, "mtime": float}`):
     - **Discarded**: The corrupt `.backup_manifest.json` (and any leftover `.backup_manifest.json.tmp`) is removed/replaced.
     - **Re-derived from the tree**: `backupctl` scans `snap-*/data/<source_id>/` using the safe `build_manifest` wrapper (`scan_files` + `file_state` with `OSError` handling) to rebuild the manifest strictly from files actually present in that snapshot's directory tree. Thus, the re-derived index never promises files the snapshot does not contain. It is written atomically via `.tmp` + `fsync` + `os.replace`.
     - **Reported**: The recovery event (`recovered_index: <snap_name>`) is logged to stderr and recorded in the current run's `.backup_report.json`.
     - If the snapshot directory itself is unreadable/empty, `backupctl` falls back to the next-most-recent valid snapshot in `list_snapshots` as the incremental base (or performs a full copy if none exists).

---

## 5. Missing or Unreadable Source Files

Source files can vanish between `scan_files` and `file_state`/`copy_file`, or fail with `PermissionError`/`OSError` when opened. Behavior is identical whether invoked by cron/scheduler or interactively by a person (no stdin prompts):

1. **Snapshot contents**:
   - Any file that raises `OSError` during `file_state` or streaming copy is **omitted** from `staging_dir/data/<source_id>/` and **omitted** from `.backup_manifest.json`.
   - Any partial destination file written before the read error is unlinked immediately.
   - Files deleted from the source since the previous snapshot are naturally absent from the new snapshot.
2. **Run reporting & exit status**:
   - Each skipped file is recorded with its relative path and `errno`/reason in `.backup_report.json` (`skipped_missing`, `skipped_unreadable`) and printed to stderr.
   - Provided at least the run's non-skipped files succeeded, the snapshot is still atomically committed and exits with code **`2`** (completed with warnings/skipped files), distinct from **`0`** (clean success) and **`1`** (fatal error, no snapshot committed).

---

## 6. Incremental Deduplication & Change-Detection Granularity

### Mechanism
- After the first full backup of a source directory, subsequent runs read `.backup_manifest.json` from the latest valid snapshot (under `LOCK_SH`).
- Using `synccli.changed_files(old_manifest, new_manifest)` (`synccli.py:36-42`), `backupctl` partitions files in `new_manifest`:
  - **Unchanged** (`rel in old_manifest and old_manifest[rel] == new_manifest[rel]` and `prev_snap_file` exists): linked into staging via `os.link(prev_snap_file, staging_file)` without copying data blocks. (Falls back to streaming copy if `EXDEV` or `EMLINK` occurs.)
  - **New or changed**: copied via streaming `1 MiB` chunked copy.
- Snapshot data files are `chmod`ed read-only (`0o444` / `a-w`) after creation so accidental in-place edits cannot corrupt hardlinked history across snapshots.

### Granularity & Missed Edits
- **Granularity**: Whole-file `(size, mtime)` metadata (`synccli.file_state`, `synccli.py:22-25`).
- **Edits this granularity can miss**:
  1. **Same-size, same-mtime overwrites**: In-place edits that preserve byte length and restore `mtime` (e.g., `touch -d`, `cp -p`, `tar -p`), or two writes occurring within the filesystem's timestamp resolution / `float64` `st_mtime` precision (~200 ns on APFS, 1–2 s on HFS+/FAT) or during an NTP backward clock step.
  2. **Metadata-only changes**: Permission (`chmod`), ownership (`chown`), extended attribute, or symlink-target changes where target string length and `mtime` are unchanged.
  3. **Dot-directories**: Because `synccli.scan_files` (`synccli.py:14`) filters `not d.startswith(".")`, edits inside hidden subdirectories (e.g., `.cache/`) are not tracked unless `--include-hidden` is explicitly added as an override.

---

## 7. Retention Policy & Safe Deletion

- **Policy**: Keep-last-$K$ (`--keep K`, default `K = 10`), enforced with a hard floor `K >= 1`.
- **Ordering**: Pruning runs **only after** the new snapshot is atomically committed into `backup_root/snap-*`. A failed run never triggers pruning, guaranteeing at least one usable snapshot always remains.
- **Safe deletion while readers are active**:
  1. List committed snapshots with `snaputil.list_snapshots(backup_root)`.
  2. If `len(names) <= K`, do nothing.
  3. For each snapshot in `names[:len(names) - K]` (oldest first):
     - Attempt `fcntl.flock(LOCK_EX | fcntl.LOCK_NB)` on `.locks/<snap_name>.lock`.
     - If `BlockingIOError` (a restore or reader holds `LOCK_SH`): **skip** this snapshot for now; it will be retried on the next run.
     - Otherwise: atomically `os.rename(snap_dir, ".trash/" + snap_name)` (removing it from `list_snapshots` so no new reader can pick it), release the lock, and `shutil.rmtree(".trash/" + snap_name)`.

---

## 8. Performance Budget (Initial Full Backup of ~1 GiB / Tens of Thousands of Files)

### Measured Baseline on This Host
Measured on this machine (`/var/folders/...` APFS, Python 3.10) using `synccli.build_manifest`, `synccli.sync`, `os.link`, and `1 MiB` chunked `shutil.copyfileobj`:
- **Metadata scan (`synccli.build_manifest`)**: `2,000` files in `0.0533 s` → **$26.7\,\mu\text{s/file}$** (~37,500 files/s).
- **Small-file create + write (`synccli.sync`, 2,000 × 10 KiB = 20 MiB)**: `0.5564 s` → **$278\,\mu\text{s/file}$** (~3,600 files/s).
- **Hardlink (`os.link`, 2,000 files)**: `0.7163 s` → **$358\,\mu\text{s/file}$**.
- **Bulk streaming copy (`100 MiB`, `1 MiB` buffer)**: `0.0227 s` → **$4{,}409\text{ MB/s}$** warm page-cache (~500–2,000 MB/s sustained SSD write).

### Derivation for $F = 30{,}000$ files, $B = 1\text{ GiB}$
$$T_{\text{full}}(F, B) = T_{\text{scan}}(F) + T_{\text{file\_ops}}(F) + T_{\text{bytes}}(B) + T_{\text{manifest}}(F)$$

- $T_{\text{scan}} = 30{,}000 \times 26.7\,\mu\text{s} \approx 0.80\text{ s}$
- $T_{\text{file\_ops}} = 30{,}000 \times 250\,\mu\text{s} \approx 7.50\text{ s}$ (open/mkdir/create/close overhead)
- $T_{\text{bytes}} = \frac{1{,}024\text{ MiB}}{500\text{–}4{,}400\text{ MB/s}} \approx 0.23\text{–}2.05\text{ s}$
- $T_{\text{manifest}} \approx 0.15\text{ s}$ (`json.dump` of ~3.6 MiB + `fsync` + `os.replace` + `os.rename`)

**Target Budget**: **$\le 15\text{ s}$ warm / $\le 30\text{ s}$ cold SSD** for a $1\text{ GiB}$, $30{,}000$-file initial backup.

*Key design constraint*: `backupctl` does **not** call `fsync()` on each individual data file ($30{,}000 \times 2\text{ ms} \approx 60\text{ s}$ penalty); it `fsync`s `.backup_manifest.json.tmp` and the staging/backup directories at commit time. (Process kills are still 100% atomic via `.staging/` + `os.rename`; only sudden OS power loss before page-cache flush is bounded by OS writeback.)

---

## 9. Scaling Bounds ($N$ directories, $F$ files, $B$ bytes)

Let $N$ = configured source directories (3 today, up to ~36 over time), $F = \sum_{i=1}^N F_i$ = total files across all $N$ directories, $B = \sum_{i=1}^N B_i$ = total logical bytes, $\Delta F, \Delta B$ = changed/new files and bytes in an incremental run, and $K$ = retention count (`keep`, default 10).

| Dimension | Formula / Bound | Concrete Example ($N=36, F=30{,}000, B=1\text{ GiB}, K=10$) |
| :--- | :--- | :--- |
| **Per-run time (full)** | $O(N + F + B)$: $277\,\mu\text{s}\cdot F + B / R_{\text{write}} + 0.15\text{ s}$ | $\approx 10\text{–}15\text{ s}$ warm ($\le 30\text{ s}$ cold) |
| **Per-run time (incremental)** | $O(N + F + \Delta B)$: $(26.7\,\mu\text{s} + 358\,\mu\text{s})\cdot F + \Delta B / R_{\text{write}}$ (+1 doomed `rmtree` in steady state) | $\approx 11.5\text{ s}$ for 0% change; scales linearly with $F$, **flat in $B$** for unchanged bytes |
| **Peak RAM** | $1\text{ MiB}$ copy buffer + $2 \times (\approx 250\text{ B} \cdot F)$ for `old` + `new` manifests + $\le 4\text{ KiB}$ locks | $\approx 1\text{ MiB} + 15\text{ MiB} = \mathbf{16\text{ MiB}}$ (independent of $B$ and $K$; flat in file size) |
| **Snapshot count on disk** | $K + R_{\text{active}} + (\le 1\text{ in-flight `.staging/`})$ | **Flat at $K = 10$** committed snapshots (plus $R_{\text{active}}$ reader-pinned snapshots) |
| **Physical disk usage** | $B_{\text{base}} + \sum_{r=1}^{K} \Delta B_r + K \cdot (120\text{ B} \cdot F) + \text{staging}(\le \Delta B)$ | $1\text{ GiB} + \sum \Delta B_r + 36\text{ MiB}$ manifests (vs $10\text{ GiB}$ without hardlinks) |
| **Apparent disk usage** (`snaputil.snapshot_disk_usage`) | $K \cdot B$ | $10\text{ GiB}$ |
| **Lock inodes** | $\le K + R_{\text{active}} + 1$ empty `.lock` files | $\le 11 + R_{\text{active}}$ inodes |

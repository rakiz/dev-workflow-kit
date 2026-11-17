# `backupctl` Design (D1)

## 1. Overview & Architecture

`backupctl` creates immutable, point-in-time snapshots of `N` configured source directories (e.g., `evals/` result trees) under a single `<backup_root>`. It builds directly on `synccli.py` (tree scanning, manifest construction, `(size, mtime)` change detection) and `snaputil.py` (snapshot naming, listing, pruning, disk usage, staleness checks), while fixing specific concurrency, atomicity, error-handling, and path-safety gaps in those modules.

### On-Disk Layout

```text
<backup_root>/
  .backupctl.lock                    # Writer mutex (fcntl.flock LOCK_EX)
  .locks/
    snap-20261112-150000-01.lock     # Per-snapshot reader/pruner lock (LOCK_SH / LOCK_EX)
  .staging/
    tmp-<pid>-<epoch_ns>/            # In-progress run; ignored by snaputil.list_snapshots()
      .backup_manifest.json          # Atomic per-snapshot index (written via .tmp + fsync + rename)
      <target_name>/...              # Copied or hardlinked files for each configured source
  .trash/
    snap-20261110-120000-01/         # Doomed snapshots moved out of snap-* before rmtree
  snap-20261112-150000-01/           # Committed, immutable snapshot (matches snaputil.py:11-18)
    .backup_manifest.json
    <target_name>/...
```

Snapshot directory names follow `snaputil.list_snapshots` (`snaputil.py:8-20`): `snap-YYYYMMDD-HHMMSS-NN` (date, time, 2-digit zero-padded sequence number). In-progress and deleting directories live under `.staging/` and `.trash/` so `snaputil.list_snapshots` (`snaputil.py:18`, filtering `entry.name.startswith("snap-") and entry.is_dir()`) never observes incomplete or deleting snapshots.

---

## 2. Grounding in Existing Code & Explicit Overrides

`backupctl` reuses the existing primitives in `synccli.py` and `snaputil.py` wherever they are sound, and explicitly overrides them where their current behavior violates snapshot safety or scale requirements:

| Existing Artifact | Location | Reuse vs. Override | Reason |
|---|---|---|---|
| `synccli.scan_files(root)` | `synccli.py:10-19` | **Reuse** (with missing-root guard) | Walks `root`, skips dot-directories (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`, line 14), returns sorted relative paths. Override: check `os.path.isdir(root)` first because `os.walk` silently yields `[]` on a missing root. |
| `synccli.file_state(path)` | `synccli.py:22-25` | **Reuse** | Returns `{"size": st.st_size, "mtime": st.st_mtime}` via `os.stat(path)`. |
| `synccli.build_manifest(root)` | `synccli.py:28-33` | **Override** | Calls `file_state()` without catching `FileNotFoundError`/`OSError` (line 32). A file vanishing between `scan_files` and `file_state` aborts the run. `backupctl` wraps `file_state()` in `try/except OSError`, omitting vanished/unstatable files and recording them in the run report. |
| `synccli.changed_files(old, new)` | `synccli.py:36-42` | **Reuse** | Returns keys in `new_manifest` that are missing from `old_manifest` or have `old_manifest[rel] != state`. Unchanged keys (`new - changed`) are hardlinked from the previous snapshot; deleted keys (in `old` only) are omitted from the new snapshot. |
| `synccli.copy_file(src, dst)` | `synccli.py:62-69` | **Override** | Three defects: (1) `fdst.write(fsrc.read())` (line 67) buffers the entire file in RAM; (2) `except OSError: pass` (lines 68-69) silently swallows read/write failures, leaving `sync()` to record uncopied or 0-byte files in the manifest; (3) does not preserve `mtime`. `backupctl` streams in `1 MiB` chunks (`shutil.copyfileobj` + `shutil.copystat`), unlinks partial `dst` on error, and returns success/error status so failed files are excluded from `.backup_manifest.json`. |
| `synccli.sync(src, dst, dry_run)` | `synccli.py:72-87` | **Override** | Mutates `dst_root` in-place, reads `dst_manifest_path` without `JSONDecodeError` handling (line 79), and overwrites `.sync_manifest.json` non-atomically via `open(..., "w")` (line 85). Replaced by staged snapshot creation + atomic manifest write + atomic directory rename. |
| `snaputil.list_snapshots(backup_root)` | `snaputil.py:8-20` | **Reuse** (create `backup_root` first) | Lists `snap-*` directories sorted oldest-first. `backupctl` ensures `os.makedirs(backup_root, exist_ok=True)` before calling. |
| `snaputil.prune_snapshots(backup_root, keep)` | `snaputil.py:23-36` | **Override** | Two defects: (1) `keep <= 0` deletes all snapshots (`names[:len(names) - 0]`, line 33); (2) calls `shutil.rmtree` directly on `backup_root/<name>` (line 35), breaking concurrent readers. `backupctl` enforces `keep >= 1`, skips any snapshot with an active reader lock, renames to `.trash/`, then `rmtree`s. |
| `snaputil.snapshot_disk_usage(root, name)` | `snaputil.py:39-51` | **Reuse** (with caveat) | Sums `st_size` of all regular files. Note: reports *logical* size; with hardlinks across snapshots, physical unique disk usage requires deduplicating by `(st_dev, st_ino)`. |
| `snaputil.safe_snapshot_path(root, name, rel)` | `snaputil.py:54-63` | **Override** | **Path traversal bug**: `os.path.normpath(rel_path)` (line 62) does *not* strip leading `..` (`normpath("../../etc/passwd") == "../../etc/passwd"`) and `os.path.join` discards prefixes if `rel_path` is absolute (`"/etc/passwd"`). `backupctl` rejects `os.path.isabs(rel_path)` and verifies `os.path.commonpath([snap_real, os.path.realpath(joined)]) == snap_real`. |
| `snaputil.is_stale(snapshot_dir, ref_epoch)` | `snaputil.py:66-73` | **Reuse** | Checks `st_mtime <= ref_epoch` for age-based retention rules. |

---

## 3. Concurrency Model (Scheduler, Human, and Restore)

1. **Writer-vs-Writer Serialization**:
   - At startup, `backupctl` opens `<backup_root>/.backupctl.lock` and acquires `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` (or blocking with `--wait <sec>`).
   - If another `backupctl` process (scheduler or human) holds the lock, the second process exits cleanly with exit code `2` (`"another backup run is in progress"`) without touching `.staging/`, `.trash/`, or `snap-*`.
   - Two writers never allocate the same sequence number `-NN`, never race on `.staging/`, and never prune concurrently.

2. **Writer-vs-Reader Isolation**:
   - Writers operate exclusively inside `.staging/tmp-<pid>-<epoch_ns>/` until the snapshot is complete. Readers only inspect committed `snap-*` directories returned by `snaputil.list_snapshots`.
   - Before reading any snapshot `<snap_id>`, a restore tool or reader acquires a shared lock `fcntl.flock(fd, fcntl.LOCK_SH)` on `<backup_root>/.locks/<snap_id>.lock` and holds it until the restore finishes.
   - Before deleting a snapshot `<snap_id>`, `backupctl` attempts `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` on `.locks/<snap_id>.lock`. If `BlockingIOError` (`EWOULDBLOCK`) is raised, a reader is active; `backupctl` skips deleting `<snap_id>` in this run and retries on the next run.

3. **Snapshot Immutability**:
   - Files copied into `.staging/` are chmodded read-only (`0o444`, preserving executable bit as `0o555`). Because unchanged files in subsequent runs are hardlinked (`os.link`) to existing snapshot inodes and changed files are always written to a *new* file in `.staging/`, an existing `snap-*` inode is never mutated in place.

---

## 4. Atomic Publication & Crash Recovery

### Atomic Commit Protocol
1. Create `.staging/tmp-<pid>-<epoch_ns>/`.
2. For each configured directory `<target>`:
   - Scan and copy/hardlink files into `.staging/<tmp>/<target>/`.
   - Record only successfully materialized files in the manifest dict `{target: {relpath: {"size": ..., "mtime": ...}}}`.
3. Write `.staging/<tmp>/.backup_manifest.json.tmp`, `flush()`, `os.fsync()`, and `os.rename()` to `.staging/<tmp>/.backup_manifest.json`.
4. `os.fsync()` the staging directory fd.
5. Choose `snap-YYYYMMDD-HHMMSS-NN` (incrementing `NN` past any existing `snap-*` with the same timestamp) and `os.rename()` `.staging/<tmp>` -> `<backup_root>/snap-YYYYMMDD-HHMMSS-NN`.
6. `os.fsync()` `<backup_root>` directory fd.

Because `os.rename()` on the same filesystem is atomic and `snaputil.list_snapshots` (`snaputil.py:18`) only lists `snap-*` directories, **no reader ever sees an incomplete snapshot**, a mix of two runs, or an index promising files that do not exist.

### Crash & Corrupt-Index Recovery (No Manual Cleanup)
On startup (while holding `.backupctl.lock`):
1. **Orphaned staging directories**: Remove all entries in `<backup_root>/.staging/` via `shutil.rmtree`. Anything in `.staging/` was from a killed/crashed run and is discarded.
2. **Interrupted deletions**: Remove all entries in `<backup_root>/.trash/` via `shutil.rmtree`.
3. **Corrupt or half-written index in an existing `snap-*` directory**:
   - When selecting the newest `snap-*` as the incremental base, `backupctl` loads `<snap>/.backup_manifest.json` and validates its schema (`version`, `targets` dict, `{size: int, mtime: float}` entries).
   - **If `json.JSONDecodeError`, `OSError` (missing manifest), or schema validation fails**:
     - **Discarded**: The corrupt `.backup_manifest.json` is discarded (unlinked/replaced).
     - **Re-derived from the tree**: `backupctl` runs `synccli.build_manifest()` (`synccli.py:28-33`, with `OSError` guard) over each `<target>` subdirectory inside `<snap>`, re-deriving `{relpath: {"size": ..., "mtime": ...}}` from the files actually present on disk, and atomically writes the repaired `.backup_manifest.json` (`.tmp` + `fsync` + `rename`).
     - **Reported**: `backupctl` logs a structured warning to `stderr` and includes `recovered_manifests: [snap_id]` in the run summary, then proceeds normally using the re-derived manifest as the incremental base.
     - If the `snap-*` directory itself has no valid target subdirectories (empty/unusable), it is moved to `.trash/` (assuming `>= 1` other valid snapshot remains, or replaced after the new full snapshot commits) and `backupctl` falls back to the next-oldest valid snapshot or a full backup.

---

## 5. Vanishing or Unreadable Source Files

Both scheduler-triggered and human-triggered runs execute the exact same code path:
- **Vanished between listing and stat/copy (`FileNotFoundError` / `ENOENT`)**:
  - Caught in `build_manifest` override and `copy_file` override.
  - The file is **omitted** from `.staging/<tmp>/<target>/` and **omitted** from `.backup_manifest.json`.
  - Appended to `skipped_vanished`.
- **Unreadable during copy (`PermissionError` / `EACCES` / `EIO`)**:
  - Any partially written destination file in `.staging/` is immediately unlinked (`os.unlink`).
  - The file is **omitted** from `.backup_manifest.json`.
  - Appended to `skipped_unreadable` with `(relpath, reason)`.
- **Reporting & Exit Code**:
  - The snapshot still commits atomically with all readable files, remaining 100% self-consistent.
  - The run prints a summary listing `copied`, `hardlinked`, `skipped_vanished`, and `skipped_unreadable`.
  - Exit code is `0` when all files succeeded, and `3` (`PARTIAL_SUCCESS`) when one or more files were skipped due to vanishing/unreadable errors (identical for scheduler and human).

---

## 6. Retention Policy & Safe Deletion

- **Policy**: Retain the newest `keep` complete snapshots (default `keep = 14`, configurable via `--keep K` with a hard floor `K >= 1`), optionally combined with age pruning via `snaputil.is_stale(snapshot_dir, ref_epoch)` (`snaputil.py:66-73`) subject to the same `K >= 1` floor so the newest valid snapshot is **never** deleted.
- **Safe Deletion**:
  1. List snapshots oldest-first via `snaputil.list_snapshots(backup_root)` (`snaputil.py:8-20`).
  2. Identify `doomed = names[:len(names) - keep]` (empty if `len(names) <= keep`).
  3. For each `snap_id` in `doomed`:
     - Try `fcntl.flock(LOCK_EX | LOCK_NB)` on `.locks/<snap_id>.lock`.
     - If locked by an active reader (`LOCK_SH`), skip it this pass.
     - Atomically `os.rename(<backup_root>/<snap_id>, <backup_root>/.trash/<snap_id>)` so no new reader or `list_snapshots()` call can see it.
     - Release the lock, remove `.locks/<snap_id>.lock`, and run `shutil.rmtree(<backup_root>/.trash/<snap_id>)`.
  - Unlinking hardlinked files in `.trash/` only decrements `st_nlink`; newer snapshots sharing those inodes keep their data intact.

---

## 7. Incremental Change Detection & Granularity Limits

- **Granularity**: `backupctl` uses `synccli.file_state(path)` (`synccli.py:22-25`) and `synccli.changed_files(old_manifest, new_manifest)` (`synccli.py:36-42`), which compare `(st_size, st_mtime)` (byte size and float modification time in seconds).
- **Unchanged files**: For `rel` in `new_manifest` not in `changed_files`, `backupctl` creates a hardlink `os.link(prev_snap_file, staging_file)` instead of copying bytes. If `os.link` fails with `EXDEV` (cross-filesystem) or `EMLINK` (link limit reached) or `ENOENT`, it falls back to streaming copy.
- **Edits this granularity can miss**:
  1. **Same-size edits within the same `mtime` tick**: Overwriting bytes in place without changing `st_size` within the filesystem's timestamp resolution (or float `st_mtime` precision) yields an identical `(size, mtime)` pair.
  2. **Explicit timestamp preservation or clock rollback**: Tools that restore `mtime` (`utime`, `touch -d`, `tar`) after modifying content of the same size, or backward NTP clock steps during writes, produce matching `(size, mtime)`.
  3. **Metadata-only changes**: Permission (`chmod`), ownership, or xattr changes do not alter `st_size` or `st_mtime` and are not detected.

---

## 8. Performance Budget (Initial Full Backup: ~1 GB, ~30,000 Files)

### Measured Baseline (This Repo & Host)
Running `python3 -m unittest` passes all 6 existing tests in `0.006 s`. Direct microbenchmarks on this host using `synccli.py` and `shutil.copy2` measured:
- `synccli.build_manifest` (walk + `stat` on 2,000 files): **`0.067 s`** (`33.5 µs/file`, `~29,850 files/s`).
- `synccli.sync` (first full copy of 2,000 × 10 KiB files = 20 MB): **`0.770 s`** (`385 µs/file`, `~26 MB/s`, dominated by per-file `open`/`makedirs`/`close` syscalls).
- `shutil.copy2` (50 × 1 MiB files = 50 MB): **`0.059 s`** (`846 MB/s` with APFS clone/copyfile; conservative physical NVMe/SSD sequential write budget: `200–500 MB/s`, i.e. `2.0–5.0 ms/MB`).
- `os.link` (2,000 hardlinks): **`0.936 s`** (`468 µs/link`, `2,136 links/s`, 0 data bytes copied).

### Derivation for `F = 30,000` Files, `B = 1,024 MB` (~1 GB)
1. **Scan + `stat`** (`synccli.build_manifest`): `30,000 × 33.5 µs = 1.01 s`
2. **Per-file create/open/close + `makedirs` overhead**: `30,000 × 350 µs = 10.50 s` (caching created parent dirs avoids redundant `os.makedirs` stat calls).
3. **Bulk byte transfer (`1,024 MB`)**:
   - APFS/CoW local disk (`~846 MB/s`): `1.21 s`
   - Physical SSD copy (`200–500 MB/s`): `2.05 s – 5.12 s`
4. **Manifest serialization (`~160 B/entry × 30,000 ≈ 4.8 MB` JSON) + commit `fsync`**: `~0.20 s` (we `fsync` the manifest and staging/root directories rather than calling per-file `fsync` 30,000 times, which would add `15–60 s`).

**Total Initial Full Backup Budget**: **`~13–17 s` typical, `≤ 30 s` hard ceiling** on local SSD for `1 GB` / `30,000` files.
*(For comparison, a subsequent incremental run with 1% changed files — `300` copied, `29,700` hardlinked — takes `1.01 s` scan + `13.90 s` hardlinks + `0.12 s` copy ≈ `~15 s`.)*

---

## 9. Scaling Bounds (`N` Directories, `F` Total Files, `B` Bytes, `K` Retained Snapshots)

Let `N` = configured source directories (`3` today, `≤ 50` over time), `F` = total files across all `N` directories, `F_changed` = changed/new files in a run (`B_changed` bytes), and `K` = retained snapshots (e.g. `14`).

- **Per-Run Work (CPU & I/O)**:
  - Initial full run: `O(F + B)` — specifically `~385 µs × F + (1.2 to 5.0 ms/MB) × B_MB`.
  - Incremental run: `O(F + B_changed)` — `~35 µs × F` (scan/stat) + `~468 µs × (F - F_changed)` (hardlinks) + `~385 µs × F_changed + (1.2 to 5.0 ms/MB) × B_changed_MB` (copies). Independent of `K`.
  - Retention pruning: `O(F)` per expired snapshot deleted (`1` snapshot deleted per run in steady state).
- **Peak Memory (RAM)**:
  - Manifests held in memory: `~400 bytes/file × F` (e.g., `12 MiB` at `F = 30,000`, `40 MiB` at `F = 100,000`). Processing `N` directories sequentially keeps only the current target's `src_manifest` + `old_manifest` active if needed, bounding manifest RAM to `O(F_max_target)` (`≤ 40 MiB`).
  - Streaming copy buffer: **`1 MiB` (`1,048,576 B`) constant**, independent of `B_max` (overriding `synccli.copy_file`'s unbounded `fsrc.read()` at `synccli.py:67`).
  - Total peak RSS for `N = 50, F = 100,000`: **`< 80 MiB`**.
- **Disk Usage**:
  - `B_initial + Σ_{i=1..K} B_changed,i + K × (160 B × F)` bytes (e.g. `~4.8 MB` manifest per `30,000`-file snapshot).
  - Unchanged files across `K` snapshots consume **`0` additional data blocks** (1 directory entry, `~64–256 B` metadata per hardlink).
  - Transient `.staging/` overhead during a run: at most `1` snapshot's delta (`B_changed + 160 B × F`).
- **What Stays Flat (`O(1)` in `N`, `F`, `B`, `K`)**:
  - Copy I/O buffer size: **`1 MiB`**.
  - Lockfiles at rest: **`1`** writer lock (`.backupctl.lock`) + **`≤ K`** reader lockfiles (`.locks/*.lock`).
  - Data block duplication for unchanged files across snapshots: **`0 bytes`**.

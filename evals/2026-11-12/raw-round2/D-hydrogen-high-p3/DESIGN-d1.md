# `backupctl` Design Specification (D1)

## 1. Overview and Scope

`backupctl` is a command-line backup tool that creates immutable, point-in-time snapshots of $N$ configured `evals/` result directories under a single `backup_root` (`N = 3` initially, scaling to `N = 24–50`). It lives alongside `synccli.py` and `snaputil.py` in this repository and reuses their working primitives while fixing concurrency, atomicity, memory, security, and crash-recovery gaps that make naive directory syncing unsafe for live evaluation trees.

### CLI & Configuration Surface

`backupctl` exposes non-interactive subcommands with identical behavior whether invoked by a scheduler (cron/launchd) or manually by a person:

```text
backupctl run     --config PATH [--backup-root PATH] [--non-blocking | --lock-timeout SEC] [--checksum] [--dry-run] [--json]
backupctl list    --backup-root PATH [--json]
backupctl verify  --backup-root PATH [SNAP_ID] [--checksum] [--json]
backupctl restore --backup-root PATH SNAP_ID --target ID --dest PATH [--json]
backupctl prune   --backup-root PATH [--keep-recent 7 --keep-daily 14 --keep-weekly 8] [--json]
backupctl repair  --backup-root PATH [SNAP_ID] [--json]
```

*Note:* If `--dry-run` is combined with `--json`, `backupctl run` executes scan + diff against the newest verified snapshot without modifying `backup_root` (except acquiring `.backupctl.lock` briefly or reading under `LOCK_SH`).

### Deterministic Exit Codes (Identical for Scheduler and Human)

| Exit Code | Meaning |
|---|---|
| `0` | Snapshot published (or dry-run complete) with zero unreadable files; transient vanished files allowed and logged. |
| `2` | Fatal configuration, invalid target, or I/O failure on `backup_root` (no snapshot published; existing snapshots untouched). |
| `3` | Snapshot published with **partial warnings** (one or more unreadable source files skipped and excluded from manifest). |
| `4` | Lock contention (`--non-blocking` or `--lock-timeout` expired while another `backupctl` writer held `.backupctl.lock`). |

---

## 2. On-Disk Layout

```text
<backup_root>/
  .backupctl.lock                 # Single-writer advisory flock (never unlinked while held)
  .latest_index.json              # Optional fast pointer cache to newest verified snap-*
  .locks/
    snap-20261113-160000-0001.lock # Per-snapshot reader/pruner flock (LOCK_SH vs LOCK_EX|LOCK_NB)
  .staging-<run_id>/              # Uncommitted run workspace (ignored by snaputil.list_snapshots)
  .staging-<run_id>.lock          # Per-staging flock; released automatically by OS if process dies
  .trash/
    snap-20261001-120000-0001/    # Atomic hide-before-delete area for pruning
  .quarantine/
    snap-20261112-090000-0001/    # Corrupt/uncommitted snap-* isolated during recovery
  snap-YYYYMMDD-HHMMSS-NNNN/      # Committed, immutable snapshot (4-digit zero-padded seq)
    .COMPLETE                     # Commit marker written & fsynced inside staging before rename
    manifest.json                 # Snapshot metadata, target map, warnings, payload_sha256
    targets/
      <target_id>.json            # Per-target file manifest + payload_sha256
    data/
      <target_id>/
        <rel_path>...             # Full standalone POSIX tree (read-only hardlinked/copied files)
```

### Design Choices in the Layout

1. **Compatible with `snaputil.list_snapshots` (`snaputil.py:8-20`):** Only committed snapshots start with `"snap-"`. Staging (`.staging-*`), locks (`.locks`), trash (`.trash`), and quarantine (`.quarantine`) use leading dots so `snaputil.list_snapshots` ignores them (`snaputil.py:18`).
2. **4-digit sequence number (`-NNNN`):** `snaputil.list_snapshots` (`snaputil.py:20`) sorts names lexicographically via `sorted(names)`. Zero-padding the sequence to 4 digits (`0001`–`9999`) prevents `"snap-...-100" < "snap-...-99"` ordering bugs when multiple runs complete within the same second.
3. **Per-target sub-manifests (`targets/<target_id>.json`):** Each configured source directory maps to a validated slug `target_id` (e.g., `eval_a`, preventing collisions if two configured paths share a basename like `/a/evals` and `/b/evals`). Splitting file entries into per-target JSON files allows `backupctl` to stream one target at a time, bounding peak RAM to the largest single directory rather than all $N$ directories combined (Section 9).

---

## 3. Codebase Grounding: Reuse and Explicit Overrides

`backupctl` builds directly on `synccli.py` and `snaputil.py`. Every existing function is either reused as designed or explicitly overridden with the exact line-level reason below.

### Reused Components

| Existing Artifact | Role in `backupctl` | Notes / Constraints |
|---|---|---|
| `snaputil.list_snapshots(backup_root)` (`snaputil.py:8-20`) | Enumerate committed `snap-*` directories oldest-first. | Works unchanged because all non-snapshot directories begin with `.` and sequence numbers are fixed-width 4 digits (`-NNNN`). |
| `synccli.changed_files(old_manifest, new_manifest)` (`synccli.py:36-42`) | Identify added or modified files between `old_manifest` and `new_manifest`. | Must be called with **projected stat-state dicts** (excluding `sha256`), because `line 40` (`old_manifest[rel] != state`) would mark every file changed if `old_manifest` includes `sha256` and `new_manifest` does not yet. Deletions are computed separately. |
| `synccli.collect_stale(items, seen=None)` (`synccli.py:45-59`) | Filter stale entries (`(path, fresh)` pairs not in `seen` and `not fresh`). | Unused by `synccli.sync` today (`test_synccli.py:21-32` tests it). Reused for identifying stale/removed paths and dead staging cleanup; callers must pass an indexable sequence because `lines 55-56` use `len(items)` and `items[i]`. |

### Explicit Overrides of Existing Code

| Existing Artifact & Location | Current Behavior / Defect | `backupctl` Override & Reason |
|---|---|---|
| `synccli.scan_files(root)` (`synccli.py:10-19`) & `synccli.build_manifest(root)` (`synccli.py:28-33`) | `build_manifest` walks the tree twice (`scan_files` calls `os.walk`, then loops calling `file_state`). `os.stat` follows file symlinks (crashing on broken symlinks), includes FIFOs/sockets, and raises unhandled `OSError` if a file vanishes between scan and `stat`. | **Override with single-pass `os.scandir(follow_symlinks=False)`:** Walks each directory once, inspects `entry.is_file(follow_symlinks=False)` and `entry.stat(follow_symlinks=False)`, skips FIFOs/sockets/devices, records symlinks explicitly (target string only, never traversed), and catches `FileNotFoundError`/`PermissionError` per entry. |
| `synccli.file_state(path)` (`synccli.py:22-25`) | Returns `{"size": st.st_size, "mtime": st.st_mtime}` using float seconds via `os.stat`. Float `st_mtime` loses precision below ~256 ns in IEEE-754 JSON; misses `utime` backdating and `chmod`. | **Override with `backup_file_state(stat_result)`:** Records integer `size`, `mtime_ns`, `ctime_ns`, `ino`, and `mode` from `lstat`, plus `sha256` populated after copy/link. |
| `synccli.copy_file(src, dst)` (`synccli.py:62-69`) | (1) `fdst.write(fsrc.read())` (`line 67`) buffers the entire file in RAM ($O(\text{file size})$). (2) Opens `dst` with `"wb"` *before* reading `src` and catches `except OSError: pass` (`lines 66-69`), leaving 0-byte/truncated files behind and masking failure. | **Override with `stream_copy_and_hash(src, dst_tmp, buf_size=1048576)`:** Streams in fixed **1 MiB** chunks while updating `hashlib.sha256` into `<dst>.tmp`. On any `OSError`, unlinks `<dst>.tmp` and propagates failure to the caller so partial files never enter the snapshot. Strips write bits (`mode & ~0o222`) on final destination. |
| `synccli.sync(src_root, dst_root, dry_run)` (`synccli.py:72-87`) & `MANIFEST_NAME` (`synccli.py:7`) | (1) Mutates `dst_root` in place (no point-in-time snapshots, never removes deleted files). (2) Overwrites `.sync_manifest.json` non-atomically (`lines 85-86`) with no error handling on `json.load` (`line 79`). (3) Writes `src_manifest` even for files that failed `copy_file` (`lines 83-86`), so the manifest falsely promises missing files and never retries them. | **Override with staged `backup_run()`:** Writes to `.staging-<run_id>`, only adds files to `targets/<id>.json` after copy/link succeeds, writes manifests with SHA-256 envelope via `.tmp` + `fsync` + `os.replace`, and publishes via atomic directory rename. |
| `snaputil.prune_snapshots(backup_root, keep)` (`snaputil.py:23-36`) | (1) When `keep <= 0`, `names[:len(names) - keep]` (`line 33`) deletes **all** snapshots, leaving zero usable snapshots. (2) Calls `shutil.rmtree` directly on `snap-*` (`line 35`), racing with active readers and leaving half-deleted `snap-*` directories on crash. (3) Supports only flat count retention. | **Override with `safe_prune_snapshots()`:** Enforces `min_keep >= 1` verified complete snapshot; checks reader locks (`LOCK_EX \| LOCK_NB` on `.locks/<snap>.lock`); moves doomed snapshots atomically to `.trash/<snap>` before `shutil.rmtree`; implements tiered retention (Section 7). |
| `snaputil.snapshot_disk_usage(backup_root, snapshot_name)` (`snaputil.py:39-51`) | Sums `os.stat(...).st_size` (`line 50`) for every file in one snapshot. Does not deduplicate hardlinked `(st_dev, st_ino)` across snapshots, overstating multi-snapshot disk usage by up to $K\times$, and crashes on broken symlinks. | **Override with `physical_disk_usage(backup_root)`:** Uses `lstat`, deduplicates across snapshots by `(st_dev, st_ino)`, and reports both logical snapshot size and physical allocated bytes (`st_blocks * 512`). |
| `snaputil.safe_snapshot_path(backup_root, snapshot_name, rel_path)` (`snaputil.py:54-63`) | **Security bug:** Docstring (`lines 58-60`) claims `".."` segments are normalized away so paths cannot climb out. Actually, `os.path.normpath("../../etc/passwd")` remains `"../../etc/passwd"`, and `os.path.join(base, snap, "/etc/passwd")` discards `base/snap` completely. | **Override with `strict_snapshot_path()`:** Rejects leading `/`, rejects any `..` path component before join, resolves `os.path.realpath`, and asserts `os.path.commonpath([snap_root_real, resolved]) == snap_root_real`. |
| `snaputil.is_stale(snapshot_dir, ref_epoch)` (`snaputil.py:66-73`) | **Off-by-one bug:** Code `<= ref_epoch` (`line 73`) returns `True` (stale) when `mtime == ref_epoch`, contradicting docstring `line 71` ("modified at exactly `ref_epoch` is not stale"). Also checks mutable directory `mtime` instead of manifest completion timestamp. | **Override with manifest timestamp check:** Reads `created_at_utc` from verified `manifest.json` and compares strictly `< ref_epoch`. |

---

## 4. Concurrency Model (Scheduler, Manual Runs, and Restore)

### 4.1 Two Backup Runs Colliding (Scheduler + Person)

- **Serialization via `.backupctl.lock`:** Every mutating `backupctl` invocation (`run`, `prune`, `repair`) opens `<backup_root>/.backupctl.lock` (`O_CREAT | O_RDWR`) and acquires an advisory `fcntl.flock(fd, LOCK_EX)`.
  - Scheduler invocations pass `--non-blocking` (`LOCK_EX | LOCK_NB`): if a manual run is active, the scheduler exits cleanly with code `4` rather than piling up queued cron processes.
  - Manual invocations default to waiting (`--lock-timeout 300`, polling or `SIGALRM`-bounded `flock`) with a single-line notice naming the lock holder PID (written to `.backupctl.lock` after acquisition) or exiting `4` on timeout.
- **Isolated staging:** Even before/during work, each run creates a unique `.staging-<timestamp>-<pid>-<rand4>` protected by its own `LOCK_EX` on `.staging-<run_id>.lock`. No existing `snap-*` directory is ever modified in place.

### 4.2 Concurrent Restore While a Backup Run Writes (and Prunes)

1. **Writer never touches existing snapshots:** While `backupctl run` copies/links into `.staging-<run_id>`, any restore reading `snap-A` sees an untouched, read-only directory tree.
2. **Cooperating reader lock protocol (`.locks/<snap_name>.lock`):**
   - Before reading `snap-A`, `backupctl restore` (and external restore tooling following the contract) opens `<backup_root>/.locks/<snap_name>.lock` and holds `fcntl.flock(fd, LOCK_SH)` until restore finishes.
   - `backupctl run` also holds `LOCK_SH` on `snap_prev`'s lock while reading `snap_prev` as its incremental base.
   - Before pruning `snap-A`, `backupctl` attempts `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on `.locks/<snap_name>.lock`. If `BlockingIOError` is raised, `snap-A` is **pinned** for this run: deletion is deferred to the next run and reported under `deferred_locked_snapshots`.
   - Note why lockfiles live in `.locks/` rather than inside `snap-A/`: renaming `snap-A` to `.trash/snap-A` or unlinking it while readers hold locks inside `snap-A/` would sever path-to-inode correspondence for subsequent readers.
3. **Uncooperative external readers (e.g., plain `cp -r` / `tar`):**
   - Pruning never unlinks files directly inside `snap-A`. Instead, `os.rename(snap-A, .trash/snap-A)` removes `snap-A` from directory listings atomically, and on POSIX any file already opened by `cp`/`tar` retains its inode/data until its FD closes.
   - Additionally, `backupctl` enforces a two-phase `.trash/` grace period (`--trash-grace-seconds`, default `3600` s): `prune` moves doomed snapshots to `.trash/<snap_name>`, and only `rmtree`s entries in `.trash/` older than the grace window (unless disk emergency override `--purge-trash`). *Boundary:* an uncooperative reader that ignores `.locks/` and pauses mid-directory-walk longer than the grace window cannot be detected portably in userspace without cooperative `LOCK_SH` or filesystem-level snapshots.

---

## 5. Atomic Publication and Crash / Index Recovery

### 5.1 Atomic Commit Sequence

Readers never check an "in-progress" flag because an unpublished snapshot does not exist at any `snap-*` path:

1. Acquire `.backupctl.lock` (`LOCK_EX`).
2. Run startup recovery (Section 5.2).
3. Create `.staging-<run_id>/data/` and `.staging-<run_id>/targets/`, holding `.staging-<run_id>.lock`.
4. For each configured target directory $i \in [1..N]$:
   - Scan source via `scandir(follow_symlinks=False)`.
   - Compare against `snap_prev/targets/<target_id>.json` (if a verified `snap_prev` exists).
   - Hardlink unchanged files from `snap_prev`; stream-copy + SHA-256 changed/new files into `<dst>.tmp` and `os.replace` to `<dst>` (`mode & ~0o222`).
   - Record only succeeded entries in memory; record vanished/unreadable files in target warnings.
   - Write `.staging-<run_id>/targets/<target_id>.json.tmp` with envelope `{"payload": ..., "sha256": "<hex>"}`, `os.fsync`, `os.replace` to `targets/<target_id>.json`, then drop target $i$'s dicts from memory.
5. `os.fsync` newly created/copied files and target directories under `.staging-<run_id>/`. (See Section 8 for `fsync` cost/batching trade-off.)
6. Write `.staging-<run_id>/manifest.json.tmp` (`status: "complete"`, `created_at_utc`, target summary, aggregate warnings, `targets_sha256` map, envelope `payload_sha256`), `os.fsync`, `os.replace` to `manifest.json`.
7. Write and `os.fsync` `.staging-<run_id>/.COMPLETE` (JSON containing `snapshot_id` and `manifest_sha256`), then `os.fsync` the `.staging-<run_id>` directory FD.
8. **Single atomic commit point:** `os.replace(".staging-<run_id>", "snap-YYYYMMDD-HHMMSS-NNNN")`, followed by `os.fsync` on the `backup_root` directory FD.
9. Atomically update `.latest_index.json.tmp` -> `.latest_index.json`.

### 5.2 Crash and Corrupt-Index Recovery Protocol

A run can be killed (`SIGKILL`, `SIGINT`, laptop sleep/power loss) at any line above. On startup, after acquiring `.backupctl.lock`, `backupctl` executes recovery automatically before starting the new snapshot:

| Failure / Leftover Found | What is Discarded | What is Re-derived from the Tree | What the Run Reports |
|---|---|---|---|
| **Abandoned `.staging-*` dir** (`.staging-*.lock` acquirable with `LOCK_EX \| LOCK_NB`, meaning owner died) | Entire `.staging-<run_id>/` directory and its `.staging-<run_id>.lock` are removed (`shutil.rmtree`). Existing `snap-*` are untouched. | Nothing needed; no `snap-*` was committed. | `"recovered_abandoned_staging": ["<run_id>", ...]` |
| **Leftover `.trash/*` dir** (crash during prior prune) | Entries whose grace period expired (or during explicit `prune`) are `rmtree`'d. | Nothing needed; already removed from `snaputil.list_snapshots`. | `"swept_trash": ["<snap>", ...]` |
| **Corrupt / half-written `.latest_index.json`** (invalid JSON, SHA-256 mismatch, or missing target `snap-*`) | Corrupt `.latest_index.json` and any `.latest_index.json.tmp` are unlinked. | Re-derived by calling `snaputil.list_snapshots(backup_root)` newest-first, verifying `.COMPLETE` + `manifest.json` SHA-256, and rewriting `.latest_index.json` atomically pointing to the newest verified `snap-*`. | `"rebuilt_root_index": {"from_snapshot": "<snap>", "reason": "..."}` |
| **`snap-*` with missing `.COMPLETE` AND missing/corrupt `manifest.json`** (uncommitted/broken tree, e.g., power loss or legacy `synccli` partial directory) | Untrusted `snap-*` is moved via `os.rename` to `.quarantine/<snap_id>` (never served to readers or used as incremental base). | Next run falls back to the preceding verified `snap-*` from `snaputil.list_snapshots` (or performs a full backup if none remain). | `"quarantined_snapshots": ["<snap_id>"]`, `"incremental_base": "<fallback_snap_or_full>"` |
| **`snap-*` with valid `.COMPLETE` marker, but corrupt/half-written `manifest.json` or `targets/<id>.json`** (or explicit `backupctl repair`) | Corrupt `manifest.json` / `targets/<id>.json` and any `*.tmp` inside `snap-*` are discarded. | **Re-derived from `snap-<id>/data/`:** Walks `snap-<id>/data/<target_id>/` via `os.scandir`, recomputes `size`, `mtime_ns`, `ctime_ns`, `mode`, and `sha256` for every regular file, maps `target_id` back to configured `source_path`, and atomically writes repaired `targets/<id>.json` and `manifest.json` flagged `"repaired_from_tree": true`. *(Note: original source `ino` and pre-crash `warnings` cannot be recovered from destination files; next incremental run will detect mismatching `ino` against source and verify/re-link or copy.)* | `"repaired_indexes": [{"snapshot": "<snap_id>", "files_reindexed": N, "warning": "source inodes reset; next run may re-verify files"}]` |

---

## 6. Vanished and Unreadable Source Files

`synccli.build_manifest` (`synccli.py:28-33`) crashes on missing files, and `synccli.copy_file` (`synccli.py:66-69`) leaves 0-byte files while `synccli.sync` (`synccli.py:85-86`) falsely records them in `.sync_manifest.json`. `backupctl` enforces strict manifest honesty with identical rules for scheduler and manual runs:

1. **File vanishes between `scandir` and `stat`/open/read (`FileNotFoundError` / `ENOENT`):**
   - Any `<dst>.tmp` created so far is unlinked immediately.
   - The file is **absent** from `snap-<id>/data/<target_id>/` and **absent** from `targets/<target_id>.json`'s `files` map.
   - Recorded in `targets/<target_id>.json` and `manifest.json` under `warnings.vanished` (`[{"rel_path": ..., "stage": "stat"|"copy"}]`).
   - Run proceeds and exits `0` (unless `--strict-vanished` is set), reporting `vanished_count` in stdout/JSON.
2. **File is unreadable (`PermissionError` / `EACCES`, `OSError` / `EIO`):**
   - Any `<dst>.tmp` is unlinked immediately (never leaving a 0-byte/truncated destination file).
   - The file is **absent** from `snap-<id>/data/<target_id>/` and **absent** from `targets/<target_id>.json`'s `files` map—so the snapshot index never promises a file the snapshot does not contain, and the next run automatically retries copying it.
   - Recorded in `manifest.json` under `warnings.unreadable` (`[{"rel_path": ..., "errno": ..., "error": ...}]`).
   - Snapshot of all readable files is still published atomically; the run prints a clear summary to `stderr` (and `warnings` in `--json`) and exits **`3` (`EXIT_PARTIAL`)** identically whether triggered by cron or interactively.

---

## 7. Incremental Detection, Granularity, and Retention Policy

### 7.1 Incremental Unchanged-File Recognition and Hardlinking

When a verified `snap_prev` exists, `backupctl` loads `snap_prev/targets/<target_id>.json` one target at a time:
- **Unchanged predicate:** A regular source file is treated as unchanged iff:
  1. `rel_path` exists in `snap_prev`'s `files` map,
  2. Source `(size, mtime_ns, ctime_ns, ino, mode)` matches `snap_prev[rel_path]` (`ino` and `ctime_ns` are source-side metadata stored in `targets/<target_id>.json`),
  3. `--checksum` is not enabled (if `--checksum` is set, source `sha256` is computed and compared against `snap_prev[rel_path]["sha256"]`), and
  4. The backing file `snap_prev/data/<target_id>/<rel_path>` exists and its destination `st_size` matches.
- **Hardlink copy:** Unchanged files are linked via `os.link(prev_snap_file, staging_file)` and inherit the previous `sha256` without reading source bytes. If `os.link` fails with `EXDEV` (cross-device) or `EMLINK` (hardlink count limit, e.g., >32,000/65,000 snapshots sharing one inode), `backupctl` falls back transparently to `stream_copy_and_hash`.
- **Snapshot immutability:** Because the initial snapshot copied files from source (creating new destination inodes), hardlinking `snap_prev -> snap_new` never shares an inode with the live source directory. Stripping write bits (`mode & ~0o222`) on snapshot files protects against accidental in-place edits across snapshots while preserving original `mode` in `targets/<target_id>.json` for restore.

### 7.2 Granularity and What Edits It Can Miss

- **Granularity:** **Whole-file granularity** (not content-defined chunking). Modifying 1 byte in a 200 MiB file copies all 200 MiB into a new inode in the new snapshot.
- **Edits missed by `synccli.file_state` (`synccli.py:22-25`, `(size, mtime)` float):**
  1. Same-size in-place overwrites followed by resetting `mtime` via `utime`/`touch`.
  2. Same-size edits occurring within the filesystem timestamp resolution or lost to IEEE-754 64-bit `float` rounding of epoch nanoseconds ($\sim 256\text{ ns}$ precision loss around $1.79 \times 10^{18}\text{ ns}$).
  3. Permission/ownership changes (`chmod`) that leave `size` and `mtime` unchanged.
- **Edits still missed by `backupctl` default `(size, mtime_ns, ctime_ns, ino, mode)`:**
  1. **Silent disk bit-rot / non-VFS writes** on the source volume (bytes change on media without updating `mtime_ns` or `ctime_ns`).
  2. **Coarse kernel timestamp ticks:** On filesystems/kernels with coarse timestamp granularity (e.g., 1 ms–10 ms tick), an in-place same-size overwrite occurring within the same timestamp tick as the prior write that `backupctl` already snapshotted keeps identical `mtime_ns` and `ctime_ns`.
  3. **Writable `mmap` modifications** if the OS delays `mtime`/`ctime` updates until `msync`/unmap across a racing scan window.
  - *Mitigation:* `--checksum` mode (reads and SHA-256 hashes source files to verify against `snap_prev`) and periodic `--verify-every K` runs.

### 7.3 Retention Policy and Safe Deletion

Default tiered retention (configurable, evaluated over **verified complete** snapshots only):
- **Recent:** keep the newest `K_recent = 7` snapshots.
- **Daily:** keep the newest snapshot per UTC calendar day for the last `K_daily = 14` days.
- **Weekly:** keep the newest snapshot per ISO calendar week for the last `K_weekly = 8` weeks.
- **Hard safety floor:** `min_keep = max(1, configured_min_keep)` — `backupctl` **never** deletes the newest verified complete snapshot and **never** leaves zero usable snapshots (overriding `snaputil.prune_snapshots`'s `keep <= 0` bug at `snaputil.py:31-33`).

**Deletion sequence per expired snapshot `S`:**
1. Acquire `LOCK_EX | LOCK_NB` on `.locks/<S>.lock`. If held by an active restore/reader (`BlockingIOError`), skip `S` and defer to the next run.
2. `os.rename(backup_root/S, backup_root/.trash/S)` + `os.fsync(backup_root)` (atomically removes `S` from `snaputil.list_snapshots`).
3. Release lockfile, then sweep `.trash/*` entries older than `--trash-grace-seconds` (`3600` s default) via `shutil.rmtree`.

---

## 8. Performance Budget for Initial Full Backup (~1 GiB, ~30,000 Files)

### Measured Baseline Constants (This Repository & Host)

Measured directly on this environment (macOS Darwin, APFS NVMe SSD, Python 3.10.11) against `synccli.py` and prototype primitives:

| Operation | Measured Workload | Measured Time / Size | Derived Rate / Constant |
|---|---|---|---|
| `synccli.scan_files` + `build_manifest` (`synccli.py:10-33`) | 5,001 files (50 dirs) | `0.046 s` + `0.176 s` = `0.222 s` | `22,527 files/s` (double walk) |
| Single-pass `os.scandir(follow_symlinks=False)` + `lstat` | 5,000 files (50 dirs) | `0.177 s` | **`28,315 files/s`** ($35.3\text{ }\mu\text{s/file}$) |
| 1 MiB chunked copy + `hashlib.sha256` streaming | 256 MiB sequential file | `0.269 s` | **`951 MiB/s`** ($1.05\text{ ms/MiB}$) |
| Per-file create/write/close metadata overhead | 5,000 × 4 KiB files (50 dirs) | `1.541 s` | **`3,244 files/s`** ($0.308\text{ ms/file}$) |
| Hardlink creation (`os.link`, dirs pre-created) | 5,000 files | `2.504 s` | **`1,997 links/s`** ($0.501\text{ ms/link}$) |
| `os.fsync` per file (APFS) | 100 files | `0.009 s` | **`11,690 fsync/s`** ($85.5\text{ }\mu\text{s/fsync}$) |
| Compact JSON manifest serialize / parse (`sha256` + `ns` stats) | 30,000 synthetic entries | `0.153 s` dump, `0.033 s` load, `6,090,001 B` | **`203.0 B/entry`**, `0.186 s` total |
| Python `dict` manifest memory (`tracemalloc`) | 30,000 entries | `14.35 MiB` | **`502 B/entry`** |

### Derived Budget for Initial Full Backup ($B = 1\text{ GiB} = 1{,}024\text{ MiB}$, $F = 30{,}000$ files)

1. **Single-pass source scan + `lstat`:** $30{,}000 / 28{,}315 = \mathbf{1.06\text{ s}}$.
2. **File creation / directory metadata overhead:** $30{,}000 / 3{,}244 = \mathbf{9.25\text{ s}}$.
3. **Byte I/O + inline SHA-256 hashing:** $1{,}024\text{ MiB} / 951\text{ MiB/s} = \mathbf{1.08\text{ s}}$.
4. **Manifest JSON dump + `fsync` + atomic directory publish:**
   - With manifest + `.COMPLETE` + directory `fsync` (and optional `F_FULLFSYNC` / `syncfs` barrier at commit): $\mathbf{0.20\text{ s}}$.
   - With per-file `os.fsync` on APFS: $+ 30{,}000 / 11{,}690 = +2.57\text{ s}$.
5. **Total derived time (warm local NVMe SSD):** **~11.6 s** (commit-barrier `fsync`) to **~14.2 s** (per-file `os.fsync`).
6. **Stated Initial Full-Backup Budget:** **$\le 30\text{ s}$** on local NVMe SSD (providing $\sim 2.1\times$ headroom for cold dentry/page cache, directory creation, and background `evals/` I/O).
   - *Filesystem caveat:* On Linux ext4/xfs with synchronous journal barriers (or rotational HDDs), per-file `fsync` drops to ~200–500 fsyncs/s (60–150 s for 30,000 files). Because staging directories are never visible until `os.replace`, `backupctl` batches durability before step 8 (using `os.syncfs` on Linux where available, or syncing target directories + manifest + `.COMPLETE` rather than synchronous per-file barriers unless `--fsync-every-file` is requested), keeping initial backup close to the ~12–20 s budget.

---

## 9. Scaling Analysis and Explicit Bounds ($N = 3 \to 24\text{–}50$)

Let:
- $N$ = number of configured source directories ($N = 3$ today; $N \le 50$ target).
- $F_i, B_i$ = regular files and bytes in directory $i$; $F = \sum_{i=1}^N F_i$, $B = \sum_{i=1}^N B_i$, $F_{\max} = \max_{1 \le i \le N} F_i$.
- $\Delta F, \Delta B$ = changed/new files and bytes in a run.
- $K \le K_{\max}$ = retained verified snapshots; under default policy $K_{\max} = 7 + 14 + 8 = 29$ snapshots (or $\le 29 + R_{\text{pinned}}$ if restores hold `LOCK_SH`).

### What Grows vs. What Stays Flat

| Resource | Exact Bound / Formula | Scaling Behavior ($N = 3 \to 50$) |
|---|---|---|
| **Copy stream buffer RAM** | **$1\text{ MiB}$ ($1{,}048{,}576\text{ B}$)** constant | **Flat ($O(1)$)** in $N, F, B, K$ (overrides `synccli.copy_file`'s $O(\max\_file\_size)$ `fsrc.read()`). |
| **Peak manifest RAM** | **$\le 2 \times 502\text{ B} \times F_{\max} + 1\text{ MiB} \approx 1{,}004 \cdot F_{\max}\text{ B}$** (plus ~25 MiB Python RSS) | **Flat in $N$ and $K$** ($O(F_{\max})$): targets $1..N$ are processed sequentially and each target's dicts are freed before loading the next. For $F_{\max} = 30{,}000$, peak manifest RAM is **$28.7\text{ MiB}$** regardless of whether $N = 3$ or $N = 50$. |
| **Per-run scan + diff work** | $O(F)$ syscalls: $\approx 35.3\text{ }\mu\text{s} \cdot F + 6.2\text{ }\mu\text{s} \cdot F_{\text{prev}}$ (load + diff) | **Linear in total $F$**, **flat in $K$** (reads only the single newest verified `snap_prev`, never all $K$ snapshots). At $N=50, F_i=10{,}000$ ($F=500{,}000$), scan takes $\sim 17.7\text{ s}$. |
| **Per-run incremental I/O work** | $\Delta B / 951\text{ MiB/s} + 0.308\text{ ms} \cdot \Delta F + 0.501\text{ ms} \cdot (F - \Delta F)$ | **Linear in $\Delta B$ and $F$**, **flat in $K$**. For 99% unchanged on $F = 30{,}000, \Delta F = 300, \Delta B = 10\text{ MiB}$: $\sim 1.1\text{ s}$ scan + $0.10\text{ s}$ copy + $14.9\text{ s}$ hardlinks $\approx \mathbf{16.1\text{ s}}$. |
| **Steady-state disk usage** | $\le B_{\text{live}} + \sum_{s=1}^{K-1} \Delta B_s + K_{\max} \cdot F \cdot (203\text{ B} + M_{\text{dirent}})$ | **Bounded by $K_{\max} = 29$** (never grows unboundedly over time). Unchanged files take **0 extra data blocks**; per-snapshot metadata overhead is **$203\text{ B/file}$** JSON + **$\sim 64\text{–}256\text{ B/file}$** dirent/link entry ($\sim 7.7\text{–}13.3\text{ MiB}$ per 30k-file snapshot, or $\le 390\text{ MiB}$ across all 29 snapshots, vs $29\text{ GiB}$ for naive full copies). |
| **Restore / incremental base lookup depth** | **$1$ hop** (`snap_target` is a complete tree) | **Flat ($O(1)$)** in $K$ and $N$ — no delta-chain replay. |
| **Lockfile footprint** | $1$ `.backupctl.lock` + $\le K_{\max} + 1$ files in `.locks/` ($\le 30$ zero-byte files) | **Flat ($\le 30$ inodes, $0\text{ B}$ data)** in $N, F, B$. |
| **Per-run prune work** | $\le 1$ snapshot expired per steady-state run ($O(F_{\text{expired}})$ unlinks in `.trash/`) | **Flat in $K$** once $K = K_{\max}$ is reached. |

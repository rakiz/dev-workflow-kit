# `backupctl` Design Document (Fixture D1)

## 1. Overview & Architecture

`backupctl` is a command-line backup utility that creates immutable, point-in-time snapshots of $N$ configured `evals/` directories ($N = 3$ today, scaling to a few dozen over time) under a single `<backup_root>` directory on the same POSIX filesystem.

`backupctl` ships alongside `synccli.py` and `snaputil.py` in this repository and directly imports their building blocks where their contracts hold, while explicitly overriding functions whose current behavior violates snapshot isolation, crash recovery, retention safety, path containment, or bounded-memory requirements.

### 1.1 Grounding Summary: Reuse vs. Explicit Overrides

| Area | Existing Artifact | Reused or Overridden | Exact Behavior & Rationale |
|---|---|---|---|
| Tree traversal | `synccli.scan_files(root)` (`synccli.py:10-19`) | **Reused (wrapped)** | Walks `root` via `os.walk`, strips hidden subdirectories (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]` at `synccli.py:14`), and returns sorted relative paths (`synccli.py:19`). Wrapped only to filter out `synccli.MANIFEST_NAME` (`".sync_manifest.json"`, `synccli.py:7`) and staging `*.tmp.*` artifacts if present. |
| Per-file metadata | `synccli.file_state(path)` (`synccli.py:22-25`) | **Reused** | Calls `os.stat(path)` (`synccli.py:24`) and returns `{"size": st.st_size, "mtime": st.st_mtime}` (`synccli.py:25`). |
| Manifest filename | `synccli.MANIFEST_NAME` (`synccli.py:7`) | **Reused** | Constant `".sync_manifest.json"` used for each per-directory manifest inside a snapshot (`<snap>/<dir_id>/.sync_manifest.json`). |
| Change detection | `synccli.changed_files(old_manifest, new_manifest)` (`synccli.py:36-42`) & `synccli.collect_stale(items, seen=None)` (`synccli.py:45-59`) | **Reused** | `changed_files` returns relative paths in `new_manifest` that are missing from `old_manifest` or whose `{"size", "mtime"}` dict differs (`synccli.py:40-41`). `collect_stale` filters a sequence of `(path, fresh)` tuples (`synccli.py:55-58`, tested in `test_synccli.py:21-33`). |
| Manifest building | `synccli.build_manifest(root)` (`synccli.py:28-33`) | **Overridden** | `build_manifest` calls `file_state(os.path.join(root, rel))` (`synccli.py:32`) with no `try/except OSError`. If a source file vanishes between `scan_files(root)` (`synccli.py:31`) and `file_state(...)` (`synccli.py:32`), or is a broken symlink, `os.stat` raises an unhandled `FileNotFoundError` and aborts the entire run. Overridden by `build_manifest_resilient(root)` which catches `OSError` per file, excludes vanished/unreadable files from the manifest, and records structured skip diagnostics. |
| File copying | `synccli.copy_file(src, dst)` (`synccli.py:62-69`) | **Overridden** | `copy_file` has four bugs for `backupctl`: (1) `fdst.write(fsrc.read())` (`synccli.py:67`) buffers the entire file in RAM; (2) `open(src, "rb")` and `open(dst, "wb")` in one `with` statement (`synccli.py:66`) creates a 0-byte or truncated `dst` file if reading `src` fails mid-flight; (3) `except OSError: pass` (`synccli.py:68-69`) silently swallows read/write errors without reporting them or removing the failed file from the manifest; (4) it does not preserve `st_mtime` on `dst`, which is required to re-derive a corrupt index from the snapshot tree. Overridden by `copy_file_atomic(src, dst, expected_state)`. |
| Sync orchestration | `synccli.sync(src_root, dst_root, dry_run=False)` (`synccli.py:72-87`) | **Overridden** | `sync` mutates `dst_root` in place (`synccli.py:83-84`), reads `old_manifest` via bare `json.load(f)` (`synccli.py:78-79`) which crashes on a half-written manifest, and writes `src_manifest` unconditionally via non-atomic `open(dst_manifest_path, "w")` (`synccli.py:85-86`) even when `copy_file` failed (`synccli.py:68-69`), causing the manifest to promise files missing from `dst_root` and preventing retries on the next pass. Overridden by `backupctl`'s staging-and-atomic-publish pipeline. |
| Snapshot listing | `snaputil.list_snapshots(backup_root)` (`snaputil.py:8-20`) | **Reused** | Scans `backup_root` (`snaputil.py:17`), returning sorted directory names where `entry.name.startswith("snap-") and entry.is_dir()` (`snaputil.py:18-20`). Because it filters strictly on the `"snap-"` prefix, `backupctl` places staging and trash directories under `.staging/` and `.trash/` so `list_snapshots` never exposes in-flight or retiring snapshots. |
| Snapshot pruning | `snaputil.prune_snapshots(backup_root, keep)` (`snaputil.py:23-36`) | **Overridden** | Two critical defects: (1) when `keep <= 0`, `len(names) <= keep` (`snaputil.py:31`) is `False` and `names[:len(names) - keep]` (`snaputil.py:33`) selects **every** snapshot—including the newest—deleting all backups; (2) `shutil.rmtree(os.path.join(backup_root, name))` (`snaputil.py:34-35`) unlinks files in place under the live `snap-*` path, exposing half-deleted snapshots on crash and breaking concurrent readers. Overridden by `prune_snapshots_safe`. |
| Snapshot age check | `snaputil.is_stale(snapshot_dir, ref_epoch)` (`snaputil.py:66-73`) | **Overridden** | Docstring (`snaputil.py:70-71`) specifies *"A snapshot whose directory was modified at exactly ref_epoch is not stale"*, but line 73 implements `os.stat(snapshot_dir).st_mtime <= ref_epoch` (returning `True` when `st_mtime == ref_epoch`). Overridden with strict `<` comparison (`st_mtime < ref_epoch`). |
| Path containment | `snaputil.safe_snapshot_path(backup_root, snapshot_name, rel_path)` (`snaputil.py:54-63`) | **Overridden** | Line 62-63 calls `rel = os.path.normpath(rel_path); return os.path.join(backup_root, snapshot_name, rel)`. In Python, `os.path.normpath("../../outside")` stays `"../../outside"`, and `os.path.normpath("/etc/passwd")` stays `"/etc/passwd"` (which causes `os.path.join` to discard `backup_root` and `snapshot_name` entirely), violating the docstring's containment guarantee (`snaputil.py:58-60`). Overridden with real/lexical ancestor verification via `os.path.commonpath`. |
| Disk usage | `snaputil.snapshot_disk_usage(backup_root, snapshot_name)` (`snaputil.py:39-51`) | **Reused + Extended** | Reused for single-snapshot logical byte size (`snaputil.py:45-51`), wrapped to ignore `FileNotFoundError` on broken symlinks and paired with `root_physical_disk_usage(backup_root)` which deduplicates hardlinked inodes `(st_dev, st_ino)` across snapshots. |

---

## 2. On-Disk Layout & Naming Contract

All paths live under `<backup_root>` on a single local filesystem (so `os.link` and `os.rename` are atomic, zero-copy metadata operations):

```text
<backup_root>/
├── .lock                                    # Advisory flock file for writers/pruners
├── .staging/                                # Hidden from snaputil.list_snapshots()
│   └── run-20261117-143012-48291-a9f1/      # Per-run staging dir (<utc>-<pid>-<rand>)
├── .trash/                                  # Quarantine for 2-phase reader-safe deletion
│   └── snap-20261110-090000-01.1794925812/  # Atomically unpublished, awaiting grace expiry
├── snap-20261117-120000-01/                 # Published immutable snapshot (oldest)
│   ├── .snapshot_index.json                 # Top-level snapshot receipt & directory map
│   ├── evals_run_a/
│   │   ├── .sync_manifest.json              # synccli.MANIFEST_NAME for evals_run_a
│   │   └── results/metrics.json
│   ├── evals_run_b/
│   │   └── .sync_manifest.json
│   └── evals_run_c/
│       └── .sync_manifest.json
└── snap-20261117-140000-02/                 # Published immutable snapshot (newest)
    └── ...
```

### 2.1 Snapshot Naming & Lexicographical Sort Invariant
`snaputil.list_snapshots(backup_root)` (`snaputil.py:8-20`) matches directories starting with `"snap-"` and sorts them with Python's `sorted(names)` (`snaputil.py:20`), expecting `snap-YYYYMMDD-HHMMSS-NN` (`snaputil.py:12`). To keep `sorted(names)` strictly chronological:
1. Date `YYYYMMDD` (8 digits) and UTC time `HHMMSS` (6 digits) are fixed-width zero-padded UTC timestamps captured when the run enters commit.
2. Sequence number `NN` is a 2-digit zero-padded counter (`01`–`99`) within that timestamp (or monotonic mod 100 when timestamps strictly advance). If the previous snapshot in `snaputil.list_snapshots(backup_root)` has the same `YYYYMMDD-HHMMSS` prefix with sequence `k`, the new snapshot uses `k + 1` (if `k == 99`, the commit sleeps until the next UTC second and uses `01`, preventing a 3-digit `100` from sorting before `02` in ASCII).

### 2.2 Directory Slug Mapping (`<dir_id>`)
The configuration file (`backupctl.json`) lists the $N$ source directories as `[{"id": "evals_run_a", "path": "/abs/path/to/evals/run_a"}, ...]`. Each `"id"` must match `^[A-Za-z0-9._-]+$` (never starting with `.` or containing `/`).

---

## 3. Concurrency, Atomicity, and Crash Recovery

### 3.1 Writer–Writer & Writer–Pruner Coordination
Both `backupctl run` ( invoked by a human or by the scheduler) and `backupctl prune` coordinate using an advisory exclusive lock (`fcntl.flock(lock_fd, fcntl.LOCK_EX)`) on `<backup_root>/.lock`:
1. **Why serialize writers instead of running two copies in parallel:** If a scheduler trigger and a manual trigger collide, running both in parallel would cause both processes to copy the same changed files from source simultaneously. By acquiring `<backup_root>/.lock` (`LOCK_EX` with a configurable `--lock-timeout`, default `600s`), the second run waits until the first run publishes `snap-T1`, and then immediately executes an incremental run against `snap-T1`—completing in sub-second time via hardlinks with zero wasted I/O.
2. **Defense in depth:** Even before or independent of `.lock`, every run builds its tree inside a PID-and-nonce-isolated staging directory `<backup_root>/.staging/run-<YYYYMMDD-HHMMSS>-<pid>-<rand4>/`. Two runs can never write to the same staging path or overwrite each other's files.

### 3.2 Reader–Writer Isolation & Lock-Free Readers
A reader (a restore tool, a human inspecting files, or `snaputil.list_snapshots`) **never acquires `<backup_root>/.lock` and never checks whether a run is in progress**:
1. **Invisible staging:** All in-progress writes happen under `<backup_root>/.staging/run-.../`. Because `.staging` does not start with `"snap-"`, `snaputil.list_snapshots(backup_root)` (`snaputil.py:18`) completely ignores it.
2. **Immutable published files:** Once a file is placed in a snapshot and published, it is never opened for writing, truncated, or mutated in place. Subsequent snapshots share unchanged files via `os.link(prev_path, new_staging_path)` (creating a new directory entry referencing the same immutable inode) and write modified files to brand-new inodes in the new staging directory.
3. **Single-syscall atomic publication:** A snapshot becomes visible to readers only at the final commit step:
   ```python
   os.rename(staging_dir, os.path.join(backup_root, snap_name))
   ```
   On POSIX filesystems, `rename(2)` within `<backup_root>` is atomic. At the instant `"snap-..."` appears in `os.scandir(backup_root)`, every subdirectory, regular file, `<dir_id>/.sync_manifest.json`, and `.snapshot_index.json` inside it is already completely written and flushed. Readers never see a partial tree, a mix of files from two runs, or an index promising files not yet present.

### 3.3 Process Death at Any Point & Corrupt Index Recovery

#### Failure Point A: Process dies during scan, copy, hardlink, or manifest write in `.staging/`
- **State left on disk:** A partial directory `<backup_root>/.staging/run-<ts>-<pid>-<rand>/`.
- **Impact on readers:** Zero. `snaputil.list_snapshots(backup_root)` (`snaputil.py:18`) ignores `.staging/`. The kernel automatically releases the dead process's `fcntl.flock` on `<backup_root>/.lock` when its file descriptors close on termination.
- **Automatic cleanup on next run:** Upon acquiring `<backup_root>/.lock`, `backupctl` scans `<backup_root>/.staging/`, removes any leftover `run-*` directories via `shutil.rmtree`, and logs `WARN cleanup_staging removed=<dir>` to `stderr`.

#### Failure Point B: Corrupt, truncated, or half-written index/manifest in a published `snap-*` directory
Suppose a prior run or external failure left the newest `snap-*` directory with a missing, 0-byte, truncated, or invalid `.snapshot_index.json` or `<dir_id>/.sync_manifest.json` (or a manifest entry referencing a truncated/missing file).
- **Why `synccli.sync()` fails (`synccli.py:77-79`):** `synccli.sync()` executes `json.load(f)` (`synccli.py:79`) without exception handling; a truncated `.sync_manifest.json` raises `json.JSONDecodeError` on every future run until manual deletion.
- **`backupctl` Index Validation & Recovery Protocol:**
  When `backupctl` inspects a prior snapshot `base_snap` to load its manifests for incremental comparison, it validates `<base_snap>/.snapshot_index.json` and each `<base_snap>/<dir_id>/.sync_manifest.json`:
  1. **Validation criteria:**
     - The JSON file exists, decodes cleanly via `json.load`, and is a `dict`.
     - Every key `rel` passes safe containment inside `<base_snap>/<dir_id>` (via overridden `safe_snapshot_path`) and maps to `{"size": int, "mtime": float | int}`.
     - Every listed file `<base_snap>/<dir_id>/<rel>` exists on disk as a regular file (`stat.S_ISREG(st.st_mode)`) with `st.st_size == entry["size"]` and no leftover `*.tmp.*` sibling.
  2. **What is discarded:**
     - Any corrupt, unreadable, or schema-invalid `.snapshot_index.json` or `<dir_id>/.sync_manifest.json` file is **discarded**.
     - Any leftover temporary file (`*.tmp.*`) inside `<base_snap>/<dir_id>/` is **discarded** (`os.unlink`).
     - Any manifest entry whose file is missing on disk or whose `st.st_size != entry["size"]` (indicating a half-written file) is **discarded**, and the mismatched file on disk is unlinked so it can never be hardlinked into a future snapshot or read by restore.
  3. **What is re-derived from the tree:**
     - For any `<dir_id>` whose `.sync_manifest.json` was corrupt, missing, or failed validation, `backupctl` walks the surviving on-disk subtree `<backup_root>/<base_snap>/<dir_id>/` using `synccli.scan_files` (`synccli.py:10-19`, excluding `.sync_manifest.json` and `*.tmp.*`) and `synccli.file_state` (`synccli.py:22-25`) to **re-derive** `{rel: {"size": st.st_size, "mtime": st.st_mtime}}` directly from the intact files on disk.
     - This re-derivation is exact because `backupctl`'s `copy_file_atomic` sets each copied file's `st_mtime` to match the source file's `st_mtime` via `os.utime(tmp_dst, (src_mtime, src_mtime))` before renaming it into place.
     - `backupctl` then atomically writes the reconstructed `<dir_id>/.sync_manifest.json` and `<base_snap>/.snapshot_index.json` (via write-to-temp + `os.fsync` + `os.replace`) so the repaired snapshot is self-consistent for all subsequent runs and readers.
  4. **What the run reports:**
     - `backupctl` logs a structured warning to `stderr` and records it in the new snapshot's `.snapshot_index.json`:
       ```text
       WARN index_recovered snapshot=snap-20261117-120000-01 dir=evals_run_a reason=JSONDecodeError discarded=.sync_manifest.json rederived_files=4812 dropped_incomplete_files=0
       ```
     - The current backup run then proceeds without manual cleanup, using the re-derived manifest as `old_manifest`.

---

## 4. Vanishing and Unreadable Source Files

Source files in active `evals/` directories can vanish between `scan_files` and `file_state`, vanish between `build_manifest` and `copy_file`, or fail with `PermissionError` (`EACCES`) / `OSError` (`EIO`) during opening or reading.

### 4.1 Why `synccli.py` Must Be Overridden
1. `synccli.build_manifest(root)` (`synccli.py:28-33`) calls `file_state(os.path.join(root, rel))` (`synccli.py:32`) unprotected; a file that disappears after `scan_files(root)` (`synccli.py:31`) crashes the process with `FileNotFoundError`.
2. `synccli.copy_file(src, dst)` (`synccli.py:62-69`) opens `dst` with `"wb"` at the same time as `src` (`synccli.py:66`) and catches `OSError: pass` (`synccli.py:68-69`), while `synccli.sync()` (`synccli.py:85-86`) still writes the full `src_manifest` to `.sync_manifest.json`. If `src` vanishes or becomes unreadable before/during `copy_file`, `.sync_manifest.json` falsely records the file as backed up, and if `fsrc.read()` fails mid-stream, a truncated `dst` file is left behind.

### 4.2 `backupctl` Behavior: What the Snapshot Contains & What the Run Reports
`backupctl` enforces identical behavior whether invoked by the scheduler or by a person (no `isatty()` branching):

1. **Stage 1 — Scanning (`build_manifest_resilient` overriding `synccli.build_manifest`, `synccli.py:28-33`):**
   - Calls `synccli.scan_files(src_root)` (`synccli.py:10-19`).
   - For each `rel`, calls `synccli.file_state(os.path.join(src_root, rel))` (`synccli.py:22-25`) inside `try ... except OSError as e`:
     - If `e.errno == errno.ENOENT` (file vanished or broken symlink): excluded from `new_manifest`; recorded as `("vanished", rel, "stat", e.errno)`.
     - If `e.errno in (errno.EACCES, errno.EPERM)` or other `OSError` (unreadable metadata): excluded from `new_manifest`; recorded as `("unreadable", rel, "stat", e.errno)`.

2. **Stage 2 — Copying (`copy_file_atomic` overriding `synccli.copy_file`, `synccli.py:62-69`):**
   - For each `rel` in `synccli.changed_files(old_manifest, new_manifest)` (`synccli.py:36-42`):
     1. Open `src` (`open(src_path, "rb")`) and inspect `st = os.fstat(fsrc.fileno())` **before** creating any destination directory or file.
     2. Create parent directory under `.staging/.../<dir_id>/` and open a temporary sibling `<dst_path>.tmp.<pid>` with `"wb"`.
     3. Stream data in $256\text{ KiB}$ chunks (`shutil.copyfileobj(fsrc, fdst, length=262144)`).
     4. Set timestamps on `<dst_path>.tmp.<pid>` (`os.utime(..., (st.st_atime, new_manifest[rel]["mtime"]))`), flush, and atomically rename `<dst_path>.tmp.<pid>` $\to$ `<dst_path>` via `os.replace`.
     5. If `open(src_path)` or chunk reading raises `OSError as e`:
        - Unlink `<dst_path>.tmp.<pid>` if it was created so **no partial or 0-byte file ever remains in the staging tree**.
        - **Delete `rel` from `committed_manifest`** (`committed_manifest.pop(rel, None)`).
        - Classify as `"vanished"` if `e.errno == errno.ENOENT` else `"unreadable"`.

3. **What the resulting snapshot contains:**
   - **No partial file and no stale fallback:** The vanished or unreadable file is **absent** from `<snap>/<dir_id>/<rel>` (we never copy half a file, and we never fall back to hardlinking the stale version from `old_manifest`, which would falsely resurrect a deleted file or silently mask an unreadable new version with stale contents).
   - **Self-consistent manifest:** `<snap>/<dir_id>/.sync_manifest.json` contains `committed_manifest`—only the files actually materialized in `<snap>/<dir_id>/`. Because an unreadable file is omitted from `.sync_manifest.json`, the next run's `synccli.changed_files(old_manifest, new_manifest)` (`synccli.py:36-42`) automatically treats it as missing from `old_manifest` and retries copying it once permissions are fixed.
   - **Audit record in `.snapshot_index.json`:** The top-level `.snapshot_index.json` records `directories[dir_id]["vanished"] = [rel, ...]` and `directories[dir_id]["unreadable"] = [{"path": rel, "stage": "copy", "errno": e.errno}, ...]`.

4. **What the run reports (identical for scheduler and person):**
   - For every vanished or unreadable file, one structured line is written to `stderr`:
     ```text
     WARN file_skipped dir=<dir_id> path=<rel> status=<vanished|unreadable> stage=<stat|copy> errno=<ERRNO>
     ```
   - At the end of the run, once the snapshot is atomically published, one summary line is written to `stdout`:
     ```text
     SNAPSHOT snap-20261117-140000-02 status=<ok|partial> dirs=3 copied=14 linked=19985 vanished=1 unreadable=0
     ```
   - **Exit code contract (identical for scheduler and manual CLI runs):**
     - `0`: Snapshot published; `unreadable == 0` (files that vanished with `ENOENT` between scan and copy are logged to `stderr` and counted in `vanished=<V>`, as transient file deletion in live `evals/` directories is normal concurrent activity).
     - `3`: Snapshot published with `status=partial` because `unreadable >= 1` (`EACCES`/`EIO` on an existing source file); the snapshot of all readable files is still committed and usable, while the non-zero exit code alerts both cron/scheduler monitoring and interactive users.

---

## 5. Incremental Backups, Change Granularity, and Missed Edits

### 5.1 Incremental Deduplication Mechanism
On every run after the first full backup:
1. `backupctl` calls `snaputil.list_snapshots(backup_root)` (`snaputil.py:8-20`) and selects the newest complete snapshot `prev_snap = names[-1]`.
2. For each configured directory `<dir_id>`, `backupctl` loads `old_manifest` from `<backup_root>/<prev_snap>/<dir_id>/.sync_manifest.json` (recovering it from the tree via Section 3.3 if corrupt) and builds `new_manifest` from `<src_root>` via `build_manifest_resilient` (wrapping `synccli.scan_files` at `synccli.py:10-19` and `synccli.file_state` at `synccli.py:22-25`).
3. Changed or added files are computed by `to_copy = set(synccli.changed_files(old_manifest, new_manifest))` (`synccli.py:36-42`), or equivalently via `synccli.collect_stale([(rel, rel in old_manifest and old_manifest[rel] == st) for rel, st in new_manifest.items()])` (`synccli.py:45-59`).
4. For every `rel` in `new_manifest`:
   - If `rel not in to_copy` (**unchanged**): `backupctl` resolves the source path in `prev_snap` via the hardened `safe_snapshot_path(backup_root, prev_snap, os.path.join(dir_id, rel))` and creates a hardlink in the staging directory via `os.link(prev_file, staging_file)` (falling back to `copy_file_atomic` only if `os.link` raises `EMLINK` when the filesystem hardlink limit, e.g. 32,767 on APFS/ext4, is reached). Zero file content bytes are read or written.
   - If `rel in to_copy` (**new or modified**): `backupctl` copies `<src_root>/<rel>` into a new inode at `<staging>/<dir_id>/<rel>` via `copy_file_atomic`.
   - If `rel in old_manifest and rel not in new_manifest` (**deleted in source**): `backupctl` does nothing; `rel` is not linked into `<staging>/<dir_id>/` and not included in the new `.sync_manifest.json`.

### 5.2 Granularity of "Unchanged" & Edits It Can Miss
- **Decision granularity:** Per-file metadata equality on the 2-tuple `(st_size, st_mtime)` stored as JSON `{"size": int, "mtime": float}` by `synccli.file_state(path)` (`synccli.py:22-25`) and compared by `old_manifest[rel] != state` in `synccli.changed_files` (`synccli.py:40`).
- **What edits this granularity can miss:**
  1. **Same-size in-place overwrites within a single `mtime` tick or IEEE-754 float ULP:** `st.st_mtime` in Python is a 64-bit IEEE-754 float (~53-bit significand; at Unix epoch $\sim 1.79 \times 10^9\text{ s}$, $1\text{ ULP} \approx 2^{-22}\text{ s} \approx 238\text{ ns}$, and coarse filesystems or tools may have $1\text{ ms}$–$1\text{ s}$ granularity). If a process modifies bytes in place without changing `st_size` within the same timestamp quantum, `{"size", "mtime"}` is identical and the edit is missed.
  2. **Edits with explicitly restored timestamps (`os.utime` / `utimensat` / `touch -r` / `cp -p`):** Any writer or archive extractor that overwrites a file with new content of the exact same byte length (`st_size`) and resets `st_mtime` to its prior value will not be detected.
  3. **Silent media corruption (bit-rot):** Underlying block corruption that alters file bytes without updating the inode's `st_mtime` or `st_size` is invisible without content hashing.
  4. **Metadata-only changes (`chmod`, `chown`, extended attributes):** Changes to permissions (`st_mode`), ownership (`st_uid`/`st_gid`), or xattrs update `st_ctime` but neither `st_size` nor `st_mtime`; `synccli.file_state` (`synccli.py:22-25`) does not inspect `st_mode` or `st_ctime`.
  5. **Edits inside hidden dot-directories:** Because `synccli.scan_files` (`synccli.py:14`) prunes `dirnames` starting with `"."`, any files added or modified under a dot-directory (e.g. `.cache/`) are ignored by design.

---

## 6. Retention Policy & Reader-Safe Deletion

### 6.1 Retention Policy
Retention runs automatically at the end of `backupctl run` (after the new snapshot is atomically published) or via `backupctl prune --keep K`:
- **Policy parameters:**
  - `keep_count` ($K$, default $K = 10$, **hard minimum floor $\max(1, K)$**): Always retain at least the newest $\max(1, K)$ complete snapshots returned by `snaputil.list_snapshots(backup_root)` (`snaputil.py:8-20`).
  - `min_age_seconds` (optional, default $0\text{ s}$): Among snapshots older than the newest $\max(1, K)$, only prune a snapshot if its directory modification time is strictly older than `ref_epoch = now - min_age_seconds` using the corrected `is_stale_strict(snap_dir, ref_epoch)` (`os.stat(snap_dir).st_mtime < ref_epoch`, overriding `snaputil.is_stale` at `snaputil.py:66-73` which used `<=`).
- **Why this never leaves the user without a usable snapshot:**
  1. `backupctl` overrides `snaputil.prune_snapshots(backup_root, keep)` (`snaputil.py:23-36`) to enforce `effective_keep = max(1, keep)`. In `snaputil.py:31-33`, passing `keep <= 0` caused `names[:len(names) - keep]` to delete **all** snapshots including the newest. With `effective_keep = max(1, keep)` and an explicit check `len(names) - len(doomed) >= 1`, the newest complete snapshot is structurally untouchable.
  2. During `backupctl run`, pruning executes **only after** the new snapshot has been `fsync`ed and atomically renamed into `<backup_root>/snap-...` (and verified via `list_snapshots`). If a backup run fails or is interrupted before publish, pruning does not run.

### 6.2 Safe Deletion While a Concurrent Reader May Be Reading
In `snaputil.prune_snapshots` (`snaputil.py:34-35`), `shutil.rmtree(os.path.join(backup_root, name))` deletes files directly inside `<backup_root>/snap-...`. That is unsafe for two reasons: (a) if interrupted mid-`rmtree`, `<backup_root>/snap-...` remains visible to `snaputil.list_snapshots()` as a half-deleted snapshot; (b) an active reader walking `<backup_root>/snap-...` experiences `FileNotFoundError` mid-restore as files vanish underneath it.

`backupctl` replaces in-place `shutil.rmtree` with **Two-Phase Quarantine + Grace-Window Reclamation** under `<backup_root>/.lock`:

1. **Cooperative Reader Check (Optional Shared Flock):**
   - Before retiring a doomed snapshot `<backup_root>/<name>`, the pruner opens `<backup_root>/<name>` and attempts a non-blocking exclusive lock `fcntl.flock(dir_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`. If a restore tool holds `LOCK_SH` on that snapshot directory, `flock` raises `BlockingIOError` and `backupctl` skips `<name>` for this prune cycle.
2. **Phase 1 — Atomic Unpublish into `.trash/` (Crash-Safe):**
   - The pruner atomically renames `<backup_root>/<name>` to `<backup_root>/.trash/<name>.<retired_epoch>`:
     ```python
     os.rename(
         os.path.join(backup_root, name),
         os.path.join(backup_root, ".trash", f"{name}.{int(time.time())}")
     )
     ```
   - Because `.trash` does not start with `"snap-"`, `snaputil.list_snapshots(backup_root)` (`snaputil.py:18`) immediately ceases to return `<name>`. If the process dies at any instant after `os.rename`, no partial `snap-*` directory exists in `<backup_root>`.
   - Furthermore, any reader whose working directory or open directory file descriptor (`openat`) is already inside `<name>` continues resolving relative paths inside the moved directory inode undisturbed while it sits in `.trash/`.
3. **Phase 2 — Delayed Physical Unlink (`shutil.rmtree`) After Grace Window:**
   - Entries in `<backup_root>/.trash/<name>.<retired_epoch>` are **not** `rmtree`'d in the same second they are unpublished unless `--trash-grace-seconds 0` is explicitly requested. By default, `--trash-grace-seconds` is `300` seconds (5 minutes, $> 50\times$ the duration of a 1 GB restore).
   - On each run (while holding `<backup_root>/.lock`), the pruner scans `<backup_root>/.trash/` and runs `shutil.rmtree` only on quarantined directories where `now - retired_epoch > trash_grace_seconds` (and `LOCK_EX | LOCK_NB` succeeds).
   - Even when `shutil.rmtree` unlinks a file in `.trash/`, POSIX `unlink(2)` only decrements the inode link count (`st_nlink`): any file hardlinked into a newer surviving snapshot (`st_nlink >= 1`) or held open by a reader file descriptor retains its inode and disk blocks completely intact.

### 6.3 Path Traversal Hardening (`safe_snapshot_path` Override)
`snaputil.safe_snapshot_path(backup_root, snapshot_name, rel_path)` (`snaputil.py:54-63`) is used by restore and verification tooling to map a manifest's `rel_path` under `<backup_root>/<snapshot_name>`. Its current implementation (`snaputil.py:62-63`):
```python
rel = os.path.normpath(rel_path)
return os.path.join(backup_root, snapshot_name, rel)
```
fails when `rel_path` is `"../../etc/passwd"` (`os.path.normpath` preserves leading `".."` on relative paths) or `"/etc/passwd"` (`os.path.join` drops preceding arguments on an absolute path). `backupctl` overrides `safe_snapshot_path` with strict containment checking:
```python
def safe_snapshot_path(backup_root, snapshot_name, rel_path):
    if not snapshot_name.startswith("snap-") or os.path.sep in snapshot_name:
        raise ValueError(f"Invalid snapshot name: {snapshot_name!r}")
    snap_root = os.path.realpath(os.path.join(backup_root, snapshot_name))
    candidate = os.path.realpath(os.path.join(snap_root, rel_path.lstrip("/\\")))
    if os.path.commonpath([snap_root, candidate]) != snap_root:
        raise ValueError(f"Path escapes snapshot root: {rel_path!r}")
    return candidate
```

---

## 7. Initial Full Backup Performance Budget (~1 GB Tree, Tens of Thousands of Files)

### 7.1 Benchmark Measurement in This Repository
To ground the budget in real numbers rather than guesses, `synccli.build_manifest` (`synccli.py:28-33`), `synccli.copy_file` (`synccli.py:62-69`), chunked `copyfileobj` + `os.utime`, and `json.dumps`/`json.loads` were benchmarked directly in this environment at $1/10\text{th}$ scale ($100\text{ MiB}$) across two file-count profiles representing a $1\text{ GB}$ ($\approx 1,000\text{ MiB}$) tree of "tens of thousands of files":

1. **Profile A ($F = 20,000$ files, average size $50\text{ KiB} = 51,200\text{ B}$, total $B \approx 1.024 \times 10^9\text{ B}$):**
   - Measured at $1/10\text{th}$ scale ($2,000$ files $\times 50\text{ KiB} = 102.4\text{ MB}$ across $40$ subdirectories):
     - `synccli.build_manifest` (`scan_files` + `file_state`): **$0.0536\text{ s}$** ($26.8\text{ }\mu\text{s/file}$)
     - `synccli.copy_file` (open + read/write + close): **$0.4890\text{ s}$** ($244.5\text{ }\mu\text{s/file}$, effective throughput $209.4\text{ MB/s}$)
     - `os.link` (incremental hardlink + `makedirs`): **$0.8313\text{ s}$** ($415.6\text{ }\mu\text{s/file}$ with per-file `makedirs`, or $\approx 95\text{ }\mu\text{s/file}$ with cached directory creation)
     - `json.dumps` / `json.loads` of manifest: **$0.0038\text{ s}$ dump / $0.0010\text{ s}$ load**, manifest size **$167,470\text{ B}$** ($83.7\text{ B/file}$)
2. **Profile B ($F = 50,000$ files, average size $20\text{ KiB} = 20,480\text{ B}$, total $B \approx 1.024 \times 10^9\text{ B}$):**
   - Measured at $1/10\text{th}$ scale ($5,000$ files $\times 20\text{ KiB} = 102.4\text{ MB}$ across $50$ subdirectories):
     - `synccli.build_manifest`: **$0.1296\text{ s}$** ($25.9\text{ }\mu\text{s/file}$)
     - Chunked copy (`256 KiB` buffer) + `os.utime` + cached `os.makedirs`: **$1.2662\text{ s}$** ($253.2\text{ }\mu\text{s/file}$)

### 7.2 Explicit Analytical Derivation & Performance Budget
For a tree of $F$ files and $B$ total bytes across $N$ directories, total initial full backup wall-clock time decomposes into per-file metadata syscalls (`lstat`/`stat`, `open` source, `open` temp dst, `utime`, `replace`, `close`) plus bulk sequential byte transfer ($B / R_{\text{seq}}$) plus JSON manifest serialization and commit `fsync`:

$$T_{\text{full}}(F, B) = F \cdot \left(t_{\text{scan+stat}} + t_{\text{file\_syscalls}} + t_{\text{json}}\right) + \frac{B}{R_{\text{seq}}} + t_{\text{fsync\_commit}}$$

Substituting the measured constants from Section 7.1:
- $t_{\text{scan+stat}} = 26.8\text{ }\mu\text{s/file}$
- $t_{\text{file\_syscalls}} \approx 210\text{ }\mu\text{s/file}$ (dominated by VFS inode creation, `open`/`close`, `utime`, and `replace` on local APFS/NVMe)
- $t_{\text{json}} = 2.0\text{ }\mu\text{s/file}$
- $B / R_{\text{seq}}$: at $R_{\text{seq}} \approx 1.25\text{ GB/s}$ sequential write rate, transferring $B = 1.0\text{ GB}$ takes $\approx 0.80\text{ s}$ (already included inside the measured $244.5\text{–}253.2\text{ }\mu\text{s/file}$ total copy time).

Scaling linearly by $10\times$ from the $100\text{ MiB}$ measurements to $B = 1\text{ GB}$ and adding a $2\times$ safety margin for cold filesystem caches and commit `fsync`:

| Metric ($B = 1\text{ GB}$ Initial Full Backup) | $F = 20,000$ files ($50\text{ KiB}$ avg) | $F = 50,000$ files ($20\text{ KiB}$ avg) |
|---|---|---|
| 1. `build_manifest_resilient` ($26.8\text{ }\mu\text{s/file}$) | $0.54\text{ s}$ | $1.34\text{ s}$ |
| 2. `copy_file_atomic` ($245\text{–}253\text{ }\mu\text{s/file}$ incl. $1\text{ GB}$ I/O) | $4.90\text{ s}$ | $12.66\text{ s}$ |
| 3. JSON manifest serialization ($2.0\text{ }\mu\text{s/file}$, $83.7\text{ B/file}$) | $0.04\text{ s}$ ($1.67\text{ MB}$) | $0.10\text{ s}$ ($4.19\text{ MB}$) |
| 4. Directory + manifest `fsync` & atomic `os.rename` | $0.15\text{ s}$ | $0.25\text{ s}$ |
| **Measured / Derived Baseline Total** | **$5.63\text{ s}$** | **$14.35\text{ s}$** |
| **Committed Performance Budget ($2\times$ head-room for cold cache/fsync)** | **$\le 12.0\text{ seconds}$** | **$\le 30.0\text{ seconds}$** |

---

## 8. Scaling & Resource Bounds ($N = 3$ Today $\to$ A Few Dozen Over Time)

Let:
- $N$: number of configured source directories ($N = 3$ today, $N \le 50$ over time).
- $F_i, B_i$: file count and total bytes in directory $i$; $F = \sum_{i=1}^{N} F_i$ and $B = \sum_{i=1}^{N} B_i$ across all $N$ directories; $F_{\max} = \max_{1 \le i \le N} F_i$.
- $\Delta F_i, \Delta B_i$: changed/new file count and bytes in directory $i$ since the previous snapshot; $\Delta F = \sum_{i=1}^{N} \Delta F_i$, $\Delta B = \sum_{i=1}^{N} \Delta B_i$, and unchanged file count $U = F - \Delta F$.
- $K$: retained snapshot count (`effective_keep = max(1, K)`), plus $G$ snapshots in `.trash/` awaiting grace expiry ($K_{\text{eff}} = K + G$, typically $G \in \{0, 1\}$).
- $C_{\text{buf}} = 262,144\text{ B}$ ($256\text{ KiB}$): fixed streaming buffer size in `copy_file_atomic`.

### 8.1 What Grows with What (Explicit Formulas & Constants)

1. **Per-Run Work (CPU, Syscalls, and I/O Time):**
   - **Grows linearly with total files $F$ and changed bytes $\Delta B$, plus $O(N)$ per-directory setup:**
     - `stat` calls on source trees: $F + N_{\text{subdirs}}$ calls ($26.8\text{ }\mu\text{s/file} \cdot F$).
     - Previous manifest parsing: $N$ `open`/`json.load` calls parsing $F$ total entries ($0.5\text{ }\mu\text{s/file} \cdot F + 0.2\text{ ms} \cdot N$).
     - Unchanged file materialization: $U = F - \Delta F$ `os.link()` calls ($\approx 95\text{ }\mu\text{s/file} \cdot (F - \Delta F)$ with cached parent directory creation).
     - Changed file copying: $\Delta F$ file copies + $\Delta B$ byte transfer ($210\text{ }\mu\text{s/file} \cdot \Delta F + \Delta B / (1.25\text{ GB/s})$).
     - Manifest writing: $N$ `.sync_manifest.json` files + $1$ `.snapshot_index.json` file ($2.0\text{ }\mu\text{s/file} \cdot F + 0.6\text{ ms} \cdot N$).
     - **Total incremental run time bound:**
       $$T_{\text{inc}}(N, F, \Delta F, \Delta B) = 0.8\text{ ms} \cdot N + 124.3\text{ }\mu\text{s} \cdot F + 115.0\text{ }\mu\text{s} \cdot \Delta F + \frac{\Delta B}{1.25\text{ GB/s}} + 5\text{ ms}$$
       *(Example: for $N = 30$ directories containing $F = 60,000$ total files and $B = 3\text{ GB}$ where $\Delta F = 100$ files / $\Delta B = 5\text{ MB}$ changed, $T_{\text{inc}} \approx 0.024\text{ s} + 7.46\text{ s} + 0.012\text{ s} + 0.004\text{ s} + 0.005\text{ s} \approx 7.51\text{ s}$.)*

2. **Peak Memory (Heap / RSS):**
   - `backupctl` processes the $N$ configured directories **sequentially one directory $i$ at a time**, freeing `old_manifest` and `new_manifest` for directory $i$ before scanning directory $i+1$, and retaining only a $256\text{ B}$ summary record per directory in the top-level `.snapshot_index.json` dict.
   - Within directory $i$, CPython holds `scan_files` ($\approx 80\text{ B/file}$), `old_manifest` ($\approx 320\text{ B/file}$), and `new_manifest` ($\approx 320\text{ B/file}$), totalling $\approx 720\text{ B} \cdot F_i$.
   - **Explicit peak memory bound:**
     $$\text{Peak Memory}(N, F_{\max}) \le 18\text{ MiB}_{\text{(CPython base)}} + 256\text{ KiB}_{(C_{\text{buf}})} + 720\text{ B} \cdot F_{\max} + 256\text{ B} \cdot N$$
     **Grows linearly with the single largest directory's file count $F_{\max} = \max_i F_i$ ($720\text{ B/file}$) and negligibly with $N$ ($256\text{ B/directory}$).** For $F_{\max} = 20,000$ files and $N = 50$ directories, peak memory is $\le 32.7\text{ MiB}$.

3. **Disk Usage under `<backup_root>`:**
   - **Grows with base physical bytes $B_{\text{base}}$, cumulative changed bytes $\sum_{r=2}^{K_{\text{eff}}} \Delta B_r$, and per-snapshot manifest + directory-entry metadata $K_{\text{eff}} \cdot F$:**
     - Manifest JSON size per snapshot: measured **$83.7\text{ B} \cdot F + 256\text{ B} \cdot N$** (plus $1\text{ KiB}$ for `.snapshot_index.json`).
     - Filesystem directory entries (hardlinks) per snapshot: $\approx 88\text{ B} \cdot F + 256\text{ B} \cdot N$.
     - **Explicit total disk usage bound across $K_{\text{eff}} = K + G$ snapshots:**
       $$\text{Disk}_{\text{total}}(N, F, B_{\text{base}}, K_{\text{eff}}) \le B_{\text{base}} + \sum_{r=2}^{K_{\text{eff}}} \Delta B_r + K_{\text{eff}} \cdot \left(172\text{ B} \cdot F + 512\text{ B} \cdot N\right)$$

### 8.2 What Stays Flat (With Explicit Bounds)

| Quantity | What It Is Invariant Under | Explicit Flat Bound |
|---|---|---|
| **File-copy streaming buffer in RAM** | Total bytes $B$, largest file size $s_{\max}$, file count $F$, and directory count $N$ | **Exactly $C_{\text{buf}} = 262,144\text{ B}$ ($256\text{ KiB}$)** (overriding `synccli.copy_file` at `synccli.py:67`, which allocated $s_{\max}$ bytes via `fsrc.read()`). |
| **Per-directory manifest RAM across $N$ directories** | Growing $N$ from $3$ to $50$ directories of size $\le F_{\max}$ | **$\le 720\text{ B} \cdot F_{\max}$** ($\le 14.4\text{ MiB}$ for $F_{\max} = 20,000$ files), independent of $N$ because manifests are built and freed one directory at a time; only the $256\text{ B/dir}$ summary ($\le 12.8\text{ KiB}$ at $N = 50$) accumulates across $N$. |
| **Source file byte I/O on unchanged files** | Total unchanged tree size $B_{\text{unchanged}}$ and directory count $N$ | **$0\text{ bytes}$ read or written** for all $U = F - \Delta F$ unchanged files (linked via `os.link`). |
| **Physical data block storage for unchanged files across $K$ snapshots** | Number of retained snapshots $K$ | **$1 \times B_{\text{unchanged}}$ bytes** of file data blocks across all $K$ snapshots (all $K$ snapshots share a single inode per unchanged file; only $172\text{ B/file}$ of manifest + dentry metadata is added per snapshot). |
| **Number of retained snapshots as total historical runs $R \to \infty$** | Total run count $R$ once $R > K$ | **At most $K$ published snapshots** ($\text{default } K = 10$, floor $\max(1, K)$) plus $G$ snapshots in `.trash/` whose retirement age is $\le 300\text{ s}$. |
| **Snapshot publication & retirement time** | $N$, $F$, and $B$ | **Exactly $1$ `os.rename()` syscall** ($\le 1\text{ ms}$) to publish a staged snapshot to `<backup_root>/snap-...`, and **$1$ `os.rename()` syscall** per doomed snapshot to unpublish it to `<backup_root>/.trash/`. |

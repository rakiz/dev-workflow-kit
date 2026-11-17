# `backupctl` Design Document (Fixture D1)

## 1. Purpose, Scope, and System Overview

`backupctl` is a zero-dependency Python 3.10+ command-line backup tool that creates immutable, point-in-time snapshots of $N$ configured source directories (`evals/` result trees—3 directories today, scaling to a few dozen over time) under a single POSIX filesystem `backup_root`. It ships in the same repository alongside `synccli.py`, `snaputil.py`, and `test_synccli.py`.

### Core Architectural Decisions

1. **Copy-on-change + POSIX hardlink deduplication (`os.link`)**: Each snapshot is materialized as a complete, standalone POSIX directory tree (`backup_root/snap-YYYYMMDD-HHMMSS-NN/sources/<name>/...`). Files unchanged since the newest verified snapshot are hardlinked (`os.link`) from that parent snapshot with **0 data bytes read or written**; new or modified files are streamed into fresh inodes using a fixed **1 MiB (`1,048,576 B`)** buffer. Any reader (`cp -R`, `rsync`, `tar`, custom restore scripts, humans) sees a complete point-in-time directory tree without special client logic or multi-snapshot stitching.
2. **Stage-seal-publish atomicity**: Every run writes strictly inside a hidden staging directory (`backup_root/.staging/run-<utc>-<pid>-<rand>/`). Only after all files are materialized, per-source manifests and the `.tree_complete` seal are written and `fsync`ed, and file data is synced to disk does `backupctl` execute a single atomic POSIX directory `os.rename` to `backup_root/snap-YYYYMMDD-HHMMSS-NN/`. Unpublished work never begins with `"snap-"` and is never visible to readers or `snaputil.list_snapshots`.
3. **Kernel-managed advisory locks (`fcntl.flock`)**: Writer-vs-writer collisions (scheduler + manual CLI) coordinate via `flock(LOCK_EX)` on a permanent lock inode `backup_root/.lock`. Cooperative readers coordinate with pruners via `flock(LOCK_SH)` on read-only (`O_RDONLY`) snapshot directory fds, backed by two-phase atomic `.trash/` retirement and a grace-period TTL for uncooperative readers. Because the kernel owns `flock` locks, `SIGKILL` or process crashes release locks instantaneously with zero manual cleanup.
4. **Sequential per-source manifest streaming**: Each source directory $i \in \{1..N\}$ has its own manifest `manifests/<name>.json` processed one directory at a time, keeping peak Python memory bounded by the single largest directory $F_{\max}$ rather than growing with total files $\sum_{i=1}^N F_i$ across $N$ directories.

### Configuration and CLI Surface

Configuration lives in JSON (`backupctl.json`, parsed with stdlib `json` on Python 3.10):

```json
{
  "backup_root": "/var/backups/evals",
  "lock_timeout_seconds": 120,
  "retention": {
    "keep_last": 10,
    "keep_daily": 7,
    "keep_weekly": 4,
    "trash_grace_seconds": 3600
  },
  "sources": [
    {"name": "eval-suite-a", "path": "/repo/evals/suite_a/results", "include_hidden_dirs": false},
    {"name": "eval-suite-b", "path": "/repo/evals/suite_b/results", "include_hidden_dirs": false},
    {"name": "eval-leaderboard", "path": "/repo/evals/leaderboard", "include_hidden_dirs": false}
  ]
}
```

Configuration validation at startup enforces:
- Each `source.name` is unique and matches `^[A-Za-z0-9._-]+$` (never `.` or `..`, never containing `/`).
- Canonicalized `os.path.realpath(backup_root)` does not lie inside any `os.path.realpath(source.path)` and vice versa (preventing recursive self-backup), and no two sources resolve to overlapping directory trees.

CLI subcommands:
- `backupctl run [--config PATH] [--lock-timeout SEC] [--verify-checksums] [--json]`: Run incremental/full snapshot + retention + trash sweep.
- `backupctl list [--config PATH] [--json]`: List verified snapshots, timestamps, file counts, logical bytes, and unique physical bytes.
- `backupctl prune [--config PATH] [--json]`: Run retention policy and expired `.trash/` reclamation under the writer lock.
- `backupctl verify [SNAP_NAME] [--checksums]`: Verify snapshot seal, manifest integrity, and on-disk file presence/sizes.

---

## 2. Grounding in Existing Code and Explicit Overrides

`backupctl` builds directly on `synccli.py` and `snaputil.py`. Every existing artifact in this directory was audited against the requirements; the table and itemized subsections below specify exact reuse, wrapping, and overrides.

### Summary Matrix

| File & Symbol | Lines | What Existing Code Actually Does | `backupctl` Disposition |
|---|---|---|---|
| `synccli.MANIFEST_NAME` | `synccli.py:7` | Constant `".sync_manifest.json"` written inside `dst_root`. | **Override placement**: Store per-source manifests at `snap-.../manifests/<name>.json` outside `sources/<name>/`, and exclude `MANIFEST_NAME` if a legacy file exists in a source tree. |
| `synccli.scan_files(root)` | `synccli.py:10–19` | `os.walk(root)` skipping dot-dirs (`d.startswith(".")`), collecting all `filenames` (including dot-files, symlinks, broken symlinks, FIFOs) via `os.path.relpath`, returning `sorted(result)`. | **Override / fuse into `scan_source_manifest(root)`**: Single-pass iterative `os.scandir` preserving sorted relative path order and dot-dir filtering, while skipping non-regular files (`follow_symlinks=False`), capturing `scandir` permission errors via explicit callback, and avoiding double-`stat` / `relpath` overhead. `synccli.scan_files` remains untouched for `synccli` callers. |
| `synccli.file_state(path)` | `synccli.py:22–25` | `os.stat(path)` returning `{"size": st.st_size, "mtime": st.st_mtime}` (`float` seconds, follows symlinks, uncaught `OSError`). | **Override with `entry_file_state(st)`**: Uses `lstat` (`follow_symlinks=False`) and returns `{"size": st.st_size, "mtime_ns": st.st_mtime_ns, "mode": st.st_mode & 0o7777}` (exact integer nanoseconds + permission bits). |
| `synccli.build_manifest(root)` | `synccli.py:28–33` | Loops `scan_files(root)` then calls `file_state(...)`. Crashes with `FileNotFoundError` if a file vanishes between scan and stat or is a broken symlink. | **Override with `scan_source_manifest(root)`**: Single-pass `os.scandir` + `entry.stat(follow_symlinks=False)` catching `OSError` per entry and recording vanished/unreadable entries in `skipped` without crashing. |
| `synccli.changed_files(old_manifest, new_manifest)` | `synccli.py:36–42` | Returns `[rel for rel, state in new_manifest.items() if rel not in old_manifest or old_manifest[rel] != state]`. | **Reuse directly**: Imported from `synccli` and called unchanged on `(old_manifest, new_manifest)` dicts! `!=` works identically on the new `{size, mtime_ns, mode}` state dicts. |
| `synccli.collect_stale(items, seen=None)` | `synccli.py:45–60` | Indexes `items[i]` via `range(len(items))` (fails on generators despite docstring saying `iterable`) and never updates `seen` on duplicates. | **Reuse with materialized `list` input** when filtering `(candidate_name, is_fresh)` sequences in trash sweep (with pre-deduplicated candidate names so `seen` non-mutation cannot emit duplicates). |
| `synccli.copy_file(src, dst)` | `synccli.py:62–69` | `fdst.write(fsrc.read())` (reads entire file into RAM), swallows all `OSError` (`pass`), leaves 0-byte/truncated `dst` if read/write fails after open, no `chmod`, no `fstat` coherence check, no `ENOSPC` propagation. | **Override with `copy_file_verified(src, dst, expected_state, buf)`**: Fixed 1 MiB `readinto` buffer, pre/post `fstat` coherence verification, `chmod`, partial-`dst` unlink on error, fatal raise on destination `ENOSPC`/`EROFS`/`EIO`, explicit typed outcome for vanished/unreadable source files. |
| `synccli.sync(src_root, dst_root, dry_run=False)` | `synccli.py:72–88` | Mutates `dst_root` in-place, never removes deleted files, crashes on corrupt JSON manifest (`json.load`), writes full `src_manifest` non-atomically (`open(..., "w")`), and records failed/skipped copies in `.sync_manifest.json` so next pass never retries them. | **Override with `backupctl` staged multi-source snapshot engine**: Immutable per-run staging directory, `os.link` for unchanged files, `committed_manifest` recording only materialized files, atomic temp+`fsync`+`os.replace` manifests, atomic `os.rename` publish. |
| `snaputil.list_snapshots(backup_root)` | `snaputil.py:8–20` | `os.scandir(backup_root)` returning `sorted` names where `name.startswith("snap-") and entry.is_dir()` (follows symlinks, doesn't check regex, raises if `backup_root` missing). | **Reuse wrapped by `list_published_snapshots(backup_root)`**: Calls `snaputil.list_snapshots(backup_root)` after ensuring `backup_root` exists, filtering out symlinks (`os.path.islink`) and validating `^snap-\d{8}-\d{6}-\d{2}$`. Staging/trash/quarantine dirs never start with `"snap-"` so raw `snaputil.list_snapshots` callers are also safe. |
| `snaputil.prune_snapshots(backup_root, keep)` | `snaputil.py:23–36` | Deletes `names[:len(names) - keep]` via in-place `shutil.rmtree`. **Bug 1**: `keep <= 0` deletes *all* snapshots including newest (contradicting docstring line 27). **Bug 2**: In-place `rmtree` exposes half-deleted `snap-*` dirs to readers and crashes active readers. | **Override with `retire_and_sweep_snapshots(...)`**: Enforces `|Kept| >= 1` (pinning newest valid snapshot), GFS retention tiers, `flock(LOCK_EX | LOCK_NB)` reader check, atomic `os.rename` to `.trash/`, and grace-TTL `shutil.rmtree`. |
| `snaputil.snapshot_disk_usage(backup_root, snapshot_name)` | `snaputil.py:39–51` | `os.walk` summing `os.stat(...).st_size`. Follows symlinks (crashes on broken symlinks or concurrent unlinks), counts metadata files, and double-counts hardlinked inodes across snapshots. | **Reuse for single-snapshot raw byte check; override for multi-snapshot reporting with `compute_storage_stats(...)`**: Uses `os.lstat` (`S_ISREG`) under `sources/` and deduplicates `(st_dev, st_ino)` across snapshots to report both logical bytes and unique physical bytes (`st_blocks * 512`). |
| `snaputil.safe_snapshot_path(backup_root, snapshot_name, rel_path)` | `snaputil.py:54–63` | `os.path.join(backup_root, snapshot_name, os.path.normpath(rel_path))`. **Critical path-traversal bug**: `normpath("../../x")` stays `"../../x"`, escaping snapshot; `normpath("/etc/passwd")` causes `os.path.join` to discard `backup_root` and return `"/etc/passwd"`! | **Override completely with `resolve_safe_snapshot_path(backup_root, snapshot_name, source_name, rel_path)`**: Strict regex validation on `snapshot_name` and `source_name`, rejects absolute paths, NULs, and `..` components, and enforces `os.path.commonpath` + `realpath` containment. |
| `snaputil.is_stale(snapshot_dir, ref_epoch)` | `snaputil.py:66–74` | `return os.stat(snapshot_dir).st_mtime <= ref_epoch`. **Off-by-one bug**: Uses `<=` instead of `<`, returning `True` at exact `ref_epoch` (violating docstring lines 71–72). | **Override with `is_trash_expired(retired_epoch, cutoff_epoch)`**: Uses strict `<` (`retired_epoch < cutoff_epoch`) on explicit retirement epoch parsed from `.trash/` entry (with fallback to `st_mtime < cutoff_epoch`), feeding `(entry, not expired)` into `synccli.collect_stale`. |

### Detailed Notes on Critical Existing Bugs Overridden

1. **Silent permanent data loss in `synccli.copy_file` (`synccli.py:62–69`) + `synccli.sync` (`synccli.py:83–87`)**:
   - Line 69 comments `# unreadable source: skip it, next pass will retry`, yet line 86 dumps the *entire* pre-copy `src_manifest` to `.sync_manifest.json`. Consequently, an unreadable file is marked as backed up in `.sync_manifest.json` despite missing from `dst_root` (or left as a 0-byte file if `open(dst, "wb")` succeeded before `fsrc.read()` raised `EIO`). Worse, if a user subsequently fixes permissions via `chmod +r`, `chmod` updates `st_ctime`—**not** `st_mtime` or `st_size`—so `synccli.changed_files` (`synccli.py:40`) considers the file unchanged and **never retries it on any future pass**. `backupctl` overrides this by building `committed_manifest` strictly from files whose copy or hardlink succeeded; skipped files are omitted from `committed_manifest` so `synccli.changed_files` automatically selects them on the next run.
2. **Unbounded heap spike in `synccli.copy_file` (`synccli.py:67`)**:
   - `fdst.write(fsrc.read())` allocates the entire source file in Python heap at once. A single 1 GiB eval checkpoint causes a ≥1 GiB RAM spike. `backupctl` reuses a single pre-allocated `bytearray(1048576)` (`1 MiB`) with `fsrc.readinto(buf)` and `fdst.write(memoryview(buf)[:n])`.
3. **Broken security boundary in `snaputil.safe_snapshot_path` (`snaputil.py:54–63`)**:
   - Despite its docstring claiming returned paths never point outside `backup_root/<snapshot_name>`, `os.path.normpath("../../outside")` evaluates to `"../../outside"` and `os.path.join(backup_root, snap, "/etc/passwd")` evaluates to `"/etc/passwd"`. `backupctl` never calls `snaputil.safe_snapshot_path` directly; `resolve_safe_snapshot_path` enforces lexical rejection of absolute/`..` segments plus `os.path.commonpath` and `os.path.realpath` containment.
4. **Total wipeout bug in `snaputil.prune_snapshots` (`snaputil.py:31–33`)**:
   - For `names = ["snap-1", "snap-2"]` and `keep = 0`, `len(names) <= 0` is `False` and `names[:2 - 0]` deletes **every** snapshot; for `keep = -1`, `names[:2 - (-1)]` (`names[:3]`) also deletes **every** snapshot. `backupctl` enforces `keep_last = max(1, keep_last)` and unconditionally adds `newest_valid_snapshot` to the kept set.

---

## 3. On-Disk Layout, Snapshot Naming, and Path Containment

### Directory Layout under `backup_root`

```text
<backup_root>/
├── .lock                                      # Permanent 0-byte lockfile (0600); flock(LOCK_EX), never unlinked
├── index.json                                 # Root catalog of valid snapshots (written via index.json.tmp.<pid> + fsync + replace)
├── .staging/                                  # In-flight runs (starts with ".", invisible to snaputil.list_snapshots)
│   └── run-20261117T120000Z-48219-a91f3c/
│       ├── .active                            # Held with flock(LOCK_EX) by live worker PID 48219
│       ├── sources/
│       │   ├── eval-suite-a/                  # Pure point-in-time copy/hardlinks of source payload only
│       │   └── eval-suite-b/
│       ├── manifests/
│       │   ├── eval-suite-a.json              # {"files": {relpath: {size, mtime_ns, mode}}}
│       │   └── eval-suite-b.json
│       ├── .tree_complete                     # Seal written & fsynced after all files + manifests are synced
│       └── snapshot.json                      # Snapshot metadata, per-source counts/sha256s, skipped list
├── .trash/                                    # Atomically retired snapshots awaiting grace-period expiry
│   └── snap-20261110-080000-00.retired-1794916800/
├── .quarantine/                               # Unsealed/damaged directories moved out of snap-* namespace
└── snap-20261117-120000-00/                   # Published, immutable snapshot (atomic os.rename from .staging)
    ├── sources/
    │   ├── eval-suite-a/
    │   └── eval-suite-b/
    ├── manifests/
    │   ├── eval-suite-a.json
    │   └── eval-suite-b.json
    ├── .tree_complete
    └── snapshot.json
```

Why `manifests/<name>.json` lives outside `sources/<name>/`:
- A separate restore tool running `cp -R` or `rsync -a <backup_root>/snap-.../sources/eval-suite-a/ /repo/evals/suite_a/results/` copies **only** genuine user files—never injecting `.sync_manifest.json` into the live `evals/` directory (which `synccli.scan_files` at `synccli.py:15` would otherwise pick up as a data file on subsequent scans because `scan_files` skips dot-directories but not dot-files).

### Monotonic Snapshot Naming (`snap-YYYYMMDD-HHMMSS-NN`)

`snaputil.list_snapshots` (`snaputil.py:8–20`) sorts `snap-*` directory names lexicographically (`sorted(names)`). To keep `sorted(names)` strictly chronological even when multiple runs finish in the same second or when NTP / laptop wake adjusts the system wall clock backward:

1. Compute current UTC timestamp `now_ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())`.
2. Under `backup_root/.lock`, inspect the newest published snapshot `last_name` matching `^snap-(\d{8}-\d{6})-(\d{2})$`.
3. If no prior snapshot exists or `now_ts > last_ts`: allocate `snap-{now_ts}-00`.
4. If `now_ts <= last_ts` (same second or backward clock skew): clamp `ts = last_ts` and set `seq = last_seq + 1`. If `seq <= 99`, allocate `snap-{ts}-{seq:02d}`; if `seq == 100`, advance `ts` by `+1` UTC second and set `seq = 00`.

This preserves exact compatibility with `snaputil.py`'s `snap-20261112-150000-07` format while guaranteeing `new_name > last_name` under lexicographic sort.

### Safe Path Resolution (`resolve_safe_snapshot_path`)

```python
SNAP_RE = re.compile(r"^snap-\d{8}-\d{6}-\d{2}$")
SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")

def resolve_safe_snapshot_path(backup_root, snapshot_name, source_name, rel_path):
    if not SNAP_RE.match(snapshot_name):
        raise ValueError(f"Invalid snapshot name: {snapshot_name!r}")
    if not SLUG_RE.match(source_name) or source_name in {".", ".."}:
        raise ValueError(f"Invalid source name: {source_name!r}")
    if not rel_path or "\x00" in rel_path or os.path.isabs(rel_path):
        raise ValueError(f"Invalid relative path: {rel_path!r}")
    parts = rel_path.replace("\\", "/").split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"Traversal segment in path: {rel_path!r}")
    base = os.path.realpath(os.path.join(backup_root, snapshot_name, "sources", source_name))
    candidate = os.path.abspath(os.path.join(base, *parts))
    if os.path.commonpath([base, candidate]) != base:
        raise ValueError(f"Escaped snapshot root: {rel_path!r}")
    if os.path.lexists(candidate):
        if os.path.islink(candidate) or os.path.commonpath([base, os.path.realpath(candidate)]) != base:
            raise ValueError(f"Symlink or target outside snapshot root: {rel_path!r}")
    return candidate
```

---

## 4. Concurrency Control and Atomic Run Lifecycle

### Collision Matrix

| Concurrent Actors | Mechanism | Guarantee |
|---|---|---|
| **Scheduler run + Manual run** | `fcntl.flock(LOCK_EX)` on permanent `backup_root/.lock` (polled with monotonic deadline `--lock-timeout`, default `120s`) + per-staging `.active` `flock(LOCK_EX)` | Second run waits up to `120s`. Once Run 1 commits `snap-...-00`, Run 2 acquires `.lock`, uses `snap-...-00` as its incremental parent (avoiding duplicate 1 GB full copy), and publishes `snap-...-01`. If `--lock-timeout` expires, Run 2 exits `3` without touching staging or snapshots. |
| **Writer run + Concurrent restore reader** | Staging in `.staging/run-...`, immutable published `snap-*`, copy-on-`chmod` (never mutating shared inodes), atomic `os.rename` publish | Restore reads an immutable `snap-*` tree; writer only increments `st_nlink` on unchanged parent inodes via `os.link` and writes new files into private inodes under `.staging/`. Zero shared mutable state. |
| **Prune + Concurrent restore reader** | `flock(LOCK_SH)` on `O_RDONLY` `snap-*` dir_fd + atomic `os.rename` to `.trash/` + `3600s` grace TTL before `shutil.rmtree` | Active cooperative readers block `os.rename` outright (`LOCK_EX \| LOCK_NB` raises `BlockingIOError` → prune deferred). Uncooperative readers never see half-deleted `snap-*` in `list_snapshots`; open fds/`fwalk`/`cwd` handles remain intact in `.trash/` for 1 hour; shared hardlink inodes survive via POSIX `st_nlink`. |
| **Two `prune` / `run` processes** | Both require `flock(LOCK_EX)` on `backup_root/.lock` | Strictly serialized; no double-`rmtree` `FileNotFoundError` races. |

### Step-by-Step `backupctl run` Protocol

1. **Acquire writer lock**: Ensure `backup_root`, `.staging/`, `.trash/`, and `.quarantine/` exist (`0700`/`0755`). Open `backup_root/.lock` (`O_CREAT | O_RDWR`, `0600`, **never unlinked**) and acquire `fcntl.flock(lock_fd, LOCK_EX)` within `lock_timeout_seconds` (using `time.monotonic()`).
2. **Startup recovery & validation**: Sweep dead `.staging/*` directories and `*.tmp` files; verify or rebuild `backup_root/index.json` against on-disk `snap-*` directories (Section 5). Select newest verified snapshot `snap_prev` (if any) as incremental parent.
3. **Verify configured source roots**: Before copying, check `os.path.isdir(src.path)` and `os.access(src.path, os.R_OK | os.X_OK)` for all $N$ configured sources. If a configured root directory itself is missing or unmounted, abort with exit code `1` before creating a snapshot (preventing an unmounted volume from creating an empty snapshot that ages out valid backups).
4. **Create private staging tree**: Create `.staging/run-<utc>-<pid>-<rand>/`, open `.active`, and acquire `flock(active_fd, LOCK_EX | LOCK_NB)`.
5. **Process each source $i \in \{1..N\}$ sequentially**:
   - Load `old_manifest_i` from `snap_prev/manifests/<name_i>.json` (`{}` if first run or newly added source).
   - Run single-pass `scan_source_manifest(src_i.path)` → `(scanned_manifest_i, scan_skipped_i)`.
   - Compute `to_copy = set(synccli.changed_files(old_manifest_i, scanned_manifest_i))` (`synccli.py:36–42`).
   - Initialize empty `committed_manifest_i = {}`.
   - For each `rel, state` in `scanned_manifest_i.items()`:
     - **If `rel not in to_copy` (unchanged)**: verify `prev_file` in `snap_prev` via `os.lstat` (`S_ISREG` and `st_size == state["size"]`) and call `os.link(prev_file, dst_file)`. If `os.link` succeeds, set `committed_manifest_i[rel] = state`. If `prev_file` is missing or `os.link` hits `EMLINK` (max hardlinks per inode, e.g., 32,767 on APFS / 65,000 on ext4), fall through to `copy_file_verified` to start a fresh inode chain.
     - **If `rel in to_copy` (new or modified)**: call `copy_file_verified(src_file, dst_file, state, io_buf)`. On success, record verified `actual_state` in `committed_manifest_i[rel]`; on source disappearance/permission error/mid-copy race, ensure `dst_file` is unlinked and append to `skipped_i` (omitting `rel` from `committed_manifest_i`).
   - Atomically write `.staging/<run>/manifests/<name_i>.json` (`.tmp` → `flush` → `os.fsync` → `os.replace`), compute its SHA-256 and counts, append compact summary for source $i$, and **free `old_manifest_i`, `scanned_manifest_i`, and `committed_manifest_i`** before advancing to source $i+1$.
6. **Seal and sync staging snapshot**:
   - Call `os.sync()` once as a bulk data writeback barrier across all newly copied file inodes and directories (avoiding $F$ serial per-file cache flushes; Section 9).
   - Write `.staging/<run>/.tree_complete` containing JSON `{"total_files": ..., "sources": {name: {"files": count, "manifest_sha256": ...}}}`, `os.fsync` it, and `os.replace`.
   - Write `.staging/<run>/snapshot.json` (`.tmp` → `os.fsync` → `os.replace`) and `os.fsync` the `.staging/<run>` directory fd.
7. **Atomic publish**:
   - Allocate monotonic `snap_name = snap-YYYYMMDD-HHMMSS-NN`.
   - Close/unlink `.staging/<run>/.active` (still protected by `backup_root/.lock`).
   - Execute single atomic `os.rename(staging_dir, os.path.join(backup_root, snap_name))`, then `os.fsync(backup_root_dir_fd)`.
8. **Update root index & prune**:
   - Atomically update `backup_root/index.json` (`index.json.tmp.<pid>` → `os.fsync` → `os.replace` → `os.fsync(backup_root_dir_fd)`).
   - Run retention retirement (`snap-*` → `.trash/`) and expired `.trash/` reclamation (Section 8).
9. **Release `.lock` and emit report**: Close `lock_fd`, print summary report, and return deterministic exit code (`0` or `2`).

---

## 5. Process Death, Signal Handling, and Corrupt Index Recovery

### Interruption at Any Point

- **`SIGINT` (Ctrl-C) / `SIGTERM`**: Signal handler sets an abort flag, unlinks any currently open destination file in `.staging/<run>/`, removes `.staging/<run>/` if still unpublished, releases locks on exit, and exits `130` (`SIGINT`) or `143` (`SIGTERM`).
- **`SIGKILL`, power loss, kernel panic, or laptop sleep**:
  - **Mid-flight death before Step 7 (`os.rename`)**: Kernel closes all fds, immediately releasing `flock` on `.lock` and `.active`. Published `snap-*` directories and `index.json` were never touched. Nothing starting with `"snap-"` was created.
  - **Laptop sleep mid-run**: Lock timeouts and run durations use `time.monotonic()` / `time.perf_counter()`, never `time.time()`. Source files modified while the laptop slept are caught either by `copy_file_verified`'s pre/post `fstat` check (if sleep occurred mid-file) or on the next scheduled run; snapshot naming clamps backward NTP adjustments on wake.
  - **Destination disk full (`ENOSPC`)**: `copy_file_verified` and manifest writers propagate destination `ENOSPC` / `EROFS` / `EDQUOT` immediately as a fatal error, removing `.staging/<run>/` (reclaiming all newly written blocks immediately!), sweeping any already-expired `.trash/` entries, leaving all prior `snap-*` snapshots intact, and exiting `1`.

### Corrupt or Half-Written Index Recovery Protocol

When `backupctl` starts (under `backup_root/.lock`), it reconciles all three state layers—`.staging/`, `snap-*/{snapshot.json, manifests/*.json}`, and `backup_root/index.json`—before selecting `snap_prev`:

#### 1. What Is Discarded
- **Dead staging trees**: Every entry in `backup_root/.staging/` on which non-blocking `flock(LOCK_EX | LOCK_NB)` on `.active` succeeds (proving no live process owns it) is **discarded completely** via `shutil.rmtree`, including any partial files and half-written `.tmp` manifests inside it.
- **Orphan temp files**: Any `backup_root/index.json.tmp.*` or `snap-*/**/*.tmp` left behind by a killed run is **unlinked**.
- **Corrupt root index**: If `backup_root/index.json` is missing, truncated/unparseable (`json.JSONDecodeError`), fails schema/version/SHA-256 check, or its snapshot list disagrees with `list_published_snapshots(backup_root)` on disk, the in-memory/on-disk `backup_root/index.json` is **discarded**.
- **Unsealed `snap-*` directory vs. sealed `snap-*` with damaged index**:
  - If a `snap-*` directory on disk has a corrupt/missing `snapshot.json` or `manifests/<name>.json`, `backupctl` inspects `snap-*/.tree_complete`:
    - **No valid `.tree_complete` (or on-disk file count disagrees with `.tree_complete`)**: The directory tree itself cannot be proven complete (e.g., an external actor or un-journaled crash created an unsealed `snap-*`). To preserve the invariant *"never a mix / never mistaken for a complete snapshot"*, the entire unsealed `snap-*` directory is **quarantined out of `snap-*`** via atomic `os.rename(snap_dir, backup_root/.quarantine/<snap>-<epoch>)`.
    - **Valid `.tree_complete` present and file counts match**: The file tree in `snap-*/sources/` was 100% materialized and synced before crash; only the corrupt `snapshot.json` and/or corrupt `manifests/<name>.json` file(s) are **discarded**.
  - Additionally, if a `snap-*` manifest promises any file path that does not exist on disk (`not os.path.lexists`), that snapshot fails verification and is **quarantined** to `.quarantine/` rather than trusted.

#### 2. What Is Re-Derived from the Tree
- **Per-snapshot manifests (`manifests/<name>.json` and `snapshot.json`)** for any sealed `snap-*` whose JSON index was corrupt:
  - Walk each `snap-*/sources/<name>/` directory on disk using `scan_source_manifest` (grounded on `synccli.build_manifest` / `os.scandir` + `lstat`), computing `{relpath: {"size": st_size, "mtime_ns": st_mtime_ns, "mode": st_mode & 0o7777}}` directly from the snapshot's regular files on disk.
  - Verify reconstructed file count matches `.tree_complete["sources"][name]["files"]`.
  - Atomically write reconstructed `manifests/<name>.json` and `snapshot.json` (`.tmp` → `fsync` → `os.replace`).
- **Root catalog (`backup_root/index.json`)**:
  - Enumerate all surviving verified `snap-*` directories via `list_published_snapshots(backup_root)` (wrapping `snaputil.list_snapshots`).
  - Read each snapshot's verified `snapshot.json` (timestamp, source summaries, file counts, `logical_bytes`), recompute deduplicated `unique_physical_bytes` across `(st_dev, st_ino)` where needed, set `latest_snapshot = valid_snapshots[-1]`, and atomically write a fresh `backup_root/index.json` (`tmp` → `fsync` → `os.replace` → `fsync(backup_root)`).

#### 3. What the Run Reports
- Every recovery action emits both a structured `stderr` warning line (`WARN recovery action=<discarded_staging|rebuilt_root_index|rebuilt_snapshot_index|quarantined_unsealed_snapshot> target=<path> detail=<reason>`) and an entry in the run's `recovery_actions` array in `snapshot.json` and stdout summary—identical whether invoked by scheduler or human—and the run continues immediately without manual intervention.

---

## 6. Incremental Change Detection, Granularity, and Missed Edits

### How Incremental Runs Avoid Re-Copying Unchanged Files

1. `backupctl` loads `old_manifest` (`{relpath: state}`) for source $i$ from `snap_prev/manifests/<name_i>.json` and scans `src_i` into `new_manifest`.
2. It calls **`synccli.changed_files(old_manifest, new_manifest)` (`synccli.py:36–42`)** directly to obtain `to_copy` (new or changed paths).
3. Paths in `old_manifest.keys() - new_manifest.keys()` (deleted in source since `snap_prev`) are simply omitted from the new snapshot.
4. Paths in `new_manifest.keys() - set(to_copy)` (**unchanged files**) are linked into `.staging/<run>/sources/<name_i>/<rel>` via `os.link` from `snap_prev/sources/<name_i>/<rel>`—zero file reads from `src_i`, zero file data writes to `backup_root`, zero new data blocks allocated.

### Exact Granularity of "Unchanged"

"Unchanged" is decided at **whole-file POSIX `lstat` metadata granularity** per relative path `relpath`, comparing exact equality on the 3-field dictionary:

```python
{"size": st.st_size, "mtime_ns": st.st_mtime_ns, "mode": st.st_mode & 0o7777}
```

Why these exact three fields (and why `synccli.file_state` at `synccli.py:22–25` is overridden):
- **`size` (`int`)**: Exact logical byte length. Any append, truncation, or different-length rewrite changes `size`.
- **`mtime_ns` (`int`, integer nanoseconds)**: `synccli.file_state` (`synccli.py:25`) stores `st.st_mtime` as an IEEE-754 `float`. At 2026 Unix epochs ($\approx 1.79 \times 10^9\text{ s} \approx 2^{30.74}$), 53-bit float significands retain only $53 - 31 = 22$ fractional bits ($\approx 238\text{ ns}$ step size), silently aliasing distinct sub-238 ns APFS/ext4/XFS modifications. `st_mtime_ns` preserves full 1 ns resolution losslessly in JSON.
- **`mode` (`st.st_mode & 0o7777`)**: Because hardlinked snapshot files share a single inode, calling `chmod` in place would mutate permissions visible in historical snapshots. Including `mode` in `file_state` causes `synccli.changed_files` to treat a permission change as a changed file, copying it into a **new inode** with the new mode while leaving historical snapshots' inodes untouched.
- **Whole-file (not sub-file block/CDC)**: Appending 1 KB to a 100 MB log copies the full 100 MB file into a new inode rather than deduplicating sub-file chunks.

### Edits This Granularity Can Miss

Routine metadata-only comparison (`size`, `mtime_ns`, `mode`) **cannot detect** the following four classes of edits unless `--verify-checksums` (full SHA-256 content scan) is enabled:

1. **Same-size content edits with preserved/restored `mtime`**: An external tool modifies bytes in place (leaving `st_size` identical) and explicitly resets `mtime` to its previous value via `utimensat` / `os.utime` (e.g., `cp -p`, `tar -xp`, `rsync -t`, `touch -r`), or atomically `rename`s a different file over `relpath` that happens to have the exact same `(size, mtime_ns, mode)`.
2. **Same-size in-place overwrites within a single filesystem timestamp quantum ("racy mtime")**: A file is written, scanned by `backupctl`, and overwritten in place to the **exact same byte count** within the same kernel filesystem clock tick:
   - **macOS APFS**: `1 ns` timestamp resolution (practically non-occurring unless guest VM clock is coarse).
   - **Linux ext4 / XFS**: Kernel `current_time(inode)` uses coarse timer ticks (`1 ms–4 ms` depending on `CONFIG_HZ`), so a second same-size write within `< 4 ms` of the first write shares the exact `st_mtime_ns`!
   - **Legacy / external volumes**: HFS+ (`1 s` resolution) and FAT32 (`2 s` resolution) miss same-size rewrites within 1–2 seconds.
   - *Built-in mitigation (Git-index style racy-clean guard)*: `snapshot.json` records `scan_start_wall_ns` for each source. On the next run, any unchanged candidate whose `old_manifest[rel]["mtime_ns"] >= prev_scan_start_wall_ns - 2_000_000_000` (modified within 2 seconds prior to or during the previous scan) is byte-compared against `snap_prev` once before hardlinking, closing the sub-tick race window at near-zero cost.
3. **Silent media corruption (bit-rot) on source storage**: Underlying flash/disk bit flips alter file payload without passing through VFS write syscalls, leaving `size`, `mtime_ns`, and `mode` unchanged.
4. **Metadata outside `(size, mtime_ns, mode & 0o7777)`**: Ownership changes (`chown` modifying `st_uid`/`st_gid`), extended attributes (`setxattr`), and POSIX ACLs update `st_ctime_ns` only and are neither tracked nor backed up.

---

## 7. Disappearing, Unreadable, and Mid-Copy Mutating Source Files

Behavior is **100% identical** regardless of whether `backupctl` was invoked by a scheduler (`cron`/`launchd`/`systemd`) or interactively by a person—no `--quiet` or `--cron` flag alters snapshot contents, error records, output streams, or exit codes.

### File-Level Failure Semantics (`copy_file_verified` & `scan_source_manifest`)

| Condition | Detection Point | What the Snapshot & Index Contain | What Next Run Does |
|---|---|---|---|
| **Vanished file** (`ENOENT`, or replaced by directory `EISDIR`) | Between `scandir` and `lstat`, or between `lstat` and `open(src, "rb")` | **Omitted** from `sources/<name>/` (any partial staging file `unlink`ed). **Omitted** from `manifests/<name>.json["files"]` (never carried forward from `snap_prev`, which would resurrect a deleted file). Recorded in `snapshot.json["skipped"]` with `reason="vanished"`. | If permanently deleted: absent in source, clean `0` exit. If transiently gone and recreated: absent from `old_manifest`, so `changed_files` detects it as new and copies it. |
| **Unreadable file or subdirectory** (`EACCES`, `EPERM`, `EIO`) | `os.scandir` directory error, `lstat`, `open(src, "rb")`, or `fsrc.readinto` | **Omitted** from `sources/<name>/` (`dst` `unlink`ed if `open(dst, "wb")` had already created an empty/partial file—fixing `synccli.py:66–69`). **Omitted** from `manifests/<name>.json["files"]`. Recorded in `snapshot.json["skipped"]` with `reason="unreadable"` or `"unreadable_dir"`. | Because the file is absent from `old_manifest`, fixing permissions (`chmod +r`) causes `changed_files` to treat it as **new** on the next run and copy it—even though `chmod` leaves `(size, mtime_ns)` unchanged (fixing `synccli.py:85–86`). |
| **Mid-copy concurrent mutation / truncation** | `fstat(fsrc)` before read vs. `fstat(fsrc)` after read (`size`, `mtime_ns`, `ctime_ns`, `ino` mismatch, or `bytes_copied != size`) | Retried up to **2 times** immediately. If coherent on retry, copied bytes + post-copy `actual_state` are committed. If still mutating after 2 retries, `dst` is `unlink`ed, omitted from `manifests/<name>.json["files"]`, and recorded in `skipped` with `reason="concurrently_modified"`. | Absent from `old_manifest` (or has old state != settled state), so next run copies the settled file cleanly; no torn half-old/half-new file ever enters a snapshot. |
| **Non-regular entry** (symlink, FIFO, socket, device node) | `entry.is_file(follow_symlinks=False)` / `stat.S_ISREG(st.st_mode)` is `False` | **Omitted** without opening (never follows symlinks outside source, never blocks on a FIFO, never creates broken symlinks that would crash `snaputil.snapshot_disk_usage` at `snaputil.py:50`). Recorded in `skipped` with `reason="non_regular"`. | Skipped deterministically until replaced by a regular file. |

### Reporting and Exit Codes (Identical for Scheduler and Person)

- **Snapshot publication**: As long as all configured source roots exist and `backup_root` is healthy, the snapshot of all readable, coherent regular files **commits normally**. One `chmod 000` scratch file or one vanishing temp checkpoint never aborts backing up the remaining 49,999 eval files.
- **Diagnostic output**:
  1. Per-item warning written to `stderr`: `WARN skipped source=<name> path=<rel> reason=<vanished|unreadable|unreadable_dir|concurrently_modified|non_regular> errno=<ERRNO>`
  2. Persisted inside `snap-.../snapshot.json["skipped"]` (auditable post-hoc).
  3. Run summary written to `stdout` (`snapshot=snap-... status=partial|ok files_total=... copied=... linked=... vanished=... unreadable=... bytes_copied=... duration_ms=...`, or JSON with `--json`).
- **Deterministic exit codes**:
  - `0`: Snapshot committed cleanly; `0` vanished/unreadable/concurrently-modified errors (`non_regular` symlinks logged informational only, or configurable).
  - `2`: **Partial snapshot committed** (snapshot is 100% self-consistent and usable; its manifest matches its contents; ≥1 source file/subdir was `vanished`, `unreadable`, or `concurrently_modified`).
  - `1`: **Fatal error — no snapshot committed** (invalid config, missing/unmounted configured source root, `ENOSPC`/`EIO` on `backup_root`).
  - `3`: **Lock contention timeout** (`backup_root/.lock` remained busy past `--lock-timeout`).

---

## 8. Retention Policy and Reader-Safe Deletion

### Retention Policy Definition

Retention evaluates **only verified, usable snapshots** (`list_verified_snapshots(backup_root)`), ordered oldest-first `S[0] ... S[m-1]`. By default (`backupctl.json` overrides supported):

- **`keep_last = 10`**: Keep the $\max(1, \text{keep\_last})$ newest snapshots unconditionally.
- **`keep_daily = 7`**: Group snapshots by UTC date `YYYYMMDD` (parsed from `snap-YYYYMMDD-HHMMSS-NN`); keep the newest snapshot of each of the most recent 7 distinct UTC days present.
- **`keep_weekly = 4`**: Group snapshots by ISO year-week `(iso_year, iso_week)`; keep the newest snapshot of each of the most recent 4 distinct ISO weeks present.
- **Unconditional usability invariant**:
  $$\text{Kept} = \{S[m-1]\} \cup \text{Last}(\max(1, \text{keep\_last})) \cup \text{Daily}(\text{keep\_daily}) \cup \text{Weekly}(\text{keep\_weekly})$$
  `Doomed = [s for s in S if s not in Kept]` (oldest first). Because $S[m-1]$ (the newest verified snapshot) is explicitly pinned in $\text{Kept}$, **deletion can never leave `backup_root` with zero usable snapshots**, even if a user configures `keep_last = 0, keep_daily = 0, keep_weekly = 0` (overriding the wipeout bug in `snaputil.prune_snapshots` at `snaputil.py:31–33`). Furthermore, during `backupctl run`, retention executes **only in Step 8 (after the new snapshot is published and verified)**.

### Reader-Safe Two-Phase Deletion Protocol

Directly calling `shutil.rmtree(backup_root/snap-X)` (as `snaputil.prune_snapshots` does at `snaputil.py:35`) breaks concurrent readers in two ways: `snaputil.list_snapshots` continues listing `snap-X` while half its files are missing, and a restore walking `snap-X` receives `ENOENT` mid-copy. `backupctl` replaces in-place `rmtree` with a two-phase protocol under `backup_root/.lock`:

1. **Phase 1 — Reader lock probe + atomic namespace retirement (`snap-*` → `.trash/`)**:
   - Open `dir_fd = os.open(os.path.join(backup_root, snap_name), os.O_RDONLY)` and attempt non-blocking `fcntl.flock(dir_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` (verified empirically on Darwin APFS & Linux VFS: `LOCK_SH` acquired on an `O_RDONLY` directory fd by a reader blocks `LOCK_EX` without requiring write permissions or lockfiles inside the snapshot).
   - If `BlockingIOError`: an active cooperative reader (`backupctl` restore or `flock -s <snap_dir> <cmd>`) is reading `snap_name` right now. Close `dir_fd`, leave `snap_name` untouched under `backup_root/`, and log `prune_deferred_reader_active`; the next run will retire it.
   - If `LOCK_EX` succeeds: atomically move the directory out of the `snap-*` namespace via `os.rename(backup_root/snap_name, backup_root/.trash/f"{snap_name}.retired-{int(time.time())}")`, `os.fsync(backup_root_dir_fd)`, close `dir_fd`, and update `backup_root/index.json`.
   - **Effect**: `snap_name` vanishes from `snaputil.list_snapshots(backup_root)` in a single atomic kernel metadata operation. **Zero files or subdirectories inside the snapshot have been unlinked**, so any uncooperative external process already holding open file descriptors, `os.fwalk`/`openat` directory descriptors, or `cwd` inside that snapshot continues reading a 100% intact tree!
2. **Phase 2 — Grace-period physical reclamation (`.trash/` sweep)**:
   - Let `cutoff_epoch = time.time() - trash_grace_seconds` (default `trash_grace_seconds = 3600` seconds = 1 hour, $>100\times$ the ~3–19s time needed to read a 1 GB snapshot).
   - Enumerate deduplicated entries in `backup_root/.trash/`, parse `retired_epoch` (falling back to `os.lstat(entry).st_mtime`), compute `is_fresh = not (retired_epoch < cutoff_epoch)` (using **strict `<`**, explicitly fixing `snaputil.is_stale`'s `<=` off-by-one bug at `snaputil.py:73`), and pass the materialized list `[(name, is_fresh), ...]` to **`synccli.collect_stale(items)` (`synccli.py:45–60`)** to obtain expired `.trash/` entries.
   - For each expired `.trash/` entry, probe `flock(dir_fd, LOCK_EX | LOCK_NB)` once more; if unlocked, run `shutil.rmtree` inside `.trash/`.
   - **Crash & inode safety**: If `backupctl` is killed mid-`rmtree`, the half-deleted remnant sits inside `.trash/` (never `snap-*`) and is finished automatically on the next run. Any file hardlinked into newer kept snapshots has `st_nlink >= 2`, so `unlink` only decrements `st_nlink`; even for `st_nlink == 1`, POSIX keeps file data blocks alive until the last open fd closes.

---

## 9. Initial ~1 GB Full Backup Performance Budget

### Empirical Measurements on This Repository's Host

To ground the budget in real numbers rather than guesses, benchmarks were executed on this host (`Python 3.10.11`, macOS Darwin on APFS NVMe SSD) comparing existing `synccli.sync` against `backupctl`'s staged pipeline (single-pass `os.scandir` + `lstat`, 1 MiB `readinto` chunked copy + `chmod`, compact JSON manifest `.tmp` + `fsync` + `replace`, `os.sync()`, atomic `os.rename`, parent dir `fsync`) across four file-count regimes at `~1.02–1.07 GB`:

| Workload (`~1 GB` Payload) | `F` (Files) | Avg File Size | Scan (`s`) | Copy + `chmod` (`s`) | Index + `sync` + Rename (`s`) | **Total Wall Time (`s`)** | Peak Python Heap (`tracemalloc`) | Compact Manifest Disk Size |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Large checkpoints (`1.049 GB`) | `10` | `100 MiB` | `<0.01` | `0.745` | `0.061` | **`0.806 s`** | `1.05 MiB` | `0.001 MiB` |
| Medium eval artifacts (`1.024 GB`) | `10,000` | `100 KiB` | `0.266` | `2.701` | `0.177` | **`3.144 s`** | `4.25 MiB` | `0.76 MiB` |
| **Canonical mixed evals (`1.070 GB`)*** | **`25,000`** | **`41.8 KiB` (8K–5M)** | **`0.807`** | **`8.092`** | **`0.277`** | **`9.175 s`** | **`12.08 MiB`** | **`2.14 MiB`** |
| Existing `synccli.sync` on same 25k tree | `25,000` | `41.8 KiB` (8K–5M) | `1.217` | *(in-place, no sync)* | *(unbuffered `json.dump`)* | `10.308 s` | `15.13 MiB`† | `2.23 MiB` |
| Small-file stress (`1.024 GB`) | `50,000` | `20 KiB` | `1.375` | `16.731` | `0.452` | **`18.558 s`** | `21.65 MiB` | `3.77 MiB` |

*\*Canonical mixed tree: 250 subdirectories containing 20,000 × 8 KiB JSON metrics + 4,750 × 128 KiB logs + 245 × 1 MiB artifacts + 5 × 5 MiB checkpoints = 25,000 files, 1,020 MiB (`1.070 GB`).*
*†`synccli.sync` peaked at `15.13 MiB` only because max file size was `5 MiB`; with a single `500 MiB` checkpoint, `synccli.copy_file` (`fsrc.read()`) spikes heap by `+500 MiB`, whereas `backupctl`'s copy buffer remains fixed at `1.00 MiB`.*

### Explicit Analytical Cost Derivation

Fitting the four measured regimes separates byte-streaming bandwidth from per-file VFS syscall cost:

$$T_{\text{full}}(F, B) = c_B \cdot B + c_F \cdot F + t_{\text{commit},0}$$

1. **Sequential read + write + sync cost ($c_B = 0.77\text{ s/GB}$)**: Measured from `F = 10, B = 1.049 GB` (`0.806 s / 1.049 GB = 0.768 s/GB`, i.e., `1.30 GB/s` end-to-end read+write+sync).
2. **Per-file VFS metadata & syscall cost ($c_F \approx 340\text{–}355\text{ }\mu\text{s/file}$)**: Comparing `F = 10,000` (`3.144 s`) and `F = 50,000` (`18.558 s`) at identical `B = 1.024 GB`:
   $$c_F = \frac{18.558\text{ s} - 3.144\text{ s}}{50{,}000 - 10{,}000} = 385.4\text{ }\mu\text{s/file} \quad (\text{and } 333\text{ }\mu\text{s/file at } F = 25{,}000)$$
   Decomposed by stage:
   - Single-pass `os.scandir` + `DirEntry.stat(follow_symlinks=False)`: **`27–32 µs/file`** (`33.7%` faster than `synccli.build_manifest`'s `48.7 µs/file` [`1.217 s / 25,000`], which pays `os.path.relpath` `abspath` calls + a second `os.stat` syscall per file).
   - File `open(src)` + `fstat`×2 + `open(dst, O_CREAT|O_WRONLY)` + `chmod` + `close`×2: **`305–345 µs/file`** (dominates wall time at >85% for small eval files!).
   - Compact JSON manifest serialization (`separators=(",", ":")`): **`~7–9 µs/file`**.
3. **Fixed commit barrier ($t_{\text{commit},0} \approx 0.06\text{ s}$)**: One `os.sync()` barrier + `.tree_complete` `fsync` + `snapshot.json` `fsync` + `os.rename` + `backup_root` dir `fsync` + `index.json` `fsync`. *(Crucial design choice: issuing `os.fsync` per file across 25,000 files would add `25,000 × ~0.5–1.5 ms = 12.5–37.5 s` of serial cache-flush stalls; batching file writes followed by a single pre-seal sync barrier achieves crash-safe staging in `~0.06–0.20 s`.)*

### Committed Performance Budget (~1 GB Initial Full Backup)

- **Canonical target (`B = 1.0 GB`, `F = 25,000` files)**:
  - **Expected measured time**: **`~9.2 s`** (`0.8 s` scan + `8.1 s` copy + `0.3 s` seal/sync/publish).
  - **Committed SLO budget ceiling**: **`≤ 15.0 s`** on local SSD (providing `~60%` headroom for cold VFS cache and concurrent host load).
- **Upper tens-of-thousands bound (`B = 1.0 GB`, `F = 50,000` files)**:
  - **Expected measured time**: **`~18.6 s`**.
  - **Committed SLO budget ceiling**: **`≤ 25.0 s`** on local SSD.

---

## 10. Scaling from $N = 3$ to $N = 36+$ Directories: Explicit Bounds

### Notation

- $N$: number of configured source directories ($N = 3$ today; $N = 36$ at a few dozen).
- $F_i, D_i, B_i$: regular file count, non-hidden subdirectory count, and logical bytes of source $i$; $F = \sum_{i=1}^N F_i$, $D = \sum_{i=1}^N D_i$, $B = \sum_{i=1}^N B_i$.
- $F_{\max} = \max_{1 \le i \le N} F_i$, $D_{\max} = \max_{1 \le i \le N} D_i$: files and subdirectories in the **single largest** source directory.
- $\Delta F, \Delta B$: changed/new files and their logical bytes in an incremental run; $F_{\text{unch}} = F - \Delta F$ unchanged files; $S_{\max}$: largest single file size in bytes.
- $K_{\text{live}}$: retained snapshots under `backup_root` (under default `keep_last=10, keep_daily=7, keep_weekly=4`, **$1 \le K_{\text{live}} \le 21$**); $K_{\text{trash}}$: retired snapshots currently within the `3600 s` grace window (at 4 runs/hour, $K_{\text{trash}} \le 4$); $K_{\text{tot}} = K_{\text{live}} + K_{\text{trash}} \le 25$.

### Explicit Scaling Bounds Table

| Resource / Metric | Exact Bound / Formula | Concrete Value ($N=3$, $10\text{k}$ files & $0.35\text{ GB}$/dir $\Rightarrow F=30\text{k}, B=1.05\text{ GB}$) | Concrete Value ($N=36$, $10\text{k}$ files & $0.35\text{ GB}$/dir $\Rightarrow F=360\text{k}, B=12.6\text{ GB}$) | Grows With / Stays Flat |
|---|---|---|---|---|
| **Copy I/O buffer RAM** | **`1,048,576 B` (`1.00 MiB`)** | `1.00 MiB` | `1.00 MiB` | **Flat (`1,048,576 B`)** — independent of $N, F, B, S_{\max}$ |
| **Open file descriptors** | **`≤ 5` fds** (`1` `.lock` + `1` `.active` + `≤ 2` `[fsrc, fdst]` or `1` `scandir` + `1` transient sync fd) | `≤ 5` fds | `≤ 5` fds | **Flat (`≤ 5` fds)** — independent of $N, F, D, K$ (iterative `scandir` closes dir_fd before descending; well under macOS `256` soft limit) |
| **Peak Python heap RAM** | $\le 1.5\text{ MiB} + 1{,}000\text{ B} \cdot F_{\max} + 120\text{ B} \cdot D_{\max} + 1{,}024\text{ B} \cdot N + K_{\text{live}}(512\text{ B} + 120\text{ B} \cdot N)$ | **`~11.1 MiB`** ($F_{\max}=10\text{k}$) | **`~11.2 MiB`** ($F_{\max}=10\text{k}$) | **Independent of $\sum F_i$ and $B$**; grows with single-dir $F_{\max}$ (`~460 B/file` × 2 manifests + `changed_set` measured) + tiny **`~1.0 KiB · N`** (`+33 KiB` from $N=3\to 36$) |
| **Full-run data bytes read / written** | Read: $B$; Written: $B + 90\text{ B} \cdot F + 350\text{ B} \cdot N + I_{\text{root}}$ | `1.05 GB` read / `1.053 GB` written | `12.60 GB` read / `12.63 GB` written | Linear in total $B$ and $F$ |
| **Incremental-run source file bytes read & data blocks written** | **$\Delta B$ bytes** (`0 B` for all $F_{\text{unch}}$ unchanged files) | **`0 B`** (if $\Delta F=0$); `10.5 MB` (if `1%` changed) | **`0 B`** (if $\Delta F=0$); `126 MB` (if `1%` changed) | **Linear in changed bytes $\Delta B$ ONLY**; **flat at `0 B`** with respect to unchanged bytes $(B - \Delta B)$ |
| **Incremental-run metadata syscalls & wall time (APFS)** | $(D + N)$ `scandir` + $F$ `lstat` + $F_{\text{unch}}$ `os.link` + $\Delta F$ copy; $T_{\text{inc}} \approx 370\text{ }\mu\text{s} \cdot F + 0.77\text{ s/GB} \cdot \Delta B + 2.5\text{ ms} \cdot N + 0.06\text{ s}$ | `~11.2 s` ($\Delta B = 0$) | `~133 s` ($\Delta B = 0$, 360k files on APFS; `~18 s` on Linux ext4 where `link` is `~20 µs`) | Syscalls linear in total $F = \sum_{i=1}^N F_i$ and $D$; byte I/O linear only in $\Delta B$ |
| **Per-run manifest I/O** | Read $\approx 90\text{ B} \cdot F_{\text{prev}}$; Write $\approx 90\text{ B} \cdot F + 350\text{ B} \cdot N$ | `2.58 MiB` read + `2.58 MiB` written | `30.9 MiB` read + `30.9 MiB` written | Linear in $F$ (`~90 B/file` measured compact JSON) |
| **Root `backup_root/index.json` size** | $\le 256\text{ B} + K_{\text{live}} \cdot (512\text{ B} + 120\text{ B} \cdot N)$ | **`≤ 18.4 KiB`** (at $K_{\text{live}}=21$) | **`≤ 101.7 KiB`** (at $K_{\text{live}}=21$) | **Flat (`0 B/file`) w.r.t. $F$ and $B$**; bounded by $O(K_{\text{live}} \cdot N)$ |
| **Total disk usage under `backup_root`** | $\underbrace{B_{\text{aligned}} + \sum_{t=2}^{K_{\text{tot}}} \Delta B_{\text{aligned},t}}_{\text{unique file data}} + \underbrace{K_{\text{tot}} \cdot (90\text{ B} \cdot F + 96\text{ B} \cdot F + 4{,}096\text{ B} \cdot (D+N))}_{\text{manifests + hardlink dentries}}$ | `1.05 GB` base + $\sum \Delta B_t$ + **`~5.6 MiB/snap`** (`~118 MiB` across $K_{\text{live}}=21$) | `12.60 GB` base + $\sum \Delta B_t$ + **`~67 MiB/snap`** (`~1.41 GB` across $K_{\text{live}}=21$) | Unique file data grows with $B + (K_{\text{tot}}-1)\overline{\Delta B}$ (**`0` extra data blocks for unchanged files**); dentry + manifest overhead is `~186 B · F · K_tot` |
| **Steady-state `.staging/` disk** | **`0 B`** idle; $\le \Delta B_{\text{run}} + 90\text{ B} \cdot F$ during 1 active run | `0 B` idle | `0 B` idle | **At most `1` active staging tree** (serialized by `backup_root/.lock`) |

### Key Scaling Takeaways

1. **Why sequential per-source manifests matter at $N = 36$**: Had all $N$ manifests been held in one monolithic dictionary in RAM, growing from $N = 3$ (`30,000` files) to $N = 36$ (`360,000` files) would multiply peak Python heap $12\times$ (`~360 MiB` for two manifests + diff sets). Processing one source `manifests/<name_i>.json` at a time keeps peak heap at **`~11.2 MiB`** when each directory has `10,000` files (`~25.5 MiB` when $F_{\max} = 25{,}000$), growing by only **`~1 KiB` per added configured directory**.
2. **Retention bounds `K_live <= 21` automatically**: With `keep_last=10`, `keep_daily=7`, and `keep_weekly=4`, the union `Kept` contains **at most $10 + 7 + 4 = 21$ snapshots** (often fewer when tiers overlap), preventing unbounded accumulation of both churned data blocks and per-snapshot manifest/dentry metadata while always preserving at least `1` usable snapshot.

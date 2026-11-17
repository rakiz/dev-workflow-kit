# DESIGN-d1 — `backupctl`

Design for `backupctl`, a snapshot backup tool for the directories listed in
its config. Written alone, no delegation. Every claim about the existing code
cites `file:line` and was checked by reading the code and, where stated, by
running it (`python3 -m unittest`: 6 tests pass; plus the probes listed in
section 9).

---

## 1. Summary

- A **run** builds a complete snapshot `snap-<YYYYmmdd>-<HHMMSS>-<seq:04d>/`
  in a staging area, then publishes it with one atomic `rename`. A snapshot
  directory exists under its final name only if it is complete.
- **One writer at a time**: a run takes an exclusive `flock` on
  `.backupctl/run.lock`. The kernel releases it on process death, so a killed
  run never leaves a stale lock.
- **Readers** (restore) take a shared `flock` on a per-snapshot lock file.
  Pruning takes the exclusive lock, so it cannot delete a snapshot being read.
- **The committed snapshot's `MANIFEST.json` is the index.** No separate index
  file exists, so there is no index that can be half-written.
- **Unchanged files** are hardlinked from the newest valid snapshot. Change
  detection is per file on `(size, mtime_ns, inode)`, with a racy-timestamp guard.
- **Vanished or unreadable sources** are skipped, recorded in the manifest
  and in the run report, and the snapshot is still published. The behavior is
  identical for scheduler and person runs.
- **Retention** keeps the newest `K` valid snapshots (default 14, minimum 1).
- **Performance budget**: initial full backup of ~1 GB / 30,000 files
  <= 60 s on the measurement host (derivation in section 7).

---

## 2. Grounding: what is reused and what is overridden

Existing artifacts in this directory (line numbers as read):

| Artifact | What it does today | Decision |
|---|---|---|
| `synccli.py:10-19` `scan_files` | `os.walk`, returns sorted relative paths. | **Override.** Line 14 (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`) silently drops every dot-directory from the backup. `backupctl` includes dot-directories by default (evals output often lives in them). Symlinks are not followed and are recorded as skipped (os.walk lists file symlinks in `filenames`, so they must be filtered explicitly). |
| `synccli.py:22-25` `file_state` | `os.stat` -> `{size, mtime}`; `mtime` is a float in seconds. | **Override.** Use `lstat` -> `{size, mtime_ns, ino}`. Float seconds lose nanosecond precision, and inode is needed so that an atomic-rename replacement is detected. |
| `synccli.py:28-33` `build_manifest` | Lists, then stats each file. No error handling: a file deleted between `scan_files` and `os.stat` raises `FileNotFoundError` and aborts the whole run. | **Override.** The manifest is built from what was actually copied or linked, per file, with per-file error capture (section 6). |
| `synccli.py:36-42` `changed_files` | Returns paths that are new or whose state dict differs. | **Reused unchanged** as the "what must be copied" primitive. It works with the new state dict. The racy-timestamp rule is applied by the caller before the call (section 5), not inside the function. |
| `synccli.py:45-59` `collect_stale` | Filters `(path, fresh)` items. | **Not reused.** No caller in the repo (grep: only `test_synccli.py:24-32` calls it). Not part of the design. |
| `synccli.py:62-69` `copy_file` | Reads the whole file into memory (`fsrc.read()`, line 67), writes straight into the destination, and swallows every `OSError` (lines 68-69) including write errors such as ENOSPC. | **Override.** Streaming copy in 1 MiB chunks, into `<name>.part`, fsync, then rename. Only **source** read errors become skips; **destination** write errors abort the run. Reason: line 69's comment says "next pass will retry", but see the next row. |
| `synccli.py:72-87` `sync` | Builds the manifest from the listing taken **before** copying (line 74), then writes it after copying (lines 85-86). A file that fails to copy is still recorded as up to date, so it is never retried. The manifest write is not atomic. | **Override the function.** Verified (section 9.1): a listed file that fails to copy is written into the manifest, and the next run skips it (`copied: []`). Verified (section 9.2): a truncated manifest makes the next run raise `JSONDecodeError`. |
| `synccli.py:7` `MANIFEST_NAME` | `.sync_manifest.json` stored in the destination root, next to user data. | **Override.** The manifest is `MANIFEST.json` inside each snapshot directory. A dst-root manifest can collide with user data. |
| `snaputil.py:8-20` `list_snapshots` | Lists `snap-*` directories, sorted by name. | **Reused for enumeration, then filtered** by validation (section 6). Sorting is lexical, so `snap-...-9` sorts after `snap-...-10`. Verified (section 9.3). `backupctl` uses a 4-digit zero-padded sequence and sorts by the `seq` field in the manifest. Also line 18 `entry.is_dir()` follows symlinks. |
| `snaputil.py:23-36` `prune_snapshots` | Deletes the oldest entries beyond `keep` with `rmtree`. Counts incomplete entries toward `keep`. No lock, not atomic. | **Override.** With `keep=1` and entries `[valid A, incomplete B]`, it deletes A and leaves no usable snapshot. The design counts only valid snapshots, deletes via atomic rename after an exclusive reader-lock check. |
| `snaputil.py:39-51` `snapshot_disk_usage` | Sums `st_size` over files (`os.stat` follows symlinks). | **Reused with one change**: deduplicate by `(st_dev, st_ino)`. Hardlinked files (section 5) would otherwise be counted once per snapshot. |
| `snaputil.py:54-63` `safe_snapshot_path` | Claims the result cannot leave the snapshot. | **Override.** Verified (section 9.4): `safe_snapshot_path('/bk','snap-x','../../etc/passwd')` returns `/bk/snap-x/../../etc/passwd` (`normpath` keeps leading `..` on relative paths), and `'/etc/passwd'` returns `/etc/passwd` (`os.path.join` discards the root). The design rejects absolute paths and any `..` component before joining. |
| `snaputil.py:66-73` `is_stale` | Docstring (line 71) says mtime equal to `ref_epoch` is **not** stale; line 73 uses `<=`. | **Not reused.** Verified (section 9.5): equal mtime returns True (stale). Contradicts its own docstring. The design does not use it. |
| `snaputil.py:76-88` `main` | CLI. | Not reused. `backupctl` has its own CLI. |
| `test_synccli.py` | 6 tests, all pass. None covers dot-directories, vanished files, or manifest atomicity. | Existing tests kept. New tests are required for every override above (section 10). |

Reused as-is: `changed_files` (`synccli.py:36-42`), the `scan_files` sorted
relative-path convention (`test_synccli.py:17-18`), `list_snapshots` for
enumeration only, `snapshot_disk_usage` with the dedup change.

---

## 3. On-disk layout

```
<backup_root>/
  snap-20261116-220000-0007/        committed snapshot, read-only, never modified
    MANIFEST.json                   index: files, skipped entries, hashes, checksum
    <dirname>/...                   one subtree per configured directory
  .backupctl/
    run.lock                        flock target: one writer at a time
    locks/snap-...-0007.lock        flock targets: readers (SH) and prune (EX)
    staging/<run-id>/               in-progress run; never visible as a snapshot
    trash/snap-...                  pruned or quarantined snapshots awaiting rmtree
```

- Snapshot names follow the `snaputil` pattern (`snaputil.py:11-12`) with the
  sequence zero-padded to 4 digits. Sequence = max valid `seq` + 1.
- `list_snapshots` ignores `.backupctl/` (it does not start with `snap-`).
- Configured directory names must be unique basenames; they become the first
  path segment in the snapshot.
- Everything lives on one filesystem, so `rename` is atomic.

### MANIFEST.json

```
{
  "format": 1,
  "seq": 7,
  "scan_start_ns": 1789000000000000000,
  "created_utc": "...",
  "dirs": ["evals", "results", "..."],
  "files": [
    {"path": "evals/run-1/out.csv", "size": 1234,
     "mtime_ns": 1788999999123456789, "ino": 88412, "sha256": "...",
     "source_ino": 88412}
  ],
  "skipped": [{"path": "evals/run-2/x.bin", "reason": "vanished|unreadable|symlink|unstable"}],
  "manifest_sha256": "..."
}
```

`manifest_sha256` is the SHA-256 of the canonical JSON of every other key. It
detects a damaged manifest (section 6). `scan_start_ns` is used by the racy rule
(section 5).

---

## 4. Concurrency

| Actors | Mechanism | Guarantee |
|---|---|---|
| run vs run (scheduler + person) | `flock(LOCK_EX \| LOCK_NB)` on `.backupctl/run.lock` | A second run exits immediately with code 75 ("another run in progress"). It does not queue. Same behavior regardless of who started it. `--wait SECONDS` is optional and off by default. |
| run vs restore | Restore only takes a shared lock on `locks/<snap>.lock` and reads committed snapshots. A run only reads the baseline snapshot and never writes into a committed snapshot. | No interaction. |
| restore vs prune | Restore takes `LOCK_SH` on `locks/<snap>.lock` for the whole read. Prune takes `LOCK_EX \| LOCK_NB` on the same file before renaming. | If a restore holds the lock, prune skips that snapshot and reports it. The snapshot is pruned on a later run. |
| restore vs prune, race on path | Restore resolves "newest valid", then takes the lock. If the snapshot was renamed away in between, restore gets `ENOENT`, re-resolves, and retries (max 3). | Restore never reads a partially deleted tree. Fails with a clear error if all retries fail. |
| crash / kill during any step | `flock` is released by the kernel on process exit. Staging and trash are discarded at next startup (section 6). | No manual cleanup. |

Scope limit: `flock` semantics are assumed for a local APFS/ext4 filesystem.
On NFS or SMB, advisory locks may not hold, so the backup root must be local
(stated as a requirement, not verified here).

---

## 5. Run protocol and change detection

### Publish sequence (run holds `run.lock`)

1. Startup recovery (section 6).
2. Load baseline = newest valid snapshot's `MANIFEST.json` (may be absent).
3. `scan_start_ns = time.time_ns()` recorded in memory.
4. Walk each configured directory (override of `scan_files`, section 2).
   For each entry, `lstat`:
   - symlink -> skipped, reason `symlink`;
   - regular file -> state `(size, mtime_ns, ino)`.
5. For each file, decide **reuse** or **copy**:
   - **reuse** (hardlink from the baseline snapshot) if the path exists in the
     baseline with an identical state **and** the racy rule does not apply;
   - **copy** otherwise (also when reuse fails, e.g. `EXDEV` or `EPERM` on a
     filesystem without hardlinks: fall back to copy).
6. Copy = streaming read in 1 MiB chunks, SHA-256 computed on the fly, written
   to `<name>.part`, fsync, `rename` to final name in staging. Stat taken
   before and after the read; if they differ, the file was modified during
   copy: retry once, then skip with reason `unstable`.
7. Build the manifest from **what was actually written or linked** (not from the
   step 4 listing). The `files` list contains only entries that exist in staging.
   Entries that failed are in `skipped`.
8. Write `MANIFEST.json.tmp`, fsync, rename to `MANIFEST.json`, fsync dir.
9. `chmod -R a-w` on the staging tree (guards against accidental writes; not
   a security boundary, because root can still write).
10. `rename(staging/<run-id>, snap-<name>)`, then fsync `backup_root`.
11. Retention (section 8) runs only after step 10 succeeds.

Crash windows:
- before step 10: the run leaves only `staging/<run-id>`. No `snap-*` exists.
- between steps 10 and 11: a complete snapshot exists; prune is simply deferred
  to the next run.

Any `OSError` on a destination write or on a manifest write (e.g. ENOSPC)
aborts the run (the run removes its own staging directory, exit 1). It is never
downgraded to a skip.

### Change-detection granularity: per file, on `(size, mtime_ns, ino)`

Decided per file path. A directory is never compared as a unit. Directories
are re-created from the file list.

**Racy rule.** A baseline entry is reusable only if
`mtime_ns < baseline.scan_start_ns - 2 s`. The 2 s margin covers coarse
timestamp granularity (HFS+ has 1 s). An entry modified within that window of
its own snapshot's scan can be modified again without changing `(size, mtime_ns)`,
so it is always re-copied. Cost: a file touched in the last 2 s before a run is copied again.
Without this rule a same-size edit in the same timestamp tick would be silently
missed.

**What the granularity misses** (stated, not mitigated by default):
1. Edits that keep size **and** mtime: `touch -r`, `rsync -t`, `tar x` restoring mtimes,
   or a tool that resets mtime. The content changes, the state does not, and the
   file is reused.
2. Edits inside the racy window that the rule cannot cover if the clock jumps
   backward between runs.
3. Inode reuse: a deleted file's inode reused by a new file with the same size and
   mtime at the same path. Requires a deliberate coincidence.
4. Metadata-only changes (permissions, xattrs) are not captured by reuse. Stated
   and not handled; restore does not promise to restore metadata.

`--verify` (opt-in) re-hashes every reused file against the baseline's `sha256`
and copies on mismatch. It removes misses 1 and 3 at the cost of reading all
data (~5.7 s per 1 GB of hashing on the measurement host, section 7; plus I/O).
It does not cover case 4.

---

## 6. Failure handling

### Vanished or unreadable source files

Applies to scheduler and person runs identically (no TTY or interactive prompt
in the code path).

| Event | Where detected | Result in snapshot | Reported |
|---|---|---|---|
| Deleted between walk and `lstat` | `lstat` -> `ENOENT` | not in `files`, in `skipped` (`vanished`) | yes |
| Deleted between `lstat` and `open` | `open` -> `ENOENT` | not in `files`, `skipped` (`vanished`) | yes |
| `open`/`read` -> `EACCES`/`EIO` | copy step | no partial file left (`.part` removed), `skipped` (`unreadable`) | yes |
| Modified during copy | stat before/after | retried once, else `skipped` (`unstable`) | yes |
| Symlink | `lstat` | not followed, `skipped` (`symlink`) | yes |
| Directory vanished mid-walk | `os.scandir` -> `ENOENT` | subtree skipped, one `skipped` entry per directory | yes |

Snapshot content invariant: **every entry in `files` exists in the snapshot with the
recorded size and sha256; every source file not in `files` is in `skipped` with a reason.**
Nothing is silently dropped.

Run report: stdout summary and the same `skipped` list in `MANIFEST.json`. Exit
codes: `0` all files captured; `3` snapshot published with skipped entries;
`1` no snapshot published (hard failure); `75` another run holds the lock.

### Startup recovery (under `run.lock`, before any new work)

Because the lock is held, no other run is live, so everything below is dead
work from an interrupted run or damage.

1. Delete everything under `.backupctl/staging/` (interrupted runs). Reported as
   `discarded staging <run-id>`.
2. Delete everything under `.backupctl/trash/` (interrupted prunes/quarantines).
3. For each `snap-*` directory (via `list_snapshots`, `snaputil.py:8-20`),
   validate:
   - `MANIFEST.json` exists and parses;
   - `manifest_sha256` matches;
   - every `files` entry exists with the recorded size (stat only; full
     verification is `--verify`).
   If any check fails: move the directory to `trash/`, report
   `quarantined snap-X: <reason>`, and continue.
4. Baseline = valid snapshot with the highest `seq`. If the newest snapshot
   was quarantined, the next older valid one is the baseline (reported).
   If none, the run is a full backup (no reuse).

**Corrupt or half-written index.** The committed `MANIFEST.json` is the index.
It is written to a `.tmp` file, fsync'd, renamed, and only then is the directory
renamed into `snap-*`, so a `snap-*` directory with a truncated index cannot be
produced by a run. The validation in step 3 covers damage after the fact (disk
fault, external edit). Such a snapshot is quarantined, not repaired: the design
does not try to re-derive a manifest from a damaged tree, because that would
claim files the snapshot may not contain. The next run re-derives the state from
the source tree (full copy of changed files, no reuse from the quarantined one).

---

## 7. Performance budget: initial full backup of ~1 GB / ~30,000 files

Measured on this host (macOS, APFS, Python 3, warm page cache — the test files
were just written). Test tree: 30,000 files x 34 KiB = 1.0 GiB, in 300 subdirectories.

| Component | Measurement | Source |
|---|---|---|
| Walk + `stat` manifest | 0.70 s | `synccli.build_manifest` on the tree |
| Existing `sync()` cold copy | 12.9 s | `synccli.sync` into an empty destination (includes manifest write; not the design's copy path) |
| Existing `sync()` no-change rerun | 0.81 s, 0 copied | `synccli.sync` second run |
| Per-file `fsync` + rename copy (no hashing) | 18.0 s | prototype loop, same logic as step 6 without SHA-256 |
| SHA-256, streaming 1 MiB chunks, 1 GB | 5.7 s | `hashlib.sha256` over the same tree |
| `os.link` for 30,000 files | 10.98 s | used for reuse (step 5) |
| Manifest JSON, 30,000 entries | 2.35 MB on disk | `sync()` output |

**Derivation (initial full backup, no reuse):**
walk 0.70 s + copy-with-fsync 18.0 s + hashing 5.7 s (worst case, not
overlapped with I/O) + manifest write (not measured; estimated < 0.1 s for
2.35 MB) ≈ **24.5 s**.

**Budget: 60 s** on this host class, warm cache, for ~1 GB / 30,000 files.
Headroom ≈ 2.5x over the derivation, reserved for cold-cache reads and disk
variance.

**Status: provisional.** The derivation uses warm-cache measurements taken
on the development host. Cold-cache and target-disk throughput were not
measured, and the streaming copy in step 6 was not implemented or timed as
written. Acceptance requires a timing of the implemented copy path on a cold
cache and on the target disk. If that exceeds 60 s, the budget is revised to
the measured value (no silent change).

**Incremental budget (no changes):** walk 0.70 s + 30,000 `os.link` 10.98 s ≈
11.7 s on this host. Linking dominates, so the design keeps hardlinks (a
pointer scheme would make pruning harder, section 8). This figure is measured
at 30,000 files and is not extrapolated.

---

## 8. Retention and deletion

**Policy:** keep the newest `K` **valid** snapshots (`--keep K`, default 14,
minimum 1). Invalid or quarantined snapshots do not count toward `K`
(override of `snaputil.py:30-33`, which counts them).

Deletion, executed only after a successful publish (step 11):

1. For each candidate (valid, older than the newest `K`, oldest first):
2. `flock(locks/<name>.lock, LOCK_EX | LOCK_NB)`. If it fails (a reader is
   active), skip the candidate and report it. Retried next run.
3. `rename(snap-<name>, .backupctl/trash/snap-<name>)`. Atomic: readers either
   see the snapshot or they do not, and readers already inside hold the shared
   lock (which step 2 made impossible).
4. `rmtree` the trash entry. Interrupted `rmtree` is cleaned by startup step 2.

The newest valid snapshot is never a candidate (`K >= 1`), so the user always
keeps at least one usable snapshot. Pruning runs after publish, so the new
snapshot exists before anything older is deleted.

Hardlinks: deleting a snapshot removes names only. File data is freed when the
last name is removed. Pruning never invalidates a newer snapshot.

---

## 9. Verified facts (probes run in this directory)

9.1 **Ghost manifest entry** (`sync()`): with `build_manifest` patched to list a
file that is then not copied, run 1 leaves `ghost.txt` in the manifest and absent
from the destination; run 2 reports `copies: []`. The file is never retried.
This is the bug the design overrides (section 2, `sync`).

9.2 **Corrupt manifest**: a truncated `.sync_manifest.json` in the destination
makes `sync()` raise `JSONDecodeError`. No recovery path exists.

9.3 **Lexical snapshot order**: `list_snapshots` on
`snap-...-07, snap-...-10, snap-...-9` returns `-07, -10, -9`. Fixed-width
sequences are required.

9.4 **Escape in `safe_snapshot_path`**: `'../../etc/passwd'` is returned as
`'/bk/snap-x/../../etc/passwd'`; `'/etc/passwd'` is returned as `'/etc/passwd'`.

9.5 **`is_stale` boundary**: equal mtime returns `True`, contradicting its
docstring (`snaputil.py:71`).

9.6 **Vanished file in `build_manifest`**: `build_manifest` has no error handling
around `os.stat`, so a file removed after listing raises and aborts the run (by
reading `synccli.py:31-32`; the probe removed the file before `copy_file`, not
within `build_manifest`, so this one is by inspection).

Test status: `python3 -m unittest` in this directory: 6 tests, OK.

---

## 10. Test plan (for implementation)

New tests, one per override or design claim:

- dot-directories are included (override of `synccli.py:14`);
- symlinks are recorded as skipped, not followed;
- a file deleted after listing is `skipped: vanished`, run exits 3, snapshot published;
- an unreadable file leaves no `.part`, is `skipped: unreadable`;
- write-side ENOSPC aborts the run and leaves no `snap-*`;
- a killed run (SIGKILL between copy and publish) leaves no `snap-*`, and the next
  run removes its staging;
- a truncated `MANIFEST.json` in the newest snapshot is quarantined and the
  previous snapshot becomes the baseline;
- a second concurrent run exits 75;
- a reader holding the shared lock prevents pruning of its snapshot;
- `keep=1` with an invalid newer snapshot deletes nothing valid;
- `safe_snapshot_path` rejects `..` and absolute paths (after override);
- racy-window entries are re-copied;
- `--verify` detects a same-size, same-mtime edit.

---

## 11. Scaling bounds

Let `N` = configured directories, `F` = total files across them, `B` = total
bytes, `C` = bytes changed since the baseline, `K` = retained snapshots.

| Quantity | Bound | Basis |
|---|---|---|
| Per-run `lstat` work | `F` calls | Measured: 0.70 s / 30,000 files (23 µs per file). |
| Per-run reuse work | `F` hardlinks at ≤ 11.0 s / 30,000 (~366 µs per file) | Measured (section 7). |
| Per-run copy work (read + hash + write) | `C` bytes, with fsync per file | Measured: 18.0 s / 1 GB full copy with fsync; hashing 5.7 s / GB. |
| Per-run RAM for the copy path | 1 MiB chunk + `O(F)` manifest entries | Streaming copy (no whole-file reads, unlike `copy_file` line 67). The manifest is `O(F)`. Per-entry in-memory cost is not measured. |
| Manifest on disk per snapshot | ~78 bytes x `F` | Measured: 2.35 MB / 30,000 entries. |
| Total disk, retained snapshots | `≤ B + Σ C_i + K · 78 · F` bytes | Unique content (hardlinks counted once) plus `K` manifests. |
| Work per run vs `N` | `O(F)`, no per-`N` term beyond one walk per configured directory | Walks are independent. |
| Memory vs `N` | `O(F)`, not `O(N)` | Only the file list is in memory. |
| Lock files | `1 + K` (one `run.lock`, one per snapshot) | Constant per snapshot. |
| Startup validation | `O(K · F)` stat calls | Stat-only; full hash only with `--verify`. |

Flat, with the stated bound: the lock count (constant), the chunk size (1 MiB),
the per-run staging (one directory per run, removed at startup if orphaned).

Growing with `F` (not `N`): time, manifest size, memory. Growing with `C`:
copy time and disk. Growing with `K`: disk (manifests and retained data), and
startup validation time.

---

## 12. Open items (not decided here)

- Restore tooling is separate. Its contract is defined here: shared lock on
  `locks/<snap>.lock`, read `MANIFEST.json` first, verify `files` sizes, retry
  on `ENOENT`. Its own design is out of scope.
- Retention beyond count (e.g. daily/weekly tiers) is not designed. The
  count policy above is the only one.
- Cold-cache and target-disk timing (section 7) is required before the 60 s
  budget is accepted.
- `--wait` for run contention is optional and unspecified beyond the flag.
- Metadata (permissions, xattrs, ACLs) is not captured (section 5, miss 4).

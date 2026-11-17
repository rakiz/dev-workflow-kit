# DESIGN — `backupctl` (fixture D1)

Status: proposal. Author worked alone; every claim about existing code was
checked by running it, and every number is measured (Appendix A) or derived
from a measurement.

## 0. Decisions in one screen

| Question | Decision |
|---|---|
| Storage model | **Content-addressed object store** (`objects/<aa>/<sha256>`) plus one immutable **tree object** per configured directory per change, plus a tiny per-snapshot `INDEX.json`. A hardlink-farm design was measured and rejected (§14). |
| Snapshot visibility | A snapshot exists **only** as `snap-YYYYMMDD-HHMMSS-NN/` directly under the backup root. It is built in `.backupctl/staging/<run-id>/` and appears with one atomic `rename(2)` after everything it references is durable. Published snapshots are never modified. |
| Concurrent runs | Serialized by one `flock` writer lock (`.backupctl/writer.lock`); the kernel releases it when the holder dies, so a dead run never needs manual unlock. |
| Readers vs deletion | Per-snapshot `flock` reader locks (`LOCK_SH`); deletion needs `LOCK_EX \| LOCK_NB` and is *deferred* (not forced) when a reader is present. |
| Crash recovery | A dead run leaves only `staging/<run-id>/` and at most one temp file in `objects/tmp/`. The next run salvages the dead run's per-file journal (torn tail discarded, salvaged objects re-hashed) and continues from there. |
| Change detection | Per **file**, on `lstat` fields `(size, mtime_ns, ctime_ns, ino, mode)`, with a git-style "racy" rule for files modified within 2 s of the scan. Unchanged ⇒ zero bytes read or written. |
| Vanished / unreadable source files | Vanished ⇒ absent from the snapshot, listed under `vanished`, run status unaffected. Unreadable / unstable ⇒ absent, listed under `skipped` with the errno, snapshot status `partial`, exit code 2. Identical for scheduler and human. |
| Retention | keep_last 10 + daily 14 + weekly 8, plus hard invariants (newest valid, newest complete, newest good copy of every directory are never deleted). |
| First-full budget | **≤ 30 s for 1 GiB / 25,000 files** on the reference machine (measured 15.9–17.4 s, 4 runs). General form: `T_full ≈ 1.42 × (F × 0.40 ms + B / 600 MiB/s)`. |

## 1. Grounding: what exists, what it really does, and how `backupctl` uses it

All behaviors below were reproduced with `python3` 3.10.11 in this directory;
`python3 -m unittest` passes (6 tests) before and must pass after the changes in §12.

### 1.1 `synccli.py`

| Function (lines) | Verified behavior | Use in `backupctl` |
|---|---|---|
| `scan_files` (10–19) | `os.walk` from `root`, prunes dirs starting with `.` (line 14), returns sorted relative paths of everything in `filenames`. Verified: (a) `os.walk` has no `onerror`, so an **unreadable subdirectory is silently dropped** (`['ok/f']` returned for a tree with a mode-000 dir); (b) a **missing root returns `[]`**; (c) a **symlink to a directory is dropped** (it sits in `dirnames`, is not descended, is never emitted); (d) hidden *files* are kept, hidden *dirs* are not. | **Reused as the scanner**, extended with three keyword args whose defaults keep today's behavior (§12): `skip_hidden_dirs=True`, `onerror=None`, `emit_dir_symlinks=False`. `backupctl` calls it with `skip_hidden_dirs=False` (eval outputs contain e.g. `.hydra/`), an `onerror` that records the directory as skipped, and `emit_dir_symlinks=True`. A missing/unreadable *root* is checked before calling it (§7.3), because (b) would otherwise look like "every file was deleted". |
| `file_state` (22–25) | `os.stat` → `{"size", "mtime"}`, `mtime` as float seconds. Follows symlinks; raises `FileNotFoundError` on a dangling link or a file that vanished. | **Overridden** by `backupctl.entry_state(path)`: `os.lstat` (symlinks are stored as links, not followed), integer `st_mtime_ns` (float loses sub-µs precision), plus `ctime_ns`, `ino`, `mode`. Reasons: §4 granularity, and crash-free vanish handling. |
| `build_manifest` (28–33) | Loop `scan_files` → `file_state`. One vanished file or dangling symlink aborts the whole call (verified: `FileNotFoundError` on a dangling symlink). | **Overridden** by `backupctl.build_tree_state(root)`: same loop shape over `scan_files`, but `FileNotFoundError` per file ⇒ `vanished`, other `OSError` ⇒ `skipped`; the scan never aborts on one file. |
| `changed_files` (36–42) | Returns paths in `new` that are absent from `old` or whose state dict differs (`!=`). Does not report deletions. Works on any dict-valued state. | **Reused unchanged** for change detection: `changed_files(base_states, new_states)`, where both dicts hold `entry_state` dicts *without* the hash, and racy base entries are dropped from `base_states` first so they come back as "changed" (§4). |
| `collect_stale` (45–59) | Paths whose `fresh` flag is false and not in `seen`. Docstring says "iterable" but it calls `len()`/indexing (verified: `TypeError` on an iterator). | **Reused** to compute "deleted since base" for the report: `collect_stale([(rel, rel in new_states) for rel in base_states])` — always passed a list. |
| `copy_file` (62–69) | Reads the **whole file into memory** (line 67), opens the destination with `"wb"` (truncate in place), and **swallows every `OSError`** (lines 68–69). The comment "next pass will retry" is false: `sync()` still writes the scan-time state into the manifest, so the next pass sees "unchanged" and never retries (verified: mode-000 file ⇒ run 1 copies nothing but records it; after `chmod 644`, run 2 copies `[]` and the file is still missing). | **Overridden** by `backupctl.store_object(src)` (§3.3): 1 MiB chunks (memory bounded by the buffer, not the file), write to a private temp file, `fsync`, `rename` into the store, errors surfaced per file. Truncating in place is exactly what must never happen to backup data. |
| `sync` (72–87) | Skeleton: scan → load old manifest → `changed_files` → copy → write manifest. Manifest load (77–79) has no error handling (verified: half-written JSON ⇒ `JSONDecodeError` on every later run until a human deletes it). Manifest write (85–86) truncates then dumps — not atomic. Records the source state from scan time, including files whose copy failed. Never propagates deletions. | `backupctl run` keeps the **same skeleton** (scan → base → `changed_files` → copy → write index). It **overrides** three steps: base loading (checksum-verified, falls back, §6.2), index writing (temp + fsync + rename, then directory publish), and what the index records (the state observed by *this* copy, only for files actually stored). |
| `main` (90–99), `--dry-run` | `--dry-run` returns `changed_files` without writing. | `backupctl run --dry-run` mirrors it: prints what would be read/hashed, writes nothing. |

### 1.2 `snaputil.py`

| Function (lines) | Verified behavior | Use in `backupctl` |
|---|---|---|
| `list_snapshots` (8–20) | `snap-*` directories under the root, **lexicographically** sorted. With a 3-digit sequence it misorders (verified: `…-07, …-100, …-99`). `entry.is_dir()` follows symlinks. | **Reused** as the single enumeration of published snapshots. Correct ordering is guaranteed by construction: names use UTC, fixed width, `NN` capped at two digits and assigned under the writer lock, and timestamps are forced monotonic (§2.2). Staging/trash/quarantine never start with `snap-` and live under `.backupctl/`, so `list_snapshots` cannot see an incomplete snapshot. |
| `prune_snapshots` (23–36) | Deletes all but newest `keep` with `shutil.rmtree` in place. Docstring says the newest is never deleted; **false for `keep <= 0`** (verified: `keep=0` deleted all three). Counts any `snap-*` regardless of validity. `rmtree` under a running restore removes files mid-walk. | **Not called** by `backupctl`; overridden by `backupctl.retention.prune()` (§8): policy-based selection with invariants, reader-lock check, rename-to-trash, then delete. Separately fix `keep < 1` to raise `ValueError` (§12). |
| `snapshot_disk_usage` (39–51) | Sums `os.stat` sizes of files in a snapshot dir. Follows symlinks; raises if a file vanishes mid-walk. | **Overridden** for `backupctl list`: in this layout a snapshot dir holds only metadata, so the logical size is `INDEX.json`'s per-dir `bytes`, and exclusive bytes come from the GC mark pass (§8.4). `snaputil.main` remains valid for the metadata-only size. |
| `safe_snapshot_path` (54–63) | Claims the result never leaves the snapshot. **False**: `normpath` keeps leading `..` and `os.path.join` discards the prefix for absolute paths (verified: `"../../etc/passwd"` ⇒ `/b/snap-x/../../etc/passwd`; `"/etc/passwd"` ⇒ `/etc/passwd`). | **Fixed in place** (§12) to reject absolute paths and any path whose normalized form starts with `..` (`ValueError`), and then **used** by restore to map index paths under the restore target (same role: stored relative path → filesystem path under a root). Every `rel` read from a tree object goes through it. |
| `is_stale` (66–73) | Docstring: equal mtime is *not* stale; code uses `<=` ⇒ it *is* (verified `True`). Uses directory mtime, which changes when entries are added/removed, not when a snapshot was taken. | **Not used.** Snapshot age comes from the name and `INDEX.json:created_utc`. Docstring/code mismatch to be fixed (§12). |

## 2. On-disk layout

```
<backup_root>/                         # must be a local filesystem (flock, rename atomicity)
  snap-20261113-150000-00/             # published, immutable, mode 0555
    INDEX.json                         # written last before publish; checksum inside
    trees/<label>                      # one line: "<tree-sha256> <files> <bytes>\n" per directory
    REPORT.json                        # what happened in the run that produced it
  objects/
    00/ … ff/<sha256>                  # file contents and tree objects, mode 0444, never rewritten
    tmp/                               # in-flight writes only
  .backupctl/
    writer.lock                        # flock(LOCK_EX) by runs and prune
    locks/<snap-name>.lock             # flock(LOCK_SH) by readers, LOCK_EX by deletion
    staging/<run-id>/                  # one per run; journal.jsonl + snapshot/ being assembled
    trash/                             # renamed-away snapshots awaiting rmtree
    quarantine/                        # snapshots whose INDEX failed verification (§6.2)
    runs/<run-id>.json                 # report of every run, including failed ones
```

### 2.1 Formats

- **Tree object** (one per configured directory, stored *as an object*, gzip JSON):
  `{"format": 1, "label": "...", "entries": {rel: {"kind": "file"|"symlink", "size", "mtime_ns", "ctime_ns", "ino", "mode", "sha256" | "target", "racy": bool}}}`.
  An unchanged directory produces a byte-identical tree ⇒ same hash ⇒ nothing new on disk.
  Measured size: 5.2 MB raw, **1.6 MB gzip for 25,000 entries (64 B/entry)**.
- **`INDEX.json`**: `{"format": 1, "name", "created_utc", "run_id", "trigger", "status": "complete"|"partial", "dirs": {label: {"source", "tree", "files", "bytes"} | {"error": "..."}}, "skipped": {label: {rel: errno-name}}, "vanished_count", "checksum"}` where `checksum` = sha256 of the canonical JSON (sorted keys, `ensure_ascii=True` so non-UTF-8 file names round-trip) of everything else.
- **`trees/<label>`**: redundancy for recovery (§6.2); written and fsynced before `INDEX.json`.
- **`journal.jsonl`**: one line per stored file `{"label", "rel", "state", "sha256"}`, appended *after* the object is renamed into the store.

### 2.2 Snapshot names

`snap-YYYYMMDD-HHMMSS-NN`, UTC (no DST folds), `NN` = smallest `00..99` not used by any existing name in the root, trash or quarantine for that second, chosen under the writer lock. The timestamp is `max(now, newest existing name + 1 s)` so a clock step backwards cannot make a new snapshot sort before an older one in `list_snapshots`; the true wall time is in `INDEX.json:created_utc`. This keeps `snaputil.list_snapshots`'s lexicographic sort correct.

## 3. `backupctl run`

### 3.1 Configuration

`backupctl.json` (JSON because the repo targets Python 3.10, which lacks `tomllib`):
`{"backup_root": "...", "dirs": [{"label": "evals-a", "path": "evals/a", "exclude": ["*.tmp"]}], "retention": {"keep_last": 10, "keep_daily": 14, "keep_weekly": 8}, "lock_wait_s": 1800}`.
Validation rejects: duplicate labels; `keep_last < 1`; a `backup_root` inside any source dir or a source dir inside the backup root (`os.path.commonpath` on `realpath`s), which would back up the backups.

### 3.2 Steps (same skeleton as `synccli.sync`, overridden steps marked ✱)

1. **Lock.** `flock(writer.lock, LOCK_EX)` with polling up to `lock_wait_s`; on timeout exit 75 (`EX_TEMPFAIL`), nothing written. Create `staging/<run-id>/` (`run-id` = UTC time + pid + 32 random bits).
2. **Recover** (§6): delete `objects/tmp/*`, finish `rmtree` of `trash/*`, salvage every other `staging/*` journal into a *salvage map* `{(label, rel): (state, sha256)}`.
3. **Base** ✱: newest snapshot in `list_snapshots(root)` whose `INDEX.json` checksum verifies; take a reader lock on it. For each label, load its tree object as the base (fallback rules in §6.2). A label with no base is a first full backup.
4. **Per directory, sequentially** (memory is per-directory, §11):
   1. Root check: `lstat(path)` must be a readable directory, else the label gets `{"error": ...}` (§7.3) and no tree.
   2. `scan_files(path, skip_hidden_dirs=False, onerror=..., emit_dir_symlinks=True)`, minus `exclude` globs.
   3. `build_tree_state` ✱: `entry_state` per path (vanished/skipped handled per file).
   4. `changed = changed_files(base_states_without_racy, new_states)` — reused as is.
   5. For each unchanged path: reuse the base `sha256` **only if** `objects/<aa>/<sha>` still exists (one `stat`, ~6 µs) — so the new tree can never reference a missing object. Otherwise treat as changed.
   6. For each changed path: if the salvage map has the same `(label, rel)` with an equal state, reuse its (re-verified) hash; else `store_object` (§3.3). Symlinks store `os.readlink` as `target`. Non-regular, non-symlink types (FIFO, socket, device) ⇒ `skipped: "unsupported-type"`.
   7. Write the tree object with `store_object` semantics, write `staging/<run-id>/snapshot/trees/<label>`.
5. **Index** ✱: write `INDEX.json` to a temp name in the staging snapshot dir, `fsync`, `rename`; write `REPORT.json`.
6. **Barrier**: `fsync` every new directory entry's parent (the 256 fan-out dirs that received objects, the staging snapshot dir). On macOS, one `fcntl(F_FULLFSYNC)` (measured 0.51 ms) because `fsync` there does not flush the drive cache.
7. **Publish**: `chmod 0555` the staging snapshot dir, `rename(staging/<run-id>/snapshot, <root>/snap-…)`, `fsync(<root>)`, create `.backupctl/locks/<snap>.lock`. From this instant the snapshot is complete and visible; before it, nothing named `snap-*` exists.
8. **Cleanup**: remove `staging/<run-id>/` and every *salvaged* dead staging dir (their objects are now referenced or orphaned).
9. **Prune + GC** (§8), still under the writer lock.
10. Write `.backupctl/runs/<run-id>.json`, print the summary, exit (codes in §7.4). Release locks (also released by the kernel on any death).

### 3.3 `store_object(src)` — the replacement for `synccli.copy_file`

```
fd   = open(src, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)   # O_NONBLOCK: a FIFO swapped in after lstat can't hang us
pre  = fstat(fd); require S_ISREG(pre)                  # else skipped: unsupported-type
tmp  = open(objects/tmp/<run-id>-<rand>, O_WRONLY|O_CREAT|O_EXCL, 0o444)
loop: read 1 MiB → sha256.update → write                # memory: one 1 MiB buffer
fsync(tmp); close(tmp)
post = fstat(fd)
if (pre.size, pre.mtime_ns) != (post.size, post.mtime_ns): retry ≤ 2 more times, then skipped: "unstable"
if post.st_nlink == 0: vanished                         # unlinked while we read it
rename(tmp, objects/<aa>/<sha256>)  — or unlink(tmp) if that object already exists (dedup)
append journal line {label, rel, state(post), sha256}; flush (fsync every 256 lines)
```

The state recorded is the one observed *around this copy* (`post`), not the earlier scan state, so the index describes what was actually stored — the opposite of `synccli.sync` line 86, which records scan-time state even for failed copies.

## 4. Change detection: granularity and blind spots

**Granularity: one file.** Key = `lstat` `(size, mtime_ns, ctime_ns, ino, mode)` compared with `synccli.changed_files` against the base tree. Versus `synccli.file_state`'s `(size, float mtime)`:
- `ctime_ns` cannot be set by user space, so tools that restore mtime (`touch -r`, `rsync -t`, `cp -p`, `tar x`) still trigger a re-read.
- `ino` catches atomic-save-by-rename of a same-size file with a preserved mtime.
- A chmod or link-count change also changes `ctime` ⇒ re-read + re-hash, but **no write** (object exists). False positives cost reads, never correctness.

**Racy rule.** Entries with `mtime_ns ≥ scan_start_ns − 2 s` are stored with `"racy": true` and are excluded from `base_states` next run, so they are re-hashed once more. This closes the "edited again in the same timestamp tick, after we read it" hole on coarse-timestamp filesystems (HFS+ 1 s, FAT 2 s).

**What this granularity can still miss** (content changes with all five fields identical):
1. Writes through `mmap` whose mtime update is deferred by the kernel until a later fault/`msync`.
2. Edits made while the system clock is set backwards to exactly reproduce `mtime` and `ctime` (requires root and deliberate effort).
3. Filesystems that do not provide stable `ctime`/`ino` (some FUSE / network / exFAT setups): there the key degrades to size + mtime, so a same-size edit with a restored mtime is missed. Over-reporting (unstable `ino`) only costs re-reads.
4. Silent corruption (bit rot) in the source or the store is not detected by stat comparison; `backupctl verify --deep` re-hashes the store.

Moving the granularity to content (re-hash every file every run) would close 1–3 at a cost of reading all bytes each run (1 GiB ≈ 1.5–2 s at the measured bandwidth, ×N directories); offered as `run --rehash`, not the default.

## 5. Concurrency

Invariant: **published snapshots and objects are immutable**; the only mutations of shared state are (a) creating new objects (temp + rename, content-named, so two writers of the same object produce identical bytes), (b) publishing a new `snap-*` (rename of a private dir), (c) deleting snapshots/objects (prune/GC only).

| Pair | Mechanism | Result |
|---|---|---|
| run × run (scheduler + human) | `writer.lock` `LOCK_EX`; the second waits ≤ `lock_wait_s`, then exits 75 having written nothing. | Strictly serialized. A dead holder releases the lock automatically (no pid files). |
| run × restore / any reader | The run writes only under `staging/` and `objects/` (new names). | Reader is unaffected; it cannot see the new snapshot until step 7, and then sees it whole. |
| prune/GC × restore | Reader: `open(locks/<snap>.lock)`, `flock(LOCK_SH)`, **then** check `<root>/<snap>` exists (else `SnapshotGone`). Deleter: `flock(LOCK_EX \| LOCK_NB)`; on `EWOULDBLOCK` the snapshot is **deferred** to a later prune and reported; on success it is renamed into `trash/` before unlocking. GC marks every object referenced by any snapshot still under `snap-*` or `quarantine/`. | A locked reader's snapshot and all its objects survive until it unlocks. A reader arriving after the rename finds the name gone and fails cleanly. |
| prune/GC × run | Both require `writer.lock`. | Never concurrent; the base snapshot of a run cannot be deleted under it. |
| restore × restore | Shared locks. | Independent. |
| non-locking reader (human `cp -r`, `ls`) × prune | Not protected by locks. Mitigations: a snapshot is only deleted after it falls out of retention (days old), and it is renamed (not deleted) first; a path-based walker started earlier will get `ENOENT` and **fail loudly** — it can never mistake a partial read for a complete one if it uses `backupctl restore` (which treats any missing object as an error). | Documented limitation; the supported path for humans is `backupctl show/restore`. |

Lock files under `locks/` are created by the writer at publish time, so readers only need read permission (`flock` works on an `O_RDONLY` fd). Lock files of deleted snapshots are swept by GC; the reader's "check existence after locking" makes the classic unlink-the-lock-file race harmless because names are never reused (§2.2).

Requirement: `backup_root` on a local filesystem. `flock` semantics over NFS/SMB are not relied upon; `backupctl` refuses to run if the mount table (`/proc/mounts` on Linux, `mount` output on macOS) reports a network filesystem type for the backup root, unless `--i-know-locks-are-unsafe`.

## 6. Interruption and recovery

### 6.1 What a dead run can leave, and why none of it looks like a snapshot

A run killed at any instant (SIGKILL, Ctrl-C, power loss, sleep that never wakes) can leave only:
- `staging/<run-id>/` — never named `snap-*`, never listed by `list_snapshots`;
- one temp file in `objects/tmp/` (the file in flight);
- complete, content-named objects in `objects/` not yet referenced by any snapshot (orphans);
- a partially emptied directory in `trash/` (if it died during prune).

Before step 7 nothing is visible; step 7 is a single `rename`; after it the snapshot is complete. Ctrl-C is not special-cased: `KeyboardInterrupt` propagates, exit 130, and the leftover state is exactly the SIGKILL state — one recovery path, exercised constantly.

### 6.2 Recovery performed by the next run (step 2), and what it reports

**A. Dead staging directory (the normal case).**
- *Discarded:* any `INDEX.json`, `REPORT.json`, `trees/*` inside it, complete or half-written — they are never read, only regenerated. Everything in `objects/tmp/`.
- *Re-derived:* `journal.jsonl` is parsed line by line; the first unparseable line and everything after it (a torn tail) is discarded. For each surviving line, the object must exist with `size == state.size`, and it is **re-hashed** (cost = salvaged bytes at ~1.6 GiB/s; 0.6 s per GiB) because on power loss `fsync` ordering is not guaranteed on every platform. Matches enter the salvage map; mismatched objects are deleted.
- *Progress:* a first full backup killed at 80 % restarts with 80 % of its objects reused (salvage re-hash ≈ 0.5 s/GiB instead of a ~16 s/GiB copy); repeated kills still converge.
- *Report:* `recovered: [{run_id, journal_lines_ok, torn_lines_discarded, objects_salvaged, bytes_salvaged, objects_rejected}]`. Not an error: exit code unaffected.
- GC treats journals still present in `staging/` as roots, so a standalone `backupctl prune` can never destroy salvageable progress.

**B. Published snapshot whose index is bad** — `INDEX.json` unparseable, checksum mismatch, or it references a tree object that is missing / fails to decompress / references missing objects. The protocol cannot produce this; it signals media error, a filesystem that broke rename/fsync ordering on power loss, or tampering.
- *Taken out of service:* the run tries `LOCK_EX | LOCK_NB` on the snapshot; on success it renames it to `.backupctl/quarantine/<name>` (invisible to `list_snapshots`); if a reader holds it, it is marked for quarantine next run (that reader's own checksum check already refuses it).
- *Discarded:* the bad `INDEX.json` (kept as `INDEX.corrupt` for inspection).
- *Re-derived from the tree:* for each `trees/<label>` pointer file, the tree object is decompressed, parsed, and every referenced object is checked to exist with the recorded size. Labels that pass are written into a new `INDEX.json` with `"rederived": true` and `status: "partial"` (the original `skipped` list is lost); labels that fail are recorded as `{"error": "unrecoverable"}`. If at least one label passed, the snapshot is renamed back to its original `snap-*` name (it now promises only what it holds); otherwise it stays in quarantine.
- *Base fallback:* the run uses the next older valid snapshot as its base. If none exists, every file is re-read and re-hashed, but objects already in the store are **not rewritten** (dedup), so losing every index costs one full read (~1.5–2 s/GiB), never a re-copy and never data loss.
- *Report:* `repaired: [{snapshot, problem, labels_recovered, labels_lost, action: quarantined|rederived}]`; exit code 2 (attention needed).

## 7. Source files that disappear or cannot be read

### 7.1 Semantics of a snapshot

Each file in a snapshot is a byte-exact copy of that file as it existed at one instant during the run, verified by identical `fstat` size/mtime before and after reading it. Different files are captured at different instants (no filesystem snapshot is taken); cross-file atomicity would require APFS/LVM/btrfs snapshots and is out of scope. A snapshot never contains a file from an earlier run that the source no longer has, nor an earlier version of a file whose current version could not be read: falling back to the previous version would produce exactly the "mix of runs" the brief forbids.

### 7.2 Per-file outcomes

| Event | Snapshot contains | Reported as | Status |
|---|---|---|---|
| Listed by `scan_files`, gone at `lstat` / `open` (`ENOENT`) | nothing for that path | `vanished` (count in INDEX, list in REPORT) | unaffected — the source genuinely no longer has it |
| Unlinked while being read (`st_nlink == 0` after copy) | nothing | `vanished` | unaffected |
| Unreadable (`EACCES`, `EPERM`, `EIO`, …) | nothing | `skipped: {rel: "EACCES"}`, plus the newest snapshot that does hold it | `partial` |
| Changed during read on 3 attempts | nothing | `skipped: "unstable"` | `partial` |
| FIFO / socket / device | nothing | `skipped: "unsupported-type"` | `partial` |
| Subdirectory unreadable (`scan_files` `onerror`) | nothing below it | `skipped: {dir/: "EACCES"}` | `partial` |
| Dangling symlink | the symlink itself (`kind: symlink`, `target`) | — | unaffected |

Empty directories are not recorded (inherited from `scan_files`, which only emits files); stated limitation.

### 7.3 Missing or unreadable configured root

Detected before scanning (because `scan_files` returns `[]` for a missing root). The label gets `{"error": "source root missing"}`; it gets **no tree** (an empty tree would read as "all files deleted"). Status `partial`. Retention invariant I3 (§8) keeps the newest snapshot that does hold that directory.

### 7.4 Exit codes and trigger independence

`0` published, complete · `2` published, partial or repaired (see REPORT) · `1` failed, nothing published (e.g. `ENOSPC`, unwritable root; staging kept for salvage) · `75` writer lock not obtained · `64` config/usage error · `130` interrupted.
The trigger (`--trigger scheduler|manual`) is recorded in INDEX/REPORT and has **no other effect**: same code path, same outcomes, same exit codes. TTY detection only toggles a progress line on stderr.

## 8. Retention and deletion

### 8.1 Policy

Candidates = `list_snapshots(root)` with a valid INDEX. Keep the union of: the newest `keep_last` (10); the newest snapshot of each of the last `keep_daily` (14) UTC days that have one; the newest of each of the last `keep_weekly` (8) ISO weeks.

### 8.2 Invariants (override the policy; violation is impossible, not merely unlikely)

- **I1** The newest valid snapshot is never deleted.
- **I2** The newest snapshot with `status: complete` is never deleted.
- **I3** For every configured label, the newest snapshot holding a valid tree for that label is never deleted.
- **I4** A snapshot with a reader lock is never deleted (deferred, §5).
- **I5** Prune runs only after this run published successfully, or via explicit `backupctl prune`; a failing run never deletes anything.
- **I6** `keep_last ≥ 1` is enforced at config load (contrast `snaputil.prune_snapshots(keep=0)`, which deletes everything).

Quarantined and invalid snapshots are never counted as "usable" for I1–I3.

Retained count bound: `S ≤ keep_last + keep_daily + keep_weekly + 2 + N = 34 + N`, plus snapshots transiently deferred by readers.

### 8.3 Deletion protocol

For each doomed snapshot: `LOCK_EX|LOCK_NB` → `rename` into `trash/` → unlock → `rmtree` (a few KB of metadata). A crash between steps leaves it in `trash/`, which the next run empties.

### 8.4 Garbage collection of objects

Mark: union of sha256s from every tree referenced by snapshots in `snap-*` and `quarantine/`, plus tree objects themselves, plus all `staging/*/journal.jsonl` hashes. Sweep: delete unmarked objects whose `ctime` precedes the GC start (belt-and-braces; under the writer lock no one else creates objects). Unique trees are loaded once. The same pass computes per-snapshot exclusive bytes for `backupctl list` (the replacement for `snapshot_disk_usage`). Interrupted GC leaves only unreferenced objects; it is idempotent.

## 9. Reader contract (restore tooling, humans, the next run)

`backupctl.open_snapshot(root, name)` (context manager) — the one supported way to read:
1. `flock(LOCK_SH)` on `locks/<name>.lock`; verify `<root>/<name>` still exists.
2. Load `INDEX.json`, verify checksum; on failure raise `SnapshotCorrupt` (never fall back to partial data).
3. Iterate entries from tree objects; map each `rel` with the fixed `snaputil.safe_snapshot_path` (escape ⇒ `ValueError`).
4. Every object open is checked; a missing object is an error, never a silently shorter restore.

`backupctl restore NAME [--dir LABEL] [--path REL] --to DIR` writes with temp + rename per file, sets `mode`/`mtime_ns`, recreates symlinks. `backupctl show NAME [LABEL[/REL]]` lists contents for humans. `backupctl verify [NAME] [--deep]` checks checksums / object existence / (deep) content hashes.

## 10. Performance budget: first full backup of ~1 GiB / ~25,000 files

### 10.1 Reference machine and data

Apple M3 Max (14 cores), 36 GB RAM, internal SSD, APFS, Python 3.10.11, corporate-managed macOS (endpoint-security hooks may inflate per-file costs). Data: 25,000 files, 1,073,729,257 bytes, log-normal sizes (max 8.5 MB) in 1,000 directories. Scripts in Appendix A; raw numbers in Appendix B.

### 10.2 Measurements

| Path | Time for 1 GiB / 25k files |
|---|---|
| Existing `synccli.sync` (whole-file read, in-place write, no fsync, no hash) | 8.29 / 8.40 / 9.14 s |
| Same copy with temp + rename (no fsync) | 11.69 / 15.19 s |
| Same with temp + `fsync` + rename | 12.08 / 14.78 s (fsync within noise) |
| **Prototype of `store_object` pipeline** (1 MiB chunks, sha256, `O_EXCL` 0444 temp, fsync, rename, gzip tree, `F_FULLFSYNC`) warm cache | **15.90 / 16.74 / 17.22 s** |
| Same, source reads with `F_NOCACHE` (cold-read proxy; `sudo purge` unavailable) | **16.59 / 17.40 s** |

Decomposition (separate runs of the same prototype): **25,000 × 1 KiB files: 9.82–10.23 s ⇒ c_file ≈ 0.40 ms/file**; **64 × 16 MiB: 1.42–1.98 s ⇒ bw ≈ 520–720 MiB/s**. sha256 alone: 1,676 MiB/s (≈0.6 s/GiB). `F_NOCACHE` changes the result by < 1 s, so on SSD the budget is metadata-bound, not read-bound.

### 10.3 Budget

**Budget: ≤ 30 s** on the reference machine for 1 GiB / 25k files (worst measured 17.4 s; ~1.7× headroom for background load). The cost over `synccli.sync` (~2×) is the price of crash safety: temp + rename (~3–6 s measured) and hashing (~0.6 s).

Scaling formula, for other sizes: `T_full ≈ k × (F × c_file + B / bw)` with `c_file = 0.40 ms`, `bw = 600 MiB/s`, and `k = 1.42` = measured 16.6 s / modelled 11.7 s for the mixed tree (mid-size files cost more than the two extremes predict). Example: 3 directories × 1 GiB × 25k ⇒ ≈ 50 s. On other hardware, `backupctl bench` re-measures `c_file` and `bw` with the same two synthetic trees and prints the predicted budget. Parallel copy (hashlib and file I/O release the GIL) is a possible later speed-up; the budget does not rely on it.

The perf test (`BACKUPCTL_PERF=1 python3 -m unittest test_backupctl_perf`) generates the Appendix A tree and fails if a first full run exceeds the budget.

## 11. What grows with what (N directories, F_d files and B_d bytes in directory d, F = ΣF_d, B = ΣB_d; C files / C_B bytes changed since base; S retained snapshots; U unique objects in the store)

| Quantity | Bound | Source |
|---|---|---|
| First full run time | `1.42 × (F × 0.40 ms + B / 600 MiB/s)` | §10 |
| Incremental run time | `≈ 60 µs × F + 1.42 × (C × 0.40 ms + C_B / 600 MiB/s)` | no-op incremental of 25k files measured 1.39–1.55 s (scan + lstat + compare + tree serialize/gzip) |
| — of which for unchanged files | 0 bytes read, 0 bytes written; 1 `lstat` + 1 object `stat` each | §3.2 step 4.5 |
| Peak memory | `≈ M0 + 1.2 KB × max_d F_d + 1 MiB` during runs; `+ 156 B × U` during GC | measured 29.0 MB peak for base + new state of 25k entries (≈1.16 KB/file); mark set 156 B/entry measured; directories are processed one at a time, so memory depends on the **largest** directory, not on N |
| Disk added per run | `C_B` (minus dedup) `+ 64 B × F_d` for each changed directory `+ ~(200 B × N + REPORT)` | tree gzip 1.6 MB / 25k measured; unchanged directory ⇒ identical tree ⇒ 0 B |
| Disk total | `≤ U_bytes + Σ_{distinct retained trees} 64 B × F_d + S × (200 B × N + REPORT)`, `S ≤ 34 + N` | §8.2 |
| GC time | `≈ 40 ms × (F_tree / 25k)` per distinct retained tree + one `scandir` of `objects/` | tree load measured 40 ms / 25k entries |
| Leftovers from dead runs | ≤ 1 staging dir and ≤ 1 temp object per dead run, removed by the next successful run | §6 |
| Locks | 1 writer lock + 1 lock file per retained snapshot (O(S)) | §5 |

Flat (independent of history length): per-run time and memory (they depend on F, C, max F_d, not on S); disk added by a run with no changes (`200 B × N + REPORT`). Growing with history: `U`, therefore GC memory (156 B × U) and total disk; if U ever exceeds ~10 M (1.5 GB mark set), GC switches to 256 passes partitioned by hash prefix (memory ÷ 256).

Worked example, 36 directories × 25k files × 1 GiB, 1 % of bytes new per run: first full ≈ 36 × 16.6 s ≈ 10 min; no-op incremental ≈ 36 × 1.5 s ≈ 54 s; peak run memory ≈ M0 + 30 MB; disk per run ≈ 369 MB of new content + ≤ 58 MB of trees.

## 12. Changes to existing files (all additive or bug fixes; existing tests keep passing)

- `synccli.scan_files(root, skip_hidden_dirs=True, onerror=None, emit_dir_symlinks=False)`: forward `onerror` to `os.walk`; when `emit_dir_symlinks`, append symlinked `dirnames` entries to the result. Defaults reproduce lines 10–19 exactly (`test_scan_sorted_relative` unchanged). `synccli.sync` itself is not changed by this design (its bugs are noted in §1.1 but out of scope).
- `snaputil.safe_snapshot_path`: raise `ValueError` for absolute paths and for normalized paths starting with `..`; add tests for both escapes demonstrated in §1.2.
- `snaputil.prune_snapshots`: raise `ValueError` if `keep < 1` (makes the docstring true).
- `snaputil.is_stale`: align code with docstring (`<`), or delete the function (unused); decide in review.
- New: `backupctl.py`, `test_backupctl.py`, `test_backupctl_perf.py` (opt-in).

## 13. Test plan

- **Unit**: `entry_state` fields; racy rule; `changed_files` reuse with racy filtering; tree determinism (same input ⇒ same hash); INDEX checksum; snapshot naming (seq, monotonic clock).
- **Fault injection** (monkeypatch `os.rename`, `os.write`, journal append to raise at the k-th call, for every k over a small tree; plus subprocess `SIGKILL` at random times on a larger tree): after each crash, (a) every `snap-*` passes `verify --deep`, (b) the next run exits 0/2 without manual action, (c) after it, no staging/tmp/trash leftovers, (d) salvaged bytes > 0 when the crash was mid-copy.
- **Corrupt index**: truncate/garble `INDEX.json`, a `trees/<label>` file, a tree object, delete an object — check quarantine / rederive / report / exit 2.
- **Vanish matrix**: delete between scan and lstat, between lstat and open, during read; `chmod 000` file and dir; FIFO; dangling symlink; missing root; modify during read. Run each with `--trigger scheduler` and `--trigger manual`, assert identical INDEX (minus `trigger`, times) and exit codes.
- **Concurrency**: two `run` processes started together (one exits 75 or both publish sequentially); reader holding `open_snapshot` while prune targets it (deferred, objects intact); reader starting after rename (`SnapshotGone`).
- **Retention**: property test over random histories asserting I1–I3 after every prune.
- **Perf** (opt-in): §10 budget.

## 14. Alternatives considered

- **Hardlink farm** (each snapshot a full directory tree; unchanged files hard-linked from the previous snapshot, rsync `--link-dest` style). Fits `snaputil`'s "snapshot = directory of files" model and is browsable with `ls`. Rejected on measurement: `os.link` costs **415 µs per link** on the reference APFS volume (5,000-link microbenchmark; 11.0–11.5 s for 25k files), so an incremental run of an *unchanged* 25k-file directory takes ~11 s — as long as copying it — and every snapshot adds F directory entries. The chosen design does 0 writes for unchanged files (no-op incremental 1.4–1.55 s). It also makes in-place writes (`synccli.copy_file`'s `"wb"`) silently corrupt every snapshot sharing the inode — a hazard the object store does not have.
- **`synccli.sync` per directory into one rolling mirror**: no point-in-time history, non-atomic, and its manifest bugs (§1.1) violate the "index never promises absent files" rule.
- **Content-hash change detection every run**: robust to all §4 blind spots, but reads all B bytes every run; kept as `--rehash`.

## 15. Assumptions and open risks

- Backup root on a local POSIX filesystem supporting `flock`, atomic `rename`, and (macOS) `F_FULLFSYNC`.
- Measurements come from one machine with possible endpoint-security overhead; Linux ext4/xfs per-file costs were not measured here (expected lower). `backupctl bench` exists to re-derive the budget per host.
- Cross-file consistency within a snapshot is per-file only (§7.1). If the evals workflow needs "a result directory is either entirely in a snapshot or not at all", the workflow should write results to a temp dir and rename it into place, and `backupctl` should exclude the temp pattern.
- A flat tree per configured directory means one changed file rewrites that directory's tree (64 B × F_d). If directories grow far past 10^5 files, split trees per subdirectory (git-style) — same format, recursive.

---

## Appendix A — measurement scripts (run from a scratch dir, argument = this repo)

`bench.py` (baseline `synccli`, hardlinks, temp/fsync variants) — core:

```python
N = 25000; TOTAL = 1 << 30; random.seed(1)
raw = [random.lognormvariate(9, 1.6) for _ in range(N)]
sizes = [max(1, int(r * TOTAL / sum(raw))) for r in raw]       # files in run{00..49}/seed{00..19}/
timed("synccli.sync full", lambda: synccli.sync(src, dst))
timed("synccli.sync no-op 2nd run", lambda: synccli.sync(src, dst))
timed("os.link all files, dirs created once", link_predirs)   # hardlink-farm cost
timed("temp+fsync+rename copy, 1MiB chunks", safe_copy_all)
```

`proto.py` (the §3.3 pipeline) — core:

```python
def store(src, objroot):
    fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
    if NOCACHE: fcntl.fcntl(fd, fcntl.F_NOCACHE, 1)
    before = os.fstat(fd)
    out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444); h = hashlib.sha256()
    while (b := os.read(fd, 1 << 20)): h.update(b); os.write(out, b)
    os.fsync(out); os.close(out); after = os.fstat(fd); os.close(fd)
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    d = h.hexdigest(); dst = os.path.join(objroot, d[:2], d)
    os.unlink(tmp) if os.path.exists(dst) else os.rename(tmp, dst); return d

def run(src, root, base):            # scan_files + lstat state + changed? -> store; gzip tree; F_FULLFSYNC
    for rel in synccli.scan_files(src):
        s = entry_state(os.path.join(src, rel)); b = base.get(rel)
        s["sha256"] = b["sha256"] if b and all(b[k] == s[k] for k in s) else store(...)
```

Also measured: 5,000 × `os.link` in one dir; 5,000 × `chmod`+`utime`; `lstat`; 20 × `F_FULLFSYNC`; `hashlib.sha256` over 256 MiB; `json.loads(gzip.decompress(tree))` × 10; `tracemalloc` peak of the state dicts and of a `set` of 25k digests; `synccli`/`snaputil` behaviors listed in §1 (each a 1–3 line reproduction).

## Appendix B — raw results

```
generate: files=25000 bytes=1073729257 max=8481471
synccli.sync full (warm cache): 9.14s | 8.40s | 8.29s
synccli.sync no-op 2nd run:     0.57s | 0.56s | 0.60s
synccli.scan_files only:        0.37s | 0.38s | 0.36s
synccli.build_manifest only:    1.16s | 1.15s | 1.14s   (under tracemalloc)
manifest entries=25000 peak_py_mem=10.4MB json_bytes=2182717
os.link all files:              11.21s | 11.53s | 11.26s
os.link, dirs created once:     11.01s | 11.16s
lstat all source files:         0.08s | 0.09s
temp+fsync+rename copy:         12.08s | 14.78s
temp+rename copy, no fsync:     11.69s | 15.19s
proto full 1GiB/25k warm:       17.22s | 15.90s | 16.74s
proto full 1GiB/25k F_NOCACHE:  16.59s | 17.40s
proto no-op incremental:        1.44s | 1.55s | 1.48s | 1.39s | 1.47s  (peak py mem 29.0MB)
proto tree: json=5214460 B, gzip=1595368 B
proto 25k x 1KiB:               10.16s | 10.23s | 9.82s | 10.11s | 10.03s
proto 64 x 16MiB:               1.42s | 1.61s | 1.48s | 1.98s | 1.89s
sha256: 1676 MiB/s; os.link: 415 us; chmod+utime: 313 us; lstat: 6.3 us;
F_FULLFSYNC: 0.51 ms; fsync (clean file): 93 us; tree load 25k: 40 ms; mark set: 156 B/entry
```

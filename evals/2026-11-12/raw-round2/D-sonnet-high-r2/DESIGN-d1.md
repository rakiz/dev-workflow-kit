# DESIGN — `backupctl` (fixture D1)

Status: design only, no `backupctl` code exists yet. Every number below is either
measured in this repo copy (method in §9) or derived from a measured constant
with the formula shown. Existing code was exercised: `python3 -m unittest`
runs 6 tests, all pass (0.005 s).

Measurement host: Apple M3 Max, macOS 24.6 (Darwin), APFS on internal SSD,
Python 3.10.11. Constants are machine-specific; the formulas are what carries
over, and §9 says how to re-measure.

---

## 1. Shape of the solution (one paragraph)

Each configured directory gets its own **snapshot store**. A run builds a new
snapshot in a private `staging/` directory, **hardlinking** every file that is
unchanged since the previous snapshot and copying only new/changed files. When
the tree is complete and its index (`MANIFEST.json`) is written, verified and
fsynced, the run publishes it with **one atomic `rename()`** into `snapshots/`.
Published snapshots are never modified again. A snapshot is therefore either
fully there or not there at all; readers never need to know whether a run is
finished. Deletion is a rename out of `snapshots/` followed by unlinking, gated
by a reader lease.

Why hardlink trees and not a content-addressed object store: the brief says
restore is separate tooling that "reads a snapshot and copies it back". A
snapshot that is an ordinary directory tree can be read with `cp -R`, `diff`,
`ls`. The price is paid openly in §7: per-run work is O(files) in metadata
operations, not O(changed files).

## 2. Layout

```
<backup_root>/
  backupctl.json                    config: [{"id": "evals-a", "path": "/abs/src"}, ...]
  <id>/
    lock                            flock target (contents = informational pid only)
    snapshots/
      00000041-20261112T091500Z/    published, immutable
        MANIFEST.json               the index (see §4)
        tree/...                    the files (hardlinks and fresh copies)
    staging/<runid>/                in-progress only; never looked at by readers
    trash/<name>/                   snapshots renamed out for deletion
    leases/<snapname>.lock          reader leases (§6)
    last_run.json                   informational copy of the last report, tmp+rename
```

* `id` matches `[A-Za-z0-9_.-]+` and is unique. A source path inside
  `<backup_root>`, or the root inside a source path, is refused at startup
  (exit 1) to prevent self-recursion.
* Snapshot name = `<seq:08d>-<UTC compact time>`. `seq` is `1 + max(seq)` among
  the names in `snapshots/`, computed while holding the directory lock. Order is
  by `seq`, **never by timestamp**, so laptop sleep, a stepped clock or NTP
  corrections cannot make "newest" wrong. Retention never deletes the newest
  snapshot (§6), so `max(seq)` is monotonic.
* **Reader rule (the whole reader contract):** a snapshot is a directory in
  `<id>/snapshots/` whose name matches `^\d{8}-\d{8}T\d{6}Z$`. Nothing else
  (`staging/`, `trash/`, any dot-name, any `.tmp`) is ever a snapshot.
* Startup probe on the backup root: create a file, `link()` it, `flock()` it, in
  a scratch dir. Failure (FAT/exFAT, many network mounts) = exit 1 with a clear
  message. Hardlinks and `flock` correctness are preconditions; the root must be
  a local filesystem on a single device (so `rename` and `link` never return
  `EXDEV`).

## 3. Grounding: what is built on, what is overridden

Everything is in `synccli.py` (103 lines). `backupctl.py` imports it
(`import synccli`), and `synccli.py` and `test_synccli.py` stay **unmodified**
so the 6 existing tests keep pinning them.

| Existing artifact | Used how |
|---|---|
| `changed_files(old_manifest, new_manifest)` `synccli.py:36-42` | **Reused unchanged** as the change detector. It returns the paths in the new map that are absent from the old map or whose entry dict differs (`old_manifest[rel] != state`, line 40). `backupctl` feeds it manifests whose entries are the richer dicts of §4; dict equality still does the work. Two things it does *not* do, handled outside it: it ignores removed files (iterates only `new_manifest`, line 39) so `backupctl` computes `removed = old.keys() - new.keys()` itself; and it cannot express "always treat this entry as changed" so racy entries (§5) are **dropped from the old map before the call**, which makes them appear new. |
| `sync(src_root, dst_root)` `synccli.py:72-87` | **Skeleton reused, mechanism replaced.** `run_directory()` keeps the same five steps: build source manifest (line 74) → load previous manifest (75-79) → diff (80) → materialize changed files (83-84) → persist the new manifest (85-86). What changes is *where* and *how* (details below): it writes into a private staging tree, not into the live destination, and persists the manifest with write-fsync-rename before an atomic publish. |
| `build_manifest(root)` `synccli.py:28-33` | **Overridden** by `backupctl.build_manifest_v2`. Same name-to-state-dict shape, but it can no longer be the old function because it calls `scan_files` and `file_state`, both overridden below. |
| `scan_files(root)` `synccli.py:10-19` | **Overridden** by `backupctl.scan_tree` for the backup path. Reasons, each reproduced against the existing code: (1) `os.walk` is called with the default `onerror=None` (line 13), so an unreadable subdirectory is silently absent. For a backup that is silent data loss and cannot satisfy "what the run reports". (2) symlinks to directories land in `dirnames`, are not descended into and are never listed: dropped silently (verified). (3) empty directories are never listed (files only). (4) line 14 (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`) silently excludes every hidden directory (`.git`, `.cache`, …); backupctl includes them and offers an explicit `exclude_dirs` list in config instead. (5) speed: line 17, `os.path.relpath`, is 1.97 s of the 2.09 s that `scan_files` takes on the 30k-file benchmark tree; a `scandir`-based walk building relative paths by string join does the same scan plus an `lstat` per file in 0.12 s (§9). `scan_files` itself still works and is still used by `synccli`. |
| `file_state(path)` `synccli.py:22-25` | **Overridden** by `backupctl.lstat_state`. It uses `os.stat` (follows symlinks) and raises on failure, so one vanished file or a dangling symlink kills the whole manifest build (verified: `FileNotFoundError`). It also stores `st_mtime` as a float: for current epoch values the double has ~238 ns resolution, so it is lossy. New version: `os.lstat`, integer `st_mtime_ns`, plus `ctime_ns`, `mode`; ENOENT/EACCES between listing and stat is returned to the caller as a skip record, not raised. |
| `copy_file(src, dst)` `synccli.py:62-69` | **Overridden** by `backupctl.copy_into_staging`. Three defects for backup purposes: (a) `except OSError: pass` (lines 68-69) swallows every failure and the comment "next pass will retry" is false: `sync()` writes the manifest regardless (85-86), so the file is recorded as up to date and never retried. Verified: an unreadable file is skipped, the permission is fixed, the next `sync()` returns `[]` and the file is still absent from dst. (b) `open(dst, "wb")` truncates in place (line 66) and a mid-read failure leaves a half-written file under its final name. (c) `fsrc.read()` (line 67) loads the whole file into memory, so memory = largest file. New version: write to a staging path, chunked 1 MiB, errors classified (§8), never leaves a partial file at a final path, preserves `mtime_ns` and mode. The `os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)` idiom on line 64 is kept. |
| `MANIFEST_NAME` `synccli.py:7`, manifest write `synccli.py:85-86` | Not reused. The in-place, non-atomic `open(path, "w")` + `json.dump` leaves a truncated manifest if the process dies mid-write, and the next `sync()` then crashes on `json.load` (verified: `JSONDecodeError`). `backupctl`'s index is written in staging and published atomically (§4, §8). A `.sync_manifest.json` found inside a source directory is just a file to back up. |
| `collect_stale(items, seen)` `synccli.py:45-59` | **Not used.** It is not on the `sync()` path and is irrelevant to change detection. Its tests (`test_synccli.py:21-33`) keep passing because it is untouched. |
| `main()` `synccli.py:90-99` | Pattern only (`argparse` + `return int`). Note it always returns 0 (line 99) even if copies failed; `backupctl` has defined exit codes (§8.4). |
| `test_synccli.py` | Style and `unittest` + `tempfile` conventions reused for `test_backupctl.py` (§10). |

New module: `backupctl.py` (functions named above plus `load_config`,
`acquire_lock`, `reap_dead`, `choose_base`, `rederive_manifest`,
`stage_links`, `publish`, `prune`, `lease`, `main`). New tests:
`test_backupctl.py`.

## 4. The index (`MANIFEST.json`)

```json
{
  "format": 1,
  "dir_id": "evals-a", "seq": 41,
  "started_utc": "…", "scan_started_ns": 1794536995000000000,
  "status": "clean" | "partial",
  "rederived": false,
  "files":   {"run007/x.dat": {"size": 2, "mtime_ns": …, "ctime_ns": …, "mode": 420, "racy": false}},
  "symlinks":{"latest": {"target": "run007", "mtime_ns": …}},
  "dirs":    ["run007", "empty"],
  "skipped": [{"path": "run003/f.dat", "reason": "EACCES"}],
  "counts":  {"files": 30000, "bytes": 999984975},
  "files_sha256": "<sha256 of canonical JSON of files+symlinks+dirs>"
}
```

* It lives **inside** the snapshot directory, next to `tree/`. It is created in
  `staging/<runid>/MANIFEST.json.tmp`, fsynced, renamed to `MANIFEST.json`,
  *then* verified against the staged tree (§8.2), then the whole staging
  directory is renamed into `snapshots/`. A published snapshot can thus never
  hold an index describing a different tree.
* `files_sha256` lets a loader tell "parses but is wrong" from "good".
* Unknown `format` major version = fatal for that directory (exit 1). It is
  never treated as corrupt and never re-derived over.
* Entries compared by `changed_files` are exactly the dicts under `files`
  (identity fields `size`, `mtime_ns`, `ctime_ns`, `mode`; `racy` is handled
  separately as described in §3, so it is stripped before comparing).

## 5. Change detection: granularity and what it misses

**Granularity: per file, identity = `(size, mtime_ns, ctime_ns, mode)` from
`lstat` of the source, compared to the same tuple recorded in the base
snapshot's index.** No content is read for unchanged files. Symlinks: target
string + `mtime_ns`. Directories: presence.

The identity is deliberately stricter than synccli's `(size, mtime)`
(`synccli.py:25`): `ctime` changes on any write, rename, chmod or `touch -r`
even when the writer restores `mtime`; a false positive only costs a re-copy.

**Racy-timestamp rule (borrowed from git's "racily clean" handling).** Record
`scan_started_ns = time.time_ns()` *before* scanning. Any file with
`max(mtime_ns, ctime_ns) >= scan_started_ns - 2 s` is stored with
`"racy": true`. Racy entries are dropped from the base map in the next run, so
those files are re-copied once. Reason: a write landing in the same timestamp
tick as the stat we recorded, keeping the same size, would otherwise be
invisible forever. 2 s covers FAT (2 s granularity) and HFS+ (1 s).

**Edits this granularity can still miss** (explicit list):

1. A same-size in-place edit on a filesystem whose `mtime`/`ctime` do not
   advance on writes or are coarser than 2 s (some SMB/NFS/FAT mounts).
   Sources are required to be on a local POSIX filesystem; `backupctl` warns
   (`UNTRUSTED_SOURCE_FS`) if the source mount type is in a small deny list.
2. Source and backup host clocks disagreeing (network source): the racy window
   is judged against the local clock.
3. System clock set backwards so that a new write reproduces a recorded
   `mtime` and `ctime` exactly. Practically never, listed for honesty.
4. Corruption that happens without a write through the filesystem (bit rot,
   bad sector) in the *source*: not an "edit", not seen.
5. Because unchanged files are hardlinks, a single corrupted backup inode is
   shared by every snapshot that links it. Not an edit either, but it bounds
   what retention buys you.

Mitigation for 1–4: `backupctl run --full` ignores the base and copies
everything (cost = initial full backup, §7), producing fresh inodes (it also
cuts item 5's sharing going forward). Scheduler recommendation: `--full`
weekly. That bounds the lifetime of any missed edit to ≤ 1 week + retention.

## 6. Concurrency, locking, retention, safe deletion

### 6.1 Locks
* **Per-directory run lock:** `flock(LOCK_EX | LOCK_NB)` on `<id>/lock`, held
  for the entire run including prune. `flock` locks are released by the kernel
  when the process dies for any reason (kill -9, power loss, sleep+wake
  does not drop it): **there is no stale-lock problem and no pid/age
  heuristic**. The pid written into the file is informational only.
* Second run on the same directory (scheduler vs person): by default exit
  **75** (`EX_TEMPFAIL`) immediately, "busy", having touched nothing;
  `--wait SECONDS` polls up to that long. Runs on **different** directories
  hold different locks and may run simultaneously.
* Exclusive access to `snapshots/` mutations (publish, seq allocation, prune)
  is therefore exactly the lock-holder. Two runs can never both rename into
  `snapshots/`; and even if a bug let them, `rename(dir, existing_nonempty_dir)`
  fails, so a published snapshot cannot be overwritten.

### 6.2 What a run reads and writes while a restore reads
A run writes only under `staging/<runid>/` until the single publish rename. It
only *reads* published snapshots (stat and `link()` of their files; read-only
inodes). A restore reads only published snapshots, which are immutable
(files mode `a-w`; nothing ever opens one for writing). Hence concurrent run +
restore cannot corrupt each other. The only interaction is deletion (§6.4).

### 6.3 Retention policy
Applied per directory, only after this run **successfully published** (or by
`backupctl prune <id>`), under the same lock. Never after a failed run.
A snapshot is kept if it is in the union of:

* **A**: the newest 5 snapshots (by `seq`);
* **B**: the newest snapshot of each of the 7 most recent UTC days that have
  any snapshot;
* **C**: the newest snapshot of each of the 4 most recent ISO weeks that have
  any snapshot;
* **D**: the newest snapshot with `status == "clean"` (partial and
  `rederived` ones do not count as clean);
* **E**: any snapshot whose lease is currently held (§6.4), this round only.

Bound: `|kept| ≤ 5 + 7 + 4 + 1 = 17` per directory, plus any leased ones. Time
keys come from the snapshot's index; a skewed clock can only change *which*
extra snapshots are kept, never whether the newest/newest-clean survive
(they are chosen by `seq` and `status`). The count bound also bounds hardlink
fan-out per inode to ≤ 18 (17 + staging), far below ext4's 65 000 link limit;
`EMLINK` from `link()` is nevertheless handled by falling back to a copy.

"Never without a usable snapshot": the newest snapshot (A) and newest clean
snapshot (D) are never deletion candidates, and deletion of snapshot S never
touches any other snapshot's names, and unlinking S's names leaves shared
inodes alive through other snapshots' links. A partial snapshot is still a
complete image of everything readable at the time, and the last good copy of
any skipped file lives on in D (§8.3).

### 6.4 Deleting a snapshot that someone may be reading
A cooperating reader (the restore tooling; a 10-line helper
`backupctl.lease(snapshot)` is provided) does:

1. `open(<id>/leases/<name>.lock, O_CREAT)`, `flock(LOCK_SH)` (blocking);
2. **after** getting the lock, `stat(<id>/snapshots/<name>)`; if gone, close
   and report "snapshot was deleted, pick another";
3. read; release the lock when done.

The pruner, for each candidate: `open(lease, O_CREAT)`, `flock(LOCK_EX |
LOCK_NB)`. If it fails, someone is reading it: **skip**, deletion is deferred
to a later run and reported as `deferred_leased`. If it succeeds, while still
holding the lock: `rename(snapshots/<name>, trash/<name>)` (one atomic step;
from this instant no reader can see a half-deleted snapshot), unlink the lease
file, release, then `rmtree(trash/<name>)`. A death during `rmtree` leaves only
`trash/` residue, reaped by the next run (§8.1).

The reader's step 2 closes the race "reader opens lease file just as pruner
unlinks it": the pruner renames the snapshot away before unlinking the lease,
so a reader that locked an orphaned lease inode finds the snapshot missing.

Non-cooperating readers (plain `cp -R` on a snapshot): files already open stay
readable (POSIX unlink semantics, and hardlinks keep shared data), but a tree
walk may hit `ENOENT` if its snapshot is pruned mid-walk. That cannot yield a
*mixed* image: it fails loudly. The exposure is small in practice because a
snapshot only leaves set A after 5 newer snapshots have been published, so the
snapshot most people restore from (the newest) is never a deletion candidate
for at least 5 publishes. This limit is stated, not hidden.

## 7. Scaling and the performance budget

### 7.1 Notation and measured constants
N = configured directories. For directory *i*: F_i files, B_i bytes,
k_i = files copied this run, b_i = their bytes. S ≤ 17 retained snapshots.
All constants measured on the host above, 30,000 files / 999,984,975 bytes
(max file 5.1 MB), warm page cache:

| Constant | Value | Measured by |
|---|---|---|
| c_scan: `scandir` walk + `lstat` per file | 4.1 µs/file (0.12 s per 30k) | §9, `m2.py` |
| c_link: one `os.link` into a staging tree | 0.32 ms/file (9.5 s per 30k); **did not speed up with 8 threads (9.47 s)** | `m2.py`, `m4.py` |
| c_copy: create + chunked copy + `utime` + `fchmod`, per file, 1 thread | 0.41 ms/file (12.2 s per 30k, incl. 33 KB mean payload) | `m4.py` |
| copy with 4 / 8 threads | 4.68 s / 4.02 s per 30k | `m4.py` |
| BW: one big file copy | 1000 MB in 0.75 s (~1.3 GB/s) | `m3.py` |
| durability: per-file `fsync` / per-file `F_FULLFSYNC` | +0.34 s / +1.18 s per 30k (serial) | `m2.py` |
| index: JSON dump / load of 30k entries | 0.018 s / 0.016 s; 124 B per entry on disk | `m5.py` |
| index in memory | 485 B per entry (17-char paths; +1 B per extra path char) | `tracemalloc`, `m5.py` |
| per extra snapshot directory metadata (30k hardlinks) | ~86 B/file (free-space delta, noisy) | `m5.py` |
| interpreter baseline RSS | 10.7 MB | `m5.py` |
| verify pass: `lstat` 30k staged files | 0.106 s | `m2.py` |

(Native comparisons on this host: `cp -R` 24.9 s wall, `cp -c -R` 8.2 s,
`rsync -a --link-dest` 13.8 s on the same tree. File creation on this host
costs ~0.3 ms regardless of tool, so c_link/c_copy are floor values for this
machine, not artefacts of Python.)

### 7.2 Budget for the first full backup of ~1 GB / ~30,000 files
**Budget: ≤ 30 s wall (hard acceptance limit), expected ≈ 6 s with the default
4 copy workers, ≈ 14 s single-threaded.** Derivation (no guess):

```
T_full = T_scan + T_copy + T_fsync + T_index + T_verify + T_publish
single thread: 0.12 + 12.2 + 1.18 (F_FULLFSYNC) + 0.02 + (0.106 + 0.12) + ~0
             = 13.7 s        (existing synccli.sync did 13.37 s on the same tree: same order)
4 workers:     0.12 + 4.68  + ~1.2          + 0.02 + 0.23       + ~0
             ≈ 6.3 s
```
The existing `synccli.sync` on the same tree: 13.37 s (full), 2.24 s (second
no-op run). The measurements were warm-cache. The cold-cache term is
`B / BW_source`; at even 100 MB/s (spinning disk) that adds ≤ 10 s, so
`13.7 + 10 = 23.7 s < 30 s`. The budget therefore holds down to a source that
reads at 100 MB/s; below that the formula says how far over it will be. Items
that would break the budget and are therefore forbidden in the design: reading
files whole into memory (synccli.py:67), hashing every file by default, and
per-file `fsync` of unchanged (hardlinked) files, none of which is needed.

### 7.3 Per-run work (what grows with what)
For one directory, a run that publishes:
```
T_i = c_scan·F_i              # scan + compare, dominated by lstat
    + (F_i − k_i)·c_link      # hardlink the unchanged files
    + k_i·c_copy + b_i/BW     # copy the changed ones   (÷ ~2.6 with 4 workers)
    + c_verify·F_i            # 0.106 s + 0.12 s per 30k
```
* **Unchanged directory (nothing changed, nothing removed, same skips):
  nothing is published.** Cost = `c_scan·F_i` + load index (0.016 s per 30k)
  ≈ **0.15 s per 30k files**, and **0 bytes of new disk**. (The existing
  `synccli` no-op took 2.24 s, mostly `relpath`.)
* **Directory with any change:** dominated by `(F_i − k_i)·c_link`
  ≈ **0.32 ms × F_i**: 30k files ≈ 9.5 s even if only one file changed. This is
  the honest cost of tree-shaped snapshots; on this APFS host it is linear in
  F_i and not parallelisable (measured). On Linux/ext4 the constant is
  expected to be far lower but is **not measured here** and no claim is made.
* **Across directories:** `T_run = Σ_i T_i` (sequential by default). N enters
  only through the sum and a constant per-directory overhead (one lock, one
  `listdir` of ≤ 17 + a few entries, one index load); there is no N² term.
  Worked: 3 directories × 30k files, all changed slightly: ≈ 3 × 9.5 ≈ 29 s;
  36 directories × 30k: ≈ 36 × 9.5 ≈ 5.7 min; unchanged: 36 × 0.15 ≈ 5.4 s.

### 7.4 Memory
Directories are processed **one at a time**; memory does not sum over N.
```
peak RSS ≈ 10.7 MB (interpreter) + 2 KB · F_max + workers × 1 MiB
```
where `2 KB` = old map + new map at 485 B/entry plus a worst-case projected copy
(the reduced-identity compare of §8.3). For F_max = 30,000: ≈ 10.7 + 58 + 4 ≈
73 MB. Flat in N, bytes and file size (chunked 1 MiB copies; synccli's
`fsrc.read()` was proportional to the biggest file). Honest limit: one
directory with ~500k files costs ~1 GB RSS; that would need a streaming index
and is out of scope (stated in §11).

### 7.5 Disk
```
disk_i ≈ B_i(live) + Σ_(retained snapshots) bytes of files that changed in that interval
         + S_i · F_i · (124 B index + ~86 B dentries)
S_i ≤ 17
```
* Unchanged files cost no data bytes per snapshot; per-snapshot overhead is
  ≈ 210 B per file: 30k files → ≈ 6.3 MB per retained snapshot, ≤ 107 MB for
  the full 17.
* Worst case (every byte rewritten every run, 17 retained): `17 · B_i`. Typical
  growth is `B_i + (changed bytes within the retention window)`.
* Transient: staging needs `b_i + F_i · 86 B` while running; freed by publish
  or reaped on failure.
* Unchanged runs add 0 bytes (no publish). The root cannot grow without bound
  from run frequency: ≤ 17 snapshots per directory, ≤ 17·N total.

What stays flat: snapshot count per directory (≤ 17); hardlink fan-out per
inode (≤ 18); peak memory vs N; number of locks held (1); work for unchanged
directories (≈ 0.15 s per 30k files, no writes).

## 8. Failure semantics

### 8.1 Run algorithm and where it can die
```
 0 acquire dir lock (flock) .......................... die: nothing happened
 1 reap: rm -rf staging/*, trash/* (we hold the lock => every such entry is dead)
 2 choose base (§8.3) ............................... read-only
 3 scan source, plan (changed_files + removed + racy) read-only
 4 if nothing to publish: report "unchanged", release  (no writes at all)
 5 mkdir staging/<runid>/tree ; mkdir dirs
 6 link unchanged files from base tree; copy changed files (workers)
 7 fsync each copied file (F_FULLFSYNC where available) ; fsync directories
 8 write MANIFEST.json.tmp -> fsync -> rename MANIFEST.json (still in staging)
 9 verify: walk staging/tree, every indexed path exists with the indexed size
           (lstat), and no unindexed path exists
10 rename staging/<runid> -> snapshots/<seq>-<ts>  ← THE publish point
11 fsync snapshots/ ; write last_run.json
12 prune (§6.3) ; release lock
```

| Dies at step | What exists afterwards | What the next run does |
|---|---|---|
| 0–4 | nothing new | nothing |
| 5–9 | `staging/<runid>/` with partial tree and maybe partial/complete `MANIFEST.json[.tmp]`. **Invisible to readers** (not under `snapshots/`) | step 1 deletes it whole; report `reaped_staging: 1`; no re-derivation needed because the base is the last *published* snapshot's index |
| 10 | atomic: either the complete snapshot is in `snapshots/` or it is not | if published, the next run sees it as the newest; steps 11–12 are idempotent |
| 11–12 | published snapshot; maybe stale `last_run.json`; `trash/` residue | `last_run.json` is informational only; prune and reap rerun |
| during `rmtree(trash/x)` | partial tree under `trash/` only | reaped at step 1 |

Power loss: steps 7 and 8 fsync data and index before step 10, and step 11
fsyncs the parent, so after a crash the published name implies durable content.
Ctrl-C / SIGTERM: handler sets a flag, workers stop, the run removes its own
staging and exits 130/143; SIGKILL is the table above.

### 8.2 "Never an index promising files that are not there"
Step 9 is a hard gate before publish. Mismatch = run fails (exit 1), staging
deleted, nothing published. The index is also inside the snapshot, so it cannot
be paired with the wrong tree.

### 8.3 Corrupt or half-written index: discarded / re-derived / reported
The protocol makes it impossible for a *dead run* to leave an index in
`snapshots/` (indices are written in staging and published by rename), so the
cases are:

**(a) half-written index from a dead run** (`staging/<runid>/MANIFEST.json[.tmp]`):
*discarded* with its entire staging directory (step 1). *Re-derived*: nothing;
the base is the last published snapshot. *Reported*: `reaped_staging: [runid…]`,
`partial_files_discarded: n`; exit code unaffected (it is routine).

**(b) a published snapshot's `MANIFEST.json` is unreadable, fails
`files_sha256`, or is absent** (disk fault, hand edit, restored-from-elsewhere
store). `choose_base` handles the newest snapshot first:
1. *Discarded:* the bad index is renamed to `MANIFEST.json.corrupt` (kept for
   forensics, never read again). Its `skipped` list, `status`, `ctime_ns`,
   `racy` flags are lost.
2. *Re-derived from the tree:* `rederive_manifest(snapshot/tree)` walks the
   snapshot's `tree/` with `scan_tree` + `lstat_state` and builds `files`,
   `symlinks`, `dirs`. This works because `copy_into_staging` preserves the
   source `mtime_ns` and mode on every copied file, so `(size, mtime_ns, mode)`
   of the snapshot file equals the source file's at copy time (hardlinks share
   the inode, hence the same values). The result is written atomically
   (`MANIFEST.json.new` → fsync → `rename`) with `"rederived": true`,
   `"status": "unknown"`.
3. *Consequences, handled conservatively:* ctime is unknown, so comparison for
   a re-derived base uses the reduced identity `(size, mtime_ns, mode)` on both
   sides; a file whose `mtime_ns` is within 2 s of the snapshot's
   `scan_started_ns` (the snapshot's recorded creation time from its directory
   name, falling back to its directory mtime) is treated as racy; `status`
   unknown never counts as "clean" for retention rule D.
4. *Reported:* warning `INDEX_REDERIVED {snapshot, reason, files}`, listed in
   the run's report and the new snapshot's `skipped`/warnings; run exit code 2.
5. If the tree itself is missing or unreadable, that snapshot is unusable as a
   base: fall back to the next older snapshot; if none, do a full copy; report
   `BASE_UNUSABLE`.
6. Even with a valid index, `link()` of a base file that fails with `ENOENT`
   (file removed by hand) or whose size differs from the index is treated as
   "changed" and recopied from the source; reported as `BASE_MISMATCH {count}`.
   This is why an index lying about a snapshot's contents cannot propagate into
   the new snapshot.

What re-derivation cannot know: whether the tree was *complete* when the index
was lost. A snapshot is only ever published after step 9, so a
published tree is complete unless tampered with; damage to the tree after the
fact is not detectable without a content hash (see `--full`).

### 8.4 Source files that vanish or cannot be read
One policy, one code path, identical whether the process was started by the
scheduler or by a person (no tty detection, no prompts, no `--ignore-errors`
flag). The only behavior flags are `--full`, `--wait`, `--workers`.

* **Vanished** (`ENOENT` at `lstat`/`open` after listing) and **unreadable**
  (`EACCES`, `EPERM`, `EIO` on source read; unreadable *directory* during scan):
  the path is **excluded** from the snapshot. It is *not* carried forward from
  the previous snapshot (that would mix versions, and hides a file that the
  source no longer provides). Nothing partial is left: a half-copied staged
  file is unlinked.
* **Unstable** (the source changes during the copy: `fstat` before vs after the
  read differ in size or `mtime_ns`; retried twice, 3 attempts total): excluded
  the same way, reason `unstable`.
* The path goes into the index `skipped` list with its errno name; the
  snapshot gets `"status": "partial"`; the report lists every skipped path
  (cap 1000 then a count) with its reason.
* **Exit codes:** `0` clean (or unchanged, nothing to publish); `2` snapshot
  published but partial, *or* any warning (`INDEX_REDERIVED`, `BASE_MISMATCH`,
  skipped files, `UNTRUSTED_SOURCE_FS`); `75` busy; `1` failure, nothing
  published for some directory (including **destination-side** errors: write
  `ENOSPC`/`EIO` on staging is fatal for that directory and never downgraded to
  a skip; this source-vs-destination split is the thing `copy_file`'s blanket
  `except OSError` at `synccli.py:68` cannot make). With several directories
  each is processed independently; the overall code is the worst by priority
  `1 > 75 > 2 > 0`.
* The skip is re-evaluated every run: a persistent unreadable file shows up as
  exit 2 every time (visible) without creating a new snapshot each time
  (a publish needs a change, a removal or a different skip set, §7.3). Once
  the permission is fixed, the file is simply "new" and is copied (contrast
  `sync()`, where it never is).
* Where the information lives: stdout one JSON report per directory
  (`{id, outcome, seq, status, copied, linked, removed, skipped[], warnings[],
  reaped_staging, pruned[], deferred_leased[], elapsed_s}`), the same JSON in
  `last_run.json`, the skip list in the published `MANIFEST.json`, a
  one-line human summary on stderr.
* Guarantee about content: each file in a snapshot is a whole, stable version
  of that file observed between scan start and publish. A snapshot is **not**
  a crash-consistent point in time across files (that needs filesystem
  snapshots); what it guarantees is never a mix of two *snapshots* and never a
  half-written *file*. The "never some files from this run and some from the
  previous one" requirement is met in the sense that matters to readers: a
  snapshot is built entirely by one run and does not change afterwards;
  linked files are by definition identical to the source's state the run
  observed.

## 9. How the numbers were obtained (reproducible)

Test tree: `gen.py src 30000 1000000000`, `random.seed(1)`, file sizes
log-normal(0, 1.5) scaled to 1e9 bytes (min 1 B, max 5.1 MB), random bytes
(incompressible), 50 × 20 = 1000 leaf directories. Result: 30,000 files,
999,984,975 bytes, 1.04 GB by `du`.

* Existing code, `import synccli`: `scan_files` 2.09 s; `build_manifest`
  2.13 s; `sync` full 13.37 s; `sync` 2nd run (no-op) 2.24 s; max RSS 70 MB;
  manifest 2.6 MB. `os.walk` alone 0.126 s; `os.path.relpath` × 30k 1.97 s.
* Defects of the existing code were reproduced, not inferred: unreadable
  file → never retried after the permission fix; truncated manifest →
  `JSONDecodeError`; dangling symlink → `FileNotFoundError` in
  `build_manifest`; symlinked directory and empty directory absent from
  `scan_files`; hidden directory excluded, dotfile included.
* Planned pipeline prototypes (throw-away scripts, not part of the repo):
  scandir+lstat walk 0.12 s; serial copy 12.2 s (0.41 ms/file); 4 threads
  4.68 s; 8 threads 4.02 s; hardlink 30k files 9.4-9.8 s serial and with 8
  threads; per-file fsync +0.34 s; `F_FULLFSYNC` +1.18 s; sha256 +0.66 s;
  `rmtree` of a 30k-file snapshot 2.4 s (hardlinked or not); 1 GB single file
  copy 0.75 s; index dump 0.018 s, load 0.016 s, 485 B/entry in memory.
* Caveats: warm page cache (could not purge without sudo); one machine; one
  filesystem; run-to-run noise about ±5 % (three repetitions of the scan: 0.119
  to 0.132 s); the `~86 B/file` dentry figure is a free-space delta on a busy
  system and is the least reliable number here. Acceptance test: re-run the
  same generator + `backupctl run` and assert `elapsed_s ≤ 30`.

## 10. Test plan (`test_backupctl.py`, `python3 -m unittest`)

Crash injection through an env var `BACKUPCTL_CRASH_AT=<phase 3..12>` that
`os._exit(137)`s at the named step of §8.1:
1. For every phase: run, die, run again; assert snapshots/ contains only
   complete snapshots (index lists exactly the tree) and the second run
   succeeds with no manual cleanup.
2. Truncated `MANIFEST.json` in a *published* snapshot → `INDEX_REDERIVED`,
   exit 2, subsequent run recopies nothing that was unchanged.
3. Vanished file (delete between scan and copy via a hook), `chmod 000` file,
   unreadable directory: same results with/without a tty (run under `setsid`
   and a pty).
4. Two concurrent runs same directory: exactly one wins, the other exits 75;
   different directories run in parallel.
5. Reader holding a lease while prune runs: snapshot survives, reported in
   `deferred_leased`; after release it is deleted by the next run.
6. Retention: simulate 60 daily snapshots; assert ≤ 17 kept, newest and
   newest-clean always kept.
7. Racy edit: same-size write within 2 s of scan is picked up by the next run.
8. No change: no snapshot published, 0 new inodes.
9. `test_synccli.py` unchanged and still green (`python3 -m unittest`).

## 11. Decisions that are open or deliberately out of scope

* Restore tooling is not designed here; only its read contract (§2 reader rule,
  §6.4 lease) is.
* A single directory above ~500k files needs a streaming index (§7.4).
* Linux/ext4 constants for `c_link` and `c_copy` are not measured; the formulas
  in §7 give the budget once they are.
* Windows is out of scope (no `flock`, different hardlink and rename semantics).

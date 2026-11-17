# DESIGN-d1: `backupctl`

Status: design only; no code written. Every claim about existing code was
checked by running it in this directory (Python 3.10.11, macOS 24.6 arm64,
APFS SSD). `python3 -m unittest` currently passes (6 tests). Line numbers refer
to the files as they are today.

## 0. Summary of decisions

| Topic | Decision |
|---|---|
| Snapshot shape | One snapshot per run, covering all N configured directories. A snapshot is a **plain directory tree** under the backup root. Unchanged files are **hard links** into the previous snapshot; changed or new files are real copies. |
| Atomicity | A snapshot is built in a staging dir (`.tmp-<runid>/`) that no reader looks at. It becomes visible by one `rename(2)` to `snap-YYYYMMDD-HHMMSS-NN`. Everything named `snap-*` is complete and immutable. |
| Writers | One mutator at a time per backup root (`flock` on `.backupctl/run.lock`). A second run exits 75 ("busy") or waits with `--wait`. |
| Readers | Immutable data plus atomic publish means a reader needs no lock to see a consistent snapshot. Readers that want protection from deletion take a shared `flock` lease. |
| Crash | Nothing time-based and no PID files. `flock` dies with the process. The next run holds `run.lock`, so every `.tmp-*` it finds is provably dead and is discarded. |
| Index | Per snapshot, per directory, plus a `SNAPSHOT.json` carrying sha256 of each index. It is written atomically inside staging, so a dead run can never leave a half-written index in a published snapshot. Recovery for a damaged published index is in section 6. |
| Missing/unreadable source file | The file is **omitted** from the snapshot (never back-filled from the previous snapshot). It is listed under `skipped` in `SNAPSHOT.json` and on stderr, and the exit code is 3. Same behavior for scheduler and person. |
| "Unchanged" | `(size, mtime_ns, ctime_ns)` equality per file, plus a "racy timestamp" rule. Misses are enumerated in section 8. |
| Retention | Newest 10, plus newest per UTC day for 14 days, plus newest per ISO week for 8 weeks. Floor of 2 valid snapshots. Deletion is `rename` to trash first, `rmtree` later, under an exclusive lease attempt. |
| First full backup (30k files, 1 GiB) | Budget **30 s**; measured 9–13 s on this machine (section 10). |

Platform assumption: local POSIX filesystem for the backup root (APFS, ext4,
xfs). It needs `link`, atomic directory `rename`, and `flock`. NFS and SMB are
out of scope. Source and backup root may be on different filesystems, because
hard links are only made inside the backup root.

## 1. Grounding: what is reused, what is overridden

`backupctl.py` will live next to `synccli.py` and `snaputil.py` and import
both. `synccli.py` is changed only in backward-compatible ways, listed in 1.1.

### 1.1 `synccli.py`

| Existing | Lines | Used how | Override or change, and why |
|---|---|---|---|
| `scan_files(root)` | 10–19 | Used for every directory scan. | **Extended, defaults preserve behavior** (new keyword args `onerror=None, skip_hidden=True, include_dir_symlinks=False`). Verified problems today: (a) line 14 drops every dot-directory, so `.git` and `.cache` under an evals results dir would silently never be backed up; backupctl passes `skip_hidden=False`. (b) `os.walk(root)` at line 13 has no `onerror`, so an unreadable subdirectory silently yields no files. I verified a `chmod 000` subdir vanishes from the listing. The new `onerror` lets backupctl record a skip. (c) Symlinks to directories land in `dirnames` and are never returned. I verified `dl -> real/` disappears. `include_dir_symlinks=True` appends them. (d) Line 17 `os.path.relpath(full, root)` per file costs 1.9 s of the 2.08 s measured for 30k files. Computing `relpath(dirpath, root)` once per directory gives identical output (checked `==` on the 30k tree) in 0.15 s. The existing `test_scan_sorted_relative` (test_synccli.py:17–18) must still pass unchanged. |
| `file_state(path)` | 22–25 | Pattern kept (a dict of stat facts). | **Replaced** by `file_state_v2` in backupctl: `os.lstat` (not `os.stat` at line 24, which follows symlinks and raises on dangling ones), integer `st_mtime_ns` instead of float `st_mtime`, plus `st_ctime_ns`, mode and kind. Reason: the float is lossy (about 240 ns resolution at current epoch), and ctime is what catches mtime-preserving edits (section 8). |
| `build_manifest(root)` | 28–33 | Shape `{relpath: state}` kept as the in-memory manifest. | **Replaced** by a tolerant builder. Line 32 calls `file_state` with no handling. I verified that one dangling symlink (listed by `scan_files`, then `os.stat` fails) raises `FileNotFoundError` and aborts the whole build. The same happens for a file deleted between listing and stat. backupctl catches per file, records `{path, reason: "vanished"}` in `skipped`, and continues. |
| `changed_files(old, new)` | 36–42 | **Used as-is** for the diff between the base snapshot's manifest and the new one. | Contract notes. It compares the full state dict by `!=`, so backupctl passes projections of identical key sets (`size, mtime_ns, ctime_ns`; for a derived base only `size, mtime_ns`). It never reports deletions (entries only in `old`). That is fine, because a snapshot is materialized from the new manifest alone. |
| `collect_stale(items, seen)` | 45–59 | **Not used.** | `sync()` never calls it and `seen` is never updated. Its tests (test_synccli.py:21–32) stay as they are. |
| `copy_file(src, dst)` | 62–69 | Only line 64 (`os.makedirs(dirname(dst), exist_ok=True)`) is kept, as the idiom. | **Superseded** by `copy_file_checked`. Line 67 `fdst.write(fsrc.read())` reads the whole file into memory (memory = largest file). Lines 68–69 `except OSError: pass  # ... next pass will retry` is wrong in practice. I verified: an unreadable file is skipped, `sync()` still writes it into the manifest (lines 85–86), and after the file becomes readable the next `sync()` returns `[]`, so the file is **never copied**. A failing write (ENOSPC) is swallowed the same way. The new function streams in 1 MiB chunks, hashes while copying, distinguishes source errors (skip) from destination errors (abort the run), fsyncs, re-stats the source to detect changes during the copy, and sets mtime. |
| `sync(src, dst, dry_run)` | 72–87 | The pipeline shape (scan, manifest, diff, copy, write manifest, `--dry-run`) is the model for `backupctl.run_directory`. | Overridden: (a) lines 77–79 `json.load` of the manifest crashes on a corrupt file. Verified: a truncated manifest raises `JSONDecodeError` on every later run, so one dead run bricks the destination forever. (b) Lines 85–86 `open(path, "w")` truncates the manifest in place, so a kill mid-write leaves exactly that corrupt file. (c) The manifest is written for files that failed to copy (see `copy_file`). (d) The manifest sits in the live destination, and there is no locking. backupctl keeps the idea, but the index is written to a temp name, fsynced and renamed, inside staging, and covered by a checksum. |
| `main()` | 90–99 | The argparse style and "print copied paths" behavior are mirrored in `backupctl run --dry-run`. | New subcommands, section 11. |

### 1.2 `snaputil.py`

| Existing | Lines | Used how | Override, and why |
|---|---|---|---|
| `list_snapshots(root)` | 8–20 | **Used as-is** for enumeration and ordering. | Relies on the `snap-` prefix and a lexicographic sort, so backupctl guarantees (a) staging, trash and quarantine names never start with `snap-` (`.tmp-`, `.trash-`, `.damaged-`), and (b) names are monotonic in publish order (section 3). It also gives `list_snapshots` the property it lacks today: every `snap-*` is complete. Note it raises if `root` is missing. |
| `prune_snapshots(root, keep)` | 23–36 | **Not used for deletion**; superseded by `backupctl.prune`. | Verified: `keep=0` deletes every snapshot (`names[:len(names)-0]`). It counts any `snap-*` directory toward `keep`. `shutil.rmtree` at line 35 runs in place, so a reader can see a half-deleted `snap-*` with its index intact and files missing, which is exactly the "index promises files it lacks" failure. There is no lease. It also has no way to tell that the survivors are usable. Fix: a guard in `prune_snapshots` that raises if `<root>/.backupctl/` exists, and `snaputil.main --prune` (79–84) reroutes to `backupctl prune`. |
| `snapshot_disk_usage(root, name)` | 39–51 | Kept for the "logical size" of one snapshot, **with** the override below. | Verified: `os.stat` at line 50 raises `FileNotFoundError` on a dangling symlink, which snapshots legitimately contain. It also raises if a file disappears underneath it (trash GC). Summed over R hard-linked snapshots it overstates real disk use about R-fold. `backupctl status` uses `unique_disk_usage` (`lstat`, dedupe by `(st_dev, st_ino)`, tolerate ENOENT). Memory is O(unique files in the walk), about 100 B each. |
| `safe_snapshot_path(root, name, rel)` | 54–63 | Replaced by `snapshot_file_path`. | The docstring claim "never points outside" is false. I ran it: `rel="../../etc/passwd"` returns `/b/snap-1/../../etc/passwd`; `rel="/etc/passwd"` returns `/etc/passwd` (an absolute `rel` makes `os.path.join` drop the prefix); `"a/../../x"` returns `/b/snap-1/../x`. `normpath` (line 62) does not remove leading `..`. This matters because index keys come from files on disk, possibly corrupt, and backupctl turns them into `os.link` destinations. `snapshot_file_path` validates the snapshot name against `^snap-\d{8}-\d{6}-\d{2}$`, rejects absolute paths, `..`, `.` and empty components and NUL, and joins under `<snap>/data/<dirname>/`. The index loader applies it to **every** key at load time, so a bad key rejects the index (it becomes the "corrupt index" case). |
| `is_stale(dir, ref_epoch)` | 66–73 | **Not used.** | Verified: the docstring says a directory modified at exactly `ref_epoch` is not stale, but `<=` at line 73 returns `True`. More importantly, directory mtime changes whenever entries are added or removed, so it is not an age. Retention uses the timestamp in the snapshot name and `created_at` in `SNAPSHOT.json`, never mtime. |

### 1.3 Tests

`test_synccli.py` stays untouched and must keep passing. Specifically
`TestScanFiles.test_scan_sorted_relative` (17–18) and `TestSync.test_second_sync_is_noop`
(48–51) guard the `scan_files` extension. New `test_backupctl.py` is described in section 12.

## 2. On-disk layout

```
<backup_root>/
  .backupctl/
    run.lock                  # exclusive flock for every mutator (run, prune, gc)
    leases/<snap-name>.lock   # shared flock held by cooperating readers
  .tmp-<runid>/               # staging, never visible as a snapshot
  snap-YYYYMMDD-HHMMSS-NN/    # published: complete, immutable
    SNAPSHOT.json             # written last in staging
    index/<dirname>.json      # one per configured directory
    data/<dirname>/<relpath>  # the files (hard links or copies)
  .trash-<snap-name>-<YYYYMMDDHHMMSS>/   # renamed for deletion, rmtree'd later
  .damaged-<snap-name>-<YYYYMMDDHHMMSS>/ # quarantined unreadable snapshots
```

`<dirname>` is the configured short name (`^[A-Za-z0-9._-]+$`, unique). Config
is JSON (`backupctl.json`, because Python 3.10 has no `tomllib`):
`backup_root`, `directories: {name: path}`, `retention`. Startup validation
rejects overlapping sources, a source containing the backup root, and the
reverse (this would recurse).

Snapshot name: `snap-` + UTC date + `-` + UTC time + `-` + 2-digit sequence
`NN`. At publish, under `run.lock`, the stamp is `max(now, stamp of newest
existing snapshot)`. `NN` is `0` for a new stamp, else newest `NN + 1`; if that
would pass 99, the stamp is bumped by one second. This makes lexicographic
order equal to publish order even if the wall clock steps backwards, which
`list_snapshots`' `sorted()` silently depends on.

Immutability: copied files get `mode & ~0222`. Hard links share the inode, so
an in-place edit of a snapshot file would corrupt every snapshot sharing it. The
read-only bit stops accidental writes only, not a determined `chmod`.

`SNAPSHOT.json` (abridged):

```json
{"format": 1, "run_id": "…", "created_at": "2026-11-13T10:00:00Z",
 "scan_started_ns": 1794564000000000000, "derived": false,
 "dirs": {"evals": {"source": "/…/evals", "index": "index/evals.json",
          "index_sha256": "…", "files": 30000, "bytes": 1073726845,
          "copied_files": 12, "copied_bytes": 4096,
          "skipped": [{"path": "a/b", "reason": "vanished", "errno": 2}]}},
 "events": []}
```

`index/<dirname>.json`: `{"files": {relpath: {"kind": "file|symlink",
"size", "mtime_ns", "ctime_ns", "mode", "sha256", "target"?}}}`. It records
only what is in `data/`. Skipped files are never in the index. Measured JSON
size is 104 B per file for `size/mtime/ctime`; with mode and sha256 it is about
230 B per file.

## 3. Run algorithm

Phases, in order. Any exception before phase 8 aborts without publishing.

1. **Config and lock.** Validate config. `flock(LOCK_EX|LOCK_NB)` on `run.lock`; if busy, print who holds it (informational only) and exit 75. `--wait SECS` blocks instead.
2. **Housekeeping (recovery, section 6).** Because the caller holds `run.lock`, every `.tmp-*` is dead. Delete them and report. GC `.trash-*` older than 1 h by the timestamp *in the name*. Remove lease files with no matching snapshot (only where an exclusive `LOCK_NB` succeeds).
3. **Choose the base.** Walk `list_snapshots(root)` newest to oldest and take the first snapshot whose `SNAPSHOT.json` and index files validate (parse, `format` known, index sha256 matches, counts match, every key passes `snapshot_file_path`). Invalid ones follow section 6. No valid snapshot means a full first backup.
4. **Per directory, one at a time** (so memory is bounded by the largest directory, not by N):
   1. Record `scan_started_ns = time.time_ns()` (once per run).
   2. `files = scan_files(src, onerror=rec, skip_hidden=False, include_dir_symlinks=True)`. A scan error at the root, or a missing or unreadable root, is **fatal** (a missing source such as an unmounted drive must not produce an empty "complete" snapshot). A scan error below the root is recorded as `{"path": dir, "reason": "unreadable-dir"}`.
   3. Tolerant manifest with `file_state_v2` (`lstat`). `ENOENT` gives skip "vanished". Sockets, FIFOs and device nodes give skip "special".
   4. Guard: zero entries while the base had more than zero is fatal unless `--allow-empty`.
   5. Build the trusted base projection: base entries minus **racy** entries (section 8). Then `to_copy = synccli.changed_files(base_proj, new_proj)`; everything else is "unchanged".
   6. After the first directory's diff is known, check free space: `free >= 1.1 * C + 0.4 KB * F` where C is the changed bytes and F the files in the run so far. Otherwise abort (exit 1) and delete staging.
   7. Materialize into `.tmp-<runid>/data/<d>/`. Unchanged files get `os.link(base_file, staged_file)`, four worker threads (section 10). `ENOENT` (base tree damaged), `EMLINK`, `EXDEV` or `EPERM` falls back to treating the file as changed. Changed files go through `copy_file_checked`. Symlinks are always re-created with `os.symlink(readlink)`.
   8. Write `index/<d>.json.tmp`, fsync, rename to `index/<d>.json`. Release the manifests.
5. **Durability.** Copied files are fsynced at close (`copy_file_checked`). fsync every staging directory (0.12 s for 1,100 directories, measured), then fsync `SNAPSHOT.json` (also tmp + rename).
6. **Write `SNAPSHOT.json`** last, including each index's sha256 and the `skipped` lists.
7. **Publish.** Choose the name (section 2), `os.rename(".tmp-<runid>", "snap-…")`, fsync the backup root. `rename` of a directory is atomic. It fails if the target exists, and then the name is bumped and retried.
8. **Retention (section 9)**, then trash GC, then the report and the exit code.

Signals: SIGINT and SIGTERM raise, a `finally` removes staging, and then exit
1 (or 130 for SIGINT). SIGKILL, power loss and sleep leave staging behind, handled in
phase 2 of the next run.

Exit codes (identical for scheduler and person; no TTY-dependent behavior, no
prompts): 0 clean; 1 failed, nothing published; 2 usage or config error; 3
published with warnings (skips, recovery events, retention suspended); 75 busy.

## 4. Concurrency

The contract is: *"concurrent triggers never corrupt anything, and readers
never need to know whether a run finished."*

- **Run versus run (scheduler and person).** The second trigger hits `run.lock` and exits 75 (or waits). Both can be launched at the same instant; at most one mutates. The cost is that a hung run blocks later runs. `flock` is released when the holder dies, so only a live-but-stuck process can block, and `.backupctl/run.lock` contains the holder's pid and start time for the human to see. Nothing reads that content to make a decision. Running two writers in parallel was rejected: it doubles the copied bytes (both diff against the same base), and it would need a second protocol for name allocation.
- **Run versus a reader (restore).** The restore reads only `snap-*` directories. A run writes only under `.tmp-*` and then performs one `rename`. A reader therefore sees the old set of snapshots or the new set, never a part. Files inside a published snapshot never change, and the hard links of the next run do not modify the linked inodes (a hard link adds a name, not a write).
- **Prune versus a reader.** A cooperating reader (the restore tool should use `backupctl.open_snapshot(name)`) takes `flock(LOCK_SH)` on `leases/<name>.lock`, and *then* checks that `snap-<name>` exists and that `SNAPSHOT.json` validates. Prune takes `LOCK_EX|LOCK_NB` on the same lease file. If a reader holds it, that snapshot is skipped this time. The order (lock, then check) closes the race; a reader that arrives after the rename finds the snapshot gone and reports "snapshot no longer exists" and nothing else. The flock-unlink race is covered by the same existence check, and orphan lease files are cleaned in phase 2.
- **A non-cooperating reader** (plain `cp -a`) is protected as follows. Published data is immutable, and the newest `keep_last` snapshots are never deleted, so anything recent is always safe. A deleted old snapshot is `rename`d to `.trash-*` first (atomic; no half-deleted `snap-*`), and `rmtree` waits at least 1 h. A reader that was mid-walk when the rename happened keeps working on already-open handles and the directory itself. If it later gets `ENOENT`, it fails loudly. It never silently mixes data from two snapshots.
- **Source files changing during a run.** See sections 7 and 8. The snapshot is *internally* consistent (index equals contents; every file comes from this run's scan). It is **not** an atomic instant of the live source, because no tool can provide that without a filesystem snapshot. Files written minutes apart during a run can show cross-file skew. An optional `pre_snapshot_cmd` hook is the extension point (for example, an APFS local snapshot or LVM snapshot of the source).

## 5. Crash model

The process may die at any instruction. Since the visible state changes only at
phase 7's `rename`, the cases are:

| Died during | Left behind | Reader sees | Next run does |
|---|---|---|---|
| phases 1–6 | `.tmp-<runid>/` (maybe with a half-written `index/*.json.tmp` and part of the data) | Nothing new. `.tmp-*` is not `snap-*`, so `list_snapshots` ignores it. | Phase 2 deletes it and reports `discarded-incomplete-run`. Copied bytes are redone. No resume (simplicity over saving one run's work). |
| phase 7, before `rename` | same as above | same | same |
| phase 7, after `rename`, before fsync of root | a published, complete snapshot (after a power loss it may be missing) | Either nothing new or a complete snapshot | Nothing special. |
| phase 8, mid-prune | a `.trash-*` dir, or a victim not yet renamed | Remaining `snap-*` are complete | Phase 2 finishes the GC. A rename-but-not-yet-rmtree state is harmless. |
| mid-`rmtree` of trash | a partly deleted `.trash-*` | nothing (not a snapshot name) | Phase 2 retries. |

Laptop sleep: nothing depends on elapsed wall time (no stale-lock timeouts, no
PID liveness probes), so a suspended run is just a slow run. A run that wakes
up hours later still publishes a consistent snapshot, with the stable-copy
check in section 7 applying to every changed file.

Power loss or kernel crash: copied files, indexes and directories are fsynced
before the rename, so a published snapshot is complete on disk. On macOS, plain
`fsync` does not flush the drive cache (`F_FULLFSYNC` does); the design uses
`fcntl(F_FULLFSYNC)` (not measured here) only for `SNAPSHOT.json` and the root
directory, to keep the cost low, and documents that per-file durability on
macOS is best-effort. A published snapshot that is damaged after the fact is
handled by section 6.

## 6. Index recovery

Indexes are the only metadata, so every way an index can be bad has a defined
outcome. Principle: **the tree is the ground truth of what a snapshot
contains; the index is a description that must be discarded when it cannot be
trusted, and never a promise.**

**A. Index left by a dead run.** An index is only ever written inside staging
(`.tmp-*`, as `*.json.tmp`, then renamed). A dead run therefore leaves only a
staging dir. *Discarded:* the whole staging dir, including any half-written
index. *Re-derived:* nothing (there is nothing to re-derive; the run starts
from the last published snapshot). *Reported:* `discarded-incomplete-run id=…
files=… bytes=…` in the run's `events`, and on stderr; exit 3.

**B. A published snapshot whose `SNAPSHOT.json` or index is unreadable.** This
cannot be caused by backupctl's own crash. It can be caused by disk or
filesystem damage, a lost write after power loss, or manual edits. The run
detects it at base selection by any of: parse failure, unknown `format`,
sha256 mismatch against `SNAPSHOT.json`, file-count mismatch, an unsafe key
(section 1.2), or a missing `index/` file. Then:

1. *Discarded:* the bad `SNAPSHOT.json` / `index/*.json`, kept as `*.corrupt` next to the repaired files.
2. *Re-derived from the tree:* a new index per directory made by walking `data/<d>/` with `scan_files(skip_hidden=False, include_dir_symlinks=True)` plus `lstat`. The index then promises exactly what is on disk and no more. Entries get `size`, `mtime_ns` (backupctl copies preserve source mtime, so this is meaningful), `mode` and `kind`; `ctime_ns` and `sha256` are `null`. `SNAPSHOT.json` is rewritten with `"derived": true` and its `skipped` list marked `"unknown"`. Both are replaced with write-tmp, fsync, `rename`, which is atomic for readers.
3. *Trust level:* a derived index is **not** equivalent to the original. As a base it is compared on `(size, mtime_ns)` only (the missing ctime guard is the lost protection), and the whole-tree "racy" cut-off becomes the snapshot's *name stamp minus 2 s* (later than the true scan start, so more files are re-copied, which is conservative). A derived snapshot does not count as "the surviving usable snapshot" in the retention safety rule (section 9), and it is counted by no keep rule: retention deletes it once at least `keep_last` newer non-derived valid snapshots exist.
4. *Unknown format version or unrecoverable tree* (cannot walk `data/`): the snapshot is renamed to `.damaged-<name>-<ts>/` (a rename, so no data loss), is not a base, and is purged after 30 days only if at least 2 valid snapshots exist.
5. *Reported:* `index-recovered snapshot=<name> reason=<parse|sha|count|unsafe-key|missing> entries=<n>` per snapshot, and exit 3.

**C. Valid index, damaged tree** (a promised file missing or with the wrong size). Found lazily: `os.link` or the size check fails in phase 4.7. The file is re-copied from the source (or skipped if the source is gone), and the event `base-entry-missing snapshot=… path=…` is recorded; exit 3. The old snapshot is left as is. `backupctl verify <snap>` lists all such problems (a full lstat comparison, about 0.06 s per 30k files).

**D. No usable snapshot at all.** Full backup; retention is suspended for this run (section 9).

## 7. Source files that disappear, change or cannot be read

The rule is the same everywhere and independent of who started the run:
**a snapshot contains exactly the files that were successfully captured by this run;
every file that was not captured is absent and is named in `skipped`.**

| What happens | Snapshot contains | Report |
|---|---|---|
| Vanishes between listing and `lstat` | file absent | `skipped: {path, reason: "vanished"}` |
| Vanishes between `lstat` and open, or during read (`ENOENT`, `ESTALE`) | file absent (partial copy deleted from staging) | `skipped: {reason: "vanished"}` |
| Unreadable (`EACCES`, `EPERM`, `EIO` on the source) | file absent | `skipped: {reason: "unreadable", errno}` |
| Unreadable subdirectory | its files absent | `skipped: {path: dir, reason: "unreadable-dir"}` |
| Changed while being copied: `fstat` before the read differs from `fstat` after (`size, mtime_ns, ctime_ns`); retried twice, then given up | file absent (a torn copy would break "self-consistent") | `skipped: {reason: "changed-during-copy"}` |
| Socket, FIFO, device | absent | `skipped: {reason: "special"}` |
| Destination errors (`ENOSPC`, `EDQUOT`, `EROFS`, `EIO` on staging) | n/a | **fatal**: run aborts, staging deleted, exit 1 |

Deliberate choice: a missing file is **not** back-filled from the previous
snapshot. Doing so would produce exactly the "some files from this run, some
from the previous one" mix the brief forbids. The cost is that an
always-changing file (a live log) is never in a snapshot; the `skipped` list
makes this visible. Reporting: one stderr line per skip (first 50, then a
count), the full list in `SNAPSHOT.json`, and exit 3. Retention (section 9)
also keeps the newest snapshot with zero skips, so a run of lossy snapshots
cannot push out the last complete one.

Related: files omitted by `scan_files` today (hidden directories, directory
symlinks, unreadable directories) are exactly the silent omissions that this
design removes (section 1.1).

Not preserved in v1, stated rather than hidden: empty directories, owner/group,
xattrs and ACLs, hard-link relationships *inside* the source (each is copied as
an independent file), and sparse-file holes (they are materialized).
Directory permissions are not recorded; restore creates directories with the
umask default.

## 8. Change detection: granularity and its blind spots

**Granularity: per file, by equality of `(size, mtime_ns, ctime_ns)` from
`lstat`**, evaluated by `synccli.changed_files`. The state is taken at scan
time in *this* run and compared with the base index. So every "unchanged" file
in a snapshot is backed by an observation made during this run, not by an
inherited assumption.

Beyond what `synccli.file_state` compares today (`size`, float `mtime`) this
adds ctime, because `ctime` cannot be set by user space: `utimensat` (used by
`touch -r`, `cp -p`, `rsync -t`, `tar x`) resets it to "now". Edits that keep
size and mtime therefore change ctime. I verified the original gap:
rewriting a file with same-length content and restoring mtime via
`os.utime(ns=…)` leaves `file_state` identical, so `synccli.sync` would have
skipped the edit.

**Racy timestamps.** The base index stores `scan_started_ns`. A base entry whose
`mtime_ns >= scan_started_ns - 2 s` (2 s is the coarsest common timestamp
granularity, FAT, HFS+, ext3) is dropped from the trusted projection before
`changed_files`, so the file counts as changed and is re-copied once. This
closes the case where a file is modified a second time inside the same
timestamp tick as the previous scan.

**What this still misses** (stated plainly):

1. A change that preserves size, mtime *and* ctime. This requires stepping the system clock back or raw device writes. It is not reachable through normal file APIs.
2. Silent media corruption or bit rot of the *source* with no metadata change. Backupctl faithfully backs up whatever the source says.
3. A file modified between its `lstat` in this run's scan and the `os.link` of its previous copy, within the same run: the snapshot holds the pre-modification version (a valid state during the run), and the next run sees a different `ctime` and re-copies. Same for files modified during the run after they were copied (the stable-copy check applies only to the window of one copy).
4. Filesystems whose ctime or mtime granularity is coarser than the edit interval **and** whose edit is not inside the racy window (an edit more than 2 s after the previous scan is a different timestamp on any filesystem with at most 2 s granularity, so this is not exploitable in practice).
5. Under a *derived* base (section 6.B): ctime is unavailable, so a same-size mtime-preserving edit is missed for that one comparison only.

Mitigation knob (default off, costs one extra source read per slice):
`verify_fraction: 1/K` re-hashes the files whose `hash(path) % K ==
run_seq % K` and compares with the stored sha256, so every file is
re-verified every K runs and misses 1 and 2 above are bounded to K runs. With
K=16, the read cost is B/16 per run (about 64 MiB per GiB).

## 9. Retention and deletion

Policy (`retention`, defaults): keep the union of

- the newest `keep_last = 10` valid snapshots;
- the newest snapshot of each UTC day, for `keep_daily = 14` days;
- the newest snapshot of each ISO week, for `keep_weekly = 8` weeks;
- the newest valid snapshot, and the newest valid snapshot with zero skips;
- the snapshot published by the current run.

Config validation requires `keep_last >= 2`. Eligible set for the keep rules: valid, non-derived
snapshots. Derived snapshots are deletable as described in 6.B; damaged and
unknown-format ones are handled only by the quarantine rule in 6.B. Upper bound on retained snapshots: R <= 10 + 14 + 8 + 1 = 33.

Prune runs only at the end of a **successful publish** in the same run (or by
`backupctl prune`, which also takes `run.lock`). A failed or aborted run
deletes nothing.

"Never leave the user without a usable snapshot" is enforced, not assumed:

1. **Pre-check.** Before deleting anything, verify the newest valid snapshot (parse, sha256, and an `lstat` comparison of every index entry against its tree, about 0.06 s per 30k files). If the check fails, **no deletion happens**; the run reports `retention-suspended` and exits 3. With `keep_last >= 2` the older ones are the fallback.
2. **Deleted only from the oldest end of the not-kept set**, one at a time, never the newest valid one.
3. **Per victim:** `flock(LOCK_EX|LOCK_NB)` on its lease file. If a reader holds it, skip (retry next run). Otherwise re-check the snapshot still exists, `rename` it to `.trash-<name>-<now>` (atomic), delete its lease file, release.
4. **Trash GC** (phase 2 of a later run, or phase 8 of this one for entries older than 1 h by the name's timestamp) runs `rmtree`. It can fail and retry harmlessly; trash is not a snapshot name.

Hard links make deletion independent: deleting snapshot S only removes names.
Any later snapshot that linked S's files still holds its own link, so no
reference counting or mark-and-sweep is needed, and no snapshot depends on
another being present. That is the reason for hard links over a delta chain or
a content-addressed object store.

`rmtree` of a 30k-file linked snapshot took 2.4 s (measured); `rename` of
the snapshot directory took 0.3 ms. The slow part is outside every reader's
path.

## 10. First-backup performance budget

Reference tree: 30,000 files, 1,073,726,845 bytes (1.0 GiB), 1,100 directories,
lognormal sizes (median 4.9 KB, max 18 MB), generated with a fixed seed.
Machine: Apple M-series, APFS SSD, Python 3.10, warm page cache for the source.
(Cold cache and spinning disks were not measured; see assumptions below.)

Measured components (each reproduced; ranges are repeated runs):

| Step | Measured |
|---|---|
| `synccli.scan_files` (current code) | 2.0 s, of which 1.9 s is `os.path.relpath` (30k calls) |
| scan with per-directory relpath (the extension in 1.1) | 0.15 s, output identical |
| `lstat` of all files (ns state) | 0.06 s |
| existing `synccli.sync`, full copy to empty destination | 10.95 s (no fsync, no hash, reads whole file into memory) |
| prototype `copy_file_checked` loop (1 MiB chunks, sha256, utime, per-file fsync) | 8.6, 8.8, 12.6 s; 11.7 s in an earlier run |
| same without fsync | 10.4 s (fsync was not the bottleneck) |
| per-file cost isolated: 30,000 x 1 KiB files, same loop | 6.34 s, i.e. 211 us/file |
| per-byte cost isolated: one 1 GiB file, same loop | 1.02 s, i.e. about 1 GB/s |
| fsync of 1,100 directories | 0.12 s |
| index JSON parse (3 MB, 104 B/file) | 0.06 s (write not timed separately; same order) |
| `os.rename` publish | under 1 ms |

**Budget: the initial full backup of the reference tree completes in at most
30 s wall time** on this class of machine (local SSD, warm cache). Derivation:
total is about `0.15 + 0.06 + (8.6..12.6) + 0.12 + 0.1 = 9 to 13 s` measured
for the prototype pipeline; 30 s is about 2.3x the worst observation to
absorb a cold source cache, a concurrent job, and the bookkeeping that the
prototype did not have (tolerant stat, skip lists, free-space check).

Scaling formula used to project other sizes (a conservative fit that is at or
above every measured run): `T_full <= 0.4 ms * F + 2 s/GiB * B`. For the
reference tree that is 12 + 2.1 = 14.1 s, and the 30 s budget is about 2x it.
The isolated 1 KiB and 1 GiB runs predict 7.3 s, so the fit already
includes the mid-size files and per-call overhead that the two extremes
understate.

Incremental runs (what grows with the *file count* even when nothing
changed): for 30k unchanged files: scan 0.15 s + lstat 0.06 s + diff 2 ms +
**hard-link pass 8.7 to 10.5 s serial, 5.0 s with 4 threads** (measured,
APFS: about 0.29 ms per `link`, 0.17 ms with 4 threads; 8 threads was slower,
7.0 s, so the default is 4). This is as slow as a copy for a small-file tree.
It is the honest cost of the plain-tree snapshot format on APFS; on other
filesystems the link cost was not measured and no claim is made. Incremental
budget for the reference tree: at most 15 s for a no-change run (4 threads,
about 5.3 s measured). The saving versus copying is in bytes written and in
disk space, not in file-system operations.

Assumptions under which the budget holds, and where it does not: local SSD;
source reads at least 500 MB/s; no antivirus filter driver. It does not hold
for rotating disks (30k opens at about 10 ms seek is about 300 s) or network
sources; those are out of scope. The test in section 12 is a scaled check
(`0.4 ms * F + 2 s/GiB * B` with a 2x allowance) rather than an absolute
wall-clock assertion, so it travels across machines.

## 11. What grows and what stays flat

Notation: N directories; F_d and B_d files and bytes of directory d;
F = sum F_d, B = sum B_d; F_max = max F_d; C = bytes changed since the last
run, c = files changed; R = retained snapshots, R <= 33 (section 9).

| Quantity | Bound | Basis |
|---|---|---|
| **Per-run time** | `T <= F * (7 us + 0.29 ms) + c * 0.2 ms + C / (1 GB/s)` serial on APFS, hard-link term about 0.17 ms with 4 threads. Linear in F. Independent of B (except through C), of R, and of N except through F. Example: 3 dirs of 30k files give about 27 s serial (about 15 s threaded); 36 such dirs (1.08 M files) give about 5.4 min serial (about 3 min threaded) with nothing changed. | measured, section 10 |
| **Per-run memory** | `M <= 1.2 KB * F_max + 1 MiB` copy buffer. About 36 MB for 30k files per directory, 120 MB for 100k. **Flat in N, B and R**, because directories are processed one at a time and each index is flushed and released. | measured: two manifests with `size, mtime_ns, ctime_ns, mode, sha256` cost 1,045 B per file under `tracemalloc` (one manifest 523 B), plus about 90 B per path string |
| Design limit | `F_max <= 100k` per directory (about 120 MB). A directory beyond that needs a streaming/sorted index, which is not designed here. | stated limit |
| **Disk, steady state** | `D <= B_0 + sum over retained r of C_r + R * F * 0.4 KB`, where `B_0` is the current size and `C_r` the bytes copied by run r. Worst case (every file changes every run) is `R * B`, i.e. 33 x. Typical evals pattern (append new result dirs, old ones frozen) is `D ≈ B + small`. | formula; 0.4 KB = 0.17 KB directory entries (measured by free-space delta on APFS: 14.6 MB for 3 snapshots of 30k files, so 166 B/file/snapshot; noisy) + about 0.23 KB index (JSON size measured at 104 B without mode/sha, estimated with them) |
| **Disk per snapshot overhead** | about 0.4 KB * F; for 30k files, about 12 MB (4.9 MB measured dirents + about 7 MB index). | as above |
| **Disk, transient** | staging holds up to C bytes plus the above, while the previous snapshots still exist. The free-space check in phase 4.6 requires `1.1 * C + 0.4 KB * F` free. Trash holds the victim's directory entries for at least 1 h. | formula |
| **Lock/lease files** | at most R + 1 files, O(1) per run. | by construction |
| **`SNAPSHOT.json`** | O(N + skipped). | by construction |
| **Retention work per run** | pre-check `lstat` pass: F * 2 us (0.06 s per 30k, so 2 s per 1 M files); at most a few renames; `rmtree` of a victim: about 80 us per file (2.4 s per 30k, measured) and off the reader path. | measured |
| **Flat regardless of N** | the number of locks (1 run lock plus R leases), the staging location, the snapshot naming and retention policy, the publish step (one `rename`). | by construction |

## 12. Verification plan (`test_backupctl.py`, `python3 -m unittest`)

Fault injection uses an env var `BACKUPCTL_FAULT=<phase>[:<n>]` that calls
`os._exit(137)` at the named point (after k files copied, after an index
write, before and after the rename, mid-prune).

1. **Crash matrix.** Kill at each phase: afterwards `list_snapshots` contains no new name, a plain read of every `snap-*` yields an index equal to its tree, and the next run succeeds with `discarded-incomplete-run` and exit 3.
2. **Corrupt index.** Truncate `index/x.json`, flip a byte (sha mismatch), plant `"../../x"` as a key, delete `SNAPSHOT.json`. Each yields the section 6.B outcome, with no writes outside the root.
3. **Concurrency.** Two runs started together: one exits 75 and the other publishes. A reader thread walking the newest snapshot while a run publishes and prunes sees either snapshot set but never a partial one (index equals tree, checked repeatedly). With a lease held, prune skips that snapshot.
4. **Vanish and unreadable.** A hook deletes a file between scan and copy, and a `chmod 000` file. Snapshot omits both, `skipped` names them, exit 3. The same result with stdin attached to a TTY and with it closed.
5. **Change detection.** Same-size/same-mtime edit via `os.utime` is detected by ctime (the contrast case: `synccli.file_state` misses it). Racy-window file is re-copied once. Derived base compares on `(size, mtime_ns)`.
6. **Retention.** `keep=0` rejected by config. A corrupt newest snapshot suspends retention. The newest zero-skip snapshot survives a run of lossy ones. The union of day/week buckets matches a hand-computed set.
7. **`snaputil` overrides.** `snapshot_file_path` rejects `../../etc/passwd`, `/etc/passwd`, `a/../../x`. `unique_disk_usage` handles dangling symlinks and hard-linked snapshots (sum equals unique inodes). `prune_snapshots` refuses on a backupctl root.
8. **`scan_files` extension.** Defaults give identical output to the old function on a fixture with hidden dirs and symlinks; the new flags include them; `onerror` fires for a `chmod 000` directory. The existing 6 tests pass.
9. **Scaled performance check**, per section 10.

## 13. CLI

`backupctl run [--config FILE] [--dry-run] [--wait SECS] [--allow-empty]`;
`backupctl list`; `backupctl status` (uses `unique_disk_usage`);
`backupctl verify <snap>`; `backupctl prune`; `backupctl lease <snap> --
<command ...>` (holds the shared lease while the command runs, for restore
tooling). `--dry-run` computes `to_copy` and prints relative paths like
`synccli.main` (lines 96–98) and writes nothing, including no staging.

## 14. Known risks and non-goals

- Hard-link cost per file on APFS is high (section 10); an index-only, content-addressed store would make unchanged files free, but it makes restore require backupctl and it needs mark-and-sweep GC with its own concurrency protocol. Chosen against for v1; revisit if F reaches the millions.
- Hard-link count limits (`EMLINK`, about 32k on ext4): handled by falling back to a copy, which costs disk but never correctness. R <= 33 stays far below it.
- Cross-file atomicity relative to a live source is not provided (section 4).
- `snaputil.main --prune` remains a hazard on a backupctl root until the guard in 1.2 is applied.
- Cold-cache and non-SSD performance were not measured; numbers carry the stated assumptions.
- The "free-space" and "empty directory" guards are heuristics against two real failure modes (a full disk, an unmounted source), not complete protections.

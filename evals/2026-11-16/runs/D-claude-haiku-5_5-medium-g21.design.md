# DESIGN-d1: `backupctl`

Status: design, no code yet. Author: single-agent design (no delegation).
Scope: a snapshot-based backup tool for a configured set of N source
directories, living next to `synccli.py` / `snaputil.py` in this repo.

All line numbers refer to the files in this directory as they exist today.
Measurements were taken on this machine (Apple M3 Max, 14 CPUs, APFS on
`/dev/disk3s5`, arm64, Python 3, warm page cache) using a generated tree of
30,000 files totalling 1.0 GiB (34 KiB per file, random content).

---

## 1. Summary

- Every run produces an **immutable snapshot**: a complete directory tree of
  every configured source, plus an index file. A snapshot is built in a
  hidden staging directory and becomes visible by a single `rename(2)`.
  Readers only ever see `snap-*` directories, and each one is complete.
- **One writer at a time**, enforced by an exclusive `flock` on
  `backup_root/.backupctl.lock`. A second run fails fast with exit 75 and
  does not wait. The lock is released by the kernel when the process dies,
  so it never goes stale.
- **Readers take no writer lock.** A restore takes a shared `flock` on a
  per-snapshot lock file. Retention takes the exclusive form of that same
  lock before it deletes a snapshot, and defers the deletion if a reader is
  active.
- **Unchanged files are hardlinked** from the previous published snapshot,
  so only changed bytes are copied. Each snapshot is still a full tree, so
  deleting any snapshot never breaks another one.
- **Interrupted runs** leave only `.inprogress-*` and `.trash-*` directories,
  which the next run sweeps under the writer lock. Partially copied files are
  kept only when a journal proves them good (see section 6).
- **Vanished, unreadable, or unstable source files** are skipped, listed in
  the index and the run report, and the run exits 3. The behavior does not
  depend on who started the run.
- **Retention** keeps the newest K verified snapshots (K >= 1, default 14).

---

## 2. Assumptions

- Local POSIX filesystem for both the sources and the backup root, on the
  same volume (required for atomic `rename` and for hardlinks). Targets are
  APFS and ext4. Network filesystems are out of scope, because `flock`
  semantics there are unreliable.
- Timestamps have nanosecond resolution (APFS, ext4). Section 7 covers the
  coarser case.
- Symlinks are recorded, not followed. Hardlinks in the source are stored as
  independent files. Owners, ACLs, and xattrs are not preserved; file mode
  bits (`st_mode & 0o7777`) are.

---

## 3. Grounding: reuse and override of the existing code

Every item below was checked against the file. Items marked **verified** were
also reproduced by running the code.

| Existing artifact | Status in `backupctl` | Reason |
|---|---|---|
| `snaputil.list_snapshots` (snaputil.py:8-20) | **Reused as is.** Lists published snapshots. | It only returns directories whose names start with `snap-` (line 18). Staging directories therefore must not use that prefix. They use `.inprogress-` and `.trash-`. |
| `snaputil.snapshot_disk_usage` (snaputil.py:39-51) | **Reused for logical size only.** Disk usage needs an override. | It adds `st_size` for every path it meets (line 50). With hardlinks, the same inode is counted once per snapshot, so the total overstates real usage. The override deduplicates on `(st_dev, st_ino)`. This is a new optional parameter, `unique_inodes=True`, in `snaputil.py`. |
| `synccli.scan_files` (synccli.py:10-19) | **Reused as the walk shape; three overrides.** | (a) Line 14 prunes every directory whose name starts with `.`. Backup must include them, so `include_hidden=True` is added. (b) Symlinked directories appear in `dirnames` and are never followed, but lines 15-18 only collect `filenames`, so they vanish silently. They must be recorded as links. (c) `os.walk` is called without `onerror` (line 13), so an unreadable or vanished directory is swallowed. An `onerror` callback records it. |
| `synccli.file_state` (synccli.py:22-25) | **Overridden.** | `os.stat` follows symlinks. `st_mtime` is a float and loses nanoseconds. The state has no ctime or inode, so an atomic-replace edit with the same size and mtime is invisible. Replacement: `os.lstat`, returning `(size, mtime_ns, ctime_ns, ino, mode)`. |
| `synccli.build_manifest` (synccli.py:28-33) | **Adapted.** Same loop shape, new state function. | Line 32 calls `file_state` with no handling. **Verified:** a file that vanishes between the scan and the stat raises `FileNotFoundError` and aborts the whole run. Backupctl catches it per file. |
| `synccli.changed_files` (synccli.py:36-42) | **Idea adapted, not reused.** | It returns only new or changed paths and never reports deletions. Backupctl needs a per-entry key comparison against the reference snapshot, plus a racy-entry rule (section 7). |
| `synccli.copy_file` (synccli.py:62-69) | **Overridden.** | Line 67 reads the whole file into memory. Lines 68-69 catch `OSError` and `pass`, so a failed copy is silent. **Verified:** a file with mode 000 was recorded in the manifest and never copied; after `chmod 600`, the next run reported nothing copied. The override streams in 1 MiB chunks, hashes while copying, re-checks the source with `fstat` after reading, and returns an explicit status. |
| `synccli.sync` (synccli.py:72-87) | **Not reused.** | It is a mutable mirror, and backupctl needs immutable snapshots. It writes the manifest after the copy (line 85) with `open("w")`, which is not atomic. **Verified:** a corrupt manifest makes the next run raise `JSONDecodeError` at line 79. The silent-skip defect above also means the manifest records files that were never copied. |
| `synccli.collect_stale` (synccli.py:45-59) | **Not used.** | No caller needs it. |
| `synccli.main` (synccli.py:90-99) | **Not used.** | Backupctl has its own CLI with a JSON report. |
| `snaputil.prune_snapshots` (snaputil.py:23-36) | **Overridden.** | **Verified:** `keep=0` deletes every snapshot (line 31: `len(names) <= 0` is false, so `doomed` becomes the full list). Line 35 is a plain `rmtree`, which can leave a half-deleted `snap-*` directory that `list_snapshots` then reports as a snapshot. It also ignores reader locks. The override rejects `K < 1`, renames before deleting, and honors reader locks. |
| `snaputil.safe_snapshot_path` (snaputil.py:54-63) | **Overridden for restore.** | **Verified:** `safe_snapshot_path('/root', 'snap-x', '../../etc/passwd')` returns `/root/snap-x/../../etc/passwd`, and `'/etc/passwd'` returns `/etc/passwd`. `normpath` keeps leading `..` and `os.path.join` discards the prefix for absolute paths. The docstring's claim is false. Restore must reject absolute paths, `..` components, and NUL bytes before joining. |
| `snaputil.is_stale` (snaputil.py:66-73) | **Not used.** | It compares directory mtime. That changes only when entries are added or removed in that directory, not when a file inside is rewritten, so it says nothing about whether a snapshot is complete. |

The existing test suite (`test_synccli.py`, 6 tests) passes today
(`python3 -m unittest`). It covers none of the failure modes above. New tests
are listed in section 13.

---

## 4. On-disk layout

```
backup_root/
  .backupctl.lock              writer lock (flock EX|NB); content: pid, runid
  .locks/
    snap-<name>.lock           reader lock per snapshot (flock SH by readers)
  .inprogress-<runid>/         staging for the one run that holds the writer lock
    .journal.jsonl             header line + one line per finished file
    <label>/...                copied or hardlinked files, directories, symlinks
    .backupctl-index.json      written last, before publish
  .trash-<name>/               snapshot being deleted (never listed)
  .reports/<runid>.json        report of a run that did not publish
  snap-YYYYMMDD-HHMMSS-NN/     published, immutable snapshot
    <label>/...
    .backupctl-index.json
```

- Snapshot names follow the existing format (snaputil.py:9-12). The timestamp
  is UTC, so lexicographic order is chronological. `NN` is the smallest
  sequence number that makes the name sort after the newest existing
  snapshot. Under the writer lock this is unique. If the clock moves
  backwards, the name still sorts after the newest existing snapshot.
- `<label>` is the configured name of a source directory. Labels must be
  unique and must not start with `.`.
- The index holds, for each label: the status (`ok`, or `missing` when the
  configured source does not exist), the entries (path, type, size, mode,
  sha256 for regular files, target for symlinks, the racy flag from
  section 7, and the recorded time), the skipped entries with reasons, the
  reference snapshot used, and the start and end times.
- Only `copied` and `linked` entries are written as `files`. Skipped entries
  go in a separate `skipped` list. An index therefore never promises a file
  the snapshot does not contain.

---

## 5. Run protocol

1. **Lock.** `flock(LOCK_EX | LOCK_NB)` on `.backupctl.lock`. If it fails, exit
   75 with the pid from the lock file.
2. **Sweep** (under the lock, so no live writer exists):
   - delete every `.trash-*` directory;
   - for each `.inprogress-*` directory, resume it if section 6 says so,
     otherwise delete it;
   - delete each `.locks/snap-X.lock` whose snapshot directory is gone,
     using the inode re-check in section 5.1.
3. **Reference.** Take the newest snapshot whose index parses and has
   `status: complete`. It may be absent (first run).
4. **Stage.** Create `.inprogress-<runid>/` and write the journal header
   (`runid`, `reference`, `config_fingerprint`, `started_ns`).
5. **Copy**, for each label in config order:
   - walk with the overridden `scan_files` (include hidden, record symlinks,
     `onerror` recorded as a skipped directory);
   - for each entry, `lstat` and build the key `(type, size, mode, mtime_ns,
     ctime_ns, ino)`, or `(symlink, target)` for links;
   - if the reference has the same path with the same key and the entry is not
     racy, `os.link` it from the reference snapshot. If linking fails, fall back
     to copying;
   - if the reference entry is racy, read the source, hash it, and compare the
     hash to the reference's sha256. Hardlink on match, copy otherwise;
   - otherwise copy in 1 MiB chunks while hashing, `fsync` the file, then
     `fstat` the source. If the stat changed during the read, retry up to 2
     times, then skip with reason `unstable`;
   - append one journal line per finished file (`flush` only, see section 6).
6. **Index.** Write `.backupctl-index.json.tmp`, `fsync` it, and `rename` it to
   `.backupctl-index.json`. `fsync` the staging directory.
7. **Verify.** For each file in the index, `lstat` the staged path and check
   that its size matches. Any mismatch fails the run (exit 1) and nothing is
   published. The check is O(F) stats and is cheap compared with the copy.
8. **Publish.** `os.rename(.inprogress-<runid>, snap-<name>)`, then `fsync`
   the backup root. The snapshot exists from this instant, and it is complete.
9. **Retain** (section 9).
10. **Exit.** The lock is released by the kernel on exit. No explicit cleanup
    is required.

### 5.1 Inode re-check for lock files

A reader opens `.locks/snap-X.lock`, takes `LOCK_SH`, and then compares
`fstat(fd).st_ino` with `stat(path).st_ino`. If they differ, the file was
unlinked and recreated during the race, so the reader retries. This keeps a
reader from locking an unlinked file while retention is deleting that
snapshot.

---

## 6. Crash recovery

The failure modes are: a killed process, a sleeping laptop, Ctrl-C, or a
power loss in the middle of step 5.

**Core rule.** A `snap-*` directory exists only if the whole run completed,
because the publish rename (step 8) is the last thing that happens. No
interrupted run can produce a visible incomplete snapshot. This also covers
the index: the index is written before publish, so a published snapshot
always has a complete index. The only source of an unusable `snap-*` is
damage after publish (disk fault, manual edit). Such a directory is reported
as `unusable`. It does not count toward retention, and it is never deleted
automatically.

**Discard versus resume.** Every `.inprogress-*` directory is an orphan at the
start of a run, because the writer lock proves no other run is alive. The
sweep decides as follows.

- **Index.** Any `.backupctl-index.json` in an orphan is discarded, whether or
  not it parses. It is never read as a source of truth. The index is
  re-derived from the journal and from the tree during the next run.
- **Journal.** Resume only if the header's `config_fingerprint` matches the
  current configuration and `reference` equals the current reference snapshot.
  Otherwise discard the whole directory. The header is the first line; a
  truncated or unparsable trailing line is ignored, and that file is copied
  again.
- **Files listed in the journal.** A journaled file is reused only if all of
  these hold: the current `lstat` key equals the journaled key; the staged file
  exists; and rehashing the staged file gives the journaled sha256. Anything
  else is copied again. This is why the journal does not need an fsync per
  line: a line that is lost or points at bytes that never reached disk causes
  a copy, never a wrong reuse.
- **Partial files** not in the journal are deleted.
- **Trash** directories from an interrupted retention are deleted by the sweep.

**Progress guarantee.** Each run starts from the newest published snapshot,
never from partial state. A run that dies always leaves a usable reference for
the next run. Resume means a dead initial backup keeps its finished files, so
a long first backup converges over several interrupted runs. Work lost is at
most the file being copied when the process died.

**Reporting.** The run report lists, in this order: the sweep actions
(discarded, resumed, deleted trash, deleted stale locks), the reference used,
and the counts of copied, linked, reused-from-journal, skipped (with reasons),
and deleted-by-retention snapshots. The report goes to stdout as JSON and is
also stored in the index of a published snapshot. A run that does not publish
writes it to `.reports/<runid>.json`.

---

## 7. Change detection: granularity and what it misses

**Granularity.** Each file (and each symlink) is a unit. A file is unchanged
when its key matches the reference entry's key:

- key = `(size, mtime_ns, ctime_ns, ino, mode)`
- symlink key = `(target)`

`ctime` is set by the kernel on every inode change, including writes, so
restoring an old mtime with `touch -r` does not hide an edit. `ino` catches
atomic-replace editors that write a new file and rename it over the old one.

**Racy entries.** Some timestamp granularities are coarser than a second
(HFS+ 1 s, FAT 2 s). A file written again within the same tick as the previous
`lstat` can keep the same key. To guard against this, an entry is marked
`racy` at record time when `max(mtime_ns, ctime_ns) >= lstat_ns - 2e9`. A racy
entry is never trusted by key. The next run reads and hashes it, and reuses it
only if the hash matches. The cost is paid only by files modified in the
2 seconds before their own snapshot.

**What the design still misses.**

1. A content change that keeps size, mtime, ctime and inode all identical.
   On a local POSIX filesystem with nanosecond timestamps this is not possible
   through normal write paths. It is not ruled out for writes through `mmap`
   that have not yet updated the metadata. The default run does not detect
   this case.
2. A reference snapshot whose stored bytes have rotted. Hardlinking propagates
   the damage. `backupctl verify` rehashes every file of a snapshot against
   its index and is the check for this case. It is not run by default.
3. Changes in owner, ACL, or xattr. They are not recorded, so they are not
   detected. Mode changes are detected because mode is part of the key.

---

## 8. Vanished, unreadable, and unstable files

Every per-file outcome is one of: `copied`, `linked`, `reused` (from the
journal), or one of these skips:

| Event | Where it is detected | Result |
|---|---|---|
| Vanished before stat | `lstat` raises `FileNotFoundError` | Skipped, reason `vanished`. The run continues. |
| Vanished during the walk | `onerror` callback | Skipped directory, reason `vanished_dir`. |
| Unreadable (EACCES, EIO, ...) | `open` or `read` raises `OSError` | Partial staged file deleted. Skipped, reason `unreadable:<errno>`. |
| Changed during copy | `fstat` after read differs from the pre-read `lstat` | Staged file deleted and copied again, up to 2 retries. Then skipped, reason `unstable`. |
| Configured source root missing | `lstat` of the label root fails | Label status `missing`. Run continues. |

A skipped file is not in the snapshot's `files`. It appears in `skipped`, and
the run exits 3. A torn copy is never published as a file: the `unstable` case
deletes the staged copy rather than keeping it.

**Same behavior for scheduler and person.** The behavior depends only on the
arguments, never on whether stdin or stdout is a terminal. There are no
prompts, no color, and no progress output unless `--progress` is passed
explicitly. The JSON report is identical for both callers.

**Exit codes.** 0 complete with no skips. 3 published with skips or missing
sources. 75 busy (another run holds the writer lock). 2 configuration error.
1 failed, nothing published.

---

## 9. Retention

- Default K = 14 (`--keep K`). K < 1 is rejected, which overrides the
  `keep=0` defect in `snaputil.prune_snapshots`.
- Retention runs only after a successful publish, under the writer lock.
- `verified` = published snapshots whose index parses and has
  `status: complete`. `keep` = the newest K entries of `verified`.
- Candidates = `verified` minus `keep`, oldest first. Unverified (`unusable`)
  directories are never candidates.
- Deletion of one candidate:
  1. try `flock(LOCK_EX | LOCK_NB)` on `.locks/<name>.lock`. If it is held by a
     reader, defer this candidate and report it. Retention does not wait;
  2. `rename(snap-X, .trash-X)`. From this instant the snapshot is no longer
     listed;
  3. `rmtree(.trash-X)`, then release the lock. A reader who acquires the
     shared lock afterwards finds the directory gone and fails cleanly. A
     reader who holds the lock before step 1 keeps retention from starting.
- A snapshot's files are hardlinks into its neighbors where unchanged. There
  is no dependency chain: each snapshot is a full tree, so deleting one only
  unlinks its names. Data is freed when the last name is removed.
- The newest verified snapshot is never a candidate, so a successful run
  always leaves at least one usable snapshot.

---

## 10. Performance budget: initial full backup of ~1 GiB / ~30,000 files

**Budget: 60 s wall-clock on the reference host (Apple M3 Max, APFS, warm
page cache) for the first full backup of a 1.0 GiB, 30,000-file tree.**

Derivation from measurements on this machine:

| Component | Measured / derived | Source |
|---|---|---|
| Existing `synccli.sync`, full copy, no fsync | 8.28 s | measured: `synccli.sync` on the 1 GiB / 30,000-file tree |
| Copy with a per-file `fsync` (`os.fsync`) | 11.15 s | measured: loop of read, write, fsync over all 30,000 files |
| Hash in-stream (sha256, read pass) | about 2.75 s per GiB | extrapolated: 0.28 s for the first 3,000 files, times 10 |
| `lstat` walk and key build | 0.31 s | measured: `synccli.build_manifest` on 30,000 files |
| Index write and staged-file verify | about 0.3 s | estimate: 30,000 entries, one JSON write and 30,000 `lstat` calls |
| Journal writes | negligible | flush only, no fsync per line |
| **Predicted design total** | **about 15 s** | sum of the rows above |

The 60 s budget is 4 times the predicted total. The margin is for variation
in the host and for the unmeasured costs listed below. The budget is not a
claim about other hardware. On rotating disks or a cold cache, 30,000 small
file creates will dominate and the number must be re-measured. That
measurement is an acceptance criterion (section 13).

Incremental run with no changes (measured, existing code): 0.38 s for 30,000
files, so an unchanged run on this host costs about 13 us per file.

---

## 11. Scaling bounds

Notation: N = configured source directories; F = total files and symlinks
across all sources; B = total bytes of regular files across all sources;
C = bytes changed since the reference snapshot; K = retention count.

| Quantity | Bound | Notes |
|---|---|---|
| Per-run `lstat` work | F stats, about 10 us each (measured: 0.31 s for 30,000) | Linear in F. N adds no extra passes. |
| Per-run copy work (first run) | B bytes read, written, and hashed | Measured budget in section 10. |
| Per-run copy work (later runs) | C bytes, plus the racy entries, which are read and hashed | Racy entries are those modified in the 2 s before their own snapshot. |
| Per-run memory | about 400 bytes per entry (measured: 12.0 MB for 30,000 entries, via `tracemalloc` on `build_manifest`), so about 400 x F bytes | Copy buffer is 1 MiB, constant. Copy memory does not scale with file size, which the existing `copy_file` (synccli.py:67) does. |
| Index size per snapshot | F x about 200 bytes JSON | 200 bytes is an estimate, not measured. |
| Disk: unique data | at most B + sum of C_i over the K retained runs, which is at most (K + 1) x B | Upper bound, reached only when every file changes every run. |
| Disk: indices | at most K x F x 200 bytes | Estimate. |
| Lock files | K + 1 at most | Bounded by retention. |
| Snapshots visible | K (plus unusable ones, which are reported) | Bounded by retention. |
| Lock contention | one writer, regardless of N | N does not add lock domains. |

So: work per run grows with F (and with C on incremental runs), memory grows
with F, and disk grows with K x (B or the changed bytes) plus K x F x 200 bytes
of indices. N has no effect beyond the sum it adds to F.

For the "few dozen directories" horizon, F is unknown. The formulas above
still hold; the budget in section 10 is the only numeric target stated.

---

## 12. Interfaces

```
backupctl run    --config CFG [--keep K] [--verify]   # exit codes in section 8
backupctl list                                         # usable snapshots, oldest first
backupctl verify SNAPSHOT                              # rehash against index
```

Config: a JSON file mapping labels to source paths, plus `keep`, `excludes`,
and the backup root. The config fingerprint is the SHA-256 of its canonical
form, which is stored in the journal header.

Restore is separate tooling. It takes the reader lock described in section
5.1, and it validates every stored path with the new check that replaces
`safe_snapshot_path`. It never writes into a `snap-*` directory.

---

## 13. Tests and acceptance criteria

New tests in `test_backupctl.py`, alongside the existing six:

1. Two concurrent `run` calls: one publishes, the other exits 75 and writes
   nothing.
2. Kill the run at each step boundary (after stage, midway through copy,
   after index, before publish): no `snap-*` appears; the next run resumes or
   discards, and completes.
3. Corrupt or truncated `.backupctl-index.json` and `.journal.jsonl` inside an
   `.inprogress-*` directory: the run discards or partially reuses them as
   section 6 specifies, and never reads them as truth.
4. File mode 000 (copy path), file removed between walk and `lstat`, file
   modified during copy: each produces the outcome in section 8 and exit 3.
5. `keep=0` is rejected; `prune` with a reader lock held defers the candidate.
6. A reader holding the shared lock during retention: the snapshot survives,
   and the reader completes.
7. `safe_snapshot_path` replacement rejects `../`, absolute, and NUL paths.
8. Racy entries: write a file within 2 s before its snapshot and modify it
   without changing its size, then confirm the next run copies it.
9. Budget: the initial backup of the 1.0 GiB / 30,000-file fixture completes in
   at most 60 s on the reference host (section 10). Also measure on the
   deployment storage, and record the result in the design.

---

## 14. Known limitations

- Single host. No remote or networked backup root.
- Owners, ACLs, and xattrs are not preserved. Source hardlinks are not
  preserved as links.
- The default run does not rehash reference snapshots (section 7, item 2).
- Unusable snapshots (external damage) are reported and kept until a human
  removes them.
- The 60 s budget is measured on one host with a warm cache. Other storage
  must be measured before any claim is made about it.

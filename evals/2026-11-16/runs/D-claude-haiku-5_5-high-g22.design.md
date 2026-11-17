# DESIGN-d1: `backupctl`

Status: design only. No code in this repo was changed. Probe scripts used for
the measurements live outside the repo (`.../T/opencode/probe/`).

Measurement host: this laptop, macOS (Darwin), APFS on `/dev/disk3s5`,
Python 3.10.11, 14 logical CPUs, 38.6 GB RAM. All timings are warm-cache
unless stated otherwise.

## 1. Summary

- A **run** covers all N configured source directories and publishes one
  **snapshot**: an immutable directory tree under the backup root, named
  `snap-<UTC>-<ordinal>`. A snapshot appears under its final name only by an
  atomic `rename()` of a fully written and fsynced staging directory.
- **Unchanged files** are hardlinked from the newest valid snapshot. They are
  not re-read or re-copied. Change detection is per file, on lstat metadata
  (`dev, ino, size, mtime_ns, ctime_ns, mode`), with a racy-timestamp guard.
- **One global lock** (`flock` on `BACKUP_ROOT/.lock`) serializes runs, pruning
  and recovery. Readers (restore) take a per-snapshot **lease** (`flock`
  shared). Kernel-released `flock` means a killed process never leaves a stale
  lock.
- **Recovery** discards every staging directory left by a dead run. It never
  repairs an index in place. The tree is the source of truth. The previous
  snapshot is only a reuse hint, and it is used only after validation.
- **Vanished or unreadable source files** are left out of the snapshot and
  listed in its `meta.json` under `skipped`. The run exits 3 and reports them.
  The same rule applies whether a person or the scheduler started the run.
- **Retention** keeps the newest K valid snapshots, K >= 1. Pruning runs only
  after a new snapshot is published, and it renames a snapshot away before
  deleting it, skipping any snapshot that a reader holds.
- **Budget:** initial full backup of ~1 GB / ~30k files <= 120 s wall-clock on
  this laptop. Measured steady state is 11-17 s (section 9).
- **Honest cost finding:** hardlink reuse costs about 0.33 ms per unchanged
  file on this machine (measured). A no-change run over 30k files therefore
  takes about 10.5 s, not 0.3 s. The savings are in bytes written and disk
  used, not in wall-clock. Section 9.3 gives the trigger for switching to a
  content store.

## 2. Grounding: what is reused, what is overridden

Line numbers refer to the files in this directory as they stand today.

### 2.1 `synccli.py`

| Item | Location | Decision | Reason |
|---|---|---|---|
| `scan_files` | synccli.py:10-19 | **Override** with `walk_tree` | Line 14 prunes every directory whose name starts with `.`. Verified: a `.git/` directory is dropped, a `.env` file is kept. The walk also never descends into a symlinked directory: `os.walk` lists it in `dirnames`, and it never reaches `filenames`, so it vanishes silently. Verified: `scan_files` on a tree with `linkdir -> realdir` returns `['file.txt', 'linkfile', 'realdir/x']`, with no `linkdir`. A backup must include hidden paths and must record symlinks, not drop them. |
| `file_state` | synccli.py:22-25 | **Override** with `lstat`-based `record_state` | `os.stat` follows symlinks, so a symlink would be stored as its target's content. `st_mtime` is a float: at the current epoch it resolves to about 0.24 us, and the measured round-trip error is -16 ns. It also has no `ctime`, and `ctime` is the field that catches a restored-mtime edit (section 5). Verified: an edit followed by `os.utime()` to the old mtime changes `ctime_ns` while keeping `mtime_ns` and `ino`. |
| `build_manifest` | synccli.py:28-33 | **Override** | Line 32 calls `file_state` with no error handling. Verified: a path listed but already deleted raises `FileNotFoundError` and aborts the whole manifest. Per-entry handling is required (section 8). |
| `changed_files` | synccli.py:36-42 | **Reuse as-is** | It is a generic dict-state comparison. Verified by reading: it reports new and changed keys and does not need the state to be a particular shape. It does not report removed keys, and this is fine: a snapshot is a full image, so a removed file is simply not linked into the new snapshot. |
| `copy_file` | synccli.py:62-69 | **Override** with `copy_entry` | Lines 68-69 swallow `OSError` with `pass`, and the comment says "next pass will retry". The caller still records the file as synced (`sync` writes the full source manifest at lines 85-86). Verified: a `chmod 000` source file is reported as copied, is absent from the destination, and is never copied on the next run. Line 67 also reads the whole file into memory (`fsrc.read()`), so memory grows with the largest file. |
| `sync` | synccli.py:72-87 | **Not used** | It mutates one destination in place, so there are no immutable snapshots. Its manifest write is non-atomic (lines 85-86). Verified: a truncated manifest makes the next run raise `JSONDecodeError` at line 79. Verified: a file deleted from the source is never removed from the destination. |
| `collect_stale` | synccli.py:45-59 | **Not used** | Only the tests call it. |
| `MANIFEST_NAME` | synccli.py:7 | **Not used** | Snapshot metadata lives under `.snapshot/` (section 3). |
| `main` | synccli.py:90-99 | **Not used** | |
| `test_synccli.py` | test_synccli.py:8-51 | **Unchanged** | Still passes (`python3 -m unittest`: 6 tests OK). backupctl adds its own test file. |

### 2.2 `snaputil.py`

| Item | Location | Decision | Reason |
|---|---|---|---|
| `list_snapshots` | snaputil.py:8-20 | **Reuse** | Enumerates `snap-*` directories and ignores everything else. Staging and trash live under dot-prefixed names, so they are never listed. Note: it sorts by full name (line 20). Names are timestamp-major, so order is wrong if the clock moves backwards. Enumeration is fine; retention ordering is not (below). |
| `prune_snapshots` | snaputil.py:23-36 | **Override** with `retention.prune` | (a) Line 31 counts every `snap-*` directory toward `keep`, including invalid ones. (b) Line 33 orders by name, so a backward clock step makes the newest snapshot the "oldest" and it gets deleted. (c) Line 35 `rmtree`s in place, which breaks any concurrent reader. |
| `snapshot_disk_usage` | snaputil.py:39-51 | **Override** with `snapshot_bytes` | Line 50 calls `os.stat`, which follows symlinks. Verified: a dangling symlink raises `FileNotFoundError`. It also counts each hardlinked inode once per snapshot, so the total overstates disk use. The override counts each `(dev, ino)` once across the root, using `lstat`. |
| `safe_snapshot_path` | snaputil.py:54-63 | **Override and fix before restore uses it** | The docstring says the result cannot escape the snapshot. Verified: `normpath("../../etc/passwd")` keeps its leading `..`, so the result is `/b/snap-x/../../etc/passwd`. Verified: an absolute `rel_path` makes `os.path.join` discard the prefix, so the result is `/etc/passwd`. Restore needs a checked version (section 11). |
| `is_stale` | snaputil.py:66-73 | **Not used** | The docstring says a directory whose mtime equals `ref_epoch` is not stale. Verified: the code returns True for equality (`<=`). It also uses directory mtime, which changes whenever an entry is added or removed. |
| `main` | snaputil.py:76-88 | **Not used** | |

No other file in this directory is used.

## 3. On-disk layout

```
BACKUP_ROOT/                         (must be on the same volume as all sources)
  .lock                              flock target: runs, prune, recovery (global)
  .staging/run-<ordinal>-<pid>/      in-progress run; never visible to readers
  .trash/<name>.<pid>.<rand>/        snapshot or staging dir renamed away, to delete
  .leases/<snap-name>                empty lock files: readers LOCK_SH, prune LOCK_EX
  snap-<YYYYMMDD-HHMMSS>-<ordinal>/  published snapshot, immutable
    .snapshot/meta.json              see below
    .snapshot/files.jsonl            one record per entry, sorted by (source, relpath)
    <source-id>/...                  the copied tree: files, symlinks, dirs
```

The config lives outside the root, in a file passed with `--config`:
`backup_root`, `keep` (K), and `sources: [{id, path}]`. Each `id` matches
`[a-z0-9-]+` and is unique. The config is rejected (exit 2) if the backup root
is inside any source path or any source is inside the backup root, checked on
`realpath`. Without that check, backups would recurse into themselves.

Snapshot names: `<YYYYMMDD-HHMMSS>` is the UTC start time, for display only.
`<ordinal>` is a zero-padded integer, `1 + max(ordinals of all snap-* names)`,
computed under the global lock. Ordering for retention and baseline selection
uses the ordinal alone, never the timestamp. This deliberately extends the
`-NN` example in `snaputil.py:12`; `list_snapshots` still matches it because
it matches by prefix only.

`meta.json` fields: `schema`, `ordinal`, `created_utc`, `sources` (per source:
`id`, `scan_started_ns`, `status`), `counts` (new, changed, linked, copied,
skipped), `bytes_copied`, `skipped` (list of `{source, path, reason}`),
`manifest_sha256` (sha256 of `files.jsonl`), `files` (entry count).

`files.jsonl` record fields, one JSON object per line:
`s` (source id), `p` (relpath), `k` (`f` file, `l` symlink, `d` directory),
`dev`, `ino`, `size`, `mode`, `mtime_ns`, `ctime_ns` (source-side lstat),
`sha256` (regular files; inherited from the baseline for linked files), and
`target` (symlinks).

## 4. Run algorithm

All steps run under the global lock unless marked otherwise.

0. **Config and preconditions** (no lock needed). Parse the config and check
   the realpath rules in section 3. Each source must exist and be a directory.
   If one does not, exit 2 and touch nothing. Config errors and usage errors
   also exit 2.
1. **Lock.** `flock(LOCK_EX | LOCK_NB)` on `.lock`. If it is busy, print the
   holder's pid (written into the lock file) and exit 75 (`EX_TEMPFAIL`).
   `--wait SECONDS` (default 0) polls until the timeout. The scheduler should
   use `--wait` only if it wants queuing; a person gets the immediate answer.
2. **Recovery** (section 7): delete `.staging/*` and `.trash/*`, delete
   `.leases/*` that have no matching snapshot, and list invalid snapshots.
3. **Baseline:** the newest snapshot (by ordinal) whose `meta.json` parses,
   whose `schema` is known, and whose `files.jsonl` matches `manifest_sha256`.
   If there is none, the baseline is empty and the run is a full copy.
4. **Staging:** create `.staging/run-<ordinal>-<pid>/<source-id>/` for each
   source.
5. **Per source, in config order:**
   1. Record `scan_started_ns = time.time_ns()`.
   2. Walk the tree with `walk_tree`: recursive `os.scandir`, names sorted,
      `lstat` on every entry, no pruning of dot-names, symlinks not followed.
      Entries that vanish during the walk are recorded as `skipped/vanished`.
   3. Build the source state dict `new` for this source.
   4. Get the baseline state dict `old` for this source, read from the
      baseline's `files.jsonl`.
   5. `changed = changed_files(old, new)` (reused as-is, synccli.py:36-42).
      Then apply the racy guard (section 5): an unchanged entry whose
      `max(mtime_ns, ctime_ns) >= baseline.scan_started_ns - 2 s` is moved to
      `changed`.
   6. For each **unchanged** entry: if the baseline file exists and its size
      matches the record, `os.link` it into staging and copy its `sha256` from
      the baseline. Otherwise treat it as changed. A failed link is
      reported and falls back to a copy.
   7. For each **changed** entry: `copy_entry` (section 8). Directories are
      created with `os.mkdir`. Symlinks are re-created with `os.symlink`.
   8. Write `files.jsonl` records for this source, in relpath order.
6. **Publish gate.** For every file and symlink record, `lstat` the staged
   path and check that it exists and that its size matches. Any mismatch
   aborts the run with exit 1 and nothing is published. The index must never
   promise an entry the snapshot does not contain.
7. **Write metadata.** Write `files.jsonl`, then `meta.json` with
   `manifest_sha256`. Fsync both files, then fsync every staged directory,
   deepest first. On macOS, durability against power loss needs
   `fcntl(F_FULLFSYNC)`, not `os.fsync`. See section 13, open decision 3.
8. **Publish.** Create the lease file `.leases/<name>`, then
   `rename(.staging/run-..., snap-...)`, then fsync `BACKUP_ROOT`. The lease is
   created before the rename so that a reader who can see the name can always
   lease it.
9. **Retention** (section 10). Runs only after the publish succeeds.
10. **Report.** Print per-source counts (new, changed, linked, copied,
    skipped), bytes copied, copy throughput (bytes / seconds), the baseline
    used, every skipped entry with its reason, every pruned or deferred
    snapshot, and every invalid snapshot found. The output is identical
    whether the run came from the scheduler or a person.
11. **Exit codes.** 0: published, nothing skipped. 3: published, with skipped
    entries. 1: run failed, nothing published. 2: config or precondition error.
    75: lock busy.

## 5. Change detection: granularity and what it misses

**Granularity.** The unit is one regular file, symlink, or directory entry.
The decision uses only the `lstat` tuple `(dev, ino, size, mtime_ns,
ctime_ns, mode)`, compared with the same tuple stored in the baseline.
Unchanged files are never read. Directory mtimes are not used, because they
change on any add or remove and say nothing about a file's content. Content
hashes are not used for change detection.

**Why `ctime_ns` is in the tuple.** `ctime` is set by the kernel on every
metadata or content change, and user space cannot set it. Verified: after an
edit followed by `os.utime()` restoring the old mtime, `mtime_ns` and `ino`
are unchanged but `ctime_ns` moves. The existing `(size, mtime)` state
(synccli.py:25) misses this edit. A same-size edit with a restored mtime
leaves `sync` with stale content (verified: the destination keeps `AAAA`
after the source became `BBBB`).

**Racy guard.** Two timestamps can be equal even if the content changed, when
the file was modified inside the same timestamp granule as the baseline's
scan. The guard treats any unchanged entry as changed when
`max(mtime_ns, ctime_ns) >= scan_started_ns - 2 s`. The 2 s margin covers
coarse filesystem timestamps (HFS+ has 1 s, FAT has 2 s). The guard only
causes extra copies, never missed ones.

**What the design still misses.**
1. Changes made by a process with privilege to set `ctime` (for example by
   setting the system clock backwards, then editing a file). The tuple can
   match the baseline.
2. Changes on filesystems whose timestamps are coarse or not updated across
   the network (FAT and exFAT, NFS or SMB with attribute caching). Sources must
   be on local APFS or ext4-class volumes. A `--rehash` option reads every
   regular file on each run instead. Its cost is the total source bytes per
   run. It is not the default.
3. Extended attributes and ACLs are not captured in v1. Their changes are
   neither detected nor saved. Mode bits are captured and restored.
4. Symlinks are stored as links and not followed. Edits to a symlink's target
   file are backed up only if the target is also inside a configured source.
5. Entries inside a source that is itself a symlink are not reached. The
   source root must be a real directory.

## 6. Concurrency

| Pair of actors | Mechanism | Outcome |
|---|---|---|
| run vs run (scheduler vs person) | `flock(LOCK_EX)` on `.lock` | Second run exits 75, or waits up to `--wait`. Nothing is shared. |
| run vs prune | Same global lock. Prune runs inside a run, after publish. | Serialized. |
| run vs restore | Restore holds `LOCK_SH` on the snapshot's lease. A run only reads baseline snapshots and never writes to a published one. | Both read. Prune is the only deleter, and it respects leases (below). |
| restore vs prune | Prune takes `LOCK_EX|LOCK_NB` on the lease. If that fails, prune defers this snapshot and reports it. Otherwise it renames the snapshot to `.trash`, unlinks the lease, releases the lock, then deletes the trash. | Restore either holds the lease (prune defers) or finds the snapshot gone and fails cleanly. |
| restore vs publish | Restore only sees snapshots by their final name. Staging is invisible. | No partial snapshot can be opened. |
| restore lease race | A reader opens `.leases/<name>` (fails with ENOENT if the snapshot is gone), takes `LOCK_SH`, then re-checks that the snapshot directory exists. | A reader that loses a race to a just-finished prune gets an error and retries after re-listing. |

**Process death at any point.** `flock` is released by the kernel when the
process exits, so the lock never goes stale. Leftovers are cleaned up in
recovery (section 7). Staging is never published, so a dead run cannot leave a
snapshot that looks complete. A rename is atomic, so a snapshot is either
fully present under its final name or absent.

**Laptop sleep.** The lock and file descriptors survive sleep. The run resumes
when the machine wakes. The design relies on no timer.

**Ctrl-C.** A SIGINT handler removes the staging directory on a best-effort
basis and exits 130. Recovery removes it anyway if the handler did not run.

## 7. Recovery: dead runs and corrupt indexes

The index is never repaired in place. There are three cases.

1. **Interrupted run.** Its `.staging/run-*` directory is deleted under the
   lock, and the report lists each one by name and file count. Staging is
   discarded entirely and never resumed in v1. Cost: the work of that run is
   lost. For the initial full backup of ~1 GB that is at most one budget's
   worth (section 9).
2. **Half-written index in staging.** Staging is never read, so a corrupt
   `files.jsonl` or `meta.json` there has no effect. Its directory is discarded
   as in case 1.
3. **Corrupt published snapshot** (for example media damage after publish,
   which can never come from a dead run). `meta.json` does not parse, the
   schema is unknown, or `files.jsonl` fails `manifest_sha256`. The snapshot
   is **not deleted** and **not counted** toward K. It is **not used as a
   baseline**. The report names it and the reason. Deleting user data
   automatically is not acceptable. The `--delete-invalid NAME` command is
   a manual action, not part of the run.

**Baseline fallback.** If the newest valid snapshot's own file is missing or
has the wrong size, that one file is copied instead of linked, and the report
counts it as a baseline miss. A valid older snapshot can also serve as the
baseline. This is correct, not just convenient: a file unchanged since that
older snapshot still has the right content in it.

**Re-derived, not trusted.** The new index is always rebuilt from the live
tree. The only fields taken from the old index are `sha256` for files that
passed the change test and link check. Those fields are valid because the
source state matched exactly.

## 8. Source files that vanish or are unreadable

The rule is the same for scheduler and person runs. The snapshot contains
exactly the entries that were copied or linked successfully. `meta.json` lists
every entry that was not, with a reason.

| Event | When | Result |
|---|---|---|
| Vanished before lstat | Listed, then deleted | Skipped as `vanished`. Not in `files.jsonl`. |
| Vanished at open | `open()` gives ENOENT | Skipped as `vanished`. |
| Unreadable | `open()` or `read()` gives EACCES or EIO | Partial staging file removed. Skipped as `unreadable`. |
| Changing during copy | `fstat` before and after the read differ in `(size, mtime_ns, ctime_ns)` | Retried up to 2 times. If still changing, skipped as `changing`. The snapshot never contains a file the run saw change mid-copy. |
| Directory vanishes mid-walk | Its entries are no longer listed | Skipped as `vanished`. |
| A configured source root is missing at start | Step 0 | Exit 2, nothing touched. |
| A configured source root disappears during the run | Step 5 | Exit 1, nothing published. A snapshot missing a whole source would look like a deletion. |

A published snapshot with skips counts as valid. It is the best image
available, and the run exits 3 so the scheduler can alert. The skipped files
are not in the baseline, so the next run classifies them as new and tries
again.

**Consistency scope.** A snapshot is not a point-in-time image of the whole
tree. Each file is copied at its own moment. Each file is internally consistent
(see the `changing` rule above), but two files can be copied at different
moments. Filesystem-level atomic snapshots (APFS local snapshots) would be the
way to get whole-tree atomicity. They are platform-specific and out of scope.

## 9. Performance

### 9.1 Initial full backup budget

**Budget: 120 s wall-clock** for the initial full backup of ~1.0 GB in 30,000
files (the probe fixture: 300 directories of 100 files each), on this laptop
class.

**Measurements** (fixture: 300 directories x 100 files x 33,333 B = 999,990,000
bytes, 30,000 files; warm cache):

| Component | Measured | Source |
|---|---|---|
| `scan_files` (30k entries) | 0.236, 0.241, 0.245 s | bench.py, 3 runs |
| `build_manifest` (scan + stat) | 0.294, 0.316, 0.318 s | bench.py, 3 runs |
| `synccli.sync` initial copy (whole-file read) | 7.71 s, 7.07 s | bench.py, 2 runs |
| `synccli.sync` no-op | 0.41 s | bench.py |
| chunked copy, temp + rename, no fsync | 9.40 s, 9.70 s | bench2.py, 2 runs |
| chunked copy, temp + rename, `os.fsync` | 9.53 s, 9.25 s | bench2.py, 2 runs |
| `sha256` read-only pass over 1 GB | 2.37, 2.39, 2.57 s | bench3.py |
| copy + sha256 + fsync + rename (design's path) | 11.13 s, 17.06 s | bench3.py, 2 runs |
| Outlier: chunked copy run right after generating the tree | 44.03 s, 30.59 s | bench2.py, first batch |

The outliers are consistent with dirty pages from the generated fixture being
flushed during the timed copy. Steady-state end-to-end throughput for the
design's path is 1.0 GB / 11.1 s = 90 MB/s, to 1.0 GB / 17.1 s = 59 MB/s.

**Derivation of the 120 s budget.** 120 s is about 2.7 times the slowest
observed outlier (44 s) and about 7 to 11 times the steady state (11-17 s).
Equivalently, the budget requires at least 8.3 MB/s end-to-end. That floor is
about 7 to 11 times below the measured 59-90 MB/s. The margin is there because
only an SSD was measured.

**Not measured:** external or network backup targets, `F_FULLFSYNC` (section
13, open decision 3), and fresh-boot cold caches. The run report prints the
measured throughput for each run, so the budget can be checked in the field.

### 9.2 Per-run costs

Let N = number of sources, F_i = entries in source i, F = sum of F_i, B =
total source bytes, U = unchanged entries in the run, and D = bytes of
changed files.

| Cost | Bound | Measured constant |
|---|---|---|
| Walk and lstat | F stats | about 8 us per entry (0.24 s / 30k) |
| Link unchanged files | U links | **0.33 ms per link** (30,000 links: 9.98, 10.40, 10.35 s) |
| Copy changed files | D bytes read, hashed, written, fsynced | 59-90 MB/s end-to-end |
| Write `files.jsonl` | F records | Each record is about len(relpath) + 130 B. The 130 B is an estimate from the fixed JSON field names and the 64-character sha256. It has not been measured. |

**No-change run over 30k files:** 0.3 s (walk) + 10.2 s (links) = about
10.5 s. This is not a fast path. `synccli.sync`'s no-op is 0.41 s, but it
writes nothing and keeps no history.

### 9.3 Why hardlinks, and when to switch

A content-addressed store (blobs keyed by sha256, snapshots as manifests over
blobs) would make an unchanged file cost one stat, about 0.3 s per 30k
entries. It was rejected for v1 for three reasons:
- Snapshots are no longer browsable trees. The contract changes for restore,
  which the brief describes as copying a snapshot back.
- It needs a garbage collector and an object store, with their own crash and
  concurrency rules.
- The existing `snaputil` helpers (`list_snapshots`, the rename-based prune)
  assume snapshots are directories of real files.

**Switch trigger:** if a no-change run takes more than 10 minutes on the
reference host, which is about 1.8 million entries at 0.33 ms per link, the
content store is the next design step. Re-measure the link cost on any other
filesystem before relying on it.

### 9.4 Scaling bounds

| Dimension | Per-run work | Memory | Disk |
|---|---|---|---|
| N sources | O(N) directory syscalls plus the F-proportional work above; sum over F_i | Flat: one source's state dict is held at a time | Snapshots grow with the sum of S_i |
| F entries | O(F) stats, O(U) links, O(F) manifest bytes | About 398 B per entry (measured for `build_manifest`'s two-field state; backupctl's richer record is expected to be larger). Bound: about 400 B x max_i F_i, plus a 1 MiB copy buffer | O(F) manifest bytes per snapshot |
| B bytes | O(D) copy work | Flat: files are streamed in 1 MiB chunks | Per snapshot: D + F x L bytes new, where L is the record size in 9.2 |
| K kept snapshots | O(K) renames, O(K) small meta reads | Flat | Total <= B_0 + sum over the kept snapshots (after the first) of D_i, plus K x F x L of manifests. Worst case, every file changes every run: K x B. |

Per-run work is linear in N and in F. Memory is flat in N and in B. It grows
with the largest single source's file count, because one source's state dict
is held whole. Streaming the baseline merge would make memory flat in F too.
That is a follow-up, not v1.

## 10. Retention and deletion

- **Keep K:** the newest K **valid** snapshots, by ordinal, with K >= 1
  enforced in config. Default K = 14 (open decision 1).
- **Order of operations:** publish first, then prune. Prune runs only after
  the new snapshot is published, and the new snapshot is the newest, so
  deletion can never leave the user with no usable snapshot. If the run fails
  before publish, prune does not run.
- **Victim selection:** the valid snapshots older than the newest K. Invalid
  snapshots are never selected (section 7).
- **Safe deletion of one victim:**
  1. `flock(LOCK_EX | LOCK_NB)` on `.leases/<name>`. If it is busy, a reader
     holds it: defer and report.
  2. `rename(snap-..., .trash/<name>.<pid>.<rand>)`. This is atomic, and no
     new reader can open the old name after it.
  3. Unlink `.leases/<name>`, release the lock, then delete the trash directory.
- **Crash during step 3:** the trash directory is deleted by recovery on the
  next run. Nothing else sees it.
- **Hardlinks:** deleting an old snapshot unlinks its names. Files still
  referenced by a newer snapshot keep their data. Deleted source files are kept
  only as long as an older snapshot still references them.
- **Growth:** at most K snapshots, plus any deferred by an active reader.

## 11. Restore contract (for the separate tool)

The restore tool is not part of this design, but it must follow this contract:
- Take `LOCK_SH` on the snapshot's lease before reading (section 6). Re-check
  that the snapshot directory exists after locking.
- Verify `meta.json` and `files.jsonl` against `manifest_sha256` before
  trusting any path.
- Map each manifest path with a checked function. Do not use
  `safe_snapshot_path` (section 2.2). The checked function must reject absolute
  paths and any `..` after normalization, and check that the resolved target
  stays under the restore destination.
- Restore into a directory outside the backup root. Snapshots are immutable,
  and hardlinks mean writing into one would change several snapshots.
- Verify each restored file's sha256 against the manifest.

## 12. Verification plan

Add `test_backupctl.py` to the repo. It should cover the observed defects,
using the same reproductions as the probes above:
- a hidden directory and a symlinked directory are walked and recorded;
- a same-size edit with a restored mtime is detected through `ctime`;
- an unreadable or vanished file is skipped, listed in `meta.json`, and the
  run exits 3;
- a truncated staging manifest and a corrupt published `meta.json` are handled
  as described in section 7;
- prune never deletes the newest snapshot, skips a leased one, and orders by
  ordinal even after a simulated backward clock step;
- two concurrent runs: exactly one proceeds and the other exits 75;
- a killed run leaves no visible snapshot, and the next run cleans up.

The 120 s budget is an acceptance test. Run it on the 1 GB / 30k-file fixture
on the reference host and record the result in the run report.

## 13. Open decisions

1. **K default.** 14 is proposed. Confirm the retention window.
2. **Symlinks.** Stored as links, not followed (section 5, item 4). Confirm,
   or switch to following file symlinks.
3. **Power-loss durability on macOS.** `os.fsync` is what was measured. It does
   not flush the drive's cache on macOS. Full durability needs
   `F_FULLFSYNC` on each copied file and each published directory. The cost is
   not measured. Choose between full durability (re-measure the budget) and
   process-death durability only.
4. **Lock wait default.** Fail-fast (exit 75) is proposed. Confirm whether the
   scheduler should use `--wait`.
5. **Optional sources.** A source may be marked `optional` so that a missing
   root is recorded as absent instead of failing the run (section 8).
6. **Switch to a content store.** Triggered by the 10-minute no-change run
   (section 9.3), not before.

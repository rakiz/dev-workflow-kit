# DESIGN-d1 — `backupctl`

Status: design for review. Target tree: this repository copy (fixture D1).

`backupctl` is a new module (`backupctl.py`, tests in `test_backupctl.py`) that
ships beside `synccli.py` and `snaputil.py` and imports both. It backs up a
configured set of source directories into immutable snapshots under one backup
root, and it builds on the existing code rather than re-implementing it.

This document first records what the existing code actually does (verified by
running it), then specifies the design, then maps every reused or overridden
function to its file and line numbers.

---

## 0. Conformance map

| Brief requirement | Where answered |
|---|---|
| Concurrent runs / restore readers / no corruption | §4, §6, §10 |
| Readers never ask whether a run finished | §2.3, §5.4, §6 (publish is atomic) |
| Process death at any point; index recovery | §6 (crash matrix), §7 (index recovery) |
| Source file vanishes / unreadable; same for scheduler and person | §9 |
| Retention; never no usable snapshot; delete vs readers | §10 |
| Incremental "unchanged"; granularity and missed edits | §8 |
| Initial full-backup performance budget for ~1 GB | §12 |
| N directories: what grows with what, explicit bounds | §11 |
| Grounding in existing files/functions, named overrides | §3, §13 |
| Work alone, no delegation | (process constraint; no design content) |

---

## 1. What the existing code does (verified)

I read `synccli.py`, `snaputil.py` and `test_synccli.py`, ran the suite, and
ran small probes. Everything asserted below is from the code or from those
runs.

- `python3 -m unittest` — 6 tests, all pass in 0.004 s.
- `synccli.scan_files` (synccli.py:10-19) returns sorted relative *file*
  paths. It drops **directories** whose name starts with `.` (line 14) but
  keeps dot-files: a probe with `.hidden/x` and `.dotfile` returned
  `['.dotfile']` only. Because it uses `os.walk(..., followlinks=False)` and
  only emits `filenames`, a symlink to a directory is listed in `dirnames`,
  never descended into, and never emitted. Special files that appear in
  `filenames` (FIFO, socket, device) are emitted as if they were regular
  files.
- `synccli.file_state` (synccli.py:22-25) returns
  `{"size": st_size, "mtime": st_mtime}`. `st_mtime` is a float; the
  nanosecond field is not used.
- `synccli.build_manifest` (synccli.py:28-33) builds `{relpath: state}` by
  calling `scan_files` and `file_state`.
- `synccli.changed_files` (synccli.py:36-42) returns new-or-changed paths. It
  never reports **deletions** (it iterates only `new_manifest`).
- `synccli.collect_stale(items, seen=None)` (synccli.py:45-59) returns
  `(path, fresh)` items that are not marked `fresh` and are not in `seen`.
  Its `seen` parameter is genuinely useful: `collect_stale(all_items,
  seen=completed)` is exactly "the work still pending".
- `synccli.copy_file` (synccli.py:62-69) does `fdst.write(fsrc.read())`
  (line 67) — the whole file in memory — and wraps the copy in
  `except OSError: pass` (lines 68-69), so an unreadable or vanished source
  is silently skipped. It does not fsync, does not use a temporary name, and
  follows symlinks because it opens by path.
- `synccli.sync` (synccli.py:72-87) builds the source manifest, reads the
  destination manifest with no validation (lines 77-79), copies changed
  files, and writes the manifest **in place** at lines 85-86. A crash during
  that write leaves a half-written `.sync_manifest.json`; there is no lock,
  no atomic replace, and no snapshot directory.
- `snaputil.list_snapshots` (snaputil.py:8-20) returns directories directly
  under the backup root whose names start with `snap-`, sorted. Sorting is
  lexicographic; the documented name format `snap-YYYYMMDD-HHMMSS-NN` makes
  that chronological.
- `snaputil.prune_snapshots(root, keep)` (snaputil.py:23-36) calls
  `shutil.rmtree` directly on live snapshot names (lines 34-35), oldest
  first. Two concrete defects: `keep=0` deletes **every** snapshot
  (`doomed = names[:len(names)]`), and a reader can lose files mid-read.
- `snaputil.snapshot_disk_usage` (snaputil.py:39-51) sums `st_size`
  (line 50), i.e. apparent bytes. With hard links this double-counts shared
  data.
- `snaputil.safe_snapshot_path(root, snap, rel)` (snaputil.py:54-63) claims
  the result can never point outside the snapshot, but it is wrong. Probes:
  `safe_snapshot_path("/backup","snap-1","/etc/passwd")` →
  `/etc/passwd` (`os.path.join` discards the prefix on an absolute path), and
  `safe_snapshot_path("/backup","snap-1","../../etc/passwd")` →
  `/backup/snap-1/../../etc/passwd`, which normalizes outside. This helper
  must not be trusted as-is for restore path resolution.
- `snaputil.is_stale(snapshot_dir, ref_epoch)` (snaputil.py:66-73) uses the
  directory's `st_mtime` (line 73). A directory's mtime changes when entries
  are added or removed, not when file contents change, so it is not a
  validity predicate for a snapshot.

Measured on the host used for §12 (macOS 15.8.1, Apple M3 Max, APFS,
Python 3.10.11): scanning 4,000 files took 0.115 s; copying 205 MB in 4,000
files took 1.284 s; copying 41 MB in 10,000 files took 2.827 s; SHA-256 ran
at 2,598 MB/s; a Python dict index costs 588 B/entry and its NDJSON encoding
156 B/entry.

---

## 2. Goals, non-goals, and the consistency model

### 2.1 Goals

1. Snapshot N configured source directories into one backup root.
2. A published snapshot is immutable, complete, and self-consistent.
3. Concurrent runs serialize; restores never observe a partial snapshot.
4. A killed run leaves only hidden, ignorable garbage; the next run recovers
   automatically.
5. Incremental runs copy only changed bytes and hard-link unchanged data.
6. A defined retention policy prunes old snapshots without ever leaving zero
   usable snapshots.
7. Explicit, derived bounds for time, memory and disk as N and the tree grow.

### 2.2 Non-goals

- No filesystem-level point-in-time (no APFS snapshot, LVM, VSS). `backupctl`
  is a userspace copier; its consistency is defined in §2.3.
- No encryption, compression, off-site transfer, or block-level dedup.
- No preservation of ownership, ACLs, xattrs, flags, or sparse holes. Mode and
  mtime are preserved; symlinks are preserved as symlinks.
- No cross-backup-root dedup; hard links only within one backup root.

### 2.3 Consistency model (precise)

- **Snapshot membership instant = the source scan.** A regular file that is
  observed during the scan belongs to the snapshot. A file created after its
  directory was scanned belongs to the next snapshot. A file deleted after
  the scan but present at scan time may still be included (it existed at the
  snapshot instant). A file present at scan time that cannot be *read* when
  the copy reaches it is omitted and reported (§9).
- **Per-file content is not torn.** After copying a changed file, the source
  is re-`stat`ed; if its state changed during the read, the partial copy is
  discarded and retried (up to 2 retries), then the file is recorded as
  `unstable` and omitted. This cannot detect a same-size rewrite that also
  preserves mtime and ctime (see §8.2), but it removes the ordinary
  append/rewrite-during-read tear.
- **No cross-file mixing.** Every published snapshot is built entirely under
  one `.inprogress-*` directory and published by one atomic rename. It never
  reuses or writes into a published directory.
- **The index never over-promises.** A snapshot's index is written only from
  the set of files that were completely materialized (copied or hard-linked)
  and passed the publish gate (§6.3), never from the pre-scan list.
- Process death is the primary fault model. Power-loss durability of the
  publish is best-effort and platform-dependent (§6.4); process-death safety
  does not depend on fsync, only on atomic rename.

---

## 3. Reuse plan and named overrides (summary; details in §13)

`backupctl` uses these existing functions as the core of its pipeline:

- Scanning skeleton, sorted path production: `synccli.scan_files`
  (synccli.py:10-19). **Overridden** where it drops hidden directories
  (line 14), loses symlinked directories, and has no `onerror`.
- Per-file state: `synccli.file_state` (synccli.py:22-25). **Overridden** to
  add `mtime_ns`, `ctime_ns`, `dev`, `ino`, `mode`, `type`.
- Manifest construction loop: `synccli.build_manifest` (synccli.py:28-33).
  **Reused as the contract**; the loop is repeated with the extended state
  because the module-level `file_state`/`scan_files` names inside it cannot be
  parameterized without monkey-patching.
- Change detection: `synccli.changed_files` (synccli.py:36-42). **Reused**
  unchanged, with both sides normalized to the same state-dict shape.
- Resume work-list: `synccli.collect_stale` (synccli.py:45-59). **Reused**,
  with `seen` = the set of files a dead run's journal proves complete.
- Copy primitive: `synccli.copy_file` (synccli.py:62-69). **Overridden**
  (streaming, no silent skip, temp+fsync, type checks).
- Manifest serialization: `synccli.sync` (synccli.py:72-87), specifically the
  in-place write at lines 85-86. **Overridden** with an atomic, streamable,
  checksummed index.
- Snapshot enumeration: `snaputil.list_snapshots` (snaputil.py:8-20).
  **Reused**.
- Deletion: `snaputil.prune_snapshots` (snaputil.py:23-36). **Overridden**
  (reader safety, `keep=0`, atomic trash rename).
- Size reporting: `snaputil.snapshot_disk_usage` (snaputil.py:39-51).
  **Reused for apparent size**, extended with inode-dedup physical size.
- Restore path mapping: `snaputil.safe_snapshot_path` (snaputil.py:54-63).
  **Overridden** because it demonstrably escapes the snapshot (§1).
- Age test: `snaputil.is_stale` (snaputil.py:66-73). **Reused only** for
  aging `.trash-*` directories, never as a snapshot-validity test.

---

## 4. Concurrency and locking

Two advisory lock files live at the top of the backup root. Both are regular
files, ignored by `list_snapshots` (their names do not start with `snap-`),
and never deleted (deleting a lock file breaks `flock` for concurrent
openers).

| Lock | Mode | Held by | Held for |
|---|---|---|---|
| `.backupctl.run.lock` | exclusive | a `backupctl run`/`prune` | whole run |
| `.backupctl.readers.lock` | shared | a reader (`restore`, `exec-in-snapshot`) | while reading a snapshot |
| `.backupctl.readers.lock` | exclusive | the prune phase only | the rename/unlink window |

Rules:

1. **Runs serialize.** The chosen answer to two simultaneous triggers is that
   they never mutate the backup root concurrently: one gets the lock and the
   other waits or reports busy. A run takes `LOCK_EX` on `.backupctl.run.lock` with
   `fcntl.flock`. Default behavior is non-blocking (`LOCK_NB`): a second run
   exits 4 with `another backup run holds the lock`; `--wait SECONDS` retries
   until the timeout. Scheduler and person get the same behavior; the
   scheduler retries on the documented exit code. There is no stale lock: the
   OS releases `flock` when the process dies, so the "next run must make
   progress without manual cleanup" rule holds even after `kill -9`.
2. **Copy is reader-safe without cooperation.** A run writes only into
   `.inprogress-*`, never into a `snap-*` directory. Therefore a backup can
   copy while any reader reads any published snapshot; the reader sees a
   complete, immutable image.
3. **Prune is the only destructive phase, and it is short.** Only pruned
   snapshots are renamed and unlinked, under `LOCK_EX` on the readers lock.
   A cooperating reader holding the shared lock is never affected: prune
   waits for it (up to `--prune-wait`, default 30 s) and otherwise defers the
   whole prune to the next run. A long copy therefore never blocks restores.
4. **Prune vs run deadlock is impossible.** Readers take only the shared
   lock; they never take the run lock. Lock order is always run-lock →
   readers-lock, one direction only.
5. **Non-cooperating readers** (third-party tools that ignore the lock) get
   defense in depth from §10.3: doomed snapshot directories are atomically
   renamed to `.trash-*` and only unlinked after a grace period, and open file
   descriptors survive both rename and unlink on POSIX.

Locking scope is one backup root. Two runs with different backup roots never
interact.

---

## 5. On-disk layout and run algorithm

### 5.1 Layout

```
<backup_root>/
  .backupctl.run.lock
  .backupctl.readers.lock
  .inprogress-<UTCts>-<pid>-<rand>/     # never visible as a snapshot
      JOURNAL.ndjson                    # append-only completion log
      RUN.json                          # start record, rewritten as final report
      <source-id>/...                   # materializing trees
      INDEX.ndjson                      # written after data, atomically
      SKIPS.ndjson
  .trash-<snapshot-name>-<UTCts>/       # renamed doomed snapshot, awaiting GC
  .corrupt-<snapshot-name>-<UTCts>/     # quarantined unusable snapshot
  snap-YYYYMMDD-HHMMSS-NN/
      INDEX.ndjson                      # published index (checksummed)
      SKIPS.ndjson                      # omitted paths + reasons
      RUN.json                          # summary, counts, duration, config hash
      <source-id>/...                   # the point-in-time trees
```

- In-progress, trash and quarantine names start with `.`, so
  `snaputil.list_snapshots` (snaputil.py:17-19, which requires
  `startswith("snap-")` and `is_dir()`) ignores them automatically.
- Snapshot names follow the documented `snap-YYYYMMDD-HHMMSS-NN` format, so
  `list_snapshots`'s lexicographic sort is chronological. `NN` is the
  smallest 2-digit value that makes the name unique under the lock.
- `<source-id>` comes from config; it is a stable ASCII token matching
  `[A-Za-z0-9._-]+` and not `.` or `..`, so sources with the same basename
  never collide and index paths cannot escape through a source id.
- The index is **NDJSON**, not a JSON dict: one header line, one line per
  entry in sorted `(source_id, relpath)` order, one summary line. This keeps
  index I/O O(1) memory and makes line-level recovery possible.

### 5.2 Run algorithm

```
run(config):
  cfg = load_and_validate(config)              # O(N), before any mutation
  lock = flock(run.lock, EX, timeout)          # §4
  recover_and_gc()                             # §7.2, §10.3
  base = newest_usable_snapshot()              # §7.1; may be None
  plan = []
  for source in cfg.sources (sequentially):    # peak memory = max per source
      plan.append(plan_source(source, base))
  for item in plan: materialize(item)           # copy / hard-link / symlink
  write_skips(); write_index(); fsync data
  verify_publish_gate()                        # §6.3
  publish = os.rename(inprogress, snap-name)   # atomic, same filesystem
  prune_if_due(base)                           # §10, under readers lock
  release lock; report
```

`plan_source` computes the current manifest and the change set, entirely with
the grounded functions from §13:

```
current  = build_manifest_ext(source.path)     # scan_files_ext + file_state_ext
base_map = entries(base, source.id)            # streamed from INDEX.ndjson
changed  = synccli.changed_files(base_map, current)   # new + changed
removed  = base_map.keys() - current.keys()            # deletions are absent
unchanged = current.keys() - changed
```

`removed` needs no action: the new snapshot simply has no entry for it. That
is what makes "a file deleted from the source" correct in a new snapshot and
why `changed_files`'s deletion blindness (synccli.py:36-42) does not hurt.

### 5.3 Materialization rules per path

- **Unchanged regular file**: `os.link(base/<source>/<rel>, inprogress/<source>/<rel>)`.
  Never open the published inode for writing. If `os.link` fails (missing
  base file, `EMLINK`, `EXDEV`, permissions), fall back to a streaming copy
  and record `link_error` in `RUN.json`. This is the incremental path.
- **Changed regular file**: stream-copy to `<rel>.part-<rand>` in the
  destination directory, hash while writing, `flush` + `fsync`, `os.replace`
  to final, append a journal line. See §9 for read failures and §6.4 for
  fsync policy.
- **Symlink**: create the link with `os.symlink(target)`; no dereference, so
  a link to an unreadable or huge target cannot fail the copy or read outside
  the tree. Store link target in the index.
- **Directory**: `os.makedirs`; mode preserved. Empty directories are
  reproduced because the scanner emits directory entries.
- **Special file** (FIFO/socket/device): never opened; recorded in
  `SKIPS.ndjson` with reason `special`. Opening a FIFO could block forever and
  hang the run; that is why the type check precedes the copy.

### 5.4 Visibility rule

A name matching `snap-*` under the backup root either does not exist or is a
fully materialized, gated, and renamed snapshot. There is no third state. Readers never ask "is the run finished"; the existence of the name is
the answer.

---

## 6. Publish protocol and crash behavior

### 6.1 Why the write path changes

`synccli.sync` writes its manifest in place with
`open(dst_manifest_path, "w")` (synccli.py:85-86). A kill during that write
truncates the manifest, and there is no snapshot directory to disambiguate a
partial run. `backupctl` keeps `synccli`'s read/compare structure but replaces
serialization and orchestration.

### 6.2 Publish sequence

1. All data files are finalized *inside* `.inprogress-*` (temp name,
   fsync, `os.replace` within the same directory).
2. `INDEX.ndjson`, `SKIPS.ndjson`, `RUN.json` are each written to a temp name
   in `.inprogress-*`, fsynced, and `os.replace`d.
3. The publish gate runs (§6.3).
4. `os.rename(".inprogress-*", "snap-YYYYMMDD-HHMMSS-NN")`. The in-progress
   directory is created inside the backup root, so source and destination of
   the rename are on the same filesystem and the rename is atomic.
5. Parent-directory fsync is attempted where the platform supports it
   (§6.4).
6. The lock is released after prune.

### 6.3 Publish gate (must pass or publish is aborted)

- The index validator (§7.1) passes: format/version, line syntax, sorted
  unique paths, relative-and-contained paths, entry hash matches.
- For every index entry, the target path exists under the in-progress
  directory and is the recorded type. For copied regular files, the size
  matches and the stored hash equals the hash computed from the bytes actually
  written (already available; no re-read). For hard-linked entries, the base
  inode is immutable and its recorded hash is inherited, so only existence and
  size are re-checked.
- No `*.part-*` file remains.
- Every configured source that was not explicitly allowed to be absent
  (§9.3) has an entry.
- `RUN.json` records the exact config (sources, ranges) hashed at start, so a
  published snapshot is self-describing.

If any check fails, the run does **not** rename; it exits 5, leaves the
inprogress directory for recovery (§7.2), and leaves all published snapshots
untouched. A reader therefore cannot see a snapshot whose index promises
missing data.

### 6.4 Durability policy

- Process-death safety (Ctrl-C, `kill`, sleep) comes from atomic rename alone.
- For power-loss durability, data files are fsynced before their `os.replace`
  in step 1; hard-linked files inherit the durability of the snapshot that
  first wrote them. The journal is fsynced at checkpoints (every 128 entries,
  `--journal-fsync`), so a crash may leave at most 127 completed-but-
  unjournaled files; recovery treats them as not done and re-derives them
  (§7.2). That is safe, only slightly wasteful.
- On macOS, file data uses `fsync(2)`; `F_FULLFSYNC` is used for the index and
  `RUN.json` when available. Directory fsync may be unsupported on some
  platforms; it is attempted and its failure is recorded, not fatal. This is
  the one place where the design deliberately weakens power-loss ordering;
  process-death correctness is unaffected.

### 6.5 Crash matrix

| Where the process dies | On-disk state | Next run | Reader sees |
|---|---|---|---|
| before any write | nothing new | normal | old set |
| during a data copy | `*.part-*` in `.inprogress-*` | part file deleted, file re-derived | nothing new |
| after N completed files | journal + complete files in `.inprogress-*` | resume via `collect_stale` (§7.2) or discard | nothing new |
| during index write | temp index only; `INDEX.ndjson` absent in in-progress | index re-derived from materialized set | nothing new |
| after gate, before rename | complete `.inprogress-*` | may validate and publish, else discard | nothing new |
| during rename | rename is atomic: old or new name | normal | old set or a complete new snapshot |
| after publish, before prune | one extra old snapshot | prune runs | old set + complete new |
| during prune rename | some doomed names are `.trash-*` | GC completes | published set intact |
| during trash unlink | partial `.trash-*` | GC completes | `.trash-*` ignored |
| while holding a lock | OS releases `flock` | proceeds | unaffected |

---

## 7. Index format, validation, and recovery

### 7.1 Format and validator

`INDEX.ndjson`:

```
{"format":"backupctl-index","version":1,"snapshot":"snap-...","sources":[...],"counts":{...}}
{"s":"evals-main","p":"sub/a.bin","t":"f","sz":12345,"mn":...,"cn":...,"dv":...,"ino":...,"md":33188,"h":"sha256:..."}
{"s":"evals-main","p":"empty","t":"d","md":16877}
{"s":"evals-main","p":"link","t":"l","lt":"target/relative"}
...
{"count":N,"entries_sha256":"..."}
```

- Entries are sorted by `(s, p)`. Sorting enables streaming merges, O(1)
  duplicate detection, and deterministic diffs.
- `mn`/`cn` are `st_mtime_ns`/`st_ctime_ns`; `dv`/`ino` are the **source**
  device/inode observed at scan (used for optional rename detection, §8.3).
- `h` is a SHA-256 computed while the bytes were copied; hard-linked entries
  inherit the base entry's hash (same inode, immutable content).
- The summary line carries the entry count and a SHA-256 over all entry-line
  bytes. Truncation, a half-written tail, or bit rot fails validation.

`validate_index(snapshot)` checks, in order: header format/version; each line
parses; `t` in `{f,d,l}`; path is relative, normalized, non-empty, contains no
`..` segment; path stays inside `snapshot/<source-id>` by the containment
check of §10.4; `(s,p)` strictly increasing (so duplicates fail); summary
count and hash match. It does **not** stat every data file: that is
`backupctl verify`'s job. A snapshot whose index fails is not "usable" and is
never used as an incremental base.

### 7.2 Recovery of a dead run (what is discarded, re-derived, reported)

At startup, while holding the exclusive run lock (so no live run can own the
directory):

- **`.inprogress-*/JOURNAL.ndjson` missing or unparseable** (including a torn
  final line): discard the entire in-progress directory; nothing is re-used.
  The run then does a normal full/incremental pass against the source tree.
  Report: `discarded incomplete run <name> (corrupt journal)`.
- **Journal valid but config hash differs** from the current config: discard
  the in-progress directory; report `discarded incomplete run <name>
  (config changed)`.
- **Journal valid and config matches**: resume. Delete `*.part-*` files.
  Entries in the journal are treated as fresh; `collect_stale` is called with
  `seen = {journaled relpaths whose data file still exists with the recorded
  size}`, yielding exactly the pending paths (this is the intended use of
  `collect_stale`'s `seen` argument; synccli.py:45-59). Each journaled file
  is re-checked against the *current* source state; if the source changed
  while the run was dead, the file is removed from `seen` and re-copied. The
  index is then **re-derived from the materialized set**, never trusted from
  the dead run. Report: `resumed incomplete run <name>: reused F files,
  re-derived R entries`.
- **A published snapshot's index is corrupt or unparseable** (external
  truncation, storage fault): rename it to `.corrupt-<name>-<ts>` (atomic
  rename, never delete data on the spot), exclude it from base selection, and
  report `quarantined unusable snapshot <name>: <reason>`. The next base is
  the next-newest usable snapshot; if none, the run is a full backup.
- **A published snapshot is missing a data file referenced by its index**
  (detected during `verify`, or when a hard link fails during a run): the
  snapshot is not usable as a base; if it is the newest, fall back to the next
  usable one and report the degradation. Never repair an old snapshot in
  place — published snapshots are immutable.

The half-written index case is inherently confined to `.inprogress-*`
because a published `INDEX.ndjson` is produced by temp+fsync+`os.replace` and
a publish only happens after the gate. Recovery of the in-progress index is
"discard and re-derive"; recovery of a published index is "quarantine and
fall back".

---

## 8. Incremental backup: granularity and what it misses

### 8.1 Decision key

"Unchanged" is decided per **relative path**, by comparing the full state
tuple `(type, size, mtime_ns, ctime_ns, dev, ino, mode)` between the newest
usable base index and the current scan. The comparison function is
`synccli.changed_files` (synccli.py:36-42) with both sides normalized to the
same dict shape; the removed set is `base.keys() - current.keys()`.

- Path identity, not content identity: this is per-file, whole-file metadata.
  It is not per-block and not per-content-hash.
- The base is only the newest usable snapshot, so "unchanged since the last
  snapshot" is literal. Work never grows with the number of retained
  snapshots: only one base index is read.

Note the override of `synccli.file_state` (synccli.py:22-25): its float
`st_mtime` is replaced with `st_mtime_ns`, and `ctime`, `dev`, `ino`, `mode`,
`type` are added. Float seconds can hide sub-second edits; `ctime_ns` catches
writes that restore `mtime`; `dev`/`ino` support optional rename detection.

### 8.2 What this granularity can miss

- A write that keeps the file the same length **and** leaves `mtime_ns` and
  `ctime_ns` unchanged. Normal writes change `ctime`; `touch -d` changes
  `mtime` but also `ctime`; therefore the realistic miss requires the
  filesystem's timestamp resolution to be coarser than two consecutive
  same-size writes (e.g. 1-second-granularity filesystems), or a privileged
  actor that can forge `ctime` on a filesystem that allows it (some network
  filesystems). Two same-size writes inside one timestamp tick on a coarse
  filesystem are the canonical miss.
- Metadata-only changes (`chmod`, `chown`, xattrs) change `ctime` and are
  therefore classified as changed and re-copied. This is a false positive
  (safe direction), not a miss.
- A file that vanished and was recreated with identical `(size, mtime_ns,
  ctime_ns, dev, ino)` inside one timestamp tick can be treated as unchanged.
  The inode and ctime components make this extremely unlikely, not
  impossible.
- `--verify=content` closes all of the above at the cost of reading **all**
  bytes every run. It re-hashes each current file and compares with the base
  `h`; a mid-run performance bound becomes B/BW rather than B_chg/BW (§12).
  The default is the metadata key; the integrity hash `h` for each copied
  file is always stored, so `backupctl verify` can audit at any time without
  changing run behavior.

### 8.3 Hard-link dedup and its limits

- Unchanged file → `os.link` from the base snapshot path. Shared bytes are
  therefore stored once, and the new snapshot is a complete image without a
  second copy.
- Grabbing granularity: snapshot-to-snapshot along the chain. A file that is
  unchanged across runs 1..K shares one inode across those K snapshots. If it
  changes at run K+1 and later reverts to the old content, run K+2 sees a
  metadata difference from its base (run K+1) and copies; it does not reach
  back to the older inode. This is a bounded loss, not a correctness issue.
- Immutability rule: a published inode is never opened for writing. Changed
  content always goes to a new file (`O_CREAT` on a fresh temp name), so a
  hard-linked older snapshot cannot be mutated through the new one.
- Optional `--detect-renames` (default off): build a secondary map
  `(dev, ino, size, mtime_ns, ctime_ns) → base path` while streaming the base
  index; a new relative path whose source identity matches a disappeared base
  path can hard-link the old content instead of copying. Cost: O(F) extra
  memory; risk: inode reuse producing a false match, mitigated by the full
  identity tuple.
- If `os.link` is unsupported or the link count limit would be exceeded, the
  item is copied instead. The index records `link` vs `copy`, so the run
  report shows how much dedup actually happened.

---

## 9. Vanished, unreadable, and changing sources

The policy is in the shared run path; it does not depend on whether a
scheduler or a person started the process. Only presentation differs
(`--json` vs human text). The same exit codes apply to both.

### 9.1 A file is observed at scan, then cannot be read

- `ENOENT` (vanished between listing and open), `EACCES`, `EIO`, `ESTALE`,
  `ETXTBSY`, or a short read: discard any partial temp file, record a
  `SKIPS.ndjson` entry `{s,p,reason:"unreadable",errno:...,at:...}`, and omit
  the file from `INDEX.ndjson`.
- The snapshot is still published (if the gate passes), because it is a
  consistent image of what was readable. It never claims the file.
- The run prints the skip list and exits **3 (partial)**. A scheduler sees a
  nonzero status and can alert; a person sees the same list. `--strict` makes
  any skip abort the publish instead (exit 5), and is available identically
  to both trigger paths.

### 9.2 A file changes while it is being read

After the copy, re-`stat` the source and compare with the pre-read state
(`size, mtime_ns, ctime_ns, ino`). If it changed, discard the copy and retry
up to 2 times. If it is still changing, skip it with reason `unstable`. This
prevents publishing an ordinary torn read (for example, a file being
appended) as if it were a coherent point-in-time file; the same-size /
same-timestamp rewrite remains the documented residual risk of §8.2.

### 9.3 A configured source root is missing or unreadable

A missing/unreadable source root would make an entire source look "empty" in
the snapshot, which a reader could mistake for a real empty directory. The
default is therefore to **fail the run without publishing** (exit 5) and leave
all previous snapshots intact. `--allow-missing-source <id>` (explicit,
recorded in `RUN.json`) opts into publishing the remaining sources with the
missing source flagged in `SKIPS.ndjson` and `RUN.json`.

### 9.4 Directory entries that disappear during the walk

The scanner wraps `os.walk`/`os.scandir` errors in an `onerror` handler
(the default `os.walk` behavior in `synccli.scan_files` silently ignores
them). A directory that vanishes mid-walk is recorded in `SKIPS.ndjson`
(`reason:"scan-error"`), and its already-seen files are handled normally. If
a directory exists but cannot be listed, the run takes the partial path
(exit 3) unless `--strict`.

### 9.5 Reporting surface

`RUN.json` (written into the snapshot and printed) contains:
`started`, `finished`, `duration_s`, `config_hash`, `sources[]`, `counts
{files, dirs, symlinks, copied, linked, skipped, bytes_copied, bytes_linked}`,
`base_snapshot`, `published_snapshot`, `skips[]`, `recovery[]`, `prune[]`,
`lock_wait_s`, and `status` (`ok` / `partial`). The scheduler consumes the
same JSON; there is no scheduler-only code path.

---

## 10. Retention and deletion safety

### 10.1 Policy

Config `retention.keep_last` (default 10) is the number of *usable* snapshots
to retain; `retention.min_age_s` (default 0) protects very young snapshots
from deletion regardless of count.

Rules, in order:

1. Prune runs only **after** a successful publish. A failed or aborted run
   never deletes anything.
2. The set to consider is the snapshots recognized as `backupctl` snapshots
   (name matches our pattern and the header identifies us). Foreign
   `snap-*` directories are ignored, never deleted.
3. Only snapshots whose index validates count as usable. A corrupt snapshot
   is quarantined (§7.2), not silently deleted and not used for the count.
4. Always keep at least the newest usable snapshot, even if
   `keep_last == 0` (clamp to 1). This is the explicit fix for
   `snaputil.prune_snapshots`'s `keep=0` behavior, which deletes everything
   (snaputil.py:31-35).
5. Never delete a snapshot younger than `min_age_s`.
6. Never delete the snapshot that was the base of the current run until the
   new snapshot is published and gated.

### 10.2 Bounded work and disk

Prune is O(K) names and O(entries in deleted snapshots) unlinks. Because of
hard links, unlinking a shared file only decrements the link count; data
blocks are freed when the last snapshot referencing the inode is pruned. Disk
therefore returns to the retention bound (§11) without reading or rewriting
surviving data.

### 10.3 Safe deletion while a reader may be reading

Three layers:

1. **Cooperative readers hold `LOCK_SH` on `.backupctl.readers.lock`** for the
   duration of reading a snapshot (`backupctl restore` and
   `backupctl exec-in-snapshot` do this automatically; external restore
   tooling is documented to use `flock -s`). Prune takes `LOCK_EX` only around
   the rename/unlink window; it waits up to `--prune-wait`, then defers pruning
   to the next run. While the shared lock is held, no snapshot a reader can
   name is renamed or unlinked.
2. **Deletion is rename-then-unlink.** A doomed snapshot is first atomically
   renamed `snap-* → .trash-<snap>-<ts>`, then unlinked. A reader that already
   opened the snapshot directory (or any file in it) keeps working through the
   rename; hard links keep the data inode alive even after other directories
   drop it.
3. **Grace period for non-cooperating readers.** `.trash-*` directories are
   not removed until they are older than `retention.trash_grace_s` (default
   300 s), measured from the rename timestamp parsed from the name (not from
   directory mtime, because `snaputil.is_stale`'s directory-mtime test,
   snaputil.py:66-73, is not a reliable content/age signal). GC runs at the
   start of the next run.

Residual window: a non-cooperating reader that resolves a snapshot name,
then loses the race to the rename, and then opens data by the old path, gets
`ENOENT`. It never gets a partial or corrupted snapshot; it must retry
`list_snapshots`. This is stated, not hidden: the guarantee against
disappearance is offered to readers that take the shared lock (or hold the
directory fd), and is best-effort otherwise. With the shared lock the
guarantee is absolute for the lifetime of the lock.

### 10.4 Restore path containment

Stored paths are validated at index-read time (§7.1) and again when mapped to
the filesystem. The mapping replaces `safe_snapshot_path` (snaputil.py:54-63)
because that helper escapes on absolute paths and `..` (verified in §1).
The replacement resolves both the snapshot root and the candidate with
`os.path.realpath`, then requires
`os.path.commonpath([snap_root_real, candidate_real]) == snap_root_real`;
otherwise it raises `PathEscape`. Validation happens before any open, so a
corrupt or malicious INDEX cannot read or write outside the snapshot.

---

## 11. Scaling: what grows with what, as explicit bounds

Symbols: `N` = number of configured source directories; `F` = total regular
files across all sources; `F_max` = maximum files in one source; `D` = total
directories; `B` = total bytes; `B_chg` = bytes in new/changed files in one
run; `K` = retained snapshots.

| Quantity | Explicit bound | Notes |
|---|---|---|
| Run locking | O(1) time and memory; two open fds | independent of N, F, K |
| Per-run stat scan | Σ over sources of `F_s` stat calls (+ `D_s` directory reads) | O(F); measured 28.8 µs/file |
| Per-run bytes read/written | `B_chg` (plus `B` on the first run) | unchanged files are linked, not read |
| Per-run copy/link operations | ≤ `F` metadata ops (one `link` or one copy per file) | O(F) |
| Per-run index I/O | O(F) read of exactly one base index + O(F) write of the new index | **independent of K**: never reads K indexes |
| Peak memory (default) | `2 · F_max · 588 B` (base + current manifest) + 1 MiB copy buffer + `N · c_cfg` + O(1) locks | measured 588 B/entry (§12); sequential per source ⇒ `F_max`, not `F` |
| Peak memory, 25k-file source | ≈ 29.4 MB manifest + 1 MiB + config | measured constant, not "bounded" hand-waving |
| Low-memory mode | stream base index (sorted) and current scan (sorted) with a merge; O(1) entries, O(path bytes) per source | for `F_max > --low-memory-threshold` (default 250k) |
| Config memory | O(N): one small record per source | N = 3 today, "a few dozen" later |
| Disk, first snapshot | `B` data + `F · 156 B` index + directory overhead | measured 156 B/entry NDJSON |
| Disk, K snapshots | `B + Σ_{i=2..K} B_chg_i + K·F·156 B + directory overhead` | hard links dedup unchanged bytes |
| Apparent size reporting | `K · B` worst case | `snaputil.snapshot_disk_usage` sums apparent `st_size` (snaputil.py:50), so it over-reports with hard links; physical size is computed by deduping `(dev, ino)` |
| Prune work | O(K) name checks + O(entries in deleted snapshots) unlinks | no data rewrite; blocks freed on last unlink |
| Number of open fds | O(1) per copy (sequential), 2 locks, 1 index writer | independent of F and N |
| Snapshot creation | +1 directory per source per snapshot → O(N) dirs, O(F) entries | flat per snapshot; no history-proportional per-run cost |

What explicitly stays flat, with the number: lock overhead O(1); per-run
index reads = 1 (not K); peak manifest memory = 2 per *source* (not 2·N);
open fds = O(1); per-run work does not include re-reading old snapshots except
the one base index. What grows: disk grows with retained snapshots and
changed bytes; cumulative unlink work grows with the snapshots pruned; the
per-run base index read grows with `F`, not with `K`.

---

## 12. Performance budget for the initial full backup

Target workload: ~1 GB, 25,000 files (40 KB average), first full backup, on
the host measured in §1 (Apple M3 Max, APFS SSD, Python 3.10.11).

### 12.1 Measurements (raw)

| Workload | Measured |
|---|---|
| scan 4,000 files (`os.walk` + `os.lstat`) | 0.115 s → 28.8 µs/file |
| copy 4,000 × 50 KB = 205 MB, streaming + no fsync | 1.284 s → 159 MB/s, 3,114 files/s |
| copy 4,000 × 50 KB, streaming + per-file fsync | 1.240 s → 165 MB/s (no measurable fsync penalty on this SSD) |
| copy 10,000 × 4 KB = 41 MB | 2.827 s → 14.5 MB/s, 3,537 files/s |
| SHA-256 over 400 MiB in memory | 2.6 GB/s |
| index memory | 588 B/entry (Python dict) |
| index encoding | 156 B/entry (NDJSON) |

The benchmark used `shutil.copyfileobj` with 1 MiB chunks (the same primitive
the design uses), created 100 subdirectories, and measured wall time on
freshly written files. These are warm-cache numbers: the 205 MB working set
fits largely in page cache, so they bound CPU and syscall overhead, not cold
device reads.

### 12.2 Derivation for 1 GB / 25,000 files

| Term | Derivation | Time |
|---|---|---|
| scan/stat | 25,000 × 28.8 µs | 0.72 s |
| copy bytes | 1,000 MB / 159 MB/s | 6.29 s |
| copy per-file overhead | 25,000 / 3,114 files/s | 8.03 s |
| SHA-256 while copying | 1,000 MB / 2,598 MB/s (overlapped with I/O) | 0.38 s |
| index write | 25,000 × 156 B = 3.9 MB | ~0.10 s |
| publish gate (lstat every entry) | 25,000 × 28.8 µs | 0.72 s |
| **Sum (warm)** | | **≈ 16.2 s** |

The byte term and the per-file term are not independent: the measured
3,114 files/s already includes the bytes of each file, so summing both is a
deliberately conservative upper bound, not a double-count error in the
unsafe direction.

**Budget: 35 s ceiling (p95) for the first 1 GB / 25,000-file backup; expected
≈ 16 s warm.** The 35 s ceiling is the derived 16.2 s with a 2.0× cold-cache
allowance (32.4 s) plus a small margin. The 2.0× factor is a stated allowance
for device reads, not a measurement; the measured terms in the table are the
derivation.

The same derivation gives ≈ 9 s warm for a small-file-heavy 100 MB / 25,000
file tree (the per-file term dominates: 8.0 s), and it is the formula, not a
guess, that makes the budget falsifiable:
`T ≈ F·28.8µs + B/159MB/s + F/3114 + B/2.6GB/s + index + gate`.

Caveats, stated as bounds rather than promises:

- Per-file fsync on a spinning disk is a different regime: at an illustrative
  ~10 ms per fsync, 25,000 × 10 ms = 250 s, so this budget is explicitly an
  SSD/APFS budget. The design measures the actual fsync cost per run and
  reports it in `RUN.json` (`duration_s`, `fsync_s`), so the claim is
  falsifiable on the deployment host.
- The incremental steady state removes the byte and per-file terms for
  unchanged files (hard links): a run with `B_chg = 0` costs the scan, one
  index read, and `F` link operations, i.e. tens of thousands of metadata
  operations, not a re-copy.
- `--verify=content` intentionally destroys this bound: it reads `B` every
  run.

---

## 13. Grounding table: exact files, functions, lines, and overrides

"Reuse" means the function is called as-is. "Override" names the exact
behavior being replaced and why.

| Pipeline stage | Existing code | Mode | Exact reason / adaptation |
|---|---|---|---|
| Directory/file scanning | `synccli.scan_files`, synccli.py:10-19 | Override | Line 14 drops hidden directories; the backup must include them. `os.walk(followlinks=False)` loses symlinked directories (they are in `dirnames` and never emitted); the backup records them as links. Special files in `filenames` are emitted as regular files; the backup classifies them and skips them. No `onerror` hook; the backup records scan errors. Replacement keeps the sorted-relative-path contract and uses `os.scandir` recursively. |
| Per-file state | `synccli.file_state`, synccli.py:22-25 | Override | Float `st_mtime` (line 25) loses sub-second precision; add `st_mtime_ns`, `st_ctime_ns`, `st_dev`, `st_ino`, `st_mode`, and a type tag. The returned dict stays equality-compatible so `changed_files` still works. |
| Manifest build | `synccli.build_manifest`, synccli.py:28-33 | Reuse contract, re-implement loop | Same loop (`for rel in scan: manifest[rel] = state`) with the overridden scanner/state. The function's module-level `file_state` reference cannot be parameterized without monkey-patching, so the loop is repeated; the shape and role are identical. |
| Change detection | `synccli.changed_files`, synccli.py:36-42 | Reuse | Called directly with the base index's state dicts and the current state dicts; dict equality is the changed predicate. Deletions are handled outside it because the function ignores them: `removed = base.keys() - current.keys()`; that is exactly the new snapshot's absence set. |
| Resume after death | `synccli.collect_stale`, synccli.py:45-59 | Reuse | `collect_stale(all_planned, seen=journaled_complete)` returns the pending work list; `seen` is the argument the function already supports (and tests, test_synccli.py:30-32). Files whose source changed while the run was dead are removed from `seen` and therefore come back as pending. |
| File copy | `synccli.copy_file`, synccli.py:62-69 | Override | (1) `fsrc.read()` at line 67 loads the whole file into memory; replaced with a 1 MiB streaming loop. (2) The bare `except OSError: pass` at lines 68-69 silently drops unreadable sources; replaced with a typed outcome that becomes a `SKIPS` entry (never a silently missing index promise). (3) No temp name, fsync, or atomic replace; added. (4) Opens by path and follows symlinks / would block on a FIFO; type checks precede the copy. |
| Manifest serialization | `synccli.sync`, synccli.py:72-87 (write at 85-86; read at 77-79) | Override | In-place `open(..., "w")` is not crash-safe and the reader trusts arbitrary JSON; replaced with temp+fsync+`os.replace`, NDJSON, checksums, and validation. The read/compare/copy structure is retained. `MANIFEST_NAME` (synccli.py:7) is not written into snapshots; the snapshot index is `INDEX.ndjson`. Optional `--emit-sync-manifest` can additionally emit a synccli-compatible `.sync_manifest.json` per source for interop. |
| Snapshot enumeration | `snaputil.list_snapshots`, snaputil.py:8-20 | Reuse | Used to enumerate `snap-*` names; results are then filtered by our validator and quarantine logic. The `startswith("snap-")` plus `is_dir()` test is exactly what lets `.inprogress-*` and `.trash-*` stay invisible. |
| Prune | `snaputil.prune_snapshots`, snaputil.py:23-36 | Override | (1) `shutil.rmtree` on live names (lines 34-35) can break a reader mid-read; replaced with rename-to-trash + grace + reader lock. (2) `keep=0` deletes all snapshots (lines 30-35); clamped to at least one. (3) It counts any `snap-*` directory as a snapshot, including one we have not validated; our pruning counts only validated, ours, non-quarantined snapshots. |
| Size reporting | `snaputil.snapshot_disk_usage`, snaputil.py:39-51 | Reuse + extend | Reused for apparent bytes in reports; with hard links the `st_size` sum (line 50) double-counts, so physical usage is also computed by deduping `(dev, ino)`. |
| Restore path mapping | `snaputil.safe_snapshot_path`, snaputil.py:54-63 | Override | Demonstrated escape: absolute input returns the absolute path (`os.path.join` discards the prefix) and `../../` survives `normpath` (probe output in §1). Replaced with realpath + `commonpath` containment (§10.4) plus index-time path validation. |
| Snapshot age | `snaputil.is_stale`, snaputil.py:66-73 | Reuse, narrow | Used only to age `.trash-*` for GC, never to decide snapshot validity: directory `st_mtime` (line 73) changes on entry add/remove, not content change. |

The three `synccli` unit-test groups (test_synccli.py:8-19, 21-33, 35-51)
still pass unchanged; `backupctl` does not modify `synccli.py` or
`snaputil.py`.

---

## 14. CLI, config, exit codes

Config is JSON (`backupctl.json`), no extra dependency on Python 3.10:

```json
{
  "backup_root": "/srv/backups/evals",
  "sources": [
    {"id": "evals-main",    "path": "/srv/evals/results"},
    {"id": "evals-archive", "path": "/srv/evals/archive"},
    {"id": "evals-scratch", "path": "/srv/evals/scratch"}
  ],
  "retention": {"keep_last": 10, "min_age_s": 0, "trash_grace_s": 300},
  "run": {"lock_wait_s": 0, "strict": false, "verify": "metadata"},
  "index": {"hash": "sha256"}
}
```

Validation before any mutation: backup root exists; it is not inside any
source, and no source is inside the backup root (otherwise a run would back up
its own snapshots); source ids are unique safe tokens and paths are absolute;
the backup root and sources are on a filesystem that supports atomic rename
and advisory locks (local FS; NFS is explicitly unsupported for the lock
guarantees, and `RUN.json` records the detected filesystem type).

Commands:

- `backupctl run [--config F] [--wait S] [--dry-run] [--strict]
  [--verify {metadata,content}] [--json]`
- `backupctl list [--json]` — usable snapshots, newest last
- `backupctl verify [SNAP] [--content]` — validate index and, optionally,
  re-hash data; exit 5 on failure
- `backupctl prune [--keep K] [--dry-run]`
- `backupctl restore SNAP --dest DIR [--source ID] [--dry-run]` — holds the
  shared reader lock; validates every path (§10.4)
- `backupctl exec-in-snapshot SNAP -- CMD...` — holds the shared reader lock
  while running a command against the snapshot
- `backupctl gc` — remove stale `.inprogress-*` and aged `.trash-*`
  (`.corrupt-*` is retained for inspection and removed manually)
- `backupctl status` — base, usable snapshots, last run report

Exit codes: `0` ok; `2` usage/config; `3` published with skips (partial);
`4` lock busy/timeout; `5` aborted or verification failed (nothing published);
`1` unexpected. Scheduler and person share this table; `--json` changes only
the output format.

---

## 15. Test plan

Unit tests extend `test_synccli.py`'s style with `unittest` and
`tempfile.mkdtemp`:

1. **Atomic publish**: inject a crash after each phase (via subprocess kill or
   a test hook) and assert no `snap-*` exists until the final rename, and that
   every visible `snap-*` passes the gate.
2. **Corrupt index recovery**: truncate an `.inprogress-*/INDEX.ndjson` and
   `JOURNAL.ndjson` tail; assert the next run discards/re-derives, publishes,
   and reports the recovery. Also corrupt a published index and assert
   quarantine + fallback base.
3. **Concurrent runs**: two `multiprocessing` processes on one root; exactly
   one publishes, the other exits 4; both runs leave the tree valid.
4. **Reader during prune**: a reader holding `LOCK_SH` for a fixed interval;
   prune must defer, not delete; a second test reads an already-renamed
   `.trash-*` through an open directory fd.
5. **Vanishing file**: delete a file between scan and copy (monkeypatch or a
   hook), assert it is absent from `INDEX.ndjson`, present in `SKIPS.ndjson`,
   snapshot is published, exit 3, and a `--strict` run exits 5 without
   publishing.
6. **Incremental**: two runs, assert second run copies 0 bytes, links every
   unchanged file, and that a content change with preserved size but new
   ctime is copied. Assert the first snapshot's inode is unchanged after the
   second run (immutability).
7. **Symlink/special/FIFO**: a symlink to a directory is recorded as a link
   and not followed; a FIFO is skipped without blocking.
8. **Path escape**: craft an index entry `/etc/passwd` and `../../x`; restore
   must refuse before opening anything.
9. **Retention**: `keep_last=0` clamps to 1; a failed run never prunes; a
   `.trash-*` younger than the grace is kept.
10. **Grounding regression**: rerun `test_synccli.py` unchanged; assert the
    reused functions still have the contracts this design relies on.

Performance is checked with a tiny benchmark target derived from §12 (for
example 2,000 × 50 KB must finish under the formula's prediction with a
generous factor), so the budget regresses visibly instead of silently.

---

## 16. Limitations, stated plainly

- Not a filesystem snapshot: a file written during the run can be observed at
  a later instant than the scan. §2.3 defines the membership instant and §9.2
  removes ordinary torn reads; a same-size, same-timestamp rewrite remains the
  documented miss of §8.2.
- Dedup is metadata-identity along the snapshot chain, not content-addressed.
  A moved file is re-copied unless `--detect-renames` is enabled; a reverted
  file is re-copied rather than linked to an older snapshot.
- No sparse-file preservation: copied holes become allocated zeros.
- Ownership, ACLs and xattrs are not preserved; mode and mtime are.
- Advisory locks protect cooperating readers. Non-cooperating readers get the
  rename/grace best effort of §10.3, not a hard guarantee.
- Power-loss ordering depends on platform fsync behavior; process-death
  correctness does not.
- NFS or any filesystem without reliable atomic rename + `flock` is out of
  scope and rejected at config validation.

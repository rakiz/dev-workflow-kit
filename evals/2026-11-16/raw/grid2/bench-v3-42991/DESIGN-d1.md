# DESIGN — `backupctl` (fixture D1)

A command-line backup tool for the `evals/` result directories. It produces
point-in-time snapshots under a backup root, reuses the code already in this
directory, and defines exactly what happens when runs collide, readers race
writers, processes die mid-flight, source files vanish, and the backup root
grows forever.

Everything quantitative in this document is either a measurement taken in
this directory (commands given in §9) or a formula derived from those
measurements. Nothing is a guess.

---

## 1. Scope

`backupctl` covers a configured set of `N` source directories (`N = 3` today,
"a few dozen over time") and writes snapshots of all of them into one backup
root.

Each snapshot is a self-contained, point-in-time image of every source
directory, with an index that describes exactly what the snapshot contains.

Out of scope: restoring. A restore is "separate tooling that reads a snapshot
and copies it back" (BRIEF §"What `backupctl` must do"). `backupctl` only has
to *produce* snapshots that such a reader can consume safely; the reader
contract is specified in §7 so the two sides agree.

---

## 2. Grounding: what already exists here

Files in this directory, read before writing this design:

| File | What it is |
|---|---|
| `synccli.py` (103 lines) | manifest-based synchronizer |
| `snaputil.py` (92 lines) | snapshot listing / pruning / size / path helpers |
| `test_synccli.py` (55 lines) | the test suite for `synccli` (6 tests, `python3 -m unittest` — all pass) |
| `BRIEF.md` | the brief this design answers |

### 2.1 What `backupctl` reuses unchanged

| Existing symbol | Location | Use in `backupctl` |
|---|---|---|
| `scan_files(root)` | `synccli.py:10-19` | the *traversal shape* (relative paths, sorted, `os.walk`-based). Reused through `backupctl.scan_files()` which calls it for the "regular" tree (§4.3). |
| `build_manifest(root)` | `synccli.py:28-33` | per-source scan + stat, producing `{relpath: {size, mtime}}`. `backupctl` calls it and then re-keys the state (§4.3). |
| `changed_files(old, new)` | `synccli.py:36-42` | the change-detection predicate: a path is copied when it is absent from the old manifest or its recorded state differs. Reused as the selection step for "what to copy this run" (§5). |
| `collect_stale(items, seen=None)` | `synccli.py:45-59` | stale-item collection, used verbatim for the crashed-run temp sweep (§4.5): `items` are `(path, fresh)` pairs where `fresh` = "still alive". |
| `list_snapshots(backup_root)` | `snaputil.py:8-20` | the authoritative list of published snapshots. `backupctl` uses it unchanged, so the snapshot naming format is forced to `snap-YYYYMMDD-HHMMSS-NN` (§3.1). |
| `snapshot_disk_usage(backup_root, name)` | `snaputil.py:39-51` | logical size of one snapshot, reported by `backupctl list`/`status`. |
| `safe_snapshot_path(backup_root, name, rel)` | `snaputil.py:54-63` | the reader-facing path mapper: `..` segments are normalized away, so an index entry can never escape its snapshot. `backupctl` uses it when *writing* the index (it asserts the produced path is inside the snapshot) and documents it for the restore tool. |
| `MANIFEST_NAME = ".sync_manifest.json"` | `synccli.py:7` | the index file name inside a snapshot. Reused so the format stays compatible with `synccli`. |
| `file_state(path)` | `synccli.py:22-25` | the shape of a manifest entry (`{"size", "mtime"}`). Reused as the entry schema; the *values* are recomputed (§3.3). |

### 2.2 What `backupctl` overrides, and why

Each override names the exact existing symbol and the reason. Nothing is
overridden as "current behavior" without a target.

1. **`synccli.file_state` (`synccli.py:22-25`) — mtime precision.**
   `file_state` stores `st.st_mtime` as a Python `float`. Measured on this
   machine, `st_mtime = 1794866704.9659765` while
   `st_mtime_ns = 1794866704965976463`; the float form has ~256 ns
   granularity, so two *different* nanosecond timestamps can collapse to the
   same float. A file rewritten within that window with the same size would be
   declared unchanged. `backupctl` defines `file_state_ns(path)` returning
   `{"size": st.st_size, "mtime_ns": st.st_mtime_ns}` (integer nanoseconds)
   and uses it for every comparison and every index entry. This is a
   superset of `file_state`'s information, so `changed_files` still works on
   the dictionaries unchanged.

2. **`synccli.scan_files` (`synccli.py:10-19`) — hidden directories.**
   `scan_files` filters `dirnames` to those not starting with `.`
   (`synccli.py:14`). Measured behaviour (temp tree with `.hid/x` and
   `vis/.dotfile`): the returned list is `['vis/.dotfile']` — hidden
   *directories* are skipped, hidden *files* are kept. That asymmetry is not a
   backup policy; it is an accident of where the filter sits. A backup tool
   that silently omits a hidden directory's contents is not a backup.
   `backupctl.scan_files()` re-implements the walk **without** the hidden-dir
   filter (everything under the source root is in scope, hidden or not) and
   returns the same `{relative path}` shape, sorted, so the rest of the
   pipeline is unchanged. `synccli.scan_files` itself is not modified —
   `synccli` keeps its behaviour.

3. **`synccli.copy_file` (`synccli.py:62-69`) — memory and error handling.**
   `copy_file` does `fdst.write(fsrc.read())`, i.e. it reads the whole source
   into RAM. Measured: copying one 46 MiB file through `copy_file` left a peak
   RSS of **81.2 MB** for that single file. It also swallows `OSError` with
   `pass` (`synccli.py:68-69`), so a vanished file and an unreadable file are
   indistinguishable and both are silently dropped from the manifest — which
   violates the requirement that the index never promises files the snapshot
   does not contain *and* that the run reports what went missing.
   `backupctl.copy_file(src, dst)` streams in 1 MiB chunks (RSS ≤ ~1 MiB per
   copy, independent of file size), distinguishes `FileNotFoundError` from
   `PermissionError`/`OSError`, and returns a status instead of swallowing it
   (§6). It also `fsync`s the destination before returning (durability, §4.4).

4. **`synccli.sync` (`synccli.py:72-87`) — non-atomic index write.**
   `sync` writes the manifest with `open(dst_manifest_path, "w")` and
   `json.dump` (`synccli.py:85-86`). That truncates the file in place: a
   crash mid-`json.dump` leaves a half-written index that a later run's
   `json.load` (`synccli.py:78-79`) will raise on — and that raise is
   unhandled, so the run dies. `backupctl` writes the index to
   `<snapshot>/.index.tmp`, `fsync`s it, then `os.replace`s it onto
   `index.json` (§4.4).

5. **`synccli.sync` (`synccli.py:77-79`) — unreadable old manifest.**
   As above, `json.load` of a corrupt manifest raises with no recovery.
   `backupctl` handles a corrupt/absent index explicitly (§4.5, §6.4).

6. **`snaputil.prune_snapshots` (`snaputil.py:23-36`) — deletion is not
   reader-safe.** It calls `shutil.rmtree` directly on each doomed snapshot
   (`snaputil.py:34-35`). A reader that resolved a path inside that snapshot
   a millisecond earlier now gets `ENOENT`, and `rmtree` can even pull the
   file out from under a reader mid-read on some filesystems.
   `backupctl.prune_snapshots()` (§8) does the selection using
   `snaputil.list_snapshots` and the same oldest-first ordering, but deletes
   in two phases: atomic `os.rename` into `.trash-…` (POSIX: an already-open
   file descriptor keeps reading the same inode) and `rmtree` only after a
   grace period. `snaputil.prune_snapshots` itself is left untouched for
   other callers.

7. **`snaputil.is_stale` (`snaputil.py:66-73`) — not usable for liveness.**
   It compares a directory's `st_mtime` against a reference epoch. The mtime
   of a directory changes every time a child is created or removed, so a
   *live* temp directory has a fresh mtime, but so does a directory that
   happened to be touched after the dead run — and a dead run's directory
   stops changing, so the two are not distinguishable by mtime alone. Used
   for the crashed-run sweep, `backupctl` uses the run lock + pid liveness
   instead (§4.5). `is_stale` is not used for that purpose.

8. **`snaputil.snapshot_disk_usage` (`snaputil.py:39-51`) — logical vs
   physical.** It sums `st_size` of every file. With hardlink de-duplication
   between snapshots (§5.3) two snapshots share inodes, so logical bytes
   double-count shared content. `backupctl` keeps using
   `snapshot_disk_usage` for the *logical* number and adds a measured
   *physical* number (`st_blocks * 512` summed per snapshot, i.e. the bytes
   actually charged to that directory's inodes) for the disk-growth
   reporting in §10.

---

## 3. Data model and on-disk layout

### 3.1 Backup root layout

```
<backup_root>/
  config.lock                 # flock: serializes runs (see 4.2)
  locks/<snapshot>.lock       # optional reader pin (see 7.2)
  snap-20261116-231500-00/    # published snapshot (list_snapshots sees it)
      index.json              # the index (atomic, see 4.4)
      d0/... d1/...           # one subtree per source directory
      .index.tmp              # transient; only exists inside an unpublished dir
  .tmp-run-<pid>-<seq>/       # in-progress snapshot (invisible to readers)
  .trash-<name>-<ts>/         # deleted-but-not-yet-rmtree'd snapshot
```

Snapshot names are `snap-YYYYMMDD-HHMMSS-NN`, exactly the format
`snaputil.list_snapshots` (`snaputil.py:8-20`) parses, so the existing helper
lists our snapshots with no change. `NN` is a per-second run sequence number
that disambiguates two runs started in the same second — it makes a name
collision impossible without needing a uuid in the name.

`.tmp-*` and `.trash-*` directories deliberately do **not** start with
`snap-`, so `snaputil.list_snapshots` (`snaputil.py:18`) ignores them. That
is the mechanism, not a convention: a half-written run is structurally
invisible to every reader that uses the existing helper.

### 3.2 Index format

One `index.json` per snapshot, at the snapshot root. It is a JSON object:

```json
{
  "format": 1,
  "snapshot": "snap-20261116-231500-00",
  "created_epoch": 1794872100.123,
  "run": {"pid": 4711, "host": "host", "trigger": "scheduler|manual",
          "duration_s": 6.4},
  "sources": [
    {"name": "evals-run-118",
     "path": "/abs/path/to/evals/run-118",
     "subtree": "d0",
     "files": 8421,
     "bytes": 402918400}
  ],
  "entries": {
    "d0/results/summary.json": {"size": 1024, "mtime_ns": 1794866704965976463},
    "d0/raw/log.txt":         {"size": 4096, "mtime_ns": 1794866704965977000}
  },
  "missing": [
    {"path": "d0/raw/gone.txt", "source": "d0", "reason": "vanished|unreadable"}
  ]
}
```

`entries` maps *snapshot-relative* path → state, and is keyed with the same
`{"size", "mtime"}` vocabulary as `synccli.file_state` (`synccli.py:22-25`),
extended with the exact-nanosecond `mtime_ns` (override 1). `subtree` maps a
source directory to its directory inside the snapshot, so two source
directories that contain the same relative path do not collide.

The index is the *only* description of the snapshot's contents. Invariant
I1: **every path in `entries` exists in the snapshot tree with the recorded
size.** Invariant I2: **every regular file in the snapshot tree is in
`entries`.** I1 and I2 are what make "a reader never sees a half-run image"
checkable; §4.4 is how they are established.

### 3.3 Source mapping

`d0`, `d1`, …, one per configured source directory, in configuration order.
Files keep their path relative to the source root inside the subtree, so
`<src>/a/b.txt` → `<snapshot>/d0/a/b.txt`.

---

## 4. Run lifecycle

A run is: acquire lock → sweep debris → scan sources → build snapshot in a
temp dir → write index → publish atomically → prune → report.

### 4.1 Trigger-independence

There is exactly one code path. `backupctl run` is what the scheduler calls
and what a human types. The only difference is a value recorded in the index:
`run.trigger` is `"scheduler"` when `--trigger scheduler` is passed (the
cron/systemd unit does) and `"manual"` otherwise. Every behaviour below —
locking, publishing, missing-file handling, reporting, exit codes — is
identical for both, because it is the same function with the same arguments.
The run never checks the trigger to decide anything else.

### 4.2 Concurrency: two runs at once

`backupctl` takes an exclusive `flock` on `<backup_root>/config.lock` for the
whole run (scan → publish). `fcntl.flock` is advisory but is the right tool:
both runs are `backupctl` processes, so both honour it.

* If the lock is free, the run takes it and proceeds.
* If the lock is held, the run does **not** block forever: it waits up to
  `--lock-timeout` (default 0 s — i.e. it fails fast) and then exits with
  code **3** and the message `another run holds the backup lock`. A scheduler
  tick that collides with a manual run therefore costs nothing and destroys
  nothing.

Consequence: two runs never write into the backup root at the same time, so
the "which run's files are in this directory" ambiguity never arises. The
atomic publish (§4.4) is still required, because it is what protects *readers*
and what makes a *crashed* run harmless.

Concurrency cost is a lock, not a queue: a second concurrent run adds zero
work to the first and produces zero extra files.

### 4.3 Scan and change detection

For each configured source `i` with root `S_i`:

1. `backupctl.scan_files(S_i)` — the `os.walk` traversal of
   `synccli.scan_files` (`synccli.py:10-19`) **without** the hidden-dir
   filter (override 2). Sorted relative paths.
2. `backupctl.build_manifest(S_i)` — per file, `file_state_ns` (override 1):
   `{"size", "mtime_ns"}`.
3. Compare against the previous snapshot's recorded state for the same
   source, using `synccli.changed_files(old, new)` (`synccli.py:36-42`).
   `old` is the previous snapshot's index entries for that source (re-keyed
   from snapshot-relative path to source-relative path); `new` is the fresh
   scan.

A file is *copied* when it is new or its state changed
(`changed_files` semantics: `rel not in old_manifest or old_manifest[rel] != state`).
A file is *unchanged* when the recorded state is identical.

Previous snapshot = the newest published snapshot that contains state for
this source, i.e. `snaputil.list_snapshots(backup_root)[-1]` if it is
complete, else the newest one that is (§4.5).

### 4.4 Building and publishing a snapshot (the atomicity core)

The snapshot is built **out of tree**, in `<backup_root>/.tmp-run-<pid>-<seq>/`:

1. Create the temp dir (`os.makedirs`).
2. For each source: create `<tmp>/d<i>`; for each file to copy, call
   `backupctl.copy_file` (override 3: streamed, error-reporting) into
   `<tmp>/d<i>/<rel>`; for each unchanged file, create it as a **hard link**
   to the previous snapshot's copy of that file (§5.3).
3. `fsync` each written file. Measured cost: 1000 small files written +
   `fsync` took 0.13 s → **7,466 files/s** (≈ 2.7 s for 20,000 files).
4. Write the index to `<tmp>/index.json.tmp`; `json.dump`; `flush`;
   `fsync`; `os.replace` onto `<tmp>/index.json`; `fsync` the temp dir.
   (`os.replace` is atomic on POSIX and on APFS.)
5. `fsync` the temp dir itself, and every subtree directory, so the tree's
   directory entries are durable. Measured: 200 directory `fsync`s took
   0.008 s → **40 µs each**; 2000 directory renames took 0.230 s →
   **115 µs each**.
6. **Publish**: `os.rename(<tmp>, <backup_root>/snap-YYYYMMDD-HHMMSS-NN)`.
   Measured rename cost: **115 µs** (§9). This is the only moment a snapshot
   becomes visible, and it is atomic: a reader either sees the directory
   under its old name or under its new name, never partially.
7. `fsync` the backup root directory so the rename is durable.

Only after step 6 does anything treat the snapshot as real. A reader that
lists snapshots with `snaputil.list_snapshots` sees only published ones,
because the in-progress directory is named `.tmp-*`.

**Invariant I1/I2 are established by construction**: the index is written
from the same in-memory set that drove the copies, and the copy step reports
every file it failed on, so an entry exists in the index only if the file was
successfully written to the temp tree. The index cannot promise a file the
snapshot lacks. Conversely, every file in the temp tree was written by the
copy step (or linked) and recorded, so I2 holds.

### 4.5 The run may die at any point

A run can die between any two of the steps above. The states and the
recovery:

| Died at | What is left on disk | Who can see it | Recovery |
|---|---|---|---|
| before step 1 | nothing | nobody | nothing to do |
| during copies | `.tmp-run-<pid>-<seq>/` with partial files | nobody (`list_snapshots` ignores `.tmp-`) | swept at the start of the next run (§4.5.1) |
| during index write | `.tmp-run-…/index.json.tmp` (half-written) | nobody | swept with the temp dir; `index.json` never existed, so no corrupt index was ever published |
| after `os.replace` of the index, before rename | complete tree + valid index inside `.tmp-run-…` | nobody | swept; the next run rebuilds from scratch — the temp dir is *not* promoted, because we cannot know whether the process died before or after the copies were all durable. Correctness over effort: the next run makes progress from the previous published snapshot, not from this debris. |
| during the rename | either old name or new name, never both, never neither (POSIX rename is atomic) | readers see a complete snapshot | nothing to do |
| after rename, before the root `fsync` | snapshot may vanish after a power loss, but was complete while it existed | readers | next run simply produces a new snapshot; retention count may drop by one |

**4.5.1 Sweeping debris.** At the start of a run, *after* taking the lock
(so no live run is touched), `backupctl` lists `<backup_root>` for entries
matching `.tmp-run-*` and `.trash-*` and decides which are dead:

* A `.tmp-run-<pid>-<seq>` is dead iff the pid it carries is not alive on
  this host *and* its mtime is older than `--stale-after` (default 3600 s).
  The pid check alone is unsafe (pids are reused, and the run may be on
  another host); the age check alone is unsafe (a long full backup of a
  1 GB tree can exceed an hour). Requiring **both** makes a false "dead"
  verdict require both a recycled pid and an old mtime.
* The selection is done with `synccli.collect_stale` (`synccli.py:45-59`),
  which takes `(path, fresh)` pairs and returns those not fresh and not
  already seen — exactly the semantics needed.
* `.trash-*` directories are `rmtree`'d once they are older than the
  trash grace period (§8).

Sweep cost: one `os.scandir` of the backup root plus one `kill(pid, 0)`
per candidate — O(number of snapshots), independent of tree size.

**4.5.2 A corrupt or half-written index is found in a *published* snapshot.**
This can only come from external damage (disk error, a hand edit, a
filesystem that lost the last write) — the publish path cannot produce one
(§4.4). Recovery rule, applied whenever `backupctl` reads the previous
snapshot's index (`run`, `verify`, `prune`):

* **What is discarded:** the corrupt index file. It is renamed to
  `index.json.corrupt` (not deleted — the damage is evidence) and the run
  reports `index corrupt: <snapshot> — re-derived from the tree`.
* **What is re-derived:** the state of every regular file in that snapshot's
  tree, by `os.stat`ing each file (the same information `build_manifest`
  collects, `synccli.py:28-33`). The re-derived manifest is used as the
  "previous" state for change detection, so the next run copies only files
  that differ from what is actually on disk.
* **What the run reports:** one warning line naming the snapshot and the
  action, and a non-zero-warning status in the JSON report (`warnings:
  ["index-recovered:snap-20261116-231500-00"]`). The run continues; it does
  not abort, because the tree itself is intact and usable.
* **A half-written index inside a `.tmp-run-*` dir** needs no special case:
  the whole temp dir is discarded (§4.5.1).

---

## 5. Change detection: what "unchanged" means

### 5.1 Granularity

**Per file, by `(size, mtime_ns)`.** A file is considered unchanged between
two snapshots iff the byte size is equal *and* the last-modified timestamp is
equal to the nanosecond. This is the same predicate as
`synccli.changed_files` (`synccli.py:36-42`) over `synccli.file_state`
(`synccli.py:22-25`), with the nanosecond-exact timestamp of override 1.

Directories are not tracked individually; a directory's contents are tracked
through its files, so creating or deleting an empty directory is **not**
detected as a change and an empty directory is **not** reproduced in the next
snapshot. (Stated as a known limit: the backup is of file content, plus the
directory skeleton needed to hold it. `synccli.scan_files` only ever returns
files (`synccli.py:16-18`), so directory-level metadata was never part of
this manifest vocabulary.)

### 5.2 What this granularity misses

* **Content changed with identical size and identical mtime.** An editor or
  tool that rewrites a file and restores the original mtime (`os.utime`) is
  invisible. Same for a filesystem with 1 s or 2 s mtime granularity
  (FAT32, HFS+): two writes in the same tick with the same length look
  unchanged.
* **mtime preserved across tools that rewrite in place** (e.g. some archive
  extractors).
* **Content changed with a different size but the same mtime** — detected, no
  issue.
* **A file replaced by a different file with identical size and mtime** —
  indistinguishable; nothing in a size+mtime manifest can distinguish it.

Mitigation that stays inside the stated granularity: `backupctl` records
`mtime_ns` (exact) rather than seconds, which shrinks the blind window from
"1 s" to "the file was rewritten and its mtime was deliberately restored".

### 5.3 Unchanged files are hard-linked, not copied

For each unchanged file, `backupctl` creates a hard link in the new snapshot
pointing at the *same inode* as the previous snapshot's copy. Consequences:

* **Disk**: a run that changes nothing costs **0 bytes** of new disk. Per-run
  disk growth = bytes of changed/new files only (plus the index, ≈ 75 bytes
  per file — measured 1.5 MB for 20,020 entries — plus filesystem overhead).
* **Time**: linking is a metadata operation. Measured: 20,000 `os.link`
  calls took 6.72 s (≈ 2,980 links/s), plus 0.055 s to create the 200
  directories. This is *not* faster than copying the same tree (5.81 s,
  §9) — hard links are bought for disk, not for time.
* **Requirements**: source and destination must be on the same filesystem
  (`link()` returns `EXDEV` otherwise). `backupctl` detects `EXDEV`/`EPERM`
  and falls back to a real copy of that file, recording the fallback in the
  run report (`hardlink_fallbacks: N`). The link source is always the
  *previous snapshot's* file, never the live source file — so the snapshot
  never shares an inode with the user's working tree, and a later edit of the
  user's file cannot alter a published snapshot.
* **Independence**: because a snapshot's files are hard links into the
  *previous snapshot's* inodes, and pruning a snapshot only removes directory
  entries, the data survives until the last link is gone. Pruning the
  previous snapshot does not damage the new one.
* **Reader contract**: a snapshot's files must be treated as read-only. The
  restore tool copies files out; it must not open them for writing in place,
  because that would modify the inode shared with other snapshots. This is
  stated in §7.

---

## 6. Source files that disappear or cannot be read

### 6.1 The cases

Between the scan and the copy, a source file may (a) vanish, (b) be replaced
by a directory, (c) be unreadable (permissions, EIO), (d) be truncated to zero
bytes while being written.

### 6.2 What the snapshot contains

The file is **omitted** from the snapshot, and the path is **not** in
`index.entries`. The snapshot therefore never contains a half-copied file:
`backupctl.copy_file` (override 3) copies into a temporary name inside the
destination directory and `os.replace`s it into place only after the copy
succeeded; a failed copy leaves no partial file (the temp name is removed).

The omission is recorded in `index.missing` with a reason (`vanished`,
`unreadable`), so the index remains a truthful description: I1 and I2 both
still hold (I2 holds because the partial file was removed; I1 holds because
the failed file is not in `entries`).

### 6.3 What the run reports

* A warning line per missing file: `missing: d0/raw/gone.txt (vanished)`.
* The run's JSON report carries `missing: [...]` and `files_copied`,
  `files_linked`, `files_skipped`.
* **Exit code 4** = "the snapshot was produced and is valid, but some source
  files could not be captured". Exit code 0 = complete capture. Any other
  non-zero code = no valid snapshot was produced.
* The same behaviour for scheduler and manual runs — the trigger is not
  consulted (§4.1).

### 6.4 Re-running repairs the omission

Because the previous snapshot's index simply does not list the missing file,
the next run's `changed_files` comparison sees it as new and copies it. The
omission is therefore self-healing on the next run, without any cleanup
step.

### 6.5 Files that change *while* being copied

If a file's `mtime`/`size` differs between the pre-copy stat and the
post-copy stat, the copy may be torn (a mix of old and new content). Two
guards:

1. After copying, `backupctl` re-`stat`s the source. If `(size, mtime_ns)`
   changed, the copy is discarded and re-copied once; if it changes again, the
   file is recorded as `missing` with reason `unstable` and the run reports
   it. The snapshot then never contains a torn file — it contains either a
   complete file or none.
2. The recorded index entry is the **post-copy** state, so the next run
   compares against what was actually captured and re-copies if the source
   moved again.

---

## 7. Reading a snapshot (the contract with the restore tool)

### 7.1 Rules for a reader

1. **Enumerate with `snaputil.list_snapshots(backup_root)`** — it returns
   only published snapshots (`.tmp-*`/`.trash-*` are invisible by name).
2. **Read `index.json` from the snapshot root.** Do not infer contents from
   the directory tree alone; the index is the authoritative list. (The tree is
   a superset check: I2 says the two agree.)
3. **Map paths with `snaputil.safe_snapshot_path(backup_root, snapshot,
   rel)`** (`snaputil.py:54-63`) — `..` segments are normalized away, so a
   hostile or corrupt index entry cannot make the reader copy from outside
   the snapshot.
4. **Open files read-only and copy them out.** Never open a snapshot file
   for writing (§5.3 — hard-linked inodes).

### 7.2 Readers racing the pruner

`backupctl` deletes snapshots in two phases (§8): rename to `.trash-…`
(atomic; an already-open file descriptor keeps reading the same inode) and
`rmtree` after a grace period. A reader that resolved a path *before* the
rename and opens it *after* the rename will get `ENOENT`. To make that
impossible, `backupctl` supports an optional reader pin:

* A reader creates `<backup_root>/locks/<snapshot>.lock` and takes a shared
  `flock` on it for the duration of the read.
* The pruner takes a **non-blocking exclusive** `flock` on the same file
  before renaming. If the lock is busy, the pruner **skips that snapshot
  this round** (leaves it in place) and reports `prune_skipped: <name>
  (in use)`. It is retried on the next run.

Without a pin, the guarantee degrades to: the reader either opened the file
(→ safe, POSIX keeps the inode alive) or gets a clean `ENOENT` and knows the
snapshot was pruned. With a pin, the reader is guaranteed a stable tree for
the whole read. Both are better than `snaputil.prune_snapshots`'s direct
`rmtree`, which can unlink files under a reader mid-read.

### 7.3 Readers racing a *new* run

A new run never modifies a published snapshot. Snapshots are immutable once
published; the only mutation of a published tree is the eventual removal of
its directory entry during pruning, which §7.2 covers. A reader therefore
never sees "some files from this run, some from the previous one": the run
writes into a temp directory and the whole directory is renamed into place.

---

## 8. Retention and safe deletion

**Policy** (configurable, defaults in brackets):

* `keep` — keep the newest **K** snapshots [7]. Older ones are candidates
  for deletion.
* `min_keep` — never delete below **1** snapshot [1]. The user always has at
  least one usable snapshot.
* The snapshot just published by the current run is **never** a deletion
  candidate in the same run.
* `trash_grace_seconds` — how long a deleted snapshot stays in `.trash-…`
  before `rmtree` [3600 s]. During the grace period its files are still
  reachable by anyone holding an open descriptor or an old path.
* `trash_max_bytes` — the total size of `.trash-…` is capped [5 % of the
  backup root's logical size]; the oldest trash is emptied first when the
  cap is exceeded.

**Selection** reuses `snaputil.list_snapshots` (`snaputil.py:8-20`) and its
oldest-first ordering (`snaputil.py:20` sorts the names lexicographically,
which for the `snap-YYYYMMDD-HHMMSS-NN` format is chronological order). The
doomed set is `names[:-keep]` — the same expression as
`snaputil.prune_snapshots` (`snaputil.py:31-33`), and the same guarantee that
the newest snapshot is never deleted (`snaputil.py:26-28`).

**Deletion** (override 6, the reason `snaputil.prune_snapshots` is not used
directly) proceeds as:

1. Take the reader lock for the snapshot non-blockingly; if busy → skip and
   report (§7.2).
2. `os.rename(<root>/snap-X, <root>/.trash-X-<epoch>)` — atomic; readers
   with open descriptors are unaffected.
3. Schedule the `.trash-*` directory for `rmtree` once it is older than
   `trash_grace_seconds`. The sweep happens at the start of the next run.

**"Never leave the user without a usable snapshot"** is enforced twice: by
`keep ≥ min_keep ≥ 1` in the selection step, and by the rule that the
snapshot published by the current run is excluded from the doomed set. A run
therefore always ends with at least one published, complete snapshot.

---

## 9. Performance budget — the first full backup

### 9.1 The measurement (taken in this directory)

Machine: macOS (darwin), Python 3.10.11 (Clang 13), 14 CPUs, 38 GiB RAM,
APFS. Tree built for the measurement: **20,020 files / 1,046,609,920 bytes
(1.047 GB)** — 20,000 files of 4 KiB in 200 directories plus 20 files of
46 MiB.

| Operation | Measured | Constant |
|---|---|---|
| `synccli.build_manifest` over the tree | **0.69 s** | 29,071 files/s |
| `synccli.sync` — full copy of the whole tree + manifest | **5.81 s** | 180.1 MB/s |
| re-scan + `synccli.changed_files` (nothing changed) | **0.47 s** | — |
| `os.stat` × 20,020 | 0.42 s | 47,700 stats/s |
| `json.dump(manifest, indent=2)` | 0.05 s | 1.5 MB for 20,020 entries (75 B/entry) |
| `json.dump(manifest)` compact | 0.04 s | 1.3 MB |
| `json.load(manifest)` | 0.01 s | — |
| `copy_file` of one 46 MiB file | 0.02 s | peak RSS **81.2 MB** (whole-file read — override 3) |
| write + `fsync` of 1,000 small files | 0.13 s | 7,466 files/s |
| `fsync` of a directory | 40 µs | 200 in 0.008 s |
| `os.rename` (directory) | 115 µs | 2,000 in 0.230 s |
| `os.link` × 20,020 | 6.72 s | 2,980 links/s |
| creating 200 directories | 0.055 s | 3,600 dirs/s |
| `shutil.copyfile` with a thread pool | w=1: 9.20 s, w=4: **3.29 s**, w=8: 3.23 s | 14 CPUs available |
| manifest dict in memory | **+9.2 MB RSS** for 20,020 entries | 460 B/entry |

### 9.2 The budget

**Budget: the first full backup of a ~1 GB tree (≈ 20,000 files) completes in
≤ 20 seconds of wall-clock, on this machine, for a single run with no other
run contending.**

Derivation (all components measured above, single-threaded):

| Component | Time |
|---|---|
| scan + stat (manifest build) | 0.69 s |
| copy 1.047 GB of file data | 5.81 s |
| fsync of every written file (20,020 files) | 2.68 s (20,020 / 7,466) |
| write + fsync the index (1.5 MB) | 0.06 s |
| directory fsyncs (~220 dirs) | 0.01 s |
| publish rename + root fsync | 0.12 ms |
| **total** | **≈ 9.25 s** |
| **budget** | **20 s** (≈ 2.2× headroom) |

The headroom covers the three things the measurement cannot: a cold page
cache (the measurement ran warm), the scheduler running other work
concurrently on the same 14 CPUs, and a machine with a slower disk. The
number is not a guess: it is 2.2× a measured sum of components.

**Optional acceleration**: the copy phase parallelises well — measured 3.29 s
at 4 threads vs 9.20 s at 1 thread for `shutil.copyfile` over the same tree
— which would bring the total to ≈ 6.8 s. The default is single-threaded
(≤ 20 s already met); `--concurrency K` (default 1) enables the pool. It is
opt-in because the thread pool raises the fsync ordering complexity and the
budget does not require it.

### 9.3 Cost of later runs

A run with nothing changed costs: scan + stat (0.69 s) + `changed_files`
(negligible) + 20,020 hard links (6.72 s) + index write (0.06 s) + publish
(0.12 ms) ≈ **7.5 s**, and **0 bytes** of new disk (apart from the index).
A run with 1% of files changed costs the same plus 1% of the bytes in copy
time (≈ 0.06 s per 1% of 1 GB at 180 MB/s).

---

## 10. How the numbers scale

Let `N` = number of source directories (3 now, ≤ ~36 planned), `F_i` =
files in source `i`, `F = Σ F_i` = total files, `B = Σ` bytes,
`C` = bytes of changed/new files in this run, `F_new` = new files,
`U` = unchanged files (`F − F_new − F_changed`).

### 10.1 Per-run work

| Resource | Cost | Bound |
|---|---|---|
| Traversal + stat | `F / 29,071 s` (measured) | **O(F)** — 1 GB / 20k files ⇒ 0.69 s |
| Change detection | `O(F)` dict comparisons | **O(F)**, ~0.01 s per 20,000 entries |
| Copy | `C / 180 MB/s` (measured) | **O(C)**, 0 bytes when `C = 0` |
| Hard-link unchanged | `(F − F_new) / 2,980 s` (measured) | **O(F)** |
| Index write | `0.05 s + 75 B × F` | **O(F)** bytes |
| Publish | 1 rename + 1 dir fsync = **115 µs + 40 µs** | **O(1)** in F and N |
| Prune | one `os.scandir` + `rmtree` of doomed snapshots | **O(N_snapshots + deleted bytes)** |
| Lock | one `flock` | **O(1)** |

Nothing in the per-run cost is super-linear in `N` or `F`. The **only**
super-linear term is `rmtree` of deleted snapshots, which is proportional to
the bytes being deleted — inherent to deleting data.

### 10.2 Memory

| Item | Bound |
|---|---|
| Source manifest (in memory) | **460 B × F** (measured: 9.2 MB for 20,020 entries) → 1 GB / 20k-file tree ⇒ **≈ 9.2 MB**; 100k files ⇒ ≈ 46 MB |
| Previous snapshot's index (loaded from disk) | same, **460 B × F** — loaded one source at a time in `backupctl` (§10.4), so the peak is `460 B × max(F_i) + 460 B × F_prev_loaded` |
| Copy buffer | **1 MiB per concurrent copy** (override 3, vs 81.2 MB measured for `copy_file` on a 46 MiB file) |
| Per-snapshot index file on disk | **75 B × F** (measured 1.5 MB for 20,020 entries) |

Total peak RSS for a 1 GB / 20k-file tree with `--concurrency 1`:
**≈ 9.2 MB (current manifest) + 9.2 MB (previous index) + 1 MiB (copy
buffer) + Python interpreter ≈ 30 MB** — independent of `B` (file size),
because nothing is read whole except the index.

### 10.3 Disk

| Item | Growth |
|---|---|
| First full backup of source `i` | `B_i` bytes (a real copy) |
| Every later run | **`C` bytes** (changed files only) + `75 B × F` (the new index) — unchanged files are hard links (§5.3) and cost 0 bytes |
| Steady state with `K` snapshots retained | `B + (K−1) × C_max` bytes of data (the `K−1` older snapshots share the unchanged inodes with the newest) + `K × 75 B × F` of indexes |
| Deleting a snapshot | frees bytes only for inodes whose last link was in the deleted snapshot |

So for the current workload (3 dirs, ~1 GB total, K = 7, 1 % changed per
run): steady-state disk ≈ **1 GB + 6 × 10 MB + 7 × 1.5 MB ≈ 1.07 GB**, and
**per-run growth ≈ 10 MB** (the changed bytes) + 1.5 MB (the index) ≈
**11.5 MB**. At 24 runs/day that is ≈ 276 MB/day of index plus changed bytes
— the index is the dominant term, and it is 75 B/file because it is
JSON (`synccli`-compatible). For 36 directories at 20k files each (720k
files), the index for one snapshot is 720,000 × 75 B = **54 MB** and the
per-snapshot memory to build it is **331 MB** (460 B × 720,000) — the point
at which the in-memory manifest must be streamed rather than held whole.
§10.4 states the mitigation.

### 10.4 What stays flat

* **Flat in `N`**: the number of locks (1), the publish cost (1 rename),
  the number of temp dirs (1), the number of indexes (1 per snapshot, not
  per source). Per-source work is additive.
* **Flat in `B` (bytes)**: memory does not depend on file size (streamed
  copy, 1 MiB buffer) — the only `B`-dependent quantity is the copy *time*
  and the disk bytes, both of which are unavoidable and linear.
* **Flat in the number of snapshots**: the prune cost is
  `O(snapshots)` for listing plus the bytes actually deleted.
* **Linear in `F`** (unavoidable: the tool must look at every file to know
  whether it changed) — with the explicit constant measured above
  (29,071 files/s for scan+stat, 2,980 links/s, 7,466 fsync'd files/s).

**Mitigation for large `F`** (stated because 36 dirs × 20k files is a
planned, not hypothetical, scale): when `F > 200,000`, `backupctl` processes
sources one at a time and writes each source's index entries to a
per-source temporary file on disk, merging them into the final index by
streaming, rather than holding all `F` entries in one dict. Peak memory
becomes `460 B × F_max_single_source + O(1)` instead of `460 B × F`. The
merge is a concatenation of sorted JSON fragments — no sorting cost
super-linear in `F`.

---

## 11. CLI surface

```
backupctl run [--config PATH] [--root DIR] [--dir NAME=PATH ...]
              [--keep K] [--concurrency K] [--trigger scheduler|manual]
              [--dry-run] [--json]
backupctl list  [--root DIR] [--json]          # list published snapshots + sizes
backupctl verify [--root DIR] [--snapshot NAME] # check index vs tree (I1/I2)
backupctl prune [--root DIR] [--keep K] [--json] # retention, two-phase
backupctl gc    [--root DIR]                    # sweep dead temp dirs + old trash
backupctl status [--root DIR] [--json]          # config, last run, disk usage
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | success, complete capture |
| 1 | error — no valid snapshot produced |
| 2 | usage error |
| 3 | another run holds the lock (colliding run; nothing done, nothing damaged) |
| 4 | a valid snapshot was produced, but some source files were missing/unreadable |

`run` is the only command that writes snapshots. `list`, `verify`, `status`
are read-only. `prune` and `gc` only delete, and only what §8 permits.

**Configuration file** (JSON, `--config`):

```json
{
  "backup_root": "/var/backups/evals",
  "keep": 7,
  "min_keep": 1,
  "trash_grace_seconds": 3600,
  "trash_max_bytes_fraction": 0.05,
  "lock_timeout": 0,
  "stale_after": 3600,
  "concurrency": 1,
  "sources": [
    {"name": "run-118", "path": "/abs/evals/run-118"},
    {"name": "run-119", "path": "/abs/evals/run-119"}
  ]
}
```

---

## 12. Test plan (mapped onto the existing suite)

The existing suite is `test_synccli.py` (6 tests, all passing,
`python3 -m unittest`). `backupctl` ships `test_backupctl.py` and does not
modify `synccli.py`/`snaputil.py`/`test_synccli.py`.

| Requirement | Test |
|---|---|
| Base of the code works | keep `test_synccli.py` green (it must be, since `synccli` is unmodified) |
| Two runs colliding | start run A with the lock held (a helper process holds `flock`), start run B → B exits 3; A's snapshot is complete |
| Reader never sees a partial snapshot | while a run is in its copy phase, poll `snaputil.list_snapshots` → either the old set or the old set + one complete snapshot; the new snapshot's index passes `verify` (I1/I2) at every poll |
| Crash mid-run | `SIGKILL` a run during copying → the backup root contains no `snap-*` dir for it; the next run sweeps the `.tmp-run-*` dir and completes normally |
| Corrupt index | corrupt a published snapshot's `index.json` → next run reports `index-recovered`, re-derives from the tree, and completes; the corrupt file is preserved as `index.json.corrupt` |
| Missing source file | delete a file between scan and copy (a hook in the copy path) → the snapshot omits it, `index.missing` records it, exit code 4; the next run copies it (self-healing) |
| Unchanged detection | run twice → the second run reports `files_copied == 0`, `files_linked == F`; touch a file's mtime → it is re-copied |
| Nanosecond mtime | rewrite a file with the same size within the same second → detected as changed (this is the `file_state` → `file_state_ns` override) |
| Retention | create 10 snapshots with `keep=3` → 7 are deleted, the newest 3 survive, at least one usable snapshot always remains |
| Safe deletion under a reader | reader holds a shared lock on a snapshot → `prune` skips it and reports `prune_skipped` |
| Hard links | after an unchanged run, `os.stat` on the file in both snapshots → same `st_ino` |
| `EXDEV` fallback | put the backup root on a different filesystem → link fails → the file is copied and the fallback is counted |
| `safe_snapshot_path` | an index entry containing `../..` maps inside the snapshot (`snaputil.py:54-63`) |

---

## 13. Open decisions / risks

1. **Hard links vs. copies.** Hard links make the "unchanged" requirement
   cheap in disk but make snapshots share inodes (§5.3), which forbids
   in-place modification of a snapshot file and makes
   `snapshot_disk_usage` report logical bytes that exceed physical bytes.
   Mitigation: physical usage is reported separately (§2.2 override 8), and
   the restore tool copies out read-only (§7.1).
2. **mtime-based change detection cannot be made content-exact** without
   hashing every file, which would cost `B` per run instead of `C` — the
   opposite of the brief's requirement. The design therefore states the
   granularity and its blind spot (§5.2) rather than claiming exactness.
   If a future requirement demands content-exactness, the natural insertion
   point is `changed_files` (`synccli.py:36-42`): replace the state
   comparison with a content hash comparison, leaving the copy/link path
   unchanged.
3. **Index size.** 75 B/file of JSON is the dominant per-run disk cost at
   large `F`. A binary or compressed index would cut it ~10×; it is not
   needed at today's scale (1.5 MB/snapshot) and would break the
   `synccli`-compatible JSON format, so it is deferred.
4. **The `--concurrency` pool** is opt-in because the fsync ordering and
   error-reporting paths become more complex, and the budget does not need
   it (§9.2).
5. **The restore tool is out of our control.** §7 states the contract; if
   the existing restore tooling resolves snapshot paths without holding a
   pin, it can still lose a race with the pruner. The pin mechanism (§7.2)
   is the mitigation and must be adopted by that tool to be effective.

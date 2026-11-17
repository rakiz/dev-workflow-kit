# DESIGN — `backupctl` (fixture D1)

A command-line backup tool for the `evals/` workflow: it covers a configured
set of source directories, produces point-in-time snapshots under a backup
root, and is safe under concurrent runs, crashing runs, disappearing source
files and concurrent readers.

This document is grounded in the code that already exists in this directory
(`synccli.py`, `snaputil.py`, `test_synccli.py`). Every reuse and every
override is named with a file, a function and line numbers. Every number in
the performance and scaling sections was measured on this machine, or derived
from a measured constant; the measurement commands are given so the numbers
can be re-derived.

---

## 1. Scope, goals, non-goals

### 1.1 What it does

```
backupctl run      [--config F] [--only DIRID]... [--dry-run] [--json]
backupctl list     [--config F]
backupctl verify   SNAPSHOT [--hash]
backupctl prune    (--keep K | --keep-days D) [--config F]
backupctl gc       [--config F]
backupctl status   [--config F]
backupctl path     SNAPSHOT RELPATH [--config F]
```

`backupctl` backs up N configured directories. Each run produces exactly one
snapshot: a directory under the backup root containing a copy of every
configured source directory, plus an index describing exactly what that
snapshot contains.

### 1.2 Goals (one line each, with the mechanism that delivers it)

| # | Requirement | Mechanism | Section |
|---|---|---|---|
| G1 | Two runs may execute at the same time without corrupting anything | per-run staging directory + exclusive run lock + atomic publish by `rename` | §5, §6 |
| G2 | A reader never has to ask whether the run finished | a snapshot name exists ⟺ the snapshot is complete (atomic rename publish) | §6.2 |
| G3 | A killed run leaves nothing a reader could mistake for a snapshot | nothing is published until the last step; abandoned staging dirs are invisible and GC'd | §7.1 |
| G4 | A dead run's half-written/corrupt index is recoverable | atomic index writes (defensive) + explicit rebuild-from-tree recovery + report | §7.2 |
| G5 | A source file may vanish or be unreadable | the snapshot contains what was copied; the index lists only what is present; the run reports the gap | §8 |
| G6 | The backup root only grows; retention deletes safely | retention policy with `keep ≥ 1`, never deleting the newest, per-snapshot locks, rename-to-trash then delete | §9 |
| G7 | Unchanged files are not copied again | per-file key `(size, mtime_ns, mode)` + hardlink reuse from the baseline snapshot | §10 |
| G8 | The first full backup of ~1 GB / tens of thousands of files has a stated budget | §11 (measured 13.6 s; budget 20 s) |
| G9 | Every growth claim is an explicit bound | §12 (formulas over N, F, B, ΔB) |

### 1.3 Non-goals

* **Not a filesystem snapshot.** `backupctl` guarantees that each snapshot is
  *self-consistent* (index ⟺ content) and that every file it contains is
  byte-correct as of its own copy. It does **not** guarantee an atomic view
  of the source: a file that changes during the scan is copied in its
  post-change state, and the source is read file-by-file over a window of
  time. Filesystem-level point-in-time semantics (`APFS`/`ZFS`/`btrfs`
  snapshots) are a different tool.
* **Not an archive format.** Snapshots are plain directories of real files,
  so `cp -a`, `rsync`, `tar` and `snaputil.py` all work on them.
* **Not a de-duplicating store.** Unchanged files are shared between
  snapshots by hardlink (one inode, N directory entries). There is no
  content-addressed blob store and no per-blob refcounting.
* **Not a restore tool.** Restore is separate tooling; `backupctl` defines
  the contract that tooling must honour (§6.4) and ships the safe path
  resolution with it (`backupctl path`).

---

## 2. Grounding: what is reused, what is overridden

### 2.1 Reused as-is

| Symbol | Location | Used for |
|---|---|---|
| `synccli.scan_files(root)` | `synccli.py:10-19` | traversal of a source tree → sorted relative paths |
| `synccli.changed_files(old, new)` | `synccli.py:36-43` | the changed-file set between the baseline index and the current scan |
| `synccli.collect_stale(items, seen)` | `synccli.py:45-59` | computing "removed since baseline" entries for the report |
| `synccli.build_manifest(root)` | `synccli.py:28-33` | the fast path of the scan phase (see §2.2, `file_state`) |
| `snaputil.list_snapshots(backup_root)` | `snaputil.py:8-20` | enumerating published snapshots (oldest first) |
| `snaputil.snapshot_disk_usage(root, name)` | `snaputil.py:39-51` | reporting the logical size of a snapshot before it is deleted |
| `snaputil.is_stale(dir, ref_epoch)` | `snaputil.py:66-73` | *not* used for retention — see §9.2; reused only to age abandoned staging dirs (§7.1) |

`snaputil.list_snapshots` is the reason the layout in §4 works: it accepts
only directories whose name starts with `snap-` (`snaputil.py:18`), so
staging, trash and lock directories are invisible to it, to
`snaputil.prune_snapshots`, and to `snaputil.main`. Verified:
`list_snapshots()` on a root containing `.staging/run1` returns `[]`.

### 2.2 Overridden, and why

Every override below names the exact function and the exact behaviour that is
replaced. None of these is "current behaviour" in the abstract.

| Existing symbol | Location | Behaviour today | `backupctl` behaviour | Reason |
|---|---|---|---|---|
| `synccli.sync` (manifest write) | `synccli.py:85-86` | writes `json.dump(src_manifest)` of the **source** manifest after copying, unconditionally | the index is built from what **landed** in the snapshot; per-file status is recorded | `copy_file` swallows `OSError` (`synccli.py:67-69`), so the source manifest can list files that were never copied. G5 requires that the index never promises a file the snapshot lacks. |
| `synccli.sync` (manifest write mechanism) | `synccli.py:85-86` | `open(path, "w")` truncates the old index and streams the new one into it | write to `*.tmp` in the same directory, `fsync`, then `os.replace` | a process killed during `json.dump` leaves a truncated JSON file — precisely the "half-written index" G4 asks about. `os.replace` is atomic on POSIX. |
| `synccli.copy_file` (whole-file read) | `synccli.py:66-67` | `fdst.write(fsrc.read())` reads the **entire** file into memory | 64 KiB chunked copy | memory must not scale with the largest file (§12). |
| `synccli.copy_file` (error handling) | `synccli.py:67-69` | `except OSError: pass` — the file is silently skipped and the run continues | classify the error (`ENOENT` → vanished, `EACCES` → unreadable, other → error), record it, report it | G5 requires the run to *say* what the snapshot lacks, identically for a scheduled and a human run. |
| `synccli.file_state` | `synccli.py:22-25` | `os.stat` (follows symlinks) | `os.lstat`-based state + explicit symlink handling | `build_manifest` raises `FileNotFoundError` on a dangling symlink. **Verified**: a tree containing one dangling symlink makes `synccli.build_manifest(t)` raise `FileNotFoundError: .../dangling`. A backup tool must not crash on a broken symlink. |
| `synccli.scan_files` (scope) | `synccli.py:10-19` | returns **files** only; drops empty directories; excludes dot-directories (`synccli.py:14`) but includes dot-files | wrapped by `backupctl.scan_tree()`, which additionally records directories (so empty dirs survive a restore) and offers `--include-hidden` to stop excluding dot-directories | the exclusion itself is deliberate and inherited; the loss of empty directories is not, and a restore must reproduce the tree. |
| `snaputil.prune_snapshots` | `snaputil.py:23-36` | deletes in place with `shutil.rmtree` (`snaputil.py:35`); `keep=0` deletes **every** snapshot | `keep` is clamped to ≥ 1; deletion is rename-to-trash then delete; snapshots that a reader holds are skipped | **Verified**: `prune_snapshots(root, 0)` deletes all snapshots and leaves `list_snapshots(root) == []`. G6 forbids leaving the user without a usable snapshot, and forbids deleting a snapshot someone is reading. |
| `snaputil.safe_snapshot_path` | `snaputil.py:54-63` | `os.path.normpath` keeps leading `..` | `backupctl` ships its own traversal-safe join | **Verified**: `safe_snapshot_path("/backup", "snap-1", "../../etc/passwd")` returns `"/backup/snap-1/../../etc/passwd"`, which resolves outside the snapshot — the docstring's "never points outside" claim does not hold for paths that *start* with `..`. A restore reading an index entry could be pointed outside the snapshot root. |
| `snaputil.is_stale` | `snaputil.py:66-73` | directory `mtime` as an age signal | not used for retention | the snapshot directory's `mtime` changes as content is added and removed; it is not the snapshot's age. Age comes from the snapshot name's timestamp and from `created_utc` in the index. |

`snaputil.list_snapshots` and `snaputil.snapshot_disk_usage` are used
unchanged; `snaputil.prune_snapshots` and `snaputil.safe_snapshot_path` are
used as the *model* for the new implementations rather than called
directly, for the reasons in the table.

---

## 3. Configuration

`backupctl` reads a JSON config (`--config`, default
`~/.config/backupctl/config.json`):

```json
{
  "backup_root": "/var/backups/evals",
  "keep": 7,
  "keep_days": 30,
  "mode": "link",
  "verify_hash": false,
  "sources": [
    { "id": "evals-2026a", "path": "/repo/evals/2026a" },
    { "id": "evals-2026b", "path": "/repo/evals/2026b" }
  ]
}
```

| Key | Default | Meaning |
|---|---|---|
| `backup_root` | required | where snapshots live; must be on one filesystem (it holds the staging area and the snapshots) |
| `keep` | 7 | number of newest snapshots always kept (§9); clamped to ≥ 1 |
| `keep_days` | 30 | age floor: a snapshot younger than this is never deleted |
| `mode` | `"link"` | `link` = reuse unchanged files by hardlink from the baseline snapshot; `copy` = copy every changed file and never share inodes |
| `verify_hash` | false | add a SHA-256 content hash to the change key (§10.3) |
| `sources[].id` | required | unique, must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`; it is a directory name inside the snapshot, so `..` and `/` are rejected at config load |
| `sources[].path` | required | absolute path of the directory to back up |

`--only DIRID` restricts a run to a subset of `sources` (the snapshot then
contains only those directories; the index records which ones were in scope,
so a later restore can tell).

---

## 4. On-disk layout

```
<backup_root>/
  snap-20261117-114233-00/          published snapshot (complete, immutable)
    evals-2026a/                    content of source id evals-2026a
      run-0001/result.json
    evals-2026b/
      ...
    index/
      evals-2026a.json              per-directory index
      evals-2026b.json
      snapshot.json                 snapshot-level metadata (dir list, counts, completeness)
  .staging/
    20261117T114233.412Z-8123-a91c/ run scratch area (never visible to readers)
      ...content...
      index/...
      .lock                         flock held by the owning run for the whole run
  .trash/
    snap-20261117-100000-00-20261117T120000Z/   deleted snapshot awaiting rmtree
  .locks/
    root.lock                       root-level critical sections (naming, baseline choice, prune)
    snap-20261117-114233-00.lock    per-snapshot lock (readers shared / pruner exclusive)
  .reports/
    20261117T114233.412Z-8123-a91c.json
```

Rules:

* **Snapshot names** keep the format `snaputil.list_snapshots` documents
  (`snaputil.py:9-13`): `snap-YYYYMMDD-HHMMSS-NN`, where `NN` is a
  2-digit sequence. Fixed width keeps the lexicographic sort in
  `snaputil.py:20` equal to chronological order. `NN` is allocated under the
  root lock at publish time, so names order by *publication*, and two
  concurrent runs publishing in the same second get `00` and `01` in
  publication order. If all 100 slots of a second are taken, the run waits
  for the next wall-clock second (a documented, bounded back-pressure: 100
  runs/second is far above the scheduler's rate).
* **Staging is not a snapshot.** `.staging/…` and `.trash/…` do not start
  with `snap-`, so `snaputil.list_snapshots` (`snaputil.py:18`),
  `snaputil.prune_snapshots` and `snaputil.snapshot_disk_usage` ignore them
  (verified).
* **The index lives inside the snapshot.** Publish is a single `rename` of
  the whole staging directory, so content and index become visible together
  or not at all. Consequence: `snaputil.snapshot_disk_usage` counts index
  bytes too — 46.7 B per file (§11.3), i.e. 1.4 MB for a 30 000-file
  snapshot, 0.13 % of the tree's size.
* **Content is never linked to the source.** Hardlinks are only ever created
  *between snapshot generations*. A source file is always copied byte-wise
  into the first snapshot that contains it, so mutating a source file can
  never mutate a snapshot through a shared inode.

---

## 5. The run pipeline

One run = one snapshot. Phases, with the locks held:

| Phase | Lock held | Work | Failure handling |
|---|---|---|---|
| 0. Preflight | none | load config, validate ids, `mkdir -p` backup root, `.staging`, `.locks`, `.reports` | fatal, exit 3 |
| 1. Claim scratch | flock on `.staging/<runid>/.lock` | create a unique staging dir | retry with a new runid; abort after 3 tries |
| 2. Choose baselines | root lock (brief, exclusive) | for each source, find the newest published snapshot containing that source id and a readable index | skip that source, report `no_baseline` |
| 3. Scan | none | per source: `synccli.scan_files` + directory enumeration; build the state map (`size`, `mtime_ns`, `mode`, type) | per-file errors are recorded, not fatal |
| 4. Plan | none | `synccli.changed_files` against the baseline index → `copy` / `reuse` / `skip` sets | baseline unreadable → full copy of that source, report it |
| 5. Materialise | shared lock on each baseline snapshot (for the whole run) | copy changed files (chunked), hardlink unchanged ones from the baseline | per-file errors recorded; reuse misses fall back to copy |
| 6. Index | none | build the index from what landed; write `index/<id>.json` atomically; write `index/snapshot.json` | index write failure → do not publish; staging is discarded |
| 7. Publish | root lock (brief, exclusive) | fsync index files and directories, `os.rename(staging, backup_root/snap-<name>)`, fsync the root | rename failure → staging discarded, nothing published |
| 8. Report | none | write the report; optionally prune (§9) | report is always written, even on failure |

Two runs overlap freely: each has its own staging directory, its own index
files and its own snapshot name. The only shared mutable state is the name
space and the prune decision, both under the root lock, and the baselines,
protected by shared snapshot locks.

### 5.1 Index format

`index/<dir-id>.json`:

```json
{
  "schema": 1,
  "dir_id": "evals-2026a",
  "source": "/repo/evals/2026a",
  "scan_started_utc": "2026-11-17T11:42:33.412Z",
  "scan_finished_utc": "2026-11-17T11:42:34.902Z",
  "entries": {
    "run-0001/result.json": {
      "type": "file", "size": 4096, "mtime_ns": 1763378553000000000,
      "mode": "0644", "sha256": null
    },
    "run-0001": { "type": "dir" }
  }
}
```

`index/snapshot.json` lists the sources covered, the totals, the baseline
per source, and `"complete": true`.

**Invariant:** `entries` contains exactly the paths that exist under
`<snapshot>/<dir-id>/` at publish time. It is built from the *results of the
materialise phase*, not from the source scan, so a file that failed to copy
is absent from both the content and the index — the index can never promise
a file the snapshot does not contain (G5).

`entries` is written per source directory, so a run that is killed while
processing the third source does not invalidate the first two.

### 5.2 Report

Identical content for a scheduled run and a human run — the only difference
is the `"trigger"` field, which is metadata. `run --json` prints it on
stdout; `run` prints a human rendering of the same data.

```json
{
  "tool": "backupctl", "schema": 1, "run_id": "20261117T114233.412Z-8123-a91c",
  "snapshot": "snap-20261117-114233-00",
  "trigger": "scheduler", "status": "ok",
  "started_utc": "...", "finished_utc": "...", "duration_s": 13.6,
  "sources": [
    { "id": "evals-2026a", "status": "ok",
      "files_total": 30000, "files_copied": 30000, "files_reused": 0,
      "files_missing": 0, "files_unreadable": 0,
      "bytes_copied": 1044480000, "bytes_reused": 0,
      "removed_since_baseline": 12,
      "baseline": null, "notes": [] }
  ],
  "prune": { "deleted": [], "skipped_busy": [], "bytes_logical_freed": 0 },
  "warnings": []
}
```

`status` is `ok` (every file of every source was captured) or `degraded`
(at least one file was missing or unreadable, or a baseline had to be
rebuilt). `files_missing` / `files_unreadable` name the affected paths up to
a cap of 100, with the full count, so the report stays bounded (§12).

Exit codes: `0` = ok, `2` = degraded (the snapshot exists and is usable,
but is not complete), `3` = fatal (nothing published), `4` = another run
holds the root lock for longer than `--lock-timeout` (default 300 s) and no
snapshot could be published. Codes 0/2/3 are identical for a scheduled and a
human run.

---

## 6. Concurrency and atomicity

### 6.1 Locks

All locks are `fcntl.flock` on a file under `.locks/`:

| Lock | Mode | Held for |
|---|---|---|
| `.locks/root.lock` | exclusive | name allocation, baseline choice, prune computation — all short, all metadata-only |
| `.locks/<snapshot>.lock` | **shared** by readers and by a run that uses that snapshot as a baseline; **exclusive** by the pruner | the whole read / the whole run / the whole deletion |
| `.staging/<runid>/.lock` | exclusive | the whole run; its presence + successful acquisition is the liveness signal for GC (§7.1) |

A run holds the **shared** lock on each of its baseline snapshots for the
whole run. That single mechanism gives three properties:

1. A pruner cannot delete a snapshot that an in-flight run is reading files
   from.
2. A pruner cannot delete a snapshot that a restore is reading.
3. A restore never observes a snapshot being dismantled underneath it.

The pruner takes the **exclusive** lock non-blockingly; if it cannot, the
snapshot is *skipped* and reported in `prune.skipped_busy`. It is not
deleted later — retention is re-evaluated on the next run. This makes
pruning eventually consistent rather than blocking a run indefinitely.

### 6.2 Atomic publish — "a reader never asks whether the run finished"

The snapshot directory is assembled in `.staging/<runid>/` and moved into
place with a single `os.rename(staging, backup_root/snap-<name>)`:

* `rename(2)` within one filesystem is atomic: another process sees either
  the old path or the new path, never a half-populated directory.
* The name `snap-…` therefore **only ever appears on a complete snapshot**.
  There is no "in progress" state to poll, no `COMPLETE` marker to check,
  and no window in which `snaputil.list_snapshots` can report a partial
  snapshot.
* The index is inside the staging directory, so it becomes visible in the
  same atomic step as the content.
* Ordering: the `fsync` of the index files and of the staging directory
  happens **before** the rename, and the backup root is fsynced after it.
  After a *process* kill, the snapshot on disk is complete. After a *power*
  loss, the snapshot may contain files whose bytes never reached the disk
  (the rename is durable, the data was still in the page cache) — see §7.4
  for the `--fsync-content` option and its cost.

Because the name is allocated at publish time under the root lock, two
concurrent runs never choose the same name; the `NN` counter is allocated
from the set of names that already exist.

### 6.3 Two runs, same source, concurrent

Run A and run B both scan the same source at the same time. They write to
different staging directories. Each hardlinks unchanged files from its own
baseline. The two snapshots are independent images; a file that changed
between A's scan and B's scan may appear with different content in each.
That is expected and is not a corruption: each snapshot is internally
consistent. The *newer* snapshot by name (the one published later) is the
baseline for the next run.

### 6.4 The reader contract (for restore tooling)

A restore tool must follow three rules; `backupctl` ships the third so
tooling does not have to re-implement it (and does not have to inherit
`snaputil.safe_snapshot_path`'s traversal flaw, §2.2):

1. **Only read `snap-*` directories.** Use `snaputil.list_snapshots`.
2. **Take a shared lock** on `.locks/<snapshot>.lock` for the duration of the
   read if it wants to be immune to concurrent pruning.
3. **Resolve paths with `backupctl path SNAPSHOT RELPATH`** (or
   `backupctl.safe_join(root, snapshot, rel)`), which rejects absolute
   paths and any path with a `..` component.

`backupctl path` prints the resolved absolute path; it exits non-zero if the
path would escape the snapshot. If the snapshot name has disappeared
between listing and opening, the reader must treat it as "this snapshot was
pruned", not as corruption — and because `keep ≥ 1` (§9), at least one
snapshot always exists.

---

## 7. Crash safety and recovery

### 7.1 A killed run

The run's footprint outside the backup root is the staging directory and its
lock file. Because nothing is published until phase 7, a killed run leaves:

* no `snap-*` directory (so no reader can mistake it for a snapshot);
* a `.staging/<runid>/` directory with partially copied files.

**Recovery is automatic.** At the start of every run (and by `backupctl gc`),
each staging directory's lock is tried non-blockingly:

* the lock **cannot** be acquired → a live run owns it → leave it alone;
* the lock **can** be acquired → the owner is dead → the whole staging
  directory is removed.

The lock file is the liveness signal rather than a PID check, because a PID
can be reused and a lock cannot. The next run therefore makes progress
without manual cleanup (G3).

`snaputil.is_stale` (`snaputil.py:66-73`) is not used for this: the staging
directory's `mtime` changes as files are copied into it, so it is not a
reliable age signal. The lock is.

### 7.2 A corrupt or half-written index

`backupctl` never publishes a half-written index (atomic write + publish,
§6.2). The recovery rule below exists for the cases where an index is
corrupted anyway: bit rot, an external tool, a filesystem that lost a
rename, or a snapshot written by an older version of the tool.

When a run needs a baseline index, it opens `index/<dir-id>.json` and:

| Condition | Action | Reported as |
|---|---|---|
| file missing | treat the source as having no baseline → full copy of that source | `baseline_missing` |
| JSON parse error / truncated / wrong schema | **discard** the index, **re-derive** the state map from the snapshot's own tree (walk `<snapshot>/<dir-id>/`, `lstat` each entry), then continue with the re-derived map | `index_rebuilt_from_tree` (+ affected source id, + entry count) |
| index parses but the tree is unreadable | treat the source as having no baseline → full copy | `baseline_unusable_full_copy` |
| an index entry points at a file that is gone from the tree | drop that entry; the file will be re-copied from the source (a hardlink to a missing file is impossible) | `baseline_entries_missing` (+ count) |

The re-derived map contains `size`, `mtime_ns` and `mode` read from the
snapshot's own files, but **no hashes** — so after a rebuild, the run can
no longer detect same-size/same-mtime content changes in that baseline
(§10.4). The report says so explicitly (`index_rebuilt_from_tree`), because
"the baseline is now weaker than usual" is exactly the kind of thing an
operator needs to be told.

Nothing is aborted by a corrupt index: the run continues with the strongest
baseline it can construct, and the degradation is reported.

### 7.3 Recovery of a *published* snapshot

A published snapshot is never modified. If one is damaged on disk (a file
deleted by hand, a disk error), the next run detects the mismatch while
hardlinking: `os.link` fails with `ENOENT`, and the file is re-copied from
the source instead. The run reports `reuse_missing_fallback` with the count
of affected paths. The reader of a damaged snapshot sees a missing file,
which is the truth of what is on disk.

### 7.4 Durability (process kill vs power loss)

| Event | Guarantee |
|---|---|
| Process killed (Ctrl-C, `kill`, laptop sleep) | the snapshot is either absent or complete and self-consistent. Data written but not fsynced is still in the page cache and is visible to every reader on the machine; only a power loss loses it. |
| Machine loses power | the snapshot name may exist while some file contents were never flushed. `backupctl run --fsync-content` fsyncs every copied file before the index is written, closing this window. Cost measured below. |

`--fsync-content` cost, measured on this machine: 100 `write+fsync` cycles
of a small file took 0.011 s → **0.11 ms per fsync**, so fsyncing a
30 000-file snapshot costs **≈ 3.3 s** on top of the 13.6 s full-backup
budget. It is therefore off by default, and the design states the
difference in guarantees rather than hiding it.

---

## 8. Source files that vanish or cannot be read

Three distinct situations, one uniform rule: **the snapshot contains what
was successfully captured, and the index lists exactly that. The run reports
everything else.**

| Situation | Snapshot content | Index | Report | Exit |
|---|---|---|---|---|
| File gone **before** the scan | not present | not listed | not reported (it was never in scope) | 0 |
| File gone **between** the scan and the copy (`ENOENT`) | not present | not listed | `files_missing` + path | 2 (`degraded`) |
| File present but unreadable (`EACCES`, `EPERM`, `EIO`) | not present | not listed | `files_unreadable` + path | 2 (`degraded`) |
| File present but is a dangling symlink | the symlink itself is captured as a symlink (never followed) | listed as `type: "symlink"` | — | 0 |
| File **changed** during the copy | the copy is retried once; if the source keeps changing, the last complete copy is kept and the file is flagged | listed, flagged `suspect` | `files_changed_during_copy` + path | 2 |
| File deleted in the source since the baseline | absent (a deletion is a legitimate difference) | not listed | `removed_since_baseline` (computed with `synccli.collect_stale`, `synccli.py:45-59`) | 0 |

Rules that make this uniform:

* The behaviour does not depend on the trigger. "Scheduler" and "human"
  differ only in the `trigger` field of the report; both take the same code
  path, produce the same exit codes, and produce the same snapshot shape.
* A single bad file never fails the run and never aborts the other sources.
  The snapshot is still published, still internally consistent, and still
  usable — it is just incomplete, and the report says exactly which paths
  are missing. The alternative (failing the whole run) would leave the user
  with *no* backup because of one unreadable file.
* Because the index is built from what landed, there is no state in which
  the index promises a file the snapshot lacks. This is the explicit
  override of `synccli.sync`'s manifest write (§2.2).

---

## 9. Retention

### 9.1 Policy

A snapshot is **protected** if either condition holds:

* it is one of the newest `keep` snapshots by name order (name order =
  publication order, §4), or
* its age is younger than `keep_days`.

A snapshot that is not protected is **deletable**. `keep` is clamped to
`≥ 1`, so the newest snapshot is never a deletion candidate — the user
always keeps at least one usable snapshot (G6). This is the explicit
override of `snaputil.prune_snapshots` (`snaputil.py:23-36`), whose
`keep=0` deletes everything (verified).

### 9.2 Deletion procedure

For each deletable snapshot, in oldest-first order:

1. Try the **exclusive** lock on `.locks/<snapshot>.lock`, non-blocking.
   * If it cannot be acquired → a restore or a run is using it → **skip**,
     report in `prune.skipped_busy`, and keep the snapshot. It becomes
     deletable again at the next run.
2. Read its logical size with `snaputil.snapshot_disk_usage`
   (`snaputil.py:39-51`) for the report.
3. `os.rename(snapshot, .trash/<name>-<ts>)` — atomic, so no reader ever
   sees a half-deleted snapshot *in place*.
4. Release the lock, then `shutil.rmtree` the trash directory.

If the process dies between 3 and 4, the trash directory remains; the next
run's GC removes it. A trash directory is invisible to
`snaputil.list_snapshots` (its name does not start with `snap-`).

`snaputil.is_stale` (`snaputil.py:66-73`) is deliberately *not* used to
decide retention: the snapshot directory's `mtime` changes as content is
added, so it is not the snapshot's age. Age comes from the name's timestamp
and from `created_utc` in the index.

### 9.3 What "safe to delete" means for shared content

Because unchanged files are shared by hardlink between snapshots, deleting
a snapshot does **not** free the bytes of files that other snapshots still
reference: the inode survives as long as another directory entry points at
it. The `bytes_logical_freed` figure in the report is therefore the
*logical* size of the deleted snapshot, not the disk space reclaimed. The
actual reclaimed space is the sum of the sizes of the inodes whose last
name was removed. The report states both (`bytes_logical_freed`,
`bytes_reclaimed`).

### 9.4 Interaction with running backups

A run holds a shared lock on its baselines for its whole duration (§6.1), so
a prune can never delete the snapshot a run is reading from. If the prune
runs first, the run's `os.link` fails with `ENOENT` and the affected files
are re-copied from the source (`reuse_missing_fallback`, §7.3). Either order
is safe.

---

## 10. Unchanged-file detection

### 10.1 The key

For every file, the change key is:

```
key = (size, mtime_ns, mode)
```

taken from `os.lstat` of the source at scan time, compared against the
values recorded in the baseline index (recorded from the same `os.lstat` at
the time the file was captured). Directories are keyed by name only (their
`mtime` changes with unrelated churn, so keying them would cause spurious
re-copies); symlinks are keyed by `(type, size, mtime_ns)` where `size` is
the length of the target path.

This is the same granularity `synccli.file_state` (`synccli.py:22-25`) uses
(`size`, `mtime`), extended with nanosecond `mtime` and with `mode`.

### 10.2 Reuse

When a file's key matches the baseline, the new snapshot gets a **hardlink**
to the baseline snapshot's copy of that file:

```
os.link(<baseline>/<dir-id>/<rel>, <staging>/<dir-id>/<rel>)
```

The two snapshots then share one inode: the bytes are stored once, the
files are independent directory entries, and the file is not copied again.
This is what "recognize the files that have not changed instead of copying
them again" means here: **no bytes are read from the source and no bytes are
written to the backup for an unchanged file**.

Because the baseline's copy was made from the source at a time when the key
matched, and the key still matches, the shared inode's content is identical
to the source's current content.

If the source and the backup root are on different filesystems, hardlinking
is impossible; `mode: "copy"` in the config falls back to copying, at the
cost of bytes.

### 10.3 Optional content verification

`verify_hash: true` (or `--verify-hash`) adds the file's SHA-256 to the key.
The hash of every source file is then computed on every run, so the run
detects a content change that preserved size and mtime. Measured cost of
hashing the 1 GB benchmark tree: **0.39 s** (SHA-256 at 2643 MB/s), plus
reading the source bytes: **≈ 2.6 s** for 30 000 files / 1 GB (small-file
open/read overhead measured at 136 MB/s effective for 34 KB files, i.e.
≈ 8.5 µs per file). Total ≈ **3.0 s per run** on top of the normal budget —
the dominant new cost is reading the source, not hashing.

### 10.4 What this granularity misses

Stated explicitly, because it is the honest cost of the design:

* **Same size and same mtime, different content.** A file edited in place
  and then restored to its original mtime (`touch -r`), or rewritten by a
  tool that preserves timestamps (`rsync --times`, some archive
  extractors, `cp -p`), is not detected. The snapshot keeps the *older*
  content. `--verify-hash` closes this at the cost in §10.3.
* **Timestamp granularity.** `st_mtime_ns` is nanosecond-resolution where
  the filesystem stores nanoseconds (APFS, ext4, XFS) but only 1 s on
  HFS+, FAT and some network filesystems. On such a filesystem, two edits
  within the same second that preserve the file size are missed.
* **Ownership.** `uid`/`gid` are not part of the key, so a `chown` is not
  detected. This is deliberate: `backupctl` does not run as root and cannot
  restore ownership anyway, so re-copying on a `chown` would cost bytes and
  change nothing. Ownership is not preserved by the backup (documented
  limitation).
* **ACLs, xattrs, resource forks, hardlink counts within the source.**
  Not captured. A file that is hardlinked to another file inside the source
  tree is captured as two independent files.
* **Sparse files** are copied densely (`st_size` bytes are written, not the
  allocated blocks).
* **Symlink targets** are captured as targets, not as the files they point
  to; a symlink whose target is changed to a *same-length* path with a
  preserved mtime is missed by the same rule as above.

---

## 11. Performance budget

### 11.1 Measurement environment

* macOS (Darwin), Python 3.10.11, APFS (`/dev/disk3s5`), 14 CPUs, 38 GB RAM.
* Benchmark tree: 30 000 files in 30 directories, 1 044 480 000 bytes
  (1.044 GB), generated with `os.urandom(34 KiB)` per file.
* Filesystem metadata operations on this volume are slow
  (**≈ 0.38 ms per `os.link`**, measured), and that dominates everything
  else. This is the single most important constant below.

### 11.2 Measured constants

| Constant | Measured value | How |
|---|---|---|
| `t_scan` — `os.walk` enumeration | 0.185 s / 30 000 files = **6.2 µs/file** | `synccli.scan_files` on the benchmark tree |
| `t_stat` — `lstat` per file | 0.672 s / 30 000 = **22 µs/file** | loop over `os.lstat` |
| `t_meta` — create a directory entry (link or create) | 0.377 ms/file | 29 700 `os.link` calls, 11.2 s |
| `R_write` — copy throughput incl. per-file overhead | 1.044 GB / 1.36 s = **770 MB/s** | full copy 12.66 s minus 30 000 × `t_meta` (11.3 s) |
| `t_json` — index write | 0.022 s / 30 000 entries (1.40 MB, compact separators) | `json.dumps(m, separators=(',',':'))` |
| index size | **46.7 B/entry** compact | 1 402 015 B / 30 000 entries |
| `t_hash` — SHA-256 | 2643 MB/s | `hashlib.sha256`, 1 GB |
| `t_read` — read source files | ≈ 8.5 µs/file + bytes | 3000 × 34 KB in 0.256 s (136 MB/s) |
| `t_fsync` | 0.11 ms/file | 100 `write+fsync` cycles |
| `t_unlink` — `rmtree` | 83 µs/file (2.50 s / 30 000) | `shutil.rmtree` of the copied tree |
| `t_size` — `snapshot_disk_usage` | 24 µs/file (0.717 s / 30 000) | `snaputil.snapshot_disk_usage` |
| manifest memory | **355 B/entry** resident (10.6 MB for 30 000) | `tracemalloc` on `synccli.build_manifest` |

### 11.3 End-to-end run shapes (measured on the benchmark tree)

| Run shape | scan+stat | materialise | index | **total** |
|---|---|---|---|---|
| Full backup (30 000 files, 1.044 GB, no baseline) | 0.858 s | 12.655 s | 0.062 s | **13.58 s** |
| Incremental, 1 % changed (300 copied, 29 700 hardlinked) | 0.850 s | 11.272 s | 0.062 s | **12.12 s** |
| Incremental, 0 % changed (30 000 hardlinked, 0 copied) | 0.864 s | 11.3 s (derived: 30 000 × `t_meta`) | 0.062 s | **≈ 12.2 s** |

(The index column uses the `indent=2` measurement, 0.062 s; the compact
form used by the implementation is 0.022 s, so 0.062 s is the conservative
figure.)

The last row is a derivation from `t_meta` and the 1 % row's measurement
(29 700 links ⇒ 0.379 ms/link), not a separate end-to-end run: a run that
changes nothing still creates one directory entry per file, because every
snapshot materialises its own entries even when the bytes are shared. The
scan-and-compare phase alone is 0.93 s (0.864 s scan + 0.062 s index);
that is the only part of a run that is independent of the per-file metadata
cost.

### 11.4 Derivation of the full-backup budget

```
T_full  =  F·t_scan + F·t_stat + F·t_meta + B/R_write + F·t_json
        =  30 000·(6.2 µs + 22 µs + 377 µs + 0.7 µs) + 1.044 GB / 770 MB/s
        =  30 000 · 405.9 µs + 1.36 s
        =  12.18 s + 1.36 s
        =  13.54 s          (measured: 13.58 s)
```

**Budget: the first full backup of a ~1 GB / ~30 000-file tree completes in
≤ 20 s on the reference machine, with the measured value at 13.6 s
(68 % of budget).**

The budget is stated in terms of the two physical constants it is made of —
metadata operations and bytes — so it can be re-derived on other hardware
rather than transplanted:

```
T_full(F, B) ≈ F · t_meta + F · 28 µs + B / R_write
```

On a filesystem with a more typical metadata cost (e.g. 0.05 ms per
directory entry), the same tree takes `30 000·(50 µs + 28 µs) + 1.36 s ≈
3.7 s`. The 20 s budget holds at this F and B for any
`t_meta ≤ 0.59 ms`.

The incremental run's cost is **not** proportional to the changed bytes: it
is proportional to the *total file count*, because each snapshot
materialises one directory entry per file even when the bytes are shared.
`T_incr(F, ΔB) ≈ F · t_meta + F · 28 µs + ΔB / R_write`. At F = 30 000 that
is 11.3 s of metadata work plus 0.85 s of scanning, independent of ΔB.
This is the honest number, and it is why §12 tracks directory entries
separately from bytes.

### 11.5 Index cost

The index is 46.7 B per file (compact JSON): 1.4 MB for a 30 000-file
snapshot, 0.13 % of the tree's bytes. It is written once per snapshot, plus
once per source directory (so a partial run still has usable per-source
indexes).

---

## 12. Scaling bounds

Let:

* `N` — number of configured source directories (3 today, a few dozen over
  time),
* `F_i` — number of files in source `i`, `F = Σ F_i`, `F_max = max F_i`,
* `B_i` — bytes in source `i`, `B = Σ B_i`,
* `ΔB` — bytes changed since the baseline (0 on a no-change run),
* `S` — number of retained snapshots (`keep`).

All constants are the measured ones from §11.2.

### 12.1 Per-run work

| Quantity | Bound | At N=3, F=30 000, B=1.044 GB |
|---|---|---|
| Source files scanned | `F` `lstat` + `F` walk entries | 0.86 s |
| Bytes read from the source | `≤ B` (full) / `≈ ΔB` (incremental; unchanged files are never read) | 1.36 s / ≈ 0 |
| Bytes written to the backup | `ΔB + 46.7 B·F` (index) + metadata | 1.4 MB index per snapshot |
| Directory entries created | **`F` — one per file, every run, even when nothing changed** | 30 000 × 0.377 ms = 11.3 s |
| Files copied | `≤ F` | 30 000 |
| Files hardlinked (reused) | `≤ F` | 29 700 |
| Open file descriptors | **≤ 4** (source, destination, lock, index) — flat in N, F, B | 4 |
| Bytes copied per source | `≤ B_i` | per directory, independent |

### 12.2 Memory

| Quantity | Bound | Value at the reference tree |
|---|---|---|
| Peak RSS | `≈ 355 B × F_max` (one source's state map) `+ 46.7 B × F_max` (index buffer) `+ 64 KiB` (copy buffer) | 10.6 MB + 1.4 MB + 0.06 MB ≈ **12.1 MB** |
| Whole-run manifest | *not* held: sources are processed one at a time and their maps are dropped before the next source | flat in `N` |
| Copy buffer | 64 KiB, **independent of file size** (this is why `synccli.copy_file`'s `fsrc.read()` is overridden, `synccli.py:66-67`) | 64 KiB |
| Report size | `O(errors)`, capped at 100 paths + counts | ≤ 20 KB |

Peak memory is therefore `O(F_max)`, **flat in N**: 36 sources of 30 000
files each still peak at ~12 MB, because the sources are processed
sequentially and each source's map is discarded before the next one starts.

### 12.3 Disk

| Quantity | Bound | Notes |
|---|---|---|
| Backup root after 1 full run | `B + 46.7 B·F` | ≈ 1.046 GB |
| Backup root after `S` snapshots, no changes | `B + S·46.7 B·F` | the data is stored **once** (shared inodes); only the indexes multiply: 7 snapshots × 1.4 MB = 9.8 MB |
| Backup root after `S` snapshots, `ΔB` changed per run | `B + S·ΔB + S·46.7 B·F` | each run adds its changed bytes once |
| Growth per run | `ΔB + 46.7 B·F` bytes + `F` directory entries | the dominant long-run term is the index: `46.7 B × F` per snapshot |
| Pruning cost | `83 µs × F` per deleted snapshot (unlinks) `+ 24 µs × F` (size report) | 2.5 s + 0.7 s per 30 000-file snapshot |
| Free space needed for a full run | `B` | the staging area holds one full copy before the rename |

The backup root grows monotonically between prunes, exactly as the brief
describes; the index term is the part that is *not* deduplicated, and it is
47 B/file/snapshot — 1.4 MB per snapshot at the reference size.

### 12.4 What stays flat, what grows

| Stays flat | Grows with |
|---|---|
| open file descriptors (≤ 4) | `F` — scan syscalls, directory entries per snapshot, index size |
| copy buffer (64 KiB) | `N` — one index file and one content subtree per source |
| number of locks (1 root + 1 per touched snapshot) | `B` — bytes read/written on a full run |
| peak memory (`O(F_max)`, flat in N) | `ΔB` — bytes written per incremental run |
| per-run report size | `S` — number of index files retained |
| number of published snapshots per run (exactly 1) | |

---

## 13. Implementation plan

Three new modules beside the existing ones, plus a test file:

| File | Contents |
|---|---|
| `backupctl.py` | CLI (`run`, `list`, `verify`, `prune`, `gc`, `status`, `path`), the run pipeline (§5), the report (§5.2), `scan_tree()` wrapping `synccli.scan_files`, `safe_join()` (§6.4) |
| `snapstore.py` | layout constants, atomic index read/write, `publish()`, `prune()`, `gc()`, index rebuild-from-tree (§7.2) |
| `lockutil.py` | `flock` helpers: `root_lock()`, `snapshot_lock(shared=…)`, `staging_lock()` |
| `test_backupctl.py` | the tests in §14 |

`synccli.py` and `snaputil.py` are **not modified**: `backupctl` reuses
their functions and implements the overrides of §2.2 in its own modules.
That keeps the neighbouring tool's behaviour intact and makes the
divergences reviewable in the single table of §2.2.

## 14. Test plan

Each row is a test in `test_backupctl.py`; the whole suite runs with
`python3 -m unittest` alongside the existing `test_synccli.py` (which
passes today: 6 tests, 0.006 s).

| # | Test | Asserts |
|---|---|---|
| T1 | two concurrent runs (two processes, same source) | both publish, names are distinct, both snapshots pass `verify`, neither contains the other's partial state |
| T2 | reader during a run | a poller of `snaputil.list_snapshots` never observes a snapshot whose index promises a missing file |
| T3 | `kill -9` mid-run | no `snap-*` directory exists; the next run publishes; the abandoned staging dir is gone after the next run's GC |
| T4 | corrupt baseline index (truncated JSON) | the run rebuilds from the tree, continues, and reports `index_rebuilt_from_tree` |
| T5 | baseline index deleted | the run does a full copy of that source and reports `baseline_missing` |
| T6 | source file deleted between scan and copy | the file is absent from the content **and** from the index; the report has `files_missing`; exit code 2 |
| T7 | unreadable source file (mode 000) | absent from content and index; `files_unreadable`; exit code 2 |
| T8 | scheduler run vs human run | identical snapshot layout and identical report fields except `trigger`; identical exit codes |
| T9 | incremental run | unchanged files are hardlinks of the baseline (same inode) and are not read from the source; changed files are new inodes with the new content |
| T10 | same-size/same-mtime content change | not detected without `--verify-hash`; detected with it |
| T11 | prune with `keep=1` | exactly one snapshot survives; the newest is never deleted |
| T12 | prune while a reader holds the lock | the snapshot is skipped, reported in `skipped_busy`, and still readable |
| T13 | prune with a run holding the baseline | the baseline survives the prune; the run completes |
| T14 | `keep=0` in the config | clamped to 1; at least one snapshot remains (the `snaputil.prune_snapshots` defect) |
| T15 | `../` in a stored path | `backupctl path` refuses to resolve it (the `snaputil.safe_snapshot_path` defect) |
| T16 | dangling symlink in the source | captured as a symlink; the run does not crash (the `synccli.file_state` defect) |
| T17 | index write interrupted (simulated) | the published snapshot's index always parses; no half-written index is ever published |
| T18 | 30 000-file tree | the full backup completes within the §11.4 budget (marked slow; runs on demand) |
| T19 | `backupctl verify` | every index entry exists with the recorded size, and the index matches the tree exactly, both directions |
| T20 | trash directory left by a killed prune | removed by the next `gc`; invisible to `snaputil.list_snapshots` throughout |

---

## 15. Assumptions and open points

* **Assumption** — the backup root is on one filesystem (it holds both the
  staging area and the snapshots). `os.rename` between filesystems fails
  with `EXDEV`; the run detects that and reports it rather than falling
  back to a non-atomic copy, because a non-atomic publish would break G2.
* **Assumption** — the evals directories are on a local filesystem with
  stable `mtime` semantics. On a network filesystem, `st_mtime_ns` may be
  1 s and the change key weakens accordingly (§10.4).
* **Open** — the report history in `.reports/` is capped at the newest 50
  files (~100 KB); the cap is a policy choice, not a correctness one.
* **Open** — `verify_hash` is off by default. If the evals workflow turns
  out to rewrite files with preserved timestamps, it should be turned on
  for the affected sources (cost ≈ 3 s per 1 GB per run, §10.3).
* **Open** — no compression is applied. Compression would reduce the disk
  term but would add CPU per byte and would break the "reuse by hardlink"
  optimisation (shared content could not stay shared across differently
  compressed generations).
* **Out of scope** — a restore command. `backupctl path` plus the reader
  contract in §6.4 is the whole interface a restore tool needs; the
  restore tool itself belongs to the separate tooling the brief mentions.

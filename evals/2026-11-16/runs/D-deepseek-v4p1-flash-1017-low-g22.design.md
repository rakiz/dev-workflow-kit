# DESIGN-d1 — `backupctl`

Status: design for review. Target: the `evals/` workflows in this repository.
Scope: snapshot creation, incremental change detection, crash recovery,
concurrency with other runs and with restores, retention, and the initial-full
performance budget.

All paths and line numbers below refer to this directory's files as checked in
(`synccli.py`, `snaputil.py`, `test_synccli.py`).

---

## 1. Decision summary

1. **A snapshot is a self-contained directory tree** under the backup root:
   `snap-YYYYMMDD-HHMMSS-SSSS/`. It contains the copied files plus one
   per-snapshot index, `.backup_manifest.json`. There is no mutable
   backup-root catalog.
2. **Publication is a single `os.rename`** of a fully built, fsynced temporary
   directory (`.tmp-<uuid>/`) onto its final `snap-…` name. A `snap-…` name
   only ever exists for a complete snapshot; readers never inspect a
   completion marker. This is the whole answer to "never a snapshot index that
   promises files the snapshot does not contain".
3. **Unchanged files are hardlinked** from the previous valid snapshot (not
   re-copied). Change detection is **per file**, on
   `(size, mtime_ns, ctime_ns, mode)` from `lstat`. The missed-edit classes
   are enumerated in §8.
4. **All mutation of the backup root after publication is a rename**:
   retention moves a snapshot out of the `snap-…` namespace before removing
   it, so no reader ever sees a partially deleted snapshot under a live name.
5. **Two lock kinds**: a short-held root lock (`flock` on
   `<backup_root>/.backupctl.lock`) around bookkeeping (temp GC, baseline
   selection, name allocation, publish, retention decisions), and per-snapshot
   **leases** (`flock` on `<snapshot>/.lease`) held shared by readers and by a
   run using that snapshot as its baseline, exclusive by retention.
6. **Interrupted runs leave only `.tmp-*` directories**, which are invisible to
   every snapshot reader and are reclaimed by the next run. A corrupt index
   can only belong to a non-`backupctl` tree or to storage damage; it is
   quarantined, never trusted, and the run re-derives its baseline from the
   live source (§6).
7. **Source files that vanish or are unreadable are omitted, never
   half-copied**, recorded in the manifest's `omitted` list, and make the run
   exit non-zero. The behaviour is identical for scheduler and human; there is
   no TTY-dependent or interactive branch.

---

## 2. What `backupctl` reuses, and what it overrides

This section is deliberately explicit because the brief requires grounding by
name. §12 repeats it as a table with line numbers and reasons.

### 2.1 Reused as-is

| Existing function | File:lines | Use in `backupctl` |
|---|---|---|
| `scan_files(root)` | `synccli.py:10-19` | First pass of the source scan, when hidden-directory inclusion is not requested. We wrap it, not re-implement it. |
| `file_state(path)` | `synccli.py:22-25` | Shape of a per-file state record (`size`, `mtime`); `backupctl` extends the same dict with `mtime_ns`, `ctime_ns`, `mode` and passes it to `changed_files`. |
| `build_manifest(root)` | `synccli.py:28-33` | Full-scan manifest path: `backupctl.build_snapshot_manifest` is `build_manifest` plus per-entry error capture and the extra state fields. |
| `changed_files(old, new)` | `synccli.py:36-42` | The incremental diff (new + changed relative paths). Works unchanged on the extended state dicts. |
| `collect_stale(items, seen)` | `synccli.py:45-59` | Retention candidate selection: items are `(snapshot_name, keep_flag)`; `seen` carries protected snapshots. |
| `copy_file(src, dst)` | `synccli.py:62-69` | Not called directly (see override O2); its create-parent-then-copy shape is preserved by `copy_file_verified`. |
| `list_snapshots(root)` | `snaputil.py:8-20` | Raw directory enumeration, then filtered by `list_valid_snapshots`. |
| `snapshot_disk_usage(root, name)` | `snaputil.py:39-51` | Used only for per-timestamp raw byte reporting; not used for capacity decisions (see O8). |
| `safe_snapshot_path(...)` | `snaputil.py:54-63` | Not used for resolution (see O9); kept only to keep the old tests meaningful. |

The existing test suite (`python3 -m unittest`, 6 tests) passes in this
directory. In particular `test_synccli.TestSync.test_second_sync_is_noop`
(`test_synccli.py:48-51`) establishes the behaviour `backupctl` extends from
"a second sync copies nothing" to "a second snapshot hardlinks everything
unchanged".

### 2.2 Overridden, with exact function and reason

**O1 — `scan_files` hidden-directory filter (`synccli.py:14`).**
`dirnames[:] = [d for d in dirnames if not d.startswith(".")]` silently drops
every dot-directory. A backup that silently omits `.git/`, `.cache/` or an
eval's hidden artifacts is not a backup. `backupctl.scan_source` includes
dot-entries by default and exposes `"skip_hidden": true` per source for users
who want the old behaviour. It also rejects symlinked directories as parents
(`os.walk(..., followlinks=False)` plus explicit `lstat` classification),
because `scan_files` would silently not descend them (they appear in
`dirnames` but are never walked) while listing them as if they were covered.

**O2 — `copy_file` (`synccli.py:62-69`).**
It has three properties `backupctl` cannot accept:
- `except OSError: pass` (lines 68-69) makes every read/write failure silent,
  which contradicts the reporting requirement for vanished/unreadable files.
- `fdst.write(fsrc.read())` (line 67) reads the whole file into RAM. Measured:
  `synccli.copy_file` on a 1 GiB file peaked at **1,122.8 MB RSS** in this
  environment; a 4 GiB eval artifact would OOM a small machine.
- It writes directly to the destination name, so a failure mid-write leaves a
  truncated file that a later reader could mistake for data.

`copy_file_verified` streams 1 MiB chunks, hashes while copying, writes to
`<path>.part` inside the unpublished temp tree, `fsync`s, renames within the
temp tree, and returns the post-copy `fstat` of the open source descriptor. It
raises `SourceGone`/`SourceUnreadable`/`SourceUnstable` upward; nothing is
swallowed. Explicit invariant: **no output path in a temp tree is opened for
writing after it has been created** (either exclusive-create+write or
`os.link`; never overwrite), because a path may already be hardlinking a
previous snapshot — writing through it would corrupt that snapshot.

**O3 — `sync` manifest write (`synccli.py:85-86`).**
`open(dst_manifest_path, "w")` truncates the live manifest in place and
`json.dump` writes it without fsync or rename; a crash leaves a half-written
`.sync_manifest.json`. `backupctl` never writes an index in place: the
manifest is written to `.backup_manifest.json.tmp` inside the temp tree,
fsynced, renamed, and the whole tree is then published atomically. The
manifest name is deliberately **not** `MANIFEST_NAME`
(`synccli.py:7`, `.sync_manifest.json`): that schema has no version, checksum
or omitted-file list, and `scan_files` does not exclude dot-files, so a source
could contain a file with the same name. `backupctl` uses
`.backup_manifest.json` with `"format": "backupctl/1"` and excludes it, and
`/ .lease`, only at the snapshot root.

**O4 — `sync`'s destination model (`synccli.py:72-87`).**
`sync` mutates one destination persistently; deletions in the source are never
removed (line 80 iterates the new manifest only) and there is no history.
`backupctl` never mutates an existing snapshot: each run builds a fresh tree,
and a file deleted from the source is simply absent from the new snapshot while
older snapshots keep their copy.

**O5 — `build_manifest` / `file_state` failure and precision
(`synccli.py:22-25, 28-33`).**
`file_state` uses `os.stat` (follows symlinks) and float `mtime`; `built_manifest`
propagates `FileNotFoundError` for a file that vanished between `scan_files`
and the stat, aborting the whole run. `build_snapshot_manifest` uses `lstat`,
records `size`, `mtime_ns`, `ctime_ns`, file type and permission bits, and
converts a per-file `OSError` into an `omitted` record instead of an abort.
`changed_files` (unchanged) compares the resulting dicts.

**O6 — `list_snapshots` (`snaputil.py:8-20`).**
Its docstring promises that "entries that are not such directories are
ignored", but the code only checks `entry.name.startswith("snap-")` and
`is_dir()`. `snap-junk`, `snap-2026-incomplete`, or a hand-created directory
are all listed. `list_valid_snapshots` additionally requires the regex
`^snap-\d{8}-\d{6}-\d{4}$` **and** a manifest whose checksum verifies. The
lexicographic sort is retained only after the regex makes the format
fixed-width; ordering itself is by the parsed `(date, time, seq)` and the
manifest's `created_ns`, not by string comparison.

**O7 — `prune_snapshots` (`snaputil.py:23-36`).**
It calls `shutil.rmtree` on live `snap-…` names directly, takes no reader
lock, has no minimum-snapshot floor (`keep=0` deletes every snapshot), can
delete a snapshot a run is currently using as its baseline, and ignores
invalid trees. `retention_pass` (§9) replaces it: floor `keep_min >= 1`,
never the newest, never a leased snapshot, rename out of the namespace first,
then deferred `rmtree`.

**O8 — `snapshot_disk_usage` (`snaputil.py:39-51`).**
It sums `st_size` once per path. With the hardlink design unchanged files in
different snapshots are the same inode, so summing entry sizes **overcounts**
shared data by up to a factor of the snapshot count. `unique_disk_usage`
deduplicates on `(st_dev, st_ino)` and is what capacity/retention reporting
uses; `snapshot_disk_usage` may still be printed as "apparent bytes".

**O9 — `safe_snapshot_path` (`snaputil.py:54-63`).**
The docstring claims "The returned path never points outside
`backup_root/<snapshot_name>`", but the implementation does not enforce it:
- an **absolute** `rel_path` makes `os.path.join(backup_root, snapshot_name,
  rel_path)` discard both earlier components and return the absolute path;
- `os.path.normpath("../../etc/passwd")` stays `"../../etc/passwd"`, and the
  join resolves outside the snapshot;
- no `realpath`/`commonpath` containment check and no symlink-component check
  are performed.

`resolve_snapshot_path(root, name, rel)` rejects absolute paths and any `..`
segment, requires the path to appear as a key in the validated manifest,
`lstat`s each component to refuse symlinked parents, and finally verifies
`os.path.commonpath([real_root, real_target]) == real_root`. Restore uses only
this function.

**O10 — `is_stale` (`snaputil.py:66-73`).**
A snapshot directory's `mtime` changes whenever an entry is added or removed,
and `<=` treats an equal timestamp as fresh. It is therefore not a validity or
completeness signal. `backupctl` does not use it for snapshots; completeness
comes from the atomic rename, and integrity from the manifest checksum.
Timestamp age for retention comes from the parsed name/manifest, not directory
mtime.

**O11 — `collect_stale` is kept but its semantics are narrowed.**
It is reused for retention candidates only, with `fresh` meaning "keep". It
does not decide safety (leases and the floor do); it only produces the
candidate list.

---

## 3. Configuration and on-disk layout

Config is JSON (no third-party dependency):

```json
{
  "backup_root": "/backups/evals",
  "sources": [
    {"id": "evals",     "path": "/srv/evals"},
    {"id": "evals-aux", "path": "/srv/evals-aux"}
  ],
  "retention": {
    "keep_min": 3,
    "keep_all_hours": 24,
    "daily_days": 14,
    "weekly_weeks": 8,
    "grace_seconds": 3600
  },
  "fsync": true,
  "recheck": "stat"
}
```

`id` is a stable, path-safe slug; it is the snapshot-relative namespace, so two
sources with the same basename cannot collide. Config validation rejects a
source that contains the backup root, a backup root inside a source, duplicate
ids, and non-existent/unreadable source roots (a missing root is a hard error,
not a degraded snapshot — see §7.3).

Layout:

```
<backup_root>/
  .backupctl.lock                  # flock target; empty; never deleted
  .tmp-<uuid>/                     # unpublished build; .run.lock inside
  .trash-<name>-<utc>/             # renamed-to-delete; removed after grace
  .quarantine-<name>-<utc>/        # invalid tree, preserved for the operator
  snap-20261116-143000-0001/
     .lease                        # empty; flock target for readers/retention
     .backup_manifest.json
     evals/results/run-17/out.txt
     evals-aux/...
```

Snapshot-relative paths are `<source_id>/<source-relative path>`. Entry names
starting with `.` are included in the copied payload (O1), except the two
reserved names at the snapshot root.

The backup root must be on a local POSIX filesystem that gives atomic
`rename(2)` within one directory tree and working `flock`. Both are true on
the platform used for the measurements. NFS (where `flock` may be local-only)
is out of scope and refused at startup if detected as such; on such storage a
different lock transport must be chosen, not silently skipped.

---

## 4. Run lifecycle

The command is `backupctl backup --config <file>` (alias `run`). A run moves
through seven phases. Phases 1, 2, 6 and 7 hold the root lock; phases 3–5 do
not, so two runs copy in parallel.

### Phase 1 — open and GC (root lock held)

1. Open/create `.backupctl.lock`; `flock(LOCK_EX)`.
2. Scan `.tmp-*`. For each, open `.tmp-*/<run>.lock` and try
   `flock(LOCK_EX|LOCK_NB)`:
   - acquired → the owner is dead (locks vanish with the process). Rename the
     temp dir to `.trash-<tmp>-<utc>` and record
     `recovery.temps_discarded += 1`.
   - `EWOULDBLOCK` → a live run owns it; skip.
   Temp directories are created **while the root lock is held** (phase 0
   below), so a temp directory always has its lock file before the lock is
   released; there is no lockless window for GC to race.
3. Remove `.trash-*` older than `grace_seconds` with `rmtree`.
4. `list_valid_snapshots()`; quarantine invalid `snap-…` trees (§6.2).

### Phase 2 — baseline and leases (root lock held)

5. Pick the newest valid snapshot by `(created_ns, name)`. Skip newer invalid
   ones already quarantined.
6. Open `<baseline>/.lease` and take `flock(LOCK_SH)`. Keep the descriptor for
   the whole run. This prevents retention from deleting the source of our
   hardlinks.
7. Release the root lock.
8. Create `.tmp-<uuid>/` and its `.run.lock`; take `LOCK_EX` on it. (Creation
   and lock happen while the root lock is held, immediately before release.)

No baseline → this is a full run; baseline maps are empty.

### Phase 3 — scan (no lock)

For each source, `build_snapshot_manifest(source_id)`:
`scan_source` → for each entry `lstat` (state) and classify (regular,
symlink, other). Store in a per-source dict keyed by `<source_id>/<rel>`. A
classifier error, or a file that vanishes during this pass, is recorded in
`omitted`; it does not abort the source.

The scan is the run's point-in-time reference for change detection.

### Phase 4 — materialize into the temp tree (no lock)

For each source, for each scanned entry, in the sorted order produced by
`scan_files`/`scan_source`:

1. Re-`lstat` the source path (second stat; catches files that vanished or
   changed between phase 3 and now). If it is gone/unreadable → `omitted`,
   continue. If the state differs from the scan, use the new state.
2. If `changed_files(baseline[source], scan[source])` does **not** contain the
   path, and the baseline entry is a regular file whose snapshot file exists
   with the recorded size, `os.link(baseline/<path>, tmp/<path>)` (creating
   parent dirs). Record `linked += 1`, reuse the baseline hash. If the
   baseline file is missing or its size differs, fall through to copy and
   report `baseline_damaged`.
3. Otherwise `copy_file_verified(...)` into the temp tree. Record
   `copied`, `bytes_copied`, hash. On `SourceGone`/`SourceUnreadable` →
   `omitted`. On `SourceUnstable` after two attempts → `omitted` with reason
   `unstable` (a file being rewritten while copied is not a coherent image).
4. Symlinks: `lstat` + `os.readlink`, record `{"type":"symlink","target":...}`,
   recreate with `os.symlink` in the temp tree. Never followed. Other special
   files (FIFO, socket, device) are **never opened** (opening a FIFO blocks
   forever); they are `omitted` with reason `special`.
5. Track `(st_dev, st_ino)` seen in this run to warn (not silently ignore)
   when source hardlinks are expanded into independent copies.

The second `lstat` and the copy return value both come from the open descriptor
(`fstat` before and after the read). If `size`/`mtime_ns` differ across the
read, the copy is retried; this is what prevents a torn file from being
recorded as a valid image.

### Phase 5 — index (no lock)

Build the manifest object:

```json
{
  "format": "backupctl/1",
  "run_id": "20261116T143000Z-4831-9f2a1c0d",
  "snapshot_name": "snap-20261116-143000-0001",
  "created_ns": 1763303400000000000,
  "sources": {"evals": {"root": "/srv/evals", "files": 19342, "bytes": 987654321}},
  "files": {
    "evals/results/run-17/out.txt": {
      "type": "file", "size": 1234, "mtime_ns": 1763303399123456789,
      "ctime_ns": 1763303399123456789, "mode": 420,
      "sha256": "…"
    }
  },
  "omitted": [
    {"path": "evals/results/run-18/tmp.bin", "reason": "vanished",
     "error": "ENOENT", "at_ns": 1763303400123456789}
  ],
  "manifest_sha256": "…"
}
```

`manifest_sha256` is SHA-256 over the canonical JSON
(`json.dumps(obj_without_checksum, sort_keys=True, separators=(",",":"))`) of
the entire object except the checksum key itself. It detects torn/edited
indexes. `files` and `omitted` are disjoint: anything in `omitted` is absent
from the tree and absent from `files`, so the index can never promise a file
the snapshot does not contain.

### Phase 6 — durable, publish (root lock held)

1. If `fsync`: `fsync` every copied regular file (kept-open write fd), then
   every directory in the temp tree, then the manifest file. Measured cost:
   ~63 µs/file. Without fsync the snapshot is still safe against process death
   (page cache survives the process), but not against OS crash; `fsync` is on
   by default.
2. Write `.backup_manifest.json.tmp`, `fsync`, `os.replace` to
   `.backup_manifest.json`, `fsync` the temp root directory. Write `.lease`
   (empty) and `fsync` the temp root.
3. Take `flock(LOCK_EX)` on `.backupctl.lock`.
4. Allocate the name: UTC `snap-YYYYMMDD-HHMMSS-<seq>`, `seq` = 1 + the
   highest sequence already present for that second; wait to the next second
   if `seq > 9999`; if the wall clock is behind the highest existing name, use
   the latter's timestamp and the next sequence. Uniqueness is guaranteed
   because allocation and rename happen under the root lock.
5. `os.rename(tmp, backup_root/name)`; `fsync` the backup root directory.
   This is the publication point.
6. Release root lock.

### Phase 7 — retention (root lock re-acquired inside `prune`)

Run only if publication succeeded (§9). Never run after a failed run.

### Phase 0 (implicit) — temp creation

Creating `.tmp-<uuid>/` and locking `.tmp-<uuid>/.run.lock` is done while the
root lock from phase 1 is still held, so GC cannot mistake a new temp for a
dead one.

### Interruption points

| Killed during | Left behind | Next run | Reader impact |
|---|---|---|---|
| phases 3–5 | `.tmp-<uuid>/` with `.run.lock` (lock released by OS) | phase 1 removes it | none: not in `snap-…` namespace |
| manifest temp write | `.backup_manifest.json.tmp` inside temp | temp discarded | none |
| phase 6 after fsync, before rename | complete temp tree | removed as a dead temp | none |
| during `rename` | old state or new state (atomic) | sees a complete new snapshot or none | sees complete or none |
| phase 7 after rename-to-trash | `.trash-*` | removed after grace | live `snap-…` name already gone atomically |

An interrupted run never leaves a `snap-…` directory, so the next run always
starts from the last complete snapshot and needs no manual cleanup.

---

## 5. Concurrency model

Three primitives:

1. **Root lock** — `flock(LOCK_EX)` on `<backup_root>/.backupctl.lock`,
   held only for phases 1–2, 6 and 7. It never spans scan, copy, hashing or
   fsync. Its longest hold is O(number of snapshots + temp dirs) to list the
   root and rename, i.e. independent of file count and bytes.
2. **Snapshot lease** — `flock` on `<snapshot>/.lease`:
   - a run holds `LOCK_SH` on its baseline for its whole duration;
   - a reader/restore holds `LOCK_SH` for the whole read;
   - retention holds `LOCK_EX` only while renaming a victim out of the
     namespace.
3. **Atomic rename** — the only operation that makes a new snapshot visible,
   and the only operation that makes an old one invisible (move to `.trash`).

### Scenario analysis

| Situation | Why nothing is corrupted |
|---|---|
| Two runs start together | each builds a private `.tmp-<uuid>`; name allocation and rename are serialized by the root lock; the result is two complete snapshots with distinct names. |
| Run A is copying while run B publishes | B only touches its own temp and the root name space; A's paths are disjoint. A's baseline is leased. |
| Two runs use the same baseline | both hardlink the same immutable inodes read-only; hardlinking increments the link count of the **baseline snapshot's** inode, never the source's; neither modifies the baseline. |
| Restore reads an old snapshot while a run writes a new one | old snapshots are immutable; the run only reads them for hardlinks (`LOCK_SH`, which restore also holds, so they coexist) and writes only its temp tree. |
| Restore asks for the new snapshot mid-run | the name does not exist until the atomic rename; the restore sees the previous snapshot or the complete new one, never a partial tree. |
| Retention vs. run baseline | the run's shared lease makes retention's `LOCK_EX|LOCK_NB` fail; retention skips and records `deferred_leased`. |
| Retention vs. restore | same lease; if the reader is cooperating, deletion is deferred. If not, see below. |
| Concurrent retention passes | root lock serializes candidate selection and each rename. |
| Same-second name collision | sequence allocation occurs under the root lock. |

**Deletion against a non-cooperating reader.** No advisory protocol can stop a
reader that never takes a lease. The guarantee we give is: retention first
renames the snapshot to `.trash-…` (one atomic directory operation), then
waits `grace_seconds` (default 3600) before `rmtree`. Therefore (a) no reader
ever observes a partially deleted tree under a `snap-…` name, and (b) a reader
that already opened files keeps valid descriptors to unlinked inodes and can
finish. A path-based reader that reopens a file after the rename gets
`ENOENT`; it must re-list. That is a failed read, never a corrupt one. The
documented contract for `backupctl restore` is to take the shared lease first,
which upgrades this to "cannot fail and cannot be deleted".

---

## 6. Crash recovery, including the index

### 6.1 Dead temp trees (the normal interrupted-run case)

A killed run leaves `.tmp-<uuid>/`. Its `.run.lock` is released by the kernel.
At the next start, phase 1 probes it and, on acquiring the lock, renames it to
`.trash` and deletes it after the grace period (or immediately if older than
grace). Reported as `recovery.temps_discarded`. Nothing in it is trusted and
nothing is reused: the new snapshot's manifest is **re-derived from the live
source tree** by phase 3, and the incremental baseline is the last valid
published snapshot, not the dead temp.

### 6.2 Corrupt or half-written index in a `snap-…` directory

Under this design a dead run cannot produce one: a `snap-…` directory only
comes into existence by renaming a finished tree. But the requirement is
explicit, and storage damage or a tree produced by another tool can still
create that state. The rule is mechanical and does not depend on guessing
whether the run "finished":

- A directory is a **valid snapshot** iff:
  1. its name matches `^snap-\d{8}-\d{6}-\d{4}$`;
  2. it contains a parseable `.backup_manifest.json` with
     `"format": "backupctl/1"`;
  3. the recomputed canonical `manifest_sha256` matches;
  4. every key in `files` is a relative path without `..`, and its recorded
     `type` is one of `file`/`symlink`.
- An index failing (2) or (3) is **discarded as an index**: it is never
  repaired, merged, or partially used. The tree is atomically renamed to
  `.quarantine-<name>-<utc>` so an operator can inspect or recover bytes by
  hand; it is excluded from `list`, from baseline selection, and from
  retention counts.
- The run then **re-derives** what it needs from the live source: the new
  snapshot's manifest comes from phase 3; the baseline falls back to the next
  newest valid snapshot, and if none remains, the run is a full run.
  Unchanged-since-the-older-baseline files are still hardlinked; files that
  changed in between are copied because their source state differs from the
  older baseline. The result is a correct snapshot.
- The run **reports** `recovery.quarantined: [name]` and, if that snapshot had
  been the selected baseline, `baseline_used: <older name>` or
  `baseline_used: null (full)`. It is not an error exit if the new snapshot is
  produced; it is reported as a warning plus `recovery` fields.
- `backupctl list` is read-only: it marks such a directory `invalid` but does
  not quarantine. `backup` and `prune` quarantine.

Deep tree verification (manifest says X, X missing or wrong size) is **not**
done on every run: that is O(total files across all snapshots) per run. It is
the job of `backupctl verify [--all]`, which — for each manifest entry —
`lstat`s the file, checks size and, with `--hash`, re-hashes it. A verify
failure marks the snapshot invalid for the next `prune` and is reported; it
does not auto-delete.

### 6.3 What is *not* claimed

The snapshot is not a filesystem snapshot: files are read sequentially, so
different files reflect slightly different instants. What is guaranteed is
per-file consistency (no torn copy is recorded; §4 phase 4) and publication
consistency (a reader sees the whole index and all its files or nothing). A
strict single-instant image across sources would require an OS/LVM snapshot,
which this tool does not assume.

---

## 7. Vanished and unreadable source files

### 7.1 Rules

| When | Snapshot contains | Manifest | Run report / exit |
|---|---|---|---|
| File gone before scan | nothing | not in `files`, not in `omitted` | normal |
| Gone between scan and re-stat/copy | nothing (old version is **not** substituted) | `omitted` reason `vanished`, `ENOENT` | `degraded`; listed; exit 2 |
| `EACCES`/`EIO`/short read | nothing (no `.part` published; partial stays in temp) | `omitted` reason `unreadable`/`io` | `degraded`; listed; exit 2 |
| Changes while being read, twice | nothing | `omitted` reason `unstable` | `degraded`; exit 2 |
| Was in previous snapshot, now gone | nothing | `omitted` reason `vanished`, plus `previously_present: true` | `degraded`; exit 2 |
| Special file (FIFO/socket/device) | nothing (never opened) | `omitted` reason `special` | `degraded`; exit 2 |
| Source root itself missing/unreadable at validation | **no snapshot is published** | — | `failed`; exit 3 |

Why omit instead of keeping the previous snapshot's version? Because a reader
of snapshot S must be able to trust that S describes the source at S's scan
time. Keeping a stale file behind a fresh index would be exactly the
"index promises a mix of runs" failure the brief forbids. The previous
snapshot remains intact and readable, so the old copy is still recoverable from
it; the report says so.

Why not abort the whole snapshot on one bad file? A single unreadable eval
artifact would then block every backup indefinitely, and the brief requires the
next run to make progress without manual cleanup. The snapshot is therefore
**complete and self-consistent but with explicitly listed omissions**. This is
degraded coverage, not corruption.

### 7.2 Reporting and exit codes

`backupctl` writes a line-oriented human log and (with `--json`) one
`RunReport` object to stdout; the same object is always also emitted on stderr
when `--quiet` is not set. Fields: `run_id`, `snapshot` (or null),
`status` (`complete|degraded|failed`), `sources{scanned,copied,linked,
bytes_copied,omitted[]}`, `recovery`, `retention`, `duration_ms`,
`exit_code`.

Exit codes: `0` complete, `2` degraded (snapshot published with omissions),
`3` failed (no snapshot published), `4` config/validation error. The
scheduler keys on the exit code; a person reads the same code and the same
list. There is **no** interactive prompt and no `isatty()` branch: the
scheduler and a person get byte-identical decisions for the same tree state.

### 7.3 Hard errors (no snapshot)

Configuration/validation errors and an unreadable source root abort before the
temp tree is materialized. A source that becomes entirely unreachable mid-run
produces per-file omissions and a degraded exit as above, but if *zero* files
of a previously non-empty source could be read, the run additionally refuses
to publish and exits 3 rather than publish a misleading empty source
(`"empty_source_refused"`), because that would look like "everything was
deleted" to every future reader. The previous snapshot stays in place. The
operator can override with `--allow-empty-source` if the deletion was real.

---

## 8. Incremental change detection: granularity and blind spots

- **Granularity: one decision per file path.** There is no block-level or
  byte-range diff.
- **State compared:** `(size, mtime_ns, ctime_ns, mode)` from `lstat`, plus
  the file type. Baseline entries are the same fields recorded when that file
  was copied (post-copy `fstat` of the source descriptor).
- **Algorithm:** `changed_files(baseline, current)` (`synccli.py:36-42`) gives
  new+changed paths; every other path is a hardlink candidate. Before linking,
  the source is re-`lstat`ed and the baseline snapshot file's size is checked
  (O5, §4 phase 4).
- **Why `ctime_ns`:** it cannot be set by userspace (`os.utime` changes
  `mtime` only), so a same-size rewrite whose author restored `mtime` is still
  detected, and a replacement file created by `rsync -t`/`tar` with preserved
  `mtime` has a new `ctime`. This narrows the blind spot substantially at zero
  per-run I/O cost.

**Edits this granularity can miss** (stated explicitly, as required):

1. Same-size in-place content change where `mtime` and `ctime` land in the
   same timestamp tick as the recorded values. Filesystem timestamp resolution
   is not nanosecond everywhere: APFS/ext4 normally give ns, but FAT (2 s),
   some HFS+/NFS/older ext3 configurations give 1 s or coarser. Two writes of
   the same size within one tick are indistinguishable by stat.
2. Direct block-device writes or filesystem-level edits that leave metadata
   unchanged (outside normal file APIs; not detectable by any stat-based
   tool).
3. Changes that do not alter file content and are not in the tracked mode:
   ownership, group, ACLs, xattrs, SELinux labels, birth time, extended
   attributes. `mode` is tracked; the rest are not copied at all.
4. Intra-source hardlink topology (two paths to one inode are copied as two
   independent files; the data is right, the sharing is not).
5. Sparse-file hole layout (reading and writing fills holes; content is
   right, sparseness is not preserved).
6. Directory-level metadata (`mtime` of directories) is not tracked; an empty
   directory is copied, but its timestamps are not preserved.

**Escape hatches:** `--recheck=stat` (default, above);
`--recheck=hash` re-reads each source file whose stat is unchanged and
compares the stored SHA-256, closing blind spot 1 at the cost of reading
`B` bytes per run; `--recheck=full` copies everything. Hashes are computed
during every copy anyway (measured 0.41 s/GiB on this host) and are used by
`verify`; they are not used for the default diff because using them would
require reading every file every run, which defeats the incremental case.

**Limit of the guarantee:** unchanged files are, by definition, those the
stat tuple says are unchanged. The design never claims byte-exact detection
without `--recheck=hash`; the manifest records which mode produced it
(`"recheck": "stat|hash|full"`) so a future reader knows the strength of the
claim behind a snapshot.

---

## 9. Retention

### 9.1 Policy

Default policy (all values configurable; `keep_min` may not be below 3 in
production config validation, and is clamped to at least 1 in code):

- always keep the newest valid snapshot and at least `keep_min` newest valid
  snapshots;
- keep every snapshot younger than `keep_all_hours` (24 h);
- keep the newest snapshot per UTC day for `daily_days` (14);
- keep the newest snapshot per ISO week for `weekly_weeks` (8);
- everything else is a deletion candidate.

Retention runs **after** a successful publication and never after a failed run.
Because the just-published snapshot is the newest, the user always has at least
one usable snapshot after every successful run; if the run failed, no snapshot
was removed, so the previous state is untouched.

Candidates are computed with `collect_stale` (`synccli.py:45-59`) over
`(name, keep)` pairs, with protected names (the just-published snapshot, the
newest valid, every leased snapshot, and acks) supplied in `seen`. The count
floor is enforced on the remaining valid set, not on the candidate list, so a
race can never take the total below `keep_min`.

### 9.2 Deletion protocol

For each candidate, under the root lock:

1. Skip if it is leased (`LOCK_EX|LOCK_NB` fails) → `deferred_leased`.
2. Skip if it is the newest or would violate the floor → `deferred_floor`.
3. `os.rename(snap, .trash-<name>-<utc>)` — atomic; the `snap-…` name
   disappears in one operation, so no reader can ever enumerate a
   partially deleted snapshot.
4. Release the root lock, then either `rmtree` immediately (if the exclusive
   lease was acquired, no cooperating reader exists) or defer to a later
   cleanup pass after `grace_seconds` for non-cooperating readers.

`.trash-*` is cleaned at startup and at the end of every run after the grace
period; `.quarantine-*` is never auto-deleted (an operator decides). Both are
outside the `snap-…` namespace, so `list`, baseline selection and restore
cannot see them as snapshots.

This replaces `snaputil.prune_snapshots` entirely (O7): that function rmtrees
live names, deletes everything when `keep == 0`, and cannot observe readers.
`backupctl` keeps its docstring-level intent ("delete oldest first, never the
newest") but not its implementation.

---

## 10. Initial full backup: performance budget and derivation

### 10.1 Measured components

Environment for the measurement: the checkout's host, macOS (APFS SSD),
Python 3.10.11, single process. Trees: 20,000 files in 50 directories, 50 KiB
each = 1,024,000,000 bytes (1 GiB). Each figure is an actual measurement, not
an estimate.

| Step | Measured time | Per-file / throughput |
|---|---:|---|
| `scan_files` (20k paths) | 0.117 s | 171k paths/s |
| `os.stat` + build extended manifest (20k) | 0.418 s | 20.9 µs/file |
| create dirs + chunked copy of 1 GiB (20k files) | 5.333 s | 192 MiB/s, 267 µs/file |
| per-file `fsync` + directory `fsync` (20k) | 1.270 s | 63 µs/file |
| manifest canonicalise, hash, write, `os.sync` | 0.100 s | — |
| atomic rename + root `fsync` | ~0.001 s | — |
| **Total end-to-end prototype** | **7.249 s** | — |

Supporting measurements on the same host:
- SHA-256 of 1 GiB: **0.413 s** (computed while copying, so it overlaps I/O
  but is included in the budget below);
- `os.link` 20,000 files: **7.8 s** (0.39 ms/link) — APFS hardlink cost; this
  affects the *incremental* run, not the initial full run;
- `synccli.copy_file` on one 1 GiB file: **0.522 s** and **1,122.8 MB peak
  RSS**, versus **0.288 s** and bounded memory for the chunked copier — this
  is the measured reason for O2.

### 10.2 Budget

**Budget: 60 s wall-clock (p95) for a 1 GiB source tree of 20,000 files on
this class of host; 120 s ceiling before the run is considered failed.**

Derivation, using the measured constants:

```
T_full ≈ 0.5 s                      fixed startup + config + publish
       + 42 µs × F                  two lstat per file (scan + pre-copy recheck)
       + 63 µs × F                  fsync per file (0 with --no-fsync)
       + B / 190 MiB/s              chunked copy at measured 192 MiB/s, minus margin
       + B / 2.5 GiB/s              SHA-256 while copying (0.41 s/GiB)
       + 0.3 s                      manifest hash + write + sync
```

For `F = 20,000`, `B = 1 GiB`: 0.5 + 0.84 + 1.26 + 5.39 + 0.41 + 0.3 ≈ **8.7 s**
(the prototype measured 7.25 s without hashing; adding the measured hash cost
gives about 7.7 s, so the formula is conservative). The 60 s budget is a
**6.9×** margin over the derived figure, covering slower SSDs, cold caches and
Python-version variance. `--no-fsync` removes the 1.26 s term; it is not the
default because it trades OS-crash durability for speed.

The budget is linear in the two dominant quantities: bytes at the measured
read throughput, and files at ~105 µs/file (two stats + fsync). For a
100,000-file, 1 GiB tree the derivation gives 0.5 + 4.2 + 6.3 + 5.4 + 0.4 +
0.3 ≈ **17.1 s** (still inside 60 s). For 1 GiB on a slower 80 MiB/s external
disk the byte term alone is 13.4 s, total ≈ 17 s; for a 30 MiB/s network
source the same calculation gives ≈ 38 s, still within budget, but the run
prints the measured `bytes_copied/duration` so the operator can see the gap.

If a source is on a network filesystem whose sustained read is below
20 MiB/s, 1 GiB cannot meet 60 s; the tool then reports the measured
throughput at the end and does not pretend the budget was met. (A pre-flight
probe would slow the common local case; the report is the honest mechanism.)

### 10.3 Memory

- Copy buffer: **1 MiB**, independent of file size (proved by the 1 GiB
  single-file measurement: chunked peak stays at interpreter overhead instead
  of 1.12 GB).
- Manifest for the largest single source: ~300 bytes/file including hash;
  20k files ≈ 6 MB; 100k ≈ 30 MB; 1M ≈ 300 MB. Processing is per source, so
  peak is `O(files in the largest source)`, not `O(files × N)`. If a source's
  manifest would exceed a configurable `max_manifest_mb` (default 512), the
  run spills that source's map to a temporary SQLite table instead of raising
  memory; the incremental diff is then a sorted merge in file order.
- Open descriptors: the write fd + one source fd + baseline lease + root lock
  + temp lock, i.e. a constant (≤ 6), not one per file.

---

## 11. What grows with what (explicit bounds)

Let be: `N` = number of source directories, `F` = total files across sources,
`F_max` = files in the largest source, `B` = total source bytes, `S` = number
of retained snapshots, `C_bytes`/`C_files` = changed bytes/files in one run,
`D` = total directories in the tree.

| Quantity | Bound | Grows with | Does not grow with |
|---|---|---|---|
| Per-run scan work | `2 × F` `lstat` calls + `D` `readdir` entries | `F`, `D` | `N` (only +N config checks), `S` |
| Per-run copy I/O | `C_bytes` bytes read/written (first run: `B`) | changed bytes | `F` beyond per-file overhead, `N` |
| Per-run hardlinks | `F − C_files` links | unchanged file count | bytes, `N` |
| Root-lock hold | `O(S + T)` entries where `T` = stale temp/trash dirs | snapshot count, not file count | `F`, `B` |
| Peak memory | `~1 MiB + 300 B × F_max + interpreter` | `F_max` | `N × F`, `B` |
| Open fds | `≤ 6` | nothing | `F`, `N`, `S` |
| Disk, unique data | `≤ B + Σ C_bytes over retained changed versions` | changed data kept by policy | `N` |
| Disk, metadata/dir entries | `O(F × S)` (each unchanged file is an extra hardlink/name per snapshot; no new data blocks) | `F × S` | bytes (except manifests) |
| Manifest storage | `~300 B × F` per snapshot | `F`, `S` | `N` (additive in `F`) |
| Snapshot listing | `O(S)` directory reads, one manifest read each | `S` | `F`, `B` |
| Per-run fixed overhead | ~0.5 s measured | nothing | `N`, `F` |
| Retention work | `O(S)` lease probes and at most `O(S)` renames | `S` | `F`, `B` |

Fitting the brief's "three directories today, a few dozen over time": going
from `N = 3` to `N = 40` with the same total `F` changes per-run work only by
40 source-opening/config checks and by the per-source loop overhead (milli-
seconds); it does **not** multiply work or memory by `N`, because the run
processes one source at a time and keeps only that source's manifest. If the
number of files is what grows, the scan/stat term (`42 µs/file`) and the
hardlink term (0.39 ms/file measured on APFS) grow linearly while disk data
grows only with changed bytes. The metadata term `F × S` is the one that
eventually argues for a lower `S`; that is exactly what retention bounds.

---

## 12. Grounding table (file, function, lines, reason)

| # | Artifact | Location | What `backupctl` does |
|---|---|---|---|
| G1 | `scan_files` | `synccli.py:10-19` | Calls it for the ordered path walk; documents that the dotdir filter at line 14 is overridden by default (O1). |
| G2 | `file_state` | `synccli.py:22-25` | Extends the same record shape with `mtime_ns`, `ctime_ns`, `mode` and `lstat` semantics (O5). |
| G3 | `build_manifest` | `synccli.py:28-33` | Basis of `build_snapshot_manifest`; per-entry `OSError` captured instead of aborting (O5). |
| G4 | `changed_files` | `synccli.py:36-42` | Unchanged; the incremental diff. |
| G5 | `collect_stale` | `synccli.py:45-59` | Retention candidate computation (§9). |
| G6 | `copy_file` | `synccli.py:62-69` | Replaced by `copy_file_verified`; exact reasons in O2 (silent `OSError`, whole-file read, in-place write). |
| G7 | `MANIFEST_NAME` / `sync` write | `synccli.py:7, 75-87` | Not reused: in-place, non-atomic, unversioned, unchecksummed (O3/O4). |
| G8 | `list_snapshots` | `snaputil.py:8-20` | Called, then filtered by `list_valid_snapshots` because the code does not implement its docstring's format check (O6). |
| G9 | `prune_snapshots` | `snaputil.py:23-36` | Replaced by `retention_pass`; reason: rmtree of live names, no floor, no leases (O7). |
| G10 | `snapshot_disk_usage` | `snaputil.py:39-51` | Used for apparent size only; `unique_disk_usage` avoids hardlink overcount (O8). |
| G11 | `safe_snapshot_path` | `snaputil.py:54-63` | Replaced by `resolve_snapshot_path`; the docstring's containment claim is false for absolute and `..` inputs (O9). |
| G12 | `is_stale` | `snaputil.py:66-73` | Not used for validity; directory mtime is not a completeness signal (O10). |
| G13 | `test_second_sync_is_noop` | `test_synccli.py:48-51` | The tested precedent that the second run copies nothing; `backupctl` extends it with snapshots and hardlinks. |
| G14 | existing test suite | `test_synccli.py` (6 tests) | Run in this directory via `python3 -m unittest`; all 6 pass. Measurements in §10 ran the same interpreter and `import synccli`. |

---

## 13. CLI surface

```
backupctl backup  --config C [--json] [--strict] [--no-fsync]
                  [--recheck stat|hash|full] [--allow-empty-source]
backupctl list    --config C [--json] [--valid-only]
backupctl verify  --config C [SNAPSHOT] [--hash] [--all]
backupctl prune   --config C [--dry-run] [--json]
backupctl restore --config C --snapshot NAME --source ID --dest DIR
```

- `restore` is the reference reader: it opens `.lease` `LOCK_SH` on the
  snapshot, validates the manifest checksum, iterates `files` (never the
  directory tree), and resolves each path through `resolve_snapshot_path`.
  It refuses symlinked parent components and writes symlink entries last.
  Separate restore tooling is expected to follow the same three steps; the
  lease is what makes retention safe.
- `--strict` changes only the policy for omission (abort instead of degraded
  publish) and is equally available to scheduler and human.

## 14. Test plan for the implementation

1. Atomicity: kill -9 the process during copy at every phase boundary; assert
   no `snap-…` exists, `.tmp-*` is reclaimed by the next run, and the next run
   completes.
2. Two concurrent runs in a loop; assert two valid, manifest-checksum-verified
   snapshots, distinct names, and byte-identical content to a full copy.
3. Restore-while-run: a reader holding the lease on the old snapshot completes
   while a new snapshot is published and retention attempts deletion
   (`deferred_leased` observed).
4. Delete a file between scan and copy (hook), and make one unreadable
   (chmod 000, as a non-root test user): assert the snapshot omits it, the
   manifest lists it under `omitted`, exit code 2, and a subsequent run
   copies it when readable.
5. Corrupt `.backup_manifest.json` in the newest snapshot: assert quarantine,
   fallback to the next valid baseline, and correct incremental result against
   a full copy.
6. Truncate `.backup_manifest.json` in a `.tmp-*` and leave it simulated-dead:
   assert it is discarded and not used.
7. Retention with `keep=0` in config: assert the code clamps to ≥ 1 and never
   removes the last snapshot; retention during a leased reader defers.
8. `resolve_snapshot_path` with `../../x`, `/etc/passwd`, a symlinked parent
   inside the snapshot, and a path absent from `files`: all rejected.
9. Change detection: same-size same-mtime rewrite (missed by stat, caught by
   `--recheck=hash`); chmod-only change (detected by `mode`); content change
   with restored mtime (detected by `ctime_ns`).
10. Performance regression: the §10 tree generator plus the prototype
    workload; fail the benchmark if the 1 GiB / 20k end-to-end exceeds the
    60 s budget on the reference host.

## 15. Risks and non-goals

- Not an OS-level point-in-time image; per-file consistency only (§6.3).
- `flock` on NFS is not trustworthy; the backup root must be local.
- Hardlinks are visible to anything that later writes into a snapshot; the
  design forbids any such write, and restore writes only to its destination.
- No encryption, compression, remote replication, or dedup across differing
  content; those are out of scope for this fixture.
- Filesystem timestamp coarseness bounds default change detection; the
  `--recheck=hash` mode is the documented way to buy exactness at the cost of
  reading the source.

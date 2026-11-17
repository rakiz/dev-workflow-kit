# DESIGN-d1 — `backupctl`, a snapshot backup tool for the `evals/` workflow

Status: design only, no code written.
Author: working alone in this repo copy, per `BRIEF.md` ("Deliverable and working mode").

Target repo layout after implementation (all new files live beside the existing ones):

```
backupctl.py        # the tool (module + CLI, mirrors synccli.py's shape)
test_backupctl.py   # its test suite (mirrors test_synccli.py's shape)
synccli.py          # existing, reused
snaputil.py         # existing, reused
```

---

## 1. What `backupctl` is

`backupctl` takes a configured set of `N` directories (today three, a few dozen
over time) and produces **snapshots** under one backup root. A snapshot is a
point-in-time copy of *all* configured directories, published atomically so
that a reader never observes a half-built or mixed image.

```
backupctl run      # one full run: scan -> stage -> publish -> prune -> report
backupctl list     # list snapshots with sizes (uses snaputil)
backupctl verify   # validate a snapshot's index against its tree
backupctl prune    # apply the retention policy
backupctl gc       # delete expired trash from an interrupted prune
backupctl open     # helper the restore tooling uses to take a shared read lock
```

A run is driven by a JSON config file (one config = one backup root = one
locking domain):

```json
{
  "backup_root": "/data/backups/evals",
  "keep": 7,
  "keep_min_age_hours": 24,
  "trash_grace_seconds": 60,
  "sources": [
    {"id": "evals",     "path": "/data/work/evals"},
    {"id": "evals-logs","path": "/data/work/evals-logs"},
    {"id": "evals-cfg", "path": "/data/work/evals-cfg"}
  ]
}
```

`id` is a unique, filesystem-safe slug; it becomes the top-level directory name
inside a snapshot. Config errors are fatal (exit 1) before anything is touched.

Exit codes (identical for scheduler and human invocations — there is no
interactive path anywhere):

| code | meaning |
|---|---|
| 0 | run completed; snapshot published; no missing sources |
| 3 | snapshot published but **incomplete**: one or more source files vanished or were unreadable (snapshot itself is self-consistent) |
| 75 | `EX_TEMPFAIL`: another run holds the run lock; this run did nothing and changed nothing |
| 1 | fatal error (bad config, unwritable root, publish failed) — **no snapshot was published** |

---

## 2. Grounding: what already exists and is reused

Verified by reading the files and by running them in this repo copy
(`python3 -m unittest` → 6 tests, OK; plus targeted probes, results in the
right-hand column). Line numbers refer to the files as they stand today.

### 2.1 Reused as-is (no behavior change)

| Existing code | Used for | Verified behavior |
|---|---|---|
| `synccli.scan_files()` — `synccli.py:10-19` | listing source files (relative, sorted) | returns `['.dotfile', 'vis/y.txt']` for a tree with a `.hidden/` dir and a `.dotfile` — **dot-*files* are kept, dot-*directories* are skipped** (the `dirnames` filter at `synccli.py:14`) |
| `synccli.file_state()` — `synccli.py:22-25` | the per-file change-detection state | returns `{"size": st.st_size, "mtime": st.st_mtime}` |
| `synccli.changed_files()` — `synccli.py:36-42` | deciding what must be copied this run | dict equality over the state maps; 0.001 s for two 30k-entry maps (0.1 µs/entry, measured) |
| `synccli.collect_stale()` — `synccli.py:45-59` | reporting files that vanished from the source since the base snapshot | returns entries not in `seen` and not fresh; currently unused by `synccli.sync()` — we are its first caller |
| `snaputil.list_snapshots()` — `snaputil.py:8-20` | enumerating published snapshots | returns dirs under `backup_root` whose name starts with `snap-`, oldest first by name |
| `snaputil.snapshot_disk_usage()` — `snaputil.py:39-51` | reporting snapshot sizes | recursive sum of regular-file sizes; counts each hard-linked file once *per snapshot* (see §8.4) |
| `snaputil.is_stale()` — `snaputil.py:66-73` | deciding an orphaned staging dir / trash dir is old enough to delete | `os.stat(dir).st_mtime <= ref_epoch` |
| `snaputil.safe_snapshot_path()` — `snaputil.py:54-63` | mapping an index path back to a file inside a snapshot | `normpath` then join — **but see the escape defect in §2.3** |

### 2.2 Reused as the *shape* of the index

`synccli.build_manifest()` (`synccli.py:28-33`) produces a flat
`{relpath: {"size":…, "mtime":…}}` map. That is exactly the per-directory index
format `backupctl` stores, and `synccli.changed_files()` consumes it directly.
So the index of a snapshot directory is the same shape as `synccli`'s
manifest, and the incremental decision is literally `synccli.changed_files()`.
`backupctl` calls `synccli.build_manifest()` when re-deriving an index from a
snapshot tree (§6.3) — that is the "re-derived from the tree" recovery path,
and it is the only place the full builder is used (it raises on an unreadable
file, so the source scan uses the guarded variant in §2.3).

### 2.3 Explicit overrides of existing behavior

Every override names the exact function, says where it lives, and says why.

| Override | Location | Why |
|---|---|---|
| `copy_file` → `backupctl.copy_file()` | `synccli.py:62-69` | **Three defects, all fatal for a backup tool.** (a) It reads the whole file into memory: `fdst.write(fsrc.read())` — a 1 GiB artifact costs 1 GiB of RSS. (b) It swallows `OSError` and leaves **no destination file**, while `synccli.sync()` still writes the manifest entry — verified: an unreadable source produces `copied: ['secret.txt']`, no file on disk, and `manifest lists secret.txt: True`. That is exactly "an index that promises files the snapshot does not contain". (c) It writes straight to the final path, so a crash mid-write leaves a **truncated file at its final name** — a reader would see it. Our replacement copies in 1 MiB chunks to `<name>.part`, `fsync`s, `os.replace()`s it into place, preserves mtime with nanosecond precision (`os.utime(..., ns=...)`), and on any error removes the `.part` file and returns a failure record instead of pretending the copy happened. |
| `sync()`'s manifest write | `synccli.py:85-86` (`open(dst_manifest_path, "w")` then `json.dump`) | `open(..., "w")` truncates first: a crash or a full disk leaves a **half-written index** that a later reader would parse (or fail to parse). Our index writes go to `<name>.tmp` → `fsync` → `os.replace()` → `fsync(dir)`. |
| `scan_files()`'s dot-directory filter | `synccli.py:14` | `dirnames[:] = [d for d in dirnames if not d.startswith(".")]` silently drops `.venv/`, `.git/`, `.cache/` from a backup — silent data loss. `backupctl.scan_source()` (§3.3) keeps hidden directories but still keeps hidden files (matching `scan_files`' file behavior) and never follows symlinked directories. |
| `build_manifest()`'s unguarded `os.stat` | `synccli.py:22-25` / `28-33` | `file_state()` raises `OSError` on an unreadable file, which aborts the **entire** scan and therefore the whole run. Our scan wraps the stat per file and records the failure (§6.2). |
| `safe_snapshot_path()` | `snaputil.py:54-63` | Its docstring claims the result "never points outside backup_root/<snapshot_name>", but `os.path.normpath("../../etc/passwd")` → `"../../etc/passwd"`, so the join escapes. Verified: `safe_snapshot_path("/root","snap","../../etc/passwd")` → `/root/snap/../../etc/passwd` → realpath `/private/etc/passwd`. `backupctl.safe_snapshot_path()` keeps the function but adds a containment check against the resolved snapshot root and raises `ValueError` on escape. Paths we write into the index are produced by `os.walk` and can never contain `..`, so this is defense in depth against a hand-edited or corrupted index. |
| `prune_snapshots()` | `snaputil.py:23-36` | It calls `shutil.rmtree` directly, with no locking (it can delete a snapshot a restore is reading), no grace period, and it honours `keep=0` — verified: `prune_snapshots(root, 0)` deletes **every** snapshot, leaving the user with none. Our retention (§6.4) uses `snaputil.list_snapshots()` for the ordering and re-implements the deletion with a lock, a trash-and-grace phase, and a hard floor of one surviving snapshot. |
| `list_snapshots()` on a missing root | `snaputil.py:8-20` | `os.scandir` raises `FileNotFoundError` on a root that does not exist. `backupctl` creates the root (and `.locks/`, `.staging/`, `.trash/`, `.state/`) before calling it. |

### 2.4 Why this design could not have been written without reading `synccli.py`

- The index format, the change-detection call, and the scan are `synccli`'s, so
  the "unchanged" semantics of `backupctl` are literally
  `synccli.changed_files()`'s semantics (§7).
- `synccli.copy_file()`'s error handling is what makes the "index promises a
  missing file" and "truncated file at its final name" failures possible; the
  override is the core of the atomicity story (§4).
- `synccli.sync()`'s non-atomic manifest write is the concrete "half-written
  index" the brief asks about; its recovery is defined in §6.3.
- `snaputil`'s naming convention (`snap-YYYYMMDD-HHMMSS-NN`, `snaputil.py:9-14`)
  dictates the snapshot name format (§3.2) and the retention ordering.

---

## 3. On-disk layout

### 3.1 Backup root

```
<backup_root>/
  .locks/
    run.lock                    # exclusive flock, one per backup root
    snap-20261113-101500-00.lock   # per-snapshot lock (shared by readers)
  .staging/
    <run_id>/                   # everything a live run writes; never visible
  .trash/
    snap-20261113-101500-00.20261113T101512Z/   # pruned, awaiting rmtree
  .state/
    counter.json                # per-second snapshot-name counter
    reports/<run_id>.json       # machine-readable report of each run
  snap-20261113-101500-00/      # a published snapshot
  snap-20261113-101512-00/
  ...
```

Dot-prefixed names mean `snaputil.list_snapshots()` (`snaputil.py:17-19`)
naturally ignores them, and `snaputil.prune_snapshots()`/our retention never
sees staging or trash.

### 3.2 Snapshot naming

`snap-YYYYMMDD-HHMMSS-NN`, matching the format documented at `snaputil.py:9-14`
("a date, a time, and a run sequence number"). `NN` is a **per-second**
sequence number, zero-padded to two digits, so two runs in the same second get
distinct names. All fields are fixed width, therefore **lexicographic order ==
chronological order**, which is what `snaputil.list_snapshots()` sorts on and
what retention relies on.

The counter lives in `.state/counter.json` and is read/written only while the
run lock is held, so no contention. If `NN` would exceed 99 within one second
(physically implausible), the run fails with exit 1 rather than emitting a name
that would break the sort order.

### 3.3 Snapshot content

```
snap-20261113-101500-00/
  snapshot.json                 # run-level metadata (see below)
  .index/
    evals.json                  # per-directory manifest: synccli's map format
    evals-logs.json
    evals-cfg.json
  evals/                        # the point-in-time tree of source "evals"
    run-0001/result.json
    ...
  evals-logs/
  evals-cfg/
```

* The **tree** of a source lives at `<snapshot>/<source_id>/`, so the snapshot
  directory is itself a usable point-in-time copy of the source directory
  (a restore can copy `<snapshot>/<source_id>/` back over the source).
* The **index** lives in `.index/`, *outside* every source tree. That is
  deliberate: re-deriving an index from the tree (`synccli.build_manifest()`,
  §2.2) then cannot pick up the index file itself as a "source file", and a
  source directory that happens to contain a file called `snapshot.json` or
  `.index/` cannot collide with run metadata.
* `snapshot.json` holds: format tag, run id, creation time, base snapshot
  used for incremental reuse, per-source summary (file count, byte count,
  copied/reused/missing counts), the list of missing files, and the SHA-256 of
  each `.index/<id>.json` (integrity anchor for §6.3).

`.index/<id>.json` content (exactly `synccli.file_state()`'s dicts):

```json
{"run-0001/result.json": {"size": 4096, "mtime": 1763000000.123456}}
```

### 3.4 Scanning a source

`backupctl.scan_source(root)` is `synccli.scan_files()`'s traversal plus
`synccli.file_state()`'s state, with two changes:

* hidden **directories** are included (override of `synccli.py:14`, §2.3);
* the `os.stat` is guarded, so an unreadable file becomes a recorded failure
  instead of aborting the run (override of `synccli.file_state()`, §2.3);
* symlinked directories are not followed (`os.walk` default, `followlinks=False`);
  symlinks to files are recorded as symlinks in the index (target string) and
  recreated as symlinks in the snapshot — never followed, so a link pointing
  outside the source tree cannot pull foreign content into a backup.

---

## 4. The run protocol

```
   ┌─ acquire exclusive flock(.locks/run.lock)  ── busy → exit 75, nothing touched
   │
   ├─ housekeeping: discard orphaned staging dirs, gc expired trash, apply retention
   │
   ├─ for each source (one at a time):
   │     scan → compare with base index → stage tree (copy changed, hardlink unchanged)
   │     → verify staged files → write .index/<id>.json (atomic)
   │
   ├─ write snapshot.json (atomic) → fsync files/dirs → fsync staging dir
   │
   ├─ publish: os.rename(.staging/<run>/snap-<name>, <root>/snap-<name>)  [atomic]
   │           → fsync(<root>)
   │
   ├─ retention (§6.4): lock → rename to .trash/ → rmtree after grace
   │
   └─ report (stdout + .state/reports/<run_id>.json); exit 0 / 3
```

### 4.1 Two runs at the same time

The backup root has exactly one run lock, `.locks/run.lock`, taken with
`fcntl.flock(LOCK_EX)`.

* The scheduler and a human use the same code path and the same config, so
  they contend on the same lock.
* Default behaviour: **fail fast** — a run that cannot take the lock exits
  **75** immediately, having touched nothing. `--wait N` makes it wait up to
  N seconds (blocking `LOCK_EX` with a deadline) before giving up with 75.
* A crashed run does not hold the lock forever: the kernel releases an
  `flock` when the owning process dies (fd closed), so the next run proceeds
  without manual cleanup.

Why a lock at all, rather than letting two runs race into two staging areas:
the incremental base selection, the per-second name counter, and the
retention decisions are all "read the current state, then act" sequences.
Serialising them removes a whole class of races for the cost of one syscall.

### 4.2 A restore reading a snapshot while a run writes a new one

A run only ever writes inside `.staging/<run_id>/` and publishes with a single
`os.rename()` (§4.3). A published snapshot is never modified afterwards
(invariant I4, §4.5). Therefore a reader of an existing snapshot is
structurally unaffected by a concurrent run: the run creates *new* files
(new inodes) and only *links* to old ones. A file a reader has open keeps its
inode alive even if the run later prunes the snapshot it was hard-linked from.

The only genuinely dangerous overlap is **pruning a snapshot that is being
read**; that is handled in §6.4 with a per-snapshot lock plus a trash grace
period.

### 4.3 Atomic publish

The whole snapshot directory is built inside `.staging/<run_id>/snap-<name>/`
and then published with one `os.rename()` of the *directory* onto
`<backup_root>/snap-<name>`. `rename(2)` within one filesystem is atomic: a
reader sees either no directory or the complete directory. There is no window
in which `snap-<name>` exists but is incomplete, and no window in which the
tree and the index disagree.

Durability ordering before the rename:

1. every copied file is written to `<name>.part`, `fsync`ed, then `os.replace`d
   to its final name (so a file's content is on disk before it is visible);
2. every directory in the staged tree is `fsync`ed (persists the directory
   entries);
3. `.index/*.json` and `snapshot.json` are written with
   write-temp → `fsync` → `os.replace` → `fsync(parent dir)`;
4. the staging directory itself is `fsync`ed;
5. `os.rename(staging → <root>/snap-<name>)`;
6. `fsync(<root>)` so the rename itself survives a power loss.

### 4.4 Crash matrix

"The process can die at any point." Every row is a state the next run finds:

| crash point | on-disk state left behind | next run's action |
|---|---|---|
| during a file copy | `.staging/<run>/…/<name>.part` | whole staging dir discarded (§6.1) |
| after copying, before the index | staging tree without index | staging dir discarded; the source is re-scanned next run |
| during the index write | `.index/<id>.json.tmp` | staging dir discarded; no published index can be half-written, because the index is written *inside* staging and only becomes visible through the atomic rename |
| between the index write and the rename | complete but unpublished staging dir | staging dir discarded (work lost, nothing corrupted) |
| during the rename | atomic: either published or not | if published, it is a complete snapshot (it is the only place a snapshot can become visible) |
| after the rename, before retention | one extra snapshot | retention runs at the *start* of the next run too, so it converges |
| during retention, after the trash rename | `.trash/<name>…` | gc removes it once the grace period has passed (§6.4) |
| during `rmtree` of trash | partial trash dir | gc retries; trash is outside every reader's view |

The invariant across all rows: **no reader-visible path ever holds a partial
file, a partial index, or a mix of two runs.** Partial data exists only under
`.staging/` and `.trash/`, both dot-prefixed and invisible to
`snaputil.list_snapshots()`.

### 4.5 Invariants a reader may rely on

* **I1** — A published snapshot directory is complete and immutable. It became
  visible in one atomic step and is never written again.
* **I2** — Every path listed in `.index/<id>.json` exists in
  `<snapshot>/<id>/` with the recorded size. Verified file-by-file before the
  index is written; a file that could not be verified is *not* listed.
* **I3** — Every file in a snapshot is a whole file (never a partial write).
* **I4** — Files inside a published snapshot are never modified in place.
  Restores must write to a fresh destination; editing a snapshot file in place
  would change every snapshot that hard-links the same inode.
* **I5** — A snapshot's index and its tree were produced by the same run.

---

## 5. Data flow and incremental reuse

### 5.1 Base selection

The base for a run is the **newest published snapshot whose index validates**
(§6.3). If it does not validate, the run falls back to the next-newest, and
so on; if none validates, the affected source is backed up in full.

The base's `.index/<id>.json` (a `synccli.build_manifest()`-shaped map) is
compared with the freshly scanned source map using
`synccli.changed_files(base_map, new_map)` — the reuse of `synccli.py:36-42`
is the whole change-detection mechanism.

### 5.2 Reuse by hard link

For a file whose state is unchanged, the run does **not** copy the bytes. It
creates a hard link in the new snapshot to the inode already stored in the base
snapshot:

```
os.link(<base>/<id>/<rel>, <staging>/<id>/<rel>)
```

Rationale and consequences:

* The bytes are stored once no matter how many snapshots reference them, so
  the "copy everything, every time" cost is avoided (requirement §7 of the
  brief): a run that changes 1% of a 1 GiB tree writes ~10 MiB, not 1 GiB.
* A hard link is atomic — the file either exists complete or does not exist.
  There is no half-linked state to recover from.
* The link source is always inside `<backup_root>` (the base snapshot), so the
  link never crosses a filesystem boundary, regardless of where the *source*
  directory lives. `os.link` failing with `EXDEV`/`EPERM` (e.g. a
  filesystem without hard links) falls back to a byte copy of that file, and
  the run reports the fallback count.
* The base snapshot may be pruned later; the inode survives because the new
  snapshot holds a link. `shutil.rmtree` on the base unlinks its names, not
  the data.
* Consequence of I4: the shared inode is only safe because snapshot files are
  immutable.

### 5.3 What is copied

For each file the run picks exactly one of:

| case | action |
|---|---|
| present in the source, unchanged vs base (`synccli.changed_files` says unchanged) | hard link from the base snapshot (byte copy as fallback) |
| present in the source, new or changed | copy bytes into `<name>.part`, fsync, `os.replace`, preserve mtime (ns) |
| present in the source, but unreadable or vanished | **not** materialized; recorded as missing (§6.2) |
| present in the base, absent from the source | not materialized (the new snapshot simply does not contain it); reported as "deleted since last snapshot" via `synccli.collect_stale()` (`synccli.py:45-59`) |

The staging tree is built **fresh** every run, so a file that was deleted from
the source disappears from the new snapshot without any explicit delete step.

---

## 6. The hard cases from the brief

### 6.1 Interrupted run: orphaned staging

On start, holding the run lock (which proves no other run is alive), the run
scans `.staging/`:

* every entry there is an orphan of a dead run → `shutil.rmtree` it;
* the orphan check uses `snaputil.is_stale(staging_dir, run_start_epoch)`
  (`snaputil.py:66-73`): a staging directory created before this run started
  is stale by construction, because this run holds the only run lock.

Reported as: `discarded 1 orphaned staging dir(s) from dead runs (17,412 files)`.
This is the "the next run must make progress without manual cleanup"
requirement: no manual step is ever needed, and nothing a reader can mistake
for a snapshot is left behind, because staging lives under a dot-prefixed
directory and is never named `snap-*`.

### 6.2 A source file disappears or is unreadable

The run scans first, then copies. Between the two, a file can vanish
(`ENOENT`) or become unreadable (`EACCES`/`EPERM`); it can also be unreadable
at scan time.

Policy (identical for scheduler and human runs — one code path, no prompts):

* the file is **not** materialized in the snapshot;
* the file is **not** listed in the index (§4.5 I2: the index never promises a
  file the snapshot does not contain);
* it is recorded in `snapshot.json` under `missing[]` with its path, the
  source, the errno, and whether it was missing at scan time or at copy time;
* it is listed in the run report and the run exits **3** (published, but
  incomplete);
* the next run re-attempts it, because the next scan sees it again — this is
  the same "retry next pass" intent as `synccli.copy_file`'s comment
  (`synccli.py:69`), except that `synccli` hides the failure while we report it.

The snapshot itself remains fully usable: it is a complete, self-consistent
image of everything that *was* readable.

### 6.3 A corrupt or half-written index

**Half-written index.** In this design a published index cannot be half
written: it is written inside the staging area and only becomes visible
through the atomic rename (§4.3). A `.index/<id>.json.tmp` left by a dead run
lives in staging and is discarded with it (§6.1). So the "half-written index"
case has exactly one resolution — discard the staging area — and it is
handled by §6.1.

**Corrupt published index.** A published index can still be damaged by disk
error, by a partially-restored filesystem, or by hand editing. Detection:
`snapshot.json` stores the SHA-256 of each `.index/<id>.json`; on load the run
recomputes the digest and also parses the JSON. Either failing means the
index is invalid.

Recovery, per source directory, in order:

1. **Discard** the invalid index file: rename it to
   `.index/<id>.json.corrupt-<utc-timestamp>` inside the snapshot (kept for
   forensics, not deleted; it counts toward the snapshot's size).
2. **Re-derive** a replacement index **from the tree**, using
   `synccli.build_manifest(<snapshot>/<id>)` (`synccli.py:28-33`) — the
   snapshot's own files, i.e. exactly what a reader would find. The
   re-derived map is written back atomically (temp → fsync → rename) and the
   run updates `snapshot.json`'s digest for that file.
3. **Decide whether the snapshot may serve as the incremental base.** The
   re-derived index describes the tree that exists; the question is whether
   the tree is *complete*. `backupctl verify` (§9) compares the re-derived
   map against the *previous* valid index of that snapshot if one survives, and
   against the run's own expectations:
   * if the tree is self-consistent, the snapshot is used as the base. The
     re-derived state is `(size, mtime)` of the snapshot copies; because the
     copy preserves the source mtime with nanosecond precision (§4.3),
     `mtime` in the re-derived map equals the source's `mtime`, so the map
     remains a valid base for `synccli.changed_files()` in the next run.
     The only thing lost is any optional stricter signal (content hash,
     §7.2): the run notes "base index for 'evals' re-derived from tree —
     content-hash verification disabled for this source".
   * if the tree is *not* consistent (files missing relative to the surviving
     evidence, or unreadable), the snapshot is **not** used as the base for
     that source. The run falls back to the next-newest snapshot with a valid
     index, or — if none — performs a **full copy** for that source in this
     run.
4. **Report** it, in the human summary and in `.state/reports/<run_id>.json`:
   `source "evals": index invalid (sha256 mismatch) → discarded, re-derived
   from tree (30,100 files); snapshot used as base`.
   A fallback-to-full-copy is reported as
   `source "evals": index invalid and tree inconsistent → full copy performed`.

Nothing in this path requires a human: the run proceeds, publishes a valid
snapshot, and tells the operator exactly what it discarded, what it
re-derived, and what it did instead.

### 6.4 Retention

Policy (config: `keep`, `keep_min_age_hours`):

* the newest snapshot is **never** deleted;
* the newest `keep` snapshots are **never** deleted;
* any snapshot younger than `keep_min_age_hours` (default 24 h) is **never**
  deleted — this stops a burst of runs from emptying the backup root;
* among the remaining candidates, the oldest are deleted first.

Retained count is therefore
`max(keep, #{snapshots newer than keep_min_age_hours})`, and at least 1.
With `keep = 7` and an hourly schedule, `keep_min_age_hours = 24` gives
`max(7, 25) = 25` retained snapshots — the disk bound in §8.4 accounts for
both terms.

Deletion procedure, per candidate (this overrides `snaputil.prune_snapshots()`,
`snaputil.py:23-36`, per §2.3):

1. take an **exclusive** `flock` on `.locks/<snapshot>.lock`, with a deadline
   (default 30 s). A restore holding the shared lock blocks the deletion; if
   the deadline passes, this snapshot is **skipped this round** and reported
   (`skipped snap-…: in use by a reader`), not force-deleted;
2. `os.rename()` the snapshot into `.trash/<name>.<utc-timestamp>/` — atomic,
   and the new name does not start with `snap-`, so `snaputil.list_snapshots()`
   no longer offers it to anyone;
3. `fsync(<backup_root>)`;
4. the actual `shutil.rmtree` happens after `trash_grace_seconds`
   (default 60), performed by the next run's gc (or `backupctl gc`). The
   grace window protects readers that do not take the lock.

Guarantees: at least one complete, published snapshot always exists (the
newest, which was verified before publication and is never a prune
candidate); a snapshot being read is not deleted under the reader; and a
deleted snapshot is removed from the reader-visible namespace *before* its
bytes are freed.

### 6.5 Two runs colliding — restated

Covered in §4.1 (run lock, exit 75) and §4.2 (a run never writes outside
`.staging/` until the atomic rename).

---

## 7. Change detection: granularity and its blind spots

### 7.1 Default: `(size, mtime)` — `synccli.file_state()`'s granularity

The default unit of "unchanged" is exactly `synccli.file_state()`
(`synccli.py:22-25`): a file is unchanged iff its **size in bytes** and its
**mtime** are identical to the base snapshot's recorded values. mtime is
carried as a float seconds value (`st_mtime`), and the copy preserves it with
nanosecond precision (`os.utime(..., ns=...)`) so that the value read back
from a snapshot file is bit-identical to the value read from the source.

What this granularity **misses** (i.e. edits that are silently not backed up):

1. **Content changed, size identical, mtime restored.** Any tool that
   rewrites a file and restores its old timestamp (`rsync -t`, `cp -p`,
   `tar -p` extraction, editors that set mtime explicitly) produces exactly
   this. The snapshot keeps the old bytes.
2. **Content changed within the filesystem's mtime resolution.** On a
   filesystem with 1-second timestamp granularity (HFS+, some network and
   FAT-derived volumes), any same-size edit inside the same second is
   invisible. On APFS the timestamps are nanosecond-resolution, but
   `st_mtime` is a `double` and at the current epoch its resolution is
   ≈ 2.4·10⁻⁷ s, so sub-microsecond same-size edits are invisible.
3. **A file replaced by a different file with the same size and mtime** —
   same blind spot as (1).
4. **Truncated-then-regrown files**: size is the same at the end of the run,
   but the intermediate state was never captured — inherent to a
   point-in-time-of-the-end-of-the-run model.
5. **Permissions, ownership, xattrs, ACLs and empty directories are not
   captured.** `synccli.file_state()` records only size and mtime, and the
   snapshot preserves only content plus mtime. A snapshot is a copy of
   *content*, not a full metadata-preserving archive. (Documented as a scope
   decision; `cp -p`-style metadata capture would need a different state
   format than `synccli.file_state()`'s, which is out of scope here.)
6. **Symlink targets** are captured (as strings), but the *content* a symlink
   points at is captured only if it is itself inside the source tree.

### 7.2 Stricter modes (optional, off by default)

* `--hash` — the index additionally stores the SHA-256 of each file's content;
  a file is "unchanged" only if size, mtime **and** digest match. This closes
  blind spots (1) and (2) at the cost of reading and hashing every file on
  every run: measured SHA-256 throughput on this machine is **1308 MiB/s**,
  so a 1 GiB tree costs ≈ 0.8 s of hashing plus the read itself (the read is
  already paid by the copy; for the scan-only path it adds a full pass over
  `B` bytes, ≈ 1–3 s per GiB). Index size grows by 64 bytes per file
  (+1.9 MB per 30k files).
* `--strict-ctime` — the index additionally stores the **source** `ctime_ns`.
  `ctime` cannot be forged by user space, so any in-place modification bumps
  it even if size and mtime are restored; comparing *source ctime to source
  ctime* across runs therefore catches blind spot (1) without hashing. It is
  not the default for two reasons: it costs one extra `stat` per file
  (+≈ 20 µs/file, i.e. +0.6 s per 30k files) and it is **not recoverable
  after an index re-derivation** (§6.3), because a snapshot copy's ctime is
  the copy's ctime, not the source's — a re-derived base silently degrades to
  `(size, mtime)` for that source, and the run says so.
* `--verify` — after copying, re-read each copied file and compare its
  digest against the source's. Cost: one extra read pass over the changed
  bytes (≈ `ΔB` at 850 MiB/s, measured).

Neither stricter mode changes the *snapshot format*: the extra fields live
alongside `size`/`mtime` in the same per-source map, and `synccli.changed_files()`
is still the comparison (dict equality) — with the caveat that a map with
extra keys never equals a map without them, so **all** maps in a comparison
must be produced in the same mode. The run therefore records the mode in
`snapshot.json` and refuses to compare a `--hash` base against a non-`--hash`
scan (it falls back to a full copy for that source and says so).

---

## 8. Scale: what grows with what, with explicit bounds

Notation: `N` = number of configured sources, `F` = total files across all
sources, `F_d` = files in source `d`, `B` = total bytes, `ΔF` = files changed
or new this run, `ΔB` = their bytes, `U = F − ΔF` = files reused unchanged,
`K` = retained snapshots, `R` = runs per day.

### 8.1 Per-run work

```
T_run  ≈  T_lock + T_housekeeping
        + Σ_d [ F_d·c_stat + ΔF_d·(c_copy + bytes_d/BW) + U_d·c_link ]
        + F·c_index + T_publish + T_retain
```

Measured constants on this machine (macOS 15.8.1, Python 3.10.11, APFS
volume `/var/folders`, 2026-11-13; tree spread over 300 directories, 30,100
files, 0.81 GiB — see §10 for the harness):

| constant | measured | note |
|---|---|---|
| `c_stat` (scan one file) | 18–19 µs (`os.stat`); 33–85 µs/file for the full `synccli.build_manifest()` scan (0.99 s and 2.54 s in two runs over 30,100 files) | the variance is page-cache state |
| `c_copy` (create + write + fsync a small file) | 579 µs/file (17.42 s for 30,100 files) | dominated by per-file metadata + fsync, **not** by bandwidth |
| `c_link` (hard link one file) | 614 µs/file (18.49 s for 30,100 links) | on this volume a link costs about as much as a small copy; on a volume with cheap metadata ops it is far cheaper |
| `BW` (large-file copy) | 850 MiB/s (1.0 GiB in 1.18 s, 100 × 10 MiB files) | |
| aggregate small-file copy rate | 48 MiB/s (0.81 GiB in 17.42 s) | per-file overhead dominates |
| `c_index` (serialize the index) | 3.3 µs/entry (0.10 s for 30k entries) | `json.dump(..., indent=2)` |
| index comparison (`synccli.changed_files`) | 0.1 µs/entry (0.001 s for 30k) | |
| re-derive an index from a snapshot tree | 1.11 s – 2.66 s per 30k files | |
| `rmtree` of a 30k-file snapshot | 3.10 s | 103 µs/file |
| SHA-256 | 1308 MiB/s | |

Consequences, stated as bounds:

* **Per-run file work is `O(F)`** (every file is scanned and compared every
  run) — 30,100 files ≈ 1.0–2.6 s of scanning.
* **Bytes written per run is `O(ΔB)`**, not `O(B)`: unchanged files are hard
  linked (§5.2). For a 1 GiB tree with 1% changed, that is ≈ 10 MiB written
  instead of 1 GiB.
* **Per-directory overhead is `O(1)`** per source: one lock, one staging
  subtree, one index file. With `N = 50` sources, the per-source fixed cost
  is at most `N × (1 fsync of its index dir + 1 fsync of its tree root)`
  ≈ 50 × 2 × 10 ms ≈ 1 s (fsync bound not measured on this machine; it is
  the only unmeasured term in the model and is flagged as such).
* **Lock acquisitions per run: exactly 1** (`O(1)`), independent of `N` and
  `F`. Snapshot locks are per-snapshot and only touched by retention.
* **Retention cost**: `O(K)` list operations plus `O(Σ deleted F)` unlink work
  (3.10 s per deleted 30k-file snapshot, measured).

### 8.2 Memory

The index maps are the only per-file state held in RAM.

* Peak resident memory is `O(max_d F_d + ΔF_d)`, **not** `O(F)`, because the
  run processes one source at a time and writes that source's index before
  moving to the next (the base index of a source is loaded only while that
  source is being processed).
* Per-entry cost, measured: 63.7 bytes serialized (`json.dumps` of a 10,000
  entry map = 637,286 bytes); in-process a two-key dict plus its key string
  and two scalars is ≈ 300 bytes. Use **400 B/entry** as the in-process
  bound.
* Therefore: **peak memory ≤ 400 B × (F_max + ΔF_max)**, i.e. ≈ 12 MB for a
  30,000-file source, ≈ 120 MB for a 300,000-file source. The machine-readable
  report is written incrementally so it does not add to the peak.
* The report file is `O(F)` on disk (bounded by the number of missing files,
  normally 0).
* Bytes read into memory at once during a copy: **1 MiB** (the chunk size) —
  this is the fix for `synccli.copy_file()`'s `fsrc.read()` of the entire file.

### 8.3 Time to the first snapshot — the budget for a ~1 GiB / tens-of-thousands-of-files tree

**Budget: the first full backup of a 1 GiB tree with 30,000 files completes
in ≤ 45 seconds on this hardware and filesystem, with the run's own report
showing a measured wall-clock time.**

Derivation (not a guess):

```
T_full = F·c_copy + F·c_stat + B/BW + F·c_index + T_publish
       = 30,000 × 579 µs        (copy every file, fsync per file)
       + 30,000 × 85 µs         (scan, worst of the two measured runs)
       + 1 GiB / 850 MiB/s      (bulk transfer, 10 MiB files)
       + 30,000 × 3.3 µs        (index)
       + ~0.5 s                 (fsyncs + rename publish)
       ≈ 17.4 s + 2.6 s + 1.2 s + 0.1 s + 0.5 s
       ≈ 21.8 s
```

Measured end-to-end for the 0.81 GiB / 30,100-file tree: **18.51 s**
(scan 0.99 s + copy 17.42 s + index 0.10 s), i.e. the model and the
measurement agree within ~5 %. Scaling the measurement to 1 GiB gives
≈ 22.6 s. The **45 s budget is a 2× margin** over the derived 21.8 s,
covering the run-to-run variance observed (the scan alone varied 0.99 s →
2.54 s between two runs on the same tree).

Where the time goes, and what would change it:

* ~80 % of it is **per-file metadata + fsync cost**, not bandwidth. On a
  filesystem where `os.link`/`open+fsync` cost ~20 µs instead of ~580 µs
  (typical local NVMe), the same backup would take ≈ 30,000×40 µs + 1.2 s ≈
  2.4 s. The formula, not the number, is the portable statement.
* The dominant lever is therefore *not* bandwidth but the number of files; a
  tree of 300,000 small files would cost ≈ 3.5 minutes at these rates. The
  budget is stated for 30,000 files and scales as `F·c_copy`.
* `--hash` adds `B/1308 MiB/s` ≈ 0.8 s per GiB (plus the read pass) and is
  not in the 45 s budget.

Incremental runs on the same tree, for reference (measured):

| run | wall clock | what dominates |
|---|---|---|
| first full backup (0.81 GiB, 30,100 files) | 18.51 s | copying bytes (17.42 s) |
| no-change run (everything hard-linked) | 19.42 s | 30,100 `os.link` calls (18.49 s) |
| 1 %-changed run (301 copied, 29,799 linked) | 18.76 s | link calls again |

The no-change run is *not* faster than the full backup on this volume,
because a hard link (614 µs) costs about as much as copying a 1 KiB file
(579 µs) here. On a volume with cheap metadata operations the link case
would be ~30× cheaper. This is stated plainly rather than hidden: the
guarantee the brief asks for is *"the bytes of unchanged files are not copied
again"* (true, and worth 1 GiB → 0 B of writes), while the *wall-clock* saving
depends on the filesystem's metadata cost. §11 lists the alternative
(content-addressed store) and why it was not chosen.

### 8.4 Disk

Let `ΔB_i` be the bytes changed in run `i`.

* **Content**: each snapshot stores only the *new* versions; unchanged files
  are hard links to inodes already on disk. So

  `content_bytes(root) ≤ B + Σ_{i=1..K} ΔB_i`  (each retained snapshot
  contributes only the versions it introduced), with the trivial worst case
  `≤ K × B` when every file changes every run.
  For a 1 GiB tree with 1 % changed per hourly run and `K = 25` retained
  snapshots: `1 GiB + 25 × 10 MiB ≈ 1.25 GiB` — versus 25 GiB for a
  copy-everything design.
* **Metadata**: each snapshot carries one directory entry plus one index
  entry per file: ≈ 64 B (JSON, measured) + ≈ 100 B (filesystem directory
  entry) ≈ 165 B per file per snapshot. Total
  `≤ K × F × 165 B` = **35 MB** for `K = 25`, `F = 30,000`.
* **Trash**: at most one snapshot's worth, for `trash_grace_seconds`.
* **Staging**: at most `ΔB` + `F` entries during a run.
* Retention bounds the root at
  `B + Σ ΔB_i + K·F·165 B + (one snapshot in trash)`.
* Note: `snaputil.snapshot_disk_usage()` (`snaputil.py:39-51`) sums the size
  of every regular file per snapshot, so it counts a hard-linked file once
  **per snapshot**: its number is the *logical* size of a snapshot, not the
  *physical* size of the root. The run report prints both (§12).

### 8.5 What stays flat

| quantity | bound |
|---|---|
| run locks held | 1, independent of `N`, `F`, `B` |
| locks per retention pass | 1 per candidate snapshot (≤ `K`), independent of `F` |
| bytes buffered in memory during a copy | 1 MiB, independent of file size and of `F` |
| bytes written per run | `O(ΔB)`, independent of `B` when nothing changed |
| number of published snapshots | `max(keep, R·keep_min_age_hours)` — a function of the schedule, not of `N` or `F` |
| index files per snapshot | `N` (one per source) |
| per-source fixed overhead per run | `O(1)` (2 fsyncs + 1 index file + 1 tree root) |

---

## 9. Verification: `backupctl verify`

`verify` answers "can I trust this snapshot?" and is the mechanism behind
§6.3's base selection:

1. every path in `.index/<id>.json` exists in `<snapshot>/<id>/` with the
   recorded size (invariant I2);
2. the SHA-256 of each index file matches `snapshot.json`;
3. with `--hash`, each file's content digest matches the index;
4. it reports the snapshot as **valid**, **index-invalid (re-derivable)**, or
   **tree-inconsistent**.

`backupctl run` calls the same verification on the base snapshot before using
it, so a damaged snapshot is detected by the next run, not by a restore.

---

## 10. How the performance numbers were measured

The harness lives outside this repo copy (it is a measurement tool, not part
of the deliverable) and is reproduced here so the numbers can be re-derived.

* Tree: 300 directories × 100 files of 1 KiB (30,000 files, 30 MB) plus 100
  files of 8 MiB (800 MB) = **30,100 files, 0.81 GiB**.
* Copy primitive: 1 MiB chunks → `<name>.part` → `flush` → `fsync` →
  `os.utime(ns=…)` → `os.replace` — i.e. exactly `backupctl.copy_file()` as
  designed (§2.3).
* Reuse primitive: `os.link` from the previous snapshot.
* Index primitive: `synccli.build_manifest()` and `synccli.changed_files()`
  (the real functions, imported from this repo).
* Timer: `time.perf_counter()`, single run, warm page cache.

Raw results (2026-11-13, macOS 15.8.1, Python 3.10.11):

```
tree built in 5.3 s
files=30100 bytes=0.81 GiB
1) full backup: scan 0.99 s, copy 17.42 s, index 0.10 s  => total 18.51 s
   copy rate 48 MiB/s, 579 us/file
2) no-change run: scan 0.93 s, compare 0.00 s (0 changed), link 18.49 s => 19.42 s
   link rate 614 us/file
3) 1%-changed run: scan 0.92 s, compare 0.00 s (301 changed), mix 17.84 s => 18.76 s
4) re-derive index from snapshot tree: 1.11 s (30101 files)
5) rmtree of 30k-file snapshot: 3.10 s
sha256 of 8.0 MiB: 0.006 s -> 1308 MiB/s
build_manifest 30100 files: 0.99 s (first run) / 2.54 s (repeat, 84.5 us/file)
```

Supporting micro-measurements (3,000 files, one directory):

```
create empty file            91.6 us/op
create + write 4 KiB        105.6 us/op
create + write 64 KiB       145.1 us/op
stat existing file            18.4 us/op
os.link                     497.8 us/op
```

and (10,000 files, 10 KiB each, four variants):

```
copy (no fsync)              320.8 us/file
copy (fsync at close)        352.0 us/file
copy (fsync after close)     584.4 us/file
copy (no fsync) over existing 514.8 us/file
hardlink                     575.0 us/file
build_manifest                39.4 us/file
changed_files                  0.1 us/file
json.dumps                    0.009 s (637,286 bytes for 10,000 entries)
os.rename (publish)           0.000341 s
```

Caveats stated honestly: these are single-run measurements on one APFS
volume; the scan cost varied by 2.5× between two runs on the same tree
(page-cache state), and `os.link` at ~500 µs is unusually expensive for a
metadata operation, which is why the incremental-run wall clock is no better
than the full-backup wall clock on this volume. The **cost model** (§8.1) is
the portable statement; the numbers are this machine's instantiation of it.

---

## 11. Alternatives considered and rejected

* **Copy every file every run** (the "naive loop" the brief names): writes
  `B` bytes per run, `K × B` on disk, and makes the first-backup cost the
  *every* run cost. Rejected.
* **Content-addressed store (CAS) + per-snapshot manifest of digests**: the
  cheapest possible incremental run (a changed file is stored once, ever; a
  snapshot is a list of digests), at the price of making every snapshot
  *virtual* — a reader can no longer `cp -a` a snapshot directory, and the
  restore tooling must reassemble files from the store. It also makes the
  "index promises files the snapshot does not contain" guarantee a property of
  the *manifest* rather than of the directory. Rejected because the brief
  asks for "point-in-time copies of those directories" and because the
  separate restore tooling is easier to keep correct against a real
  directory. The measured cost difference on this volume is small
  (hard link 614 µs vs. store insert + one link), but the model in §8.1 shows
  the CAS variant would win on filesystems with cheap metadata ops — a
  re-evaluation worth doing if `backupctl` ever runs on a fast local SSD.
* **Reflinks / APFS clones** (`cp -c`, `clonefile`): copy-on-write clones
  would be both fast and space-efficient, but they are per-filesystem
  extensions, not portable to the volumes the backup root may live on. The
  design uses POSIX hard links, which are portable across the filesystems
  that matter here. (A future `clone` strategy could be added as a third
  reuse mode behind the same interface.)
* **rsync with `--link-dest`**: the same reuse idea, well tested. Rejected
  because it is an external dependency and because it does not give us the
  index format, the atomic publish, or the crash-recovery semantics this
  design needs.
* **Lock-free concurrent runs**: allowed to overlap by giving each run its own
  staging area and letting the atomic rename arbitrate. Rejected because the
  *incremental base* would then be ambiguous (two runs could pick different
  bases, and the second's hard links could point into a snapshot the first is
  pruning) and because the brief explicitly requires that colliding runs
  "may not corrupt a snapshot or each other's work" — a lock makes that a
  one-line proof instead of an argument.

---

## 12. The report

Human-readable (stdout):

```
run 20261113-101500-00  base snap-20261113-091500-00  duration 18.51s
  evals      30100 files  0.81 GiB   copied 301 (0.01 GiB)  reused 29799  missing 0
  evals-logs  1204 files  0.02 GiB   copied 0             reused 1204   missing 0
  evals-cfg     18 files  0.00 GiB   copied 18            reused 0      missing 0
  published  snap-20261113-101500-00
  pruned     snap-20261110-101500-00 -> trash (grace 60s)
  discarded 1 orphaned staging dir(s) from a dead run
```

Machine-readable (`.state/reports/<run_id>.json`): run id, start/end
timestamps, duration, per-source `{id, path, files, bytes, copied, reused,
missing[], errors[]}`, base snapshot used, snapshot published, pruned[],
skipped[], recovered[] (index re-derivations), warnings[], exit code.

The same information is printed to stderr as well, so a scheduler's log
captures it even if stdout is redirected.

---

## 13. Test plan (`test_backupctl.py`, `unittest`, like `test_synccli.py`)

| # | Requirement from the brief | Test |
|---|---|---|
| 1 | Concurrent runs do not corrupt each other | start a run holding the run lock, assert the second exits 75 and the root is unchanged |
| 2 | A reader never sees a partial snapshot | assert `.staging/` is invisible to `snaputil.list_snapshots()`; assert a snapshot dir only appears complete |
| 3 | Crash mid-run leaves nothing a reader mistakes for a snapshot | kill a run mid-copy (SIGKILL); assert no `snap-*` dir, then run again and assert it completes |
| 4 | The next run makes progress without manual cleanup | after (3), assert the orphan staging dir was discarded and reported |
| 5 | Corrupt index recovery | corrupt `.index/x.json`; assert it is discarded, re-derived from the tree, and the run reports it; assert the next run still does an incremental (not full) copy |
| 6 | Half-written index | leave a `.index/x.json.tmp` + truncated staging; assert it is discarded |
| 7 | Missing / unreadable source file | delete a file between scan and copy (monkeypatched); assert it is absent from the snapshot, absent from the index, recorded in the report, exit code 3 |
| 8 | Scheduler and human behave identically | the same run invoked twice through `main()` yields identical reports |
| 9 | Retention never empties the root | `keep=1` → assert one snapshot survives; assert the newest is never deleted |
| 10 | Deletion is safe while a reader holds the snapshot | take the shared lock, run retention, assert the snapshot is skipped and reported |
| 11 | Unchanged files are not copied again | second run → assert `copied == 0` and that the file's inode is shared with the previous snapshot (`os.stat().st_ino` equality) |
| 12 | Change detection granularity | a same-size edit with a restored mtime is *not* detected (documented blind spot); a size change *is* detected; `--hash` detects the same-size edit |
| 13 | Index never promises a missing file | assert every path in the index exists in the tree with the recorded size, after every run |
| 14 | Restore reads a snapshot while a run writes another | assert a restore of an existing snapshot succeeds during a concurrent run |
| 15 | Bounds | assert the number of locks is 1 per run; assert the index size is `O(F)` |

The existing suite (`python3 -m unittest`) must stay green — `backupctl` does
not modify `synccli.py` or `snaputil.py`; it only *calls* them (and, where
§2.3 says so, does not use their defective variants).

---

## 14. Requirements traceability

| Brief requirement | Where it is answered |
|---|---|
| Scheduler and human runs may collide; no corruption | §4.1 (single exclusive run lock, exit 75), §4.3 (atomic publish), §4.5 (invariants) |
| A restore may read a snapshot during a run | §4.2 (runs write only into staging), §6.4 (per-snapshot shared/exclusive locks, trash grace) |
| Readers see a complete, self-consistent image | §4.3, §4.5 (I1–I5), §6.2 (missing files are excluded from the index) |
| The process can die at any point | §4.4 (crash matrix), §6.1 (orphaned staging), §6.3 (corrupt index recovery) |
| A source file can disappear without warning | §6.2 (policy + report + exit code 3), same code path for scheduler and human |
| The backup root only grows; retention deletes old snapshots | §6.4 (policy, lock, trash, floor of one snapshot) |
| Unchanged files are not copied again | §5.2 (hard-link reuse), §7.1 (granularity), §7.2 (stricter modes) |
| Performance budget for the first full backup, derived not guessed | §8.3 (45 s budget, derivation, measurement), §10 (harness and raw numbers) |
| What grows with what, as explicit bounds | §8.1–§8.5 |
| Grounded in the existing code | §2.1–§2.4 (reuse table, verified behaviors, named overrides) |

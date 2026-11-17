# DESIGN-d1 — `backupctl`

Status: design for review. Target: a CLI backup tool that ships next to
`synccli.py` / `snaputil.py` in this repository.

This document is deliberately concrete about on-disk state, lock protocol,
failure recovery, and numbers. All line references are to the files in this
checkout; the measurements in §12 were taken in this checkout (§3.3).

---

## 0. Requirement traceability

| Requirement in `BRIEF.md` | Mechanism | Section |
|---|---|---|
| Two runs collide; restore reads during a write | per-source run lock; immutable published snapshots; reader leases | §6 |
| Reader never asks whether the producing run finished | staging + atomic directory rename; index written before publish | §4 steps 7–8, §5 |
| Process dies at any point | kernel-released `flock`; staging never visible; next run cleans it | §7 |
| Corrupt / half-written index left by a dead run | published indexes cannot be half-written; dead staging discarded; corrupt published index skipped, baseline re-derived | §7.2 |
| Source file disappears / is unreadable | omitted from the index, recorded in `problems`, snapshot still published atomically; identical for scheduler and person | §4.5, §10 |
| Retention must be safe, never leave no snapshot | `keep >= 1`; newest clean snapshot protected; non-blocking exclusive reader lock, rename-to-trash before delete | §9 |
| Unchanged files are not copied again | per-file state comparison against the newest valid prior index; hardlink from the previous immutable snapshot | §8 |
| First full backup budget | measured end-to-end prototype + explicit cost formula | §12 |
| What grows with N / files / bytes; what is flat | explicit formulas and measured constants | §11 |
| Grounding in this directory | reuse/override table with exact functions and line numbers | §3 |

---

## 1. Terms and scope

- **Source**: one configured directory. `N` = number of sources (3 today,
  a few dozen later). `F_s` = number of files in source `s`, `B_s` = bytes in
  source `s`; `F = Σ F_s`, `B = Σ B_s`.
- **Snapshot**: one complete, immutable image of one source, stored under
  the backup root. Each snapshot has its own index and tree.
- **Run**: one invocation of `backupctl run`. A run may cover all sources or a
  subset (`--source`).
- **K_s**: retention count for source `s` (default 7).
- **J**: number of sources processed concurrently (default 1, `--jobs`).

v1 fidelity: regular files, directories, symlinks, mode bits, mtime
(nanoseconds). Not preserved: ownership, xattrs/ACLs, ctime (not settable),
device nodes/FIFOs/sockets (recorded as `unsupported_type` problems, not
copied). Empty directories are recreated from the index. This is stated as a
limitation, not hidden.

A backup root must be a local POSIX filesystem that supports hardlinks and
`flock`. The tool probes both at startup. If hardlinks are unavailable it
degrades to full copies and reports `dedupe=unavailable` (the disk bound in
§11 then loses the hardlink saving and each snapshot costs its full `B_s`);
if `flock` is unavailable it refuses to run rather than run without mutual
exclusion.

---

## 2. On-disk layout

One independent snapshot chain per source. Using one root per source is what
lets the existing `snaputil` functions operate per source without changes:

```
<backup_root>/
  .backupctl/                      # nothing source-specific; optional global state
  sources/
    <source-id>/
      .run.lock                    # per-source writer lock (flock)
      .readers.lock                # per-source reader/delete lock (flock)
      .staging-<run-id>/           # in-flight, never listed, never readable as a snapshot
        .backupctl/index.json.tmp
        data/<source tree>
      .trash-<snap-name>-<uuid>/   # deletion in progress / crashed deletion
      snap-20261116-224800-0007/   # published snapshot; immutable after rename
        .backupctl/index.json
        .backupctl/lease           # per-snapshot reader lease (flock)
        data/<source tree>
```

- `<source-id>` is a validated slug plus `sha256(canonical source path)[:12]`
  to avoid collisions; the config may pin it.
- Snapshot names keep `snap-YYYYmmdd-HHMMSS-<seq>` so they match the format
  documented at `snaputil.py:8-14` and remain sortable. `<seq>` is derived
  under the run lock as `max(existing seq) + 1`, so ordering is robust to a
  backwards wall clock even when the name sort is not.
- The source tree lives under `data/`; the index lives under `.backupctl/`.
  This reserves the `.backupctl` name so a source file called
  `.backupctl/index.json` cannot collide with the snapshot's own index.
- A path is a *visible, complete snapshot* if and only if it is a directory
  named `snap-…` directly under `sources/<source-id>/`, contains both
  `.backupctl/index.json` and `.backupctl/lease`, **and** its index validates
  (§4.6). Staging and trash names never satisfy that predicate.
  `snaputil.list_snapshots` (`snaputil.py:8-20`) can enumerate the visible
  names; `backupctl` re-filters them by the exact name pattern because the
  current implementation only checks the `snap-` prefix (`snaputil.py:18`;
  verified: a directory `snap-garbage` is returned).

No source data is ever hardlinked *from the source*. Hardlinks only point from
a previous snapshot's `data/` tree to the new snapshot's `data/` tree, so a
later write to the source cannot mutate a snapshot.

---

## 3. Grounding: what is reused and what is overridden

### 3.1 Reused as-is

| Artifact | Use |
|---|---|
| `synccli.scan_files` (`synccli.py:10-19`) | Basis for enumeration: `os.walk` + `os.path.relpath` + sorted output. We keep its relative-path convention and sorted order, so snapshot paths are deterministic. |
| `synccli.changed_files(old, new)` (`synccli.py:36-42`) | Reused verbatim to compute the changed/new set: it returns every key whose state dict differs or is absent. This is exactly the incremental-set primitive we need. |
| `synccli.build_manifest` (`synccli.py:28-33`) | The `{relpath: state}` container shape is reused; `backupctl.scan_entries` supplies the state because `build_manifest` is hard-wired to the old `file_state` (§3.2). |
| `snaputil.list_snapshots` (`snaputil.py:8-20`) | Enumerates the per-source snapshot chain; output re-filtered by name pattern and re-sorted by parsed sequence for retention. |
| `snaputil.snapshot_disk_usage` (`snaputil.py:39-51`) | Reused for logical size reporting (sum of `st_size`). It is not used for physical usage because it double-counts hardlinks; see §3.2. |
| `python3 -m unittest` with `test_synccli.py` | Baseline suite: 6 tests, all passing in 0.014 s in this checkout. `backupctl` wraps rather than edits `synccli`, so these tests stay valid. |

`synccli.collect_stale` (`synccli.py:45-59`) is not reused: it only filters a
`(path, fresh)` list and never looks at time; its name suggests a staleness
policy it does not implement.

New files: `backupctl.py` (CLI, `run_source`, `materialize_file`,
`scan_entries`, index/lock/retention helpers; imports `synccli` and
`snaputil`) and `test_backupctl.py`. No existing file is modified, so the
existing suite continues to describe the untouched behavior.

### 3.2 Overridden, with the exact reason

| Function | Current behavior (verified) | `backupctl` replacement and why |
|---|---|---|
| `synccli.file_state` (`synccli.py:22-25`) | Returns `{"size", "mtime"}` with `st_mtime` as a float. Float seconds lose the nanosecond field (`st_mtime_ns`) and no ctime/inode/type/mode is recorded. | `stat_state()` records `st_size`, `st_mtime_ns`, `st_ctime_ns`, `st_mode`, `st_ino`, `st_dev`, and entry type via `os.lstat`. The nanosecond fields and ctime are what make §8's change detection meaningful; float mtime can miss a same-second edit. |
| `synccli.scan_files` (`synccli.py:10-19`) | `dirnames[:] = ... if not d.startswith(".")` (`:14`) silently drops hidden directories; symlinked directories are not descended; no error hook. | `scan_entries()` includes hidden entries (an evals result tree may contain `.config`, `.git`, dotfiles), detects symlinks with `os.lstat`, never descends a symlinked directory, and passes `onerror` to record unreadable directories as problems instead of aborting. The relative-path/sorted convention is kept. Excludes are explicit config globs, never implicit dot filtering. |
| `synccli.copy_file` (`synccli.py:62-69`) | `fsrc.read()` (`:67`) reads the whole file into memory, and `except OSError: pass` (`:68-69`) makes an unreadable source indistinguishable from success. No metadata preserve, no verification, no retry. | `materialize_file()` copies in 1 MiB chunks (bounded memory), raises typed `SourceVanished` / `SourceUnreadable` / `SourceUnstable`, copies into staging, verifies size, and records mode/mtime in the index. A 100 GiB file cannot OOM the backup process. |
| `synccli.sync` (`synccli.py:72-87`) | Builds the source manifest *before* copying (`:74`), copies changed files (`:83-84`), then overwrites `.sync_manifest.json` in place (`:85-86`). The destination is mutated in place; a failed copy is still listed in the manifest; a reader can see a mix of old and new; there is no locking and no incremental storage. | `run_source()` builds the index *from captured entries only*, writes it to staging, verifies it against the staged tree, and publishes the whole directory with one rename. This is the core correctness override (§4, §5). |
| `snaputil.prune_snapshots` (`snaputil.py:23-36`) | `len(names) <= keep` then `rmtree` of the oldest (`:32-35`). Verified: `prune_snapshots(root, 0)` deletes *everything*; no lock, no rename, no reader protection, no protection of a clean snapshot. | `prune_source()` clamps `keep >= 1`, protects the newest *valid* snapshot and the newest clean snapshot, takes a non-blocking exclusive reader lock, renames to `.trash-…` before `rmtree`, and reports what it did. §9. |
| `snaputil.safe_snapshot_path` (`snaputil.py:54-63`) | Normalizes only `rel_path`, then joins (`:62-63`). Verified in this checkout: `safe_snapshot_path(root, "snap-1", "../x")` returns a path containing `snap-1/../x` (resolves outside the snapshot), and `safe_snapshot_path(root, "snap-1", "/etc/passwd")` returns `/etc/passwd` — an absolute stored path escapes the backup root entirely. | `resolve_member()` rejects absolute paths, `..` components, empty segments, NUL, and any result whose `realpath` is not under `data/` of that snapshot. Index writing applies the same validation, so a malicious/corrupt index cannot steer a restore outside its snapshot. |
| `snaputil.snapshot_disk_usage` (`snaputil.py:39-51`) | Adds `st_size` for every `os.walk` file; hardlinked files are counted once per snapshot; file symlinks are followed by `os.stat`, potentially counting targets outside the snapshot. | Logical size still uses this function, clearly labelled "logical". `physical_usage()` walks the retained snapshots, counts each `(st_dev, st_ino)` once, and sums `st_blocks * 512`; symlinks are `lstat`ed. This is the number used for disk growth claims. |
| `snaputil.is_stale` (`snaputil.py:66-73`) | Docstring says "older than `ref_epoch`", code uses `<=` (`:73`) so "exactly equal" *is* stale; it compares directory mtime in float seconds. | Not used. Ownership is decided by `flock` and by index validity, both of which survive process death. mtime-based staleness cannot distinguish a live slow run from a dead one. |

### 3.3 Checks performed for this design

- `python3 -m unittest -v`: 6 tests, OK (0.014 s).
- Python 3.10.11, macOS 15.8.1, APFS local volume.
- Verified `os.link` exists, `os.clonefile` does not; `flock`, `st_mtime_ns`,
  `st_ctime_ns` available.
- Reproduced the `snaputil` path/list/prune defects above with throwaway
  directories (details in the table).

---

## 4. Run pipeline (one source)

All steps for source `s` happen while holding `s/.run.lock` (§6.3).

1. **Recover** (still under the lock): list `s/`. Delete every
   `.staging-*` and `.trash-*` directory. Because only the run-lock holder
   creates staging for `s`, any staging seen now belongs to a dead run; the
   lock being held proves no live run exists. Report each deletion (name,
   bytes, count) in the run report. Trash removal needs no reader lease: a
   deleter renames to trash only after acquiring the exclusive reader lock
   (§9), so no reader can be inside a trash entry.
2. **Scan**: `scan_entries(source_path)` walks with `os.lstat`, producing:
   - `files[rel] = stat_state(...)` for regular files,
   - `symlinks[rel] = {"target": ..., "state": ...}`,
   - `dirs[rel] = {"mode", "mtime_ns"}` for directories,
   - `problems[]` for unreadable directories (walk errors).
   `scan_entries` is the override of `synccli.scan_files` described in §3.2.
3. **Pick baseline**: collect visible snapshot names, newest first by parsed
   sequence, and validate indexes (§4.6) until one valid index loads. That
   snapshot is the incremental baseline. Any invalid newer index is reported
   (§7.2), never modified, and skipped. If no valid baseline exists, the run
   is a full backup.
4. **Classify**:
   - `captured` starts empty.
   - For each regular file in the scan, use `synccli.changed_files(baseline,
     scanned)` to get changed/new paths (reused verbatim).
   - Unchanged path: `lstat` it once more immediately before linking. If its
     state still equals the scan state **and** the baseline's stored file
     exists with the expected size, hardlink `baseline/data/rel` to
     `staging/data/rel`. Otherwise fall through to copy (covers a source
     that changed between scan and link, or a missing baseline file).
   - Changed/new path: copy (§4.5). Never hardlink from the source.
5. **Populate index**: only after a file is successfully materialized do we
   add it to `staging_index.files`; only successfully created symlinks and
   directories do we add to `symlinks`/`dirs`. Skipped files are never added
   to `files`; they go to `problems`. This produces the invariant "the index
   never promises a file the tree does not contain", by construction.
6. **Verify**: for every `files`/`symlinks`/`dirs` entry, `lstat` the staged
   path and check that it exists with the expected type and size. Any
   mismatch is an internal error: delete staging, publish nothing, exit 1
   with the offending path. This is the second, independent enforcement of
   the same invariant.
7. **Write index** (§4.6) to `staging/.backupctl/index.json.tmp`, `fsync` it,
   rename to `index.json` (same directory, atomic), create the empty
   `staging/.backupctl/lease`, then chmod the tree (files `0444`, directories
   `0555`, as in §13; the lease itself stays `0644`) and `fsync` the staging
   dir.
8. **Publish**: `os.rename(staging, s/snap-<stamp>-<seq>)` — atomic within the
   source's filesystem, and it refuses an existing non-empty target (we use
   `rename`, not `replace`). Then `fsync` `s/`. At the instant of the rename,
   every file, every directory, and the complete index are already in place.
9. **Prune and clean** (§9), then release locks.

Step 8 is the only moment a snapshot becomes visible. There is no "in
progress" marker for readers to interpret and no window in which a directory
named `snap-…` exists with fewer files than its index lists.

### 4.5 A file that vanishes, is unreadable, or keeps changing

`materialize_file()` handles three outcomes; all three use the same code path
regardless of who invoked `backupctl`:

| Event | Snapshot content | Index | Report |
|---|---|---|---|
| `lstat`/`open` raises `ENOENT` (vanished between scan and copy) | file absent from this snapshot | absent from `files`; listed in `problems` as `vanished` | problem line + `status: partial`, exit 3 |
| `open`/`read` raises `EACCES`, `EIO`, … | partial staging file is removed; file absent | absent; problem `unreadable` with errno | same |
| source `(size, mtime_ns, ctime_ns, ino)` differs before vs after copy | staging file removed; file absent | absent; problem `unstable` after 3 attempts | same |
| copy succeeds and post-stat equals pre-stat | file present, bytes complete | present, with the scan state | normal |
| file vanishes after its successful copy | file present (a valid copy of the version observed during scan) | present | normal |

A successful copy is chmod `0444` and `utime`d to the source `mtime_ns`; the
original mode and mtime are recorded in the index. A hardlinked file already
carries the same mtime (state equality is required) and is not `utime`d,
since that would mutate the shared inode. If the source *root* itself is
missing or unreadable, the source is an error: no snapshot is published
(publishing an empty snapshot would misrepresent the source) and the run
exits 1.

A snapshot with problems is still published and is still a *complete image of
what it contains*: `status: partial` is metadata about the source, not an
indication that publication or the index is incomplete. `complete` in the
index means "publication finished and the index matches the tree". Both
scheduler and person get exactly this behavior: no prompts, no TTY detection,
no different branch. Exit code 3 is the only signal, and the same run report
is emitted in both cases (§10).

### 4.6 Index format and integrity

One JSON document per snapshot, `snap-…/.backupctl/index.json`:

```json
{
  "format": "backupctl.index/1",
  "snapshot": "snap-20261116-224800-0007",
  "source": {"id": "evals-main", "path": "/srv/evals", "dev": 16777220},
  "created_ns": 1763333280123456789,
  "complete": true,
  "status": "complete",
  "files": {
    "results/run-1/out.json": {
      "size": 1234, "mtime_ns": 1763333200000000000,
      "ctime_ns": 1763333250000000000, "mode": 33188,
      "ino": 987654, "dev": 16777220
    }
  },
  "symlinks": {"link": {"target": "../x", "mtime_ns": 0, "ctime_ns": 0}},
  "dirs": {"results/run-1": {"mode": 16877, "mtime_ns": 0}},
  "problems": [
    {"rel": "results/run-2/out.json", "kind": "vanished", "errno": 2, "at": "copy"}
  ],
  "counts": {"files": 20000, "symlinks": 1, "dirs": 1200, "problems": 1},
  "body_sha256": "…"
}
```

- `body_sha256` is SHA-256 over the canonical serialization of every field
  except itself: `json.dumps(obj, sort_keys=True, separators=(",", ":"),
  ensure_ascii=True).encode("utf-8")`. `ensure_ascii=True` makes non-UTF-8
  filenames representable via JSON escapes without invalid byte sequences.
- `complete: true` is the publication invariant ("all data written, index
  matches the tree"). `status` is about the source (`complete` vs `partial`
  when there are problems); a partial snapshot still has `complete: true`.
- Keys are validated by `validate_rel()`: relative, no `..` segment, no
  absolute path, no NUL, no empty segment.
- The index is written **last**, after all data and the verification pass, and
  renamed into place inside staging. A published snapshot therefore cannot
  have a truncated index: either the whole staging directory (including a
  complete index) was renamed, or nothing was published. A half-written
  `index.json.tmp` can exist only under `.staging-*`, which is discarded by
  the next run (§7).
- Logical size and per-snapshot reporting call
  `snaputil.snapshot_disk_usage`; physical usage uses `physical_usage()`
  (§3.2), because hardlinks make `st_size` sums misleading.

---

## 5. Why a reader cannot observe a half-written snapshot

There are only three states of a snapshot path:

1. It does not exist (not started, or staging, or in trash). A reader that
   enumerates `snap-…` entries does not see it.
2. It exists as `.staging-…` or `.trash-…`. Readers never consider these
   names; `list_snapshots` plus the exact-name filter excludes them.
3. It exists as `snap-…`. It was produced by an atomic rename of a directory
   whose data and index were complete and verified before the rename. Nothing
   writes into a `snap-…` directory afterwards: every run either copies or
   links into a new staging tree, and retention only removes whole snapshots.

A reader therefore never needs to ask whether the producing run is finished.
"Published directory present" is the completion signal, and it is installed
by a single atomic operation. The index cannot promise a missing file because
it is generated from the set of files the verification pass just confirmed,
not from the earlier scan set (the fatal flaw in `synccli.sync`, where the
manifest is built at `synccli.py:74` but copy failures are swallowed at
`synccli.py:68-69`).

---

## 6. Concurrency model

### 6.1 Run vs. run

- Two runs on **different** sources never share a lock and proceed fully in
  parallel. A single process can process sources with `--jobs J`.
- Two runs on the **same** source serialize on `s/.run.lock`
  (`flock(LOCK_EX)`): the first holds it for its whole run; the second waits
  up to `--wait` (default 60 s) and then marks that source `busy`, skips it,
  and reports it. It never copies into the same staging path, never derives
  the same sequence number, and never prunes concurrently. Skipping is a
  valid progress policy: the scheduler's next tick will run it.
- `flock` is released by the kernel when the process exits or is killed, so a
  crashed run cannot leave a lock a later run must break. There is no PID file
  and no manual cleanup step.
- Sequence allocation and retention both happen under this same lock, so a
  name collision or a prune/rename race between runs is impossible.
- Lock order is always `run.lock` → `readers.lock` → snapshot `lease`.
  Readers enter at `readers.lock` (never at `run.lock`), and no path takes
  these in reverse, so there is no deadlock cycle (§6.3).

### 6.2 Writer vs. reader (restore)

Snapshots are immutable, so a restore may read snapshot `S` while a run is
copying into a new staging tree with no interaction at all. The one operation
that can remove `S` is retention. Protection is **per snapshot**, so one
restore does not stop retention from removing other old snapshots:

- A reader (the restore tooling, a human, `backupctl verify`) does:
  1. acquire `s/.readers.lock` shared (`LOCK_SH`), which excludes a concurrent
     delete/rename for the short list+lease section (steps 2–3);
  2. list/validate the snapshots and choose `S`;
  3. open `S/.backupctl/lease` and acquire `LOCK_SH` on it;
  4. release `s/.readers.lock` and keep the per-snapshot lease for the whole
     time it reads `S`'s files.
- A pruner acquires `s/.readers.lock` exclusive (`LOCK_EX | LOCK_NB`) only
  around listing and lease acquisition. For each deletion candidate it tries
  `LOCK_EX | LOCK_NB` on that candidate's `.backupctl/lease`:
  - acquired ⇒ no reader holds this snapshot: rename the snapshot to
    `.trash-…` (atomic), keep the lease fd, and delete later;
  - busy ⇒ an active restore is reading *this* snapshot: skip it, try the
    next candidate. Other candidates are still pruned; the run reports
    `prune_skipped: [snap, …]`.
  The pruner never waits on, interrupts, or truncates a read. If the short
  `readers.lock` critical section itself is occupied, the prune is deferred
  to the next run (`prune_deferred: lister_active`).
- Ordering makes the race impossible: the reader's source lock and the
  per-snapshot lease are acquired in the order reader-side `SH → SH`, while
  the pruner uses `EX → EX`, both in the same global order (source lock
  first). A snapshot whose lease the pruner acquired cannot be listed by a
  new reader (it is already renamed) and cannot have an old reader (a shared
  lease would have made the exclusive acquire fail).

`backupctl` ships the reader helper so the separate restore tooling has one
correct way to participate:

```
backupctl read-lease --source evals-main --snapshot snap-… -- restore-cmd …
```

which holds the source lock just long enough to take `S`'s lease, holds the
lease for the lifetime of `restore-cmd`, and exports `BACKUPCTL_SNAPSHOT`;
or, when embedded in Python,
`with reader_lease(source_dir, snapshot) as lease: lease.path("results/x.json")`.
A reader that ignores the lease is not corrupted (snapshots are immutable),
but its path-based reads may fail with `ENOENT` if retention renames the
snapshot; that is outside the safety guarantee, and the helper exists to make
following the contract easy. Integration requirement: the separate restore
tool runs under `backupctl read-lease` (or imports `reader_lease`); this is a
one-line wrapper, and it is what makes retention safe against an in-flight
restore.

### 6.3 Lock details

- Lock files are ordinary files opened `O_RDWR|O_CREAT`, mode 0600; the
  per-snapshot `lease` is created in staging before publish and is mode 0644
  so a reader in the backup owner's group can take a shared lock. A lock file
  is never unlinked while in use: unlinking a locked `flock` file would let a
  second process create a new inode and bypass the lock.
- Acquisition uses non-blocking attempts in a short sleep loop, bounded by
  `--wait`; no unbounded blocking, no busy spin.
- Global lock order is `run.lock` → `readers.lock` → snapshot `lease`.
  Readers hold `readers.lock` only during list+lease acquisition, then hold
  only the snapshot lease. No path takes locks in the reverse order, so there
  is no deadlock cycle.
- The run lock is held across scan, copy, publication, and prune. Staging
  cleanup is safe precisely because no other live process can be writing that
  source's staging area.

---

## 7. Crash and corruption recovery

### 7.1 Publication crash matrix

| Crash point | State on disk | Reader sees | Next run |
|---|---|---|---|
| during scan | no staging yet | old snapshots only | normal |
| while copying into staging | partial `.staging-…`, no `snap-…` | old snapshots only | deletes staging, continues |
| after all copies, before index | staging complete but no final index | old snapshots only | deletes staging (it was never published) |
| while writing `index.json.tmp` | staging with a truncated temp index | old snapshots only | deletes staging; the temp is never read |
| after index rename inside staging | complete staging | old snapshots only | deletes staging; no partial snapshot is exposed |
| during `os.rename(staging, snap-…)` | rename is atomic: old name or new name, never both | either no snapshot or a complete one | normal |
| after publish, before `fsync(s/)` | snapshot present (process death does not lose page cache) | complete snapshot | normal; for power-loss durability see below |
| during prune after rename to `.trash-…` | snapshot gone from listing, trash remains | other snapshots intact | deletes trash |
| while holding locks | kernel releases them at process death | old snapshots intact | acquires immediately |

The "half-written index" left by a dead run is therefore always a
`index.json.tmp` (or a partial `index.json`) **inside `.staging-…`**. The next
run discards the entire staging directory and reports it; it never adopts,
repairs, or renames it, because a staging tree is not known to be complete.

Durability scope: the default guarantees process-crash safety (Ctrl-C, kill,
sleep) because data is closed and index/directory entries are in the kernel
before the atomic rename. Power-loss safety additionally requires data
`fsync` (on macOS `F_FULLFSYNC` for media flush). `--durability=power` enables
per-file data sync before publication; it is not part of the §12 budget, and
its cost is hardware-dependent. Index and directory fsync are always done
because they are cheap (measured index write+fsync: 41 ms for 20k entries).

### 7.2 A corrupt or half-written *published* index

A half-written published index cannot be produced by this design (§7.1), but
a published index can still become unreadable through bit rot, an externally
truncated file, a filesystem error, or a foreign writer. Recovery is
deterministic and is reported:

1. `load_index()` reads the file, parses JSON, checks `format`,
   `complete == true`, the key/path invariants, and recomputes
   `body_sha256`. Any failure raises `CorruptIndex(reason)`.
2. The run **discards the index for reuse** (it is never used as the
   incremental baseline) but **does not modify or delete the snapshot**:
   published data is immutable, and the snapshot's tree may still be useful.
3. The run chooses the **newest older valid index** as the baseline. The
   current state is always re-derived by a fresh `scan_entries()` of the
   *source tree*, so correctness of the new snapshot does not depend on the
   corrupt file. If no older valid index exists, the run performs a full copy
   (no hardlinks).
4. The run report contains `index_recovery: {snapshot, reason,
   baseline: "<older-snapshot>" | "none (full copy)"}` and the run exits 3
   (completed with warnings).
5. If the corrupt snapshot is the newest, it remains protected by retention
   until a newer valid snapshot exists; after that it is eligible for normal
   age-based deletion. A corrupt index never makes a restore silently return
   partial data: `read-lease` verifies the index and reports `CorruptIndex`
   instead.

Why not "re-derive the index from the snapshot tree"? The index records the
**source's** `ctime`/`ino`/`dev`, which cannot be reconstructed from the stored
copy (copying cannot preserve ctime, and hardlinked entries share the inode).
Re-deriving from the snapshot would produce a baseline that compares unequal
to the source and silently degrades to full copies. Re-deriving the *current*
source state and using an older valid baseline is both correct and cheap.

### 7.3 Signals

First `SIGINT`/`SIGTERM`: set an abort flag checked between files and between
prune operations. The run finishes the current file, removes its staging
directory best-effort, releases locks, writes an `interrupted` report, and
exits 130. If `SIGKILL` or a machine crash prevents that, §7.1 applies.

---

## 8. Change detection: granularity and blind spots

**Unit of decision: one filesystem entry.** Regular files are compared by
`(type, size, mtime_ns, ctime_ns, ino, dev, mode)` against the newest valid
prior index; symlinks by `(type, target)`. Directories are not used to gate
copies (they are recreated from the index).

- Unchanged ⇒ no data read: hardlink the previous snapshot's inode.
- Changed/new ⇒ read the source and copy the bytes.
- Deleted ⇒ absent from the new index and tree (the snapshot reflects the
  deletion); no tombstone is needed because each snapshot is a full image.

A hardlink is storage sharing, not a semantic mix of runs: the state equality
that authorized the link means the linked bytes are exactly the bytes the
source has at this run's scan. Every entry in the snapshot therefore represents
this run's observed source state; no entry is a stale previous-run version
that the current source no longer has.

Without filesystem-level snapshots, no userspace copier can freeze all files
at one global instant. The guarantee is per file: each entry is a complete
version actually observed during this run (and a file that changes during its
copy is retried or omitted), while a file modified after its own copy is
captured at the earlier version. This is the strongest available guarantee and
is stated rather than implied.

Metadata-only changes are intentionally treated as changes (a `chmod` costs
a full copy even though the bytes are identical). That is a false positive
in the safe direction: it never misses a content change and only spends
extra I/O.

What this granularity can miss:

1. A content edit that preserves **size, mtime, ctime, inode, and device**. On POSIX,
   a write updates ctime, which users cannot set back, so this requires a
   filesystem/OS that does not update ctime (or has coarse ctime granularity)
   and an explicit mtime restore. It is not reachable with ordinary
   `write()`+`utime()` on the filesystems this tool supports.
2. Two edits within the filesystem's timestamp granularity where the second
   restores the size and mtime of the first, and ctime is coarser than the
   edit interval (e.g. a 1-second-granularity ctime on a filesystem that
   still reports nanoseconds syntactically). On APFS/ext4 with nanosecond
   stat fields the measured `st_ctime_ns` changes per write and is detected.
3. A change made and reverted to byte-identical content **is** reported
   unchanged if all stat fields match. This is correct for the new snapshot's
   content (the bytes are identical) but loses the intermediate version,
   which was never requested as a snapshot.
4. Sub-file block changes are not detected independently: the decision is
   per file, not per block. A 1-byte change recopies/links the whole file.
5. Data corruption in a prior snapshot that is not reflected in the source is
   not detected by stat comparison; `--hash` stores SHA-256 per file at copy
   time and `backupctl verify --content` detects it, at the measured cost in
   §12.

`--hash` does **not** change the incremental decision by default: hashing
unchanged files would force reading the full tree every run. It is used for
verification, and `backupctl run --verify-content` may be used when the
stat-based blind spots above are unacceptable.

Detected-state semantics: for a copied file, the state recorded is the one
observed *before* the copy, and the post-copy `lstat` must equal it or the
file is retried/omitted (§4.5). For a hardlinked file, the source is
re-`lstat`ed immediately before linking; if it changed since the scan, the
file is copied instead. Thus every entry in a snapshot corresponds to a state
actually observed during this run.

---

## 9. Retention

Policy per source, evaluated at the end of a successful run (or via
`backupctl prune`), under `.run.lock`:

- `keep = max(1, K_s)`; the newest snapshot is always retained, so the user
  always has at least one usable snapshot.
- Additionally retain the newest snapshot whose index `status == "complete"`
  (no `problems`). If the newest snapshot is partial, the last clean one is
  protected as well.
- Ordering is by the sequence parsed from the name, not raw name sort, so a
  backwards clock cannot make a new snapshot look oldest.
- Deletion is oldest-first, one snapshot at a time:
  1. Acquire `readers.lock` `LOCK_EX | LOCK_NB` for the short section that
     lists candidates and takes their leases. On failure (a reader is in its
     short list+lease section), stop and report `prune_deferred:
     lister_active`; retry next run. Never block the backup.
  2. For each deletion candidate, oldest first: open `snap/.backupctl/lease`
     and try `LOCK_EX | LOCK_NB`.
     - Busy ⇒ an active restore is reading this snapshot. Skip it, add it to
       `prune_skipped`, and continue with the next candidate.
     - Acquired ⇒ `rename(snap, .trash-<snap>-<uuid>)`; `fsync` the source
       dir; keep the lease fd so the lock survives the rename.
  3. Release `readers.lock` (readers may now list and lease other snapshots).
  4. For each renamed trash: `remove_tree(trash)`, report bytes freed, then
     close the lease fd. On error leave the trash and report it (next run
     retries cleanup). `remove_tree` first walks the tree and chmods every
     directory from `0555` to `0700` (snapshot directories are intentionally
     non-writable, so a plain `rmtree` would fail with `EACCES` on the first
     unlink), then removes it bottom-up.
- A crash between steps 2 and 4 removes the snapshot from listing but leaves
  bytes in trash; the next run deletes the trash under the run lock (§4 step
  1). Because the rename in step 2 is only done after acquiring that
  snapshot's exclusive lease, no reader can be inside it.
- Retained count bound: `K_s + 1` (normally `K_s`; the extra one appears when
  the newest is partial and the newest clean snapshot falls outside the newest
  `K_s`). If `L_s` snapshots are actively leased at prune time, those cannot
  be deleted and the bound becomes `K_s + 1 + L_s`; `L_s` is at most the
  number of concurrent restores/verifies, and `prune_skipped` names exactly
  those snapshots. An indefinitely
  open restore can therefore delay deletion of *its own* snapshot only, never
  of the others. If a process is stopped inside the short list+lease section,
  the whole prune is deferred until that process resumes; that costs retention
  delay, never correctness.
- Deletion never touches a `snap-…` that an active run just published: the
  publisher holds the run lock until pruning is done, and the newest is
  protected regardless.
- Removing a source from the config does not delete its data. Its chain simply
  stops growing (bounded by its last `K_s + 1 + L_s`); `backupctl prune
  --source <id>` can still apply the policy explicitly. No implicit
  `rm -rf`-by-config-deletion.
- If `keep` is configured as 0, it is clamped to 1 with a warning.

---

## 10. Reporting and exit codes

Every source gets one report entry; the whole run gets one JSON document
(optional `--json-report PATH`, also summarized on stderr):

```json
{
  "run_id": "…",
  "started_ns": 0,
  "sources": [{
    "id": "evals-main",
    "status": "ok | partial | busy | error | interrupted",
    "snapshot": "snap-…" | null,
    "baseline": "snap-…" | "none",
    "counts": {"files": 0, "copied": 0, "linked": 0, "symlinks": 0,
               "dirs": 0, "vanished": 0, "unreadable": 0, "unstable": 0},
    "problems": [{"rel": "…", "kind": "vanished", "errno": 2}],
    "index_recovery": {"snapshot": "…", "reason": "…", "baseline": "…"} | null,
    "staging_cleaned": ["…"],
    "pruned": ["…"], "prune_skipped": ["…"],
    "prune_deferred": null | "lister_active",
    "bytes_written": 0, "bytes_linked": 0
  }]
}
```

Exit codes, in precedence order: `130` interrupted; `1` fatal (e.g. backup
root unwritable, source root missing, verification failure); `2`
usage/config error; `4` at least one source was busy and skipped; `3`
completed with warnings (partial source, corrupt-index fallback, prune
deferred, or hardlink fallback); `0` all clean. The exit code and report are
identical whether the scheduler or a person invoked the command: there is no
interactive branch, no prompt, and no terminal-dependent behavior.

---

## 11. Scaling: what grows with what, with bounds

Let `N` sources, `F_s` files / `B_s` bytes in source `s`, `F = ΣF_s`,
`B = ΣB_s`, `K_s` retention, `J` concurrent workers, and `C_s,i` the total
size of the files **copied** into snapshot `i` of source `s` (new and changed
files; a hardlinked unchanged file contributes zero bytes).

| Quantity | Explicit bound | Evidence / notes |
|---|---|---|
| Per-run metadata work | `Σ_s (c_scan·F_s) + N·c_src`, `c_scan ≈ 25 µs/file` (lstat scan), `c_src ≈ 0.13 ms/source` (open+flock+close 62 µs, root `scandir` 63 µs measured) | measured §12 / §3.3 |
| Per-run data work | `Σ_s C_s,run` bytes written; unchanged files are links (no data) | §8 |
| Wall time | `Σ_s T_s / J` for balanced sources, `T_s = c_scan·F_s + c_copy·F_s + C_s,run/R + index(F_s)`; grows linearly with files and copied bytes, not with `N` beyond `N·c_src`, not with snapshot history | §12 |
| Memory per worker | `≤ 0.5 KiB · F_s + 4 MiB`; measured 3.8 MiB dict for 20k entries (199 B/file) + 2.6 MB index JSON (129 B/file) | tracemalloc / JSON size |
| Memory total | `≤ J · (0.5 KiB · max_s F_s + 4 MiB) + O(N)`; flat in `K` (only one prior index is loaded) and flat in total file count when sources are processed sequentially (`J=1`) | design: no all-source manifest |
| Disk data | `≤ Σ_s Σ_{retained i} C_s,i` plus transient staging/trash; unchanged files add 0 data blocks because of hardlinks | hardlink model |
| Disk metadata | `≤ Σ_s (K_s+1+L_s)·F_s⁺·m`, where `F_s⁺ = max(F_s, largest retained snapshot's file count)`, measured `m ≈ 130 B/file` for the JSON index (conservative bound 0.5 KiB/file incl. directory entries); retained snapshots per source `≤ K_s+1+L_s`, where `L_s` is the number of concurrently leased snapshots (`L_s = 0` with no active restore) | §4.6, §9 |
| Inodes created per snapshot | changed/new files, symlinks, and directories; an unchanged file adds a directory entry (link), not an inode | hardlink model |
| Per-run work vs. snapshot count | `O(Σ_s (F_s·(1+V_s) + K_s))`, where `V_s` is the number of newer corrupt indexes inspected before a valid baseline (normally 0): one baseline index read + `list_snapshots`; only corruption forces walking back | §4 step 3, §7.2 |
| Open file descriptors | `O(J)` + transient per-file `O(1)` | pipeline |
| Lock files | `2N` source locks plus one `lease` per retained snapshot (same bound as disk metadata); only `O(1)` locks are held per active source/reader | §6, §9 |
| Work vs. `N` at fixed total `F,B` | additive `N·0.13 ms` for lock/list overhead plus one index read per source; no quadratic term | §12 |

"Flat" claims are therefore: memory is flat in `K` and (for `J=1`) in the
number of sources; per-run work is flat in the number of retained snapshots,
apart from `O(K_s)` name listing and the `V_s` corrupt-index walk; per-snapshot
physical byte growth is zero for unchanged files. Disk is the only quantity
that accumulates with history, and it is bounded by the formula above, not
merely "bounded". Two explicit exceptions are stated rather than hidden:
snapshots actively leased (`L_s`, bounded by the number of concurrent
restores) and runs that complete while a prune is deferred by a stopped
lister; both delay the reduction and add at most one snapshot per completed
run during the delay.

---

## 12. Performance budget for the initial full backup

Target: one source, `F = 20,000`, `B = 1.0 GiB`, local APFS SSD, warm cache,
Python 3.10.11 on this machine. Initial backup means no baseline and no
hardlinks: everything is copied.

Measured with a prototype that implements the §4 cost path (lstat scan, 1 MiB
chunked copy, post-copy verification, canonical index write + fsync; no
symlinks and no hashing, so the figures are a slight underestimate of the
real phase costs and the budget carries margin for them):

| Phase | Wall time | Per file | Notes |
|---|---:|---:|---|
| scan + `lstat` (20k files) | 0.496 s | 24.8 µs | `os.walk`, `st_mtime_ns`/`st_ctime_ns` |
| copy (1 MiB chunks, dirs created) | 5.118 s | 256 µs | 200 MiB/s for 50 KiB files |
| post-copy verify (`lstat`, size) | 0.393 s | 19.7 µs | existence + expected size |
| index JSON + fsync | 0.041 s | — | 2.6 MB canonical JSON in the 5-field prototype; production adds `dev`/`complete`, ≈3 MB, so the phase stays ~50 ms |
| **total** | **6.047 s** | **302 µs** | **≈169 MiB/s end-to-end** |

Data-point separating per-file overhead from byte throughput: four 256 MiB
files (1.07 GiB total) copied in 0.45 s (≈2.4 GiB/s) with the same 1 MiB
chunk loop; the existing read-whole-file `synccli.copy_file` took 0.47 s on
the cached files but would allocate the entire file in RAM. On the 20k-file
tree, `synccli.copy_file` measured 5.18 s and `synccli.build_manifest` (via
`scan_files` + `file_state`) 0.58 s, so the chunked design is not paying a
measurable speed penalty for its bounded memory. Small-file cost is dominated
by per-file metadata, not bandwidth.

Derivation for the budget. Copy time separates per-file overhead from byte
throughput: the measured 256 µs/file for 50 KiB files includes about 20 µs of
data time at the measured 2.4 GiB/s, leaving ≈236 µs/file of open/write/
directory cost; use a conservative 0.20 ms/file.

```
T_full(F, B) ≈ F·(25 µs scan + 20 µs verify + 2 µs index)   # metadata
              + F·0.20 ms                                  # per-file copy cost
              + B / (1.5 GiB/s)                            # conservative vs 2.4 measured
              + 0.1 s index serialize/fsync + margins
```

For `F=20,000`, `B=1 GiB` this gives `0.94 s + 4.00 s + 0.67 s + 0.1 s ≈
5.7 s`, consistent with the 6.047 s measurement and slightly conservative.
The same formula applied to four 256 MiB files gives ≈0.82 s vs 0.45 s
measured, i.e. it does not understate. The budget, not a guess:

- **p50 ≤ 10 s, p95 ≤ 20 s, hard target ≤ 30 s** for 1 GiB / 20k files on
  local APFS SSD, warm cache, default options. The p50 figure is the 20k-file
  target; at the top of "tens of thousands" (100k files, 1 GiB) the same
  formula gives ≈25.5 s (`100k·247 µs + 0.67 s + 0.1 s`), inside the hard
  target on this host because copying the same bytes in smaller files is
  metadata-bound, not bandwidth-bound.
- Excludes source cold-cache/network/HDD: add `B / R_device` once (e.g.
  1 GiB at 500 MiB/s ≈ +2 s; a 100 MiB/s HDD ≈ +10 s), and excludes optional
  `--hash` (SHA-256 measured 0.46 s for 1 GiB at 2.2 GiB/s) and
  `--durability=power` data fsync.
- It scales by substituting the measured constants: a 2 GiB / 40k-file tree
  gives `1.88 s + 8.00 s + 1.33 s + 0.1 s ≈ 11.3 s` by the formula (linear
  scaling; still inside the same budget shape), and a tree of the same bytes
  in fewer, larger files is faster.

Incremental no-op measurement (for context, not the budget): scan 0.494 s +
`changed_files` 0.001 s + link phase 6.72–8.40 s for 20k links (2.4–3.0k
links/s) + 0.4 s for the pre-link re-`lstat` pass ≈ 7.6–9.3 s, writing ~0 data
bytes. Linking is slower per file than copying a 50 KiB file on APFS, but it
saves 1 GiB of writes and is bounded; directory creation is hoisted out of the
per-file loop in the implementation (the 6.72 s figure) to keep it at the low
end.

---

## 13. Security and robustness details

- **Path containment**: all index keys are validated on write and on read;
  `resolve_member()` uses `realpath` + `commonpath` against
  `<source>/<snap>/data` and rejects escapes. This fixes the verified absolute
  path and `..` escapes in `snaputil.safe_snapshot_path`.
- **Symlinks**: stored as symlinks with their target string; never followed
  during scan or restore. A symlink whose target is absolute or points outside
  is still stored as a symlink (restoring it recreates the link, not the
  target's content), which cannot read outside the snapshot. Copies open
  regular files with `O_NOFOLLOW` after the `lstat`, so a path swapped to a
  symlink between scan and copy is reported (`changed_type`/`unreadable`),
  not silently followed outside the source.
- **Backup root / source overlap**: at config load, reject a source that
  contains the backup root or is contained by it, using `realpath` +
  `commonpath`. Otherwise scanning would ingest a growing tree of snapshots.
- **Read-only snapshots**: stored files are chmod `0444`, directories `0555`
  (applied after the index is written, before publish); the `.backupctl/lease`
  file is the one exception, kept `0644`. Original modes are recorded in the
  index and restored by the restore tool. This prevents
  accidental in-place edits to a hardlinked inode, which would otherwise
  mutate every snapshot sharing it. Retention's `remove_tree()` explicitly
  restores directory write permission before deletion (§9). Ownership/xattrs/
  ACLs are explicitly out of scope.
- **No source hardlinks**: only prior-snapshot inodes are linked into a new
  snapshot, so source writes cannot affect published data.
- **Unreadable directories**: recorded as `problems` and the walk continues;
  the snapshot may be partial, but the index still matches the tree exactly.
- **Disk-full**: a write error aborts the source's snapshot (staging deleted,
  nothing published), releases the lock, and exits 1; previously published
  snapshots are untouched.

---

## 14. Validation plan

Unit / integration (new `test_backupctl.py`, alongside the existing suite):

1. Reuse checks: `changed_files` returns the same set for our richer state
   objects; `list_snapshots` names are re-filtered correctly.
2. Initial backup publishes one valid snapshot; index entries all exist;
   second run links unchanged files (inode equality inside the backup root,
   different inode from source) and copies changed ones.
3. Crash injection: kill the process after each pipeline step (scan, mid-copy,
   after index temp, after index rename, before publish rename); assert no
   `snap-…` appears, the next run cleans staging, and the report says so.
4. Concurrency: two processes on one source (second reports busy or waits);
   two on different sources run in parallel; a holder of `read-lease` on
   snapshot `S` while a prune runs causes `S` to appear in `prune_skipped`,
   other snapshots to be pruned, and the reader to complete unharmed.
5. Vanished/unreadable/unstable: delete a file between scan and copy, chmod
   one unreadable, modify one during copy; snapshot publishes with the file
   absent and `problems` populated, exit 3, identical output for both
   invocation paths.
6. Corrupt index: truncate/garble the newest index; next run reports
   `index_recovery`, uses the older baseline (or full copy), publishes a new
   valid snapshot, and does not modify the corrupt one.
7. Retention: `keep=1`, newest partial + older clean retains both; a leased
   snapshot is reported in `prune_skipped` while unleased older ones are
   removed; crash after rename leaves trash and next run removes it; `keep=0`
   clamps to 1.
8. Path safety: index with `../x` and `/etc/passwd` is rejected; a symlink in
   a snapshot is not followed during verify/restore.
9. Existing `python3 -m unittest` remains green (6/6).

The performance claims can be reproduced with a script that creates 20,000
50 KiB files, runs the §4 prototype, and reports the phase table in §12.

---

## 15. Trade-offs and alternatives considered

- **One table of all sources vs. one chain per source.** A single global
  snapshot would make cross-source restore atomic, but it also makes every
  run global-lock-bound and makes a vanished file in one source interfere
  with all others. Per-source chains scale with `N`, let different sources run
  in parallel, and match `snaputil`'s per-root model. Chosen: per source.
- **Content-addressed store instead of snapshot trees.** Better dedupe across
  sources and no hardlink cost, but restore and `snaputil`'s path helpers
  expect a tree; it also adds garbage collection complexity. Chosen:
  hardlinked trees, with cross-source dedupe explicitly out of scope.
- **Block-level deltas (rsync-like).** Detects sub-file changes but requires
  a delta format, a reconstructor, and a much larger trust surface. The evals
  workflow's files change wholesale; per-file granularity with the stated
  blind spots is the simpler correct choice.
- **Deleting with a grace period for uncooperative readers.** A time window
  cannot bound retention without also bounding run frequency; the per-snapshot
  reader lease is exact and cheap. Chosen: per-snapshot lease +
  `prune_skipped` (and `prune_deferred` only for the short listing section).
- **Global root lock for both publication and reads.** Simpler, but a restore
  would block publication of every source, and all sources would serialize.
  Chosen: per-source locks, with publication needing no reader lock at all
  because the rename is atomic and snapshots are immutable.

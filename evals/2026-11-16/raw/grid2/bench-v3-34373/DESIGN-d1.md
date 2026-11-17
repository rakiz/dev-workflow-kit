# DESIGN-d1 — `backupctl`

Status: design for the fixture in this directory. No network, no third-party
dependencies: `backupctl` is stdlib-only Python, like `synccli.py` and
`snaputil.py`, and ships alongside them as `backupctl.py` + `test_backupctl.py`.

Everything below is grounded in this directory's code. Where the design must
differ from existing behavior, the override is named by function and line
number and the reason is stated. Measurements quoted here were produced by
running the existing code in this directory (commands and output in
Appendix A); `python3 -m unittest` currently passes all 6 tests.

---

## 1. Invariants

These are the properties every mechanism in this document exists to preserve.
They are numbered so the rest of the design can refer to them.

- **I1 — A visible snapshot is complete.** A directory whose name matches
  `snap-*` directly under the backup root exists only after every file and the
  index in it have been written, verified, and flushed. There is no "in
  progress" state that a reader can observe under a `snap-*` name.
- **I2 — The index promises only what is present.** Every entry in a
  snapshot's index names a file that exists in that snapshot with the recorded
  type and size. There are no entries for files that were skipped.
- **I3 — Published snapshots are immutable.** No `backupctl` code path writes
  to a file or directory inside an existing `snap-*` tree (hardlinks make this
  a shared-inode contract; see §9.4).
- **I4 — One writer per backup root.** At most one `backupctl run` mutates a
  backup root at a time. Readers never mutate.
- **I5 — Retention never removes the last usable snapshot.** The newest valid
  snapshot is never deleted, and at least `keep` (minimum 1) valid snapshots
  remain after pruning.
- **I6 — Source races are data facts, not corruption.** A file that vanishes,
  is unreadable, or changes during a run is either present with verified
  contents in the new snapshot or recorded as omitted in the run report; it is
  never half-present or promised-but-absent.
- **I7 — All snapshot-relative paths are contained.** No path read from an
  index or manifest can address anything outside its snapshot directory.

---

## 2. What actually exists here (verified, not assumed)

### 2.1 `synccli.py`

- `scan_files(root)` (lines 10–19) walks with `os.walk`, **excludes
  dot-directories** (`dirnames[:] = [d for d in dirnames if not
  d.startswith(".")]`, line 14), and returns a sorted list of relative paths.
- `file_state(path)` (lines 22–25) returns only `{"size": st_size, "mtime":
  st_mtime}` — a float mtime, no inode, no ctime, no mode.
- `build_manifest(root)` (lines 28–33) stats every file from `scan_files` into
  `{relpath: state}`.
- `changed_files(old, new)` (lines 36–42) returns entries that are new or whose
  `{size, mtime}` differs. It **cannot report deletions**: a file present in
  `old` and absent from `new` is simply never visited.
- `collect_stale(items, seen=None)` (lines 45–59) returns paths that are not
  `seen` and not `fresh`. Its tests (`test_synccli.py` lines 21–33) pin the
  important edge: the first stale item is included.
- `copy_file(src, dst)` (lines 62–69) reads the **whole file into memory**
  (`fdst.write(fsrc.read())`, lines 66–67) and **swallows `OSError`** (lines
  68–69). `sync()` (lines 72–87) then writes the manifest for **all scanned
  source files** (lines 85–86), not just successful copies.

I ran the unreadable-file case to confirm the consequence. A file with mode
`000` is stat-able (so it enters the manifest) but not openable:

```
copied: ['secret.txt']
manifest promises: ['secret.txt']
snapshot file present: False
```

`sync()` reports the file as copied and the manifest promises a file that does
not exist. That is exactly the failure I2 forbids; `backupctl` overrides
`copy_file`/`sync` for this reason (§7, §15).

Also confirmed: after deleting a source file and re-syncing, the destination
still contains the stale file (`after source deletion -> dst has stale a: True
b: True`). A snapshot cannot rely on `changed_files` for deletion.

### 2.2 `snaputil.py`

- `list_snapshots(root)` (lines 8–20) returns `sorted()` names that
  `startswith("snap-")` and are directories (line 18). `entry.is_dir()` follows
  symlinks by default. Verified: a symlink named `snap-20990101-000000-00`
  appears in the listing.
- `prune_snapshots(root, keep)` (lines 23–36) selects oldest-first and
  `shutil.rmtree`s them **directly** (lines 33–35), with no validity check, no
  reader check, and no age guard.
- `snapshot_disk_usage(root, name)` (lines 39–51) sums `st_size` over every
  path from `os.walk` using `os.stat` (line 50). Verified double-counting of a
  hardlink pair: two names → one 1000-byte inode reports `2000`, actual unique
  bytes `1000`. It also follows symlinks via `os.stat`.
- `safe_snapshot_path(root, name, rel)` (lines 54–63) is **broken**:
  `os.path.normpath` does not remove leading `..`, and `os.path.join` with an
  absolute `rel` discards the prefix. Verified outputs:

  ```
  '../../escape.txt' -> <root>/snap-x/../../escape.txt
  '/etc/passwd'      -> /etc/passwd
  'a/../../../b'     -> <root>/snap-x/../../b
  ```

  The docstring's guarantee ("never points outside …") is false. `backupctl`
  overrides this function (§11).
- `is_stale(snapshot_dir, ref_epoch)` (lines 66–73) compares the directory
  mtime with a reference epoch. Directory mtime changes whenever a child is
  added/removed; it is not a completeness signal. `backupctl` does not use it
  for validity (§15).

### 2.3 Tests

`test_synccli.py` exercises `scan_files` (lines 17–18), `collect_stale`
(21–33), and `sync` (42–51). They pass. They are the behavioral baseline this
design reuses, except where §15 names an override.

---

## 3. Architecture and on-disk layout

One `backupctl run` produces **one snapshot containing every configured
source** at a single run boundary. This matches `prune_snapshots`' global
"keep newest K under this root" policy and gives a consistent point across
sources.

```
<backup_root>/
  .backupctl/                     control plane; never a snapshot
    run.lock                      flock for I4
    seq                           monotonic run counter (reserved before publish)
    locks/<snap-name>.lock        per-snapshot reader/writer flocks
    reports/<seq>-<runid>.json    machine-readable run report (atomic write)
  snap-20261112-150000-000007/    published snapshot (complete by I1)
    evals/                        source "evals" tree (files/dirs/symlinks)
    results/                      source "results" tree
    .backupctl/
      index/evals.json            per-source index (entries = present files)
      index/results.json
      COMMIT.json                 completion record + per-index sha256 + counts
  .backupctl-staging-<runid>/     in-flight; never matches "snap-"; GC'd on crash
  .backupctl-trash-<name>-<ts>/   already-retired; GC'd on crash
  .backupctl-quarantine-<name>-<ts>/  unreadable published tree; kept, reported
```

Why the staging name starts with `.backupctl-`: `list_snapshots` only accepts
names starting `snap-` (line 18), so staging/trash/quarantine are invisible to
it. Staging is created **under the backup root**, guaranteeing the final
`os.rename` is same-filesystem and therefore atomic (a staging dir in `/tmp`
would break this).

A source id is a directory name at the top of the snapshot. Ids are validated
(`[A-Za-z0-9._-]+`, not `.backupctl`, not starting `snap-`, unique). Source
trees are rejected if they are nested/overlapping or if the backup root lies
inside a source (otherwise a run would back up snapshots into themselves).

Snapshot names are `snap-<UTC YYYYmmdd>-<UTC HHMMSS>-<seq:06d>`, matching
`snaputil.list_snapshots`' documented "date, time, run sequence" shape (lines
12–14). The `seq` is a monotonic counter persisted in `.backupctl/seq` and
reserved **before** staging is created (gaps after a crash are fine, reuse is
not). Retention orders by `seq`, not by lexicographic name, so a backward
clock step cannot make a new snapshot look old (§10). Names are still
zero-padded and sort correctly in normal operation for `list_snapshots`.

### 3.1 Per-source index

```json
{
  "format": 1,
  "source_id": "evals",
  "source_path": "/repo/evals",
  "scan_started": "2026-11-12T15:00:00Z",
  "scan_finished": "2026-11-12T15:00:01Z",
  "entries": {
    "run-7/a.json": {
      "type": "file",
      "size": 12345,
      "mtime_ns": 1762959600123456789,
      "ctime_ns": 1762959600123456789,
      "ino": 88123,
      "dev": 16777220,
      "mode": 420,
      "sha256": null,
      "status": "ok",
      "linked_from": "snap-20261112-140000-000006"
    }
  }
}
```

`mtime_ns`/`ctime_ns`/`ino`/`dev` describe the **source file at capture
time** (the identity change detection compares against next run), not the
snapshot copy's inode. Entries exist only for files successfully materialized
and verified (I2). `linked_from` records reuse via hardlink; `sha256` is
present only with `--verify-hash` or `verify_hash: true` in config.

### 3.2 `COMMIT.json`

```json
{
  "format": 1,
  "snapshot": "snap-20261112-150000-000007",
  "seq": 7,
  "run_id": "<uuid>",
  "created_at": "2026-11-12T15:00:03Z",
  "sources": {
    "evals": {"index_sha256": "...", "files": 41230, "bytes": 812345678,
              "omitted_missing": 2, "omitted_unreadable": 0, "unstable": 1}
  },
  "totals": {"files": 61230, "bytes": 1012345678, "linked": 60110}
}
```

`COMMIT.json` is written last inside staging, after its index hashes are
computed. It is the completeness and integrity record: a published snapshot is
valid iff `COMMIT.json` parses, each per-source index matches its recorded
sha256, and a publish-time check found every entry present with the recorded
type/size. A final-named directory without a valid `COMMIT.json` is not a
usable snapshot (§6).

---

## 4. Configuration

```json
{
  "backup_root": "/Volumes/backups/evals",
  "sources": [
    {"id": "evals",   "path": "/repo/evals"},
    {"id": "results", "path": "/repo/results"}
  ],
  "retention": {"keep": 7, "min_age_seconds": 3600},
  "verify_hash": false,
  "include_hidden": true
}
```

Defaults: `keep=7` (clamped to ≥1), `min_age_seconds=3600`, `verify_hash=false`,
`include_hidden=true`. Validation errors exit 2 and write nothing.

---

## 5. Run protocol

All steps after the run lock are performed by one process; no threads.

1. **Load and validate config** (§4): absolute paths, sources exist and are
   directories, ids valid/unique, no source nesting, backup root real path not
   equal to/inside a source real path. Create `.backupctl/`,
   `.backupctl/locks/`, `.backupctl/reports/` if missing.
2. **Acquire the run lock** `flock(.backupctl/run.lock, LOCK_EX|LOCK_NB)`. On
   `EWOULDBLOCK`, emit the "busy" report and exit 75. The lock is on an open
   file descriptor; if the process dies, the kernel releases it, so a crashed
   run never leaves a stale lock (I4).
3. **Recover under the lock** (§6): delete staging/trash dirs, quarantine
   invalid `snap-*` dirs, re-derive a damaged index where the tree is
   trustworthy. Record every action for the report.
4. **Select the baseline**: the valid snapshot with the greatest `seq`
   (excluding quarantined ones). Take `LOCK_SH` on
   `.backupctl/locks/<baseline>.lock` and hold it until retention finishes.
   Load its per-source index one source at a time (never all at once, §13).
5. **Reserve a sequence number**: read `.backupctl/seq`, +1, write it back
   atomically (`tmp`+`fsync`+`rename`) before doing the run, so a crash cannot
   cause a future run to reuse a name.
6. **Create staging** `.backupctl-staging-<runid>` with `os.mkdir` (fails if it
   exists), then fsync the backup root directory.
7. **Per source, sequentially**:
   a. **Scan**: `synccli.scan_files` (lines 10–19) for the listing, with the
      dot-directory exclusion at line 14 overridden when
      `include_hidden=true`. For each path take `os.lstat` (not `os.stat`) and
      build the current identity tuple `(dev, ino, size, mtime_ns, ctime_ns,
      mode)`; symlinks and special files are recorded as their own entry types
      and never followed.
   b. **Change set**: `changed = synccli.changed_files(baseline_index,
      current_index)` (lines 36–42) for new/changed paths, plus `deleted =
      set(baseline) - set(current)` computed here because `changed_files`
      cannot report deletions (lines 39–42 iterate only over `new`).
   c. **Unchanged files**: a path is unchanged iff its tuple equals the
      baseline entry's tuple **and** the baseline snapshot file exists (lstat
      type/size match). Unchanged files are materialized with `os.link(baseline
      path, staging path)` (never `os.link(live_source, staging)`, §9.4). On
      `ENOENT`/`EXDEV`/`EPERM`/`EMLINK`, fall back to a copy from the source
      and record the fallback.
   d. **Changed/new files**: copy from the source via the override in §7
      (streaming, temp file, fstat before/after, retry, preserve
      `mtime_ns`/mode, propagate errors). Files that vanish or are unreadable
      are omitted and reported (I6).
   e. **Write the per-source index** to
      `staging/.backupctl/index/<id>.json` via `json.dump` to a temp file,
      `flush`+`fsync`, then `os.rename` to the final name inside staging.
8. **Publish validation**: for every index entry, `os.lstat` the staged path
   and require matching type and size (I2). Compute each index file's sha256
   and write `COMMIT.json` (temp + fsync + rename). Fsync the index dir and
   `.backupctl` dir.
9. **Publish**: `os.rename(staging, snap-…)` (same filesystem, atomic), then
   fsync the backup root. If the name unexpectedly exists, bump `seq` and
   retry. From this instant the snapshot is visible and complete (I1); there
   is no flag a reader must check.
10. **Retention** (§10) while still holding the baseline shared lock; the
    baseline is therefore never a deletion candidate.
11. **Report** (§12): write `.backupctl/reports/<seq>-<runid>.json` atomically,
    print the human or `--json` summary, release locks, exit.

Crash at any point before step 9 leaves no `snap-*`; step 3 of the next run
removes the staging dir. Crash between 9 and 10 leaves a complete snapshot
(retention is idempotent and simply runs again next time). `SIGINT` is caught:
the handler removes staging best-effort, reports `aborted`, exits 130; no final
name is ever created. `SIGKILL` cannot be caught; it is covered by step 3.

---

## 6. Crash recovery, corrupt indexes

Under the run lock, before the new run does any work:

| Leftover | Action | Reported |
|---|---|---|
| `.backupctl-staging-*` | `rmtree` (incomplete, unusable; I1) | count, bytes freed |
| `.backupctl-trash-*` | `rmtree` (already retired) | count, bytes freed |
| `snap-*` with missing/unparseable `COMMIT.json` | rename to `.backupctl-quarantine-<name>-<ts>`; not usable, data kept | name, reason |
| `snap-*` whose index sha mismatches `COMMIT`, tree consistent | **re-derive** that index by walking the source tree under the snapshot | entries, what was lost (§6.1) |
| `snap-*` whose tree disagrees with `COMMIT` (missing file, size mismatch) | quarantine whole snapshot; fall back to next older valid baseline | name, first mismatches |
| no valid snapshot at all | baseline is empty; this run is a full copy | "no usable baseline" |

### 6.1 What re-derivation discards and re-derives

Re-derivation is allowed only when `COMMIT.json` parses and every index file
either matches its sha or is individually unparseable, **and** the tree under
the snapshot is intact (every file is a regular file/symlink, no size
contradictions). Then the damaged index is **discarded** and rebuilt by walking
the snapshot tree: `type`, `size`, `mtime_ns` (preserved at copy time via
`os.utime`, §7), `mode`, `ino`/`dev` of the snapshot file, `sha256: null`,
`linked_from: null`.

The rebuilt index has no source identity (`ino`/`dev` of the live source at
capture) and no hashes. Its entries are marked `identity: "stat-only"`;
change detection against such a baseline compares `(size, mtime_ns, mode)`
only. Consequences are reported explicitly:

```
recovered index for snap-.../evals: 41230 entries re-derived from tree;
source inode identity and content hashes unavailable; next run for this
source uses (size, mtime_ns, mode) change detection (may re-copy files
whose content changed without changing size or mtime).
```

If any file is missing or a size disagrees with `COMMIT`, re-derivation is
refused: the snapshot is quarantined and the baseline falls back. Nothing is
ever published from a repaired index without recomputing its sha and writing a
new `COMMIT.json` atomically inside the (still read-only to others under I4)
snapshot.

Note the protocol's own guarantee: a run under this design **cannot** leave a
half-written index behind a `snap-*` name, because index and `COMMIT` are
written and flushed inside staging and the only name-giving operation is the
final rename. The re-derivation path exists for externally damaged snapshots
(disk corruption, an older tool, manual edits) and is specified because the
brief asks what happens to "a corrupt or half-written index left behind."

---

## 7. Copy path and source races

### 7.1 Override of `synccli.copy_file` (lines 62–69)

Reasons: it buffers the whole file in memory (line 66–67, memory grows with the
largest file), silently drops `OSError` (68–69), and leaves a truncated/empty
destination when a read fails after the destination is opened. `backupctl` uses
`copy_one(src, dst_staging, identity_before)`:

1. `os.open(src, O_RDONLY)`; `fstat` → `before`.
2. Create `<dst>.part-<pid>` in staging; stream 1 MiB chunks (constant 1 MiB
   buffer, §13), hashing as it goes only when hashes are enabled.
3. `flush`; fsync the payload **only** when power-loss durability is requested
   (`durability: fsync`); process death does not require it because the page
   cache survives (§14 shows both budgets).
4. `fstat` the source again → `after`. If `(dev, ino, size, mtime_ns,
   ctime_ns)` differ from `before`, the file changed while being read: delete
   the temp, retry up to 2 times. If it is still changing, rename the temp into
   place anyway, mark the index entry `"status": "unstable"` with both tuples,
   and report it. The snapshot stays self-consistent (the file present is
   exactly the bytes written, and its size matches the index); it is a torn
   **read of one file**, never a mix of two runs.
5. Require the number of bytes written to equal `before.size`; otherwise treat
   as unreadable.
6. Preserve `mtime_ns` (`os.utime(dst, ns=(atime_ns, mtime_ns))`) and `mode`
   (`os.chmod`). `os.rename(temp, final)` inside staging.

Errors are classified at the caller, not swallowed:

| `errno` / condition | Classification | Snapshot content | Report |
|---|---|---|---|
| `ENOENT` (between scan and open, or during read) | `missing` | file absent, no index entry | count + up to 100 paths |
| `EACCES`/`EPERM`/`EIO`/`EISDIR` | `unreadable` | file absent, no index entry | count + up to 100 paths |
| identity changed after retries | `unstable` | file present, entry flagged | count + paths |
| source replaced by another type | `type_changed` | absent (or new type copied next run) | count |

All of these are **warnings on a successful run**, exit 0: the snapshot is a
complete image of everything readable at its scan window, and nothing in it is
promised but absent (I2, I6). The same code path, report, and exit code are
used whether the run was started by the scheduler or by a person; nothing
inspects a TTY or prompts (§12).

### 7.2 Point-in-time boundary

The capture window for a source is from the start of its `scan_files` walk to
the end of its last copy (recorded in the index). Files created after the walk
are not in this snapshot; files deleted after the walk are omitted and
reported. This is the honest definition of the snapshot's instant, stated in
the report.

---

## 8. Change detection: granularity and what it can miss

Identity per path is `(st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns,
st_mode)` from `os.lstat`, compared against the baseline entry's **source**
tuple. Unchanged files are hardlinked from the baseline snapshot instead of
re-read.

This overrides `synccli.file_state` (lines 22–25) for two concrete reasons:

- `st_mtime` is a float (microsecond-ish and lossy); the design uses
  `st_mtime_ns`.
- the existing tuple has no inode/ctime, so a file replaced by another file of
  the same size and mtime is invisible, and an in-place edit with the mtime
  restored (`touch -r`) is invisible. Adding `st_ino`/`st_dev` catches
  atomic-replace editors, and adding `st_ctime_ns` catches `touch -r`-style
  edits because `ctime` cannot be set from user space.

What the granularity can still miss — stated, not hidden:

1. **Sub-tick content change on coarse-timestamp filesystems.** On a
   filesystem with 1 s (HFS+) or 2 s (FAT) timestamp granularity, two edits of
   the same size within one tick can have identical `size`/`mtime_ns`/
   `ctime_ns`/`ino`. APFS and ext4 with nanosecond timestamps make this
   negligible but not impossible.
2. **Raw/instrumented writes that restore both mtime and ctime** (e.g. writing
   through a block-device image, or filesystem snapshot tricks). Ordinary
   user-space writes always advance `ctime`.
3. **Metadata-only changes to owner, group, xattrs, ACLs.** `mode` is in the
   tuple and preserved; owner/group/xattrs are not preserved or compared.
4. **A pre-existing baseline recovered via §6.1**, which is stat-only
   (`size`, `mtime_ns`, `mode`): content changes that keep size and mtime can
   be missed until a full/hash run.

`--verify-hash` (or `verify_hash: true`) closes gap 1–2 and strengthens 4 by
reading every file and storing SHA-256; cost is `B / 2152 MiB/s` for bytes plus
one read per file (measured hashing throughput in Appendix A). Without it,
detection is metadata-only, which is a deliberate cost/coverage trade stated in
the run report (`"detector": "stat" | "stat+sha256"`).

Renames appear as delete+new and are re-copied; `ctime`/`ino` are preserved in
the index, so an optional optimization can match by inode and link the old path
instead of copying, without changing correctness. It is not required for the
correctness claims here.

---

## 9. Concurrency

### 9.1 Lock inventory

| Operation | `.backupctl/run.lock` | `.backupctl/locks/<snap>.lock` |
|---|---|---|
| `run` | `LOCK_EX` non-blocking, whole run | `LOCK_SH` on baseline for steps 4–10 |
| `restore` | not taken | `LOCK_SH` on the source snapshot for the whole restore |
| `verify` | not taken | `LOCK_SH` on the snapshot |
| `list` | not taken | not taken (tolerates `ENOENT` mid-scan) |
| retention (inside a run) | already held `EX` | `LOCK_EX\|NB` per doomed snapshot; failure ⇒ skip |

Acquisition order is fixed (run lock first, then snapshot locks in ascending
`seq`) to make deadlock impossible. `flock` locks are released by the kernel on
process death, so there is no stale-lock recovery. Lock files are never used as
ownership tokens; existence means nothing, the held lock does.

### 9.2 Two runs collide

The second `flock(... EX|NB)` fails with `EWOULDBLOCK`; it writes nothing,
reports `{"status":"busy","held_by":<pid if readable>}`, and exits 75
(`EX_TEMPFAIL`, the standard scheduler-retry signal). No interleaving is
possible, so no snapshot or index can be corrupted (I4).

### 9.3 Restore while a run writes

A restore reads only `snap-*` trees, which are immutable (I3). The run writes
only inside its staging directory and then atomically renames a new
`snap-*` into place, so the restore's snapshot is untouched. If the run is also
pruning and the restore holds the snapshot's shared lock, the prune's
`LOCK_EX|NB` fails and that snapshot is skipped and reported. If the restore is
external tooling that does not take the lock, §10.3's rename-first deletion
still guarantees the restore never observes a partially deleted tree under the
original name.

### 9.4 Hardlinks and immutability

A new snapshot's unchanged files are hardlinks **to the baseline snapshot's
files**, never to live source paths. Live sources are mutable; linking them
would let the next source edit rewrite history. Consequence: all snapshots
sharing an inode share its content and mode. `backupctl` never writes inside a
snapshot, and `restore` copies **out** of a snapshot, never into it. If an
external process edits a file through a snapshot path, every snapshot sharing
that inode changes; this is outside the tool's contract, and the mitigation is
`--verify-hash` stored hashes plus `backupctl verify`, which detects content
divergence. This is the explicit cost of hardlink dedup; the alternative
(full copy per snapshot) was rejected because disk becomes `keep × tree` for
every version (see §13.3).

---

## 10. Retention and safe deletion

### 10.1 Policy

Keep the newest `keep` **valid** snapshots (`keep ≥ 1`, default 7) and never
delete a snapshot younger than `min_age_seconds` (default 3600). Invalid
snapshots are not candidates (they are quarantined, §6); they never count as
usable, and deleting is never the response to corruption.

### 10.2 Reuse and override of `prune_snapshots` (lines 23–36)

The ordering and "oldest first, newest never deleted" policy (lines 30–33) is
reused. The deletion loop (lines 33–35) is overridden: it calls `rmtree`
directly, with no validity, reader, or age guard. `backupctl` computes doomed
candidates itself (ordered by `seq`, not name), then for each candidate:

1. Skip unless it is a valid snapshot (§5 step 8 validity, including the
   `COMMIT.json`/index sha check).
2. Skip if it is the newest by `seq`, if deleting it would leave fewer than
   `keep` valid snapshots, or if it is the current baseline.
3. Skip if `now - created_at < min_age_seconds` (protects a restore that just
   started without locking).
4. Try `LOCK_EX|NB` on its lock file; if busy, skip and report
   `"skipped":"reader"`.
5. `os.rename` the snapshot to `.backupctl-trash-<name>-<ts>` — atomic, so the
   `snap-*` name disappears as a whole and no reader can ever see a
   half-deleted tree under it. Then fsync the root and `rmtree` the trash.
   A crash between rename and rmtree is cleaned by the next run (§6).

Hardlink counts make deletion safe: retiring an old snapshot just drops its
links; newer snapshots keep their data. No snapshot is ever a required parent.

### 10.3 Readers that do not lock

The published/immutable/rename-first rules give the following guarantee even
for foreign restore tooling: a reader that resolves
`<root>/snap-…/path` either sees the complete snapshot or gets `ENOENT` after
the name was atomically removed; it never sees a partially deleted tree under
the snapshot name. A reader that already has file descriptors open keeps those
inodes alive after deletion (POSIX link semantics). The remaining caveat is
explicit: a path-by-path foreign reader that runs longer than
`min_age_seconds`, without the shared lock, can get `ENOENT` partway through;
it should re-list and retry. Our `restore`/`verify` take the shared lock and do
not have this caveat.

---

## 11. Path safety (override of `safe_snapshot_path`, lines 54–63)

The existing function is unsafe as shown in §2.2. `backupctl` defines
`contained_path(snapshot_dir, rel)` and uses it everywhere an index path is
turned into a filesystem path:

```
reject if rel is empty, absolute, contains NUL, or has any component in
  ("..", ".") after splitting on "/" and os.sep
joined = os.path.join(snapshot_dir, rel)
base   = os.path.realpath(snapshot_dir)
real   = os.path.realpath(joined)
require os.path.commonpath([base, real]) == base
```

In addition, restore opens snapshot files with `os.open(..., O_NOFOLLOW)` and
`lstat`s each component, so a symlink inside a snapshot cannot be traversed to
escape. Symlink entries stored in the index are recreated with
`os.symlink(target, dst)` as data, never followed during scanning or restore.
The `..`/absolute cases from §2.2 are regression tests.

---

## 12. Reporting, exit codes, scheduler vs person

A run always reports the same facts through the same code path; nothing
depends on a terminal. `--json` prints one object to stdout; without it, the
same fields are printed as labeled lines. Every run also writes
`.backupctl/reports/<seq>-<runid>.json` atomically.

Report fields: `run_id`, `seq`, `snapshot` (name or null), `status`
(`ok`|`partial`|`busy`|`aborted`|`error`), `baseline`, `detector`
(`stat`|`stat+sha256`), per-source `{scanned, copied, linked, bytes, omitted:
{missing, unreadable, type_changed}, unstable}`, `recovered` (staging/trash
freed, quarantined, re-derived), `retention {deleted, skipped:[{name,reason}]}`,
`duration_ms`, `warnings`.

`status` is `partial` when the snapshot published but any file was omitted or
unstable — this is success, not failure: the snapshot is complete for what it
contains and the index promises nothing else.

| Exit | Meaning |
|---|---|
| 0 | Snapshot published (possibly with `partial` warnings) |
| 2 | Config/usage error; nothing touched |
| 3 | Verification/restore found index-vs-tree mismatch; nothing restored |
| 75 | Another run holds the run lock; nothing touched; retry later |
| 1 | Fatal error before publish (root unwritable, rename failed); no `snap-*` left |
| 130 | Interrupted (SIGINT); staging removed best-effort; no `snap-*` |

The scheduler and a person get identical exit codes and reports for identical
config; `--strict` is the only behavior switch and is a config/flag decision,
not a TTY decision.

---

## 13. Scaling: what grows with what (explicit bounds)

Let `N` = number of configured sources, `F_i`/`B_i` = files/bytes in source
`i`, `F = ΣF_i`, `B = ΣB_i`, `U` = unchanged files in a run, `C` = changed
files, `S` = snapshots retained. Measured constants are in §14/Appendix A.

### 13.1 Time

```
run_time ≈ Σ_i [ 25 µs·F_i                      # scan: walk + lstat
              + 0.338 ms·U_i                    # hardlinks for unchanged
              + 0.36 ms·C_i + B_c,i/2400MiB/s   # copies (changed bytes)
              ] 
         + 110 B·F /(index write ~2.5 µs/file)
         + 18.6 µs·F                            # publish lstat validation
         + 0.1 s fixed (config, locks, commit, fsync)
         + retention: Σ_doomed 79 µs·F_snap     # 12.6k unlinks/s
```

This is linear in `F` and `B`, never superlinear; there is no `O(N²)` term.
First-run `U=0, C=F`.

### 13.2 Memory

- Peak per run = `max_i(386 B·F_i + 110 B·F_i)` (measured manifest+path-list
  peak 7.4 MiB for 20k files, plus the loaded baseline index ~110 B/file),
  because sources are processed **sequentially** and each baseline index is
  loaded, used, and dropped before the next source.
- Plus `O(N)` for config and `O(S)` for snapshot names (~100 B each), plus a
  constant 1 MiB copy buffer and constant hash state.
- `F_total` does not enter peak memory when the largest source is fixed; `N`
  enters only as `O(N)` config/summary, so peak memory is flat in `N` for a
  fixed largest source.
- `list`/`verify` full-root unique-inode accounting needs `O(unique inodes)`
  entries (16–32 B each); `verify` alone is `O(F_snap)` index entries loaded
  for that one snapshot. Both are stated, not hidden.

### 13.3 Disk

```
physical_bytes ≈ Σ over distinct retained file versions size(version)
               + S · (110 B · F + Σ_i index_i COMMIT overhead)
               + filesystem directory-entry overhead per snapshot per file
```

- Unchanged files add **0 data bytes** per snapshot (hardlink), only the
  index/dir entry (≈110 B index + FS dir entry).
- Worst case (every file changes every run): `keep × B` plus metadata.
  Best case: `B + keep × (110 B·F + dir entries)`.
- Per snapshot the metadata file count is `N` index files + 1 `COMMIT.json`,
  i.e. grows with `N`, not with bytes.
- Retention frees an old snapshot's unique versions only; shared versions stay
  until their last link is gone.

### 13.4 Flat quantities (the numbers)

- Open file descriptors: **≤ 8** at any instant (run lock, baseline lock, one
  source fd, one temp fd, one index temp fd, one index read, one directory fd,
  spare).
- Staging directories: exactly **1** per run (runs serialized).
- Processes/threads: **1**. Copy buffer: **1 MiB** constant.
- Lock acquisitions: **1 run + 1 baseline + ≤ S sequential prune probes**;
  never nested beyond that.
- Peak memory: flat in `N`; grows only with the largest source's file count
  (386 B/file + 110 B/file).
- Per-run work: grows with `F`/`B` and the change volume, never with
  `S` except retention's `Σ_domed F_snap` unlinks.

Concrete examples from the formulas: 20k files/1 GiB first run ≈ 8.6 s
(§14); 200k files, all unchanged, incremental ≈ 77 s (dominated by 0.338
ms/file linking), peak memory ≈ 77 MiB + index ≈ 22 MiB, added data bytes 0.

---

## 14. Performance budget: initial full backup of ~1 GB / tens of thousands of files

Measured on this machine (macOS, APFS, Python 3.10.11), by running this
directory's code (Appendix A).

### 14.1 Measured constants

| Quantity | Measurement | Derived constant |
|---|---|---|
| scan (`build_manifest`: walk + stat) | 20,000 files in 0.505 s | 25.3 µs/file (39.6k files/s) |
| lstat alone | 20,000 in 0.372 s | 18.6 µs/file |
| scandir walk alone | 20,000 in 0.056 s | 2.8 µs/file |
| copy, 20,000 × 50 KiB = 0.95 GiB | 7.59 s | 0.359 ms/file + bytes/2400 MiB/s |
| copy, one 512 MiB file | 0.21 s | 2409 MiB/s (page-cache bound) |
| hardlink, 20,000 files | 6.75 s | 0.338 ms/link (2,963 links/s) |
| rmtree, 20,000 files | 1.58 s | 79 µs/file (12,658 unlinks/s) |
| index JSON, 20,000 entries | 2.1 MiB; dump 0.050 s; load 0.011 s | 110 B/entry; 2.5/0.55 µs/entry |
| manifest memory peak | 7.4 MiB / 20,000 | 386 B/file |
| SHA-256 | 256 MiB in 0.12 s | 2152 MiB/s |
| write+fsync, 1 KiB file | 1,000 files in 0.08 s | 80 µs/file |

### 14.2 Derivation for 1 GiB / 20,000 files

```
scan        = 20,000 × 25.3 µs            = 0.51 s
copy        = 20,000 × 0.359 ms + 1 GiB/2400 MiB/s
            = 7.18 s + 0.43 s             = 7.61 s
publish lstat validation = 20,000 × 18.6 µs = 0.37 s
index write/commit/fsync (small files, index only) ≈ 0.10 s
publish rename = O(1)                     = 0.00 s
--------------------------------------------------
process-death budget (no per-file fsync)  ≈ 8.59 s
per-file fsync for power-loss durability  = +1.60 s
--------------------------------------------------
worst case for power-loss durability      ≈ 10.2 s
```

**Design budget: ≤ 12 s wall for 1 GiB / 20,000 files** on this class of
machine (local APFS SSD), i.e. ≈1.4× the no-fsync measured path and ≈1.18× the
with-fsync path. For 50,000 files / 1 GiB the same formula gives
`1.27 + 18.0 + 0.43 + 0.93 + 0.10 ≈ 20.7 s`; budget ≤ 25 s. Per-file fsync is
a configuration choice (`durability`); the default process-death guarantee
does not need it because the OS page cache survives any process kill, only a
machine/power failure loses it.

**Cold-cache caveat (explicit):** the copy constant is page-cache-warm. If the
source must be read from the device, add `B / R_disk`; at `R_disk = 500 MiB/s`
add ~2 s, at 150 MiB/s (HDD) add ~7 s. On a network source, use the link
throughput instead. The budget above assumes local SSD and states the term it
would add elsewhere; it is not a guess about an unmeasured disk.

`--verify-hash` adds `B / 2152 MiB/s ≈ 0.5 s` for 1 GiB plus one open/read per
file.

### 14.3 Incremental budget (for comparison)

All 20,000 files unchanged: `0.51 s scan + 6.75 s links + 0.37 s validation +
0.05 s index ≈ 7.7 s`, added data bytes **0**, added metadata ≈ 2.1 MiB.
Honest note: at 1 KiB average file size, linking (0.338 ms) is comparable to
copying a 1 KiB file (0.36 ms), so the wall-time win at tiny file sizes is
neutral; the win is disk/bytes and grows with file size (for 1 GiB in 20 files:
full copy ≈0.45 s vs links ≈0.007 s). The requirement "recognize instead of
copy again" is met in bytes and disk, not falsely claimed in wall time.

---

## 15. Grounding: reuse vs override (exact names and lines)

| Concern | Existing code | Lines | Decision |
|---|---|---|---|
| Directory listing | `synccli.scan_files` | 10–19 | **Reuse** for the walk/relpath contract; **override** the dot-directory exclusion at line 14 when `include_hidden` (a backup must not silently omit `.git`/hidden eval output). |
| Stat identity | `synccli.file_state` | 22–25 | **Override**: add `dev`, `ino`, `mtime_ns`, `ctime_ns`, `mode`; replace float `st_mtime`; reason §8. |
| Manifest construction | `synccli.build_manifest` | 28–33 | **Reuse** the `{relpath: state}` shape, emitted per source and only for verified files (I2). |
| Change set | `synccli.changed_files` | 36–42 | **Reuse** for new/changed; **supplement** deletions by key-set difference, which it cannot see (its loop only visits `new`, line 39). |
| Retry/unverified set | `synccli.collect_stale` | 45–59 | **Reuse** after the copy pass: `collect_stale([(rel, verified), …])` yields the files needing retry; its tests at `test_synccli.py` 21–33 pin the first-item edge. |
| Byte copy | `synccli.copy_file` | 62–69 | **Override** (§7.1): streaming, temp+rename, fstat verify, preserve mtime/mode, propagate errors; existing code buffers whole files and swallows `OSError`, which lets a manifest promise an absent file (verified demo in §2.1). |
| Manifest/index write | `synccli.sync`, lines 85–86 (`open(...,"w")`) | 72–87 | **Override** with an index written to temp+fsync+rename inside staging; in-place JSON write is torn on crash and the manifest includes failed copies. |
| Manifest filename | `synccli.MANIFEST_NAME` (line 7) `.sync_manifest.json` | 7 | **Not used**; snapshots use `.backupctl/index/<id>.json` + `COMMIT.json` (§3). |
| Snapshot listing | `snaputil.list_snapshots` | 8–20 | **Reuse** ordering/name contract; **guard** symlinks (`entry.is_dir()` follows them, verified) and require the `snap-<date>-<time>-<seq>` pattern before treating a name as a snapshot. |
| Retention selection | `snaputil.prune_snapshots` | 23–36 | **Reuse** "oldest first, newest never deleted" intent; **override** the `shutil.rmtree` loop at 33–35 with validity/age/reader guards and atomic rename-to-trash (§10). Ordering for the decision uses `seq`, not lexicographic names, so clock steps cannot delete a new snapshot. |
| Disk usage | `snaputil.snapshot_disk_usage` | 39–51 | **Override**: count unique `(dev, ino)` so hardlinks are not double-counted (verified 2000 vs 1000) and use `lstat` so symlinks are not followed (line 50 uses `os.stat`). |
| Path containment | `snaputil.safe_snapshot_path` | 54–63 | **Override** entirely (§11): it demonstrably escapes (`../../`, absolute paths); `normpath` does not strip leading `..`. |
| Staleness | `snaputil.is_stale` | 66–73 | **Not used** for completeness; directory mtime is changed by child operations and is not an index-completeness signal; completeness is the atomic publish + `COMMIT.json` (§5, §6). |
| CLI framing | `synccli.main` | 90–99 | **Reuse** the argparse/print-result pattern (`argparse`, `json`, `os`, `shutil` only). |

No new module invents scanning, statting, change comparison, path mapping,
listing, pruning policy, or disk accounting from scratch: each is the named
existing function with the named override.

---

## 16. Test plan

`test_backupctl.py`, run with `python3 -m unittest`, extending the style of
`test_synccli.py` (tempdirs, direct function calls) plus subprocess tests for
kill/concurrency.

1. **Atomic publish**: monkeypatch the publish step to raise between `COMMIT`
   write and rename → no `snap-*`; next run GCs staging, reports it, succeeds.
2. **SIGKILL mid-copy**: subprocess run against a large fixture, kill during
   copy → no `snap-*`; rerun publishes; report lists staging discarded.
3. **Corrupt index recovery**: truncate a per-source index in a completed
   snapshot → next run quarantines or re-derives per §6.1, reports exactly what
   was lost, and never publishes an index promising a missing file.
4. **Two runs collide**: start run A holding the lock; run B exits 75 and
   writes nothing; A's snapshot validates.
5. **Restore during prune**: reader holds `LOCK_SH`; prune skips it and
   reports `reader`. Without the lock, assert a walker either sees all files
   or `ENOENT`, never a partial tree (rename-first).
6. **Vanishing source between scan and copy**: delete after scan → file absent
   from snapshot and index; report `missing`; next run captures it if it
   returns.
7. **Unreadable source**: mode `000` → absent from snapshot and index; contrast
   regression against `synccli.sync` behavior demonstrated in §2.1; snapshot
   still validates (I2).
8. **Change-detection granularity**: same-size in-place edit with `utime`
   restoring mtime → detected via `ctime`/`ino`; simulated coarse-timestamp
   case documented as a miss; `--verify-hash` catches it.
9. **Hardlink dedup and accounting**: unchanged file has `st_nlink == 2`;
   `snapshot_disk_usage` override reports unique bytes, not double.
10. **Path escapes**: `'../../escape.txt'`, `'/etc/passwd'`,
    `'a/../../../b'` rejected by `contained_path`.
11. **Retention**: newest/only/young/busy snapshots are never deleted; a
    delete never reduces valid snapshots below `keep`; hardlinked data remains
    readable in newer snapshots afterward.
12. **Performance smoke** (opt-in, marked slow): 20k-file fixture must finish
    within the §14 budget on a CI-class machine, using the formula rather than
    a hard 12 s on unknown hardware.

Existing tests (`test_synccli.py`) remain unchanged and continue to pass; they
document the reused `scan_files`/`collect_stale`/`sync` behavior.

---

## 17. Limitations and rejected alternatives

- **Hardlink immutability contract** (§9.4): an external in-place edit through
  a snapshot path affects every snapshot sharing the inode. Accepted in
  exchange for `0` data bytes per unchanged file; `--verify-hash` detects it.
- **Per-file metadata changes** (owner, group, xattrs, ACLs) are neither
  preserved nor part of identity; only mode and mtime are.
- **Foreign restore tools** that ignore locks can get `ENOENT` if they outlive
  `min_age_seconds` and the snapshot is pruned mid-walk; documented, with the
  lock/rename guarantee that they never see a partial tree under the name.
- **No compression, encryption, remote transport, or cross-version dedup.**
  Those are orthogonal; the snapshot layout (per-source index + immutable
  tree) does not prevent adding them.
- **Rejected: full copy per snapshot.** Simple, but disk is `keep × B` for
  every version even when nothing changes; violates the "most files do not
  change" requirement.
- **Rejected: reflink/clonefile (APFS `clonefile`).** Would avoid the shared
  inode contract, but is platform-specific and not available through the
  stdlib on the Python version in this directory (3.10); hardlinks are POSIX
  and measured here.
- **Rejected: an overlay/manifest-only snapshot with no materialized tree.**
  Readers (including separate restore tooling) would need to understand the
  overlay and would depend on older snapshots; the brief's "reader never asks
  whether the run is finished" is best served by a self-contained immutable
  tree.
- **Quarantine is not auto-deleted.** Corrupt published trees are kept for
  operator inspection; they consume disk until `backupctl quarantine purge` is
  run manually. This trades disk for never deleting data on a corruption path.

---

## Appendix A — measurements (reproducible in this directory)

All run with the code in this directory, Python 3.10.11, macOS/APFS.

```
$ python3 -m unittest -v
... Ran 6 tests in 0.005s  OK

# scan / manifest / memory / index (20k files, 1 KiB)
build_manifest 20k files: 0.543s  (36864 files/s)
build_manifest warm 20k: 0.551s (36275 files/s)
changed: 0 0.0020s
manifest: 20000 entries, peak 7.4 MiB (386 B/file)
index json: 2.1 MiB, dump 0.050s, load 0.011s

# lstat vs walk (20k)
scandir walk+type: 0.056s
lstat 20k: 0.372s

# copy (same volume)
copy 512MiB: 0.21s  2409 MiB/s
sync full copy 20000 files (0.95 GiB): 7.59s  129 MiB/s, 2634 files/s

# hardlink / rmtree / hashing / fsync
hardlink 20k files: 6.75s (2963 links/s)
rmtree 20k files: 1.58s (12641 unlinks/s)
sha256 256MiB: 0.12s = 2152 MiB/s
1000 file write+fsync: 0.08s

# synccli failure modes confirmed
unreadable source: copied ['secret.txt']; manifest promises ['secret.txt'];
  snapshot file present: False
source deletion: after source deletion -> dst has stale a: True b: True

# snaputil failure modes confirmed
safe_snapshot_path('../../escape.txt') -> <root>/snap-x/../../escape.txt
safe_snapshot_path('/etc/passwd')      -> /etc/passwd
hardlink pair (one 1000-byte inode): disk usage reported 2000, unique 1000
symlink named snap-*: appears in list_snapshots
```

These measurements are the source of every constant in §13–§14; they are
derived from this code, not estimated.

# DESIGN-d1 — `backupctl`

Status: design, no code written. Basis: `BRIEF.md`, `synccli.py`, `snaputil.py`,
`test_synccli.py` in this directory, plus measurements run on this machine
(Appendix A). All timings are from `python3` 3.10.11 on macOS 15.8.1, Apple
M3 Max, APFS on the internal NVMe, warm page cache unless stated otherwise.

---

## 0. Decisions at a glance

| Question | Decision |
|---|---|
| Snapshot visibility | Snapshot is built in `<root>/.stage/<run>/` and published with one `os.rename` into `<root>/snap-…`. A reader that lists `snap-*` never sees a partial snapshot. |
| Concurrent runs | One global writer lock (`flock`). First run wins, second waits (`--wait`) or exits 75 (`EX_TEMPFAIL`). Lock is released by the kernel on death — no stale-lock recovery. |
| Reader vs delete | Per-snapshot lock file in `<root>/.locks/`; readers take `LOCK_SH`, retention takes `LOCK_EX` before rename-to-trash. Lock is held across "snapshot exists" re-check, so a reader can never be reading a snapshot that is being deleted. |
| Crash mid-run | Staging tree is invisible and discarded wholesale by the next run; published snapshots are immutable and complete by construction. Corrupt *published* index is rebuilt from the tree and reported. |
| Missing/unreadable source file | The file is omitted from the snapshot and from the index, recorded in `skipped[]`, reported, exit code 3 — identically for scheduler and human. |
| Change detection | Per-file `(dev, ino, size, mtime_ns, ctime_ns, mode)` equality (plus `sha256` when hashing is enabled). Same tuple ⇒ link/clone from the previous snapshot, no data copy. Misses are enumerated in §6.1. |
| Unchanged file materialization | Hardlink from the **previous snapshot** (never from the live source), fallback `clonefile(2)`, fallback copy. Measured: 0.48 ms/file, +2 MiB physical per 20 000 files (0.95 GiB of data). |
| Retention | Tiered selection over `snaputil.list_snapshots`, deletion through the reader-lock protocol, never the newest snapshot, never the last valid one. |
| Full backup budget | 1 GiB / 20 000 files: **30 s** warm, **90 s** cold/contended. Derivation and measurements in §10. |
| Grounding | `scan_files`, `file_state` semantics, `changed_files`, `list_snapshots`, `prune_snapshots`, `snapshot_disk_usage` reused; `sync()`, `copy_file()`, `build_manifest()`, `safe_snapshot_path()`, `collect_stale()`, `is_stale()` are overridden or deliberately unused, each with file/line and reason (§1, §3–§9). |

---

## 1. Grounding inventory: what is reused, what is overridden, and why

Everything below was read and, where a claim is behavioural, executed against
the real code (Appendix A.1). Line numbers are from the files in this
directory.

### 1.1 Reused as-is

| Artifact | What it does | Where it is used |
|---|---|---|
| `synccli.scan_files(root)` | `os.walk`, drops directories whose name starts with `.` (line 14), returns a **sorted** list of relative paths. Sorting matters: it makes run reports and index key order deterministic, which is part of "same behaviour for scheduler and person". | Source enumeration; the same walk is reused (as `scan_source_entries`) to rebuild an index from a snapshot tree. |
| `synccli.changed_files(old, new)` | Returns `rel` when `rel not in old_manifest or old_manifest[rel] != state` (lines 36–42). Dict equality is exactly the semantic needed for a multi-field state tuple. | Copy plan for each source: `changed_files(previous_snapshot_states[key], current_states)`. |
| `snaputil.list_snapshots(root)` | Lists directories whose name starts with `snap-`, sorted (lines 8–20). Verified in A.4 that `.stage/`, `.locks/` and `trash-*` are ignored, so staging and trash are invisible to it. | Snapshot enumeration for base selection, retention, `list` and `verify`. |
| `snaputil.snapshot_disk_usage(root, name)` | Sums `st_size` of every regular file in a snapshot (lines 39–51). | *Logical* size reporting only (caveat in §8.4). |
| `snaputil.prune_snapshots(root, keep)` | Deletes the oldest `len-K` snapshots with `shutil.rmtree` (lines 23–36). | Only when the configured policy is the simple "keep newest K"; called under the writer lock and inside the guards of §8. Tiered policies use `list_snapshots` + the deletion protocol directly. |
| `synccli.file_state` semantics | The `(size, mtime)` idea (lines 22–25). | Reused conceptually, not called: see 1.2. |
| `test_synccli.py` | 6 tests, all pass today (`python3 -m unittest`, A.1). | Kept green: `backupctl` does not change any `synccli` signature. |

### 1.2 Deliberately overridden (name, location, reason)

1. **`synccli.copy_file` (lines 62–69) — replaced entirely.**
   Four independent defects, all verified:
   - `fsrc.read()` (line 67) buffers the whole file: measured RSS 9 MiB →
     1 033 MiB on a 1 GiB file (A.3). A backup tool must stream. Replacement
     copies in 1 MiB blocks (measured peak 28 MiB RSS, 4.2 GiB/s warm, A.3).
   - `except OSError: pass` (lines 68–69) hides ENOENT/EACCES/EIO. Measured:
     a `chmod 000` source produced `copied: ['a.txt', 'b.txt']` while
     `b.txt` did not exist in the destination (A.1). Replacement returns a
     typed outcome (`ok|unstable|skipped(errno)`) for every file.
   - No `fsync`, no write-to-temp-then-rename: a dead process or a failed
     read can leave a short file at the final name. Replacement writes
     `<staging>/<rel>.part-<uuid>`, fsyncs, then `os.replace`, all inside the
     staging tree.
   - No mode preservation: `open(dst,"wb")` creates `0666 & ~umask`. The
     index records `st_mode`, so a restore can reproduce the mode.
2. **`synccli.build_manifest` (lines 28–33) — replaced.**
   It stats paths produced by `scan_files` and lets any `OSError` escape:
   measured, a file deleted between listing and stat makes `sync()` raise
   `FileNotFoundError` and abort the whole run (A.1). Replacement is
   `scan_source_entries()`: the same walk/filter as lines 13–18, but it yields
   `(rel, lstat_result)` from the same `DirEntry`, and a vanished entry is
   recorded as a skip instead of aborting. (Warm-cache measurements show the
   `DirEntry.stat()` variant at 27.4 µs/file vs 28.2 µs/file for path-based
   `lstat` - a 3 % difference, A.2; the win is error containment and one fewer
   path resolution per file, not raw speed.)
3. **`synccli.file_state` (lines 22–25) — replaced.**
   - `os.stat` follows symlinks: a dangling link aborts the run (same
     `FileNotFoundError` class), and a link to `/etc` would be backed up as
     data. Replacement uses `os.lstat`, records symlinks as symlinks with
     their target string, and never follows them.
   - `st_mtime` is a float. At 2026 epoch values the representable spacing is
     ~477 ns (measured value `1794849632.8527977`, A.1), so two distinct
     `mtime_ns` values can compare equal. Replacement stores
     `st_mtime_ns`/`st_ctime_ns` integers and `st_dev`/`st_ino`.
4. **`synccli.sync` (lines 72–87) — not called.**
   - Manifest is written with `open(..., "w")` then `json.dump` (lines 85–86):
     a crash truncates the index. Replacement publishes the index by atomic
     replace inside staging and then renames the whole snapshot (3.3).
   - The manifest is written from `src_manifest` (line 86) *after* copies that
     may have silently failed (line 84 → 68–69): the index promises files the
     snapshot does not contain — precisely the failure the brief forbids.
     Measured (A.1): index lists `b.txt`, destination has no `b.txt`.
   - No locking, no staging, and no deletion handling: files removed from the
     source are never removed from the destination (it only copies
     `to_copy`, lines 83–84), so the destination is not a point-in-time image.
   - Reusing `sync()` would require replacing its copier, its manifest writer
     and its loop; that is the whole function. The building blocks above are
     reused instead.
5. **`snaputil.safe_snapshot_path` (lines 54–63) — replaced, security.**
   The docstring claims the result "never points outside
   `backup_root/<snapshot_name>`"; it is false. `os.path.normpath` keeps
   absolute paths absolute and leaves leading `..` components, and
   `os.path.join` discards the base when the second argument is absolute.
   Measured (A.1): `safe_snapshot_path(root,"snap-1","/etc/passwd")` returns
   `/etc/passwd`, and `"../../../etc/passwd"` climbs out of the snapshot.
   Replacement `resolve_in_snapshot()`: reject absolute paths, reject any `..`
   component after `normpath`, then `os.path.realpath` + `os.path.commonpath`
   containment, and `O_NOFOLLOW` when opening entries. The old function stays
   in place (other callers/tests) but `backupctl` never calls it.
6. **`snaputil.prune_snapshots` (lines 23–36) — wrapped, not called directly
   for tiered policy.**
   - It deletes with a bare `shutil.rmtree` (line 35) with no reader
     protection: a restore in flight loses files mid-walk. Replacement goes
     through the per-snapshot lock (§8.2).
   - `keep=0` deletes **every** snapshot, including the newest
     (`doomed = names[:len(names)-0]`, lines 32–33) — violates "never leave
     the user without a usable snapshot". The wrapper enforces `keep >= 1` and
     the guards of §8.3.
   - Its ordering is purely lexicographic on names (line 20/30). That is
     correct only for our fixed-width, zero-padded names; see §8.3 for the
     format validation that protects against foreign `snap-*` directories.
7. **`snaputil.is_stale` (lines 66–73) — deliberately unused.**
   It compares a snapshot directory's `st_mtime` to a caller-supplied epoch.
   Directory mtime moves when children are added or removed, and a published
   snapshot's directory mtime is not a completeness signal; completeness is
   the presence of a validated `manifest.json` in a snapshot that appeared via
   rename. Using mtime would classify a just-written directory, or an
   externally touched one, incorrectly. Not used, by design.
8. **`synccli.collect_stale` (lines 45–59) — evaluated, deliberately unused.**
   It filters an iterable of `(path, fresh)` pairs against a `seen` set. The
   copy plan is already exactly `changed_files(previous, current)`; calling
   `collect_stale` would require materializing a parallel `(rel, fresh)` list
   plus an extra `O(F)` `seen` set to express the same filter. It is not
   re-implemented — it is simply the wrong shape for this pipeline, and using
   it would add memory without changing behaviour.

### 1.3 Behavioural contract we must not break

`test_synccli.py` imports `synccli` only; `backupctl` adds a module and a CLI
without touching `synccli`'s public functions, so the 6 tests remain the
regression gate for the reused pieces (A.1).

---

## 2. On-disk layout

```
<backup_root>/
  snap-20261116-120000-00/          published snapshots (name = UTC date-time-seq)
    .backup/
      manifest.json                 committed index, one per snapshot (§3.3)
      sources/<key>.sync_manifest.json   compat projection for synccli-style readers
    <key>/…                         data tree of source <key> (one directory per source)
  .stage/<run-id>/                  in-flight snapshot (invisible to listings)
  .locks/
    writer.lock                     0 bytes, flock only
    snap-20261116-120000-00.lock    one per published snapshot (reader/deleter)
  .trash/<name>.<nanots>/           snapshots being deleted (§8.2)
```

- `<key>` is a stable slug: sanitized basename of the source path + 4 hex
  digits of `sha1(realpath)`. Renaming the config file or moving other
  sources does not change it; changing the source path does, which is
  reported as a new source (first full backup of it) rather than silently
  diffing against the wrong tree.
- Data directories are **not** hidden, so `synccli.scan_files` over a source
  directory inside the snapshot returns the source's own relative paths.
  Metadata lives in `.backup/`, which `scan_files` skips as a dot-directory
  (line 14) — index bytes are never mistaken for backed-up data. The compat
  projection has the same payload shape as `synccli.MANIFEST_NAME`
  (`{rel: {size, mtime, …}}`, synccli.py:7), so `synccli.changed_files` can
  consume it directly.
- `.stage` and `.locks` do not match `snap-`, so `snaputil.list_snapshots`
  ignores them (verified, A.4). `trash-…` is also ignored; `.trash/` is a
  dot-directory anyway.
- Everything under `<backup_root>` is therefore either a complete published
  snapshot, an internal directory that listings ignore, or nothing.

---

## 3. Run pipeline and the atomic commit

### 3.1 Phases of one run

1. **Lock** — take the writer lock (§4.1). On failure: exit 75 with a report,
   unless `--wait`.
2. **Recover/GC** — with the writer lock held: discard every `.stage/*`
   directory (no other process can own one, §5.3), and delete `.trash/*`
   entries older than `retention.trash_grace` (default 300 s).
3. **Choose base** — newest snapshot by name among `snap-*` directories that
   pass validation (or successful rebuild) of §5.4. If none: base = `null`
   (full backup), reported as `base: null`.
4. **Per source, sequentially** (bounds memory, §11.2):
   a. enumerate with `scan_source_entries()` (the `scan_files` walk with
      `lstat` and error capture, §1.2 item 2) → current state map;
   b. `changed_files(base_states[key], current)` → copy plan;
   c. materialize every current file into `.stage/<run>/<key>/`:
      unchanged → hardlink from base snapshot (fallback `clonefile`, then
      copy); changed/new → streamed copy (temp name, fsync, `os.replace`);
      symlink → recreate symlink; special file → record only;
   d. write the compat projection `.backup/sources/<key>.sync_manifest.json`;
   e. fold counts into the run totals and **drop** the state map.
5. **Commit index** — write `.backup/manifest.json` (status `complete`) into
   staging with fsync; fsync `.backup/` and the staging root.
6. **Publish** — `os.rename(.stage/<run>, snap-<name>)`; fsync the backup
   root. One rename, same filesystem, atomic.
7. **Retention** — §8, while still holding the writer lock.
8. **Report + unlock** — emit report (human summary on stderr, `--json` on
   stdout), exit with §7.4's code; releasing the lock closes the process's
   `flock`.

### 3.2 Naming

`snap-YYYYMMDD-HHMMSS-NN`, UTC, fixed width. `NN` counts existing snapshots
sharing the same date-time prefix, computed under the writer lock. If `NN`
would exceed 99 in one second, the run sleeps until the next second (keeps
lexicographic order equal to chronological order, which `list_snapshots` and
`prune_snapshots` rely on). Because the writer lock serializes runs, `NN`
only matters when a run finishes inside the same second as the previous one.

### 3.3 Why this is atomic for readers

- Data files, the compat projections and `manifest.json` all exist inside
  `.stage/<run>`. Nothing outside can name them.
- The final directory name appears only via `os.rename`. POSIX rename of a
  directory to a non-existent name on the same filesystem is atomic: a
  concurrent `list_snapshots` sees either no entry or the complete tree.
- `manifest.json` is written once, before the rename, and is never modified
  afterwards except by an atomic `os.replace` during repair (§5.4). Readers
  therefore see either the old or the new index, never a torn one.
- Write ordering: each copied file is fsynced before the index is written and
  fsynced, so a durable index implies durable data. Default fsync cost is
  measured at 0.21 ms/file in an isolated microbenchmark, A.3 (4.2 s for
  20 000 files, the conservative figure used in the budget; the marginal cost
  inside the real copy loop measured only +0.82 s, ~8 %, A.3);
  `--durable=full` switches to `F_FULLFSYNC` (4.1 ms/file, 82 s per 20 000
  files, A.3) for power-loss-grade durability.

---

## 4. Concurrency

### 4.1 Writer lock (scheduler vs person)

`<root>/.locks/writer.lock`, opened `O_CREAT|O_RDWR` mode 0600, then
`fcntl.flock(fd, LOCK_EX | LOCK_NB)`. Measured (A.4): a second process gets
`EWOULDBLOCK`; the lock is released automatically when the holder's fd closes
*or the process dies*, and the next process then acquires it. Therefore:

- No PID-liveness heuristic, no stale-lock cleanup, no `O_EXCL` pid file.
  PID files are only written as a diagnostic string (pid, start time, run id)
  and are never trusted for correctness (PID reuse).
- The writer lock file is never deleted — deleting and recreating a lock file
  is a classic race. `.locks/writer.lock` is one 0-byte inode, bounded
  forever.
- Collision policy: default `--wait=0` → exit 75 `busy`, report includes the
  holder's diagnostic string. `--wait=S` polls at 250 ms up to S seconds,
  then 75. Same binary, same behaviour for both triggers; nothing is queued
  silently and nothing is interactive.
- Lock ordering: writer lock first, then at most one per-snapshot lock at a
  time (retention, §8.2). Readers take only per-snapshot locks. There is no
  cycle, so no deadlock.
- Assumption: local filesystem with sane `flock`+`rename` semantics (APFS,
  ext4, xfs). On NFS, `--lock=none` exists and prints a warning that
  concurrent runs are then unsafe; this is a documented limitation, not a
  silent fallback.

### 4.2 Reader/deleter protocol (per snapshot)

Reader (restore tooling, a human copying files, or `backupctl restore`):

1. open `.locks/snap-<name>.lock` (`O_CREAT`), `flock(LOCK_SH)`;
2. then verify `snap-<name>` is a directory and `.backup/manifest.json` parses
   with `format`/`status: complete`; if not, unlock and fail cleanly
   (`snapshot gone or incomplete`);
3. read; unlock.

Deleter (retention, §8.2):

1. open the same lock file, `flock(LOCK_EX)` (blocking with
   `retention.lock_timeout`, default 30 s);
2. re-verify the snapshot is still a candidate and not the newest/valid guard;
3. `os.rename(snap, .trash/<name>.<nanots>)` — atomic;
4. `shutil.rmtree(.trash/<name>.<nanots>)` (measured 1.78 s for 20 000 files,
   A.3);
5. unlink the lock file **while still holding** the lock; unlock.

Why this is safe:

- The reader's order (lock → existence check) and the deleter's order
  (lock → rename) interleave in only two ways: reader locks first ⇒ deleter
  blocks until the read is done; deleter locks first ⇒ reader blocks, then
  sees the snapshot absent and reports it cleanly. There is no window in
  which a reader holds a shared lock on a snapshot that is being removed.
- If the deleter unlinks the lock file, a reader that already opened the old
  inode and only then acquires `LOCK_SH` is not protected by the now-unlinked
  inode — but its existence check runs *after* the lock and the snapshot is
  already gone, so it fails cleanly and retries. The invariant is preserved
  by the check, not by the inode.
- Hardlinks make deletion harmless to newer snapshots: unlinking an inode in
  an old snapshot only decrements the link count (§6.3).
- Honesty about non-cooperating readers: separate tooling that ignores this
  protocol can still lose a file mid-walk. The rename-to-trash step plus
  `trash_grace` (default 300 s before `rmtree`) means a path-based reader that
  finishes within the grace period is unaffected even without locking; an
  absolute guarantee for readers requires the documented protocol. This is
  stated in the restore documentation and in the design's limits (§14).
- Crash during deletion: rename is atomic, so a crash leaves either the
  snapshot or a trash entry, never a half-deleted `snap-*`; the next run's GC
  finishes the trash entry (§5.3).

---

## 5. Crash safety and index recovery

### 5.1 Process death at any point

| Killed during | What exists afterwards | What the next run does |
|---|---|---|
| scan / stat / copy / link | `.stage/<run>/` with partial tree and no published name | Discards it wholesale (writer lock proves no live run), reports `discarded_staging: 1` |
| index write | `.stage/<run>/.backup/manifest.json` truncated | Same discard; the truncated index never leaves staging |
| between index fsync and rename | Complete staging tree, unpublished | Discarded (it is not a published snapshot; no index points at it) |
| during rename | Old namespace or new namespace (atomic); rename is one transaction | Nothing; either a valid snapshot or a staging dir is discarded |
| during retention rename | Snapshot or `.trash/<name>` | GC completes the trash entry after grace |
| during retention rmtree | `.trash/<name>` partial | GC removes it after grace |

No manual cleanup is ever required: `.stage` and `.trash` are the only
places a dead run can leave residue, and both are managed by the next run's
phase 2. Nothing a reader could list (`snap-*`) is ever partial.

### 5.2 Interrupted run and the "in progress" snapshot

There is no in-progress marker to interpret, no `snap-*.partial`, no
`.incomplete` file. Incompleteness is represented by *not being in the
namespace*. That is why a reader never has to ask whether a run finished.

### 5.3 GC rules (writer lock held)

- Every `.stage/*` is orphaned by definition: only the writer-lock holder
  creates staging dirs, so while we hold the lock there is no live owner.
  `rmtree` each; report count. No pid/mtime heuristic and no reliance on
  `snaputil.is_stale`.
- `.trash/*` older than `trash_grace`: `rmtree`; report. A trash entry younger
  than the grace period is left alone (it is the no-lock-reader cushion of
  §4.2). Forced removal with `--retention-now`.

### 5.4 Corrupt or half-written index — exact recovery

Our own publishing never emits a corrupt published index (§3.3). A corrupt
index can still exist because of (a) disk error, (b) a snapshot produced by an
older build or by hand, (c) an interrupted tick that renamed before data was
durable on a filesystem that did not honour the ordering (mitigated by
`--durable=full`). The recovery is:

1. **Validate** the candidate base snapshot's `.backup/manifest.json`:
   `json.load` (catch `JSONDecodeError`/`UnicodeDecodeError`); check
   `format == "backupctl.index/1"`, `status == "complete"`, `run.id` equals
   the directory name, every `sources[i]` has `key`/`files`; then for each
   `files` entry `lstat` the tree path and compare `size`, and for each
   symlink compare the target string. Cost is one `lstat` per entry: 0.55 s
   per 20 000 entries warm (27–28 µs/file, A.2).
2. **Classify**:
   - *unparseable* — no JSON or wrong `format`/`status`;
   - *dangling* — parses, but entries promise files absent from the tree (the
     case the brief names explicitly);
   - *mismatched* — entries exist but `size`/symlink target differs;
   - *unreadable subtree* — some data directory cannot be walked.
3. **Recover** (non-destructive; never delete user data in this path):
   - *unparseable*, *dangling*, *mismatched*: re-derive the index **from the
     snapshot tree itself** with `scan_source_entries()` over each
     `<snap>/<key>/` (with `include_hidden=True`, so a source's dot-directories
     are not silently dropped), atomically `os.replace` the rebuilt
     `manifest.json`, set `"recovered": {"action":"rebuilt", "entries":…,
     "dangling":…, "missing":…}`. `sha256` is re-derived only when hashing is
     enabled or `--repair --hashes` is passed (2.9 s/GiB, A.3); otherwise the
     field is absent and `verify --hashes` reports it as unknown rather than
     failing.
   - Files that are absent or wrong-sized are recorded with `"state":
     "missing"`, the snapshot's `status` stays `degraded` (not `complete`),
     and **no `missing` entry may ever be used as a hardlink source** for a
     new snapshot.
   - *unreadable subtree*: leave the snapshot untouched and unusable as a
     base; it is still reported as a usable-for-restore candidate (it may be
     partially restorable), and retention's "last valid snapshot" guard
     (§8.3) protects it.
4. **Report** — every action appears in `report.recovery[]` (snapshot name,
   action, entry counts, dangling/missing counts, whether hashes were
   re-derived), one warning line per snapshot on stderr, and exit code 3
   (published with warnings) if the degraded snapshot was used as the change
   base, 0 if it was rebuilt cleanly and fully. Nothing is ever deleted by
   recovery.
5. **Base selection consequence**: the base is the newest snapshot that
   validates or was successfully rebuilt. If none, the run performs a full
   backup, reports `base: null` and `recovery: [{action:"no_usable_base"}]`,
   and still makes progress — the brief's "next run must make progress
   without manual cleanup".
6. **Compat projection damage** (`sources/<key>.sync_manifest.json`
   truncated/corrupt) is not a recovery event: it is a derived artifact,
   regenerated from the main index atomically during the same run.

`backupctl verify <snap> [--repair] [--hashes]` exposes the same machinery
without running a backup.

---

## 6. Change detection

### 6.1 Granularity, stated exactly

Unchanged means equality of the per-file tuple

```
(dev, ino, size, mtime_ns, ctime_ns, mode)        regular file
(target string)                                   symlink
```

computed by `lstat` during enumeration. The decision is per file. The copy
plan is `synccli.changed_files(base_states[key], current_states)`, i.e.
"new or any tuple field differs" (lines 36–42).

What this granularity can miss:

1. An in-place content change that leaves all six fields identical. Not
   possible through normal POSIX writes: any write updates `ctime` (and
   `mtime`), and `ctime` cannot be set by `utime`/`utimensat`/`touch`; a
   rewrite through a new file changes `ino`. Reachable only by raw block
   device writes, by restoring a whole-volume snapshot that rolls `ctime`
   backwards (inode numbers then usually differ too), or on a filesystem with
   coarse timestamps where a same-size rewrite lands in the same tick.
2. **Coarse timestamp filesystems**: on 1-second-granularity filesystems
   (HFS+, ext3), a same-size rewrite within the same second can produce equal
   `mtime_ns`; `ctime_ns` has the same granularity, so it can be missed.
   Mitigation: `--hash=on-change` will not help (the metadata says unchanged);
   only `--hash=always` catches it. Detected at config time: the run reports
   the source filesystem's timestamp granularity if it is coarser than 1 ms.
3. Reading a file while it is being written: handled as instability, not as
   change detection (§7).
4. Hardlinked **source** files: two paths, one inode. The tuple is per path,
   so both are recorded; content is copied for the first and the second copy
   is independent unless the source link count is preserved (we do not
   preserve source hardlinks; §14).

What it can over-detect (safe direction): a source restored from another
volume changes `dev`/`ino`/`ctime` ⇒ every file re-copied. That is wasted
work, never a stale snapshot; reported as `changed_reason` counts
(`ino`,`ctime`) so the operator sees why.

Why `mtime_ns`/`ctime_ns` instead of the float `st_mtime` of
`synccli.file_state` (lines 22–25): at 2026 epoch values a float64 can
distinguish only ~477 ns (A.1), so distinct APFS timestamps can compare
equal. Integers are exact and free.

### 6.2 Hashing

`--hash=never|on-change|always` (default `on-change`: hash only files whose
tuple differs, and store it; this gives restore-time verification of new data
for free because the bytes are being read anyway).

- `always`: hashes every file every run. Measured cost 351 MiB/s single-core
  ⇒ 2.9 s per GiB per run (A.3). Detects case 1 and case 2 above at the price
  of a full read; suitable for sources on coarse-timestamp or network
  filesystems.
- `on-change`: hashing is free (bytes are already streaming) and stores
  `sha256` for changed files; unchanged files inherit the base snapshot's
  hash, which is still valid because the tuple matched.
- Hash is `sha256` (chosen for portability of verification tooling, not
  speed; BLAKE2b measured 148 MiB/s here, A.3, so nothing is lost).

### 6.3 Materializing unchanged files

Order of preference, per unchanged file:

1. **Hardlink from the previous snapshot's file** (measured 0.48–0.50 ms/file;
   +2 MiB physical for 20 000 files holding 0.95 GiB, A.4).
2. **`clonefile(2)`** if hardlink fails (measured 0.29–0.45 ms/file, +77 MiB
   physical, A.4) — APFS copy-on-write from the base snapshot.
3. **Streamed copy** as last resort (0.51–0.71 ms/file, +1026 MiB, A.4).

Safety argument for hardlinks: a link is only ever created **from an older
snapshot**, never from the live source tree. Older snapshots are immutable, so
a later in-place write to the source file (which operates on the source's own
inode) cannot mutate snapshot content. Link chains are therefore always
backward in the snapshot lineage, and an inode's link count is at most the
number of retained snapshots that still contain it (≤ retention K, §8).

Known consequence: an in-place edit **inside a snapshot path** would mutate
every snapshot sharing that inode. Snapshots are documented immutable; restore
copies out. `--seal` additionally removes write bits (chmod on a hardlinked
inode propagates to all snapshots sharing it; the index records the captured
mode, so a sealed older snapshot's on-disk mode may differ from its index —
documented, reported by `verify --modes`).

Why not avoid materializing unchanged files entirely (reference the base
snapshot and store only deltas): a reference-based snapshot is not
self-contained — restore would chase a chain of references, and retention
would need reference counting and could never delete a base that a newer
snapshot pins. The current design trades 0.29–0.50 ms/file of metadata work
for a snapshot that any tool can read with a plain directory walk
(`snaputil.snapshot_disk_usage`, the `resolve_in_snapshot` mapping of §9,
`cp -a`).

---

## 7. Sources that disappear or cannot be read

### 7.1 Per-phase behaviour

The pipeline never retries indefinitely, never prompts, and never depends on
how the run was started. A file that cannot be captured is **absent from the
tree and absent from the index**: the index never promises a file the
snapshot does not contain.

| Detection point | Trigger | Snapshot content | Index | Report | Exit |
|---|---|---|---|---|---|
| enumeration | directory vanished mid-walk, `lstat` ENOENT | entry absent | absent | `skipped[{rel, phase:"stat", errno:2}]` | 3 |
| copy | ENOENT between stat and open | entry absent | absent | `skipped[phase:"copy"]` | 3 |
| copy | EACCES/EPERM/EIO | entry absent; partial `.part-*` removed | absent | `skipped[phase:"copy", errno]` | 3 |
| copy + re-stat | source tuple changed during the read | retried once; if still changing, entry absent | absent | `unstable[{rel, attempts:2}]` | 3 |
| unchanged materialization | hardlink/clone OSError (EPERM/EMLINK/ENOTSUP) | falls back clone→copy; a skip only if copy also fails | `via` records which | `fallback[]` count | 0 normally, 3 if the copy fallback also fails |
| since previous run | file deleted from source | absent | absent | `deleted_since_previous: n` | 0 |
| special file | FIFO/socket/device | no data copy | `special[{rel, kind}]` | count | 0 |
| mount point | `st_dev` differs from source root's | not descended | `special[{rel, kind:"mount-point"}]` | count | 3 |

The `--include-unstable` flag commits torn content (marked `"unstable": true`)
instead of omitting it; the default omits because "a reader must see a
self-consistent image" outranks completeness for one file that is being
written. Either way the report and the index agree with the tree.

### 7.2 Same behaviour for scheduler and person

There is no TTY check, no prompt, no interactive retry, no different retry
budget. Ordering is `scan_files`-sorted, so two runs of the same input produce
the same sequence of `skipped` entries. `--json` and the human report are
produced from the same in-memory report structure. The only difference between
triggers is who reads the output. Configuration cannot introduce a difference:
`--strict` (config-level, default off) makes the run *not publish* a snapshot
with any skip, discarding staging and exiting 4 — still non-interactive.

### 7.3 What a snapshot contains when a source file is missing

All other files of that source as read at enumeration+copy time; no placeholder
for the missing path; no stale copy of the file's previous version (the new
snapshot is built from scratch in staging, so the previous snapshot's copy is
not silently inherited as if new). `deleted_since_previous` distinguishes
"deleted before the run" from "vanished during the run": the former is a
normal absence, the latter is a `skipped` entry.

### 7.4 Exit codes

| Code | Meaning |
|---|---|
| 0 | published, no skips, no degraded base |
| 3 | published, with skips/unstable entries and/or a degraded/rebuilt base |
| 4 | `--strict` refusal: skips present, nothing published, staging discarded |
| 5 | configuration error, invalid root, source inside backup root, unusable lock directory |
| 75 | another run holds the writer lock (`EX_TEMPFAIL`; scheduler retries later) |
| 1 | fatal I/O error before publish (staging discarded, snapshot namespace untouched) |

---

## 8. Retention

### 8.1 Policy

`retention = {keep_last: 7, keep_daily: 14, keep_weekly: 8, keep_monthly: 12,
min_valid: 1, trash_grace: 300, lock_timeout: 30}` (all configurable). A
snapshot is kept if it is the newest `keep_last`, or the newest in its UTC
day for the last `keep_daily` days, or the newest in its ISO week for
`keep_weekly` weeks, or the newest in its month for `keep_monthly` months.
Defaults cap the count at 30. `prune --dry-run` prints the decision per
snapshot.

Deletion order is oldest first (the order `list_snapshots` returns, line 20).
When the policy is exactly "keep newest K", `snaputil.prune_snapshots` is
called under the writer lock and its result is the report — otherwise the
selection above is computed and each chosen snapshot goes through §8.2.

### 8.2 Deleting safely while a reader may be reading

Per §4.2: shared/exclusive `flock` on `.locks/snap-<name>.lock`, rename to
`.trash/`, grace, `rmtree`, unlink lock. If `LOCK_EX` cannot be acquired
within `lock_timeout`, the snapshot is **not** deleted this run; it is listed
in `retention.deferred[]` with the holder's diagnostic string, and the next
run retries. Deletion failures (`EBUSY`, `EPERM`) are reported per snapshot and
never abort the run.

### 8.3 Guards (never leave the user without a usable snapshot)

1. The newest snapshot by name is never deleted.
2. If deleting the selected set would leave zero snapshots, the oldest
   selected snapshot is kept.
3. If fewer than `min_valid` snapshots remain whose index is `complete` (or
   rebuilt and not degraded), deletion stops.
4. `keep >= 1` is enforced before calling `snaputil.prune_snapshots`, which
   with `keep=0` would delete everything including the newest (lines 32–35).
5. Foreign directories: a `snap-*` directory that does not match
   `^snap-\d{8}-\d{6}-\d{2,}$` (or fails `run.id == dirname`) is reported as
   `foreign` and never deleted, never used as a change base. This closes the
   gap that `list_snapshots` accepts *any* `snap-*` directory (line 18).
6. `--retention-now` skips the trash grace but not the locks or the guards.

### 8.4 Disk accounting and the hardlink caveat

`snaputil.snapshot_disk_usage` sums `st_size` per snapshot (lines 39–51), so a
hardlink-shared 1 GiB file counts 1 GiB in every snapshot that links it: it
reports **logical** size, not physical. `backupctl list` labels it `logical`.
`--physical` computes actual bytes by deduplicating `(dev, ino)` across all
snapshots (`O(F)` memory for the report, not for the run), or, more cheaply,
reports the `statvfs` free-space delta attributable to a snapshot at creation
time (recorded in the index as `counts.new_bytes`). Its unguarded `os.stat`
(line 50) also raises if a file vanishes concurrently, so `backupctl` wraps
the call and reports the partial total instead of dying.

The bigger `st_size`-based trap: because the data is shared, deleting an old
snapshot frees only the inodes no newer snapshot links
(`st_nlink`-aware accounting via `--physical`). That is the correct behaviour
and the reason deletion is cheap in wall time (measured rmtree 0.089 ms/file
for the unlink itself) but why "reclaimed bytes" must never be estimated from
logical size.

---

## 9. Reader / restore contract (separate tooling, defined protocol)

`restore` is separate tooling per the brief; this design defines what it must
do, and `backupctl` provides the primitives.

1. **Discover**: `list_snapshots` order; skip `degraded` unless
   `--allow-degraded`; `foreign` directories are not snapshots and are never
   offered.
2. **Lock**: open `.locks/snap-<name>.lock`, `LOCK_SH`, then verify the
   snapshot directory and index (§4.2). Never rely on a listing made before
   the lock.
3. **Read the index**: `.backup/manifest.json`, `status: complete`; choose
   `sources[i].key`.
4. **Resolve paths** with `resolve_in_snapshot(snapshot_dir, rel)` — absolute
   paths rejected, `..` rejected, `realpath` containment, `O_NOFOLLOW` — which
   replaces the escaping `snaputil.safe_snapshot_path` (§1.2 item 5).
5. **Copy out** (never link or edit in place: hardlinked snapshot content is
   shared). Verify `size` (and `sha256` when present) as it reads; a mismatch
   is an error for that file, not a silent success. Reproduce `mode` from the
   index; xattrs/ownership only with the opt-in flags of §14.
6. **Unlock** after the last read.

`backupctl export <snap> --dest DIR` performs exactly this (so the protocol is
available even if the separate restore tool predates it), and
`backupctl reader-guard <snap> -- <cmd>` holds the shared lock around an
arbitrary command for legacy tooling.

---

## 10. Performance budget for the first full backup

### 10.1 Environment and measured constants

macOS 15.8.1, Apple M3 Max (14 cores), 36 GiB RAM, APFS on internal NVMe,
Python 3.10.11, warm page cache (the synthetic tree was generated in the same
session; run-to-run variance from APFS writeback is reported). Synthetic tree:
20 000 files × 50 KiB = 1 024 000 000 bytes (0.95 GiB) in 40 directories; the
budget below is stated for the brief's 1 GiB target, and the 5 % difference is
inside the stated margin. Raw data in Appendix A.

| Operation | Measured | Constant used in the budget |
|---|---|---|
| `synccli.scan_files` over 20 000 files | 0.236 s (11.8 µs/file) | 12 µs/file |
| state map via `lstat`/`DirEntry.stat` | 0.548–1.665 s (27–83 µs/file) | 28 µs/file (warm); 3× cold |
| streamed copy of 20 000 × 50 KiB (no fsync) | 10.18 s (509 µs/file) | 0.51 ms/file + bytes |
| same, with per-file `os.fsync` | 11.00 s (550 µs/file, +0.82 s over no-fsync) | +0.21 ms/file (isolated microbenchmark; conservative) |
| same with `F_FULLFSYNC` | — | +4.1 ms/file (measured on 200 files) |
| pure sequential copy, 1 MiB blocks, 1 GiB | 0.241 s (4 244 MiB/s) | 1 GiB/s conservative |
| write index (2.70 MB, 20 000 entries) + fsync | 0.062 s | 135 B/entry |
| publish `rename` + dir fsync | 0.4 ms | fixed |
| hardlink 20 000 files (0.95 GiB) | 9.50–9.83 s (475–491 µs/file), +2 MiB | 0.5 ms/file |
| `clonefile` 20 000 files (0.95 GiB) | 5.72–8.91 s (286–446 µs/file), +77 MiB | 0.45 ms/file |
| `rmtree` 20 000 files | 1.78 s | 0.09 ms/file |
| `sha256` read of 1 GiB | 2.919 s (351 MiB/s) | 2.9 s/GiB |

### 10.2 Derivation (1 GiB / 20 000 files, first full backup)

```
scan      0.236 s
stat      20 000 × 28 µs                  = 0.56 s
data copy 20 000 × 0.51 ms (create/write) = 10.2 s
bytes     1 GiB / 1 GiB/s (conservative)  = 1.0 s
fsync     20 000 × 0.21 ms                = 4.2 s
index     0.06 s
publish   0.0004 s
---------------------------------------------
sum                                      ≈ 16.3 s
```

Measured end-to-end staging builds of exactly this tree: **11.0 s** and
**24.3 s** (two runs; the slower one overlapped APFS writeback from tree
generation). The derivation is deliberately conservative — it uses the
isolated fsync constant and 1 GiB/s rather than the measured 4.2 GiB/s — so it
sits above the measured builds; the budget is that derivation with margin.
`F_FULLFSYNC` mode would add 82 s and is not the default.

**Budget: ≤ 30 s warm, ≤ 90 s cold/contended, for 1 GiB / 20 000 files.**
The 30 s figure is ~1.8× the 16.3 s derivation and 1.2× the slowest measured
build (24.3 s); the 90 s figure allows 3× cold metadata cost, 1 GiB/s data and
contention.
Per-file cost dominates, so this budget holds for the same file count at any
tree size in the 0.1–10 GiB range: `T ≈ 0.75 ms × F + B/(1 GiB/s)`. Ten
thousand 100 KiB files take about the same 15 s; twenty thousand 2 KiB files
still take ~15 s.

Incremental run, nothing changed (20 000 files): sum of the measured
components — scan+stat 0.54 s + hardlink 9.5 s + index 0.06 s ≈ **10 s,
budget 15 s**; with `clonefile` the materialization measures 5.7–8.9 s, so
≈ 6–9 s total.
A changed 100 MiB adds ~0.1 s of data copy plus one file-create per changed
file.

Scale, N = 30 sources × 20 000 files (30 GiB total): first full backup
≈ 30 × 16 s ≈ 8 min; no-change incremental ≈ 30 × 10 s ≈ 5 min. Both are
linear in total file count, not quadratic, because sources are processed
sequentially and state maps are dropped per source (§11.2).

### 10.3 What the budget does not include

Cross-source global consistency (sources are captured sequentially; skew = run
duration, ~10–20 s at 30 GiB, reported as `capture_skew_seconds`), and reading
data from a network filesystem (the per-file constants above are local-APFS
numbers; on NFS the 0.5 ms/file constant can be 10–50× larger and the budget
scales accordingly — the formula, not the number, is the contract).

---

## 11. Growth bounds (explicit)

Let N = number of configured sources, F = total regular files, B = total bytes,
Fmax = files in the largest single source, FΔ/BΔ = changed files/bytes since
the base snapshot, K = retained snapshots (≤ 30 with defaults).

### 11.1 Per-run work

| Term | Bound | Source of constant |
|---|---|---|
| enumeration | `12 µs × F` + `28 µs × F` | measured, A.2 |
| materialization | `0.5 ms × F` (all files get a directory entry every run) | measured, A.4 |
| data copy | `0.5 ms × FΔ + BΔ / 1 GiB/s` | measured, A.4/A.3 |
| hashing (`on-change`) | within the data copy (no extra read) | — |
| hashing (`always`) | `2.8 ns/B` ⇒ 2.9 s per GiB (351 MiB/s) | measured, A.3 |
| index write | `135 B × F`, fsynced once | measured, A.3 |
| per-source fixed cost | ~1–2 ms × N (dir create, manifest section, fsync) | measured order of magnitude |

So per-run work is `O(F)` system calls plus `O(BΔ)` bytes, with a fixed
`O(N)` overhead. Nothing in the run is quadratic in N or F.

### 11.2 Memory

- Per source, peak = current state map + base state map =
  `2 × Fmax × 481 B` (measured deep size 481 B/entry, RSS delta 9 MiB /
  20 000 entries, A.3).
- Plus `~15 MiB` interpreter baseline, a 1 MiB copy buffer, and `O(N)` index
  sections (~0.2 KB each).
- Memory does **not** grow with F_total: sources are processed one at a time
  and each state map is dropped after its compat projection is written.
- Bound: `peak ≈ 2 × Fmax × 481 B + 15 MiB + N × 0.2 KB`. For Fmax = 20 000
  ⇒ 33 MiB; 200 000 ⇒ ≈199 MiB. Config validation warns above 500 000 files in
  one source (≈474 MiB peak); that is the designed practical ceiling, stated
  as a number rather than "bounded".

### 11.3 Disk

- Logical size of a snapshot = B (self-contained trees); total logical =
  `K × B` (misleading; see §8.4).
- Physical: unchanged bytes are shared, so
  `physical ≈ B + Σ_window BΔ + K × (index(F) + linkmeta(F))` where
  `index(F) = 135 B × F` (2.7 MB per 20 000 files) and `linkmeta(F)` measured
  at ~2 MiB per 20 000 links (0.95 GiB of data). `clonefile` costs ~77 MiB for
  that snapshot instead, which is why hardlink is the default.
- Staging transient during a run: `BΔ + O(F)` link metadata (measured +2 MiB
  for 20 000 links), *not* B, because unchanged files are linked rather than
  copied. Trash transient: `O(F)` dentries and no data bytes that are still
  referenced by a retained snapshot.
- With retention K the disk stops growing at the change rate: total growth per
  run ≤ `BΔ + FΔ × 135 B + created-snapshot metadata`, independent of how
  many runs happened before.

### 11.4 What stays flat (with the flat value)

| Quantity | Bound |
|---|---|
| open file descriptors | ≤ 8 (source dir, 2 copy fds, lock fds; closed per file) |
| threads / processes spawned | 0 (single-threaded, sequential) |
| writer locks | exactly 1 |
| per-snapshot locks held at once | ≤ 1 (retention is sequential) |
| staging dirs | ≤ 1 live per run; 0 after phase 2 |
| memory outside the two state maps | ~15 MiB interpreter + ≤13 MiB readahead/buffer (measured 28 MiB peak for a 1 MiB-chunk 1 GiB stream, A.3) |
| per-run fixed cost per source | ~1–2 ms, linear in N |

### 11.5 What grows with N

Config parse `O(N)`, index sections `O(N)` (~0.2 KB each), one directory per
source per snapshot (`K × N` directories), and the per-source fixed cost
above. No term is `O(N²)`.

---

## 12. Configuration and CLI

`backupctl.json` (JSON, no new dependency; `synccli` already depends on `json`):

```json
{
  "backup_root": "/Volumes/backups/evals",
  "sources": [
    {"path": "/Users/x/evals/results", "include_hidden_dirs": true,
     "exclude": ["**/*.tmp"]}
  ],
  "retention": {"keep_last": 7, "keep_daily": 14, "keep_weekly": 8,
                "keep_monthly": 12, "min_valid": 1,
                "trash_grace": 300, "lock_timeout": 30},
  "hash": "on-change",
  "link_mode": "hardlink",
  "durable": "file",
  "wait_seconds": 0
}
```

Validation at startup: every source exists and is a directory; no source is
inside `backup_root` (realpath containment, to avoid self-backup recursion);
`backup_root` is writable and on a filesystem that supports the configured
link mode; `keep >= 1`. `sources[].exclude` is an optional list of `fnmatch`
patterns matched against POSIX relative paths; excluded entries are recorded in
`sources[].excluded[]` with counts, are not indexed, and their absence is
therefore never mistakable for a vanished file.

CLI: `run`, `list`, `verify`, `prune`, `restore`/`export`, `reader-guard`,
`status` (lock holder, staging/trash residue). Common flags: `--config`,
`--json`, `--dry-run`, `--wait=S`, `--strict`, `--hash=…`, `--link-mode=…`,
`--durable=file|full|none`, `--include-unstable`, `--retention-now`.

Report (`--json`, stdout; human summary on stderr) contains:
`run.id`, `run.started_ns/finished_ns`, `base` (snapshot or null),
`published` (snapshot or null), `recovery[]`, `sources[]` with
`counts{files,dirs,symlinks,special,bytes,changed,linked,cloned,copied,
skipped,unstable,deleted_since_previous}`, `skipped[]`, `unstable[]`,
`fallback[]`, `retention{policy,deleted[],deferred[]}`, `discarded_staging`,
`capture_skew_seconds`, `exit`, `errors[]`. The exit code is also in the
report so a scheduler reading stdout and one reading `$?` agree.

---

## 13. Test plan

Unit:
- `scan_source_entries`: hidden-dir option, symlink recorded not followed,
  dangling symlink becomes a skip, mount-point detection, sorted output.
- state tuple: `mtime_ns`/`ctime_ns`/`ino`/`dev`/`mode` differences each
  produce "changed"; equal tuples produce "unchanged".
- `resolve_in_snapshot`: absolute path, `..` climb (including
  `../../../etc/passwd`), symlink escape, legitimate nested path.
- naming: UTC format, fixed width, same-second sequence, >99 in one second
  rejects-with-sleep path, lexicographic order == chronological order.
- index validation: truncate, wrong `format`, dangling entry, size mismatch,
  `run.id` mismatch; rebuild output and `recovered` block.
- retention selection: tiers, `keep=0` rejection, newest guard, last-valid
  guard, foreign `snap-*` never selected.

Integration (temp dirs, `unittest`, alongside `test_synccli.py`):
- first + incremental: second run reports all `link` and writes +2 MiB, not
  +1 GiB (assert `statvfs` delta and `counts.linked == files`).
- content edit preserving size and `mtime` (set mtime back with
  `os.utime`): `ctime` differs ⇒ detected (proves the ctime choice).
- file deleted before scan ⇒ absent; deleted between scan and copy
  (monkeypatched enumeration) ⇒ `skipped[phase=copy]`, snapshot published,
  exit 3, and `verify` shows no index entry for it.
- `chmod 000` file ⇒ skipped, not silently omitted (the exact `copy_file`
  defect of A.1).
- unstable file (writer thread mutating during copy) ⇒ retry then omission,
  exit 3; with `--include-unstable` present and marked.
- corrupt index: truncate `.backup/manifest.json` of the newest snapshot ⇒
  next run rebuilds it, reports, uses it as base; snapshot with a **dangling
  entry** ⇒ same, and the missing entry is never linked.
- `snap-*` junk directory ⇒ `foreign`, untouched, not a base.
- crash injection: child process SIGKILLed at each phase boundary ⇒ no
  `snap-*` created, `.stage` residue removed by the next run, exit codes as
  tabled; a truncated in-staging manifest never appears under `snap-*`.
- concurrency: two writers, one waits/exits 75 (A.4 proves flock semantics);
  reader holding `LOCK_SH` makes `prune` defer, then succeed after release;
  deleter times out ⇒ `retention.deferred` non-empty, snapshot intact.
- lock ordering: reader never waits on the writer lock (no deadlock under
  `--wait` while a reader holds a snapshot lock).
- retention: last-snapshot guard, `keep=0` rejection, trash grace, GC after
  crash, no data loss for a newer snapshot sharing inodes.
- existing regression: `python3 -m unittest` (6 tests) stays green.

Performance smoke (opt-in, skipped on slow CI):
- generate 1 GiB / 20 000 files, assert full run < 60 s and no-change run
  < 20 s on the reference-class machine; assert incremental physical growth
  < 5 % of logical.

---

## 14. Limits and non-goals (stated, not hand-waved)

- **No cross-source atomicity.** Each source's tree is captured consistently
  per file (never a mix of runs), but sources are read sequentially; skew is
  reported. Whole-volume point-in-time is out of scope (would need APFS
  snapshot integration).
- **Power-loss durability** requires `--durable=full` (`F_FULLFSYNC`,
  4.1 ms/file). Default `file` covers process death and ordered publish; a
  machine crash during the window between data fsync and rename can lose the
  unpublished staging tree only.
- **Filesystem assumptions**: `flock`, atomic `rename` within the root,
  hardlinks or `clonefile` for the fast path; FAT/exFAT/network mounts fall
  back to copying and are reported at config time. NFS requires `--lock=none`
  and loses writer mutual exclusion.
- **Immutability is a contract.** Hardlink sharing means an in-place edit of a
  snapshot path corrupts every snapshot sharing the inode. `--seal` mitigates
  but is not the default because it changes recorded modes on shared inodes.
- **Preservation scope**: contents, symlinks, mode bits, size and timestamps
  in the index. Owner/group only with root; xattrs/ACLs only with `--xattrs`;
  source hardlink topology is not preserved (each path is an independent
  inode in the snapshot); device files, FIFOs and sockets are recorded but not
  copied; mount points are not descended.
- **Single-writer model.** Concurrent *runs* are refused rather than merged.
  This is deliberate: merging two runs would have to define which run owns
  each directory-tree image, and the brief only requires that collisions not
  corrupt anything.
- **Hardlink fallback is silent to readers but not to the report**: the
  `via` field of each unchanged entry says `hardlink|clone|copy`, so a
  filesystem that cannot link is visible in every snapshot's index.
- **Retention is time-tiered by snapshot name (UTC)**, not by wall-clock
  history: if runs are missed, the tiers collapse to what exists, and the
  report says which tier a kept snapshot satisfied.

---

## Appendix A — measurement log

Raw commands were run in a scratch directory outside this repo copy
(`.../T/opencode/d1-measure`); this repo copy was only imported, never
modified.

### A.1 Ground-truth checks against the existing code

- `python3 -m unittest -v` ⇒ 6 tests OK.
- File vanished between `scan_files` and `file_state` (monkeypatched
  enumeration): `synccli.sync` raised
  `FileNotFoundError: .../src/gone.txt` — `build_manifest` (lines 28–33) has no
  error containment.
- `sync` with one `chmod 000` file: returned `copied: ['a.txt','b.txt']` and
  wrote a manifest listing `b.txt`, while `b.txt` did not exist in the
  destination (`copy_file` lines 68–69 swallow the `OSError`;
  `sync` lines 85–86 write `src_manifest` regardless). This is the
  "index promises files the snapshot does not contain" failure.
- `snaputil.safe_snapshot_path(root,'snap-1','/etc/passwd')` ⇒
  `/etc/passwd`; `'../../../etc/passwd'` ⇒
  `<root>/snap-1/../../../etc/passwd` — outside the snapshot. Docstring claim
  (lines 57–61) is false.
- `os.stat` float mtime at the 2026 epoch: `1794849632.8527977` vs
  `st_mtime_ns = 1794849632852797809` ⇒ float spacing ~477 ns.

### A.2 Enumeration and stat, 20 000 files (1 024 000 000 bytes)

- `synccli.scan_files`: 0.236 s (11.8 µs/file).
- `synccli.build_manifest` (path `os.stat`): 0.566 s (28.3 µs/file).
- custom path `os.lstat`: 0.564 s (28.2 µs/file).
- `os.scandir` + `DirEntry.stat(follow_symlinks=False)`: 0.548 s
  (27.4 µs/file).
- second measurement of the incremental metadata phase (scan + state map
  together) after cache warm: 0.535 s (26.8 µs/file); a full state map under
  APFS writeback: 1.665 s (83 µs/file) — hence the 3× cold allowance in the
  budget.

### A.3 Copy, fsync, hash, memory, deletion

- 1 GiB in one file, 1 MiB chunks: 0.241 s (4 244 MiB/s); 8 MiB chunks:
  0.369 s (2 773 MiB/s).
- 20 000 × 50 KiB copy, no fsync: 10.18 s (509 µs/file); with per-file
  `os.fsync`: 11.00 s (550 µs/file); first-run measurement under writeback:
  24.27 s.
- per-file `os.fsync` on 1 000 new 50 KiB files: 0.211 s (0.211 ms/file);
  `F_FULLFSYNC` on 200 files: 0.822 s (4.11 ms/file).
- `sha256` 1 GiB: 2.919 s (351 MiB/s); BLAKE2b: 6.911 s (148 MiB/s).
- State map of 20 000 entries: `ru_maxrss` 111 → 120 MiB (Δ 9 MiB);
  `sys.getsizeof` deep total 9.2 MiB ⇒ 481 B/entry.
- Index JSON: 2 700 000 bytes for 20 000 entries ⇒ 135 B/entry; write+fsync
  0.062 s.
- `synccli.copy_file`-style whole-file `read()` on the 1 GiB file: RSS
  9 MiB → 1 033 MiB (Δ 1 024 MiB). The streaming path in a fresh process:
  RSS 9 MiB → 28 MiB (readahead + 1 MiB buffer), a 37× smaller peak.

### A.4 Links, clones, publish, locks

- 20 000 × 50 KiB (1 024 000 000 bytes) materialization: hardlink
  9.50–9.83 s, `statvfs` Δ +2 MiB; `clonefile` 5.72–8.91 s, Δ +77 MiB; plain
  copy 10.18–14.14 s, Δ +1 026 MiB.
- `rmtree` of a 20 000-file snapshot: 1.78 s (0.089 ms/file).
- publish `os.rename` + directory `fsync`: 0.4 ms.
- `snaputil.list_snapshots` over a root containing `.stage/run-1`,
  `trash-1`, `snap-20261116-120000-00`, `snap-20261116-130000-00` returned
  exactly the two `snap-` entries.
- `flock` semantics: child `LOCK_EX|LOCK_NB` on a held lock ⇒
  `BlockingIOError [Errno 35]` (`EWOULDBLOCK`); after the holder closed its fd,
  the next child acquired it — kernel release on close/death, as relied on in
  §4.1.

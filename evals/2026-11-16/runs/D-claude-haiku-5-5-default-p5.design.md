# DESIGN-d1: `backupctl`

Status: design, no code yet. Written from `BRIEF.md` and from reading and
running the code in this directory. Every claim about existing code below was
checked by reading it or by running it; measured numbers say where they came
from.

Existing artifacts this design touches:

- `synccli.py`: `scan_files` (L10-19), `file_state` (L22-25),
  `build_manifest` (L28-33), `changed_files` (L36-42), `collect_stale`
  (L45-59), `copy_file` (L62-69), `sync` (L72-87), `main` (L90-99).
- `snaputil.py`: `list_snapshots` (L8-20), `prune_snapshots` (L23-36),
  `snapshot_disk_usage` (L39-51), `safe_snapshot_path` (L54-63),
  `is_stale` (L66-73).
- `test_synccli.py`: 6 tests, all pass (`python3 -m unittest`, 6 OK).

---

## 1. Layout

One backup root holds one independent *label* per configured directory. A
label is a subdirectory, so the existing `snaputil.list_snapshots(backup_root)`
can be called unchanged on `backup_root/<label>`:

```
<backup_root>/
  <label>/                      one per configured source directory
    .lock                       flock: serializes runs and prunes on this label
    .readers                    flock (shared): held by restores while reading
    .staging/<run-id>/          in-progress run; never read by anyone
    .trash-<snapname>/          snapshot being deleted; never read by anyone
    snap-YYYYMMDD-HHMMSS-SS/    published snapshot: complete, immutable
      MANIFEST.json             index of exactly the files in this snapshot
      <files...>                regular files; mode 0444
```

`snaputil.list_snapshots` only returns names starting with `snap-` that are
directories (`snaputil.py` L17-19), so `.staging/` and `.trash-*` are invisible
to it by construction.

Sequence number `SS`: assigned under the label lock as `max(existing SS for
the same timestamp) + 1`. Names are therefore unique even when two runs start
in the same second, and sorting by name stays chronological (fixed width).

## 2. Concurrency

Two lock types, both `fcntl.flock` on files (not lock files whose existence
means "locked"):

| Lock | Taken by | Mode | Held for |
|---|---|---|---|
| `<label>/.lock` | run, prune | EXCLUSIVE | whole run / whole prune |
| `<label>/.readers` | restore | SHARED | duration of the restore |
| `<label>/.readers` | prune | EXCLUSIVE, non-blocking | rename+rmtree of one snapshot |

Rules:

- Two runs on the same label serialize on `.lock`. The scheduler starts with
  `--wait 0`: if the lock is busy it exits with 75 (EX_TEMPFAIL) and does not
  queue behind a person's run. A person uses the default wait (up to 30 min,
  then exit 75).
- Different labels never block each other.
- A restore never takes `.lock`. It only reads published `snap-*` directories,
  which are never modified after publish. It takes `.readers` in SHARED mode.
- Prune needs `.readers` EXCLUSIVE, non-blocking. If a restore holds it,
  prune skips deletion for this label in this run and reports it. Prune never
  waits on a reader, so a long restore cannot stall a run.
- flock is released by the kernel when the process dies. A killed run or
  restore never leaves a lock that needs manual removal.

## 3. Run protocol (one label)

1. Acquire `.lock` EXCLUSIVE (policy in section 2).
2. Crash recovery (section 4): delete `.staging/*` and `.trash-*`. Holding
   `.lock` proves no live run owns them.
3. Pick the reference: the newest `snap-*` whose `MANIFEST.json` parses (section 4).
4. Create `.staging/<run-id>/`. Scan the source (section 5), decide for each
   file reuse or copy (section 6), write the new `MANIFEST.json` into staging.
5. Verify before publish: every entry in the new manifest exists in staging
   with the recorded size. Any mismatch aborts the run (no publish).
6. `fsync` each copied file and `MANIFEST.json`; `chmod 0444` each.
7. `os.rename(.staging/<run-id>, snap-<name>)`: the single publish point.
   `fsync(<label>)` after the rename.
8. Release `.lock`. Print the run report (section 7).

A snapshot exists for readers if and only if step 7 happened. Before it,
nothing under `snap-*` exists for this run, so a reader can never see a mix
of two runs or an index that names files not in the directory.

Override of `synccli.sync` (L72-87): synccli writes the destination manifest
with `open(..., "w")` directly (L85-86), after copying in place, with no
atomic publish. A kill in the middle leaves a dst tree with new files and an
old or truncated manifest. backupctl does not use `sync`. The publish is a
directory rename into a path that did not exist before.

## 4. Crash and corruption recovery

Principle: sources are the canonical data and snapshots are derived. Any
broken staging state is discarded, not repaired. The next run re-derives
everything by scanning the source.

- Dead run (`.staging/*` present, lock acquired): discard the whole staging
  directory. Nothing in it was published. Report `discarded_staging: <run-id>`.
- Dead prune (`.trash-*` present): finish the `rmtree`. It was already
  invisible to readers.
- Corrupt or half-written `MANIFEST.json` in staging: covered by the dead-run
  rule. The index is never repaired.
- Published snapshot whose `MANIFEST.json` fails to parse or fails the
  verify in step 5 (disk damage, external edit). Do not delete it
  automatically. Report `damaged_snapshot: <name>`. Exclude it from the
  reference search, so the run falls back to the next older valid snapshot,
  or to a full copy if none exists. The damaged snapshot is still counted by
  retention until it ages out, and a restore of it fails with a clear error.
- Reference unavailable (no valid snapshot): full copy. Report
  `reference: none (full copy)`.

Override of `synccli.sync` again: L77-79 `json.load` on the destination
manifest raises `JSONDecodeError` on a corrupt file. I ran this: a manifest
containing `{bad` makes `sync` raise. backupctl catches it, applies the rule
above, and reports it.

## 5. Scanning and what a file's state is

Scan: `os.walk` over the source directory, with symlinks recorded as links
(`os.lstat`, not followed). Dot-directories are included.

Override of `synccli.scan_files` (L14): `dirnames[:] = [d for d in dirnames
if not d.startswith(".")]` silently drops whole subtrees like `.git` or
`.cache`. For a backup this is silent data loss. backupctl keeps them. This
is a deliberate behavior change, and the reason is that `synccli` is a
sync tool (it mirrors what you choose to see) while backupctl is a backup tool
(it must not drop data without a report).

Per-file state key, used for "unchanged":

```
state = (st_size, st_mtime_ns, st_ctime_ns)
```

Override of `synccli.file_state` (L22-25): it uses `st_mtime` (a float, which
rounds away sub-microsecond precision) and ignores ctime. backupctl uses the
integer `_ns` fields. `ctime` is set by the kernel on every inode change and
cannot be set by `utime`, so a file restored with an old mtime (`touch -r`,
`cp -p`, `rsync -t`) still changes ctime and is caught.

Override of `synccli.build_manifest` (L28-33): no error handling. I ran it
with a `file_state` that raises `FileNotFoundError`: the exception escapes
`build_manifest` and aborts the whole sync. backupctl stats each file in a
try block, and a vanished file becomes a report entry (section 8).

## 6. Change detection and its granularity

"Unchanged" is decided per file, using the state key from section 5, compared
against the same path's entry in the reference snapshot's `MANIFEST.json`.
If equal, the file is not read: the new snapshot gets a hardlink to the
reference's copy (`os.link`). If not equal, or the path is new, the file is
copied.

Building on `synccli.changed_files` (L36-42): the comparison logic
(`rel not in old or old[rel] != state`) is reused. The key is wider, see
section 5. `changed_files` never reports deletions, and backupctl does not
need them: a file absent from the new manifest is simply absent from the new
snapshot.

Racy-timestamp rule. A file's state can match the reference even though its
content changed, when a write lands in the same timestamp tick as the
reference's recorded mtime. Rule: if `recorded_mtime_ns >= reference_start_ns
- margin`, the entry is marked `racy` in the new manifest and is never reused
(the next run copies it). `margin = 2 s`, the coarsest timestamp granularity
of supported filesystems (FAT), so the rule holds on all of them.

What the state key can still miss:

1. A write that keeps size, mtime and ctime. On a normal local filesystem a
   content write updates ctime, so this needs a racy tick (covered above) or a
   filesystem that does not maintain ctime. Those are out of scope; the
   design requires a local filesystem that updates ctime.
2. Content changes made while the copy reads the file. Covered by reading the
   state **before** the read (see section 9): the recorded state is then older
   than the content, so the next run sees a difference and copies again.
3. Changes below the filesystem's timestamp granularity that happen after the
   recorded state was taken, within the same tick. Covered by the racy rule.

Not a correctness miss, but a cost: two identical files at different paths
are both copied. There is no content hashing. A content hash of every file on
every run would read the whole tree (about 1 GB per run), which the budget in
section 10 excludes.

## 7. Snapshot integrity for readers

- `MANIFEST.json` lists exactly the files in the snapshot, with per-file size,
  state and `racy` flag. Written in staging, before publish. Verified against
  the staging directory (step 5).
- Snapshots are never modified after publish: files are `0444`, the manifest
  is written before the rename, and no code path reopens a published snapshot
  for write.
- The run report (stdout, one JSON line, and the same JSON to the run log):

```
{"label": ..., "snapshot": "snap-...", "reference": "snap-..." | "none",
 "files_total": n, "files_linked": n, "files_copied": n,
 "bytes_copied": n, "skipped_vanished": [...], "skipped_unreadable": [...],
 "changed_during_copy": [...], "racy": n,
 "discarded_staging": [...], "damaged_snapshots": [...],
 "prune_deleted": [...], "prune_skipped_busy": bool}
```

Source-vanished and source-unreadable behavior, identical for a scheduler
run and a person's run (no TTY-dependent output):

- Vanished between listing and copy (`FileNotFoundError` on open/lstat): the
  file is omitted from the new snapshot and its index entry is not written.
  It is listed in `skipped_vanished`. The reference snapshot still holds the
  last good version, so no history is lost.
- Unreadable (`PermissionError` / `OSError` on open or read): omitted from the
  snapshot, listed in `skipped_unreadable`. Same index rule as above.
- Changed while being read: the copy is kept (it is the content the reader
  got), its pre-read state is recorded, so the next run will copy it again.
  Listed in `changed_during_copy`.
- The run still publishes a snapshot, which is complete for everything it
  could read. Exit code 3 (completed with skipped sources), exit code 0 when
  nothing was skipped. A failure that prevents any publish exits 1.

Override of `synccli.copy_file` (L62-69): `except OSError: pass` (L68-69)
swallows the error, so the file vanishes with no report. I ran it with an
unreadable source: the destination has no `a.txt`, yet the manifest from
`sync` (L85-86) records `a.txt`. That is a stale-promise bug. backupctl does
not use `copy_file`. It reports every skip and never writes an index entry
for a file it did not copy.

Override of `synccli.copy_file` memory use (L66-67): `fsrc.read()` loads the
whole file into memory. backupctl copies in 1 MiB chunks (`shutil.copyfileobj`
with a fixed buffer), so memory per file is constant regardless of file size.

## 8. Retention

Policy: per label, keep the newest `K` published snapshots (`K >= 1`,
default `K = 14`). Delete the rest, oldest first.

`snaputil.prune_snapshots(backup_root, keep)` (L23-36) is reused for the
ordering and selection logic, but backupctl overrides its deletion:

- Override of L31-35 (keep=0): `keep` is not validated. With `keep=0`,
  `doomed = names[:len(names)]` deletes every snapshot. backupctl rejects
  `K < 1` at the CLI and inside the call.
- Override of L35 (`shutil.rmtree` in place): deleting a snapshot that a
  restore is reading would break it. backupctl first takes `.readers`
  EXCLUSIVE non-blocking (section 2). If that fails, it skips this label for
  this run. Then it renames `snap-X` to `.trash-snap-X` (atomic, and invisible
  to `list_snapshots`), releases the lock, and runs `rmtree` on the trash
  directory. A restore that resolved the path before the rename keeps its
  open file descriptors; a restore that resolves it after the rename gets
  ENOENT and must re-list. Restore is specified to re-list on ENOENT.
- The newest snapshot is never deleted (inherited from L33 logic).
- Prune runs only inside a run, under `.lock`, after the new snapshot is
  published. So a run that publishes a snapshot and then fails prune still
  leaves a usable state.

Retention cannot delete the only usable snapshot: a damaged snapshot (section
4) does not count toward the "usable" total, so pruning keeps the newest `K`
*valid* snapshots and deletes damaged ones older than them.

## 9. Restore-side path safety

Override of `snaputil.safe_snapshot_path` (L54-63): the docstring says any
`..` segments are "normalized away", so a stored path cannot leave its
snapshot. That is false. I ran it: `safe_snapshot_path(root, "snap-x",
"../../etc/passwd")` returns `root/snap-x/../../etc/passwd`. `os.path.normpath`
keeps leading `..` segments. backupctl's restore rejects any manifest path
that is absolute, or that after `normpath` starts with `..` or is `.`, before
joining. The function is not used for that check.

## 10. Performance budget: initial full backup of ~1 GB

Budget: **initial full backup of a 1 GB tree of ~30,000 files completes in
≤ 60 s wall-clock** on the reference machine (this development machine, APFS,
local SSD).

Measured on this machine, one run each, with the existing `synccli` code
(`build_manifest` + `sync`), tree of 30,000 files × 33 KiB = 1,013,760,000
bytes, written by the same process just before the run (so data is in the page
cache, which is optimistic):

| Step | Time |
|---|---|
| `build_manifest` (scan + stat, 30,000 files), first call | 0.77 s |
| `build_manifest`, second call | 0.79 s |
| `sync` initial (copy all 30,000 files) | 15.27 s |
| `sync` no-op (scan + manifest compare, 0 copied) | 0.86 s |

Derivation of the budget: the initial backup is dominated by copy. Measured
copy time is about 15.27 − 0.79 ≈ 14.5 s. That is ≈ 70 MB/s on warm cache, or
≈ 0.48 ms per file. The budget is set at 4× the measured cost, to cover a cold
cache and a slower disk, giving 60 s. This margin is a judgement, not a
measurement. A cold-cache run was **not** measured and must be done before the
budget is accepted.

Gate: a test (not yet written) creates the 30,000-file tree and fails if the
initial backup exceeds 60 s on the reference machine. This is the check that
turns the budget from an estimate into a result.

Note on the copy path: the 0.48 ms per file measured above is the existing
`copy_file` path (open, read whole file, write, plus a `makedirs` call per
file). backupctl's chunked copy and per-directory `makedirs` caching are
expected to be no slower, but this is not measured yet. The budget does not
depend on it being faster.

## 11. Scaling with N directories and the tree

Symbols: N = configured directories; F_d = files in directory d; F = Σ F_d;
B_d = bytes in directory d; B = Σ B_d; K = retention per label; C = bytes
changed since the reference; I = index bytes per snapshot.

| Quantity | Bound | Source of constant |
|---|---|---|
| Stat / scan work per run | Σ_d F_d stat calls ≈ 27 µs × F | measured: 0.79 s / 30,000 files |
| Copy work per run | C bytes (only changed/new files) | design (section 6) |
| Memory per run | O(max_d F_d) manifest entries; directories processed one at a time | design; the per-entry size is **not measured** |
| Index size per snapshot I_d | F_d × (path + state + flag) bytes | **not measured**; to measure with `len(json.dumps(manifest))` on the 30,000-file tree before the design is accepted |
| Disk per run, new | C + I_d (hardlinks for unchanged files cost a directory entry only) | design |
| Disk, steady state, per label | ≤ K × I_d + (distinct file versions retained) ≤ K × B_d (worst case: every file changes every run) | design |
| Disk, whole root | Σ_d (K × I_d + distinct versions of d) | design |
| Runs (lock contention) | one lock per label; labels independent | design (section 2) |

What grows with N: per-run wall time (linear in Σ F_d), total disk
(linear in Σ over labels), and the number of lock files and flock calls
(one each per label per run). What stays flat with N: memory per run
(directories are processed one at a time, so memory is O(max F_d), not
O(Σ F_d)), and the crash-recovery work (per label, only its own `.staging`
and `.trash-*`).

Worst case for disk, with N = 3 today and a few dozen later: disk grows as
N × K × B_d in the pathological "everything changes every run" case. The
common case is governed by C, which is the bytes that actually changed.

## 12. Open items (not decided in this design)

- Measure cold-cache initial backup and the index size per file (section 10,
  section 11). Both numbers are needed before the budget is accepted.
- Restore's exact CLI and its ENOENT re-list loop (section 8) are specified
  only in outline.
- Symlink targets: recorded as links, restore semantics not yet specified.
- Whether `K` should be per label or global. This design uses per label, so
  each directory's history is independent.

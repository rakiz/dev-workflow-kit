# DESIGN-d1: `backupctl`

Status: design only. No code written. Every claim about existing code was checked
by reading the file or by running it (noted inline).

## 0. Existing code, verified

Checked by reading `synccli.py`, `snaputil.py`, `test_synccli.py`, and by running
`python3 -m unittest` (6 tests pass) and small probes.

| Artifact | Behavior today | Use in backupctl |
|---|---|---|
| `synccli.scan_files` (synccli.py:9-19) | `os.walk`, skips dot-*directories*, keeps dot-files, returns sorted relative paths. | **Reuse.** Dot-dir exclusion is kept deliberately (see §6). |
| `synccli.file_state` (:22-25) | `{size, mtime}` with float `st_mtime`. | **Override.** Replace with `{size, mtime_ns, ctime_ns}` (§5). Float mtime loses ns precision. |
| `synccli.build_manifest` (:28-33) | Calls `os.stat` unguarded for every file. | **Override.** A file that vanishes after the walk raises `FileNotFoundError` and aborts the run. Must be tolerant (§4). |
| `synccli.changed_files` (:36-42) | Compares dict states; returns new or changed paths. | **Reuse the comparison logic**, but the baseline is the last *published snapshot's index*, not a `.sync_manifest.json` written into the destination. |
| `synccli.copy_file` (:45-54) | `except OSError: pass`. Opens `dst` in the same `with` after `src`. | **Override.** Probe: `chmod 000` on a source file → `sync()` returns `['a','b']`, and the next `sync()` returns `[]`. The file is recorded as synced and is never retried, despite the comment "next pass will retry". Errors must be reported, and dst must only be written after a successful read. |
| `synccli.sync` (:57-72) | Copies, then writes manifest with `json.dump` directly to the final path, non-atomically. Writes the *source* manifest even when copies failed. | **Override.** Manifest/index written last, atomically, and only listing files actually copied. |
| `synccli.collect_stale` (:75-91) | Not used by `sync`. | **Not used.** |
| `snaputil.list_snapshots` (snaputil.py:7-17) | Lists non-dot dirs starting with `snap-`, sorted. | **Reuse as-is.** Staging and trash names start with `.` so they are invisible to it. Names sort correctly because they are `snap-YYYYMMDD-HHMMSS-SS`. |
| `snaputil.prune_snapshots` (:20-35) | `shutil.rmtree` directly, no lock, no reader check. A partial rmtree leaves a `snap-*` dir that `list_snapshots` still returns. | **Override.** Deletion goes through rename-to-trash under the writer lock plus a per-snapshot reader lock (§3). Keeps the "never delete the newest" rule, which the existing code gets right. |
| `snaputil.snapshot_disk_usage` (:38-52) | Sums `st_size` over files, no inode dedupe. | **Reuse with one change:** dedupe by `(st_dev, st_ino)`. Hardlinks (§5) would otherwise be counted twice. |
| `snaputil.safe_snapshot_path` (:55-67) | Docstring says `..` cannot escape. **False.** `normpath("../../etc/passwd")` keeps the leading `..`, and `os.path.join(root, snap, "/etc/passwd")` returns `/etc/passwd`. Both verified by running it. | **Override.** Reject absolute paths and any `..` component; do not normalize them away. Restore depends on this. |
| `snaputil.is_stale` | Not needed. | Not used. |
| `test_synccli.py` | 6 tests, all happy path. No test for unreadable, vanished, interrupted, or concurrent cases. | New test suite required (§9). |

## 1. Layout

```
<backup_root>/
  .backupctl.lock          writer lock (flock, §3)
  .staging-<run_id>/       in-progress run; never read by anyone
  .trash-<id>/             snapshot being deleted; never read by anyone
  snap-20261113-101500-01/ published snapshot; immutable after publish
    index.jsonl            one line per file, sorted by path (§2)
    report.json            run outcome: omitted/unreadable/vanished files
    <dirname>/...          copied tree for each configured directory
  snap-.../.lock           per-snapshot reader lock file (created with the snapshot)
```

- `<dirname>` is the configured directory's basename. Duplicate basenames are a
  config error (rejected at startup), not renamed silently.
- Sequence number `NN` is `max(existing seq for the same timestamp second)+1`,
  allocated under the writer lock, so two runs cannot produce the same name.

## 2. Snapshot commit protocol (readers never see partial state)

1. Acquire the writer lock (§3).
2. Recover leftovers (§4.3): delete `.staging-*` and `.trash-*`.
3. Create `.staging-<run_id>/`. Copy each file to `.staging-<run_id>/<dirname>/<rel>` (§4.1, §5).
4. Write `index.jsonl` and `report.json` inside staging. `fsync` each file, then `fsync` each directory.
5. `rename(.staging-<run_id>, snap-<ts>-<seq>)`. **This rename is the only commit point.** It is atomic on one filesystem.
6. `fsync(backup_root)`. Release the lock. Run retention (§7).

A snapshot without a valid `index.jsonl` is never returned to a reader, because
staging and trash are dot-prefixed and invisible to `snaputil.list_snapshots`.
`index.jsonl` is written before the rename, so a published snapshot always
has its index. Index entries and files correspond exactly (§4.1).

Snapshot contents are write-once. Files are `chmod 0444`. Nothing writes into a
published snapshot. A restore copies out of a snapshot and never edits it in place.

## 3. Concurrency

**Writer lock.** `backupctl` takes `flock(LOCK_EX | LOCK_NB)` on `.backupctl.lock`.
If it is busy, the run exits with code 75 (EX_TEMPFAIL) and prints the holder's
run id if one is recorded. Scheduler and person get the same behavior. The
lock is released by the kernel when the process dies, so a crash never leaves a
stale lock. The lock file is never deleted.

**Reader lock.** A restore or the next run's baseline read takes `flock(LOCK_SH)`
on `snap-X/.lock`. Retention takes `flock(LOCK_EX | LOCK_NB)` on that file
before trashing it. If the lock is held, retention skips that snapshot and
reports it. Deletion therefore never races a reader.

**Deletion.** Under the writer lock: take `LOCK_EX|LOCK_NB` on the snapshot's
`.lock`, then `rename(snap-X, .trash-<id>)`, release, then `rmtree(.trash-<id>)`.
A crash between the rename and the rmtree leaves a `.trash-*` directory, which
step 2 of the next run removes. A half-deleted snapshot is never visible as
`snap-*`.

**Two runs.** Second run gets exit 75 immediately. No waiting, so a scheduler
retry loop is the caller's decision.

## 4. Failure handling

### 4.1 Source file disappears or is unreadable

Per file, during copy (replaces the walk-then-stat flow of `build_manifest` and
the swallowing of `copy_file`):

1. `stat` the path. `FileNotFoundError` → record `vanished`, skip.
2. `open(src,'rb')`. `FileNotFoundError` → `vanished`. `PermissionError` or other `OSError` → `unreadable`. Neither creates anything in staging.
3. Stream the content to `staging/<dirname>/<rel>.part`. Only on full success
   is it renamed to `<rel>`. `fstat` the open fd after reading. If `(size,
   mtime_ns, ctime_ns)` differs from the pre-read stat, the file changed during
   the copy: retry up to 2 times, then record `changing` and skip.
4. Only successful files get an index line. A failed file has no index entry
   and no file in the snapshot, so the snapshot never promises a file it does not
   contain.

`report.json` lists every omitted file with its reason. Exit code: `0` if
nothing was omitted, `3` if any file was omitted (the snapshot is still
published, because it is self-consistent and the user should keep it). The same
rule applies whether the run came from the scheduler or a person: same code
path, same report, same exit code. Per-run summary goes to stderr and the
scheduler logs the exit code.

Overrides: `synccli.build_manifest` (unguarded stat) and `synccli.copy_file`
(`except OSError: pass`, verified to mark unreadable files as synced).

### 4.2 Process dies mid-run

Anything left is in `.staging-*`, which nothing reads. The next run deletes it
(step 2, §2) and starts a full baseline-relative pass from the last *published*
snapshot. Progress is guaranteed because each run either publishes or leaves
the previous published snapshot untouched.

### 4.3 Corrupt or half-written index in a published snapshot

By construction this should not occur (index is fsynced before rename). If it
is found anyway (disk fault, manual edit):

- **Detect:** a published snapshot is *valid* only if `index.jsonl` parses
  line-by-line, every line has the required fields, and every indexed file exists
  with matching size. Checked when the snapshot is used as baseline.
- **Discard:** an invalid snapshot is **not deleted** (the user may want to
  inspect it), is excluded from baseline selection, and is listed in the run
  report as `invalid_snapshot`.
- **Re-derive:** no attempt to rebuild the index from the tree. The tree of a
  snapshot does not carry source hashes, so a re-derived index would be a
  guess about "unchanged". Instead the next run uses the newest *valid* snapshot
  as baseline, or does a full copy if none exists.
- **Report:** `invalid_snapshot` entries and the baseline chosen, in the run
  report and exit code 3.

### 4.4 Retention failure

Retention runs after publish. If it fails, the new snapshot is still
published, and the failure is reported. Retention never deletes the snapshot
just published, nor the newest valid one.

## 5. Change detection

**Unit of "unchanged": one file**, identified by relative path, compared on
`(size, mtime_ns, ctime_ns)` against the baseline index. Changes are detected per
file. Directories are not compared. Directory-level change detection would miss
file-level edits.

The baseline is the newest valid published snapshot's `index.jsonl`, not a
manifest in the destination (replaces `changed_files` / `.sync_manifest.json` use).

- If the state matches, the file is **not copied**. It is hard-linked from the
  baseline snapshot's file (safe, because published files are immutable, §2).
  Disk cost of an unchanged file is one directory entry, not its bytes.
- If it differs, or is new, it is copied from the source (§4.1).
- Hardlinks are on one filesystem, which holds because all snapshots live under
  one backup_root. If `link()` fails with `EXDEV`/`EPERM`, fall back to copying
  and report `relinked_as_copy` for that file.

**Why ctime as well as mtime:** `ctime` is set by the kernel on every metadata
change, including `touch -r`, `rsync -t` and `tar` restores that set mtime
backwards. A user cannot forge it. Adding ctime removes the main class of
misses from mtime-only checks.

**What this still misses:**

1. Content changes that alter neither size, mtime, nor ctime: only possible if
   the writer restores all three, which no normal tool does, or if writes
   land inside the same nanosecond tick on a filesystem with coarse timestamps
   (HFS+ has 1 s; APFS has ns). On coarse-timestamp volumes, same-second edits
   with equal size are missed.
2. Edits made by a process that has a file mapped and writes after the copy's
   fstat but before the next run's stat: these are caught next run, because the
   recorded state is the post-read fstat. If the write lands between the
   pre-read stat and the read, the fstat check (§4.1 step 3) catches it.

**Mitigation for the residual miss:** a full-content audit (sha256 over the
source) of a rotating 1/K slice of files per run, where K = retention depth. Over
K runs every file is hashed once. Cost is bounded by `bytes/K` per run. A
mismatch with an unchanged index entry is reported as `silent_change` and the
file is copied. This is a budget decision: it is off unless `--audit` is set.

## 6. Scope decisions

- **Dot-directories are excluded** (inherited from `scan_files`, synccli.py:14).
  Kept deliberately for the evals layout, where `.cache`-style dirs are scratch.
  A config flag `include_dot_dirs` overrides it. Dot-*files* are kept, as today.
- **Symlinks** are not followed (`os.walk` default `followlinks=False`). A symlink
  is recorded in the index as `link` with its target text and is not
  dereferenced. Not copied content-wise. Restore recreates it.
- **Hardlinked source files** are copied as independent files. Source-side
  hardlink identity is not preserved.

## 7. Retention

- Policy: keep the newest `K` published snapshots (default `K=7`, config).
  Snapshots are ordered by name (`list_snapshots`).
- Invalid snapshots (§4.3) are not counted toward K and are never deleted by
  retention.
- Deletion follows §3. A snapshot whose reader lock is held is skipped and
  retried next run.
- Safety: `K >= 1` is enforced at config load, and the newest published
  snapshot is excluded from every deletion candidate set.
- Disk bound: see §8.

## 8. Scaling (N directories, F files, B bytes total, K retained snapshots)

All numbers are formulas over these variables. Constants are from the measurement in §9.

| Quantity | Bound | Notes |
|---|---|---|
| Per-run stat calls | `F` | One stat per file (walk + state). |
| Per-run bytes read | `B_changed` (bytes that changed since baseline) | Unchanged files are hardlinked: 0 bytes read. |
| Per-run bytes written | `B_changed` | Plus index: about `F × line_size` for the new snapshot. |
| Per-run memory | `O(F)` for the in-memory baseline map (dict of path→state) | Index is read as JSONL, so the baseline can be streamed sorted-merge with `O(1)` memory: O(chunk) = 1 MiB copy buffer. Streaming is the design; the `O(F)` figure is the naive upper bound. |
| Per-run work across dirs | `Σ_i F_i` = `F` | Linear in N. No pair-wise dirs comparison. |
| Disk, retained | `≈ B + Σ_{runs in K} B_changed + K × F × line_size` | `B` is the first full backup. Worst case (everything changes every run): `(K+1) × B`. |
| Index overhead | `K × F × ~150 B` (estimate; line size not measured) | For 20k files: about 3 MB per snapshot. Measure at implementation time. |
| Number of snapshots | `K` | Independent of N. |
| Lock count | 1 writer lock + one `.lock` per snapshot | Constant in N. |

What grows with N: the walk (linear in F, and F grows with N), the index (linear in
F), and per-run stat calls. What stays flat: number of snapshots, number of
locks, retention cost per snapshot (a rename and an rmtree of one tree).

## 9. Performance budget for the initial full backup (~1 GB, ~20k files)

**Measured here** (darwin, Python 3.10.11, warm cache, this repo's code):

- Built a synthetic tree: 20,000 files, 200 directories, 50,000 bytes each,
  total 1,000,000,000 bytes.
- `synccli.build_manifest` (scan + stat): **0.63 s**.
- `synccli.sync` (scan + read + write to empty dst, full copy): **12.42 s**
  (≈ 80 MB/s). The current `copy_file` reads each file whole into memory.

**Budget:** the initial full backup of that tree must finish in **≤ 25 s** on this
machine (2 × the measured 12.42 s baseline). Derivation: the new path adds
streamed chunked copy (lower peak memory, similar throughput), per-file `fstat`,
and an fsync of each file and directory for durability. The fsync cost is not
measured, so the budget is held at 2× baseline until the implementation has a
measurement. If the fsync measurement exceeds 2× baseline, the budget is raised
only with a measured figure in the design, not by estimate.

**Acceptance gate:** a benchmark in `test_backupctl.py` that builds the same
synthetic tree and asserts the initial backup under the budget, reporting the
measured value.

## 10. Test plan (new, beyond the 6 existing tests)

1. Unreadable source: report `unreadable`, exit 3, no index entry, next run
   retries it (contrast with the verified `copy_file` behavior).
2. Source vanishes between walk and copy: `vanished`, no crash.
3. Source changes during copy: `changing` after 2 retries.
4. Kill mid-copy (SIGKILL at a fixed file count): no `snap-*` appears; next run
   removes `.staging-*` and publishes a complete snapshot.
5. Corrupt index in published snapshot: `invalid_snapshot`, not deleted, not used
   as baseline.
6. Two concurrent runs: exactly one publishes, the other exits 75.
7. Restore reading a snapshot while retention runs: retention skips the locked
   snapshot.
8. `safe_snapshot_path` override: `/etc/passwd` and `../../x` both rejected.
9. Hardlink dedupe in `snapshot_disk_usage`.
10. ctime-only change (`touch -r old new` on a changed file): detected and copied.
11. Dot-dir exclusion and `include_dot_dirs` override.

## 11. Open questions for the owner

1. Is `K=7` right for the evals workflow? It sets the disk bound in §8.
2. Is exit code 3 ("published with omissions") acceptable for the scheduler,
   or should it fail the job?
3. Is the §5 audit (`--audit`) worth its read cost, or is ctime+mtime+size
   enough for these directories?

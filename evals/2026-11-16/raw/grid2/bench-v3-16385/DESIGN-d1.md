# DESIGN-d1: `backupctl`

Status: design only. No code written. Every claim about existing code below was
checked against the files in this directory (line numbers as of this checkout)
or by a probe run in a scratch temp directory. Probe and benchmark results are
labelled **[measured]**; numbers derived from them are labelled **[derived]**;
everything else is a design decision.

Host for all measurements: macOS (darwin), Python 3.10.11, APFS on an internal
SSD, warm page cache. Cold-cache and external-disk behaviour was **not**
measured.

---

## 0. Summary

`backupctl` takes **snapshots** of N configured source directories into a
backup root. A snapshot is a directory `snap-YYYYMMDD-HHMMSS-SS/` that is
written under a staging name, fully indexed, fsynced, and then published with a
single `rename(2)`. Published snapshots are immutable. Unchanged files are
hard-linked from the newest valid earlier snapshot; only changed files are
copied. Runs and prunes are serialized by one `flock`. Readers take a per-snapshot
shared lease, and prune refuses to delete a leased snapshot. A dead run leaves
only staging directories, which the next run deletes.

The existing `synccli.py` is reused for scanning, state comparison and the
dry-run concept. Its copy and manifest-write paths are overridden, because they
are not crash-safe and they silently drop failed files (section 2 lists each
override). `snaputil.py` is reused for snapshot listing; its prune and
safe-path helpers are overridden, because they contain bugs (section 2).

---

## 1. Design

### 1.1 On-disk layout

```
<backup_root>/
  .lock                       flock target: serializes run and prune (one global lock)
  .leases/<snap-name>         flock target: readers hold SH; prune takes EX|NB
  .tmp-<run_id>/              staging for one run; NOT a snapshot (no "snap-" prefix)
  .trash-<snap-name>/         a snapshot being deleted; NOT a snapshot
  snap-20261112-150000-00/    committed snapshot, immutable after rename
    SNAPSHOT.json             index: schema, run times, per-source files, report, digest
    <source-name>/...         the copied / hard-linked tree for each configured source
```

The snapshot name format is the one `snaputil.list_snapshots` already expects
(`snaputil.py:8-20`, docstring lines 9-14): `snap-` + date + time + sequence.
Times are UTC. The sequence is a two-digit counter, the first free value within
that second.

**Name monotonicity.** The name time is `max(now_utc, newest_existing_name_time)`.
If the wall clock steps backwards, the sequence counter is bumped instead. This
guarantees that lexical order of names equals commit order, which
`list_snapshots` relies on through `sorted()` (`snaputil.py:20`).

### 1.2 Concurrency: runs, prunes, restores

| Actors | Mechanism | Outcome |
|---|---|---|
| run vs run (scheduler + person) | `flock(.lock, LOCK_EX\|LOCK_NB)` at start of `run`. If held: exit **75** (EX_TEMPFAIL) and touch nothing. | Exactly one run at a time. The scheduler retries on 75. |
| run vs restore | Restores read only committed `snap-*` directories, which are never modified. The run writes only under `.tmp-<run_id>/`. | No shared state, so no coordination needed. |
| run vs prune | Prune runs under the same `.lock`, either at the end of a successful run or via `backupctl prune`. | Serialized with runs. |
| prune vs restore | Restore takes `flock(.leases/<snap>, LOCK_SH)` **before** checking that the snapshot exists, and holds it for the whole restore. Prune takes `LOCK_EX\|LOCK_NB` on that lease before renaming the snapshot. | If a restore holds the lease, prune skips that snapshot and reports it as "in use". If prune got there first, the restore's blocking acquire returns and the existence check fails with a clear "pruned, choose another snapshot" error. |

`flock` is released by the kernel when the holding process dies. Neither `.lock`
nor a lease can go stale, so no PID files or timeouts are needed. Restore tooling
(which is out of scope here) must follow the lease protocol above; this is part
of the contract `backupctl` publishes.

### 1.3 Run protocol (commit point = one `rename`)

1. `flock(.lock, LOCK_EX|LOCK_NB)`. On failure, exit 75.
2. Delete every `.tmp-*` and `.trash-*` entry under the root. The lock is held,
   so none of them can have a live owner. Report the count as "discarded N
   incomplete runs". Nothing is resumed: the next run recomputes from the
   source tree against the last committed base.
3. Validate config. Every configured source root must exist and be a directory,
   otherwise exit **2** with nothing committed (section 1.6).
4. `run_start = time.time_ns()`. Compute the snapshot name (section 1.1).
5. `mkdir .tmp-<run_id>/`. For each source `d`, sequentially:
   a. Scan the tree (section 1.4).
   b. Load the base for `d`: the newest committed snapshot whose
      `SNAPSHOT.json` parses, has a valid digest, and contains `d` with status
      `ok` (section 1.7). Load its per-file entries for `d` only.
   c. Decide per file (section 1.5): hard-link from the base, or copy, or skip.
   d. Write `.tmp-<run_id>/<d>/...`. Drop the base and the entries for `d`
      before starting `d+1`.
6. Write `SNAPSHOT.json` into staging via temp file, `fsync`, `rename` inside
   staging. The digest covers the whole body (section 1.7).
7. `fsync` each directory in staging (the per-file fsync is done at copy time,
   section 1.8).
8. `rename(.tmp-<run_id>, snap-<name>)`. **This is the commit point.** Then
   `fsync(<backup_root>)`. If the process dies before the rename, nothing is
   visible. If it dies after the rename, the snapshot is complete. No partial
   snapshot can be observed at any point.
9. Prune (section 1.9), still under `.lock`.
10. Exit. The kernel releases `.lock`.

`--dry-run` stops after step 5a-c, prints "would link / would copy / would
skip" per file, and creates nothing. It reuses the `changed_files` logic
(`synccli.py:36-42`), which is the same idea as `synccli.sync(dry_run=True)`
(`synccli.py:81-82`).

**Clarification on "never a mix of runs."** A committed snapshot may contain
files hard-linked from an earlier snapshot. That is not a mix in the sense the
brief forbids. The requirement is that each snapshot's index describes exactly
the files that are present, and that the snapshot is immutable once committed.
Both hold: `SNAPSHOT.json` lists every entry, and a hard link has the same
content as the base file it points to.

### 1.4 Scanning

Reuses `synccli.scan_files` (`synccli.py:10-19`) with two additional keyword
arguments (section 2 explains the overrides). Behaviour required by backupctl:

- Dot-directories are **included** (override of `synccli.py:14`).
- Symlinks are recorded as entries of kind `symlink` with their target from
  `os.readlink`. Symlinked directories are recorded as symlinks and **not**
  descended into, which avoids cycles. Dangling symlinks are recorded too.
- Results are sorted (as now), so `SNAPSHOT.json` is deterministic.

Per-file state is taken with `lstat`, not `stat` (section 2, `file_state`):

```
{"kind": "file" | "symlink", "size", "mtime_ns", "ctime_ns", "ino", ["target"]}
```

`file_state` already returns `size` and `mtime` (`synccli.py:22-25`).
`mtime` is a float: at epoch 1.7e9 s, one float64 ulp is 2^-22 s, about 0.24 µs,
so two writes closer than that are indistinguishable. backupctl uses the integer
`*_ns` fields instead.

**Vanished during scan.** `lstat` raises `FileNotFoundError` between `scandir`
and `lstat`. This is caught per file and recorded as outcome `vanished`
(section 1.6). It does not abort the run.

### 1.5 Change detection: granularity and what it misses

**Granularity: one regular file, decided by its metadata.** A file is
*unchanged* if and only if the base snapshot has an entry for the same relative
path with equal `(kind, size, mtime_ns, ctime_ns, ino)`, that entry is **not
racy** (below), and the base file still exists in the base snapshot with
matching size.

Directory-level short-circuits (skip a directory whose mtime did not change) are
**not** used. A directory's mtime changes only when its entries are added or
removed, not when a file inside it is written, so such a rule would miss edits.
This is why the scan stats every file. The cost of that is measured in section 3.

The comparison reuses `synccli.changed_files` (`synccli.py:36-42`) unchanged.
backupctl passes it a base dict with racy entries removed, so racy files always
show as changed.

**Racy entries** (the "racy git" rule). A file is recorded with `racy: true` in
the snapshot if either:

- `mtime_ns >= run_start_ns - G`, where `G = 2 s` (configurable). This covers a
  second write landing in the same timestamp tick as the one we saw.
- its `lstat` after the copy differs from its `lstat` before the copy (it was
  modified while being read).

In both cases the state recorded is the pre-copy `lstat`, and `racy: true` forces
a recopy on the next run. Cost: a file touched within the last `G` seconds
may be copied twice. Nothing else is affected.

**What the granularity can still miss.**

| Miss | Why | Mitigation |
|---|---|---|
| Edit that keeps size, `mtime_ns`, `ctime_ns` and `ino` | `write(2)` and `truncate` set `ctime` as well, so an edit that changes content without updating `ctime` should be impossible on local POSIX filesystems. Not verified on every filesystem. | Metadata is the only available signal without reading content. A content hash on every run would make the run read the full tree (section 3 shows that cost). |
| Edit within one timestamp tick of the previous state | Coarse filesystem timestamps (the classic case is 1 s on HFS+; this host's APFS granularity was not measured). | Racy guard with `G = 2 s` (above). Filesystems with timestamps coarser than `G` (e.g. FAT, 2 s) are **not supported** by this design. |
| `mmap` writes that have not yet been written back | Kernel updates `mtime` lazily for mapped pages. The scan can see the old state. | The later writeback changes `mtime` and `ctime`, so the next run sees the change. Nothing is lost, only delayed by one run. |
| Edits to a file after its `lstat` and before its copy completes | Race with the copy. | Stat before and after the copy, and mark racy on mismatch (above). The snapshot then contains whatever bytes were read, and the next run re-copies it. |
| Changes to ACLs, xattrs, owner, mode | Not part of the `(size, mtime, ctime, ino)` tuple unless the mode changes `ctime`, which it does. Xattr-only changes do update `ctime`. | Changes that update `ctime` cause a recopy. ACLs and xattrs are **not backed up** (out of scope, stated in section 5). |

### 1.6 Vanish, unreadable, and skipped files

The brief requires the same behaviour whether a person or the scheduler runs
the backup. backupctl has no prompts and no tty-dependent output. Its stdout
and the `SNAPSHOT.json` report are identical in both cases.

Per-file outcomes:

| Outcome | When | Snapshot contains the file? | Recorded in report | Next run |
|---|---|---|---|---|
| `copied` / `linked` | normal | yes | no | normal |
| `racy` | modified during read, or mtime in the racy window | yes (the bytes read) | yes, flagged racy | re-copied |
| `vanished` | `lstat` or `open` returns `ENOENT`, or it disappears during the scan | **no** (omitted from index) | yes, reason `vanished` | file absent |
| `unreadable` | `open` or `read` returns `EACCES`, `EPERM` or `EIO` | **no** (omitted from index and from base entries) | yes, reason `unreadable` + errno | file is "new" again, so retried |

Rules:

- A partial copy of an unreadable file is deleted from staging before the
  next file is handled.
- A file that is omitted is **never** written into `SNAPSHOT.json`, so the index
  never promises a file the snapshot does not contain.
- A run whose only problems are `vanished` / `unreadable` / `racy` files
  **commits** a snapshot and exits **3** ("committed with skipped files"). The
  skipped list is in `SNAPSHOT.json` under `sources.<d>.skipped`, so every
  later reader can see what is missing.
- A configured source root that is missing or is not a directory makes the run
  fail with exit **2** before anything is committed. Otherwise a whole source
  could silently drop out of the snapshot sequence.
- Exit codes: `0` committed clean; `3` committed with skipped files; `1` run
  failed, nothing committed; `2` configuration error, nothing committed; `75`
  another run holds `.lock`, nothing touched.

### 1.7 Index integrity and recovery

**Index = `SNAPSHOT.json`.** Its shape:

```
{ "schema": 1,
  "run_id": "...", "run_start_ns": ..., "name": "snap-...",
  "sources": { "<d>": { "status": "ok", "files": {relpath: entry, ...},
                        "skipped": [{"path":..., "reason":..., "errno":...}] } },
  "digest": "sha256:..." }
```

`digest` is the SHA-256 of the canonical JSON of the whole object with the
`digest` key removed (`sort_keys=True`, fixed separators).

**Why a dead run cannot leave a usable-looking corrupt index.** A dead run only
ever leaves a `.tmp-*` directory. Its `SNAPSHOT.json` is never read, because
staging names are not `snap-*` and the base search never looks there. It is
deleted at the start of the next run (step 2). A committed `SNAPSHOT.json` was
fully written and fsynced before the rename (steps 6-8), so it is complete by
construction.

**Corrupt committed index** (bad JSON, digest mismatch, unknown schema, or
path entries that fail the safe-path check in section 2): this is not a dead-run
case. It is treated as follows:

- The snapshot is **not** used as a base. The base search continues to the
  next-older committed snapshot, and so on. If none is usable, the run does a
  full copy (the first-run path).
- It is **not** deleted automatically. The user decides, or retention ages it
  out (section 1.9). `backupctl list` shows it as `corrupt`, and each run prints
  a warning naming it.

### 1.8 Copying and durability

Copy path (replaces `synccli.copy_file`, section 2):

- Source opened `O_RDONLY | O_NOFOLLOW`, after `lstat` confirms it is a regular
  file, so a file swapped for a symlink mid-run cannot redirect the read.
- Data is copied in **1 MiB chunks** (`shutil.copyfileobj`, buffer size 1 MiB)
  to `.tmp-<run_id>/<d>/<relpath>`. The whole file is never held in memory.
- `fsync` on each copied file, then the file is closed. Durability of the file
  data is established before the commit rename.
- Hard links: `os.link(base_path, staging_path)`. On `EXDEV` or `EMLINK`, fall
  back to a copy.
- Symlink entries: `os.symlink(target, staging_path)`, no fsync (no data).

**Measured fsync cost [measured]:** 0.17 ms per 51 KB file, `write` + `fsync`,
2000 files. Extrapolated to 20 000 files: 3.4 s **[derived]**. Note that on
macOS `os.fsync` does not issue `F_FULLFSYNC`, so this number is not
power-loss durability. Applying `fcntl(F_FULLFSYNC)` would be slower and
was not measured. It is listed as an open item in section 5.

### 1.9 Retention and prune

**Policy:** keep the newest `K` committed snapshots (`--keep K`, default
**K = 14**, must be `>= 1`), **and** always keep the newest *valid* snapshot
(section 1.7), even if it is older than the K newest. Everything else is
eligible.

**Why `snaputil.prune_snapshots` is not used** (section 2): it deletes with
in-place `rmtree`, which breaks readers mid-restore; it ignores leases; and with
`keep=0` it deletes **every** snapshot including the newest (verified, section 2).

backupctl's prune:

1. Under `.lock`. Candidates = `snaputil.list_snapshots(root)` minus the keep
   set (oldest first).
2. For each candidate: `flock(.leases/<name>, LOCK_EX|LOCK_NB)`. If it fails,
   skip and report "in use".
3. `rename(<name>, .trash-<name>)`. From this moment no reader can reach the
   snapshot by path. Readers that already hold fds keep reading unlinked
   files, which is valid on POSIX.
4. Unlink `.leases/<name>`, then `rmtree(.trash-<name>)`. If the process dies
   during rmtree, the next run removes `.trash-*` (section 1.3 step 2).

**Safety properties.**

- Prune runs only after a run's commit, so a failed run never prunes.
- The newest valid snapshot is always kept, so the user always has a usable
  snapshot.
- Snapshots are **independent**. A hard-linked file keeps its inode alive
  until the last snapshot that links it is removed. Deleting an old snapshot
  never breaks a newer one. Every snapshot's `SNAPSHOT.json` is self-contained.
- A snapshot's hard links are immutable, so a base file can never be modified
  through a newer snapshot.

**Disk accounting.** `snaputil.snapshot_disk_usage` (`snaputil.py:50`) sums
`st_size` for each link, so hard-linked files are counted once per snapshot.
backupctl adds `snapshot_unique_bytes` to `snaputil.py`, which dedupes on
`(st_dev, st_ino)` and uses `lstat`. The reported footprint uses the unique
value. The old function stays in place, because it is part of the existing
helper surface.

---

## 2. Grounding: reuse and overrides (verified)

### 2.1 Reused as-is

| Artifact | What backupctl uses it for | Verified |
|---|---|---|
| `snaputil.list_snapshots` (`snaputil.py:8-20`) | Enumerate committed snapshots, oldest first. Staging/trash names are excluded by the `snap-` prefix test on line 18. | Yes: returns only `snap-*` directories, sorted. |
| `synccli.changed_files` (`synccli.py:36-42`) | Compare base entries with current entries. Racy entries are removed from the base dict before the call. | Yes: returns new or differing keys. |
| `synccli.scan_files` (`synccli.py:10-19`) | Base walk. Called with the keyword overrides below. | Yes: sorted relative paths. |
| `synccli.sync(dry_run=True)` concept (`synccli.py:81-82`) | Dry-run semantics. | Yes. |
| `test_synccli.py` | Existing six tests keep passing. | Yes: `python3 -m unittest`, 6 tests OK. |

### 2.2 Overridden (current behaviour, where it lives, why)

| Override | Current behaviour (file:line) | Verified how | Why backupctl differs |
|---|---|---|---|
| `scan_files` | Prunes **all dot-directories** (`synccli.py:14`). Symlinked directories are **silently dropped** (`os.walk` defaults `followlinks=False`, so they land in `dirnames` and are never listed). | Probe: `.env` included, `.git` excluded; symlink-to-dir absent from output. | Backup must include dot-directories and must record symlinks. Override via new keyword arguments, default unchanged so synccli users see no change. |
| `file_state` | `os.stat` (follows links), float `mtime` (`synccli.py:24-25`). | Code read. ulp of 2^-22 s at epoch time. | Need `lstat` and integer `mtime_ns`, `ctime_ns`, `ino`. Adds keys. Dict equality in `changed_files` still works. |
| `build_manifest` | No per-file error handling (`synccli.py:28-33`). | Probe: `file_state` on a removed file raises `FileNotFoundError`; a dangling symlink in the tree makes `build_manifest` raise. | A vanished or dangling entry must not abort the run. Per-file try/except and outcome recording. |
| `copy_file` | `fsrc.read()` loads the whole file (`synccli.py:67`). `except OSError: pass` (`synccli.py:68-69`). Writes straight to the destination path. | Probe: copy of a 400 MiB file raised max RSS by 400 MiB. Probe: unreadable source returned without error and without a file in dst. | Memory must be O(chunk). Errors must be classified and recorded. Writes must go to staging, with fsync. |
| `sync` | Loads dst manifest with bare `json.load` (`synccli.py:79`). Writes the manifest non-atomically (`synccli.py:85-86`). Writes the **full source manifest**, including files whose copy failed. | Probe: corrupt manifest raises `JSONDecodeError`. Probe: a file made unreadable (`chmod 000`) was reported as copied, its manifest entry was written, it was absent from dst, and a second run copied nothing. The `synccli.py:69` comment "next pass will retry" is false. | The failed file is never retried. A corrupt or half-written index crashes the next run. backupctl does not use `sync` at all. |
| `snaputil.prune_snapshots` | `rmtree` in place (`snaputil.py:35`). `keep` check on line 31-33. | Probe: `prune_snapshots(root, 0)` **deleted all three snapshots**, including the newest. | No leases, in-place deletion, and the `keep=0` bug. backupctl prunes by rename-to-trash under a lease, with `keep >= 1` enforced. |
| `snaputil.snapshot_disk_usage` | `st_size` per link, `os.stat` (`snaputil.py:50`). | Code read. | Hard-linked files would be double counted; dangling symlinks would raise. Adds `snapshot_unique_bytes`. |
| `snaputil.safe_snapshot_path` | Claims `..` segments are normalized away (`snaputil.py:58-60`). `normpath` on line 62, join on line 63. | Probe: `safe_snapshot_path(root, "snap-1", "../../etc/passwd")` returns `root/snap-1/../../etc/passwd` (escapes the snapshot). Probe: an absolute `rel_path` returns `/etc/passwd` (`os.path.join` discards the prefix). | Stored paths come from `SNAPSHOT.json`, which may be corrupt. backupctl rejects absolute paths and any `..` component **before** joining. The docstring is wrong and should be fixed. |
| `snaputil.is_stale` | `st_mtime <= ref_epoch` (`snaputil.py:73`). | Probe: returns `True` for a directory whose mtime equals `ref_epoch`. Docstring (lines 67-71) says it must return `False` at exactly `ref_epoch`. | Not used by the design. Listed because the docstring and code disagree; the fix is `<`. |
| `collect_stale` | Index-based loop, unused by this design. | Code read. | Not used. |

### 2.3 Test gap

`test_synccli.py` covers scanning of a plain tree, `collect_stale`, and a
noop second sync. It does **not** cover: dot-directories, symlinks, vanished or
unreadable files, a corrupt manifest, or pruning. Those are the cases this
design changes, so `test_backupctl.py` must cover each of them.

---

## 3. Performance, memory and disk bounds

### 3.1 Initial full backup budget

Fixture: 20 000 files, 51 200 B each, 200 directories of 100 files,
**1.024 GB** total [measured on this host, generated for the benchmark].

| Component | Measured | Source |
|---|---|---|
| scan + `stat` of all files | **0.47 s** | `synccli.build_manifest`, run twice, same result |
| full copy via `synccli.sync` (fresh dst) | **6.07 s**, and 5.90 s on a second cold-dst run | includes the 0.47 s scan |
| copy only (derived) | 5.6 s, about 183 MB/s | 6.07 - 0.47 |
| fsync per file | 0.17 ms per file, **3.4 s** for 20 000 files | [derived] from 2000-file probe |
| sum of components [derived] | **about 9.5 s** | 0.47 + 5.6 + 3.4 |

**Budget: the initial full backup of this ~1 GB, 20 000-file tree must finish in
≤ 60 s wall-clock on this host.** That is about 6× the derived component sum,
which leaves room for slower disks or load.

Limitations of this number: the cold-cache case, external and rotational disks,
and `F_FULLFSYNC` are not measured. The design gate is: re-run the benchmark
on the reference host with the final code, and if it exceeds 60 s, change the
fsync policy to one fsync per directory before the rename (the directory fsync
still establishes the rename's durability).

### 3.2 Per-run bounds (N directories, F_d files and B_d bytes per directory)

Let `F = Σ_d F_d` and `B = Σ_d B_d` for the configured sources. Let `Δ` be the
bytes of files that are new or changed since the base (so copied), and `C` the
number of copied files.

| Quantity | Bound | Basis |
|---|---|---|
| `lstat` calls per run | exactly `F` | every file is stat'ed; section 1.5 explains why no short-circuit |
| CPU time per run, no change | about `23.5 µs × F` + JSON parse of the base manifests | 0.47 s / 20 000 files **[measured]**; the manifest-parse term is not measured |
| bytes copied per run | exactly `Δ` (≤ `B`) | section 1.5 |
| `fsync` calls per run | exactly `C` (+ one per staging directory and one for the root) | section 1.8 |
| copy time per run | about `Δ / 183 MB/s + 0.17 ms × C` | 183 MB/s and 0.17 ms per file **[measured]** |
| memory per run | at most `2 × max_d F_d × 348 B + 1 MiB` | 348 B per in-memory entry **[measured]** for the current 3-field entry; the design adds 2 fields, so this must be re-measured. Factor 2 covers the base and the new entries of one directory. Directories are processed one at a time, so this is `max_d`, not `Σ_d`. |
| disk per run (new snapshot) | `Δ + M`, where `M` is the manifest size | hard links cost no data |
| manifest size per snapshot `M` | about `76 B × F` on disk | 1.52 MB for 20 000 entries **[measured]** with `indent=2` and the 3-field entries used in the probe; real entries are larger, re-measure |
| total retained disk | `B_first + Σ_{retained runs} Δ_i + K × M` | first full copy, then the changed bytes of each retained run, then `K` manifests |
| worst case retained disk | `K × B` | every file changes every run |
| snapshot count | `K` committed, plus at most one staging dir (plus `.trash-*` during prune) | section 1.9 |
| `flock` count | **1** global lock, plus one lease file per snapshot | section 1.2 |

### 3.3 What grows with N, and what stays flat

Growing with N (number of configured directories):

- Per-run `lstat` calls, CPU time and copy time: linear in `F` and `Δ`, that is
  in the total file count and changed bytes across all directories.
- Manifest size per snapshot `M`, and so total manifest disk `K × M`: linear in
  `F`.
- Base-manifest parses per run: one per directory, `N` total. The search for a
  base walks back from the newest snapshot until it finds a valid one that
  contains the directory. In the normal case this is one parse per directory.
  Worst case (every snapshot corrupt) is `N × K` parses, and that case is
  reported.

Flat (independent of N):

- Peak memory: `max_d F_d`, not `Σ_d F_d`, because directories are processed
  one at a time (section 1.3 step 5d).
- Lock count: always 1.
- Snapshot count `K`, and the prune cost, which is `O(K)` renames and removals per
  run.
- Staging: one directory per run.

Per-run cost that is not a constant: the copy of `Δ` bytes, which depends on
how many files changed and is unbounded in principle. A one-time 1 GB
initial copy is the worst case for `Δ` on the first run.

---

## 4. Failure matrix

| Event | State after event | Next run |
|---|---|---|
| Ctrl-C during copy | `.tmp-<id>` only | removed at start; re-copies the changed files |
| laptop sleep / power loss before rename | `.tmp-<id>` only; committed snapshots intact | removed; re-derives from the last committed base |
| kill -9 during prune rmtree | `.trash-<name>` only; the snapshot is already unreachable | `.trash-*` removed at start |
| second run starts while one runs | second run exits 75 and touches nothing | scheduler retries |
| restore reading snapshot S while run writes S+1 | no conflict (S is immutable) | n/a |
| restore holds lease on S while prune runs | prune skips S ("in use") | prune retries on the next run |
| source file vanishes during scan | omitted, report entry, exit 3 | file absent |
| source file unreadable | omitted, report entry, exit 3 | retried next run |
| source file modified during copy | included, flagged racy | re-copied next run |
| source root missing | exit 2, nothing committed | nothing changed |
| corrupt committed `SNAPSHOT.json` | not used as base; listed as corrupt; never auto-deleted | prune ages it out, or user removes it |
| `keep=0` requested | rejected, `keep >= 1` enforced | n/a |

---

## 5. Open items and limitations

- **Not backed up:** ACLs, extended attributes, owner/group, hard links inside
  the sources (copied as separate files), sparse-file holes, FIFOs and device
  nodes (recorded as skipped with reason `unsupported`). Mode and mtime are
  recorded in the index; restore decides what to apply.
- **Filesystems with coarse timestamps coarser than 2 s** (e.g. FAT) are not
  supported; the racy guard `G` would have to grow. This host's timestamp
  granularity was not measured.
- **Durability:** `os.fsync` on macOS does not flush the drive cache.
  `F_FULLFSYNC` is not measured and not used; its cost must be measured before
  claiming power-loss durability.
- **Cold-cache and external-disk timing:** not measured. The 60 s budget (section 3.1)
  is conditional on the reference host.
- **Memory of the final entry format** (`ino`, `ctime_ns` added): the 348 B per
  entry figure is for the current 3-field entry and must be re-measured.
- **Cross-platform:** the design uses `flock`, `O_NOFOLLOW` and hard links,
  all POSIX-only. Windows is out of scope.
- **Restore tooling** is separate. It must follow the lease protocol in
  section 1.2, and it must use the fixed safe-path check (section 2.2), not
  `snaputil.safe_snapshot_path` as it stands.
- **snaputil fixes** (outside this design's scope, to be decided by the owner):
  `safe_snapshot_path` (`snaputil.py:54-63`), `is_stale` comparison
  (`snaputil.py:73`), and `prune_snapshots` `keep=0` (`snaputil.py:31-33`).
  Per the brief's ask-before-acting rule, none of these is changed here.

# DESIGN-d1 — `backupctl`

Status: proposal. Scope: the backup tool described in `BRIEF.md`. It lives
next to `synccli.py` / `test_synccli.py` and builds on them.

All numbers marked **[measured]** come from runs I did on this repo copy
(Apple M3 Max, 36 GiB RAM, macOS 15.8.1, APFS internal SSD, Python 3.10.11,
page cache warm). The method is in Appendix A, so anyone can run it again.

---

## 1. Summary

`backupctl` stores each configured directory as a series of **immutable
snapshots** in a **content-addressed object store**:

```
<backup_root>/
  ROOT.lock                      flock: runs take SHARED, the object sweep takes EXCLUSIVE
  locks/<dir>.lock               flock: one writer per configured directory
  objects/ab/abcdef…(sha256)     file contents, write-once, named by their hash
  snapshots/<dir>/<snap-id>.json the index: one write-once manifest per snapshot
  tmp/<run-id>/                  staging for one run (partial objects, partial manifest)
  trash/                         manifests being deleted by retention
  quarantine/<dir>/              corrupt manifests found by a run (kept, never read)
  reports/<run-id>.json          per-run report (same content as --json stdout)
```

A snapshot exists only if `snapshots/<dir>/<snap-id>.json` exists. That file
appears through one atomic `os.replace` **after** every object it names has
been written, fsynced and renamed into `objects/`. A reader therefore sees a
whole snapshot or no snapshot. It never sees one that is half-built. Unchanged
files are found with `synccli.scan_files` + `synccli.changed_files` against
the previous manifest. They cost one `stat` and no bytes copied. Concurrency
uses kernel `flock` locks, which the kernel releases when a process dies. A
killed run therefore leaves no stale lock, only a `tmp/<run-id>/` directory
that the next run removes.

Budget for the first full backup of a 1 GiB / 30,000-file tree: **≤ 40 s**.
The prototype measured **19.5–20.5 s**. `synccli.sync` takes **17.3 s** on the
same tree (§9).

---

## 2. What the existing code gives us, and where it falls short

I read `synccli.py` and ran it against the failure modes in the brief
(Appendix A.3 has the script). Findings, by function:

| Function (synccli.py) | What it does | Used by backupctl? | Gap found (verified) |
|---|---|---|---|
| `scan_files(root)` L10–19 | `os.walk`, drops dot-directories (L14), returns sorted relative paths | **Yes, reused** (with 2 backward-compatible parameters, §8) | `os.walk` uses `onerror=None` (L13), so an **unreadable subdirectory disappears silently**. Verified: a `chmod 0` dir `locked/` is missing from the listing and nothing reports it. Dot-*directories* are skipped. Dot-*files* are kept (verified: `.dot` listed, `.hid/h` not). Symlinked dirs are not followed (`os.walk` default). |
| `file_state(path)` L22–25 | `{"size", "mtime"}` from `os.stat`, float mtime | **Yes, extended** (§8) | Raises `FileNotFoundError` if the file vanished. Float `st_mtime`. Does not see a restored mtime (`touch -r`, `cp -p`, `rsync -t`). |
| `build_manifest(root)` L28–33 | `{rel: file_state}` for the whole tree | **No, replaced** by `backupctl.build_states` | One file vanishing between `scan_files` and `file_state` raises out of the loop (L32), so the whole directory fails. Verified: `FileNotFoundError`. |
| `changed_files(old, new)` L36–42 | Paths that are new or whose state dict differs (`!=`, L40) | **Yes, reused as-is** | Does not report deletions. backupctl doesn't need that, because each manifest is rebuilt from the new scan. |
| `collect_stale(items, seen)` L45–59 | Filters `(path, fresh)` tuples | **No** (no use for it in this design) | — |
| `copy_file(src, dst)` L62–69 | `makedirs`, reads the **whole file into memory** (L67), writes **in place** at `dst`, **swallows `OSError`** (L68–69) | **No, replaced** by `backupctl.put_object` | (1) Peak memory equals the file size: 5.5 MB for a 5.5 MB file [measured]. (2) An in-place write lets a reader see a truncated file and lets a crash leave a torn one. (3) The L69 comment says "next pass will retry", but **it doesn't**. Verified: the file is unreadable, `sync` returns it as copied and lists it in the manifest, and after `chmod` fixes it a second `sync` copies **nothing**. `chmod` changes ctime, not `(size, mtime)`. |
| `sync(src, dst)` L72–87 | Manifest at `dst/.sync_manifest.json` (L7, L75). Loads it (L77–79), copies the changed files, rewrites the manifest | **No, replaced** by `backupctl.run_dir` | (1) A corrupt manifest raises `json.JSONDecodeError` on **every** later run (verified), so it never makes progress without manual cleanup. (2) The manifest write (L85–86) is non-atomic `open("w")`, so a crash leaves a truncated index. (3) It writes `src_manifest` from *before* the copies, so the index promises files whose copy failed (see `copy_file`). (4) It overwrites one mirror in place, so readers see a mix of two runs. |
| `main` L90–99 | argparse, `--dry-run` | Pattern reused (`backupctl run --dry-run` = `changed_files` without writing) | — |

backupctl therefore **reuses** `scan_files`, `file_state` and `changed_files`.
It **overrides** `build_manifest`, `copy_file` and `sync`, for the reasons in
the table. It does not change the behaviour `synccli` users depend on (§8).

---

## 3. Configuration and CLI

`backupctl.json`. JSON, because Python 3.10 has no `tomllib`:

```json
{
  "backup_root": "/Volumes/backup/evals",
  "dirs": { "evals-a": "/path/evals/a", "evals-b": "/path/evals/b" },
  "skip_hidden_dirs": true,
  "lock_timeout_s": 600,
  "retention": { "keep_last": 10, "daily": 14, "weekly": 8, "monthly": 12 }
}
```

The keys of `dirs` are stable names. Renaming a source path keeps its history.
A renamed key starts a new history.

```
backupctl run     [--config F] [--dir NAME ...] [--dry-run] [--json]
backupctl list    [--dir NAME]                    # snapshots, status, error counts
backupctl restore NAME DEST [--snapshot ID] [--path REL ...]
backupctl prune   [--dry-run]                     # retention + object sweep only
backupctl verify  [--deep]                        # check manifests; --deep re-hashes objects
backupctl bench   --tree DIR                      # re-runs the §9 measurement on this host
```

**Exit codes are the same for the scheduler and for a person.** No flag and
no TTY detection changes them:

| code | meaning |
|---|---|
| 0 | every directory committed a `complete` snapshot |
| 1 | every directory committed a snapshot, but with warnings: vanished files, quarantined index, retention deferred because a snapshot is in use, sweep deferred |
| 2 | at least one snapshot is `partial` (files that exist but could not be read, §6) |
| 3 | at least one directory committed **no** snapshot this run (busy past `lock_timeout_s`, source root missing, I/O error on the backup root) |
| 4 | fatal: bad config, backup root unusable |
| 130 | interrupted (SIGINT/SIGTERM). Directories committed before the signal stay committed. |

Every run prints a short summary to stderr and writes `reports/<run-id>.json`.
`--json` sends the same document to stdout.

---

## 4. Data model

### 4.1 Objects

`objects/<h[0:2]>/<h>`, where `h` is the sha256 hex of the content. Objects
are written once, mode 0444, and never modified. Two runs that write the same
content produce the same name, and `os.replace` of identical content is
idempotent. Identical files across directories and snapshots are stored once.
A reader can check any object by re-hashing it.

### 4.2 Manifest (the "index")

`snapshots/<dir>/<snap-id>.json`. `snap-id = <UTC yyyymmddThhmmssZ>-<6 hex
run suffix>` is assigned at commit time. It is guaranteed to sort after the
base snapshot's id (bumped by one second if the clock went backwards). As a
result, "newest" equals "lexicographically largest".

```json
{
  "format": "backupctl-manifest/1",
  "dir": "evals-a", "source": "/path/evals/a",
  "snapshot_id": "20261112T215400Z-3fa9c1", "base": "20261111T215400Z-0b12aa",
  "started_at": "...", "finished_at": "...",
  "status": "complete",
  "files":   { "run001/sub0/f.bin": { "state": {"size":…, "mtime":…, "mtime_ns":…, "ctime_ns":…, "ino":…, "mode":…},
                                       "obj": "ab12…", "racy": false } },
  "vanished": ["run007/tmp.log"],
  "errors":   [ { "path": "run009/locked.bin", "errno": 13, "error": "EACCES" },
                { "path": "skipped-dir/", "errno": 13, "error": "EACCES (directory not listed)" } ],
  "stats":    { "files": 30000, "changed": 300, "bytes_copied": …, "new_objects": … },
  "checksum": "sha256 of the canonical JSON (sort_keys, compact) of every other field"
}
```

`status` is `complete` exactly when `errors` is empty.

There is **no mutable index**: no "latest" pointer and no catalog file. Every
index-level fact is derived by listing `snapshots/<dir>/`. A dead run
therefore cannot leave a half-updated catalog, because none exists.

### 4.3 Invariants

- **I1 (publish order):** a manifest appears in `snapshots/` only after every
  object it names is in `objects/`, fsynced and renamed. For entries reused
  from the base, the object's presence is checked with `os.path.exists`:
  2.4 µs per object, 0.07 s for 30k [measured].
- **I2 (no premature deletion):** an object is deleted only by the sweep. The
  sweep runs under `ROOT.lock` EXCLUSIVE, so no run is in flight, and it
  deletes only objects that no manifest in `snapshots/` references.
- **I3 (manifests are write-once):** they are only created by `os.replace`
  and removed by retention (§7). They are never edited in place.
- **I4:** `objects/` holds only complete objects. A partial object exists only
  as `tmp/<run-id>/obj.part`.

Together, I1–I4 answer the brief's "never an index that promises files the
snapshot does not contain". The limit is damage from outside the tool (disk
errors, manual deletion), which `verify` reports and §5.4 recovers from.

---

## 5. The run

### 5.1 Steps for one run

```
run_id = utc + random suffix
mkdir tmp/<run_id>/, flock(tmp/<run_id>/.lock, EX)          # marks this staging dir as "owned by a live process"
flock(ROOT.lock, SH)                                         # blocks only while a sweep holds EX (seconds)
cleanup_abandoned_staging()                                  # §5.4
for name in configured dirs (free ones first, busy ones re-tried until lock_timeout_s):
    flock(locks/<name>.lock, EX)                             # one writer per directory; write {run_id, pid, host, since} into it
    run_dir(name)                                            # §5.2; commits one snapshot or reports why not
    apply_retention(name)                                    # §7.1, only if run_dir committed
    unlock
unlock ROOT; try flock(ROOT.lock, EX|NB) -> sweep (§7.2), else note "sweep deferred"
rmtree(tmp/<run_id>); write report; exit code (§3)
```

Directories are processed **one at a time** inside a run. That keeps memory
independent of N (§10). Two runs started together split the directories
between them, because each takes the directories that are free first. A run
that finds a directory busy waits for it. Once the other run commits, this
run's pass over that directory is a cheap incremental one: 3.3 s for 30k
unchanged files [measured]. Either way, when a run exits 0 or 1, every
directory has a committed snapshot that started no earlier than that run did.

### 5.2 `run_dir(name)`: one directory, one snapshot

1. **Base.** Load the newest *valid* manifest in `snapshots/<name>/` (§5.4)
   and take `flock(SH)` on it for the duration, so retention can't remove it
   under us. No valid manifest means `base = {}`.
2. **List.** `synccli.scan_files(src, onerror=record, skip_hidden_dirs=cfg)`.
   A directory that can't be listed goes into `errors`, which makes the
   snapshot `partial`. Today that loss is silent (§2).
3. **Stat.** `build_states`: for each `rel`, call
   `synccli.file_state(path, extended=True)` (§8). `FileNotFoundError` /
   `NotADirectoryError` means the file vanished and goes to `vanished`. Any
   other `OSError` goes to `errors`. Unlike `build_manifest` (L28–33), the
   loop never aborts.
4. **Diff.** `changed = synccli.changed_files({r: e["state"] for r, e in base.items()}, states)`.
   This reuses L36–42 unchanged. Its `!=` on the dicts (L40) compares every
   extended field. A file with `racy: true` in the base is added to `changed`
   (§6.2). So is a file whose base object is missing (I1).
5. **Copy.** For each changed file, `put_object` (replaces `copy_file`
   L62–69):
   - Open the source. Stream in 1 MiB chunks into `tmp/<run_id>/obj.part`,
     updating sha256 as it goes. Memory is constant 1 MiB, against L67's
     whole-file read.
   - `fstat` the open fd after the read. If `size` / `mtime_ns` differ from
     step 3, the file changed during the copy: retry, up to 3 attempts. If it
     is still changing, it goes into `errors` as `"unstable"`.
   - `os.fsync(obj.part)`. If `objects/<h>` exists, delete `obj.part` (dedup).
     Otherwise `os.replace` it into `objects/<h[:2]>/<h>`.
   - `OSError` on open/read: `ENOENT` goes to `vanished` and anything else to
     `errors`. **Never swallowed** (L68–69 is the behaviour overridden).
     Either way, the file is **not** in `files`.
6. **Unchanged files** reuse the base entry `{state, obj}`. No bytes are read.
7. **Commit.** Write the manifest (with checksum) to `tmp/<run_id>/manifest.json.part`,
   `flush`, then one `F_FULLFSYNC` on macOS (`fsync` on Linux), then
   `os.replace` into `snapshots/<name>/<snap-id>.json`, then fsync that
   directory. The single `F_FULLFSYNC` acts as a device-cache barrier for all
   the per-object `fsync`s before it. Per-object `F_FULLFSYNC` would cost
   5 ms/file: 10.2 s for 2,000 files against 0.5 s with `fsync`
   [measured]. That is ~150 s for 30k files, so it is rejected.

`--dry-run` stops after step 4 and prints `changed`, the same contract as
synccli's `--dry-run` (L81–82).

### 5.3 What "point in time" means here

Without filesystem snapshots, which would need privileges on APFS (`tmutil`),
no tool can freeze a live source tree. What backupctl guarantees:

- (a) Each file's bytes are one consistent read of that file (the step-5
  `fstat` check).
- (b) Every file in a snapshot comes from **this** run, or is byte-identical
  to the base by the §6 rule. A snapshot never mixes runs.
- (c) The manifest records `started_at` / `finished_at`.

The source can still change across files during the window, as it can with
any non-snapshotting copier. That is stated, not hidden.

### 5.4 Crashes, interruption and index recovery

The process can die between any two system calls. What it leaves behind, and
what the next run does:

| Died during | Left behind | Next run |
|---|---|---|
| anything | `tmp/<dead-run>/` (partial `obj.part`, maybe `manifest.json.part`). Locks are **not** left: the kernel drops `flock` on exit. | `cleanup_abandoned_staging`: for each `tmp/*`, try `flock(.lock, EX\|NB)`. If it succeeds, the owner is dead, so `rmtree` it and report `"removed abandoned staging of run X (started T, k bytes)"`. A live run's staging is skipped, because its lock is held. A laptop that slept keeps its lock, so its staging is safe. |
| step 5 after `os.replace` of some objects | complete objects in `objects/` that no manifest references yet | Reused by dedup if the next run needs that content. Otherwise the sweep removes them (§7.2). Harmless either way. |
| step 7 before `os.replace` | no new manifest | Readers never saw anything. The next run's base is the previous snapshot, and it copies only what is still missing from `objects/`. |
| retention, between rename-to-trash and unlink | `trash/<file>` | Emptied at the start of the next run. Its objects become garbage for the sweep. |
| sweep | some unreferenced objects deleted, others not | The sweep is idempotent. The next sweep finishes the job. |

`SIGINT` / `SIGTERM` handler: stop at the next file boundary, `rmtree` own
staging, release locks, report the directories that committed, exit 130.
`SIGKILL` and power loss are covered by the table.

**Corrupt or half-written index.** A dead *process* cannot leave a half-written
published manifest (§5.2 step 7). A half-written one exists only as
`manifest.json.part` in staging, and the cleanup above deletes it. A *published*
manifest can still be damaged by power loss on a device that ignores barriers,
by disk errors, or by a hand edit. Loading follows these rules:

- **Validate.** It must parse as JSON. `format` must be known. `checksum` must
  match. `files` must map to `{state, obj}` with `obj` a 64-hex string.
- **Discard.** A manifest that fails is moved (`os.replace`) to
  `quarantine/<dir>/<snap-id>.json`, not deleted, so a person can inspect it.
  It stops being a snapshot: not listed, not a base, not a retention
  candidate, and not part of the sweep's live set.
- **Re-derive.** The run moves to the next-newest *valid* manifest as its
  base. If none is valid, the base is `{}`. Every source file is then re-read
  and re-hashed. The object store is kept: content already present is not
  rewritten. The cost is `a·F + b·B` of reads and hashing, with writes only
  for content that is actually new. Nothing else needs re-deriving, because
  there is no catalog (§4.2).
- **Report.** Warning line plus a `quarantined` entry in the report:
  `"index: quarantined snapshots/evals-a/X.json (checksum mismatch); base = Y; 30000 files re-hashed, 12 new objects"`.
  Exit code at least 1.
- **Clean up.** Quarantined files older than 30 days are deleted by `prune`.

A corrupt **object** (re-hash mismatch, found by `restore` or `verify --deep`)
is moved to `quarantine/objects/`. The next run then finds the base object
missing (step 4) and copies the file again if the source still has it.
`verify` lists the snapshots that refer to the lost object.

---

## 6. Change detection: granularity and what it misses

### 6.1 Granularity

The unit is **the whole file**. A file counts as unchanged when its extended
state is equal to the base entry, compared by `changed_files` L40:
`(size, mtime, mtime_ns, ctime_ns, ino, mode)`. Two more conditions apply:
its base object must still exist, and the base entry must not be marked
`racy`. Any difference re-reads and re-hashes the **whole file**. If the
content turns out identical, no new object is written (dedup). If it
differs, the whole new version is stored. There is no block-level delta: a
1-byte change to a 5 MB file stores 5 MB more.

Compared with synccli's `(size, mtime)` (L24–25), backupctl adds `ctime_ns`
and `ino`. That closes synccli's verified miss: a file that was fixed with
`chmod` was never recopied. It also catches tools that restore mtime
(`touch -r`, `cp -p`, `rsync -t`, `tar x`): user space cannot set ctime, and
atomic-save editors change the inode.

### 6.2 Edits this granularity can still miss

1. **Same-tick races on coarse timestamps.** Suppose a file is modified again
   in the same timestamp tick as our `stat`, with the same size. On APFS and
   ext4 the tick is 1 ns, but FAT uses 2 s, HFS+ 1 s, and some NFS/SMB
   mounts 1 s. Mitigation, the same as git's "racy" rule: if
   `mtime_ns ≥ stat_time − 2 s`, the entry is written with `racy: true`, and
   the next run treats it as changed.
2. **Writes through a shared `mmap`** whose mtime update the kernel delays
   until `msync`/`munmap`. Missed until the mtime moves, then picked up on the
   next run.
3. **Content changes without any metadata change**: raw block-device writes,
   filesystem bugs, bit rot in the *source*. Not detected, by design.
   Detecting them would mean re-hashing every byte on every run
   (`b·B` ≈ 1.4 s/GiB plus the I/O).
4. **Clock / ctime manipulation** (changing the system clock to forge ctime).
   Out of scope.

The opposite error, re-reading files that didn't change, comes from `chmod`,
`chown`, new hardlinks, and filesystems with unstable inode numbers (some
FUSE/SMB). It costs read and hash time, not disk, because of dedup.

---

## 7. Retention and deletion

### 7.1 Policy, per directory

Apply the rules to that directory's valid snapshots, sorted by id. A snapshot
is **kept** if any rule selects it:

- the newest `keep_last` (10);
- the newest snapshot of each UTC day, for the last `daily` (14) days;
- the newest of each ISO week, for the last `weekly` (8) weeks;
- the newest of each month, for the last `monthly` (12) months;
- **always: the newest `complete` snapshot**, however old. The newest
  snapshots may all be `partial` if one file has been unreadable for weeks,
  and this keeps a fully consistent image anyway.

Everything else is a deletion candidate. Upper bound on retained snapshots per
directory: `S_max = 10 + 14 + 8 + 12 + 1 = 45`.

**Safety rules:**

- Retention for `<dir>` runs only in a run that holds `locks/<dir>.lock` and
  has just **committed** a snapshot of `<dir>`. A failing directory is never
  pruned.
- The snapshot just committed is always among the `keep_last`.
- Deletion therefore can never take a directory down to zero snapshots, or
  remove its newest complete one.

**Deleting one manifest** (reader-safe):

1. `fd = open(manifest, O_RDONLY)`, then `flock(fd, EX|NB)`. If that fails, a
   reader holds it SHARED: skip it and report
   `"retention: 1 snapshot kept, in use"` (exit ≥ 1). The next run retries.
2. Holding EX: `os.replace(manifest, trash/…)`, which removes it from listings
   atomically. Then fsync the directory, `unlink`, close.

Objects are never deleted here. That is the sweep's job.

### 7.2 Object sweep (mark and sweep)

Runs only under `flock(ROOT.lock, EX|NB)`. When that is held, no run is
staging objects that no manifest references yet. It is attempted at the end
of a run when a marker `needs_sweep` exists (set by any deletion), and by
`backupctl prune`.

- **Mark:** stream every manifest in `snapshots/*/` and collect the `obj`
  hashes. A reader's snapshot is in that set by construction: it is still
  listed, because its SH lock blocks deletion.
- **Sweep:** walk `objects/` and unlink anything not in the set.

Quarantined manifests are not in the live set. Partitioning keeps memory
bounded (§10): pass `p` of `P` marks and sweeps only hashes whose first hex
digit falls in partition `p`.

### 7.3 Reader protocol (restore, `list`, any tool)

backupctl exports `open_snapshot(root, dir, snap_id=None)`. The `restore`
subcommand and any external restore tooling must use it:

1. List `snapshots/<dir>/` and pick the id. Open it, then `flock(fd, SH)`.
   This waits only while a deletion holds EX, which is milliseconds.
2. Check `os.stat(path).st_ino == os.fstat(fd).st_ino`. If the path is gone
   or is a different inode, retention deleted it in between: go back to
   step 1 (pick again, or fail if a specific id was requested).
3. Validate the manifest (§5.4). Read objects and verify each sha256 while
   streaming. Hold the SH lock until done.

Holding SH on a listed manifest blocks its deletion (§7.1). Its objects are
then in the sweep's live set. The sweep also never runs during a backup run.
A reader can therefore never lose an object it is about to read. A reader
that skips the protocol, such as a person running `cat` on
`objects/ab/…`, has no protection. `restore` and `list` are the supported
human interface.

The protocol needs `flock` to work on the backup root. That holds for local
APFS / ext4 / HFS+. `run` refuses to start on network filesystems where it
is known to be unreliable (`statfs` type `nfs`/`smbfs`) and exits 4.

---

## 8. Changes to `synccli.py` (backward compatible)

Two parameters with defaults that keep today's behaviour. The existing 6 tests
in `test_synccli.py` keep passing unchanged, and new tests cover the new
parameters.

1. `scan_files(root, onerror=None, skip_hidden_dirs=True)` (L10). Passes
   `onerror` to `os.walk` (L13) and makes the L14 filter conditional. Reason:
   backupctl must report unreadable directories, which today are silently
   lost, and must let a config back up dot-directories.
2. `file_state(path, extended=False)` (L22). With `extended=True` it adds
   `mtime_ns`, `ctime_ns`, `ino` and `mode` from the **same** `os.stat` call.
   The default output stays `{"size", "mtime"}`, so existing
   `.sync_manifest.json` files still compare equal through `changed_files`
   and no synccli user triggers a full recopy.

Not changed in synccli, though the analysis found them: the swallowed
`OSError` and false "next pass will retry" in `copy_file` (L68–69), and the
non-atomic manifest write and corrupt-manifest crash in `sync` (L77–86).
backupctl avoids these through its own `put_object` and commit path. Fixing
them in `synccli` itself is a separate change that needs separate approval.

New file `backupctl.py` (CLI + `run_dir`, `build_states`, `put_object`,
`open_snapshot`, retention, sweep) and `test_backupctl.py`, both run with
`python3 -m unittest`.

---

## 9. Performance budget for the first full backup

### 9.1 Budget

**Initial full backup of a 1 GiB / 30,000-file tree: ≤ 40 s wall-clock** on
the reference machine above. Model for other trees and hosts:

```
T_full ≈ a·F + b·B           a = 0.47 ms/file,  b = 1.36 s/GiB      (reference machine)
budget = 2 × T_measured                                              (headroom: cold cache, background load)
```

### 9.2 Where the numbers come from [measured, Appendix A]

| Measurement (30,000 files, 1,073,726,846 B, lognormal sizes, max 5.5 MB, 300 dirs) | Time |
|---|---|
| `synccli.scan_files` | 0.42 s |
| `synccli.build_manifest` (scan + 30k `stat`) | 2.0–2.7 s |
| `synccli.sync`, first full (baseline: no hash, no fsync, in-place) | 17.3 s |
| `synccli.sync`, no-op second run | 1.4–2.8 s |
| **backupctl prototype, first full** (scan, extended stat, streamed copy + sha256 + `fsync` per object + rename, one `F_FULLFSYNC` on the manifest, atomic publish) | **19.5 s, 20.5 s** (2 runs) |
| same, without per-object `fsync` | 18.8 s |
| prototype, no-op incremental | 3.3 s |
| prototype, 1 % (300 files) changed | 3.34 s |
| sha256 throughput (single core) | 1,770 MB/s |
| per-file constant `a`: 30,000 × 1-byte files, first full | 14.2 s ⇒ **0.47 ms/file** |
| per-byte constant `b`: 128 × 8 MiB files (1 GiB), first full | 1.36 s ⇒ **1.36 s/GiB** |

Model check: `0.47 ms × 30,000 + 1.36 s × 1.0 = 15.5 s` against 20 s
measured. The model underestimates the mixed tree by about 25%, so the
budget is set from the measured 20 s and not the model: 2 × 20 s = **40 s**.

The cost is per-file, not per-byte. 14 of the 20 s are fixed per-file costs
(open/create/rename and directory updates). Hashing a full GiB costs only
0.6 s. A "first backup is slow because of hashing" worry is unfounded on this
hardware.

Hash, `fsync` and atomic rename together cost **+13–18 %** over the existing
unsafe `synccli.sync` (20 s against 17.3 s).

### 9.3 Not measured (stated as such)

- **Cold page cache.** `purge` needs root, so it wasn't run. Derivation: the
  extra cost is the source read time, about 1 GiB at the SSD's sequential
  rate plus about 30k random small reads. On an internal NVMe that is a few
  seconds, which the 2× headroom covers.
- **Spinning or USB backup targets.** They change `a` and `b` and must be
  re-measured with `backupctl bench`. The command reports `a`, `b` and the
  derived budget for the host.

### 9.4 Rejected because of measurements

- **Hardlink-farm snapshots** (`rsync --link-dest` style, browsable trees):
  re-linking 30k unchanged files took **13.3 s per run** (dirs pre-created,
  2 runs), and deleting such a snapshot took **3.6 s**. The CAS no-op run
  takes **3.3 s**. Every incremental run would also do O(files) metadata
  writes, against O(changed files) here.
- **Per-object `F_FULLFSYNC`:** 5 ms/file (above).

---

## 10. Scaling: explicit bounds

Notation:

| Symbol | Meaning |
|---|---|
| N | configured directories |
| F_i | files in directory i |
| B_i | bytes in directory i |
| C_i | files changed since the base |
| ΔB_i | bytes in the changed files |
| S_i ≤ 45 | retained snapshots of directory i (§7.1) |
| U | unique live objects across the whole root |

Constants measured on the reference machine:

| Constant | Value | Source |
|---|---|---|
| t_s | 0.11 ms/file | scan + extended stat + reuse (no-op run, 3.3 s / 30k) |
| a | 0.47 ms/file | per changed file |
| b | 1.36 s/GiB | per changed byte |
| m | 227 B | manifest bytes per file entry (6.82 MB / 30k) |
| r | 1.04 KB | peak run memory per file of the current directory (31.2 MB / 30k, tracemalloc) |
| h | 210 B | live-set bytes per object (4.54 MB / 21,630 objects, `sys.getsizeof`) |

The live-set figure comes from the prototype store: the 30k-file tree
deduplicated to 21,630 unique objects, and their live set measured 4.54 MB.

| Quantity | Bound | Grows with |
|---|---|---|
| **Per-run time** | `Σ_i (t_s·F_i + a·C_i + b·ΔB_i) + T_ret + T_sweep`. Example: 30 dirs × 30k files at 1 % churn ≈ 30 × 3.34 s ≈ **100 s**. A first full run of 30 dirs × 1 GiB ≈ 30 × 20 s ≈ **10 min**. | linear in N and in total files. Bytes only through changes. |
| **Retention time** `T_ret` | ≤ number of deletions × (1 open + flock + rename + unlink): milliseconds each, at most ~1 per dir per day in steady state | N |
| **Sweep time** `T_sweep` | `P × Σ_i S_i × (43 ms × F_i / 30k)` to load manifests (load of one 30k-entry manifest: 43 ms) **+** one walk of `objects/` (~2.4 µs × U). Runs only when a deletion happened. Worst case 30 dirs × 45 × 30k ≈ 58 s per pass. | N·S·F |
| **Peak memory of a run** | `r × max_i F_i + 1 MiB copy buffer + interpreter` ≈ 31 MB + 1 MiB for a 30k-file directory. **Independent of N** (directories are processed one at a time). Independent of file size (streamed, against L67's whole-file read). | the largest single directory |
| **Peak memory of the sweep** | `h × U / P`. P is chosen as `ceil(h × U / 64 MiB)`, so **≤ 64 MiB** (and P ≤ 16 because P splits on the first hex digit; past that, U > 5.1 M objects, the cap rises to `h × U / 16`). | U (all directories). The only memory term that grows with N, and it is capped. |
| **Disk: objects** | `Σ_i ( B_i,unique + Σ_{retained s} ΔB_i,s )`: the first full copy plus every retained changed version, deduplicated across directories and snapshots. Measured: 1,027,812 KiB on disk for the 1 GiB tree (21,630 unique objects). | bytes of churn × retention |
| **Disk: manifests** | `m × Σ_i F_i × S_i` ≤ 227 B × F × 45 per directory, i.e. ≤ **307 MB** for a 30k-file directory at full retention | N·F·S |
| **Disk: staging** | per active run ≤ largest single file (one `obj.part` at a time) + `m × F_i` (manifest) | — |
| **Disk: reports / locks** | `reports/` ≈ O(N + errors) per run, removed by `prune` after 90 days. `locks/`: N+1 files of < 200 B. | N |
| **Stays constant** | the per-file costs t_s, a, b, m; the copy buffer (1 MiB); snapshots per directory (≤ 45) | — |

Root-wide *growth* is bounded by retention: in steady state, objects ≤ the
live data plus up to 45 retained versions of churn per directory. "Only ever
grows" applies between prunes.

---

## 11. Vanished and unreadable source files

The policy is the same for the scheduler and for a person. Two cases differ:

| Case | Detected at | In the snapshot | Reported | Status / exit |
|---|---|---|---|---|
| **Vanished**: `ENOENT`/`ENOTDIR` between listing and stat, or between stat and open | `build_states`, `put_object` | **absent** (the snapshot reflects the tree without it, which is true by then) | listed under `vanished` (path), with a count in the summary | stays `complete`; exit 1 (warning) |
| **Unreadable**: `EACCES`, `EIO`, `EPERM`, or still changing after 3 copy attempts | `build_states`, `put_object`, `scan_files(onerror)` for directories | **absent**. The previous version is **not** carried forward, because that would mix runs (§5.3b). | `errors` (path, errno). The summary prints each one. | `partial`; exit 2. Retention keeps the newest `complete` snapshot no matter what (§7.1). |

`restore` of a `partial` snapshot restores what it contains and prints the
`errors` list first. To get those files, restore the same paths from an
earlier snapshot (`--snapshot`, `--path`). That is an explicit human
decision, not silent mixing.

Regression guard against synccli's verified bug: an unreadable file is never
listed in `files`. Because it isn't there, the next run sees it as new and
copies it once it becomes readable again (a test covers this, §12).

---

## 12. Test plan (`test_backupctl.py`, `python3 -m unittest`)

**Unit tests**

- New `scan_files` parameters: unreadable directory reaches `onerror`;
  `skip_hidden_dirs=False` lists `.hid/h`.
- `file_state(extended=True)` keys; `extended=False` output unchanged.

**Run semantics**

- First run copies all files. A second run copies none (mirrors
  `test_second_sync_is_noop`). `touch -r` and `chmod` are detected.
- A file vanishes between scan and stat (monkeypatched `scan_files`, as in
  Appendix A.3): `vanished`, `complete`, exit 1.
- Unreadable file: `partial`, exit 2, not in `files`. After `chmod`, the next
  run copies it. This is the regression test for `copy_file` L68–69.
- A file growing during the copy ends up as `unstable`.

**Fault injection** (environment hook `BACKUPCTL_FAULT=<step>:<n>` raising
`SIGKILL` on itself at named steps 5.2.1–5.2.7, 7.1, 7.2, in a subprocess)

- For every step: no new manifest unless the step is past commit, and
  `verify` passes.
- The next run exits ≤ 1, removes the staging, and reaches the same final
  state as an uninterrupted run.

**Corrupt index**

- A truncated, checksum-mismatched, or schema-invalid manifest is
  quarantined. The base falls back correctly. The report and the exit code
  say so.
- With all manifests corrupt, the run re-derives from the tree and writes no
  duplicate objects.

**Concurrency** (multiprocessing)

- Two runs at once: both exit ≤ 1, and each directory gets 1–2 valid
  snapshots.
- A reader holding SH during `prune`: the snapshot survives and the reader
  reads every object. A reader racing a deletion retries via the inode check.
- A run and a sweep: the sweep is deferred while the run holds SH.

**Retention**

- Property test over random snapshot histories and statuses: never 0
  retained, the newest complete always retained, ≤ 45 retained.

**Budget** (`bench`, opt-in, not in the default suite)

- Generates the Appendix A tree and fails if the first full run exceeds the
  §9 budget.

---

## 13. Rollout

1. `synccli.py`: the two parameters (§8) plus tests. No behaviour change for
   synccli.
2. `backupctl.py`: `run`, `list`, `restore`, `verify`. The retention policy
   is configured but only reports (`prune --dry-run`), until it has run for a
   week alongside the existing workflow.
3. Retention and sweep enabled. The scheduler (launchd/cron) calls
   `backupctl run --json`. Exit codes ≥ 2 alert, 1 is logged.
4. Later, not needed for the brief: on APFS with source and backup root on
   the same volume, `clonefile()` in `put_object` would turn copies into
   copy-on-write clones.

---

## Appendix A: how the numbers were produced

Scripts lived outside the repo copy, in the session temp dir. They have been
reduced to their essentials here so they can be re-run.

**A.1 Tree.** 30,000 files, sizes `lognormvariate(9.5, 1.5)` rescaled to a
total of 2^30 bytes (largest 5.49 MB), contents from an 8 MiB random blob
prefix. Equal-size files are therefore identical: 21,630 unique objects. The
layout is `run%03d/sub{0,1,2}/f%05d.bin` (300 × 3 dirs). Each step was timed
with `time.perf_counter` around a direct call (`synccli.scan_files(src)`,
`synccli.build_manifest(src)`, `synccli.sync(src, dst)`). Memory came from
`tracemalloc` peak around the call.

**A.2 Prototype run** (the code path whose time is the budget):

```python
rels = synccli.scan_files(src)
states = {r: state(os.path.join(src, r)) for r in rels}        # os.stat → size, mtime, mtime_ns, ctime_ns, ino
changed = set(synccli.changed_files({r: e["state"] for r, e in old.items()}, states))
for r in rels:  # changed → stream 1 MiB chunks into tmp + sha256, os.fsync, os.replace into objects/h[:2]/h (unlink if exists)
    files[r] = {"state": states[r], "obj": put_object(...)} if r in changed else old[r]
json.dump({"files": files}, tmp_manifest); fcntl.fcntl(fd, fcntl.F_FULLFSYNC); os.replace(tmp_manifest, snapshots/d/<id>.json)
```

Constants `a` and `b` came from the same code on 30,000 × 1-byte files and on
128 × 8 MiB files. The fsync comparison copied the same 2,000 files (76 MB)
three ways: no sync, `os.fsync`, and `fcntl F_FULLFSYNC`. The hardlink
alternative ran `os.link` for every file into a pre-created directory tree,
then `shutil.rmtree`.

**A.3 synccli behaviour checks.** These produced the findings in §2:

```python
# unreadable source: sync() reports it copied and lists it in the manifest, file absent;
# after chmod 0644 a second sync() returns [] (never retried)
# corrupt manifest '{"ok.txt": {"si' → sync() raises JSONDecodeError
# scan_files patched to list a nonexistent "gone.txt" → build_manifest raises FileNotFoundError
# chmod 0 subdirectory "locked/" → scan_files omits locked/f, no error
# ".hid/h" omitted, ".dot" kept
```

`python3 -m unittest` on the unmodified repo: 6 tests, OK.

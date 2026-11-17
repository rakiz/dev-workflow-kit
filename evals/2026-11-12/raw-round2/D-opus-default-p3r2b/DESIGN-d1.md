# DESIGN-d1 — `backupctl`

Status: design, no code yet. Target file: `backupctl.py`, next to
`synccli.py` and `snaputil.py`. It ships in the same repo and imports both.

Line numbers below refer to the files in this directory as they are today.
Every behavioral claim about the existing code was checked by running it
(§10 lists the probes); every number was measured or derived from
measurements on this machine (§7).

---

## 1. Summary of the approach

* **One repository per configured directory**:
  `<backup_root>/<name>/`. Each configured directory is processed on its own,
  under its own lock, with its own snapshots, retention and object store.
  N directories means N independent repositories.
* **Content-addressed object store + one immutable index per snapshot.**
  File contents are stored once in `objects/<aa>/<sha256>`. A snapshot is a
  directory `snap-YYYYMMDD-HHMMSS-NNNNNN/` holding a single file
  `index.json.gz`, which maps every relative path to its stat key and object
  hash. A snapshot is a complete image *by definition of its index*.
* **Commit = one atomic `rename(2)`** of a fully written, fsynced snapshot
  directory from `staging/` into the repository. Nothing named `snap-*` ever
  exists in a partial state.
* **Change detection per file** on the key
  `(size, mtime_ns, ctime_ns, ino, dev)`, compared with the previous
  snapshot's index through the existing `synccli.changed_files`. Unchanged
  files cost one `lstat` and zero bytes of I/O.
* **Concurrency by `flock(2)`**: an exclusive per-repository writer lock for
  runs/prune/GC, and per-snapshot shared *leases* for readers. Kernel locks
  vanish with the process, so a killed run never leaves a stale lock.

The alternative I measured and rejected — an rsync `--link-dest`-style
hard-link tree per snapshot — is discussed in §7.4: on this machine (APFS)
`link(2)` costs ~330 µs, so an *unchanged* 30k-file directory still takes
~10 s per run with link trees vs 0.19 s with the index design.

---

## 2. What exists today and how `backupctl` uses it

`synccli.sync` (`synccli.py:72-87`) already has the skeleton backupctl needs:
*scan → load previous manifest → diff → copy changed → write manifest*.
`backupctl` keeps that skeleton and replaces each step that is unsafe for
backups. The table is the full grounding map; each override is explained in
the section named in the last column.

| Existing artifact | What it does today (verified) | backupctl use | § |
|---|---|---|---|
| `synccli.MANIFEST_NAME` (`synccli.py:7`) | manifest stored *inside* the destination tree | **not used**: the index lives in the snapshot dir, outside the content namespace, so no source file can collide with it | 3 |
| `synccli.scan_files` (`synccli.py:10-19`) | `os.walk`, drops every dir starting with `.` (line 14), symlinks-to-dirs silently vanish (walk does not follow them, they are not in `filenames`), unreadable dirs silently ignored (`onerror=None`), `os.path.relpath` per file | **contract reused** (sorted list of `/`-relative paths), **implementation overridden** by `scan_tree` | 4.1 |
| `synccli.file_state` (`synccli.py:22-25`) | `{"size", "mtime"}` with float `st_mtime`; separate `os.stat` after the listing | **overridden** by the stat key from the same `lstat` the scan already did | 4.1, 5 |
| `synccli.build_manifest` (`synccli.py:28-33`) | `scan_files` then `file_state` per file; a file deleted between the two raises `FileNotFoundError` and aborts the whole run | **overridden** (the scan returns the stat in one pass; no second stat) | 4.1, 6.1 |
| `synccli.changed_files` (`synccli.py:36-42`) | returns paths new in, or whose state differs from, the old manifest (dict equality) | **reused unchanged**, fed with backupctl's stat-key dicts | 5 |
| `synccli.copy_file` (`synccli.py:62-69`) | truncating in-place write, whole file read into memory, `OSError` swallowed (`pass`) | **overridden** by `store_object` | 4.2, 6.1 |
| `synccli.sync` (`synccli.py:72-87`) | writes `src_manifest` (line 86) even for files whose copy failed; non-atomic manifest write; `json.load` of a half-written manifest raises forever | **skeleton reused, every step overridden as named here** | 4, 6 |
| `synccli.collect_stale` (`synccli.py:45-59`) | unrelated helper (and needs a sequence despite the "iterable" docstring) | **not used** | — |
| `snaputil.list_snapshots` (`snaputil.py:8-20`) | `snap-*` directories directly under a root, sorted by *name* | **reused** for discovery, followed by validation and a re-sort by numeric `seq` | 3.2, 8 |
| `snaputil.prune_snapshots` (`snaputil.py:23-36`) | count-based, in-place `shutil.rmtree` | **overridden** by `apply_retention` | 8 |
| `snaputil.snapshot_disk_usage` (`snaputil.py:39-51`) | sum of `st_size` of files in a snapshot dir | **reused** to report the on-disk size of a snapshot's index (the only file in a snapshot dir); content size comes from the index | 7.5 |
| `snaputil.safe_snapshot_path` (`snaputil.py:54-63`) | claims to keep paths inside the snapshot; does not | **not used**; replaced by `check_relpath` | 9 |
| `snaputil.is_stale` (`snaputil.py:66-73`) | dir-mtime ≤ ref | **not used**; ages come from the index header | 8 |

Defects found in the existing code (all reproduced, §10). `backupctl` must not
inherit them; it does **not** modify `synccli.py`/`snaputil.py` (their tests
stay green, `python3 -m unittest` → 6 tests OK). Fixing them in place is a
separate decision for the owner.

1. `copy_file` swallows `OSError` (`synccli.py:68-69`) and `sync` then records
   the file in the manifest (`synccli.py:85-86`). The comment "next pass will
   retry" is false: on the next run, after the permission was fixed,
   `sync` copied `[]` and the file was still missing from the destination.
2. A truncated `.sync_manifest.json` makes every later `sync` raise
   `JSONDecodeError` (`synccli.py:79`): no self-recovery.
3. `build_manifest` raises `FileNotFoundError` when a file vanishes between
   `scan_files` and `file_state`.
4. `scan_files` silently skips hidden directories (e.g. `.cache/`) and
   symlinked directories.
5. `(size, mtime)` misses a same-size edit whose mtime was restored
   (`os.utime`, `cp -p`, `tar x`, `rsync -t`): reproduced, the destination
   kept the old bytes; `ctime` did change.
6. Deleted source files are never removed from the destination.
7. `copy_file` truncates the destination first: a crash mid-copy leaves a
   short file with no marker.
8. `safe_snapshot_path("/b","snap-1","../../etc/passwd")` →
   `/b/snap-1/../../etc/passwd`; `"/etc/passwd"` → `/etc/passwd`.
   `normpath` keeps leading `..`, and `os.path.join` discards the prefix for
   absolute paths.
9. `list_snapshots` sorts names lexicographically: `...-100` sorts before
   `...-99`, and a leftover `snap-…-01.partial` directory is listed as a
   snapshot.
10. `prune_snapshots(root, 0)` deletes every snapshot, partials included,
    contradicting "the newest snapshot is never deleted"; `keep=-1` also
    deletes everything. It counts partial dirs as snapshots, so with
    `keep=1` it can keep a partial and delete the last good one. `rmtree` in
    place races readers.
11. `is_stale` returns `True` at exactly `ref_epoch` (`<=`, line 73) although
    its docstring says "not stale". Directory mtime also changes whenever
    entries are added or removed, so it is not an age anyway.
12. `snapshot_disk_usage` raises if a file disappears during the walk
    (concurrent prune) and counts shared (hard-linked) bytes once per
    snapshot. A 1000-byte file linked into two snapshots reports 1000 + 1000.

---

## 3. On-disk layout

```
<backup_root>/
  backupctl.json                      # optional copy of config (informational)
  <name>/                             # one repository per configured directory
    lock                              # writer lock (flock LOCK_EX); content = holder info
    objects/00..ff/<sha256>           # immutable file contents, mode 0444
    snap-20261113-104500-000042/      # committed snapshot (immutable)
      index.json.gz
    staging/<snap-name>/              # in-progress run (never named snap-* at repo level)
      tmp/<n>                         # object being written
      index.json.gz                   # written last
    leases/<snap-name>.lock           # reader leases (flock LOCK_SH)
    trash/<snap-name>/                # pruned, awaiting deletion
    quarantine/<snap-name>/           # committed snapshot whose index failed validation
    runs/<run-id>.json                # run reports (bounded, §7.5)
```

Every bookkeeping directory name avoids the `snap-` prefix, so
`snaputil.list_snapshots(<backup_root>/<name>)` (`snaputil.py:16-19`) sees
committed snapshots only. The `.partial`/staging trap from defect 9 is
structurally excluded.

### 3.1 Index format (`index.json.gz`)

```json
{"format": 1,
 "header": {"repo": "evals-results", "source": "/abs/path", "seq": 42,
            "run_id": "20261113T104500Z-4f2c", "trigger": "scheduler",
            "started_at": "...Z", "completed_at": "...Z",
            "base": "snap-20261113-090000-000041",
            "entry_count": 30000, "entries_sha256": "<hex>",
            "summary": {"files": 30000, "bytes": 1067051796, "copied": 300,
                        "vanished": 0, "unreadable": 0, "unstable": 0}},
 "entries": [
   ["run000/case00/f0.json", "f", {"size":..,"mtime_ns":..,"ctime_ns":..,"ino":..,"dev":..},
    "rw-r--r--", "<sha256>", "ok"],
   ["logs/locked.txt", "f", null, "rw-------", null, "unreadable:EACCES"],
   ["latest", "l", null, null, "run000", "ok"],
   ["empty_dir", "d", null, "rwxr-xr-x", null, "ok"]
 ]}
```

* Entries are sorted by path (the `scan_files` contract, `synccli.py:19`).
* `entries_sha256` = SHA-256 of the canonical (`separators=(",",":")`) JSON
  of `entries`. Combined with gzip's CRC32 and length trailer, a truncated or
  bit-flipped index fails validation.
* A stat key of `null` means "do not trust as a change-detection baseline".
  It is used for unreadable, unstable and racy entries (§5, §6.1).
* Measured size: 4.57 MB raw / **1.78 MB gzipped for 30,000 entries
  (≈ 59 B/entry)**. gzip costs 0.10 s; decompress + parse costs 0.02 s.

### 3.2 Snapshot names and ordering

`snap-<UTC YYYYMMDD-HHMMSS>-<seq:06d>`. `seq` = 1 + the highest seq found in
`snap-*`, `quarantine/*` and `trash/*` under the writer lock. The name keeps
the format `list_snapshots` documents (`snaputil.py:11-13`). The authority for
"newest" is the **numeric `header.seq`**, not the name sort that
`list_snapshots` returns. This overrides that ordering (defect 9) because
names are wrong when the seq passes its width or the wall clock steps back.

### 3.3 Config

`backupctl.json` (path via `--config`, default `./backupctl.json`):

```json
{"backup_root": "/Volumes/backup/evals",
 "directories": {"evals-results": "evals/results", "evals-runs": "evals/runs"},
 "exclude": ["**/__pycache__"],
 "retention": {"keep_last": 7, "keep_daily": 14, "shrink_guard": 0.5},
 "lock_wait_seconds": 0}
```

Names match `[A-Za-z0-9_-]{1,64}`. If `backup_root` resolves inside a source
directory, it is auto-excluded from that source's scan. `backup_root` must be
a local filesystem (flock semantics, §6.2); `backupctl` refuses NFS/SMB
(`statfs` type check) unless `--allow-remote-root` is given.

---

## 4. A run, step by step

`backupctl run [--only NAME…] [--wait SEC] [--trigger scheduler|manual]`
processes the configured directories **sequentially** (memory bound, §7.5).
For each repository:

1. **Lock.** `flock(lock, LOCK_EX | LOCK_NB)`; with `--wait`, retry until the
   deadline. If the lock is busy, the result is `skipped-busy` and the report
   includes the holder info read from `lock`. Then the run moves to the next
   directory.
2. **Recover** (§6.3): delete `staging/*` and `trash/*`, both of which belong
   to dead runs because we hold the lock. If anything was deleted, set
   `needs_gc`.
3. **Discover and validate**: `snaputil.list_snapshots(repo)`, validate each
   index header + checksum (§6.3), quarantine failures, and sort the valid
   ones by `seq`. **Base** = the newest valid snapshot. Its object references
   are checked by one `stat` per object (≈5 µs each). An entry whose object
   is missing drops out of the baseline (it will be re-read), and the run
   reports it.
4. **Source check**: if the configured source path is missing or not a
   directory, the result is `source-missing`, **no snapshot is committed** and
   nothing is pruned. An empty snapshot of an unmounted volume must never
   look like "everything was deleted".
5. **Scan** (`scan_tree`, §4.1) → `{rel: entry}` with stat keys.
6. **Diff**: `synccli.changed_files(old_keys, new_keys)` (`synccli.py:36-42`,
   unchanged). `old_keys` = `{rel: key}` from the base index for entries with
   a non-null key **and** an existing object; `new_keys` = keys from the scan.
   The result is the set to read. Everything else carries the base entry's
   hash forward.
7. **Store** each changed file with `store_object` (§4.2) into
   `staging/<snap>/tmp/` → `objects/`.
8. **Write the index** to `staging/<snap>/index.json.gz`. Then `fsync` it,
   issue the durability barrier (§6.4), `rename(staging/<snap>, <snap>)`, and
   `fsync(repo dir)`. **This rename is the commit point.**
9. **Retention + GC** (§8), only if step 8 committed.
10. **Report**: append this directory's result to the run report.
11. **Unlock** (also implicit on exit or crash).

### 4.1 `scan_tree` — overrides `synccli.scan_files` + `file_state` + `build_manifest`

Iterative `os.scandir` walk, with `DirEntry.stat(follow_symlinks=False)`
taken once per entry. Paths are built by string concatenation.

Differences from `scan_files` (`synccli.py:10-19`), each deliberate:

* **Hidden directories are included** (line 14 drops them). Silently not
  backing up `.something/` is data loss. Exclusion is explicit via config
  `exclude` and is counted in the report.
* **Symlinks** are recorded as `l` entries with their target, never followed.
  Today symlinked dirs vanish from the listing (reproduced), and symlinked
  files are followed by `os.stat` in `file_state`.
* **Unreadable directory** (`PermissionError` from `scandir`): recorded as a
  `d` entry with status `unreadable:<errno>` and reported as an error. Today
  `os.walk` hides it.
* **Special files** (fifo, socket, device) are skipped and counted as
  `skipped-special` (warning).
* **No `os.path.relpath`.** Profiling `build_manifest` on the 30k-file tree:
  2.57 s total, of which **1.73 s is `posix.getcwd`** called twice per file
  by `relpath` (line 17). `scan_tree` takes **0.15–0.18 s** for the same tree.
* **No second `stat`**: `build_manifest`'s separate `file_state` call
  (`synccli.py:32`) is where a vanished file crashes the whole run (defect 3).
* Stat key = `size, st_mtime_ns, st_ctime_ns, st_ino, st_dev`, as ints
  instead of `file_state`'s float `st_mtime` (`synccli.py:25`). §5 explains
  why.

### 4.2 `store_object` — overrides `synccli.copy_file`

```
fd = open(src, O_RDONLY | O_NOFOLLOW)             # ENOENT → vanished; other errno → unreadable
before = fstat(fd)                                  # must still be a regular file
out = open(staging/tmp/<n>, O_WRONLY|O_CREAT|O_EXCL, 0o444)
loop: buf = read(fd, 1 MiB); sha.update(buf); write(out, buf)
fsync(out); close(out)
after = fstat(fd)
if key(before) != key(after): retry (max 3), then keep last copy, status "unstable", key := null
h = sha.hexdigest()
if exists(objects/h[:2]/h): unlink(tmp)            # dedup (content already stored)
else: rename(tmp, objects/h[:2]/h)                 # object appears whole or not at all
```

Differences from `copy_file` (`synccli.py:62-69`):

* **Errors are classified and recorded**, not swallowed (line 69): the index
  never claims a file it does not hold (§6.1).
* **Temp + rename** instead of truncate-in-place (line 66): a dead run leaves
  only `staging/` debris, never a short object under a real name.
* **Streaming 1 MiB buffer** instead of `fsrc.read()` (line 67): memory per
  copy is 1 MiB, not the size of the largest file.
* **`fstat` before/after on the same fd**, so the recorded key describes the
  bytes actually read.
* **No `utime`/`chmod` per stored file**: mode and mtime live in the index,
  and restore applies them. Measured on this machine, `utime` costs 150 µs
  and `chmod` 68 µs per file, together ≈ 6.5 s per 30k files.

---

## 5. Change detection: granularity and what it misses

**Granularity: one file.** For each file, "unchanged" means its key
`(size, mtime_ns, ctime_ns, ino, dev)` equals the key recorded in the base
snapshot for the same path. The diff itself is
`synccli.changed_files` (`synccli.py:36-42`), unchanged: its dict-equality
test is exactly what we need once the state dicts carry the richer key.
Storage granularity is also a whole file: a changed file is re-read and
stored entirely if its SHA-256 is new. Identical content (renames, copies,
reverted edits) is deduplicated by hash, so it costs a read but no bytes.

Why this key instead of `file_state`'s `(size, mtime)`:

* `ctime` cannot be set from userland. It catches the mtime-restoring edits
  that `(size, mtime)` misses (defect 5, reproduced).
* `ino`/`dev` catch the atomic-replace pattern (write temp, rename over) even
  when size and times collide.
* Integer nanoseconds avoid float rounding on `st_mtime`.

**Racy-clean rule** (as in git's index): if a file's `mtime_ns` or `ctime_ns`
is within 2 s of the moment it was `fstat`ed, its key is stored as `null`. A
write in the same timestamp tick right after our read would otherwise be
invisible next time. The 2 s window covers 1 s (HFS+) and 2 s (FAT)
granularity. The next run re-reads those files: cost is a read + hash, and
dedup avoids new bytes.

**What this granularity can still miss** (stated, not hidden):

1. An edit that keeps size, mtime **and** ctime identical. That requires
   setting the system clock back to the exact previous ctime, or a
   filesystem without a real ctime (some FUSE/network mounts, FAT) combined
   with an mtime-restoring same-size edit.
2. Writes through `mmap` whose mtime update the OS has not yet applied when
   we scan. The next run catches them once mtime moves.
3. Content corruption without a metadata change (bit rot, raw block-device
   writes), both in the source and in `objects/`. The stat check cannot see
   these. `backupctl verify NAME [SNAP]` re-hashes objects (2.7 GB/s SHA-256
   measured, so ~0.4 s CPU per GB plus read time) and is the only detector.
4. Sub-file changes are not deltas: appending 1 byte to a 3 MB file stores
   3 MB again.

---

## 6. Correctness under concurrency, crashes and a moving source

### 6.1 Vanishing and unreadable source files

Behavior is identical regardless of trigger. `--trigger` is informational
only and appears in the report and header. There is no TTY detection and no
interactive prompt.

| Situation | Snapshot contains | Index | Report / exit |
|---|---|---|---|
| Vanished between listing and `open` (`ENOENT`/`ENOTDIR`) | nothing for that path | no entry | `vanished: [paths]`, **warning**, exit 0 |
| Vanished after `open` | the complete bytes read through the open fd | normal entry | nothing special |
| Unreadable (`EACCES`, `EPERM`, `EIO`, `ELOOP`, …) | **no content** for that path | entry with `hash=null`, `status="unreadable:<errno>"`, key `null` | `unreadable: [path, errno, last_good_snapshot]`, **error**, exit 2 |
| Changed during copy after 3 attempts | last copy | entry with hash, `status="unstable"`, key `null` | `unstable: [paths]`, **warning**, exit 0 |
| Directory unreadable | nothing below it | `d` entry `unreadable:<errno>` | error, exit 2 |

Design points:

* **No carry-forward of old content for an unreadable file.** Silently
  putting the previous run's bytes into this snapshot would be exactly the
  "mix of this run and the previous one" the brief forbids. Instead, the
  report names `last_good_snapshot` (the newest valid snapshot whose entry
  has a hash), so a human knows where the last good copy is.
* The index records the unreadable path with no hash. Restore therefore knows
  the file existed, and the index never promises content it does not hold.
* A `null` key means the next run re-reads the file automatically. This fixes
  defect 1's false "next pass will retry".
* An unreadable file does **not** block the commit. The other 29,999 files
  are worth a snapshot.

### 6.2 Concurrent runs, restores and prunes

Locks are `fcntl.flock`, which the kernel releases when the process dies.
There are no pid files and no stale-lock heuristics.

* **Run vs run (same repository)**: `lock` with `LOCK_EX`. The second run
  either skips (`lock_wait_seconds: 0`, the default for both triggers) or
  waits up to `--wait`. It never writes concurrently, so staging, seq
  allocation, object renames, prune and GC are single-writer by construction.
  Runs on **different** repositories proceed in parallel.
* **Run vs reader**: a run only ever (a) creates new files in
  `staging/`, (b) renames complete objects into `objects/` (an existing
  object is never rewritten, since its name is its content hash), and (c)
  renames a complete snapshot in. Committed snapshots and objects are never
  modified. A reader of snapshot S therefore cannot observe a run writing
  S+1.
* **Prune/GC vs reader — the lease protocol** (implemented by
  `backupctl.open_snapshot()` and used by `backupctl restore`; external
  restore tools must use it):
  1. Reader: pick snapshot S, `flock(leases/S.lock, LOCK_SH)`, **then**
     check that `S/` still exists and validate its index. If S is gone,
     release and pick again.
  2. Pruner (holding the writer lock):
     `flock(leases/S.lock, LOCK_EX | LOCK_NB)`. If that fails, S is in use:
     defer and report. Otherwise `rename(S, trash/S)`, release, delete the
     lease file, and later `rmtree(trash/S)`.
  3. GC deletes only objects referenced by **no** snapshot still under
     `snap-*`. A leased snapshot can never have been moved, so its objects
     are always live.

  Ordering: the reader locks *before* it checks existence, and the pruner
  renames only *while* holding the exclusive lease. So either the reader
  sees S and S cannot be pruned until release, or the reader finds S gone.
* **Readers that ignore the protocol** (a human running `zcat` + copying
  objects by hand) are not protected against deletion. Because objects are
  immutable and content-addressed, they can get `ENOENT` but never wrong
  bytes, and an already-open object stays readable after `unlink`. This
  limitation is documented, not engineered away.
* **Quarantine vs reader**: quarantining also takes the exclusive lease
  non-blocking. If S is leased, it stays in place (excluded as base) and GC
  is skipped for that run, because a corrupt index has an unknown object set.

### 6.3 Crash at any point: what is left and how the next run proceeds

| Crash point | State left | Next run (under lock) |
|---|---|---|
| Before lock / while waiting | nothing | — |
| Writing objects | `staging/<snap>/tmp/*` (partial), plus complete objects already renamed into `objects/` | deletes `staging/*`; sets `needs_gc` (below) |
| Writing index | `staging/<snap>/index.json.gz` half-written | **discarded** with `staging/` — never read |
| After commit rename, before dir fsync | snapshot fully present, or (after power loss) absent | either is valid |
| During prune | `trash/<snap>` partially deleted | `rmtree(trash/*)` |
| During GC | some unreferenced objects remain | the next GC removes them |
| Writing run report | `runs/.tmp-*` | deleted |

**Orphan objects after a crash.** Objects renamed into `objects/` by a dead
run are referenced by no committed index. On macOS, `fsync` does not reach
stable media (§6.4), so after a power loss such an object could exist by
name with bad contents. To avoid trusting it, recovery with `needs_gc` runs
**GC before the scan**: every object not referenced by a valid committed
index is deleted. Only then does dedup ("object exists → skip") apply. Every
object a committed index references was written before that snapshot's
durability barrier. Measured cost: listing and stat of 30,300 objects took
0.12 s, plus one index parse (0.02 s) per retained snapshot.

**Corrupt committed index.** By construction this happens only through
media/FS corruption or external tampering, since half-written indexes exist
only in `staging/`. Validation on every run checks: gzip CRC, JSON parse,
`format == 1`, `entry_count`, `entries_sha256`, and every path passing
`check_relpath` (§9).

* **Discarded**: the snapshot directory is renamed to `quarantine/<snap>`
  (kept for diagnosis, at most 5 per repository, oldest deleted first). It no
  longer counts as a snapshot for base selection or retention, and its
  objects are no longer protected by GC.
* **Re-derived from the tree**: the change-detection baseline falls back to
  the newest *valid* snapshot. If none is valid, the baseline is empty and
  every source file is read and hashed again from the **source tree**.
  Objects whose content still exists are not rewritten (dedup), so the cost
  is at most the first-full budget (§7). Nothing in a quarantined index is
  trusted, even partially.
* **Reported**: `quarantined: [{snapshot, reason, entry_count_claimed}]`, a
  run **error** (exit 2), plus which snapshot became the base.

### 6.4 Durability barrier

Per-object `os.fsync` happens before its rename. Measured on macOS it costs
≈29 µs/file and does **not** flush the drive cache. Before the commit rename,
the run issues **one** `fcntl(F_FULLFSYNC)` on the index fd (macOS), which
flushes the device cache for everything written so far. On Linux, `fsync` is
already a full flush, so the barrier is the index `fsync` + directory
`fsync`. A per-file `F_FULLFSYNC` was measured at **4.68 ms/file**, which
would add ≈140 s per 30k files. That is why there is one barrier per
snapshot, not one per file.

### 6.5 What "point in time" means here

Each file's content is the state of that file at the moment it was read, and
it is verified stable by `fstat` before/after. The snapshot covers the window
`[started_at, completed_at]`. It is **not** an instantaneous cross-file
image: that needs filesystem snapshots (APFS/ZFS/LVM), which is out of scope.
Every entry in a snapshot was either read or stat-verified unchanged **by
this run**, so no entry is "from the previous run".

---

## 7. Performance: first full backup budget and growth bounds

### 7.1 Measurement setup

* Machine: Apple M3 Max, 14 cores, 36 GB RAM, internal SSD, APFS,
  Python 3.10.11.
* Tree: generated by a script, **30,000 files, 1,067,051,796 bytes**
  (1.1 GB in `du`). 29,900 files of 1–55 KiB in 60 × 20 directories, plus
  100 files of 1–3 MiB. Contents are random bytes, so no compression effects.
* Source in page cache (freshly written). `sudo purge` was not available, so
  cold-cache reads were not measured; see 7.3.
* Prototype of §4 (`scan_tree` + `store_object` + gzip index + barrier),
  ~60 lines, run 4 times. Throwaway code in a temp dir, not in this repo.

### 7.2 Results

| Run | Time |
|---|---|
| **First full backup, index design** (4 runs) | **15.6, 15.8, 22.9, 27.8 s** |
| — of which scan (`scan_tree`) | 0.15–0.18 s |
| — of which index write + barrier + commit | 0.02–0.06 s |
| Second run, nothing changed | **0.19 s** (one outlier: 2.18 s) |
| Run with 300 files (1%) changed | **0.41 s** |
| Reference: `synccli.sync` full copy (no hash, no fsync, no atomicity) | 11.0 s |
| Reference: `synccli.sync` no-op | 2.3 s (2.1 s is `build_manifest`, mostly `relpath`) |
| Rejected hard-link-tree design: first / no change / 1% change | 11.6–12.3 s / 9.98 s / 9.59 s |

Profile of the first run (`cProfile`, 15.6 s run):

| Item | Time | Per file |
|---|---|---|
| `open` (src + tmp) | 4.04 s | 135 µs |
| `rename` | 2.96 s | 99 µs |
| `fsync` | 0.87 s | 29 µs |
| `read` | 5.35 s | |
| `write` | 0.94 s | |
| `sha256` | 0.43 s | |

### 7.3 Budget and its derivation

Model: `T_full ≈ F · c_file + B / r`.

* `c_file` ≈ 0.28 ms: two opens 135 µs + rename 99 µs + fsync 29 µs +
  close/stat 18 µs, all measured.
* `r` ≈ 160 MB/s: read + write + hash = 6.72 s for 1.07 GB, measured.

For F = 30,000, B = 1.07 GB: 30,000 × 0.28 ms + 1.07 GB / 160 MB/s
= 8.4 s + 6.7 s = **15.1 s predicted vs 15.6 s measured** (median of the
two fast runs). The slower runs (22.9, 27.8 s) show up to 1.8× variance from
machine load.

**Budget: the initial full backup of a ~1 GB / ~30k-file tree must complete
in ≤ 60 s** on this class of machine (local SSD). That is ≈2.2× the worst
observed run and ≈4× the median. The run report records `elapsed`,
`files_copied` and `bytes_copied` per directory, and any directory over
`60 s × max(B/1 GB, F/30k)` is flagged `over_budget` (warning).

Caveats:

* **Linux/ext4 is not measured here.** The formula holds, but `c_file` and
  `r` must be re-measured on the target host with the same generator and
  prototype (to be added as `bench_backupctl.py`).
* **Cold cache on SSD**: this SSD reads well above 160 MB/s, so `r` is not
  read-bound. **On a spinning disk** the budget does not hold: 30k random
  seeks at ~8 ms ≈ 240 s.

### 7.4 Why not hard-link trees (the obvious alternative)

A `--link-dest` design makes each snapshot a browsable tree, with unchanged
files hard-linked to the previous snapshot. Measured on APFS:

| Operation | Per op | Per 30k files |
|---|---|---|
| `link(2)` | 336 µs | 10.1 s |
| `utime` | 150 µs | 4.5 s |
| `chmod` | 68 µs | 2.0 s |
| `lstat` | 5 µs | 0.14 s |

So a run where **nothing changed** cost 9.98 s per 30k-file directory,
versus 0.19 s for the index design. At a few dozen directories that is
minutes versus seconds, on every run. The link tree also adds ~4.8 MB of
directory entries per snapshot (measured with `du`) versus 1.78 MB of gzipped
index, and each `link()` pins inode link counts.

What the index design gives up is that snapshots are not directly browsable.
`backupctl ls NAME SNAP [PATH]` and `backupctl restore` cover that.

### 7.5 Growth bounds

Notation:

* N = configured directories.
* For directory i: Fᵢ files, Bᵢ bytes, Cᵢ changed files / Bcᵢ changed bytes
  in a given run.
* R = retained snapshots per repository ≤ `keep_last + keep_daily` = 7 + 14
  = **21**, plus at most L snapshots deferred because a reader holds a lease.
* U = distinct objects in a repository.

**Per-run time**, directories processed sequentially:

T_run = Σᵢ [ Fᵢ·(5.5 µs scan + 5 µs base-object stat) + 4 µs·Fᵢ
(base index decompress+parse 0.02 s + new index gzip 0.10 s per 30k, measured) + Cᵢ·0.28 ms
+ Bcᵢ / 160 MB/s ] + GC when it runs (≈ 4 µs·U + 0.7 µs·R·F̄ᵢ).

* No-change run: measured 0.19 s per 30k-file directory, so ≈ 6.3 µs·F.
* 36 directories × 30k files with no changes: ≈ 7 s.
* **Scales with ΣF and with the changed bytes. It does not scale with
  total B or with the history depth R** (except during GC).

**Peak memory per run**:

M ≈ 2 · 675 B · maxᵢ Fᵢ + 1 MiB copy buffer + ≈100 B · U (GC live set) +
interpreter (~15 MB).

* 675 B/entry was measured: `tracemalloc` peak was 20.2 MB to parse a
  30k-entry index.
* For 30k files: ≈ 40 MB + 3 MB + 15 MB ≈ **60 MB**.
* This **does not depend on N** (sequential processing), on Bᵢ (streaming
  copy instead of `copy_file`'s whole-file read), or on R (one index is parsed
  at a time; GC keeps only the hash set).

**Disk per repository**:

* objects ≤ Bᵢ (newest) + Σ over retained snapshots of new content Bcₖ
  (minus dedup).
* indexes ≤ (R + L) · 59 B · Fᵢ. For 30k files and R = 21 that is ≤ 37 MB.
* quarantine ≤ 5 indexes.
* `runs/` ≤ 100 reports, each capped at 1000 listed paths per category,
  ≈ ≤ 150 KB each → ≤ 15 MB.
* leases: (R + L) empty files.
* staging: transient, ≤ one in-flight temp object at any instant beyond the
  renamed objects; empty after the run.
* trash: empty after the run.
* objects directory fan-out: 256 subdirectories, ≈ U/256 entries each
  (30k → ~117).

**Total root**: Σᵢ of the above.

* An unchanged run adds exactly one index (59 B · Fᵢ), and retention removes
  one, so the steady state with no edits is **flat at ≤ (R + L) · 59 B · ΣF
  of indexes over Σ Bᵢ of objects**.
* `snaputil.snapshot_disk_usage(repo, snap)` (`snaputil.py:39-51`) is used
  as-is for the index-bytes column of `backupctl list`, which is the only
  file it walks. It is called only under the writer lock, because of its
  crash on concurrent deletion (defect 12). The "content bytes" and
  "exclusive bytes" columns are computed from the indexes (reference counts
  per object), not from the walk.

**Locks and inodes**: 1 writer lock per repository, ≤ R + L lease files,
≤ U object inodes.

---

## 8. Retention

`apply_retention` overrides `snaputil.prune_snapshots`
(`snaputil.py:23-36`). It runs under the writer lock, only after this run
committed a snapshot.

1. Candidates = valid committed snapshots (discovered via `list_snapshots`,
   validated, sorted by `seq`). Staging, quarantine and trash are never
   counted. The count-only `prune_snapshots` counted a `.partial` dir as a
   snapshot (defect 10).
2. **Keep**:
   * the `keep_last` newest (default 7, minimum enforced **1**; `0` and
     negatives are config errors, unlike `prune_snapshots(root, 0)`);
   * the newest snapshot of each UTC day for the last `keep_daily` days
     (default 14), with age taken from `header.completed_at`, not directory
     mtime (`is_stale` is not used, defect 11);
   * always the newest valid snapshot.
3. **Shrink guard**: if the snapshot just committed has fewer than
   `shrink_guard` (default 50%) of the files or bytes of the largest retained
   snapshot, prune deletes nothing and the report says why. A wiped or
   half-mounted source therefore cannot rotate the good history out within
   `keep_last` runs.
4. **Delete** each remaining candidate with the lease protocol (§6.2):
   exclusive lease non-blocking → `rename` to `trash/` → delete the lease
   file. A leased snapshot is deferred to a later run (reported, counted in L).
5. **GC** (only if something was trashed, or `needs_gc`): live set = union of
   hashes in all valid `snap-*` indexes. Delete every object not in it, then
   `rmtree(trash/*)`.

Invariants:

* Never zero usable snapshots, because the newest valid one is always kept,
  and a run that did not commit (busy, source missing, fatal) never prunes.
* Never delete under a protocol reader.
* Never delete an object a retained snapshot references.

---

## 9. Restore and path safety

`backupctl restore NAME SNAP TARGET [--path PREFIX]`:

1. Open S with a lease and validate the index.
2. For each entry, create directories/symlinks, or stream the object to
   `TARGET/rel.tmp-<run>`, **verifying the SHA-256 while copying**, then
   `rename` and apply mode/mtime.
3. Entries marked `unreadable` are listed as not restorable, along with the
   last snapshot that has them.

`snaputil.safe_snapshot_path` (`snaputil.py:54-63`) is **not used** because it
does not do what its docstring says (defect 8). It is replaced by
`check_relpath`, applied both at index validation and at restore. It rejects:

* empty paths and NUL bytes;
* absolute paths;
* any `..` component in the stored path (rejected, not normalized);
* paths whose real parent, after creating intermediate dirs with
  `O_NOFOLLOW`-checked opens, is not under `realpath(TARGET)`.

The last rule means a symlink restored earlier cannot redirect a later
file: symlink entries are created after all regular files.

---

## 10. Verification of the claims about existing code

Run against unmodified `synccli.py`/`snaputil.py` (copies in a temp dir):

* unreadable `a` → `sync` returned `['a']`, file absent, `'a'` in manifest;
  after `chmod 644`, `sync` returned `[]`, file still absent (defect 1);
* manifest truncated to `{"a": {"si` → `JSONDecodeError` on every call
  (defect 2);
* `scan_files` on `{a, .cache/x, real/y, lnk→real}` → `['a', 'real/y']`
  (defect 4);
* `build_manifest` with a file removed after scanning → `FileNotFoundError`
  (defect 3);
* same-size edit + `os.utime` restore → `sync` returned `[]`, destination
  kept `AAAA`, ctime differed (defect 5);
* deleted source file still present in destination (defect 6);
* `safe_snapshot_path` outputs as in defect 8;
* `is_stale(d, stat(d).st_mtime)` → `True` (defect 11);
* `list_snapshots` order `[-100, -99, …-01.partial]`; `prune_snapshots(r, 0)`
  and `(r, -1)` delete everything (defects 9, 10);
* `snapshot_disk_usage` on one 1000-byte inode linked in two snapshots →
  1000 and 1000 (defect 12);
* `collect_stale(iter([...]))` → `TypeError` (unused by backupctl);
* `python3 -m unittest` → 6 tests, OK (none of the above is covered).

---

## 11. CLI, reporting, exit codes

* `backupctl run [--only NAME…] [--wait SEC] [--trigger T]`
* `backupctl list [NAME]` — seq, name, completed_at, files, content bytes,
  exclusive bytes, index bytes.
* `backupctl ls NAME SNAP [PATH]`
* `backupctl restore NAME SNAP TARGET [--path P]`
* `backupctl verify NAME [SNAP]`
* `backupctl prune [NAME]`

Report: `runs/<run-id>.json` per repository (temp + rename), plus a
one-line-per-directory summary on stdout. Each directory's result is one of
`committed | committed-with-errors | skipped-busy | source-missing | failed`
and carries the counts and path lists from §6.1, quarantine events,
deferred prunes, `elapsed` and `over_budget`.

Exit code, highest wins:

| Code | Meaning |
|---|---|
| 1 | fatal: config, backup root unusable |
| 2 | any directory with errors: unreadable, quarantine, source-missing, failed |
| 3 | any directory `skipped-busy` |
| 0 | otherwise; warnings (vanished, unstable, over_budget) do not change it |

The same exit codes apply for scheduler and manual runs.

---

## 12. Test plan

New `test_backupctl.py`, run with `python3 -m unittest` next to the existing
suite, which must stay green.

* **Crash injection**: env hook `BACKUPCTL_CRASH_AT=<phase>` (after object
  N, mid-index, before/after commit rename, mid-prune, mid-GC) with
  `os._exit`, plus a subprocess `SIGKILL` at random times. After each, assert:
  * every `snap-*` validates;
  * every referenced object exists and hashes correctly;
  * the next run succeeds with no manual step.
* **Corrupt index**: truncate / flip a byte / break `entries_sha256` → the
  snapshot is quarantined, the base falls back, the report shows exit 2, and
  the next snapshot is correct.
* **Concurrency**: two `run` processes (one skips with exit 3); `run` +
  leased reader + prune (the leased snapshot is deferred, the reader
  completes byte-identical).
* **Moving source**: file removed between scan and open (vanished, exit 0);
  `chmod 000` (unreadable entry, exit 2, retried and captured next run after
  the fix); file appended during copy (unstable).
* **Change detection**: same-size edit with restored mtime → detected
  (ctime); racy-clean file re-read next run.
* **Retention**: keep_last / daily / shrink guard / never-zero / source
  missing ⇒ no prune.
* **Path safety**: `../x`, `/etc/x`, NUL, and the symlink-then-file attack
  are all rejected.
* **`bench_backupctl.py`**: the generator from §7.1 plus timing of the
  first / no-change / 1% runs, printing `c_file` and `r` for the formula in
  §7.3.

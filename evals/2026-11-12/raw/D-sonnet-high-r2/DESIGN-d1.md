# DESIGN-d1 — `backupctl`

Status: design only. No existing file is modified by this document.
Everything below marked **(measured)** comes from runs I did on this machine
(macOS, arm64, APFS local SSD, Python 3.10.11, warm page cache). Anything
marked **(derived)** is arithmetic on those measurements. Anything I did not
measure says so.

---

## 1. Summary of the design

* A **snapshot** is an immutable directory `snapshots/<id>/` holding `tree/`
  (a full, plain-file image of the source set) and `manifest.json` (the index).
  Unchanged files are **hard-linked** from the previous snapshot; changed files
  are copied. Every snapshot is therefore a complete tree that `cp -r` can
  restore, and deleting any snapshot cannot damage another.
* A snapshot is built in a private `staging/` directory and becomes visible by
  one atomic `rename(2)` into `snapshots/`. **Presence in `snapshots/` means
  complete.** Readers never ask whether a run is finished.
* One advisory `flock` per set serializes runs and pruning. Crashes release it
  automatically; there are no stale locks and no pid files to reason about.
* "Unchanged" is decided per file by `(size, mtime_ns, ctime_ns, mode)`, with a
  "racily clean" rule. The design lists exactly which edits that misses.
* Source problems (vanished / unreadable / unstable files) have one defined
  outcome, identical for scheduler and human runs: nothing is guessed, nothing
  is carried over from the older snapshot, the manifest lists only files that
  are really in `tree/`, and the problem is listed in `manifest.skipped` and in
  the exit code.
* Retention is a defined policy plus hard guards that always keep a usable
  snapshot. Deletion is "rename out of sight, then unlink", and cooperating
  readers hold a shared lease that deletion respects.

---

## 2. Grounding in the existing code

`synccli.py` (103 lines) and `test_synccli.py` (6 tests, all pass —
`python3 -m unittest`, **measured**) are the base. `sync()` already has the
pipeline shape I need: **scan → manifest of per-file state → load previous
manifest → diff → copy the diff → persist manifest.** `backupctl` keeps that
shape and each stage reuses the existing function named below. Where it must
differ, the difference and the reason are stated; "differs" rows are the
important part of this section.

| Stage | Existing code | How `backupctl` uses it | Where it **must differ**, and why |
|---|---|---|---|
| Listing | `synccli.scan_files(root)` (l.10) | Same walk, same sorted relative paths, called for every set. | (a) `os.walk(..)` is called with no `onerror`, so an unreadable directory silently drops its whole subtree. I **measured** this (`chmod 0` dir → absent from the list, no error). A backup that silently omits a subtree is the opposite of the brief. `backupctl` needs `onerror` and records `skipped` (`reason: unreadable-dir`). (b) `dirnames[:] = [d … not startswith(".")]` drops every dot-directory (`.git`, `.cache`, a hidden results dir) from the list, while dot-*files* are kept (measured). Fine for syncing a working tree, not for "back up this directory". `backupctl` includes hidden directories. (c) Directory symlinks are not in the result (measured: `lnk` absent) and empty directories are lost, so a restore could not rebuild them; `backupctl` needs them recorded as `symlinks` / `dirs`. (d) FIFOs/sockets are listed as files (measured) and `open()` on a FIFO blocks forever; they must be classified, not opened. (e) **Speed:** `os.path.relpath(os.path.join(d,f), root)` per file costs ≈87 µs. `scan_files` on the 30k-file tree takes **2.7 s (measured)**; the bare `os.walk` takes 0.12 s and walk + string slice 0.095 s. |
| Per-file state | `synccli.file_state(path)` (l.22) → `{"size","mtime"}` | Same function, same dict-of-scalars shape, so the existing diff keeps working. | `os.stat` follows symlinks → dangling symlink raises (measured: `FileNotFoundError` crashes the whole `sync`) and a symlink is backed up as its target's content. `backupctl` needs `os.lstat`. `mtime` is a float: at epoch ≈1.7e9 a double has ≈240 ns resolution, so it cannot represent a nanosecond mtime; need `st_mtime_ns`. Adds `ctime_ns` and `mode` (§7). |
| Manifest build | `synccli.build_manifest(root)` (l.28) | Same loop (`scan_files` → `file_state`), result is `{relpath: state}`. | Any exception from one file aborts the manifest (measured, dangling symlink). `backupctl` must catch per file, classify (`vanished` vs `unreadable`) and carry on. |
| Diff | `synccli.changed_files(old, new)` (l.36) | **Used unchanged.** It compares whole state dicts with `!=`, so extra state keys (`ctime_ns`, `mode`) are picked up for free. It is also direction-agnostic: an *older* mtime counts as changed, which is what a backup needs (restoring an old file over a new one). | It returns only new/changed paths, not deletions — fine for snapshots, because a snapshot is built from the *new* listing, so deleted files simply are not linked or copied. To make the "racy" rule (§7.3) work **without touching `changed_files`**, hashes and racy flags live in *separate* manifest sections (`digests`, `racy`), not inside the state dict. If a `sha256` key were inside the state dict, every file would compare unequal. Before the call, racy entries are dropped from `old`, which makes them look new. |
| Copy | `synccli.copy_file(src, dst)` (l.62) | Reuses its one good idea (`os.makedirs(dirname(dst), exist_ok=True)`). | **Cannot be used as is.** (1) `except OSError: pass` swallows every failure, including ENOSPC on the destination. (2) `sync()` then writes the manifest anyway, so the manifest promises a file the destination lacks. I **measured** it: a `chmod 0` file is reported as copied, is absent from `dst`, is in the manifest, and is never retried (the comment "next pass will retry" is false). That is exactly the brief's "index that promises files the snapshot does not contain". (3) `fdst.write(fsrc.read())` holds the whole file in memory: peak RSS = largest file (a single 1 GB file means 1 GB RSS). (4) No mtime restore, no hash, no check that the file did not change while being read. `backupctl` uses a new `copy_regular()` (chunked, hashing, stat-bracketed, raises typed errors). `synccli.copy_file` is left alone for `synccli`. |
| Persist | `synccli.sync()` (l.72), manifest write at l.85 | Same ordering idea; also the `dry_run` contract (return the list that would be copied, touch nothing) is kept. | The manifest is written with `open(path,"w")` in place: a kill mid-write leaves torn JSON and the next `sync` dies on `json.load` (measured: `JSONDecodeError`), forever, until manual cleanup. Brief requires "the next run makes progress without manual cleanup". `backupctl` writes the manifest into a private staging dir and publishes by directory rename, so a torn manifest can never be seen. A manifest that is nevertheless unreadable (bit rot) is caught, that snapshot is skipped as a base and reported. |
| Entry point | `synccli.main()` (l.90) | Same argparse style. | `main` always `return 0`. `backupctl` needs distinct exit codes (§9). |
| `collect_stale` (l.45) | — | **Not used.** It is not called by `sync()` and has no role in change detection; I am not building on it. | — |

### Proposed edits to `synccli.py` (not done; need your go-ahead)

All backward compatible; `sync()` and the 6 existing tests keep today's
behaviour.

1. `scan_files(root, *, include_hidden=False, onerror=None)` — and replace
   `relpath` with a slice of the joined path (output must be identical for
   roots like `"src"`, `"src/"`, `"./src"`; add a test). Alone this makes
   `sync` ≈ 2.5 s faster on 30k files (measured: 2.7 s → ≈0.1 s walk + slice
   in the experiment).
2. `file_state(path, *, detailed=False)` — `detailed` uses `lstat` and returns
   `{"size","mtime_ns","ctime_ns","mode"}`.
3. `build_manifest(root, *, detailed=False, on_error=None)` — per-file
   try/except calling `on_error(rel, exc)` when given; today's raise
   behaviour when `None`.

New code goes in `backupctl.py` (+ `test_backupctl.py`). `synccli`'s own
defects found while reading it (silent copy failure recorded as success, torn
manifest, dangling-symlink crash) are **reported here, not fixed here** — that
is a separate decision for you.

---

## 3. On-disk layout

```
<backup_root>/
  <set>/                         one directory per configured source dir
    .lock                        flock target; also holds "pid, started" text for diagnostics
    snapshots/
      0000000042-20261112T101500Z/     <seq>-<UTC start time>   (the snapshot id)
        manifest.json
        tree/...                       immutable
    staging/<runid>/                   private, invisible to readers
    trash/<id>.<rand>/                 snapshots being deleted
    leases/<id>.lock                   reader leases (§8.2)
    pins/<id>                          optional "never prune" marks
    runs.jsonl                         one line per run, append-only (info only)
```

* Set name is the config name (`[A-Za-z0-9._-]+`), never derived from the
  source path.
* **`seq` is the ordering key**, not the clock: it is `max(existing seq)+1`
  computed under the lock. A laptop whose clock jumps back still gets a
  correct "newest".
* Readers (restore, humans, the next run) look **only** in `snapshots/`.
  `staging/`, `trash/`, `leases/` are never snapshot content.
* `staging/` and `snapshots/` are in the same directory so the publishing
  `rename` is within one filesystem (atomic). Requirements on the backup
  root: one local filesystem with hard links, atomic rename and `flock`
  (APFS, ext4, xfs: yes; NFS/SMB/exFAT: no). `backupctl` checks this on
  first use by creating a test link and refuses otherwise; a documented
  `link_mode: "copy"` degrade exists (unchanged files are copied from the
  base snapshot: correct but O(bytes) per run, no dedup).
* The backup root must not be inside any source and no source inside the root
  (checked on config load, using realpaths) or the tool would back itself up.

`manifest.json` (compact JSON, `separators=(",",":")`):

```json
{
  "format": 1, "set": "evals-results", "seq": 42, "id": "0000000042-…Z",
  "source": "/abs/path", "base_seq": 41,
  "started_at": "…", "finished_at": "…", "status": "ok" | "partial",
  "counts": {"files": 30000, "copied": 300, "linked": 29700, "bytes_copied": 0},
  "files":   { "rel/path": {"size":…, "mtime_ns":…, "ctime_ns":…, "mode":…} },
  "digests": { "rel/path": "sha256 hex" },
  "racy":    [ "rel/path", … ],
  "dirs":    [ "rel/dir", … ],
  "symlinks":{ "rel/link": "target" },
  "skipped": [ {"path":…, "reason": "vanished|unreadable|unstable|unreadable-dir|special", "detail":…} ]
}
```

`files` is exactly the set of regular files present in `tree/`. `skipped` is a
*report*, never a promise: nothing in it is in `tree/`.

---

## 4. Run algorithm (one set)

1. **Lock.** Open `<set>/.lock`, `flock(LOCK_EX|LOCK_NB)`.
   Busy → print "busy (pid N, since T)", exit 75 for this set (§9). Optional
   `--wait SECONDS` retries until the deadline; it is a flag, not a mode
   chosen by who is calling.
2. **Recover.** Under the lock, nothing else is in flight for this set, so
   every entry in `staging/` and `trash/` is an orphan of a dead run:
   `rmtree` them. This is the entire crash recovery; no flags, no manual
   step.
3. **Pick the base.** Newest `snapshots/<id>` (by `seq`) whose `manifest.json`
   parses, has `format==1` and `len(files)==counts.files`. An invalid snapshot
   is reported (`corrupt`) and skipped; if none is valid, this is a full
   backup.
4. **Scan.** `scan_files(src, include_hidden=True, onerror=…)` then
   `file_state(detailed=True)` per entry (`lstat`). Record
   `scan_start_ns` first. `FileNotFoundError` on lstat → `vanished` (dropped);
   other `OSError` → `unreadable`. Non-regular, non-symlink, non-dir entries
   (FIFO, socket, device) → `skipped: special`, never opened.
5. **Diff.** `changed = synccli.changed_files(old_files_minus_racy, new_files)`.
   Files in `new` not in `changed` are "unchanged".
6. **No-op shortcut.** If the file set, all states, `dirs`, `symlinks` and the
   skipped set equal the base's, **no new snapshot is created**; log a line in
   `runs.jsonl`, run retention, exit 0. (The newest snapshot is still an exact
   image; this makes the common case cost ≈0.4 s, §10.) `--force` overrides.
   `--dry-run` stops here and prints `changed` (same contract as
   `sync(dry_run=True)`), creating nothing, not even `staging/`.
7. **Safety guard.** Source missing / not a directory → error, exit 1, no
   snapshot. Zero files found while the base had >0 → refuse (exit 1) unless
   `--allow-empty` (an unmounted source volume must not produce an empty
   "newest" snapshot).
8. **Build in staging.** `staging/<runid>/tree/`; create `dirs`, create
   `symlinks` with `os.symlink`. Per file:
   * unchanged → `os.link(base/tree/rel, stage/tree/rel)`. If the link fails
     (`ENOENT` base file missing → treat as changed; `EXDEV`/`EPERM`/`EMLINK`
     → copy from the base file), never fail the run.
   * changed/new → `copy_regular(src, dst)`: `open(O_RDONLY|O_NOFOLLOW)`,
     `fstat` → must be a regular file; copy in 1 MiB chunks, updating a
     sha256; `fstat` again. If `(size, mtime_ns, ctime_ns)` differs from
     before the read the bytes may be torn → retry up to 3 times, then
     `skipped: unstable`. Then `os.utime(ns=…)` to the source mtime and store
     with mode `(mode|0o400) & ~0o222` (read-only; real mode is in the
     manifest). State recorded in the manifest is the **pre-copy** `fstat`.
   * Error classification, source vs destination: failures on `open`/`read`
     of the source are *source-side* (`vanished` for ENOENT, `unreadable`
     otherwise) and only skip that file. Failures writing to the staging tree
     (ENOSPC, EIO, EDQUOT) are *run-fatal*: remove staging, exit 1.
   * a skipped file is **not** replaced by its copy from the base snapshot:
     that would be the brief's forbidden "some files from this run, some from
     the previous one". It is simply absent and listed.
9. **Write `manifest.json`** into staging (last file written). `status` is
   `partial` iff any `unreadable`, `unstable` or `unreadable-dir` entry
   exists; `vanished` and `special` alone keep `ok` (§6).
10. **Make durable, then commit.** `os.sync()` (the 30k files are not
    individually fsynced; **measured** `fsync` on 3000 already-flushed files
    ≈0.44 s so per-file fsync would add ≈4 s, `os.sync` of the whole tree
    after the run ≈0.06 s; I did not measure power-cut behaviour, and on macOS
    `sync(2)` does not promise `F_FULLFSYNC` semantics). Then
    `rename(staging/<runid>, snapshots/<id>)` and `fsync` the `snapshots/`
    directory. The rename is the commit point.
11. **Retention** (§8) under the same lock. Skipped if the run failed (a
    failing backup must not shrink history), except after an ENOSPC abort,
    where policy-eligible deletions are exactly what can help.
12. Append to `runs.jsonl`, release lock (closing the fd releases it).

---

## 5. Concurrency and crash model

**Two runs at once (scheduler + person).**
Same set: one wins the `flock`, the other exits 75 "busy" without touching
anything, or waits with `--wait`. Different sets: independent locks,
independent directories, may run in parallel. The lock is held by an open
fd; if the holder dies for any reason the kernel releases it, so a stale lock
cannot exist. A *hung but alive* run (e.g. frozen NFS source) holds the lock
indefinitely: the second run reports the holder's pid and start time from the
lock file; killing it is a human decision (`--wait` has a deadline).

**Restore (or any reader) while a run writes.**
A run writes only under `staging/` and creates a new name in `snapshots/` by
rename. Published snapshot contents are **never modified** (write-once files,
read-only mode, hard links only to other immutable files). So a reader of
snapshot *S* is unaffected by a run producing *S+1*, and a reader that lists
`snapshots/` sees either *S+1* complete or not at all. Readers take no lock.

**Reader sees a coherent image.** Every file in `snapshots/S/tree` was either
copied by run S (stat-bracketed) or hard-linked from the base snapshot after
the scan showed its state equal to the base's. The manifest `files` section
is built from exactly that set, so it cannot list a file that is absent.
*What this does not give:* the source tree is not frozen during a run (no
filesystem snapshot), so a snapshot is "each file whole, at some moment during
the run", not one instant across files. If cross-file point-in-time matters,
the source must be quiesced or run from an APFS/LVM/btrfs snapshot; the design
leaves a place for that (`source` can point at a mounted snapshot) but does
not implement it.

**Death at any point.**

| Dies during | Left behind | Visible to readers? | Next run |
|---|---|---|---|
| steps 1–7 | nothing / a lock fd (released) | no | normal |
| step 8–9 (copying, manifest) | `staging/<runid>/` partial | no (not under `snapshots/`) | step 2 deletes it, restarts the run |
| between 10's `os.sync` and rename | complete staging | no | deleted and redone (work lost, correctness kept) |
| after rename | a published, complete snapshot | yes, correct | no-op or next increment |
| during prune | snapshot already moved to `trash/` | no | step 2 finishes the delete |
| Ctrl-C/SIGTERM | the same as above; a `finally` also best-effort removes staging | no | same |
| laptop sleep | process suspended, lock held, nothing torn | no | other runs report busy; resumes on wake (source may have changed — handled by the stat bracket) |

An interrupted run is *redone*, not resumed: simpler and safe. Cost: a killed
initial full backup restarts from zero (≈18 s at reference size, §10).

---

## 6. A source file disappears or cannot be read

Same behaviour for scheduler and human: there is no TTY check, no prompt, no
"interactive" branch; the only inputs are config and flags.

| Situation | Snapshot contains | Reported as | Status / exit |
|---|---|---|---|
| Vanishes between scan and copy (ENOENT on `open`/`lstat`) | no entry, no partial file | `skipped: vanished` in manifest + stderr + `runs.jsonl` | `ok`, exit 0 |
| Unreadable (EACCES, EIO, read error mid-copy) | no entry (a half-written dst file is deleted) | `skipped: unreadable` with `errno` | `partial`, exit 3 |
| Directory unreadable (`onerror` fired) | nothing under it | `skipped: unreadable-dir` | `partial`, exit 3 |
| Changed during every one of 3 copy attempts | no entry | `skipped: unstable` | `partial`, exit 3 |
| FIFO / socket / device | no entry | `skipped: special` | `ok`, exit 0 |
| Destination write failure | no snapshot at all | error, staging removed | exit 1 |

Rationale: a vanished file no longer exists, so a snapshot without it is a
faithful image of the source *now*; making it `partial` would turn routine
churn (temp files) into permanent alarms. The known cost: a **rename** during
the run looks identical to a delete and the file may be in neither snapshot
for one cycle; the next run captures it. An unreadable file is real data
missing and is therefore `partial` and exits non-zero. Because skipped files
are absent from `files`, the next run sees them as "new" and **retries them
automatically** — the retry that `synccli.copy_file`'s comment promises but
does not deliver. A permanently unreadable file does not create a new
snapshot every run (§4.6 compares skipped sets).

A partial snapshot is still published (most of the data is better than none);
retention (§8) never lets a partial snapshot count as "the usable one".

---

## 7. Change detection: what "unchanged" means

### 7.1 Granularity

A file is unchanged iff, for the same relative path, `(size, mtime_ns,
ctime_ns, mode)` equals the base manifest's (via
`synccli.changed_files`, §2). It is per file, per path; it never reads file
contents. Directories are compared by their listing (name set).

### 7.2 What it can miss

* An edit that leaves size, mtime **and** ctime unchanged. Normal tools can't
  do this because ctime can't be set from user space; it needs a clock change
  or a filesystem that reports ctime = mtime, a FUSE/network filesystem with
  coarse or fake stat data, or a raw block-device write.
* Edits within one timestamp tick of the previous scan that keep the size
  (handled in 7.3).
* Bit rot/corruption of the *source* with no stat change.
* Not missed (a reason for including `ctime_ns`): `cp -p`, `rsync -t`,
  `touch -r`, `os.utime`, tar extraction with preserved times — all of which
  defeat the `(size, mtime)` pair that `synccli` uses today (**measured**: a
  same-size edit with the mtime put back is *not* picked up by
  `synccli.sync`; `dst` keeps the old bytes).
* False positives (safe direction, cost only): `chmod`, `chown`, xattr
  changes, being renamed, a hard link added elsewhere → recopy.

Backstop: `backupctl run --rehash` hashes every source file and compares to
`digests`, ignoring stat equality. It costs a full read of the source
(≈0.6 s/GB of sha256 here, **measured**, plus the per-file open cost); meant
for a weekly job. `backupctl verify <set> [id]` re-hashes a snapshot's
`tree/` against its own `digests` to detect rot in the backup.

### 7.3 Racy-clean rule

A file whose `max(mtime_ns, ctime_ns)` is within 2 s of `scan_start_ns` could
be modified again in the same timestamp tick (FAT 2 s, HFS+ 1 s, ext4 jiffy)
without changing its stat. Such files are copied normally, listed in
`racy`, and **treated as changed by the next run** (dropped from `old` before
the diff). It costs one extra copy of recently written files.

### 7.4 Where this differs from `synccli`

`synccli` uses `(size, mtime float)`: loses sub-250 ns precision, blind to
`utime`-restored edits (measured), no racy handling, no mode. `backupctl` is a
strict superset of the detection, so it never misses something `synccli`
would catch.

---

## 8. Retention and safe deletion

### 8.1 Policy (defaults, per set, configurable)

Keep the **union** of:
* the newest `keep_last = 5` snapshots (by `seq`);
* the newest snapshot of each of the last `keep_days = 14` UTC days;
* the newest snapshot of each of the last `keep_weeks = 8` ISO weeks;
* any `pins/<id>`.

Bucketing uses `finished_at`; ordering uses `seq`. Upper bound: ≈27
snapshots per set. Everything else is eligible, only after the run that
precedes it succeeded (§4.11). Because unchanged files are hard-linked,
deleting a snapshot frees only the file versions nobody else links to.

### 8.2 Hard guards (checked after the policy, they override it)

* G1: never delete the newest *valid* snapshot (manifest parses).
* G2: never delete the newest valid snapshot with `status: ok`, if one exists
  (so a run of partial snapshots cannot rotate out the last good one).
* G3: never delete a snapshot whose lease cannot be taken (below).
* Corrupt snapshots (manifest unreadable) are **never auto-deleted**; they
  are reported every run for a human to decide. They don't count as usable.

Publish happens before prune, so there is never a window where the new
snapshot isn't there while old ones are gone.

### 8.3 Deleting while someone may be reading

1. Try `flock(LOCK_EX|LOCK_NB)` on `leases/<id>.lock`. Fails → a reader
   holds a shared lease → **skip this snapshot, retry next run**.
2. `rename(snapshots/<id>, trash/<id>.<rand>)` — atomic; from here no new
   reader can find it, and a half-deleted snapshot is never visible in
   `snapshots/`.
3. `rmtree(trash/…)` (unlink only; hard-linked inodes shared with newer
   snapshots survive), then unlink the lease file.

**Reader protocol (cooperating tools such as the restore tooling):**
open/create `leases/<id>.lock`, `flock(LOCK_SH)`, **then re-check that
`snapshots/<id>` still exists** (closes the race with step 2), read, release.
`backupctl lease <set> <id> -- <command…>` and a small Python context manager
provide this. The restore tooling is separate and I cannot force it to
cooperate, so I also state what a **non-cooperating** reader gets: files are
never modified in place, only unlinked, and prune never touches the newest
snapshots (G1/G2). A reader of an old snapshot that gets pruned under it hits
`ENOENT` (loud, errors) rather than reading wrong bytes; readers that already
hold open directory fds or open files keep reading them (unlink doesn't
invalidate open fds). `backupctl pin` protects an old snapshot for a human who
does not want to depend on that.

---

## 9. CLI and exit codes (identical for every caller)

```
backupctl [--config backupctl.json] run [--set NAME ... | --all]
          [--dry-run] [--force] [--rehash] [--allow-empty] [--wait SECS]
backupctl list [SET]        backupctl latest SET [--ok]
backupctl verify SET [ID]   backupctl prune SET [--dry-run]
backupctl lease SET ID -- CMD…     backupctl pin|unpin SET ID
```

Config is JSON (Python is 3.10.11 here: no `tomllib`; `synccli` already uses
JSON): `{"root": "...", "sets": [{"name":"…","path":"…"}], "retention": {…}}`.

| Code | Meaning |
|---|---|
| 0 | every selected set ok (or no-op); includes `vanished`/`special` notes |
| 1 | a set failed: config, missing source, empty-source guard, destination I/O |
| 2 | usage / config invalid |
| 3 | at least one `partial` snapshot (unreadable/unstable) |
| 75 | at least one set was busy and skipped (nothing wrong; try later) |

With `--all`, a failure in one set does not stop the others; exit is the
highest-priority code, order `1 > 3 > 75 > 0`, and a per-set line is printed.

---

## 10. Performance budget for the initial full backup (~1 GB, tens of thousands of files)

### 10.1 What I ran (measured)

Fixture: 30,000 regular files, total 999,984,920 B, median 9,338 B, max
6.6 MB, log-normal sizes, random (incompressible) content, 1,000 directories,
on local APFS, page cache warm (files just written). Throwaway scripts in a
temp dir; they are not committed. If you want them kept, say so.

| Measurement | Result |
|---|---|
| Existing `synccli.sync()` initial run (copy 1 GB / 30k files) | **17.0 s**, RSS 82 MB |
| Existing `synccli.sync()` second run, nothing changed | 3.6 s (mostly `scan_files`) |
| `synccli.scan_files` alone | **2.7 s**; bare `os.walk` 0.12 s; walk + slice 0.095 s; 30k `lstat` 0.08 s |
| Existing manifest JSON (indent=2, float mtime) | 2.6 MB |
| Chunked copy + `utime` + `chmod` + sha256, all 30k files | 18.5 s |
| …same with blake2b / with no hash (`shutil.copyfile`) | 17.1 s / 18.4 s — hashing is in the noise |
| One 1 GB file, chunked copy + sha256 | 0.93 s (bytes are cheap) |
| sha256 read-only, 1 GB | 0.63 s |
| Create + write one 9 KB file | 178 µs |
| `os.link` of an existing file, 30k files | **12.8 s ≈ 430 µs each**, same for 2nd/3rd generation |
| `symlink` / `unlink` of a linked file | ≈99 µs |
| `rmtree` of a 30k-entry linked snapshot | 3.1 s |
| `os.sync()` after the staged tree | 0.06 s |
| **Prototype of §4 (scan, diff, copy/link, manifest, sync, rename), initial** | **17.8 s**, RSS 71 MB (scan 0.36, copy 17.25, manifest+sync 0.22) |
| Prototype, nothing changed (§4.6 no-op) | **0.43 s** |
| Prototype, 300 files edited | **14.3 s** (300 copies + 29,700 links) |
| Prototype manifest with digests + 4 state fields, 30k files | 6.3 MB |

### 10.2 Derivation

The initial backup is dominated by **per-file cost, not bytes**:
`T ≈ F × c_file + B / r`, with `c_file ≈ 17.25 s / 30,000 ≈ 0.57 ms`
(open, create, chunked loop, `utime`, `chmod`, hash) and
`r ≈ 1.1 GB/s` (single large file: 0.93 s/GB). So
`30,000 × 0.57 ms + 1 GB / 1.1 GB/s ≈ 17.1 + 0.9 ≈ 18 s`, matching the 17.8 s
measured run, with scan + manifest + sync ≈0.6 s more.

**Budget: ≤ 30 s wall clock for ≈1 GB / 30k files on a local SSD** (≈1.7× the
measurement, to absorb a cold page cache — my measurement was warm — and
noise). Scaling rule to state with it: ≈ 0.6 ms × files + 1 s × GB; 3× the
files at the same bytes → ≈ 3× the time. A cold-cache run, a spinning disk,
a Linux filesystem, and a network source are **not measured**; the budget does
not claim them.

Choices this budget bought: hashing is free relative to copying (so digests
are always computed); the 1 MiB chunk loop avoids `fsrc.read()` (peak memory
is bounded by the chunk, not by the file); a whole-run `os.sync()` (0.06 s)
instead of per-file fsync (≈4 s); fixing `relpath` in `scan_files` saves
≈2.5 s on every run, including today's `sync`.

### 10.3 The cost the hard-link design pays (honest)

On this APFS, `os.link` (430 µs) is *slower* than creating and writing a
9 KB file (178 µs). So a run that changes 1% of files still costs ≈14 s:
the links dominate. Expect Linux ext4/xfs to be cheaper; I did not measure it.
The no-op shortcut hides this only when *nothing* changed.

Alternative considered: a content-addressed object pool with the snapshot as a
manifest only. Per-run cost for unchanged files would be ≈0 (no per-file fs
ops), but then a snapshot is not a directory that `cp -r` restores, every
reader needs the pool indirection, and pool GC must be made safe against
concurrent readers. I rejected it for v1 because the brief's readers are
"separate tooling … reading a snapshot and copying it back". Revisit if the
no-change-but-not-no-op run for a set exceeds ≈30 s.

---

## 11. What grows with what

Let `F` = files in one set, `N` = number of sets, `S` = retained snapshots per
set (≤ ≈27), `C` = files changed since last run, `ΔB` = bytes of changed files.

| Resource | Grows with | Stays flat |
|---|---|---|
| **Time per set per run** | `F` for scan + diff (≈12 µs/file, 0.36 s/30k) and manifest write (≈7 µs/file); `F−C` links (≈430 µs each on APFS); `C` copies (≈0.57 ms each) + `ΔB` (≈1 s/GB); prune: ≈100 µs per entry of each deleted snapshot | A no-op run (nothing changed): ≈0.4 s, independent of bytes |
| **Time per scheduled round** | linear in `N` (sets run sequentially by default). **(derived)** `N=36` sets of this size, all quiescent: ≈36 × 0.4 s ≈ 15 s; each with 1% churn: ≈36 × 14 s ≈ 8.5 min | no cross-set lock contention; one busy set never blocks another |
| **Memory** | `F` of the *largest set being processed*: ≈70–90 MB RSS at 30k files (old + new manifests as Python dicts; **measured**). With sequential sets, peak is flat in `N`; `--jobs J` would multiply it by J | independent of file size (chunked copy) and of `N` |
| **Disk** | first snapshot ≈ source size; each later snapshot ≈ `ΔB` of unique file versions + directory entries for all `F` files + a manifest (**6.3 MB per 30k files**, measured). Worst case manifests `≈ S × 6.3 MB ≈ 170 MB` per 30k-file set, plus up to `S` snapshots worth of changed versions; linear in `N` | unchanged files cost no data blocks, however many snapshots reference them; the *count* of snapshots is bounded by retention, not by run frequency (no-op runs create none) |
| **Open fds / locks** | one lock fd per set in flight | no per-file handles retained |

The manifest overhead is the one non-flat disk item per snapshot; if it
matters, gzip it (≈5–8× on this JSON, not measured) at the cost of
`verify`/restore needing to decompress.

---

## 12. Tests required before this is "done"

Existing `test_synccli.py` must pass unchanged (`python3 -m unittest`).
New `test_backupctl.py` (stdlib `unittest`, temp dirs), at least:

* `scan_files` equivalence for roots `"x"`, `"x/"`, `"./x"` (the `relpath`
  replacement) and defaults preserve today's output; `include_hidden`,
  `onerror`.
* **Crash injection:** kill (a `KeyboardInterrupt`/`os._exit` hook) at every
  numbered step in §4; assert `snapshots/` contains only complete snapshots
  and the next run finishes with no manual step.
* **Concurrency:** two processes on one set (one gets exit 75); a reader
  looping over `snapshots/` while a run publishes sees only complete,
  manifest-consistent trees; prune vs a held lease skips; prune vs reader
  that took a lease never loses the files.
* **Source faults:** file vanishing between scan and copy (hook in
  `copy_regular`), `chmod 0` file, unreadable dir, FIFO, dangling symlink,
  file growing during copy → `unstable`; each asserts tree contents,
  `skipped`, status, exit code, and that the next run retries.
* **Change detection:** `utime`-restored same-size edit is caught; racy file
  is recopied next run; older-mtime replacement is caught; `--rehash` finds a
  stat-invisible edit.
* **Retention:** a table of `seq/finished_at` → expected kept set; G1/G2
  with all-partial history; corrupt snapshot never deleted; failed run doesn't
  prune.
* Empty/unmounted-source guard.

---

## 13. Known limits and open decisions

1. Snapshot files are hard-linked and therefore **must never be written in
   place**; the 0444 mode is a guard against casual `>` redirects, not
   against root or a restore tool that "restores" by opening a snapshot file
   for writing. The restore tooling's contract (read-only, lease) should be
   written down with its owners.
2. No cross-file point-in-time guarantee (§5). Needs a source-side filesystem
   snapshot; not in scope.
3. Metadata coverage: mode, mtime, symlinks, empty dirs yes; ownership,
   xattrs/ACLs, hard-link relationships *within the source* and sparse-ness
   no (not needed for the evals results; say if they are).
4. Retention numbers (5 / 14 days / 8 weeks) are defaults I chose, not
   derived from the workload; easy to change.
5. The three `synccli.py` edits in §2 and the decision about fixing
   `synccli`'s own silent-failure and torn-manifest bugs are yours to make.
6. Linux and cold-cache performance are unmeasured (§10).

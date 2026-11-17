# DESIGN — `backupctl` (fixture D1)

A command-line backup tool for the `evals/` result directories: it produces
point-in-time snapshots of a configured set of source directories under a
backup root, incrementally (only what changed), safely under concurrency,
crashes, missing source files and retention pressure.

This document is the design only; no code is written here. Where it changes
behaviour of code that already exists in this directory, the exact function and
the reason are named.

---

## 1. Summary of the design

* **Snapshots are directories.** `<backup_root>/snap-<UTC>-<seq>/` (the naming
  scheme already implemented in `snaputil.list_snapshots`,
  `snaputil.py:8`). Each snapshot holds a **materialized tree** of the source
  directories under `data/<source_id>/`, plus a **line-oriented index**
  `index.jsonl` and a completion record `meta.json`.
* **Publication is atomic.** A run builds the whole snapshot in a staging
  directory and publishes it with a single `os.rename()` into place. A reader
  therefore never sees a half-built snapshot; a reader either sees the old
  world or the new one.
* **Runs are serialized per backup root** by an advisory `flock` on
  `<backup_root>/.lock`. Two runs (scheduler + human) cannot interleave: the
  second one exits with `EX_TEMPFAIL` (75) and says so.
* **Incremental by hardlink, not by re-copy.** Files whose source state is
  unchanged since the last published snapshot are **hardlinked** from that
  snapshot instead of being copied again; only changed files are read and
  written. Content bytes are therefore read/written only for changed files.
* **The last published snapshot is the baseline.** There is no separate mutable
  "state file" that a crash could corrupt; the baseline is an immutable,
  atomically published artifact.
* **Retention = unpublish, then delete.** A snapshot is first renamed out of
  the `snap-*` namespace (so no new reader can resolve it), then deleted, and
  only if no reader holds it. The newest `keep` snapshots are never deleted.
* **Missing / unreadable source files are recorded, not hidden.** The copy
  routine's current silent `except OSError: pass` is overridden: the file is
  omitted from the tree and recorded in the index as `missing`, and the run
  reports it. The index never promises a file the snapshot does not contain.
* **Recovery is defined for a corrupt index.** The index is re-derived from the
  snapshot's own tree (`synccli.scan_files` + `synccli.file_state`), the
  snapshot is republished with a new digest, and the run reports it.

Everything below is specified with measured constants; the measurement
environment and the raw numbers are in §11.

---

## 2. Grounding: what exists here, and what this design changes

### 2.1 Reused as-is

| Existing code | Used for |
|---|---|
| `synccli.scan_files(root)` — `synccli.py:10` | Enumerating relative paths under a root, sorted. The basis of the tree walk and of the index re-derivation. |
| `synccli.build_manifest(root)` — `synccli.py:28` | Building `{relpath: state}` for a source directory; the state dict shape is the basis of the index record. |
| `synccli.changed_files(old, new)` — `synccli.py:36` | The **rule** for "what changed": a path is changed if it is absent from `old` or its state differs. Our streaming diff (§7.2) implements exactly this rule and is verified against this function by a property test (§12). |
| `synccli.file_state(path)` — `synccli.py:22` | The state of one file: `{"size", "mtime"}`. Basis of the record's size/mtime fields. |
| `snaputil.list_snapshots(root)` — `snaputil.py:8` | Enumerating and ordering snapshots (oldest first). Used unchanged for listing, for choosing the baseline, and for retention selection. |
| `snaputil.snapshot_disk_usage(root, name)` — `snaputil.py:39` | Reporting a snapshot's on-disk bytes. Works unchanged because snapshots are materialized directories. |
| `snaputil.safe_snapshot_path(root, name, rel)` — `snaputil.py:54` | Mapping an index path back to a file inside a snapshot; used by the restore contract (§10). |
| `snaputil.is_stale(snapshot_dir, ref_epoch)` — `snaputil.py:66` | Age test used by the retention grace period. |
| `test_synccli.py` (6 tests, `python3 -m unittest` → **OK**, 0.005 s) | Regression baseline. Every change this design proposes to `synccli.py` is additive with a default that preserves today's behaviour, so this suite must keep passing unchanged. |

### 2.2 Overridden, with the reason

| Existing behaviour | Where | Why it must change | Replacement |
|---|---|---|---|
| Hidden directories are silently skipped (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`) | `synccli.py:14` | A backup that silently drops `.git/`, `.cache/`, `.ipynb_checkpoints/` is a data-losing backup. The tool must not lose files silently. | `scan_files(root, include_hidden=False)` — additive keyword; `backupctl` always passes `include_hidden=True`. Default unchanged, existing test (`test_synccli.py:17`) unaffected. |
| `st_mtime` returned as a float | `synccli.py:25` | float64 at epoch ~1.7e9 s has ~5e-7 s resolution, so sub-microsecond mtime differences are lost; change detection then misses a rewrite. | `file_state(path, digest=False)` returns `mtime_ns` (integer) alongside `size`; `backupctl` compares `(size, mtime_ns, type)`. Default record shape extended, existing behaviour of `size`/`mtime` preserved. |
| `copy_file` swallows `OSError` and silently skips the file (`except OSError: pass`) | `synccli.py:67-69` | A vanished or unreadable source would produce a snapshot that silently lacks a file, with no trace in the index or the report. | New `backupctl.copy_file_checked(src, dst)` returns a status (`copied` / `vanished` / `unreadable`) instead of swallowing the error. `synccli.copy_file` is left untouched for its other user. |
| `copy_file` reads the whole file into memory (`fdst.write(fsrc.read())`) | `synccli.py:67` | Peak RSS measured **1086 MB** for a single 1 GiB file (measured, §11.3). Backup memory must be O(1) in file size. | `copy_file_checked` streams in 1 MiB chunks and hashes while streaming. |
| `copy_file` does not preserve mtime and writes directly to the destination path | `synccli.py:62-69` | (a) Without `os.utime`, the copy's mtime is the copy time, so a snapshot's tree no longer mirrors the source and the index cannot be re-derived from the tree (§9.3). (b) Writing directly to the final path means an interrupted copy leaves a **truncated file** that looks like a real file. | `copy_file_checked` writes to `<dst>.part`, `os.utime`s the copy from the source, and `os.replace`s it into place — atomic per file, and no truncated file can ever appear under a published path. |
| `prune_snapshots` deletes in place with no reader coordination and no age grace | `snaputil.py:23` | (a) A restore reading the snapshot being deleted can see files vanish mid-read. (b) The snapshot it is about to delete may have been resolved by a reader seconds earlier. (c) It has no notion of "the last usable snapshot". | `backupctl.prune_with_retention(...)` — see §9. It *uses* `snaputil.list_snapshots` for ordering and `snaputil.is_stale` for the age test, and overrides only the deletion procedure. |
| `sync()` writes the manifest in place with `open(..., "w")` and no fsync | `synccli.py:85` | A crash mid-write leaves a truncated manifest — the exact "half-written index" the brief asks about. | Not used for snapshots. Snapshots use the staged-write + `os.replace` + fsync sequence (§8). |
| `collect_stale` | `synccli.py:45` | It solves a different problem (marking freshness of a list); no role in the backup diff. It is left alone. | — |

### 2.3 Not used, and why

`synccli.sync()` (`synccli.py:72`) is a *mirror* into a fixed destination
directory, not a snapshot producer: it mutates its destination in place, keeps
exactly one manifest, and has no notion of generations. `backupctl` needs
immutable, append-only generations, so `sync()` is not used as the engine; its
building blocks (`scan_files`, `build_manifest`, `changed_files`, `file_state`)
are.

---

## 3. On-disk layout

```
<backup_root>/
  .lock                       # the run lock (flock). Also holds the pid/started-at of the holder.
  .locks/
    snap-20261116-190000-00.lock   # per-snapshot reader/pruner lock (flock)
  snap-20261116-190000-00/   # a PUBLISHED snapshot (visible to snaputil.list_snapshots)
      data/
        evals/                # one materialized tree per configured source id
          run-0001/
            result.json
        models/               # second configured source id
      index.jsonl             # the index (one JSON record per line, sorted by path)
      meta.json               # completion record: state, counts, index_sha256, run metadata
  .staging/                   # in-progress runs (never matches "snap-*" → invisible to readers)
      snap-20261116-190500-01/
        .owner.lock           # flock held by the owning process for the run's lifetime
        data/ ... index.jsonl meta.json
  .trash/                     # snapshots unpublished but not yet deleted
  quarantine/                 # snapshots quarantined after an integrity failure
  logs/
    snap-20261116-190500-01.log
```

* **Source ids.** Each configured source directory gets a stable id (`evals`,
  `models`, …) taken from its key in the configuration file. The id, not the
  path, is the namespace inside `data/`, so a source can move on disk without
  invalidating the baseline.
* **Why `.staging`, `.trash`, `quarantine` are safe names.**
  `snaputil.list_snapshots` (`snaputil.py:17-19`) only accepts entries that
  `startswith("snap-")` **and** are directories. `.staging`, `.trash`,
  `quarantine` and `.locks` do not match, so no reader that uses the shipped
  helper can ever resolve an unpublished artifact as a snapshot.
* **Nothing outside `<backup_root>` is written.** Blob/duplication sharing is
  achieved by hardlinks *inside* the root, so a snapshot can never reference a
  file the reader cannot see.

---

## 4. The index

`index.jsonl` — UTF-8, one JSON object per line, LF-terminated, **sorted by
`(source_id, relpath)`**. Sorted order is not cosmetic: it is what makes the
diff a streaming merge (§7.2) and therefore O(1) in memory.

Header record (first line):

```json
{"record":"snapshot","index_version":1,"snapshot_id":"snap-20261116-190000-00",
 "created_utc":"2026-11-16T19:00:00Z","source_ids":["evals","models"],
 "file_count":30010,"byte_count":1073741824}
```

Then one record per path:

```json
{"record":"path","source_id":"evals","relpath":"run-0001/result.json",
 "type":"file","size":1234,"mtime_ns":1763312400123456789,"mode":"0644",
 "sha256":"e3b0c4…","origin":"copied"}
```

Field semantics:

| field | meaning |
|---|---|
| `type` | `file`, `dir`, `symlink`, `missing`, `skipped` |
| `size`, `mtime_ns` | the source file's state at the time the record was taken (`stat`, `lstat` for symlinks) — this is the change-detection state |
| `mode` | permission bits, to be restored |
| `sha256` | digest of the file's **content**; `null` when it was not computed (§7.3) |
| `origin` | `copied` (bytes read from the source during this run), `shared` (hardlinked from the baseline snapshot; content is byte-identical to the baseline, whose digest was computed from the source in an earlier run), `missing`, `skipped` |
| `target` | for `symlink`, the link target |

**The index never promises a file the snapshot does not contain.** Every
`type: file` record has a corresponding real file in `data/`, checked by a
`stat`+size check of every staged path before publication (§8.5, measured
6–27 µs per file). Records for files that vanished or were unreadable carry
`type: missing` and no path in the tree — they describe an *absence*, which is
exactly what the run saw.

---

## 5. Configuration

JSON, one file, used identically by the scheduler and by a human:

```json
{
  "backup_root": "/var/backups/evals",
  "sources": [
    {"id": "evals",  "path": "/srv/evals"},
    {"id": "models", "path": "/srv/models"}
  ],
  "keep": 7,
  "min_age_seconds": 300,
  "fsync": "none",
  "immutable": false
}
```

* `keep` ≥ 1 is enforced (usage error otherwise) — the retention rule can never
  leave the user without a usable snapshot.
* `min_age_seconds` is the grace period during which a snapshot is never
  deleted even if it is over the retention count (§9).
* `fsync`: `none` (default, see §8.3) or `files` (per-file durability against
  machine crash).
* `immutable`: also chmod published files to `0444` (§9.3).

---

## 6. Concurrency

### 6.1 The run lock

`<backup_root>/.lock`, opened `O_CREAT|O_RDWR`, locked with
`fcntl.flock(fd, LOCK_EX|LOCK_NB)`.

* **Acquire succeeds** → this process owns the root. It writes its pid and
  start time into the lock file for diagnostics (the flock, not the file
  content, is the authority).
* **Acquire fails (`EWOULDBLOCK`)** → another run is in progress. The run
  prints `run skipped: backup root is locked by pid <pid> since <ts>` and exits
  **75** (`EX_TEMPFAIL`). It does not queue, does not wait, and does not
  partially write anything.

`flock` is used rather than a pidfile because **the kernel releases it when the
holder dies**. A run killed with SIGKILL leaves the lock free; there is no
stale-lock cleanup to do and the next run proceeds immediately. This is the
reason "the next run must make progress without manual cleanup" holds for the
lock specifically.

The lock file is never deleted (deleting it would create a race where two
processes hold different inodes). Documented assumption: the backup root is on
a local POSIX filesystem; `flock` semantics over NFS are unreliable.

### 6.2 Readers and the pruner

Each published snapshot has a lock file `<backup_root>/.locks/<snapshot>.lock`.

* A **reader** (the separate restore tool, `backupctl show/verify`) takes
  `LOCK_SH` on it for the duration of its read.
* The **pruner** takes `LOCK_EX` on it before unpublishing/deleting that
  snapshot; if it cannot get the lock within the prune timeout it **defers**
  the deletion to a later run and reports it.

Shared locks are compatible with each other, so many readers can restore
concurrently, and the run lock (§6.1) is independent of them — a restore can
read a snapshot **while a run is building the next one**.

### 6.3 The run vs. the pruner

A run reads the baseline snapshot to hardlink unchanged files from it. If the
pruner deleted the baseline mid-run, those links would fail with `ENOENT`.
Therefore a run holds a **shared** lock on the baseline snapshot's lock file
for as long as it links from it. The pruner then defers that snapshot.

### 6.4 The run vs. another run

Impossible by construction: the run lock is exclusive. A run therefore never
races another run over the staging area, the snapshot names, the retention
decision, or the garbage collection.

### 6.5 Two runs and the same snapshot id

Snapshot ids embed a UTC timestamp with second resolution plus a sequence
number, `snap-<YYYYMMDD>-<HHMMSS>-<NN>`. The sequence number is chosen under
the run lock by probing `snaputil.list_snapshots` for the next free value in
`00..99`, so ids are unique and sort oldest-first (fixed-width fields ⇒
lexicographic order is chronological order). Because the run lock is held,
there is no race on id allocation.

---

## 7. Change detection

### 7.1 The granularity

**Decision unit: one whole file.** A file is "unchanged" iff its source
`(size, mtime_ns)` equals the `(size, mtime_ns)` recorded in the baseline
snapshot's index for the same `(source_id, relpath)`. This is exactly
`synccli.changed_files`'s equality test, applied to our richer state record
(`synccli.py:40`).

Directories are not change-detected by content (their children are); empty
directories are recorded and recreated. Symlinks are detected by their own
`lstat` mtime/target. Special files (fifo, socket, device) are never copied —
they are recorded as `skipped` and reported.

### 7.2 How the diff is computed (and why it is O(1) in memory)

The baseline index is sorted by `(source_id, relpath)`; the new scan is sorted
by `relpath` (`synccli.scan_files` returns a sorted list, `synccli.py:19`).
The diff is therefore a **streaming merge**: read the next record from the
baseline index, take the next path from the scan, compare states, emit
"changed" when the state differs or the path is new.

Memory is O(1) records. The alternative — loading both manifests as dicts,
which is what `synccli.changed_files` (`synccli.py:36`) does — measured
**1199 bytes of Python objects per entry** (tracemalloc, 30 000 entries), i.e.
36 MB at F = 30 000 and 1.2 GB at F = 1 000 000. The streaming merge is
therefore not an optimization but a bound: it keeps the tool usable as the
tree grows. §12 adds a property test that the streaming merge and
`synccli.changed_files` agree on every path of randomly generated trees.

### 7.3 What the granularity misses, and the optional stronger mode

With the default `(size, mtime_ns)` test, the following edits are **missed**
(the source is considered unchanged and the baseline's content is reused):

1. Content rewritten **in place** with the same length and the mtime restored
   afterwards (`touch -r`, `cp -p` onto the same path, a build system that
   sets timestamps, a `git checkout` of a file whose blob is the same length).
2. Two writes inside the filesystem's mtime granularity. On APFS/ext4 mtime is
   nanosecond-resolution and `st_mtime_ns` is compared exactly; on a
   filesystem with 1-second mtime granularity (some network filesystems) two
   writes in the same second are indistinguishable.
3. A file replaced by a different file of identical length with an identical
   mtime — same mechanism as (1).

`--rehash` closes (1)–(3) by hashing every source file and comparing the
digest with the baseline's `sha256`; a mismatch forces a copy even when
`(size, mtime_ns)` matches. Measured cost: **54 µs per small file** (30 000 ×
16 KiB in 1.63 s) and **0.45 s per GiB** (sha256 at 2.2 GiB/s, warm cache) —
i.e. much cheaper than copying (335 µs/file), so it is affordable; it is
simply not the default because the default must also be safe against a source
that is *being written* while we hash it.

Even with `--rehash`, an edit that happens *during* the run (between the hash
and the copy, or after the copy) is not detected. This is inherent to any
userspace copier; the design does not claim otherwise.

### 7.4 The race window during a copy

For each file to copy, `backupctl` stats the source **before** the copy
(deciding) and **after** the copy (recording). If the post-copy state differs
from the pre-copy state, the file changed while we were reading it; the file
is copied **once more** (at most two attempts) and, if it still races, the
record is marked `"racy": true` and reported. The recorded state is always the
post-copy state, so the next run compares against what we actually captured.

### 7.5 The baseline

The baseline for a source `d` is the **newest published snapshot whose index
contains records for `d`**. If the newest published snapshot has no record for
`d` (e.g. that source was unreadable during that run), the next older
snapshot that has one is used; if none exists, `d` is backed up in full.
Choosing the baseline from published snapshots — rather than from a separate
mutable state file — means a crashed run cannot corrupt the change-detection
state: an unpublished run contributes nothing to the baseline.

---

## 8. The run algorithm

`backupctl run` (identical for scheduler and human):

1. **Acquire** the run lock (§6.1). On failure: report and exit 75.
2. **Recover** (§9.2): remove stale staging directories, quarantine or rebuild
   broken snapshots, delete leftover `.trash` entries.
3. **Choose the baseline** (§7.5) and take a shared lock on its snapshot lock
   (§6.3).
4. **Create the staging directory** `<root>/.staging/<run-id>/`, create
   `.owner.lock` and hold an exclusive flock on it for the run's lifetime
   (a dead owner releases it automatically ⇒ the next run can identify and
   discard the wreckage).
5. **For each configured source** (in configuration order):
   a. Walk the source with `synccli.scan_files(root, include_hidden=True)`
      (additive keyword; §2.2). A source that cannot be listed (e.g. `EACCES`)
      is recorded as an unreadable source in the report; the run continues
      with the other sources.
   b. Compute the diff against the baseline (§7.2), streaming.
   c. For each **unchanged** path: create the tree entry by **hardlinking** the
      baseline's file into the staging tree; record `origin: shared`. If the
      link fails (`EXDEV` across devices, `EPERM`, `EMLINK` when the inode's
      link count is exhausted, or the baseline vanished), fall back to copying
      the file from the source and record `origin: copied` — the snapshot is
      still correct, only less space-efficient.
   d. For each **changed or new** path: `copy_file_checked` (streamed, hashed,
      `.part` + `os.replace`, `os.utime`) into the staging tree; record the
      post-copy state and the digest.
   e. For each path that **vanished** or was **unreadable**: record
      `type: missing` with the reason; no file is created in the tree.
   f. Recreate **empty directories** and their modes; record symlinks as
      symlinks (`lstat`).
6. **Write the index** `index.jsonl` into staging, in sorted order, streaming
   (never held fully in memory). fsync the file.
7. **Verify the staging tree** (§8.5).
8. **Write `meta.json`** with `state: "complete"`, `index_sha256`, counts and
   run metadata; fsync it; fsync the staging directory.
9. **Publish**: `os.rename(staging, <root>/<run-id>)` — a single atomic
   directory rename; fsync `<root>`.
10. **Retain**: prune per §9.
11. **Report** (§11.5) and exit 0.

### 8.1 Why the publish is atomic

`os.rename` of a directory onto a non-existing name in the same directory is
atomic: the name either does not exist or exists with the complete contents.
Combined with the staging directory never matching `snap-*`, a reader using
`snaputil.list_snapshots` can only ever see a fully published snapshot.

### 8.2 What a crash leaves behind

| Crash point | What is on disk | What a reader sees | Next run |
|---|---|---|---|
| During the source walk / copying | `.staging/<run-id>/` with partial data and `*.part` files | nothing (the name is not `snap-*`) | the staging dir's owner lock is free ⇒ it is deleted and reported |
| After the index is written, before `meta.json` | staging dir with `index.jsonl` but no `meta.json` | nothing | same as above: deleted, reported as "incomplete run discarded" |
| After `meta.json`, before the rename | staging dir that *looks* complete | nothing | the run lock is free; the owner lock is free ⇒ **deleted**, and a fresh run starts from the last published snapshot. This costs one run's work; it never produces a bad snapshot. |
| During the rename | rename is atomic ⇒ either fully there or not | either the old world or the new snapshot | — |
| After the rename, before retention | a complete snapshot | the new snapshot | retention runs on the next run |

The rule that makes this work: **a snapshot directory exists under a `snap-*`
name only if it was complete at the instant it was renamed there.**

### 8.3 Durability: why the default does not fsync every file

The failure model in the brief is *process* death (Ctrl-C, sleep, SIGKILL).
Data that has been `write()`n is in the page cache and survives process death;
it only disappears on a machine crash / power loss. The default therefore
fsyncs **directories and the index** (cheap: 33 µs per directory, 150 dirs =
5 ms) but not every data file.

`--fsync files` adds a per-file `fsync` and buys durability against power
loss at a measured **+873 µs per file** (36.25 s vs 10.05 s for 30 000
files) — a 3.6× slowdown. The trade-off is explicit and documented rather than
buried in a default.

### 8.4 The `.part` discipline

Every data file is written as `<final>.part` and `os.replace`d into place, so
a copy interrupted by SIGKILL leaves a `.part` file, never a truncated file
under a published name. `.part` files never appear in the index and are
removed with the staging directory.

### 8.5 The publish-time verification

Before `meta.json` is written, the run verifies the staged tree against the
index: for every `type: file` record, `stat` the staged path and compare the
size; count the files found in the tree and compare with the index's record
count. Cost: one `stat` per file, measured **6–27 µs** (0.08–0.18 s for
30 000 files). A mismatch aborts the run (no snapshot published, exit 1).

### 8.6 Missing and unreadable source files — the exact rule

Grounded on the fact that `synccli.copy_file` currently swallows `OSError`
(`synccli.py:67-69`); `copy_file_checked` returns a status instead.

* The file vanished between the walk and the copy (`ENOENT` on open) →
  the record is `{"type":"missing","reason":"vanished"}`; **no file is created
  in the tree**; the run reports it.
* The file cannot be read (`EACCES`, `EPERM`, `EIO`) → the record is
  `{"type":"missing","reason":"unreadable"}`; same treatment.
* The file changed while being copied (size/mtime differ before vs. after)
  → retried once (§7.4); if it still races, the record carries
  `"racy": true` and the file that was captured is stored (it is a complete
  file, just possibly an older version than the source's current state).
* A source **directory** that cannot be listed → the whole directory is
  recorded as missing/unreadable and reported; other directories continue.

What the snapshot then contains: everything that could be read, plus the
*absence* of what could not. What the run reports: a count and one line per
affected path, in both stdout and the run log. The exit code stays **0** (the
snapshot was published and is usable) — the report is the signal. A strict
deployment can use `--strict-missing` to turn any missing/skipped file into
exit code 1; this flag is a property of the invocation, never of the
*trigger*: the scheduler and the human get the same semantics for the same
arguments.

---

## 9. Retention and deletion

### 9.1 The rule

Snapshots are ordered oldest-first by `snaputil.list_snapshots`
(`snaputil.py:8`). With `keep = K`:

* the newest `K` snapshots are **never** deleted;
* among the older ones, the oldest are deleted first;
* `K ≥ 1` is enforced, so a usable snapshot always remains;
* a snapshot younger than `min_age_seconds` is **deferred**, not deleted
  (grace period protecting readers that resolved it moments ago);
* a snapshot a reader currently holds (shared lock) is **deferred** — the
  pruner takes the exclusive lock with a timeout and gives up if it cannot
  get it.

### 9.2 The deletion procedure (overriding `snaputil.prune_snapshots`)

`snaputil.prune_snapshots` (`snaputil.py:23`) does `shutil.rmtree` directly on
the snapshot directory. That is unsafe while a reader may be reading it and
unsafe while a run may be hardlinking from it. `backupctl.prune_with_retention`
keeps the *selection* rule and replaces the *execution*:

1. `names = snaputil.list_snapshots(root)` — unchanged.
2. `doomed = names[:len(names) - keep]` — unchanged rule.
3. For each candidate, oldest first:
   a. if `snaputil.is_stale(snapshot_dir, now - min_age)` is `False` (too
      young) → defer, report;
   b. acquire `LOCK_EX` on `<root>/.locks/<name>.lock` with a timeout; on
      failure → defer, report;
   c. **unpublish**: `os.rename(<root>/<name>, <root>/.trash/<name>.<run-id>)`
      — atomic; the name is now outside the `snap-*` namespace, so
      `snaputil.list_snapshots` no longer offers it and no *new* reader can
      resolve it;
   d. delete the trash directory: `shutil.rmtree` with an `onerror` handler
      that chmods read-only directories back to writable first (published
      directories are `0555`, §9.3). Measured: 2.84 s for a 30 000-file tree,
      plus ~150 directory chmods;
   e. release the lock.
4. Report deleted / deferred names.

**Why this is safe for a reader.** A reader that has already opened files
keeps them alive: POSIX keeps an unlinked file readable through an open file
descriptor, and the reader's shared lock prevents the pruner from getting the
exclusive lock at all while the reader is inside. A reader that resolved a
snapshot name but has not yet taken the lock may find it gone — the reader
protocol (§10.2) handles this by taking the lock first and re-resolving.

**Hardlink sharing and deletion.** Because unchanged files are shared by
inode between snapshots, deleting one snapshot frees only the inodes that no
other snapshot references. `shutil.rmtree` unlinks the names; the content
survives as long as another snapshot links to it. This is why deletion can
never damage a *different* snapshot.

### 9.3 Hardening published snapshots

Published snapshot directories are `chmod 0555` and their files `0644`
(measured: 150 directory chmods ≈ negligible). This prevents a stray writer
from *adding or removing* entries (that needs write permission on the
directory). With `--immutable` the files are also `0444` (+2.16 s per 30 000
files, measured) to prevent in-place modification — worth having precisely
because a shared inode is modified in every snapshot at once.

### 9.4 What "the backup root only ever grows" means here

The root grows monotonically in *content* (blobs are only ever added; a
snapshot's data is never rewritten) and shrinks only through retention, which
is bounded by the rules above. There is no in-place mutation of a published
snapshot: new snapshots are built in staging and published by rename, and
retention only ever removes whole snapshots.

---

## 10. The reader contract (for the separate restore tooling)

### 10.1 Listing

`snaputil.list_snapshots(root)` — unchanged. Optional extra: `backupctl show
<snapshot>` prints the index header and a human-readable tree.

### 10.2 Reading a snapshot safely

```
1. names = snaputil.list_snapshots(root)
2. pick the name the user asked for; if it is not in names → "no such snapshot"
3. open <root>/.locks/<name>.lock; flock(LOCK_SH)          # blocks the pruner
4. re-check that <root>/<name> exists; if not → it was pruned between 1 and 3:
   re-resolve (step 1) or report "snapshot was pruned concurrently"
5. read meta.json → require state == "complete"           # else report
6. read index.jsonl, streaming:
   for each record:
       src = snaputil.safe_snapshot_path(root, name, rec.path)   # snaputil.py:54
       copy src → destination, recreating directories; set mtime and mode
       (optional) verify sha256(src) == rec.sha256
7. release the shared lock
```

`safe_snapshot_path` (`snaputil.py:54`) is what makes step 6 safe against a
malicious or corrupted index: the path is normalized, so a stored `..`
segment cannot climb out of the snapshot.

Because snapshots are materialized and hardlink-shared, the restore is an
ordinary file copy — no index-to-blob resolution, no special tooling.

---

## 11. Performance: the budget and where the numbers come from

### 11.1 Measurement environment

All numbers below were measured on **this machine** — macOS (darwin), APFS,
Python 3.10.11 — with the working tree on the `/var/folders/...` volume, warm
page cache. The measurement scripts used `synccli`'s own functions
(`scan_files`, `build_manifest`, `copy_file`) and equivalents of the proposed
routines. Raw constants:

| Constant | Measured | How |
|---|---|---|
| `c_scan` — enumerate paths | 0.185 s / 30 000 files (6.2 µs/file) | `synccli.scan_files` over a 30 000-file tree |
| `c_stat` — `stat` one file | 0.08–0.18 s / 30 000 (2.7–6 µs) | `os.stat` loop |
| `c_manifest` — walk + stat (the per-source manifest) | 0.68–0.82 s / 30 000 | `synccli.build_manifest` |
| `c_copy` — stream + sha256 + `utime`, **no** fsync | 335 µs/file | 30 000 × 16 KiB in 10.05 s |
| `c_copy` with per-file fsync | 1208 µs/file (fsync adds 873 µs) | same tree in 36.25 s |
| `c_link` — hardlink | 377 µs/file (11.43 s / 30 000) | `os.link`; `cp -al` of the whole tree: 11.43 s |
| `c_link` on a different volume (home dir) | 1056 µs/file | same, on `~/` |
| `c_dirfsync` — fsync a directory | 33 µs (150 dirs = 5 ms) | `os.fsync` on dir fds |
| `c_hash` — sha256 of a small file | 54 µs/file (30 000 × 16 KiB in 1.63 s) | hashlib |
| `c_hash` — sha256 throughput | 0.45 s / GiB (2.2 GiB/s, warm) | 1 GiB file |
| `c_index` — write a JSONL index record | 1.3 µs/record (30 000 records = 0.04 s, 4.53 MB) | measured |
| `c_index` — read + parse | 1.0 µs/record (0.03 s / 30 000) | measured |
| index size | 219 B/record → 4.53 MB / 30 000 files | measured |
| in-memory manifest cost | 1199 B/entry → 36 MB / 30 000 entries | tracemalloc |
| `c_delete` — delete a snapshot | 2.84 s / 30 000 files | `shutil.rmtree` |
| `c_chmod` — chmod 30 000 files | 2.16 s | `os.chmod` loop |
| `synccli.copy_file` peak RSS on a 1 GiB file | **1086 MB** | `ru_maxrss` — the reason for streaming |

Reference: the shipped test suite passes — `python3 -m unittest` → 6 tests, OK,
0.005 s.

### 11.2 The initial full backup: ~1 GiB, ~30 000 files

Term by term, using the measured constants (average file size 34 KiB; the
byte term is `B / throughput`):

| Term | Formula | Value |
|---|---|---|
| walk + stat | `F × c_manifest` | 0.82 s |
| copy + hash + `utime` | `F × c_copy` + `B/r` | 30 000 × 335 µs = 10.05 s + ~0.5 s (1 GiB at 2.2 GiB/s, warm) |
| index write | `F × c_index` | 0.04 s (4.53 MB) |
| index fsync + dir fsyncs | `F_dirs × c_dirfsync` + 1 fsync | ≈ 0.01 s |
| publish verification (stat per file) | `F × c_stat` | 0.18 s |
| publish (rename + fsync of root) | — | < 0.01 s |
| **total (warm cache)** | | **≈ 11.6 s** |
| **total (cold cache, 200 MB/s source read)** | + (1 GiB / 200 MB/s − 0.5 s) | **≈ 16.5 s** |
| with `--fsync files` | + `F × 873 µs` | ≈ 37 s (warm) / ≈ 42 s (cold) |

**Budget: the initial full backup of a ~1 GiB / 30 000-file tree completes in
≤ 20 s** on the reference machine with the default policy (measured 11.6 s
warm, 16.5 s cold), and in ≤ 45 s with `--fsync files` (measured ~37 s warm).
The number is a measured sum of measured per-file constants, not an estimate;
the derivation is the table above and the constants are reproducible with the
scripts in §11.1.

Note where the time goes: **~90 % of the full backup is per-file overhead
(335 µs/file), not bytes** (1 GiB moves in ~0.5 s warm). A backup of 10 GiB
in the same 30 000-file shape would cost ≈ 11 s + 4.5 s ≈ 16 s; a backup of
the same 1 GiB in 300 000 files would cost ≈ 100 s. **File count, not byte
count, is the scaling driver** — which is exactly why the incremental path is
built around per-file metadata operations.

### 11.3 Memory

* Copy buffer: **1 MiB** (fixed) — this is why `copy_file_checked` streams
  instead of using `synccli.copy_file`'s whole-file `read()` (measured 1086 MB
  peak RSS on a 1 GiB file).
* Diff: **O(1) records** — a streaming merge of the sorted baseline index with
  the sorted source scan (§7.2).
* Index writing: **O(1)** — streamed to disk.
* Per-source state: O(1) per source; the configuration is O(N).

**Bound: peak RSS ≤ interpreter baseline + ~8 MB, independent of F (files),
of B (bytes) and of N (directories).** For comparison, the dict-based diff
(`synccli.changed_files`'s intended usage) costs 1199 B/entry → 36 MB at
F = 30 000 and 1.2 GB at F = 1 000 000.

### 11.4 What grows with what — explicit bounds

Let `N` = configured directories, `F` = total files, `B` = total bytes,
`C` = changed files, `Cb` = changed bytes, `S` = retained snapshots,
`U = F − C` = unchanged files.

**Per-run work**

| Quantity | Bound |
|---|---|
| Files examined (stat) | `F` — exactly, once per file (no re-walks) |
| Files read (bytes) | `Cb` — unchanged files are **not** read; only linked |
| Bytes written | `Cb` + 219 B × F (the index) |
| Hardlinks created | `U` (one per unchanged file) |
| Directory operations | `O(N)` config reads + `O(F_dirs)` directory creations |
| Retained snapshots after the run | `min(S+1, keep)` — flat in F and B |

**Per-run wall time (default policy, warm cache)**

```
T ≈ N·t_src_open
  + F·c_stat                    (6 µs)     ← the scan
  + U·c_link                    (377 µs)   ← dominated by filesystem metadata cost
  + C·c_copy                    (335 µs)
  + Cb/r_read + Cb/r_write
  + F·c_index                   (1.3 µs)
  + F·c_verify                  (6 µs)
```

At `N = 3`, `F = 30 000`, `B = 1 GiB`, `C = 0`: `T ≈ 0.8 + 11.3 + 0.04 + 0.18 ≈ 12.3 s`.
At `C = F` (everything changed): `T ≈ 0.8 + 10.0 + 0.2 + 0.5 ≈ 11.5 s` — i.e. an
incremental run with no changes is *not* cheaper than a full run on this
filesystem, because both are dominated by ~F metadata operations of the same
order. That is an honest property of a materialized, hardlink-shared layout on
a slow-metadata filesystem, and it is the reason the `c_link` constant is
called out explicitly: on a filesystem with 10–20 µs metadata ops (typical
ext4 on Linux), the same run is `F × 20 µs ≈ 0.6 s` instead of 11.3 s.

**Memory**: O(1) (§11.3).

**Disk**

| Quantity | Bound |
|---|---|
| Unique content | `≤ B` bytes (shared by hardlink; a changed file adds at most its new size) |
| Per-snapshot metadata overhead | `219 B × F` (index) + directory entries for `F` names ≈ `≈ 8 MB` at F = 30 000, i.e. ≈ 270 B per file per snapshot |
| Total root size at steady state | `S × F × 270 B + B_unique` → at S = 7, F = 30 000: ≈ 57 MB of metadata + the unique content |
| Growth per run | `+1` snapshot's metadata (`F × 270 B`) + the changed bytes; content grows only by genuinely new bytes |

**Scaling summary**

* Grows linearly with **F** (per-file metadata ops): scan, link, index,
  verify.
* Grows linearly with **B** only through the **changed** bytes: unchanged
  content is never read or written.
* Grows with **N** only through `O(N)` config reads and one index segment per
  source: `t_src_open ≈ 1 ms` per source (measured as part of `c_manifest`;
  a source with no files still costs one directory listing).
* Stays flat in **N** for memory, and flat in **F** for memory.

### 11.5 The report format

Line-oriented, stable, identical for every trigger, written to stdout **and**
to `<root>/logs/<run-id>.log`:

```
run start run_id=snap-20261116-190500-01 sources=3 trigger=cli
recovered discarded_staging=1 rebuilt_index=0 quarantined=0
scan source=evals files=30000 bytes=1073741824
copied files=12 bytes=131072
shared files=29988 links=29988
missing files=2 (evals/run-0007/a.json:vanished evals/run-0008/b.json:unreadable)
index records=30010 sha256=ab…
published snapshot=snap-20261116-190500-01 duration=11.4s
retention deleted=1 deferred=0
run ok snapshot=snap-20261116-190500-01
```

Exit codes:

| code | meaning |
|---|---|
| 0 | a snapshot was published (possibly with `missing`/`skipped` files, which are listed in the report) |
| 1 | the run failed; **no** snapshot was published (the staging directory is discarded) |
| 64 | usage or configuration error (e.g. `keep < 1`) |
| 75 | skipped: the backup root is locked by another run |

The scheduler and a human invoke the same `run` subcommand with the same
configuration file. There is no trigger-specific code path, no trigger-specific
default, and no "quiet" mode that changes the exit code: the only difference
is which scheduler fires the command.

---

## 12. Test plan

New file `test_backupctl.py` (the existing `test_synccli.py` continues to
pass unchanged — every proposed change to `synccli.py` is additive with a
behaviour-preserving default):

1. **Change detection equivalence** — property test over randomly generated
   trees: the streaming merge's changed-set equals `synccli.changed_files`
   (`synccli.py:36`) on the same two manifests.
2. **Second run copies nothing** — a second run over an unchanged tree copies
   0 bytes and creates only hardlinks; the index shows `origin: shared`.
3. **Granularity limit** — edit a file's content while restoring its old size
   and mtime: the default run reuses the old content (documented miss);
   `--rehash` detects the change and re-copies.
4. **Missing source file** — delete a file between the walk and the copy
   (monkeypatched): the snapshot has no file at that path, the index records
   `type: missing`, the report lists it, and the index never promises it.
5. **Unreadable source file** — `chmod 000` (skipped as root) or an injected
   `OSError`: same handling as (4).
6. **Concurrent runs** — fork a second `run` while the first holds the lock:
   the second exits 75 and writes nothing.
7. **Interrupted run** — SIGKILL the process mid-copy: no `snap-*` directory
   appears; the next run discards the staging directory, reports it, and
   publishes a fresh snapshot.
8. **Corrupt index recovery** — truncate `index.jsonl` of a published
   snapshot, then run `backupctl verify --repair`: the index is re-derived
   from the tree, the snapshot stays usable, the report says
   "index rebuilt from tree (N records, digests unknown)".
9. **Incomplete snapshot** — a snapshot directory without `meta.json` is
   quarantined (renamed into `quarantine/`) and reported; `list_snapshots` no
   longer returns it.
10. **Retention with a concurrent reader** — a reader holds the shared lock on
    the oldest snapshot: the pruner defers it (reports `deferred=1`) and
    deletes it on a later run when the reader is gone.
11. **Retention never empties the root** — with `keep = 1`, after 5 runs
    exactly one snapshot remains, and it is the newest.
12. **Restore contract** — restore a snapshot with mixed file/dir/symlink/
    missing records and check the destination tree, the mtimes, and the
    `safe_snapshot_path` mapping.
13. **Scale/perf smoke** — a synthetic 30 000-file tree: assert the
    incremental run copies 0 bytes and that the run's duration is within the
    §11.2 budget.

---

## 13. Alternatives considered and rejected

* **Blob store + per-snapshot index** (content-addressed, no materialized
  tree): incremental runs would touch only changed files — ~1 s instead of
  ~12 s at F = 30 000, because per-file metadata operations (377 µs each,
  measured) dominate. **Rejected** because the brief requires the index to be
  re-derivable *from the tree* (§8.5, §9.2): with a blob store, a lost index
  loses the path→content mapping and the snapshot is unrecoverable, whereas
  with a materialized tree the tree *is* the redundancy. It remains the
  natural next optimization if per-file metadata cost ever dominates.
* **Copying unchanged files instead of linking**: same per-file cost class
  (335 µs copy vs 377 µs link, measured) and it re-reads/re-writes bytes —
  strictly worse.
* **Directory-level reflinks (`cp -cR` / `FICLONE`)**: measured 9.27 s for
  30 000 files — no better than per-file links here, and not portable.
  Mentioned as an optional future optimization behind `--clone`.
* **A separate mutable state file** (like `synccli`'s `.sync_manifest.json`,
  `synccli.py:7`) to hold change-detection state: rejected — a crash can
  corrupt it, and the baseline would then be inconsistent with any snapshot.
  The last *published* snapshot is the baseline instead, so the state and the
  data share one atomic publication.
* **`synccli.sync()` as the engine** (`synccli.py:72`): it mirrors into a
  mutable destination and keeps one manifest; it cannot produce immutable
  generations. Its parts are reused, its whole is not.

---

## 14. Known limits (stated, not hidden)

* **Not an atomic point-in-time of the source.** Different files are captured
  at different moments during the run. A filesystem-level snapshot would be
  needed for true atomicity; that is out of scope and is not claimed.
* **Extended attributes, ACLs and macOS resource forks are not preserved.**
  Only `mode`, `mtime` and content are. Symlinks are preserved as symlinks
  (not followed).
* **Hardlink sharing means a published snapshot's files are shared inodes.**
  In-place modification of a file inside a published snapshot would corrupt
  every snapshot sharing it; `--immutable` (0444) prevents that, and the
  default (`0555` directories) prevents adding/removing entries.
* **The backup root must be on a local POSIX filesystem** (`flock` semantics
  and hardlinks across snapshots); NFS is not supported.
* **Per-file metadata cost is filesystem-dependent** (377 µs/file here, 1056
  µs/file on another volume of the same machine, ~10–20 µs/file on typical
  ext4). The budget in §11.2 is stated for the reference machine and the
  formula in §11.4 lets it be recomputed for another one.
* **The `keep` policy is count-based, not age-based.** A snapshot younger than
  `min_age_seconds` is never deleted, but an old snapshot can be deleted by
  count alone; a time-based policy (`keep_daily: 7`, `keep_weekly: 4`, …) is
  a natural extension of `prune_with_retention` and does not change the
  safety rules.

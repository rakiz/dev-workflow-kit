# DESIGN-d1 — `backupctl`

Status: design, no implementation. Scope: back up a configured set of
directories (`N` = 3 today, ~50 over time) into snapshots under a backup
root, safely under concurrent runs/restores, process death, unstable
sources, growth, and retention.

Everything numeric below was measured on this checkout's machine (Darwin
24.6.0, arm64/APFS, Python 3.10.11) or derived from those measurements;
the derivation and the script shape are in §11. Grounding claims about the
existing code were executed, not inferred — see §17.

---

## 1. Layout on disk

```
backup_root/
  sources/
    <source-id>/                 # source-id = slug + "-" + sha256(abs path)[:8]
      snap-0000000042-20261116T221500Z/    # the only entries a reader ever sees
        index.json                          # committed manifest (schema §13)
        data/                               # payload: 1:1 mirror of the source tree
          ...                               # (kept out of the snapshot root so a
                                            #  source file named index.json cannot collide)
      .tmp-<uuid4>/             # uncommitted run; invisible; contains LOCK + data/
      .trash/<uuid4>/           # tombstoned snapshot awaiting purge
      .locks/                   # run.lock, alloc.lock, seq, read-<snapname>.lock
      .runlog                   # append-only, O_APPEND, one line <= 4096 B
  .quarantine/<source-id>/<snapname>.<utcsec>/
```

Decisions embedded in the layout:

- **Per-source namespace.** `snaputil.list_snapshots` (snaputil.py:8) works on
  one directory, so each source lives in its own. Retention,
  sequence numbers, and locks are per source; one source can never starve or
  block another.
- **No global registry.** There is no `backup_root/index.json` and no `latest`
  symlink. Names are the truth; each snapshot self-describes. A global index
  is a mutable file that can promise files a snapshot does not contain and a
  single corruption point under concurrent runs — exactly what the brief
  forbids. `latest` is resolved by listing + sorting, never by a mutable
  pointer that could be repointed under a reader.
- **Name = `<seq:010d>-<UTC>Z`.** Sequence first, fixed width, so the plain
  `sorted()` at snaputil.py:20 is chronological **by publish order**, not by
  wall clock (immune to NTP steps/DST; UTC only for humans). Capacity 10^10
  snapshots per source (1 run/min ≈ 19,000 years). Names are never reused:
  the allocator's high-water mark is persisted in `.locks/seq` (atomic
  replace), so pruning or quarantining never recycles a name (§3, §4). This
  deliberately overrides the `snap-20261112-150000-07` ordering implied by
  snaputil.py:11-14 — with the old date-first, two-digit sequence, `-100`
  sorts before `-99`.
- **Payload under `data/`.** A source's own `index.json`/`data/` names cannot
  shadow metadata; restore maps `data/<rel>`.
- **Incomplete work never matches `snap-`.** `.tmp-*`, `.trash/`, `.locks/`,
  `.runlog` are all invisible to `list_snapshots` (startswith test at
  snaputil.py:18) *and* to the strict validator in §5. Two independent
  barriers, because the existing test at snaputil.py:17-19 is too weak (§2).

---

## 2. Grounding: what is reused, what is overridden and why

### 2.1 Reuse ledger (named file + function, purpose)

| Existing artifact | Lines | How `backupctl` builds on it |
|---|---|---|
| `synccli.scan_files` | synccli.py:10-19 | The enumerator contract for regular trees: recursive, **sorted** relative paths (the sort is what makes index diffs deterministic and lets `changed_files` be a simple dict walk). Reused verbatim when the source contains no dot-directories and no symlinked directories; `backupctl.scan` is a thin variant that keeps its output contract (sorted rel paths) and changes only the filter (§2.2). |
| `synccli.file_state` | synccli.py:22-25 | Reused as the *base* of the change key `{size, mtime}`; `backupctl.scan.file_state_v2` returns a superset (adds `mtime_ns`, `ino`, `ctime_ns`, `mode`, `type`) so `changed_files`' `!=` comparison keeps working unchanged. |
| `synccli.build_manifest` | synccli.py:28-33 | Reused as the reference shape `{relpath: state}` for both the previous index (loaded into this shape) and the new one. `backupctl` builds the same dict with `file_state_v2` values. |
| `synccli.changed_files` | synccli.py:36-42 | **Reused unchanged** as the change-set computation: iterate the new manifest, emit entries absent from the old one or with a different state. Returns the copy plan directly. Deletions need no branch: a snapshot is a full image, so a vanished source file is simply absent from the new index and the previous index is immutable. |
| `synccli.sync` (structure) | synccli.py:72-87 | Reused as the plan → copy → write-manifest sequence, and its `dry_run` early return (synccli.py:81-82) is reused verbatim for `backupctl run --dry-run` (prints the plan, writes nothing). Its manifest *commit* is replaced (§2.2). |
| `synccli.main` | synccli.py:90-99 | Reused CLI shape: `argparse`, returns an int exit code, prints one line per action. |
| `snaputil.list_snapshots` | snaputil.py:8-20 | Reused for enumeration + ordering (its `sorted()` at line 20 becomes correct once names are fixed-width seq-first, §1). `backupctl.retention` wraps it with the validator the docstring at snaputil.py:9-14 promises but the code does not implement. |
| `shutil.rmtree` (inside `snaputil.prune_snapshots`) | snaputil.py:35 | Kept as the deleter — it refuses to follow a symlink (verified), which is a useful safety property — but only ever called on a `.trash/<uuid>` path, never on a live `snap-*` path. |
| `test_synccli.py` style | test_synccli.py:1-55 | Reused as the test pattern: stdlib `unittest` + `tempfile.mkdtemp`, function-level fixtures, `python3 -m unittest`. The existing 6 tests were run and pass (0.006 s), and the suite is extended, not replaced (§15). |

### 2.2 Overrides (exact function, exact line, exact reason)

Every row was verified by execution (§17) where it is a behavior claim.

| Overridden | Location | Defect observed | Replacement |
|---|---|---|---|
| `scan_files` dot rule | synccli.py:14 | `dirnames[:] = [d for d in dirnames if not d.startswith(".")]` silently drops **every** dot-directory (verified: `.hidden_dir/x` is absent from the scan). A backup that silently omits data violates "complete, self-consistent image". | `backupctl.scan.scan_entries(root, excludes)`: same sorted-relpath contract, dot-directories **included by default**, exclusion only via explicit config globs. Dot-files were already included (only dirnames are filtered), so that asymmetry disappears. |
| `scan_files` symlink policy | synccli.py:13-19 | Verified: a symlink **to a directory** is silently dropped (os.walk `followlinks=False` yields it in `dirnames` but never descends, so it appears nowhere); a symlink **to a file** is enumerated and `file_state`/`copy_file` follow it, i.e. content from outside the tree is copied and the link is flattened. Neither is acceptable for a backup (data exfiltration, TOCTOU, non-faithful restore). | `scan_entries` uses `os.scandir` + `lstat`, records `type: "symlink"` with the verbatim `target`, never follows. Directories are recorded too, so **empty directories survive** (file-only enumeration loses them). |
| `file_state` key | synccli.py:22-25 | `(size, mtime_float)` only. `st_mtime` is `float` seconds, whose resolution at the current epoch is ~380 ns (measured reconstruction error of `st_mtime_ns` from `st_mtime`: 21–177 ns), so `st_mtime_ns` is not recoverable; and there is no inode/ctime, so "replace a file with one of equal size and restored mtime" is invisible. | `file_state_v2` = `{size, mtime_ns, ino, ctime_ns, mode, type}`. `ctime_ns` catches `utime`-preserving rewrites (POSIX bumps ctime on `utimensat`); `ino` catches atomic replacement. Cost measured: `lstat` 21 µs/file (same order as the existing `os.stat`). Granularity and blind spots are stated in §7. |
| `build_manifest` traversal | synccli.py:30-32 | One `os.stat` per path from a pre-built list, i.e. two passes and a full O(F) path list; also follows symlinks. | Single `os.scandir` pass keeping the same `{rel: state}` result, `lstat` only, one syscall per entry where the platform allows it (`DirEntry.stat(follow_symlinks=False)`). Output is the input `changed_files` expects. |
| `collect_stale` | synccli.py:45-59 | Dead code: it is not called anywhere in `synccli` (verified — only `test_synccli.py:21-33` exercises it). Its per-item `fresh` flag models an incremental-freshness pass, not snapshot planning. | Not used. The equivalent need is met by `changed_files` plus the per-file error list (§6). Naming it here so the reuse is a decision, not an omission. |
| `copy_file` | synccli.py:62-69 | Five independent defects: (1) `except OSError: pass` at 68-69 discards the failure *and* returns success — the brief requires a report; (2) `fsrc.read()` at 67 loads the whole file into RAM (memory = largest file, unbounded in the design sense); (3) `open(dst, "wb")` at 66-67 truncates the final path in place, so a crash leaves a partial file at a name a reader can find; (4) no `fsync`/dir-sync, no temp+rename, so publication is not atomic; (5) mode/mtime/type are not preserved, so restore loses the executable bit and timestamps. | `backupctl.copy.copy_file_durable`: 1 MiB chunked loop, `O_NOFOLLOW`-guarded source open, temp file in the destination directory, `fchmod` + `futimens`, `fsync`, `os.replace`, parent-dir `fsync` (policy-dependent, §3), returns a per-file result object; raises nothing the planner does not classify (§6). |
| `sync` manifest write | synccli.py:85-86 | `json.dump` straight onto the final path: a kill mid-write leaves a truncated manifest that `json.load` (line 79) then crashes on with no recovery, and two runs interleave last-writer-wins. Also no `fsync`. | Index is written inside `.tmp-<uuid>/`, `fsync`ed, and published by one `os.rename` of the directory (§3). Corrupt-index recovery is defined in §5. |
| `sync` locking | synccli.py:72-87 (none) | Two `sync()` calls open the same destinations with `"wb"` and write the same manifest; a reader can observe a half-written file. | No shared mutable paths at all: unique `.tmp-<uuid>`, atomic publish, immutable snapshots; locks are an optimization and a reader contract (§4). |
| `list_snapshots` validation | snaputil.py:17-19 | The docstring (8-14) promises "Entries that are not such directories are ignored", but the code only tests `startswith("snap-")` and `is_dir()`. Verified: `snap-`, `snap-partial-deadbeef`, and a **symlink** named `snap-...` are all returned (`is_dir()` follows symlinks by default). | `retention.list_valid(source_dir)` calls `snaputil.list_snapshots`, then keeps only entries matching `^snap-\d{10}-\d{8}T\d{6}Z$` whose `lstat` is a real directory (not a symlink) and whose `index.json` parses + validates. Non-matching `snap-*` entries are reported once and quarantined, never treated as snapshots. |
| `prune_snapshots` | snaputil.py:23-36 | (1) Deletes by `shutil.rmtree` on a live name (34-35): a kill mid-delete leaves a still-`snap-*` directory with missing files — a reader sees a snapshot that promises files it lacks. (2) `keep` is not clamped: **verified** `prune_snapshots(root, 0)` deletes every snapshot, including the newest, leaving the user with nothing. (3) No lock, so it can delete a snapshot a restore is reading. (4) One error (e.g. a planted symlink — `rmtree` refuses, verified) aborts the loop *after* earlier deletions, applying a partial policy. | `retention.apply`: clamp `keep >= 1`; never delete the newest; tombstone by atomic `os.rename(snap → .trash/<uuid>)` (cuts off new discovery instantly), purge trash only when older than `min_age` **and** the reader lock is free; per-snapshot try/except; report a debt count for skipped snapshots (§9). |
| `snapshot_disk_usage` | snaputil.py:39-51 | Walks + `os.stat`s every file (46-50), so it is O(F) per snapshot, **double-counts hardlinked/reflinked bytes** (it counts each name), follows symlinks (counts their targets), and can raise `FileNotFoundError` at line 50 if a concurrent prune removes an entry mid-walk. Using it to answer "how big is a snapshot" would be wrong on every count. | Logical size from `index.json` totals (O(1)); physical/unique size from `st_blocks` with a `(st_dev, st_ino)` dedup set in an explicit `backupctl du` command; both guarded with `lstat` + `FileNotFoundError` tolerance, and both labelled logical vs physical. |
| `safe_snapshot_path` | snaputil.py:54-63 | Docstring claims "any `..` segments in `rel_path` are normalized away ... cannot climb out". **Verified false**: `normpath("../a") == "../a"`, so `safe_snapshot_path(root, "snap-x", "../../etc/passwd")` returns `root/snap-x/../../etc/passwd`, and an absolute `rel_path` discards the whole prefix (`os.path.join(root, snap, "/etc/passwd") == "/etc/passwd"`). An index is attacker-influenced data on restore. | `restore.safe_path`: reject empty, absolute, NUL; reject any component in `{"", ".", ".."}`; then `realpath` both the snapshot root and the candidate and require `commonpath(...) == real_root` (catches symlinked intermediate directories and case-insensitive aliases on macOS). Restore itself stages into `DEST.tmp-<uuid>` and publishes by rename. |
| `is_stale` | snaputil.py:66-73 | Completeness inferred from directory mtime. Verified the code contradicts its own docstring: at `st_mtime == ref_epoch` the code returns `True` ("stale") while lines 68-71 say it is "not stale". Worse, a directory's mtime does not change when files *inside* it change, so it is not a completion signal at all. | Not used. Completeness is defined by the atomic directory rename (§3); nothing infers state from mtime. `is_stale` is left in place (other callers may exist) but `backupctl` never calls it. |

Not reused, deliberately: `synccli.MANIFEST_NAME`/`synccli.sync`'s on-disk
`.sync_manifest.json` (a live mirror is the opposite of an immutable
snapshot), and `snaputil.main`'s `--prune` CLI (it inherits the unclamped,
unlocked prune).

---

## 3. Run lifecycle: plan → stage → commit

One run of one source. All renames are inside `backup_root` on one
filesystem, so `rename(2)` is atomic and `EXDEV` cannot occur for the
commit. Copies are copies (never renames) from the source, so a backup root
on another filesystem is fine.

**Phase 0 — preflight (no writes outside `.tmp`/`.locks`)**

1. Resolve config; `source-id`; refuse if `backup_root` is inside the source
   or the source is inside `backup_root` (would self-recurse). Exclude the
   backup root from the scan if it is nested.
2. Take the per-source run lock (§4) with bounded wait.
3. `recover.sweep(source_dir)` (§5): reap dead `.tmp-*`, purge old `.trash`,
   repair/quarantine damaged indexes. This is what makes "the next run makes
   progress without manual cleanup" true.
4. `base = retention.newest_valid(source_dir)`; load its index into the
   `{rel: state}` shape that `changed_files` consumes; take a shared reader
   lock on `base` (§4). If the lock is unavailable or the index fails
   validation, `base = None` (full copy; reported).
5. Create `tmp = <source_dir>/.tmp-<uuid4>`; `mkdir`; take `LOCK_EX|LOCK_NB`
   on `tmp/LOCK` and **hold the fd for the whole run**. The lock is the
   liveness proof the reaper uses; the kernel releases it on death, so no
   PID/age heuristics.

**Phase 1 — scan + plan**

6. `cur = build_manifest_v2(source)` — sorted entries, files, dirs, symlinks,
   specials; one `lstat`-family lookup each (≈21 µs/file measured).
7. `to_copy = synccli.changed_files(base.entries, cur)`; everything else in
   `cur` is "unchanged" and will be materialized by clone/hardlink (§8).
8. Errors collected so far (unreadable dir, vanished during scan) go into the
   run's error list; a vanished *directory* is recorded as `skipped_missing`.
9. `--dry-run` returns here, printing the plan exactly like
   `synccli.sync(..., dry_run=True)` (synccli.py:81-82); nothing is written.

**Phase 2 — stage into `tmp/`**

10. Create `tmp/data/` directory tree from the scanned entries (all dirs
    first, one `mkdir` each, in sorted order; avoids a per-file `makedirs`
    like synccli.py:64 and makes the dirent cost predictable).
11. For each `rel` in `to_copy`: `copy_file_durable(source/rel, tmp/data/rel)`
    with the torn-read protocol of §6. Attributes written into the index.
12. For each unchanged regular file: materialize from `base/data/rel` via
    `clonefile` → `FICLONE` → `hardlink` → copy, in that order (§8). A
    failure falls through to the next strategy; all-four failure is a
    per-file error, not a run abort.
13. Symlinks: `os.symlink(target, tmp/data/rel)` from the recorded target
    (never `os.readlink` a live target's contents).
14. Empty directories already exist (step 10), so they survive the snapshot.
15. Write `tmp/index.json` incrementally (entries one at a time — no
    `json.dumps` of the whole map; see the measured 750 B/entry transient in
    §11), then a trailer with the entry count + SHA-256 over the canonical
    entry bytes. `fsync(index)`; `fsync` each touched directory
    (`tmp/data/...` and `tmp/`) if `durability = power_loss` (see below).

**Phase 3 — commit (the only visibility-changing step)**

16. Take `<source_dir>/.locks/alloc.lock` (`LOCK_EX`). Under it:
    `seq = max(highest seq ever published, max valid seq) + 1` (read from
    `.locks/seq`, a persisted high-water mark, then atomically advanced so a
    pruned or quarantined name is never recycled); `dst =
    snap-<seq:010d>-<UTC>`; `os.rename(tmp, dst)`.
    On `EEXIST`/`ENOTEMPTY` (verified: renaming onto an existing non-empty
    directory raises errno 66), recompute `seq` and retry; at most 3 tries,
    then a run error. Release the lock.
17. Release the base reader lock; release the run lock (or let process exit
    do it); append the summary line to `.runlog`; print it to stderr.

**Why a reader never asks whether the run finished.** The final name appears
in one atomic step, and it already contains the complete `data/` tree and the
complete `index.json`. Before that step the name does not exist; after it,
nothing is ever modified. There is no moment at which a reader can find a
name whose index promises a file the tree lacks (files are all created before
the index, the index before the rename). This also means the commit does not
need a separate "complete" marker, and no reader ever takes a lock to read.

**Durability levels (explicit, because the brief lists sleep/kill, not power
loss).**

- `process_death` (default): no per-file `fsync`. Metadata and data are in
  the page cache and visible to every process immediately; `rename` is atomic
  in the VFS. A kill/Ctrl-C/sleep loses nothing that was already published.
  Measured cost of this mode: temp+rename without fsync, 8.33 s/20k files.
- `power_loss`: `fsync` each file before its directory is synced, then the
  index, then each directory, then publish. Measured: 9.14 s/20k single
  thread (fsync adds ≈0.04 ms/file on APFS); 4.16 s at 8 workers.
  A run killed before publish leaves only `tmp/`, which the reaper discards.

---

## 4. Concurrency model

Shared resources and their protection:

| Resource | Writers | Protection |
|---|---|---|
| `.tmp-<uuid>` | exactly one run | name uniqueness (uuid4, 122 bits) + `flock` on `tmp/LOCK` held for the run's life |
| published `snap-*` | nobody, ever, after publish | immutability by contract; only `recover` rewrites `index.json` via temp+rename (§5), which is atomic for readers |
| sequence numbers / final name / `.locks/seq` | all runs of one source | `flock(LOCK_EX)` on `.locks/alloc.lock`, held only for the high-water read+advance and the rename, so publishes serialize for milliseconds |
| a snapshot being read (restore **or** a run using it as its base) | readers only | `flock(LOCK_SH)` on `.locks/read-<snapname>.lock`; prune needs `LOCK_EX` on the same file |
| `.trash/<uuid>` | one pruner | unique name; per-`uuid` deletion |
| `.runlog` | all runs | `O_APPEND` write of one line ≤4096 B |
| lock-file inodes | readers/pruner | open `O_CREAT`, `flock`, then compare `fstat(fd)` with `lstat(path)`; on `(dev,ino)` mismatch close and retry (≤3). The pruner unlinks a lock file only while holding `LOCK_EX` on it. Prevents the classic unlink/recreate double-inode race. |

**No mutual exclusion is required for correctness.** Two runs of the same
source at the same time each stage in their own `tmp/`, each link from the
same immutable base (or copy), and each publish under the alloc lock. Both
snapshots are valid full images; neither can observe the other. A restore
reading snapshot `S` cannot see a run in progress at all (the run writes only
to `.tmp-*`). A restore and a *prune* are the only interacting pair, handled
above.

Locks are therefore an **optimization** (avoid duplicating I/O) and a reader
contract:

- Per-source run lock `.locks/run.lock`, `LOCK_EX|LOCK_NB`; on contention
  wait up to `--wait-seconds` (default 600 for both scheduler and person;
  there is no TTY branch anywhere in the tool), then exit **75** (retry
  later). Waiting is safe because publishes are short.
- Base reader lock: `LOCK_SH|LOCK_NB`; on `EWOULDBLOCK` fall back to
  `base = None` (full copy) instead of waiting — no stall, no deadlock.
- Lock order, to make deadlock impossible: alloc lock is only ever taken when
  holding no other lock; reader locks may nest; the prune's exclusive lock is
  always `LOCK_NB` and is released before any blocking operation. A blocked
  acquisition is a skip, never a wait.
- One fd per lock, never shared across threads (`flock` is per open file
  description; threads sharing an fd would release each other's locks).

**Restore compatibility contract** (documented in the man page and enforced
by the shipped `backupctl restore`): open `<snap>` once as a directory fd,
take `LOCK_SH` on the external lock file, and resolve entries with
`openat(dirfd, ...)`. Because the lock file and the snapshot are separate
inodes and pruning moves the snapshot by `rename`, a restore that already
holds the lock is never affected; a restore that does *not* take the lock is
still protected by `min_age` (default 1 h) before any deletion, and by the
rename-to-trash cut-off. That is a best-effort guarantee for third-party
tooling and a hard guarantee for `backupctl restore`.

---

## 5. Crash safety and index recovery

The definition of "corrupt index left behind by a dead run" in this design:

- **Uncommitted index** (`snap-*/.tmp`-style paths, or anything under
  `.tmp-*`): not a recovery target. Discarded.
- **Committed directory whose `index.json` is unparseable/truncated/checksum
  mismatch**: possible only from external damage or an older version (this
  design never publishes such a file). Recovery is *derivable* because the
  snapshot's own tree is complete and immutable — the point-in-time content
  is in `data/`, so the index is re-derived **from the snapshot tree**, never
  from the live source (which has moved on).
- **Committed directory whose index promises a file that is missing/short**:
  *not* recoverable — the tree no longer proves the original image. Quarantine
  the whole snapshot.

Algorithm, run in Phase 0 (`recover.sweep`), per source:

1. For each `.tmp-*`: try `LOCK_EX|LOCK_NB` on `tmp/LOCK`.
   - acquired → owner is dead (kernel released its lock) → `rmtree(tmp)`;
     report `discarded incomplete run <uuid>`.
   - `EWOULDBLOCK` → a live run owns it → leave it alone.
   - `LOCK` does not exist yet (a run died in the microseconds between
     `mkdir` and creating/locking the file) → reap only if the directory is
     older than 60 s; a brand-new lock-less directory may be a live run
     mid-start. The window is why the run creates and locks `LOCK` as its
     first action after `mkdir`.
   A laptop that slept mid-run is reaped on the next start (the kernel
   released the lock at process death), and a concurrently running scheduler
   job is never touched.
2. For each `.trash/<uuid>` older than `min_age` (config, default 1 h) and
   whose source snapshot name is no longer referenced: `rmtree`. Trash names
   are invisible to readers already.
3. For each `.quarantine` entry: leave it (a human decides); count it.
4. For each name that `snaputil.list_snapshots` returns:
   - validate against the strict regex and `lstat().is_dir(follow_symlinks=False)`;
     a non-conforming `snap-*` entry (verified examples: `snap-`, `snap-partial-deadbeef`,
     a symlink named `snap-...`) is **quarantined** (renamed out of the
     `snap-` namespace) and reported. It was never a usable snapshot.
   - parse `index.json`; verify trailer checksum, entry count, monotonic
     entry order, and for every entry `lstat(snapshot/data/rel)` matches
     `type` and `size`. Stat-only by default: O(F) at 21 µs/file; hashing
     only with `--verify` (0.42 s/GiB measured).
   - index bad + tree consistent → **repair**: rebuild the index from
     `data/` (lstat + hash each file), write `index.json.tmp`, `fsync`,
     `os.replace` inside the snapshot directory, `fsync` the directory.
     Report `repaired index of <snap> (<N> entries, <t> s)`. Readers see the
     old or the new index, never a partial one (single atomic replace).
   - tree inconsistent → **quarantine**: `rename(snap → .quarantine/...)`,
     report `quarantined <snap>: missing <rel>`. It is removed from the
     snapshot namespace, so no reader can mistake it for a complete snapshot
     and no later run can pick it as its base.
   - Only the **newest** index of the source being backed up is fully
     validated per run; the others are validated on `backupctl check` or
     when they are used as a base. Per-run startup is therefore O(1) in
     retained history (§12).
5. Summary counts (`reaped`, `repaired`, `quarantined`) are appended to the
   run's report; exit code 3 if any repair/quarantine happened, 0 otherwise
   (§14).

Repair is bounded by the snapshot itself: O(F) stats + O(B) hash at 21 µs/file
and 2.4 GB/s, so ~1 s per GiB plus 0.43 s per 20k files. It happens only on
damage; the normal path never re-reads an old index beyond the base.

---

## 6. Unstable sources: vanish, unreadable, torn, special

A per-file state machine, identical for scheduler and person (no
`isatty()`, no prompt, no interactive confirmation anywhere):

| Situation | Detection | Snapshot content | Report / exit |
|---|---|---|---|
| File vanishes between listing and copy | `open()` → `ENOENT` | file **absent** from index and tree; snapshot is a full image without it | `skipped_missing +1`, one `warning:` line; exit stays 0 (a deletion is legitimate) |
| File unreadable | `EACCES`, `EPERM`, `EIO`, short read | absent from index; never a zero-length placeholder | `errors +1`, `error:` line with errno; snapshot still publishes; exit **2** |
| File changes while being read | after the copy: `fstat(fd)` differs from the pre-copy `lstat`, or `lstat(path)` no longer matches `fstat(fd)` (path replaced) | retry once from the new state; if it changes again, drop and report | `errors +1` (`churn`); exit **2** |
| FIFO/socket/device | `lstat` type | not opened at all (opening a FIFO would block the run forever); recorded as `special` in the index | `skipped_special +1`, `warning:` line; exit 0 |
| Symlink | `lstat` type | recorded `{type: symlink, target}`; target never fetched | none |
| Directory unreadable | `scandir` → `EACCES` | contained in the index as a dir, contents absent | `errors +1`; exit **2** |
| Source root missing | preflight | no snapshot at all | `error:` line; exit **2**; retention is **not** applied (never prune on a failed run) |

The torn-read protocol is three cheap checks per copied file and costs
≈40 µs/file extra (two `lstat` + one `fstat`, vs 210–460 µs of
materialization). It guarantees that every file in a published snapshot is
either a complete read of a single inode or absent — never a splice.

**Cross-file atomicity is explicitly out of scope.** Without an
filesystem-level snapshot (`fs_snapshot`, needs privileges) a tree walk
cannot be a global point-in-time image; files are captured over a window.
What the design does guarantee is what the brief asks: no file ever comes
from a *different run's* partial state, no file is torn, the index matches
the tree exactly, and `index.json` records `scan_start_utc` / `scan_end_utc`
so a consumer knows the window. Change detection is per-file over that
window (§7).

---

## 7. Change detection: granularity and what it can miss

**Key:** `(size, mtime_ns, ino, ctime_ns)`, with `mode`/`type` checked for
type changes. Compared by `synccli.changed_files` (synccli.py:36-42)
unchanged.

**Base:** the newest *valid committed* snapshot of that source at Phase 0.
If it fails validation or cannot be locked, the run does a full copy and
says so.

**What the key catches that `(size, mtime_float)` does not:** atomic replace
with identical size and restored mtime (`ino`), and in-place rewrite followed
by `utime` (`ctime_ns` is bumped by `utimensat` even when `mtime` is forged).
It also stops losing sub-microsecond precision by storing `mtime_ns` as an integer instead of `float` seconds.

**What it still misses (residual, unavoidable without reading bytes):**

1. In-place content change with size unchanged, where the writer restores
   `mtime` **and** the filesystem does not bump `ctime` (a stepped system
   clock can make the new `ctime_ns` land in the same recorded tick).
2. Coarse timestamp filesystems: FAT (2 s), ext3 (1 s), some NFS/SMB servers
   that truncate to seconds — two writes in one tick with equal size are one
   state.
3. A network filesystem that lies about attributes (client-side caching).
4. `mtime` set into the future, then edited "before" that time.
5. Holes vs data (`cp`-style sparse rewriting) are invisible to the key; a
   same-size rewrite of a sparse region is missed. (Holes are also not
   preserved, §16.)

Clock going backwards produces a *different* `mtime_ns`, i.e. a false
positive (a needless re-copy), which is the safe direction.

**Mitigations, priced:** `--checksum` hashes every file and ignores the key
(0.42 s/GiB measured, 2.4 GB/s, parallelizable across the worker pool);
`backupctl verify SNAP` re-hashes a published snapshot against its index;
`--reuse=copy` disables clone/hardlink reuse so every file is re-read. The
default is the stat key, because reading every byte every run would turn a
1 GiB/20k-file incremental from 0.6 s into 0.9 s+ today and scale with total
bytes instead of total files — the wrong shape for "most files do not
change".

**Consequence to state plainly:** "unchanged" is a *content-reuse* decision
whose failure mode is stale bytes in snapshot `S+1` for exactly the files
that changed in a way the key cannot see. It is not run mixing: the index
still describes snapshot `S+1` completely and every promised file exists.
`--checksum` is the answer when that risk is unacceptable.

---

## 8. Snapshot storage, space, and why no delta chain

Each snapshot is a **full logical image**: every source entry appears under
`snap-*/data/`. Bytes are shared where possible, names are not.

Materialization of an unchanged regular file, in order:

1. `clonefile(2)` (APFS): measured **0.6 ms for 1 GiB**, 0.23 ms/file for
   4 KB files. New inode, copy-on-write extents, no cross-snapshot mutation
   hazard.
2. `FICLONE` ioctl (Linux btrfs/xfs).
3. `os.link` from `base/data/rel`: measured **0.4 ms for 1 GiB**. Same inode
   → an in-place mutation of one snapshot's file would corrupt the other.
   Mitigated by the immutability contract, not by permissions; `--reuse=copy`
   exists for that reason.
4. Chunked copy (the durable path).

All four operate within one backup root on one filesystem. Measured per-file
cost at 4 KB is **metadata-bound, not byte-bound**: plain copy 0.235 ms,
clonefile 0.231 ms, hardlink 0.386 ms, temp+rename+attrs 0.42 ms (0.46 with
fsync). So reuse
buys *bytes and cold-cache reads*, not per-file time, at small file sizes;
for large files it is the whole game (0.6 ms vs 230 ms per GiB warm, ~700 ms
cold).

**Rejected: delta chains** (snapshot `S+1` records unchanged files as pointers
to `S`). It would avoid the ~0.2–0.4 ms/unchanged-file dirent cost, but (a)
retention could then never delete `S` without rewriting or invalidating
`S+1`, directly contradicting "deletion must never leave the user without a
usable snapshot" and making `snaputil.prune_snapshots` (which deletes by
oldest name, snaputil.py:30-35) actively destructive; (b) a single corrupt
base breaks a whole chain instead of one snapshot. Full images + COW reuse
keep every snapshot independently readable, prunable, and verifiable, which
is worth the dirent cost (measured 4.16 s for 20k files at 8 workers).

Hardlinks *inside* one source tree are preserved: entries with
`nlink > 1` are tracked by `(st_dev, st_ino)` and the second path is
materialized as a link to the first path's snapshot entry, so the physical
image does not silently double bytes.

---

## 9. Retention

Policy per source: `keep = K` (default 14), `min_keep = 1`, `min_age`
(default 1 h). Applied at the end of a **successful** run only.

Order (this is the exact algorithm, not "prune old ones"):

1. `names = retention.list_valid(source_dir)` (strict, §2.2); order is
   sequence order (= publish order).
2. `if len(names) <= max(K, min_keep): return []` — clamp so `keep = 0` and
   negative values cannot empty the store (verified that
   `snaputil.prune_snapshots(root, 0)` does exactly that today).
3. `newest = names[-1]`; the deletion set is `names[:-1]` beyond `K`, and
   **never contains `newest`**.
4. For each candidate, oldest first:
   - skip if `age < min_age` (protects an in-flight restore that never took a
     lock);
   - skip if `flock(read-<name>.lock, LOCK_EX|LOCK_NB)` fails (a reader or
     another run's base holds it) → count as **debt**, report it;
   - otherwise `os.rename(snap → .trash/<uuid4>)` under `LOCK_EX`, then
     release. New readers cannot discover it from this instant; an existing
     reader holding `LOCK_SH` is excluded by the previous step; a reader that
     uses `openat` on its dirfd is unaffected by the rename.
5. Purge `.trash/<uuid>` older than `min_age` (they are already invisible and
   unreferenced). Measured delete cost: 1.59 s per 20k files (~80 µs/file).
6. Report `retained=<n> deleted=<d> debt=<m>`; if `debt > 0` say why
   (locked/min-age) — retention is a floor, not a hard cap: the real count is
   `K + debt`, bounded by the number of concurrently reading snapshots
   (normally 0–1 per source).

"Never leave the user without a usable snapshot" is enforced three times:
`keep >= 1`, newest is excluded, and only *valid* snapshots are counted or
deleted (a corrupt one is already quarantined, §5).

Space bound with K retained full images and COW reuse:
`disk <= B_tree + Σ_{i=1..K-1} Δ_i + K · F · 197 B` where `Δ_i` is the bytes
changed at run `i` and 197 B/entry is the measured index size with SHA-256.
Worst case (every file changes every run) it degenerates to
`K · (B_tree + F · 197 B)`; the metadata term for 50 sources × K=14 × 20k
files is ≈2.7 GB against ≈700 GiB of data, so metadata is not the driver.
`backupctl du --physical` (st_blocks + inode dedup) is the honest number for
shared extents; `snapshot_disk_usage` is not used (§2.2).

---

## 10. Restore and path safety

`backupctl restore SNAP DEST`:

1. Resolve `SNAP` by listing + strict validation (never by trusting a path
   argument verbatim); take `LOCK_SH` on the external reader lock.
2. Open the snapshot directory once; walk `index.json` entries in order;
   validate every `rel` with `restore.safe_path` (§2.2 override of
   `snaputil.safe_snapshot_path`) and every entry's `lstat` type/size against
   the index. A mismatch aborts with a diagnostic naming the entry.
3. Stage into `DEST.tmp-<uuid>` (parents as `dir` entries, symlinks recreated
   with `os.symlink`, mode+mtime applied, files written `O_EXCL` so a
   pre-existing symlink cannot redirect the write), then publish
   `DEST.tmp-<uuid>` → `DEST` by rename, configurable to merge instead.
   A restore killed mid-way leaves only a `.tmp` directory, never a
   half-restored destination.
4. Optional `--verify` re-hashes while copying (2.4 GB/s measured).

Path safety is a hard requirement because `index.json` is data, and a corrupt
or hand-edited index is exactly the case §5 repairs: absolute paths and `..`
must never escape the snapshot, and symlinked intermediate directories inside
`data/` must not redirect a read outside it. The containment check is
`realpath` + `commonpath`.

---

## 11. Performance budget for the first full backup

**Contract:** 1 GiB tree, ~20,000 files, reference machine (APFS/SSD,
8 workers, `durability = process_death`), **≤ 30 s wall**; measured
**4.8 s**. Single worker: ≈9.6 s (9.14 s materialize + 0.43 s stats),
budget ≤ 90 s. HDD-backed backup root: modelled 19 s, budget ≤ 120 s.
Incremental run of the same tree with 100 changed files: derived from the
same constants ≈0.6 s (0.43 s stats + 0.02 s copy + 0.06 s index), budget
≤ 10 s.

**Where the numbers come from — measured, not asserted.** The tree was built
in a temp dir (200 dirs × 100 files × 4 KB = 82 MB; plus a separate 1 GiB
single file), using `synccli.scan_files` and `synccli.build_manifest` from
this repo, and the copy routine used for the measurement is the design's
`copy_file_durable` (temp file, 1 MiB chunks, `fchmod`, `futimens`,
`os.replace`, optional `fsync`).

| Operation | Measured | Rate |
|---|---|---|
| `synccli.scan_files`, 20k/200 dirs | 0.125 s | 160.5 k files/s (6.2 µs) |
| `synccli.build_manifest` (`os.stat`) | 0.480 s | 41.7 k files/s (24 µs) |
| `lstat` pass | 0.429 s | 46.7 k files/s (21 µs) |
| plain chunked copy, dirs pre-created | 4.71 s | 4.2 k files/s, 17 MB/s |
| temp+rename+attrs, no fsync, 1 thread | 8.33 s | 2.4 k files/s |
| temp+fsync+rename+attrs, 1 thread | 9.14 s | 2.2 k files/s |
| temp+fsync+rename+attrs, 8 threads | 4.16 s | 4.8 k files/s, 20 MB/s |
| hardlink, 20k × 4 KB | 7.73 s | 2.6 k files/s |
| `clonefile`, 20k × 4 KB | 4.61 s | 4.3 k files/s |
| `clonefile` 1 GiB | 0.0006 s | O(1) |
| `os.link` 1 GiB | 0.0004 s | O(1) |
| 1 GiB copy, 1 MiB chunks (warm) | 0.230 s | 4.4 GB/s |
| SHA-256 1 GiB | 0.416 s | 2.4 GB/s |
| index 20k entries w/ SHA-256: 3.94 MB | dump 0.018 s, +fsync 0.063 s | 3.2 µs/entry |
| index load 20k entries | 0.014 s | 0.7 µs/entry |
| `rmtree` 20k files | 1.59 s | 80 µs/file |
| peak memory, `build_manifest` 20k | 7.0 MB | 352 B/entry (tracemalloc) |

**Derivation.** `T_initial ≈ F·t_file(P) + B/S + F·t_index + T_fixed`, with
`t_file(8) = 0.208 ms` (the durable copy above, which includes data write,
attrs, and rename), `S = 4.4 GB/s` warm (1.0–1.5 GB/s cold SSD),
`t_index = 3.2 µs`, `T_fixed ≈ 0.15 s` (scan + publish + dir syncs). For
F = 20k, B = 1 GiB:

`0.208 ms × 20,000 = 4.16 s` (dominant), `1 GiB / 4.4 GB/s = 0.23 s`,
`3.2 µs × 20,000 = 0.064 s`, `+0.15 s` → **≈4.6 s**, measured 4.8 s. The
term that grows is **files**, not bytes: at 4 KB the work is metadata-bound
(verified by plain copy 4.71 s vs 1 GiB copy 0.23 s). Cold-cache SSD model:
`0.30 ms × 20k = 6 s` + `1 GiB/1.5 GB/s = 0.7 s` ≈ 6.7 s, still under 30 s.
HDD model: `0.6 ms × 20k = 12 s` + `1 GiB/150 MB/s = 7 s` ≈ 19 s, under the
120 s budget. The SHA-256 pipeline adds 0.42 s of CPU per GiB but overlaps
the copy (measured copy is metadata-bound at small sizes).

**Scaling rule made explicit:** per-run time is `O(F_d)` stats plus
`O(ΔB_d)` bytes; it is *linear in the number of files even when nothing
changed* (you must `lstat` a file to know it is unchanged — 21 µs measured,
0.43 s per 20k files). Reuse removes bytes, not dirents.

---

## 12. What grows with what (`N` sources, per-tree F files / B bytes)

| Quantity | Bound | Basis |
|---|---|---|
| per-run CPU | `0.44 ms·F_d + ΔB_d/4.4 GB/s` (1 worker, process-death, 4 KB files; the 0.44 already includes one `lstat` at 21 µs, materialize at 420 µs, index at 3.2 µs) | measured §11 |
| per-run peak RSS | `352 B·F_d` (metadata map) + `P·2 MiB` copy buffers + `≤1 KiB` fixed; F_d = 1e6 → ≈350 MiB | tracemalloc 352 B/entry measured; serialization is streamed, so no second F-sized copy |
| open fds | `2P + 6` = 22 at `P = 8` (one source + one dest per worker, 3 locks, 1 log) | formula, constant in N and F |
| per-run startup work | `O(1)` in N and in retained snapshots: only this source's newest index is validated; reaper scans `#orphan tmp` + `#trash` (normally 0) | §5 |
| lock/sidecar inodes | `O(1)` per source (2) + `O(1)` per active run + `O(1)` per reading snapshot | §4 |
| disk | `Σ_d [B_d + Σ_{i<K} Δ_{d,i} + K_d·F_d·197 B]`; worst case `Σ_d K_d·(B_d + F_d·197 B)` | §9; index/blob size measured |
| retention time | `O(K_d)` listings + `O(bytes deleted)` at 80 µs/file | `rmtree` measured |
| total across N per scheduled sweep | one run per source: `Σ_d T_d`; memory stays `max_d`, **not** `Σ_d`, because sources are processed sequentially | §3 runs one source at a time |
| restore time | `O(F_snap)` + `O(B_snap)/S` | same primitives |

For 3 → 50 sources of ~1 GiB / 20k files: per-run work is unchanged
(≈4.8 s per source), memory unchanged (≈8 MB per run, one tree at a time),
disk grows as `50 × 14 × (1 GiB + 4 MB)` ≈ 700 GiB worst case, and the
application-level state that scales with N is 50 source-id directories and
their config entries. Nothing in the per-run path is O(N).

If a single run is used to cover all 50 sources, time is the sum (the
unavoidable `ΣF` stats) but memory is still `max_d` because of sequential
processing.

---

## 13. Index schema (`index.json`, one per snapshot, immutable)

```json
{
  "format": "backupctl.snapshot/1",
  "source": {"path": "/abs/source", "id": "evals-3f2a1c9d", "dev": 16777220},
  "run": {"id": "uuid4", "pid": 1234, "host": "h",
          "scan_start_utc": "...", "scan_end_utc": "...", "finished_utc": "..."},
  "change_key": "size,mtime_ns,ino,ctime_ns",
  "base": "snap-0000000041-20261116T211500Z",
  "durability": "process_death",
  "counts": {"files": 20000, "dirs": 210, "symlinks": 3, "specials": 0,
             "bytes": 1073741824, "copied": 113, "reused": 19887,
             "skipped_missing": 0, "skipped_special": 0, "errors": 0},
  "entries": [
    {"rel": "a/b.txt", "type": "file", "size": 12, "mtime_ns": 1700000000123456789,
     "mode": 33188, "ino": 8811023, "ctime_ns": 1700000000123456789,
     "sha256": "...", "how": "copy"},
    {"rel": "link", "type": "symlink", "target": "../outside"},
    {"rel": "empty", "type": "dir", "mode": 16877}
  ],
  "errors": [{"rel": "x", "op": "read", "errno": 13, "message": "..."}],
  "trailer": {"entries": 20213, "sha256": "..."}
}
```

Rules: entries sorted by `rel` (bytewise); `sha256` on files is computed
during the copy (2.4 GB/s measured) or inherited from the base for
reuse entries; `how ∈ {copy, clone, link, link-internal}`; the trailer hash
covers the canonical serialization of `entries`; `counts` is advisory and
recomputed from `entries` on validation. Written incrementally, one entry at
a time, so peak memory is the change-key map only (measured: a whole-map
`json.dumps` costs 750 B/entry transient — 15 MB per 20k entries — which
would be a needless second F-sized copy).

---

## 14. CLI, config, reporting, exit codes

```
backupctl init --root BACKUP_ROOT --source PATH [--source PATH ...]
backupctl run [--all | SOURCE...] [--dry-run] [--wait-seconds N]
              [--checksum] [--reuse clone|link|copy] [--workers N]
              [--durability process_death|power_loss]
backupctl list [SOURCE] [--json]
backupctl check [SOURCE]            # full validation/hash of all snapshots
backupctl verify SNAP              # re-hash one snapshot
backupctl restore SNAP DEST [--verify] [--merge]
backupctl prune [SOURCE] [--keep K] [--min-age SECONDS] [--dry-run]
backupctl du [SOURCE] [--physical]
backupctl status [SOURCE]          # newest, counts, debt, last-run summary
```

Config: one JSON file (`backupctl.json`) next to the repo, stdlib only
(matching this repo's dependency profile: `synccli.py`/`snaputil.py` import
nothing outside the stdlib). Keys mirror the flags; `sources[]` holds
`{path, id, excludes[], keep}`.

Reporting: every run emits exactly one summary line to stderr and appends it
to `<source>/.runlog` (verified append semantics: `O_APPEND`, ≤4096 B):

```
backupctl: run <uuid> source <id> snapshot <name> files=20000 dirs=210
           bytes=1073741824 changed=113 reused=19887 errors=0 missing=0
           elapsed=4.9s base=<name|none>
```

plus one `warning:`/`error:` line per anomaly (`discarded incomplete run`,
`repaired index`, `quarantined`, `skipped_missing`, `error: read EACCES`).
No output goes to stdout except data for `--json`/`list`.

Exit codes: `0` success (including `skipped_missing`); `2` snapshot published
but ≥1 source error (`errors > 0`); `3` success with recovery actions
(repaired/quarantined; reaping a dead run's `.tmp` is routine and stays 0);
`64` usage; `75` per-source run lock not
acquired (retry later); `1` unexpected (no snapshot published). Scheduler and
person get the same codes and the same lines — there is no interactive path.

---

## 15. Test plan

Extends `test_synccli.py`'s pattern (`unittest` + `mkdtemp`); the 6 existing
tests keep passing unchanged.

- **Atomic publish:** run in a subprocess, `SIGKILL` mid-copy, then list:
  only `snap-` names with a complete `index.json` where every entry resolves;
  the `.tmp-*` is invisible; a second run reaps it and publishes.
- **Index corruption:** truncate `index.json` of a published snapshot →
  next run repairs from `data/` (entries and hashes match a pre-corruption
  checksum) and exits 3; delete a payload file → next run quarantines and
  exits 3, and the snapshot is no longer offered to restore.
- **Vanishing/unreadable file:** delete a file between plan and copy (monkey-
  patch `open`), chmod 000 (skip when root), FIFO in the tree → assert
  snapshot contents, `counts`, and exit code from the §6 table; FIFO test
  proves no hang.
- **Torn read:** writer flips a file's size between the two `fstat`s; assert
  retry-once then `errors`/exit 2, and that no torn content is in the index.
- **Concurrent runs:** two processes on one source; assert both snapshots
  valid, distinct seqs, and one `run.lock` wait/75 as configured.
- **Reader vs prune:** hold `LOCK_SH` on the oldest candidate, run
  `prune --keep 1`; assert it is skipped, reported as debt, and still
  readable; release, prune again, assert `rename → .trash`, then purge after
  `min_age`.
- **Retention clamp:** `--keep 0` and `--keep -1` keep the newest snapshot;
  a corrupt snapshot is not counted/deleted.
- **Path traversal:** `restore.safe_path` rejects `../x`, `/etc/passwd`,
  `a/../../x`, `a//b`, `""`, and a snapshot `data/` containing a symlinked
  directory; `restore` publishes by rename so a failure leaves no partial
  destination.
- **Change detection:** edit a file preserving size; rewrite via
  `os.replace` with restored mtime; assert `changed_files` behavior and that
  `ctime_ns`/`ino` catch the replacement while `(size, mtime)` alone would
  not (documenting the residual misses).
- **Symlink/dot-dir/empty-dir fidelity:** a dot-directory, an empty
  directory, a symlink to a file outside the tree, a symlink to a directory
  → all present exactly once as their own type, no outside content copied.
- **Sequencing:** 120 snapshots in one day, clock stepped backwards between
  publishes → `list_valid` order is publish order; seq width holds.
- **Budget smoke test:** build 1 GiB / 20k files in CI and fail if the full
  run exceeds the §11 budget by 2× (guards regressions in the per-file
  path).

---

## 16. Assumptions and explicit limitations

- `backup_root/sources/<source-id>/` is tool-owned: entries that do not
  match the strict snapshot name are quarantined (renamed, with a report),
  never deleted, never treated as snapshots.
- Backup root is a local POSIX filesystem with atomic `rename(2)` and working
  `flock(2)` (APFS, ext4, xfs). Network filesystems are unsupported for
  concurrent writers unless they provide POSIX `flock`; the tool refuses to
  run if `flock` is unsupported (`ENOTSUP`/`EOPNOTSUPP`/`ENOLCK`).
- Snapshots are immutable by contract. Prefer `clonefile`/`FICLONE`; if only
  hardlinks are available, an external in-place edit of one snapshot's file
  would be visible in every snapshot sharing that inode — `--reuse=copy`
  removes the hazard.
- Cross-file point-in-time atomicity is out of scope (§6). Files are captured
  over a scan window; the window is recorded in the index.
- Not preserved: xattrs, ACLs, ownership when not running as root, file
  flags, resource forks, sparse holes (a sparse file is copied dense), hard
  links across *different* source trees. Ownership is recorded and applied
  best-effort.
- Change detection is a stat key by default and has the residual blind spots
  listed in §7; `--checksum`/`verify` are the strong modes.
- Retention is a floor under lock/min-age pressure (§9), not a hard cap.
- One backup root per filesystem; a source may live on another filesystem
  (copies are copies, never renames, so `EXDEV` does not arise).

---

## 17. Verification log (what was actually executed)

- `python3 -m unittest` in this directory: **6 tests, OK, 0.006 s** — the
  suite the design is required to keep green.
- `snaputil.safe_snapshot_path(root, "snap-x", "../../etc/passwd")` →
  `.../snap-x/../../etc/passwd`; with `/etc/passwd` → `/etc/passwd`. The
  docstring at snaputil.py:57-59 is false.
- `snaputil.list_snapshots` on `{snap-, snap-partial-deadbeef,
  snap-20261112-150000-07, notasnap, <symlink named snap-…>}` returns the
  first, second, third, and the symlink; only `notasnap` is ignored. So
  neither the documented name validation (snaputil.py:9-14) nor the
  symlink guard exists.
- `snaputil.prune_snapshots(root, 0)` → deletes all three, leaves
  `notasnap`; `keep` is not clamped and the newest is not protected.
- `snaputil.is_stale(dir, st_mtime)` → `True` at equality, contradicting
  snaputil.py:68-71.
- `synccli.scan_files` on a tree with `.hidden_dir/x`, `.hidden_file`, a
  symlink to an outside directory and a symlink to an outside file returns
  `['.hidden_file', 'linkfile']`: dot-dirs and dir-symlinks are dropped,
  file-symlinks are followed.
- `os.rename(tmpdir, existing_nonempty_dir)` → `OSError errno 66`
  ("Directory not empty"), the collision the publish loop retries; renaming
  onto a free name succeeds (the commit step).
- `shutil.rmtree` on a symlink → `OSError: Cannot call rmtree on a symbolic
  link` (the safety property retained for trash purge).
- All performance and memory figures in §11 were produced by a stdlib
  script in a temp directory that imports `synccli` from this repo and uses
  the design's `copy_file_durable` loop; the timings are listed with the
  operation they measured so they can be re-run against the implementation
  without trusting this document.

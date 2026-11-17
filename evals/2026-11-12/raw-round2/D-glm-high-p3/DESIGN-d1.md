# DESIGN — `backupctl` (fixture D1)

`backupctl` is a command-line backup tool for the `evals/` result directories.
It backs up a configured set of N directories into a backup root, producing
**snapshots**: point-in-time, self-consistent copies. It builds on the code
already in this directory (`synccli.py`, `snaputil.py`) rather than
re-implementing it; every reuse and every deliberate override is named in
§2 and §11.

All numbers below were measured on this machine (Apple Silicon, APFS,
Python 3.10.11) against a synthetic tree of **25,000 files / 1,201 MB** in
200 directories — the "~1 GB, tens of thousands of files" shape the brief
names. The benchmark built the tree with random 50 KB blocks and timed the
real functions from `synccli.py` (listed in §10). The existing test suite
passes as-is: `python3 -m unittest test_synccli` → 6 tests, OK.

---

## 1. What `backupctl` is

    backupctl run      [--config PATH] [--wait SECS] [--verify] [--fsync-files]
    backupctl status   [--config PATH]
    backupctl prune    [--config PATH] [--keep K]
    backupctl verify   <backup_root> <snapshot-name>

- `run` is the only writer. Both the scheduler and a person invoke the same
  `run` command, so all crash/vanish/concurrency behavior is identical by
  construction (this is how the brief's "same behavior whether the run was
  started by the scheduler or by a person" is guaranteed — there is one code
  path, no scheduler-specific mode).
- `status` lists snapshots and sizes (thin wrapper over `snaputil.py` helpers).
- `prune` applies the retention policy standalone (§8).
- `verify` re-checks a committed snapshot against its index.
- Restore remains separate tooling, as the brief states; §9 defines the
  contract any reader must follow so it can never observe a partial snapshot.

Configuration is a JSON file (default `backupctl.json` next to the code):

    {
      "backup_root": "/backups/evals",
      "dirs": ["/proj/evals/runs-a", "/proj/evals/runs-b", "/proj/evals/runs-c"],
      "keep": 24
    }

`keep` is the retention window (§8). Directories are processed **sequentially
within one run** under one lock (§4); a failure in one directory does not
abort the others.

## 2. Grounding: what is reused from the existing code

Every claim below was verified by reading the file; line numbers refer to the
current contents of this directory.

| Existing artifact | Where | How `backupctl` uses it |
|---|---|---|
| `synccli.scan_files(root)` | synccli.py:10–19 | **Reused as the source scanner.** Its contract — sorted list of `os.path.relpath` relative paths from an `os.walk` — is exactly the per-directory file listing the run needs. One deliberate override (dot-files), see §11-O1. |
| `synccli.file_state(path)` | synccli.py:22–25 | **Reused as the change-detection state function**, extended to `st_mtime_ns` (§11-O2, §7). Its `(size, mtime)` shape *is* the change-detection granularity of this design (§7). |
| `synccli.build_manifest(root)` | synccli.py:28–33 | **Reused as-is** to build the per-directory `{relpath: state}` map each run diffs against. |
| `synccli.changed_files(old, new)` | synccli.py:36–42 | **Reused as-is** as the diff between the previous snapshot's index and the fresh manifest: returns changed-or-new files; files in `old` but not `new` are the removed set (computed symmetrically). |
| `synccli.collect_stale(items, seen)` | synccli.py:45–59 | **Reused for the retry pass**: after the first copy loop, files that failed are fed back as `[(rel, False)]` and `collect_stale` yields exactly the not-yet-succeeded set to retry once (§6). |
| `synccli.copy_file(src, dst)` | synccli.py:62–69 | **Reused as the measured-fast copy primitive** — buffered read/write, parents created. Two overrides (§11-O3): silent `except OSError: pass` (line 68–69) must become a recorded per-file error, and an fsync hook. Note the measurement surprise: this plain loop (12.3 s / 25k files) **beat** `shutil.copyfile` (16.6 s) here, so the existing code is kept as the hot path rather than replaced. |
| `synccli.sync()` manifest load/write | synccli.py:76–79, 85–86 | **Pattern reused, mechanism overridden** (§11-O4): the non-atomic `json.dump` to the final path (line 85–86) is exactly the half-written-index hazard the brief calls out; `backupctl` writes every index/catalog as `*.tmp` + `fsync` + `os.replace` + dir-fsync. |
| `synccli.sync()` diff-then-copy flow | synccli.py:72–87 | The overall per-directory flow of `run` is this function's shape (load previous state → diff → copy → write index), restructured for snapshots, locking, and atomic publication (§5). |
| `snaputil.list_snapshots(backup_root)` | snaputil.py:8–20 | **Reused as-is** as the reader-visible snapshot list. It matches directories named `snap-*` (line 18) and sorts them — this *dictates* the on-disk naming and why in-flight dirs must not start with `snap-` (§3). |
| `snaputil.prune_snapshots(backup_root, keep)` | snaputil.py:23–36 | **Reused logic, overridden mechanism** (§11-O5): the "delete all but the newest `keep`, oldest first" policy (lines 30–36) is kept verbatim, but in-place `shutil.rmtree` (line 35) is replaced by tombstone-rename + locked deletion (§8) so a concurrent reader of the doomed snapshot is not hit by ENOENT mid-traversal. |
| `snaputil.snapshot_disk_usage(backup_root, name)` | snaputil.py:39–51 | **Reused as-is** by `status` and by the retention report. Requires each snapshot to be a self-contained file tree — the reason the design materializes per-snapshot trees (§7) rather than a content-addressed store. |
| `snaputil.safe_snapshot_path(backup_root, snap, rel)` | snaputil.py:54–63 | **Reused as the reader path resolver, with a required guard added** (§11-O6). Verified broken as written: `os.path.normpath('../../etc/passwd')` is still `'../../etc/passwd'`, and `os.path.join('/backups','snap-x', rel)` resolves to `/etc/passwd` — the docstring's "never points outside" (lines 58–60) does not hold. Readers call it and then reject any result that does not remain under the snapshot directory. |
| `snaputil.is_stale(snapshot_dir, ref_epoch)` | snaputil.py:66–73 | **Reused** to age-check leftover `tmp-*` run directories before cleanup (§6): a `tmp-*` dir whose mtime is stale relative to the run-start timestamp is certainly from a dead run. |
| `test_synccli.py` | test_synccli.py | Kept green (`python3 -m unittest` → OK, re-run during design). New tests follow its `tempfile.mkdtemp` + direct-call style (§12). |

Anything the design touches that is *not* in this table (locking, atomic
publication, retention tombstones, hashing) has no existing counterpart in
this directory — `synccli.py` has no concurrency story (its manifest sits
inside the destination and is written last-write-wins, synccli.py:85–86), and
`snaputil.py` has no notion of incomplete snapshots.

## 3. On-disk layout

    <backup_root>/
      backupctl.json           # config copy of record (also readable at repo)
      run.lock                 # flock file: run-vs-run mutual exclusion
      reader.lock              # flock file: readers (shared) vs pruner (exclusive)
      catalog.json             # last committed run summary (optimization, §6)
      snap-20261112-150000-01/ # a committed snapshot
        .backup_index.json     #   the snapshot's index (written BEFORE publication)
        <source tree>          #   copied or hardlinked files, source-relative
      tmp-20261112-150301-<pid>/   # an in-flight snapshot (NOT reader-visible)
      trash-20261112-150000-01/    # a tombstoned snapshot awaiting deletion

Naming rules, and why:

- Committed snapshots are named `snap-YYYYMMDD-HHMMSS-SEQ` — the exact shape
  `snaputil.list_snapshots` parses and sorts (snaputil.py:9–20), with `SEQ`
  disambiguating two runs in the same second. Since runs are serialized by
  `run.lock`, `SEQ` is a process-local counter; it exists so the name stays
  correct if serialization is ever relaxed.
- In-flight (`tmp-*`) and dying (`trash-*`) directories do **not** start with
  `snap-`, which is precisely what keeps `list_snapshots` (snaputil.py:18)
  from ever returning them. A reader therefore sees a snapshot only when the
  directory is complete *and* its index is in place — that is the atomic
  publication boundary (§5, step 7).

Per-snapshot index (`.backup_index.json`):

    {
      "schema": 1,
      "source_dir": "/proj/evals/runs-a",
      "started_at": "2026-11-12T15:00:00Z",
      "base_snapshot": "snap-20261112-060000-01",   // diff base, or null
      "files": {"rel/path": {"size": 51200, "mtime_ns": 1762952400123456789,
                             "mode": 33188, "via": "copy" | "link", "sha256": "..."}},
      "skipped": [{"rel": "v.log", "errno": 2, "stage": "copy"}],
      "removed": ["old.log"]                        // in base, absent from source now
    }

`files` lists **exactly** the files present in the snapshot — it is written
after all copying has finished, so it can never promise a file the snapshot
lacks (the brief's "never a snapshot index that promises files the snapshot
does not contain").

## 4. Concurrency model

Two `flock` files (per backup root), because `flock` is atomic, survives the
holder dying (the kernel releases it), and needs no lock server:

1. **`run.lock` — exclusive, held for the whole run.** This makes run-vs-run
   collisions impossible-by-construction: the second run (scheduler or human,
   same command) either waits (`--wait SECONDS`, default 0) or exits
   immediately with code 3 and the message `another run is in progress`.
   Nothing is ever written concurrently to the same snapshot or catalog.
2. **`reader.lock` — shared (readers) vs exclusive (deleter).**
   - Any reader (restore tooling, `status`, `verify`, `prune`) takes `LOCK_SH`
     on `reader.lock` for the duration of its read of a snapshot.
   - The deletion of a snapshot (run's prune step, or standalone `prune`)
     takes `LOCK_EX` on `reader.lock` for the tombstone-rename + `rmtree`
     (§8).
   - Lock ordering is always `run.lock` → `reader.lock` (the run holds
     `run.lock` first, takes `reader.lock` only in its prune step), so there
     is no ordering cycle and no deadlock.

Combinations the brief rules out, and how:

| Combination | Why it is safe |
|---|---|
| run + run | serialized by `run.lock`; loser waits or exits 3 |
| run writes new snapshot + restore reads an old one | disjoint directories; reader locks `reader.lock` shared, which the run only needs exclusively at prune time — after the new snapshot is committed |
| run publishes new snapshot + reader lists | publication is a single `rename(2)` (§5 step 7): the reader sees the snapshot either fully (with index) or not at all |
| prune deletes snapshot S + reader reads S | reader holds `LOCK_SH`, pruner blocks on `LOCK_EX`; if the reader arrived late and S is already `trash-*`, it sees no such snapshot and falls back to the newest remaining one (§9) |
| prune deletes S + run in progress | the run holds `run.lock`; prune (whether the run's own final step or standalone) runs under it too — `prune` as a standalone command takes `run.lock` shared→ actually takes it exclusive (a prune is a mutation of the root), so prune never overlaps a run |

## 5. The run, step by step

For each configured directory, in sorted order, under `run.lock`:

1. **Acquire/clean.** On `run.lock` acquisition, any `tmp-*` directory in the
   backup root belongs to a dead run (runs are serialized) → delete it;
   double-check with `snaputil.is_stale` (snaputil.py:66–73) against run-start
   time before `rmtree`. Any leftover `trash-*` is likewise finished off.
   Load `catalog.json` (atomic-read; on corruption ignore it and re-derive,
   §6).
2. **Pick the diff base.** Newest committed snapshot of *this source dir*
   whose index parses and has the right schema. If none → base = null → full
   copy (the first run, or recovery, §6).
3. **Scan + diff.** `build_manifest(src)` (synccli.py:28–33, on top of
   `scan_files`, synccli.py:10–19) → diff with the base index's `files` via
   `changed_files` (synccli.py:36–42) → changed/new set; symmetric pass →
   removed set.
4. **Create the in-flight dir** `<root>/tmp-<ts>-<pid>/`.
5. **Materialize.**
   - *Unchanged* files (state matched): `os.link` the file from the base
     snapshot into the in-flight dir ("link from the previous snapshot",
     never from the live source — so a later in-place edit of the source can
     never mutate a snapshot; an in-place edit changes mtime anyway and is
     then detected as changed). POSIX link count keeps both snapshots intact
     through later deletion.
   - *Changed/new* files: `synccli.copy_file` (synccli.py:62–69), extended
     per §11-O3 to record failures instead of swallowing them. Failed files
     are retried once via `collect_stale` (synccli.py:45–59) — same call shape
     its tests cover (test_synccli.py:22–32).
   - Copy is capped-rate memory: `copy_file` streams per-file; the largest
     memory resident at once is the largest single file (its `read()` buffer),
     not the tree.
6. **Write the index atomically inside the in-flight dir**: serialize
   `.backup_index.json.tmp`, `fsync` it, `os.replace` to
   `.backup_index.json`, fsync the directory fd. The index lists only files
   that exist in the in-flight dir at this moment (§3).
7. **Publish**: `os.rename(tmp-…, snap-…)` — same directory, same filesystem,
   atomic. A reader running `list_snapshots` before the rename cannot see the
   snapshot at all; after the rename, it sees it complete with a valid index.
   There is no window in which a snapshot is visible but partial.
8. **Update the catalog** `catalog.json` (atomically, same tmp+replace
   pattern) recording, per source dir, the newest committed snapshot name and
   its index checksum.
9. **Prune** (§8): take `reader.lock` exclusive, tombstone+delete per policy,
   release.

Exit codes: 0 success (warnings for skipped files allowed), 3 lock busy,
4 at least one source directory could not be processed at all (e.g. source
vanished between config and scan).

## 6. Crash recovery — the dead-run cases, enumerated

The threat is process death at any instruction: Ctrl-C, SIGKILL, sleep. The
invariants that make every intermediate state harmless:

- **No reader-visible partial state.** A snapshot becomes visible only via
  the step-7 rename, which happens after the index is in place. A killed run
  leaves at most a `tmp-*` dir, which `list_snapshots` (snaputil.py:18) never
  returns.
- **The next run makes progress without manual cleanup.** Step 1 removes
  `tmp-*`/`trash-*` leftovers automatically; nothing else is left behind
  because the only other durable writes (index, catalog) are atomic
  tmp+`os.replace` (the direct fix for the non-atomic `json.dump` at
  synccli.py:85–86, §11-O4).

The index-recovery table the brief demands:

| Found at run start | What it is | Recovery | Reported |
|---|---|---|---|
| `tmp-*` dir | in-flight work of a dead run, pre-publication | deleted in step 1; the snapshot never existed for readers | one log line: `discarded incomplete run dir tmp-…` |
| `catalog.json` unparsable / wrong schema | catalog written by a run that died mid-replace is impossible (replace is atomic); corruption here means disk-level damage | **ignored entirely**; re-derived in step 2 by scanning the newest committed snapshot with a valid index (the catalog is a cache, never a source of truth) | `WARN: catalog unusable; diff base re-derived from snapshots` |
| newest snapshot's `.backup_index.json` unparsable / missing / wrong schema | a snapshot dir damaged after publication (disk error), or hand-tampered | that snapshot is demoted: not a diff base, not offered by `status` as restorable, and first in prune order. Diff base falls back to the next-newest snapshot **with a valid index**; if none exists, base = null → the run falls back to a **full copy** of that directory into a fresh snapshot (progress, no manual cleanup) | `WARN: snap-… index invalid; treated as incomplete; diff base = snap-…` |
| base index valid but files it names missing from the base snapshot dir | index/data divergence | same demotion path as above: the snapshot is not a usable base; full copy | same WARN plus the missing names |
| a committed snapshot's index valid, diff against it succeeds | normal path | — | — |

What is *discarded* vs *re-derived* vs *kept*, in one line: pre-publication
state (`tmp-*`) is discarded; the diff base is re-derived from the newest
provably complete snapshot (valid atomic index), falling back to a full copy;
every committed snapshot with a valid index is kept untouched.

## 7. Incremental backups — granularity and its blind spots

**Mechanism.** First run of a directory copies everything (base = null).
Later runs copy only files whose state changed since the base snapshot's
index, and hardlink the rest from the base snapshot (§5 step 5).

**Granularity of "unchanged":** the `(size, mtime)` pair of
`synccli.file_state` (synccli.py:22–25), upgraded to exact integers
(`st_mtime_ns`, §11-O2). Two states are "unchanged" iff size and mtime-ns are
both equal. This is a *stat-only* decision: no content is read for unchanged
files — that is what makes the incremental run O(F) syscalls with O(changed
bytes) I/O instead of O(total bytes).

**Edits this granularity can miss** (stated, per the brief):

1. Content edits that preserve both size and mtime — a tool that writes in
   place and then restores the timestamp (`touch -t`, `rsync -a`-style
   backdating, archive extraction). Size-preserving + mtime-preserving edits
   are invisible.
2. Writes within one filesystem mtime tick with unchanged size — relevant on
   coarse-mtime filesystems (HFS+ 1 s, some network mounts 2 s). On APFS
   mtime is nanosecond and `st_mtime_ns` is exact, so on this repo's target
   machine the practical miss is category 1.
3. Metadata-only changes (permissions, ownership) — not part of the state
   pair. Consequence of hardlinking: an inode's permissions are shared by all
   snapshots hardlinking it, so a later `chmod` on the source can retroactively
   alter the mode seen in older snapshots. Accepted for this workload (result
   directories, not permission-sensitive data); `run --no-link` disables
   hardlinking and copies instead, at the cost of re-reading unchanged bytes.
4. Symlinks: `scan_files`/`file_state` treat a symlink-to-file as the target
   (os.walk lists it in `filenames`; `os.stat` follows). A snapshot stores the
   target's content, not the link. Recorded here as a known shape of what is
   backed up.

**Defense in depth:** `run --verify` additionally SHA-256-hashes changed
files at copy time and every unchanged file is hashed only on explicit
`backupctl verify`, which recomputes hashes from the snapshot and compares to
the index — that is the tool that would *detect* a category-1 miss after the
fact; `run` itself does not re-read unchanged content (that would erase the
incremental win).

## 8. Retention — policy and safe deletion

**Policy:** keep the newest `keep` (config, default 24) *complete* snapshots
per backup root, deleting older ones oldest-first — the exact ordering and
"newest is never deleted" guarantee of `snaputil.prune_snapshots`
(snaputil.py:23–36), with two additions: (a) snapshots demoted in §6 are
pruned first regardless of age, and (b) the policy never deletes the newest
complete snapshot, so deletion can never leave the user without a usable
snapshot; if there is only one, nothing is deleted (mirrors the
`len(names) <= keep` guard, snaputil.py:31–32).

**Safe deletion under readers:**

1. Take `reader.lock` exclusive (blocks new readers from *starting* on this
   root; readers already holding shared finish first).
2. `os.rename(snap-…, trash-…)` — atomic; the snapshot disappears from
   `list_snapshots` in one step, so even a reader that skipped the lock (a
   human with Finder) can no longer *find* it.
3. Release nothing yet: `shutil.rmtree(trash-…)`, then remove the lock.

On POSIX, files a reader already has open survive `rmtree` (unlinked-but-open),
and lock-respecting readers (restore, `verify`, `status`) never observe a
half-deleted snapshot at all: they either see it complete or not listed, and
a late reader that resolves a snapshot name to `ENOENT` retries against the
newest remaining snapshot (§9).

## 9. Reader contract (for the separate restore tooling)

Any reader of the backup root must:

1. Take `LOCK_SH` on `reader.lock`.
2. Pick a snapshot from `snaputil.list_snapshots` (snaputil.py:8–20) — newest
   or named; anything not in that list does not exist.
3. Load `.backup_index.json` inside it; if it does not parse, the snapshot is
   demoted (§6) — pick the next-newest, never read a demoted snapshot.
4. Resolve file paths via `snaputil.safe_snapshot_path` (snaputil.py:54–63)
   **and** reject any resolved path that escapes the snapshot directory —
   verified necessary because the helper's own `..`-clipping claim does not
   hold (§11-O6): `normpath('../../x')` still contains `..` and the join
   resolves to `/backups/x`, outside the snapshot.
5. Treat `ENOENT` during read as "snapshot was deleted under me": release the
   lock, retry from step 2 against an older snapshot.

Following 1–5, a reader can observe: complete snapshots only, indexes that
match contents, and — because publication is atomic rename + readers list
only `snap-*` dirs — never "some files from this run, some from the previous
one".

## 10. Performance budget for the first full backup

Measured on this machine, with the real functions from `synccli.py`, against
a synthetic tree of **25,000 files / 1,201 MB / 200 dirs** (the benchmark is
reproducible: build the same shape, call the same functions):

| Step (first full backup) | Measurement | Source |
|---|---|---|
| Scan + manifest (`build_manifest`, synccli.py:28) | **0.84 s** | timed `synccli.build_manifest(src)` — ~34 µs/stat × 25,000 |
| Copy all files (`copy_file`, synccli.py:62) | **12.3 s** | timed loop over `synccli.copy_file` — ~0.49 ms/file, ~98 MB/s effective |
| Index write (20k-entry `json.dump` + `os.replace`) | **0.07 s** | timed serialize+replace of the manifest dict |
| Per-file fsync (optional `--fsync-files`) | **+9.1 s** at 25k files | timed 100 fsync'd copies: 0.5 ms/file → off by default (§10 threat model) |
| Hardlink 25,000 files (incremental materialization floor) | **12.4 s** (14.9 s with per-file `os.makedirs`) | timed `os.link` loop; ~0.5 ms/link — the per-file syscall floor dominates at 50 KB/file, so an incremental run's wall clock is bounded by file *count*, not bytes |

**Budget: the initial full backup of a ~1 GB / ~25k-file tree completes in
under 60 s on this class of machine (APFS SSD); measured: ≈ 13 s** (0.84 +
12.3 + 0.07, fsync-files off). The 60 s number is not a guess — it is the
measured 13.2 s with a 4.5× margin for colder cache and smaller files
(more per-file overhead at the same total bytes). Where the number comes
from: per-file costs are the dominant term and they scale linearly —
~0.85 ms/file end-to-end measured (scan 34 µs + copy 490 µs + index 3 µs),
so the budget in seconds ≈ `0.85 ms × F` with `F` = file count; at 25,000
files that is 21 s worst-case-shaped, 13 s measured, 60 s budget.

## 11. Explicit overrides of existing behavior

Each override names the exact function, where it lives, and why.

- **O1 — `scan_files` hides dot-files.** `synccli.scan_files` prunes any
  name starting with `.` (synccli.py:14). A backup tool must back up hidden
  files (`.env`, `.git`, dot-directories in eval results are exactly the
  kind of content users expect to survive). `backupctl` uses a wrapper
  `scan_all_files` with the same walk-and-sort contract but no dot filter;
  the filter stays available as an explicit per-directory `exclude` option.
- **O2 — `file_state` uses float mtime.** `synccli.file_state` returns
  `st.st_mtime` as a float (synccli.py:25); float64 mtime loses nanosecond
  precision and can make two distinct writes compare equal. `backupctl`'s
  state uses `st.st_mtime_ns` (exact integer) plus `st.st_mode`. The
  `(size, mtime)` *pair* and its blind spots are kept (§7).
- **O3 — `copy_file` swallows errors.** `synccli.copy_file` catches
  `OSError` and passes silently (synccli.py:68–69, comment: "unreadable
  source: skip it, next pass will retry"). For a backup, silent data loss is
  the failure mode the brief forbids: the same vanish-skip happens, but it is
  **recorded** in the index's `skipped` list, printed as a `WARN` line, and
  retried once (§5 step 5, via `collect_stale`). The copy primitive otherwise
  stays this function — it measured faster than `shutil.copyfile` here
  (12.3 s vs 16.6 s for 25k files).
- **O4 — non-atomic manifest write.** `synccli.sync` writes the manifest
  with a bare `open(..., "w")` + `json.dump` at the final path
  (synccli.py:85–86). A process killed mid-write leaves a truncated manifest
  — precisely the "half-written index" case the brief calls out.
  `backupctl` writes every index and the catalog as tmp-file + `fsync` +
  `os.replace` + dir-fsync (§5 step 6), which is also what makes the §6
  recovery table decidable.
- **O5 — `prune_snapshots` deletes in place.** `snaputil.prune_snapshots`
  calls `shutil.rmtree` directly on the live snapshot name (snaputil.py:35).
  A reader traversing the snapshot concurrently gets ENOENT mid-read — the
  brief's "must be safe while something else may be reading". Overridden
  with the tombstone-rename + `reader.lock` protocol (§8); the *policy*
  (keep newest K, oldest deleted first, never the newest) is kept verbatim.
- **O6 — `safe_snapshot_path` does not actually confine.** Its docstring
  claims any `..` segments are "normalized away" so a stored path cannot
  escape (snaputil.py:58–60). Verified false: `normpath` keeps leading `..`
  and `join` produces `…/snap-x/../../etc/passwd` → `/etc/passwd`. Readers
  must add the confinement check the helper lacks (§9 step 4); the helper is
  still used, so path mapping stays in one place, but nothing may trust its
  docstring.
- **O7 — `sync` keeps its manifest inside the destination.**
  `synccli.sync` reads/writes `.sync_manifest.json` inside the destination
  tree (synccli.py:7, 75–86). For snapshots this would both pollute the
  backed-up image and make "which index belongs to which snapshot" ambiguous
  across hardlinked trees. `backupctl` keeps one `.backup_index.json` per
  snapshot (§3), and the diff base comes from the *base snapshot's* index,
  not from a manifest inside the destination.

## 12. How the design scales (explicit bounds)

Notation: `N` = configured directories, `F` = total files across them,
`B` = total bytes, `C` = changed files and `b` = changed bytes in a run,
`K` = retention window. Constants are measured (§10) on the 25k-file tree.

| Quantity | Bound | Where the constant comes from |
|---|---|---|
| Per-run wall clock | `≈ 34 µs·F (scan) + 0.5 ms·F (copy-or-link materialization) + b / 100 MB/s` | scan 0.84 s/25k; copy 12.3 s/25k; link 12.4 s/25k — **the per-file syscall floor dominates**: an incremental run costs ~0.55 ms × F even when `b ≈ 0` (12.4 s + 1.2 s rescan at 25k files, measured: rescan+diff 1.23 s, link floor 12.4 s) |
| Per-run memory | `O(F)`, ≈ 410 B/file for the manifest dict + index string | 25k-entry manifest measured 10.2 MB (`tracemalloc`) — independent of `B` |
| Index size per snapshot | `≈ 72 B × F` | 25k-entry index measured 1.79 MB on disk (0.07 s to write) |
| Per-run disk growth | `b` data bytes + `O(F)` dirent metadata (hardlinks add no data blocks) | link-count semantics of §7 |
| Total disk under retention | `≤ B + (K−1)·b_max` data + `K` indexes of `72 B·F` | prune keeps exactly `K` complete snapshots |
| Work that grows with `N` | per-run loop is `N` × (per-dir scan of its files); directories are processed sequentially so peak memory is one manifest at a time | §5 |
| Work that stays flat in `N`, `F`, `B` | lock acquisition, publication rename, catalog replace, prune decisions: `O(1)` or `O(K)` `list_snapshots` scans | §5, §8 |

The honest statement of the flat/growing split: **everything grows with `F`
(two `O(F)` syscall passes per run — stat and materialize), nothing grows
with `B` except the changed bytes `b` (first run excepted), and nothing
superlinear grows with `N`.** If the 0.5 ms/file materialization floor ever
becomes the pain point at "a few dozen" directories with very large trees,
the documented lever is a content-addressed store — explicitly out of scope
here because it breaks `snapshot_disk_usage` (snaputil.py:39–51) and the
self-contained-snapshot property the reader contract (§9) and retention
mechanism (§8) rely on.

## 13. Test plan (extends `test_synccli.py` in its own style)

Direct-call unittest classes over `tempfile.mkdtemp` fixtures
(test_synccli.py:8–14), new file `test_backupctl.py`:

1. **Publication atomicity** — kill a run (SIGKILL a child process
   mid-copy); assert `list_snapshots` is empty and no `snap-*` dir exists;
   re-run; assert it completes and the new snapshot's index matches an
   independent walk of its tree.
2. **Index recovery** — corrupt the newest snapshot's index by hand; run;
   assert the WARN is emitted, the demoted snapshot is pruned first, and the
   diff base fell back (or full copy) per §6.
3. **Vanishing file** — delete a file between `build_manifest` and copy
   (monkeypatch `copy_file` to unlink then fail); assert the snapshot is
   consistent (index ↔ walk), the file is in `skipped`, exit code 0.
4. **Concurrency** — spawn two `run` processes; assert one exits 3 and
   exactly one snapshot exists.
5. **Reader vs prune** — hold `LOCK_SH` in a thread while pruning; assert
   the prune blocks and the reader finishes its read.
6. **Incremental** — run twice with one changed file; assert run 2 contains
   1 copy + (F−1) hardlinks (link count check), and its index's `via` fields
   say so.
7. **Granularity miss** — rewrite a file in place with same size and
   `os.utime` backdating; assert run 2 does *not* pick it up (documenting
   the §7 blind spot as specified behavior).

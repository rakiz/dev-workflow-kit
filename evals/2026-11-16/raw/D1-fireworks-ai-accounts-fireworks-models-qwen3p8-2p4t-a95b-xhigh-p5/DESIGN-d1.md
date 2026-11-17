# DESIGN-d1 — `backupctl`

Design of `backupctl`, a snapshot backup tool for the `evals/` result
directories, to live in this directory alongside `synccli.py` and
`snaputil.py` and ship in the same repo.

Every claim about the existing code below was checked by running it
(§17, Appendix A); every performance number was measured on a real
1 GB / 20,000-file tree (§12, Appendix B), not estimated.

Notation used in bounds:

| Symbol | Meaning |
|---|---|
| `N` | number of configured source directories (3 today, a few dozen over time) |
| `F` | total number of files across all sources (`F = Σᵢ Fᵢ`) |
| `B` | total bytes across all sources (`B = Σᵢ Bᵢ`) |
| `Cₖ`, `nₖ` | bytes changed / files changed in run `k` |
| `K` | retention: number of snapshots kept |

---

## 1. Summary

`backupctl run` produces **snapshots**: immutable, point-in-time copies of
all configured source directories, stored under one backup root as
directories named `snap-YYYYMMDD-HHMMSS-NN` — exactly the naming
`snaputil.list_snapshots` already parses (snaputil.py:8-20, docstring
lines 12-13), so listing, ordering, pruning and sizing come from
`snaputil` for free.

The core mechanism is **stage-then-atomically-publish**:

1. One writer at a time, enforced by an `flock` on a lock file in the
   backup root (auto-released by the kernel if the holder dies — verified,
   §17 A3). Readers never lock and never ask whether a run is in progress.
2. A run builds the whole snapshot in a staging directory
   (`backup_root/staging/run-<pid>-<epoch>`) that no reader can see —
   `list_snapshots` only recognizes `snap-*` names (snaputil.py:18;
   verified, §17 A10).
3. Unchanged files are **hardlinked** from the previous snapshot
   (`os.link`, zero bytes moved); changed/new files are copied in 1 MiB
   chunks with per-file `fsync`.
4. The index (`snapshot.json`) is written **from copy/link results**, so it
   can never promise a file the snapshot does not contain; it is written
   temp+fsync+rename inside staging, then the staging directory is
   published with a single `os.rename` to its final `snap-*` name. A
   directory rename is atomic: a reader either does not see the snapshot
   or sees it complete.
5. Old snapshots are deleted **rename-first**: `snap-X` → `trash-snap-X`
   (atomically invisible to readers) → `rmtree`.
6. Any run start sweeps leftovers of dead runs (`staging/*`, `trash-*`)
   under the lock, so an interrupted run never blocks progress and never
   leaves anything a reader could mistake for a snapshot.

Change detection reuses `synccli` unchanged: the snapshot index's `files`
map *is* a synccli manifest (`{relpath: {"size":…, "mtime":…}}`, the exact
output shape of `synccli.file_state`, synccli.py:22-25, collected by
`synccli.build_manifest`, synccli.py:28-33), so
`synccli.changed_files(base_index["files"], new_scan)` (synccli.py:36-42)
computes the copy set with zero new change-detection code.

Where current code does the opposite of what the brief demands, §5.2 names
the exact function and line being overridden and why — e.g.
`synccli.copy_file`'s silent `except OSError: pass` (synccli.py:68-69)
combined with `synccli.sync` writing the *source* manifest regardless of
copy failures (synccli.py:85-86) demonstrably produces a manifest that
promises files the destination does not contain (verified, §17 A5) — the
exact failure the brief forbids.

---

## 2. Reference environment and verification method

| | |
|---|---|
| Machine | Apple M3 Max (14 cores), 36 GB RAM |
| OS / FS | macOS 15.8.1 (24H32), APFS |
| Python | 3.10.11 |
| Baseline | `python3 -m unittest` in this directory: 6/6 tests pass (§17 A1) |

All behavioral claims (§5, §7, §8, §10, §11) were verified by executing
the existing code; results are logged in Appendix A. All performance
constants were measured on a fixture of 20,000 files × 50 KB (1.02 GB) in
200 directories; recipes to reproduce are in Appendix B. Numbers carry a
conservative rounding for budget use; measured ranges are shown.

Assumption: the backup root lies on a single filesystem (hardlinks and
atomic directory rename require same-fs; staging lives *inside* the backup
root, so this holds by construction).

---

## 3. Layout and data model

```
backup_root/
  backupctl.lock                 flock target; contains writer pid (diagnostic only)
  staging/                       invisible to readers (not snap-*)
    run-<pid>-<epoch>/           one live run at a time; dead ones swept at next start
      <source-name>/<relpath>    copied or hardlinked files
      snapshot.json              index (written last, before publish)
      snapshot.json.tmp          transient during index write
  snap-20261116-120000-00/       committed snapshot (atomic rename product)
    snapshot.json                self-contained index
    <source-name>/<relpath>      payload
  trash-snap-20261101-000000-00/ transient during prune; swept at next start
```

**Naming.** `snap-YYYYMMDD-HHMMSS-NN` verbatim per the
`list_snapshots` docstring (snaputil.py:12-13): zero-padded date, time,
and a 2-digit run sequence. Because every field is fixed-width and
zero-padded, `list_snapshots`' lexicographic `sorted()` (snaputil.py:20)
is chronological — verified (§17 A10). The timestamp is taken at *commit*;
single-writer serialization makes commit order == name order.

**Multi-source layout.** Config maps a unique short name to each source
path (`{"results": "evals/results", …}`). Inside a snapshot, each source
occupies `snap-*/<source-name>/…`, and index keys are
`"<source-name>/<relpath>"`. One flat merged manifest per snapshot means
`synccli.build_manifest` runs per source (unmodified) and its output is
merged with prefixed keys — `synccli.changed_files` then needs exactly one
call over the merged maps. Duplicate source names are rejected at config
load.

**Index schema** (`snapshot.json`, inside each snapshot):

```json
{
  "format": "backupctl-index-v1",
  "started_at": 1763295600.0,
  "committed_at": 1763295610.4,
  "sources": {"results": "evals/results", …},
  "base_snapshot": "snap-20261116-000000-00",   // null on a full backup
  "files":   {"results/run42/metrics.json": {"size": 4096, "mtime": 1763290000.123}, …},
  "skipped": [{"path": "results/run43/tmp.bin", "stage": "copy", "errno": 2, "strerror": "No such file or directory"}],
  "counts":  {"copied": 1000, "linked": 19000, "deleted": 5, "skipped": 1}
}
```

The `files` map has *exactly* the value shape `synccli.file_state` returns
(synccli.py:25) and `synccli.build_manifest` collects (synccli.py:28-33) —
that is what makes `synccli.changed_files` (synccli.py:36-42) directly
reusable against it. There is deliberately **no global index** anywhere in
the backup root: each snapshot is self-contained, discovery is
`list_snapshots` (snaputil.py:8-20), and "latest" is the last list element.
There is therefore no shared file whose half-written state could corrupt
more than one snapshot — the only index a dead run can leave half-written
is inside its staging directory, which is unsweepable-as-data and
indistinguishable from garbage (§8).

---

## 4. What exists (baseline)

- `synccli.py` — source→destination sync driven by `.sync_manifest.json`
  (`MANIFEST_NAME`, synccli.py:7): scan (`scan_files`, 10-19), state
  (`file_state`, 22-25), manifest (`build_manifest`, 28-33), diff
  (`changed_files`, 36-42), copy (`copy_file`, 62-69), driver (`sync`,
  72-87), CLI (`main`, 90-99).
- `snaputil.py` — snapshot helpers: `list_snapshots` (8-20),
  `prune_snapshots` (23-36), `snapshot_disk_usage` (39-51),
  `safe_snapshot_path` (54-63), `is_stale` (66-73), CLI `main` (76-88).
- `test_synccli.py` — unittest suite (6 tests, all passing), tempfile
  fixture style (test_synccli.py:9-15).

`backupctl` will be a new module `backupctl.py` in this directory,
importing `synccli` and `snaputil`, with `test_backupctl.py` in the same
unittest style.

---

## 5. Grounding map

### 5.1 Reused as-is

| Existing function | Location | Role in `backupctl` |
|---|---|---|
| `synccli.scan_files` | synccli.py:10-19 | Source enumeration: sorted relative file paths; `os.walk` (line 13), dot-directories filtered (line 14). Used per source; keys prefixed with `<source-name>/`. |
| `synccli.file_state` | synccli.py:22-25 | The change-detection state: `{"size": st.st_size, "mtime": st.st_mtime}` (line 25), via `os.stat` (line 24, follows symlinks). Defines the "unchanged" granularity (§10). |
| `synccli.build_manifest` | synccli.py:28-33 | Builds `{relpath: state}` for a source (lines 31-32) — and, at recovery time, re-derives a corrupt base index by manifesting the *snapshot tree* itself (§8.3). |
| `synccli.changed_files` | synccli.py:36-42 | The whole diff step: `changed_files(base_files, new_scan)` returns the copy set (new or state-differing, lines 39-41). Any inequality triggers a copy (line 40), so mtime *regressions* (e.g. after a restore) are also caught. |
| `synccli.copy_file` — structure only | synccli.py:62-69 | Parent-dir creation + read/write loop is the base shape of backupctl's copier; three named overrides in §5.2 (O1-O3). |
| `synccli.sync` — `dry_run` pattern | synccli.py:81-82 | `backupctl run --dry-run`: compute and print the plan, write nothing (same early-return shape). |
| `snaputil.list_snapshots` | snaputil.py:8-20 | Snapshot discovery and ordering for commit naming, base selection, pruning, `list`, and the reader/restore contract. Verified: ignores `staging/`, `trash-*`, `lock`, plain files (line 18 keeps only `snap-*` directories); zero-padded names sort chronologically (line 20). |
| `snaputil.prune_snapshots` — selection | snaputil.py:23-33 | Which snapshots are doomed: `names[:len(names) - keep]` (line 33), oldest first, with the `len(names) <= keep` guard (lines 31-32). Verified: with keep=2 over 3 snapshots it deletes only the oldest (§17 A11). The deletion *step* (line 35) is overridden (§5.2, O6). |
| `snaputil.snapshot_disk_usage` | snaputil.py:39-51 | Per-snapshot apparent size for `list`/reports (`st_size` sum, lines 49-50). Note: it counts a hardlinked file in *every* snapshot — verified 1025 MB reported for each of three snapshots sharing one inode set (§17 A12); `backupctl` therefore additionally reports true/marginal bytes (§11.3). |
| `snaputil.safe_snapshot_path` | snaputil.py:54-63 | Inside `backupctl`'s hardened resolver `resolve_in_snapshot()` (§5.2, O7) for mapping index keys back under a snapshot — the link step and the restore contract both go through it. |
| `snaputil.is_stale` | snaputil.py:66-73 | The optional age-based retention axis (§11.2): a snapshot is age-doomed when `is_stale(snap_dir, now − keep_days·86400)`. Committed snapshot dirs are never modified after publish, so their `st_mtime` is a stable run-time proxy. Boundary semantics: implementation is `<=` (line 73) — verified `True` at exactly `ref_epoch` despite the docstring claim (lines 71-72, §17 A13); backupctl follows the *implementation* and documents the boundary as inclusive (immaterial at day granularity). |
| CLI shape | synccli.py:90-99, snaputil.py:76-88 | argparse subcommand style; run reports print one line per notable event, like `synccli.main`'s per-file prints (lines 97-98) and `snaputil.main`'s `deleted`/size lines (lines 83-87). |
| Test style | test_synccli.py:8-51 | `unittest` + `tempfile.mkdtemp` fixtures (lines 9-15); sync-level end-to-end assertions (lines 42-51). Extended with subprocess kill/lock tests (§15). |

### 5.2 Overrides (named, located, reasoned)

Each override names the exact existing behavior it replaces, where that
behavior lives, the requirement it violates, and the observed evidence.

**O1 — chunked copy replaces whole-file read.**
`synccli.copy_file` reads the entire source into one buffer:
`fdst.write(fsrc.read())` (synccli.py:66-67). Memory is O(largest file):
measured 52 MB tracemalloc peak copying a single 50 MB file (§17 B, C).
`backupctl` copies with `shutil.copyfileobj(fi, fo, 1 MiB)` — measured
2.1 MB constant peak on the same file — so per-run memory is bounded by
§13's formula, not by the largest file.

**O2 — reported copy results replace silent swallowing.**
`synccli.copy_file` ends in `except OSError: pass` (synccli.py:68-69): an
unreadable or vanished source is skipped with no signal. Worse,
`synccli.sync` then reports it as copied (`to_copy` is returned unchanged,
synccli.py:87) and writes the *full source manifest* to the destination
regardless of which copies succeeded (synccli.py:85-86 writes
`src_manifest`, not the copied subset). Verified end-to-end: an unreadable
source file appears in `sync`'s returned "copied" list *and* in the
destination manifest while being absent from the destination tree (§17 A5)
— precisely the brief's "an index that promises files the snapshot does not
contain". `backupctl`'s copier returns a per-file result
(`copied | skipped(stage, errno)`), the index `files` map is built **only
from successes** (§9), and every skip is reported (§14).

**O3 — pre-created directories replace per-file `makedirs`.**
`synccli.copy_file` calls `os.makedirs(os.path.dirname(dst), exist_ok=True)`
per file (synccli.py:64). Measured: 25-55 µs/file when the directory
already exists; pre-creating the unique dirname set derived from the scan
list costs 27 ms total for 200 directories (§17 B, 4/7). Since
`scan_files` yields the full path list before copying starts, `backupctl`
pre-creates all directories once per run (staging tree and link tree) and
copies/links into them.

**O4 — stage+atomic-publish replaces in-place destination mutation.**
`synccli.sync` copies changed files directly into the live destination
(synccli.py:83-84) and only then rewrites the manifest (85-86): a reader
during a run sees a mix of old and new files — the brief's "a mix of some
files from this run, some from the previous one". `backupctl` never mutates
anything a reader can see: the run builds `staging/run-<pid>-<epoch>`
(invisible per snaputil.py:18) and publishes it with one `os.rename`
(§7.2). Verified rename semantics underpinning this: renaming a directory
onto an existing **non-empty** directory fails `ENOTEMPTY` (errno 66), and
onto an existing **empty** directory it silently replaces (§17 A2) — the
staging tree always contains `snapshot.json` before the rename, so it is
never empty and a collision can never silently replace a committed
snapshot (§7.3).

**O5 — durable index write + recovery replace in-place non-atomic write.**
`synccli.sync` writes the manifest with a plain `open(path, "w")` +
`json.dump` (synccli.py:85-86): a kill mid-write leaves a truncated file,
and the next `sync`'s unguarded `json.load` (synccli.py:77-79) dies with
`JSONDecodeError` — verified (§17 A8). `backupctl` (a) writes the index as
`snapshot.json.tmp` → `flush` → `fsync` → `os.rename` within staging
(visible only via the whole-directory publish), and (b) *defines recovery*
when a base index is nonetheless invalid — discard the index text,
re-derive the `files` map from the snapshot tree with
`synccli.build_manifest`, report what happened (§8.3).

**O6 — rename-then-destroy replaces in-place `rmtree` on live names.**
`snaputil.prune_snapshots` deletes by `shutil.rmtree` directly on the
canonical snapshot path (snaputil.py:35): a concurrent reader can watch a
canonical `snap-*` name disintegrate file by file. `backupctl` keeps the
selection logic (snaputil.py:30-33) and replaces the deletion step:
`os.rename(snap-X → trash-snap-X)` — atomically invisible to
`list_snapshots` (verified, §17 A10) — then `shutil.rmtree` on the trash
path. A kill between the two leaves a `trash-*` leftover, swept at next
start (§8.2).

**O7 — containment-checked path resolution replaces bare
`safe_snapshot_path`.**
`snaputil.safe_snapshot_path` (snaputil.py:54-63) claims the result
"never points outside backup_root/<snapshot_name>" (docstring lines 58-61)
because `os.path.normpath` (line 62) "normalizes away" `..` segments.
Verified false in both directions (§17 A4): an absolute `rel_path`
(`/etc/passwd`) makes `os.path.join` (line 63) discard the snapshot prefix
entirely, and net-leading `..` (`../../etc/passwd`, `a/../../etc`) survives
`normpath` and climbs out. Paths *produced* by `scan_files` are safe
(`os.path.relpath` under the root can't start with `/` or `..`), but the
function is the restore-side resolver for *stored* index keys, and a
corrupt/tampered index is exactly the input recovery must survive.
`backupctl.resolve_in_snapshot(root, snap, rel)` calls
`snaputil.safe_snapshot_path` and then enforces containment: reject keys
whose `normpath` is absolute or starts with `..`; require the resolved
absolute path to start with `os.path.join(root, snap) + os.sep`.

**O8 — stat-failure-tolerant manifesting replaces crash-on-unstatable.**
`synccli.file_state` calls bare `os.stat` (synccli.py:24) and
`synccli.build_manifest` has no error handling (synccli.py:31-32): a
broken symlink or a file that vanishes *during the scan* kills the whole
run — verified `FileNotFoundError` propagates (§17 A6). The brief requires
surviving exactly this ("vanish between listing and copying").
`backupctl` wraps state collection: per file, `os.stat` + `stat.S_ISREG`
check; any `OSError` (or non-regular file: fifo, socket, device) is
recorded as `skipped(stage="stat", errno, strerror)` and the file is
omitted from the manifest — the run continues (§9). `synccli.file_state`
itself remains the state producer for stat-able regular files; the wrapper
only adds the failure path it lacks.

**O9 — optional full scan replaces the dot-directory filter (default off).**
`synccli.scan_files` skips every directory whose name starts with `.`
(synccli.py:14; verified: `.hidden/inner.txt` absent from results while
`.dotfile` is kept, §17 A7). For a *backup* tool, silently omitting
dot-directories is potential data loss, so config accepts
`"include_dotdirs": true`, which switches enumeration to
`backupctl.scan_files_all` — the same walk as synccli.py:10-19 with the
line-14 filter removed (the one place backupctl re-implements an existing
function, for this named reason). Default is `false`: reuse
`synccli.scan_files` as-is, consistent with the neighboring tool, and the
evals result directories contain no dot-directories. The behavior is
documented in the run report either way.

### 5.3 Reviewed, not used

- `synccli.collect_stale` (synccli.py:45-59): "collect items not marked
  fresh" duplicates what `prune_snapshots`' doomed-slice (snaputil.py:33)
  and `changed_files` (synccli.py:36-42) already compute for retention and
  change detection respectively. No backupctl step needs it; forcing it in
  would obscure, not ground.
- `snaputil.main` (snaputil.py:76-88): its `--prune` path (79-84) calls
  `prune_snapshots` directly — no lock, no rename-first. `backupctl` never
  calls `snaputil.main`; running the raw `snaputil` CLI against a
  `backupctl` root is documented as unsupported (§16, L7).
- `synccli.MANIFEST_NAME` (synccli.py:7): the snapshot index is named
  `snapshot.json`, not `.sync_manifest.json` — it is a different artifact
  (self-contained per snapshot, richer schema, §3). The precedent reused is
  the *pattern*: a JSON metadata file living inside the tree it describes.

---

## 6. Run lifecycle

`backupctl run` (single implementation; scheduler and human invoke the
identical code path, §9.3):

```
 0. Load config; validate (unique source names; sources exist; backup_root
    on one filesystem). makedirs(backup_root, staging).
 1. Acquire writer lock (§7.1). On contention: wait up to --lock-timeout
    (default 0), then exit 2.
 2. Sweep dead-run leftovers under the lock: rmtree(staging/*), rmtree(trash-*)
    (§8.2). Report each (name, file count, bytes).
 3. Select base: newest snapshot (list_snapshots, snaputil.py:8-20) whose
    index VALIDATES (§8.3); on invalid index try re-derivation from its
    tree; if that fails, try the next-newest; if none usable, base = null
    (full backup). Report the choice and any recovery performed.
 4. Scan: for each source, build_manifest (synccli.py:28-33) via the
    O8-tolerant wrapper; merge with "<source-name>/" prefixed keys.
    Record skips (stage="stat").
 5. Diff: to_copy = synccli.changed_files(base_files, new_scan)
    (synccli.py:36-42); to_link = keys(new_scan) − set(to_copy);
    deleted = keys(base_files) − keys(new_scan)   (reported only;
    changed_files by construction never returns deletions — verified §17 A9).
    If --dry-run: print counts/plan and exit 0 here (pattern of
    synccli.py:81-82). Nothing has been written.
 6. Create staging dir staging/run-<pid>-<epoch>; pre-create all needed
    directories from the scan list once (O3).
 7. Link unchanged: for rel in to_link:
       os.link(resolve_in_snapshot(root, base, rel), staging/rel)
    On link failure (base tree missing a file its index promised, §10.4):
    fall back to copy-from-source; on failure of both: skip(stage, errno).
 8. Copy changed/new: for rel in to_copy: chunked copy (O1) + flush +
    fsync(file) [default on, §8.4]. Success → record state (the scan-time
    file_state dict); failure → skip(stage="copy", errno).
 9. Write index: snapshot.json.tmp = {schema §3, files = successes only,
    skipped, counts, base_snapshot}; flush + fsync(tmp); rename over
    snapshot.json; fsync(staging dir).
10. Publish: name = snap-<commit-time>-NN, NN from 00; os.rename(staging/run-*,
    backup_root/name); on ENOTEMPTY/EEXIST bump NN and retry (§7.3, cap 100);
    fsync(backup_root dir). The snapshot is now visible, complete, at once.
11. Prune (§11): doomed = prune_snapshots-selection (snaputil.py:30-33)
    with keep=K, plus age axis if configured; apply the I3 usable-guard;
    for each: rename to trash-<name> (O6), rmtree, report.
12. Release lock. Print report (§14); exit 0 (no skips) / 1 (committed
    with skips) / 3 (fatal — nothing committed; staging remains and will
    be swept by the next run).
```

Step order is load-bearing: files (7-8) → index (9) → publish (10) →
prune (11). Prune runs only after a successful commit, so a run that
commits nothing never deletes anything (invariant I2, §11.4).

---

## 7. Concurrency and atomicity

### 7.1 Writers: one at a time, kernel-enforced

All mutations (staging, publish, prune) happen under an exclusive
`fcntl.flock(fd, LOCK_EX | LOCK_NB)` on `backup_root/backupctl.lock`.
Why flock and not a lock *file existence* check or a pid file: the kernel
releases the lock when the holder dies, **including SIGKILL** — verified:
a second process gets `EWOULDBLOCK` (errno 35) while the holder lives, and
acquires immediately after the holder is SIGKILLed (§17 A3). There is no
stale-lock state to detect, no pid-liveness guessing, no manual cleanup: a
leftover lock *file* is just an unlocked file. The pid is written into the
file after acquisition for diagnostics only; flock is the sole authority.

The brief's "two runs may execute at the same time" resolves as: two run
*attempts* may overlap arbitrarily (scheduler tick + human, two humans,
tick pileup); their *executions* serialize. The loser's behavior is one
flag: `--lock-timeout S` (default 0). Scheduler keeps the default — exit
immediately with code 2 ("run active, pid N"), skip this tick, next tick
proceeds. A human passes `--lock-timeout 300` and waits (1 s poll). No
other behavior differs (§9.3). Neither run can corrupt the other: the
second sees a backup root in which every `snap-*` is complete (only whole
renames publish) and `staging/` is untouched by anyone but the lock
holder.

### 7.2 Readers: lock-free by construction

Readers (restore, human, `backupctl list`) take **no lock** and never
consult run state — the brief's "a reader never asks whether the run that
produced a snapshot is finished" is satisfied structurally, by what is
*visible*:

- **R1 Discovery.** Committed snapshots = `snaputil.list_snapshots(root)`
  (snaputil.py:8-20); newest = last element. `staging/`, `trash-*`,
  `backupctl.lock` are invisible to it (line 18 filter; verified §17 A10).
- **R2 Completeness.** A `snap-*` name exists **iff** its rename (step 10)
  completed. Directory rename is atomic within a filesystem (POSIX
  `rename(2)`): there is no interval in which the name exists and the tree
  or index inside is incomplete. Everything inside was fully written and
  fsynced *before* the rename (§8.4 for the power-loss ordering).
- **R3 Index fidelity.** `snapshot.json["files"]` contains exactly the
  files successfully placed (steps 7-9): keys ⊆ tree and tree payload ⊆
  keys ∪ {`snapshot.json`}. A reader trusting the index never hits a
  missing file — this is the invariant O2/O5 exist to protect.
- **R4 Immutability.** Nothing ever writes inside a committed snapshot.
  Hardlinked payloads are never modified in place; restore copies out.
- **R5 Deletion races.** The only actor touching a committed snapshot is
  the pruner, via rename-first (O6): the name vanishes atomically, then
  bytes are destroyed out of view. A reader that resolved paths *before*
  the rename either holds open fds (POSIX unlink semantics: data readable
  until close) or gets `ENOENT` mid-walk. Reader contract: on `ENOENT`,
  re-run discovery and pick the newest snapshot (or fail with "snapshot
  pruned mid-read"). This can only affect snapshots older than the newest
  K (§11), which is where restores should not be targeting anyway.
- **R6 Path safety.** Index keys are resolved via
  `resolve_in_snapshot` (O7) — a corrupt or tampered index cannot point a
  reader outside the snapshot.

Restore itself is separate tooling (per the brief); R1-R6 are the complete
contract it may rely on, and nothing else about a run's in-flight state is
observable.

### 7.3 Name collisions at commit

Two runs committing in the same wall-clock second would compute the same
`snap-…-HHMMSS` name (single-writer serialization means they commit
sequentially, but the clock can tie). Retry loop: attempt
`os.rename(staging/run, snap-…-NN)` with `NN = 00, 01, …`; a committed
snapshot is never empty (it contains `snapshot.json`), so a collision
always fails `ENOTEMPTY`/`EEXIST` — verified errno 66 for
directory-onto-non-empty-directory, and verified that
directory-onto-*empty*-directory would silently replace (§17 A2), which is
why "index written before rename" is a safety requirement, not just an
ordering nicety. Cap 100 attempts (>99 commits in one second is
impossible: a run takes ≥ seconds); beyond the cap the run fails exit 3
and its staging is swept by the next run.

---

## 8. Crash and corruption recovery

Threat model per the brief: Ctrl-C, laptop sleep, SIGKILL — the process
dies at an arbitrary point. Design decision: **no cleanup-on-signal
traps**. A trap cannot run under SIGKILL anyway, so recovery must not
depend on the dying process doing anything; instead, one uniform mechanism
covers every death mode: *leftovers are garbage, and the next run sweeps
them*. The invariant that makes this sound: **anything not under a
canonical `snap-*` name is invisible to readers (R1) and unconditionally
deletable by the next lock holder** — if we hold the writer lock, no live
writer owns that staging/trash tree.

### 8.1 Crash windows

| Death point (step, §6) | On disk afterwards | Reader impact | Next-run action |
|---|---|---|---|
| 0-5 (scan/diff) | nothing, or an empty `staging/` | none (R1) | sweep no-op |
| 6-8 (copy/link mid-flight) | partial tree under `staging/run-*` | none (R1) | sweep: `rmtree(staging/*)`; measured 0.17 s per 2,000-file leftover (~85 µs/file) |
| 9 (index half-written) | `snapshot.json.tmp` (or half of it) inside staging | none (R1) | swept with the staging tree; a half-written index exists *only* here — never at a visible path |
| between 9 and 10 (complete but unpublished) | complete staging tree | none (R1) | swept; the work is redone. Explicit decision: no "adopt finished staging" optimization — the invariant "staging is always garbage" is worth one run's rework |
| during 10 (rename) | rename is atomic: either published-complete or still staging | none, ever | as either row above |
| after 10, before root fsync | published snapshot | complete (R2) | none. Process death cannot undo a completed rename; power-loss ordering handled by §8.4 |
| during 11 (prune) | `trash-*` leftover(s), possibly partially destroyed | none (R1); retention decision already effective (name gone from listing) | sweep: `rmtree(trash-*)`; newest snapshot untouched (I1) |

Every row ends with the same guarantees: nothing a reader could mistake
for a complete snapshot ever exists mid-flight or post-mortem, and the
next run proceeds **without manual cleanup** — its step 2 is the entire
recovery procedure for dead runs.

Laptop sleep deserves one note: sleep suspends the process; on wake the
run continues. Files that changed during the sleep are handled by the
existing machinery: their recorded scan-time state differs from their
post-wake source state, so the *next* run recopies them (§10.5); files
that vanished during sleep take the skip path (§9). Nothing special-cases
suspend.

### 8.2 Sweep (step 2)

Under the lock: `shutil.rmtree` every entry of `staging/` and every
`trash-*` directory in the backup root. Cost bound: `85 µs × files in
leftovers` (measured, §12). Report line per leftover: name, file count,
bytes — a dead run is thus *reported by the run that cleans it*, which is
the only report it will ever get.

### 8.3 Corrupt or half-written index found by a run (step 3)

A committed snapshot's index should always parse (written whole, fsynced,
published atomically). It can still be invalid: power-loss reordering
beyond the fsync order's protection (§8.4), bitrot, manual tampering, or a
snapshot produced by older/other tooling. Base selection therefore
*validates*, and the brief's three recovery questions are answered
explicitly:

- **Validation.** `json.load` + schema check (`format` matches, `files` is
  a dict whose values have `size`/`mtime`). Cost: ~30 ms per 1.35 MB index
  (measured).
- **What is discarded.** The index *text* only. Payload bytes in the
  snapshot tree are never touched by recovery.
- **What is re-derived from the tree.** The `files` map, via
  `synccli.build_manifest(snapshot_dir)` (synccli.py:28-33) through the
  O8-tolerant wrapper, excluding the root-level key `snapshot.json`,
  keeping `S_ISREG` files only, and dropping unstatable entries (counted).
  The product has exactly the `{relpath: {size, mtime}}` shape
  `changed_files` consumes (synccli.py:36-42), so a re-derived base drives
  normal incremental operation — unchanged files are hardlinked from the
  re-derived snapshot's tree, changed ones copied.
- **What the run reports.** One of:
  `base snap-X: index invalid (<error>); re-derived N entries from tree (M unstatable excluded)`;
  or, when the tree is also unusable (missing/unreadable):
  `base snap-X unusable; using snap-Y` / `no usable base; full backup`.
  `backupctl list` applies the same validation (parse-only) per snapshot
  and flags invalid ones, so a human sees the damage outside run time.

Retention interaction: a snapshot with an invalid-but-re-derivable index
counts as **usable** for invariant I3 (§11.4); one whose tree is also
unreadable counts as **not usable**. It is never silently chosen as base.

### 8.4 Durability ordering (power loss)

Process death needs no fsync at all (a completed syscall is not undone by
a process dying; rename atomicity is syscall-level). fsync exists for the
stronger case — battery death during/after sleep. Default `--fsync` (on)
enforces: each copied file's data fd → `snapshot.json.tmp` → rename within
staging → staging dir fd → publish rename → backup root dir fd. The order
is write-ahead: rename visible ⇒ everything sequenced before it is
durable. The worst power-loss outcome is a *lost* rename (snapshot absent —
safe direction, work redone next run), never a present-but-incomplete
snapshot. Measured cost of per-file fsync: 21-43 µs/file (§12) — under
10 % of the ~400 µs file-creation floor, hence default-on; `--no-fsync`
is documented for filesystems where fsync is far more expensive.

---

## 9. Vanished and unreadable source files

### 9.1 Windows and behavior

A source file can fail at three points; all three take the same
skip-and-report path (O2/O8), and in all three the file is **omitted from
the snapshot and from the index**:

| Window | Mechanism | Recorded skip |
|---|---|---|
| (a) gone/unstatable *during the scan* | O8 wrapper: `os.stat` raises (`FileNotFoundError`, `PermissionError`, …) or `S_ISREG` fails | `stage="stat"`, errno, strerror |
| (b) gone between listing and copy/link | copy raises `FileNotFoundError`; (link targets the base tree, not the source, so "gone" only bites the copy path — including the fallback of §10.4) | `stage="copy"`, errno 2 |
| (c) unreadable when the copy reaches it | copy raises (`PermissionError`, I/O error) | `stage="copy"`, errno |

**What the snapshot then contains:** every file that could be placed, and
nothing else; the index lists exactly that set (R3) plus the structured
`skipped` list. The snapshot is *complete relative to what was readable*,
self-consistent, and restorable as-is — a partial snapshot by source
comparison, a whole snapshot by its own index. A vanished file's older
version remains available in earlier snapshots (retention permitting);
the report says so implicitly by naming the file and stage.

**What the run reports:** one line per skip —
`skipped results/run43/tmp.bin (copy: ENOENT No such file or directory)` —
plus counts in the summary, plus the machine-readable copy in
`snapshot.json["skipped"]`, plus **exit code 1** (committed-with-skips),
so a scheduler notices partial runs without parsing text.

### 9.2 Why the index can't drift from the tree

`synccli.sync` today writes `src_manifest` — the *intent* — to the
destination manifest regardless of copy outcomes (synccli.py:85-86), after
`copy_file` silently ate the failure (68-69): verified manifest-promises-
missing-file (§17 A5). `backupctl` inverts the source of truth: the index
is assembled from *results* (step 9 records only successes). Intent never
reaches disk as fact.

### 9.3 Scheduler ≡ human

One implementation of `run`. No flag changes scanning, copying, skipping,
indexing, publishing, or pruning semantics; the only run-shape flags are
`--lock-timeout` (wait vs. skip on contention, §7.1) and `--quiet`
(report volume). Snapshot content, index content, skip handling, and exit
codes are bit-for-bit identical regardless of who started the run — as the
brief requires for the vanished-file case and everything else.

---

## 10. Change detection and dedup

### 10.1 Granularity

Per **file**, keyed by `(size, mtime)` — exactly
`synccli.file_state`'s dict (synccli.py:22-25): `st_size` + `st_mtime`
(float seconds) from `os.stat` (line 24, which follows symlinks).
`synccli.changed_files` (synccli.py:36-42) marks a file for copy iff its
key is new or its state dict differs (line 40 — any inequality, so
mtime *regressions*, e.g. after a restore of older data, also trigger a
copy). Unchanged files are not copied: they are **hardlinked** from the
base snapshot's tree (`os.link`, zero data bytes; dedup verified:
`st_nlink == 2` on the base file after a link run, and true-unique disk
after three generations 1079 MB vs 3 × 1025 MB apparent, §17 B).

### 10.2 What this granularity can miss

Stated exhaustively, per the brief:

1. **Same-size edits that preserve mtime** — editors/restore tools that
   reset timestamps (`touch -r`, `rsync -t` with equal values), or manual
   tampering. Both state fields unchanged ⇒ file considered unchanged ⇒
   stale bytes linked forward. This is the fundamental blind spot of
   (size, mtime) keying; the mitigation is opt-in, not default:
   `--full-every N-th-run` forces a periodic full copy that launders the
   base (documented trade: content hashing would close it at a cost of
   reading all `B` bytes every run — ~5.3 s/GB at the measured 190 MB/s
   stream rate, plus defeating the hardlink's zero-byte property).
2. **Same-size edits within one mtime clock tick of the filesystem.**
   `st_mtime` resolution is filesystem-defined (APFS: nanoseconds — window
   negligible; HFS+: 1 s; FAT: 2 s). Two writes inside one tick with
   unchanged size are invisible. Bound: window ≤ filesystem mtime
   granularity.
3. **Metadata-only changes** — mode, owner, xattrs, ACLs. `file_state`
   records neither (synccli.py:25), so `chmod`/`chown` alone never
   triggers a copy, and snapshots do not preserve them (payload bytes
   only; §16 L3).
4. **Nothing else.** New paths, grown/shrunk files, any mtime move in
   either direction, deletions (absence from the new scan), and renames
   (delete + add at both paths; the add either copies or links correct
   bytes) are all detected by construction.

### 10.3 Deletions

`changed_files` iterates only the *new* manifest (synccli.py:39) and
therefore never reports deletions — verified `[]` on a delete-only diff
(§17 A9). `backupctl` needs no deletion machinery for correctness: the new
snapshot's content is defined by the new scan (copy set ∪ link set), so a
file deleted at the source simply has no entry — absent from tree and
index alike. `deleted = keys(base_files) − keys(new_scan)` is computed for
the report only. (This is also where `synccli.sync`'s destination differs
— it never removes stale destination files; irrelevant here because each
snapshot is built fresh, never mutated.)

### 10.4 Corrupt base encountered *as a reader* (hardening)

The brief's "index promises files the snapshot does not contain" can also
bite the *writer* linking from a base: `os.link(resolve_in_snapshot(…))`
raises `ENOENT` when the base index over-promises (damaged base beyond
§8.3's index-level validation — the index parsed, but the tree lost
files). Per-file fallback: copy from source instead; if the source is also
gone, skip+report (§9). The new snapshot's R3 invariant holds regardless
of the base's condition, and the damaged base is re-flagged by the run
report. No global "verify base tree" pass: a full stat sweep of the base
would cost `F × 19 µs` (measured stat rate) every run to protect against
damage that the link attempt itself detects for free, per file, exactly
when it matters.

### 10.5 Files changing during a run

- Changed **after** the scan, before copy/link: the snapshot carries the
  scan-era version (copy) or base-era bytes (link — only possible when
  scan state == base state, so linked bytes always equal the recorded
  state exactly). The source's final state differs from the recorded state
  (a completed write advances mtime), so the next run recopies. Stale but
  self-consistent for one generation; converges.
- Changed **during** a copy (torn read): recorded state is the pre-copy
  scan state; the writer's completion moves the source state ⇒ next run
  recopies. The only unfixable case is a writer that restores exact
  (size, mtime) — blind spot 10.2.1, already documented.
- Broken symlink / vanished at scan: §9.1(a). Directory symlinks are not
  descended into (`os.walk` default `followlinks=False`, synccli.py:13);
  file symlinks are dereferenced (`os.stat` follows, synccli.py:24; the
  copy stores target bytes). Both documented (§16).

---

## 11. Retention and pruning

### 11.1 Policy

Count-based, default `K = 10`, config `"keep"` (validated `K ≥ 1`):
doomed = oldest `len(names) − K` of `list_snapshots(root)` — verbatim the
selection of `snaputil.prune_snapshots` (snaputil.py:30-33; guard 31-32,
slice 33), verified to delete only the oldest and never the newest
(§17 A11). Prune executes at step 11 of every successful run, and via
`backupctl prune` (which takes the same writer lock).

### 11.2 Optional age axis

Config `"keep_days": D` adds: age-doomed = snapshots with
`is_stale(snap_dir, now − D·86400)` (snaputil.py:66-73). Boundary
semantics documented as **inclusive** — the implementation's `<=`
(line 73) returns `True` at exactly `ref_epoch` even though the docstring
(lines 71-72) claims otherwise; verified (§17 A13). At day granularity a
one-second-inclusive boundary is immaterial; the design follows the
implementation and says so, rather than repeating a docstring the code
contradicts. Committed snapshot dirs are never touched after publish, so
their `st_mtime` (set when staging was populated, ≈ run time) is stable.
The doomed set is the **union** of both axes, then filtered by I3.

### 11.3 Deletion mechanics (O6)

For each doomed snapshot: `os.rename(root/snap-X, root/trash-snap-X)` —
atomic removal from reader visibility (R1/R5; `list_snapshots` ignores
non-`snap-*`, snaputil.py:18, verified) — then `shutil.rmtree(trash path)`,
then report. Hardlink safety: deleting an older snapshot only decrements
`st_nlink` on inodes the newer snapshots still link; their data is
untouched (POSIX link semantics; exercised in the benchmark: prune of the
full snapshot left the two link-derived snapshots intact and listable,
§17 B/G). Cost: `85 µs × files in doomed snapshots` (measured: 1.6 s for a
1 GB / 20k-file snapshot). A kill between rename and rmtree leaves a
`trash-*` leftover — invisible, swept at next start (§8.1/8.2).

Accounting note: `snaputil.snapshot_disk_usage` reports *apparent* size —
verified counting the same hardlinked inode in every snapshot (1025 MB
each for three snapshots sharing one inode set, §17 A12). `backupctl list`
therefore reports both: apparent per snapshot (reusing snaputil.py:39-51
as-is) and **true/marginal bytes** = `Σ st_size over files with
st_nlink == 1` per snapshot (what deleting it would actually free;
measured scan cost 1.3 s per 20k-file snapshot). Retention decisions use
counts (K), not bytes; if a byte budget is ever added, it must use the
true accounting, or it will "free" 1 GB per pruned snapshot on paper while
freeing ~50 MB in fact.

### 11.4 Invariants

- **I1 — newest never doomed.** Selection deletes only the oldest
  `len − K` (snaputil.py:33; verified). With `K ≥ 1` the newest snapshot
  is outside the doomed slice by arithmetic.
- **I2 — prune only after commit.** Step 11 follows step 10; a run that
  commits nothing prunes nothing. `backupctl prune` under the lock obeys
  I1/I3 identically.
- **I3 — never left without a *usable* snapshot.** Usable = index valid or
  re-derivable (§8.3). After applying both axes, drop from the doomed set
  any snapshot whose deletion would leave zero usable snapshots — the
  corner case being `keep=1` with a corrupt newest snapshot: naive
  selection would doom the one usable older snapshot; I3 keeps it and the
  report says why. (I1 alone doesn't cover this: it protects the newest,
  not the newest *usable*.)
- **I4 — deletion safe against readers.** Rename-first (O6) + reader
  contract R5: canonical names never disintegrate in place; open fds
  survive until close; `ENOENT` mid-walk means "pruned, re-discover".

---

## 12. Performance budget — initial full backup

### 12.1 Measured constants (reference environment §2; recipes Appendix B)

Fixture: 20,000 files × 50 KB = 1.02 GB in 200 directories (the brief's
"~1 GB, tens of thousands of files").

| Constant | Measured | Budget value (conservative) |
|---|---|---|
| Scan+stat per file (`build_manifest`, synccli.py:28-33) | 24-39 µs/file (0.48 s warm / 0.78 s cold per 20k) | 40 µs |
| Bare `os.stat` | 19 µs/file | — |
| Whole-read copy (`synccli.copy_file`, subset) | 240 µs/file (215 MB/s) | — |
| Copy 50 KB, chunked, no fsync | 270-378 µs/file across runs (±40 % run variance; 138-188 MB/s implied at 50 KB) | — |
| Per-file `fsync` overhead | 21-43 µs/file | 45 µs |
| Copy 50 KB, chunked + fsync (full-backup per-file cost) | 369-478 µs/file (three passes) | 480 µs |
| Pure `os.link` (zero bytes moved) | 371-418 µs/file | 420 µs |
| Per-file `makedirs(exist_ok)` avoided by O3 | 25-55 µs/file (pre-create 200 dirs: 27 ms total) | avoided |
| Effective streaming rate (no fsync, end-to-end incl. per-file cost) | 188-215 MB/s on 50 KB files | 190 MB/s (conservative; per-file cost amortizes on larger files) |
| Whole-read `copy_file` memory (O1 evidence) | 52 MB peak on a 50 MB file vs 2.1 MB constant chunked | — |
| Index: JSON bytes | 68 B/entry (1.35 MB per 20k files) | 76 B/entry (incl. ~8-char source prefix) |
| Index: write+fsync+rename+root-fsync (commit) | 0.04 s | 0.1 s |
| Index: `json.load` | 0.03 s per 1.35 MB (~22 µs/KB); 478 B/entry RAM | 30 ms / 20k |
| Manifest RAM | 389 B/entry (tracemalloc) | 400 B/entry |
| Diff (`changed_files`, 20k × 20k) | 2 ms | 0.1 µs/file |
| `rmtree` (prune/sweep) | 80-85 µs/file (1.6 s per 1 GB/20k prune; 0.17 s per 2k-file sweep) | 85 µs |
| Incremental run, 0 changes, end-to-end | 8.4 s (scan 0.5 + diff 0.002 + 20k links 7.9 + commit 0.04) | — |
| Incremental run, 1,000/20,000 changed (51 MB) | 8.4 s; detected exactly 1,000 | — |
| Disk after 3 generations (1 full + 1 unchanged + 1 5 %-changed) | apparent 3 × 1025 MB; **true unique 1079 MB** | — |

The dominant per-file cost on this machine is *file creation itself* —
even a zero-byte `os.link` costs ~370-420 µs — not byte movement; that is
why the budget is per-file-dominated at 50 KB average size and why
pre-creation (O3) and result-batched syscalls matter more than buffer
sizes.

### 12.2 Derivation and committed budget

Full backup of `F` files / `B` bytes:

```
T_full(F, B) = F · 0.55 ms            (scan 40 µs + copy-with-fsync 480 µs + margin)
             + B / (190 MB/s)         (streaming term; dominates only for
                                       avg file size ≳ 100 KB)
```

For the brief's tree (F = 20,000, B = 1.02 GB): composed
**11.0 s + 5.4 s = 16.4 s** (deliberately conservative — the byte term
partly double-counts what the measured 480 µs/file already includes at
50 KB average). Direct end-to-end measurement of the same shape:
**9.6-10.5 s** (7.4-9.6 s copy phase + 0.8 s scan + 0.03 s dir
pre-create + 0.04 s commit).

> **Committed budget: the initial full backup of a ~1 GB / ~20k-file tree
> completes in ≤ 60 s on the reference hardware** — 3.7× the composed
> bound, 5.7× the measured. The budget is a ceiling for CI assertions, not
> an expectation; on other hardware or tree shapes recompute with the
> formula above (both constants are one benchmark apart, Appendix B).

Steady-state incremental runs (context for the budget — the expensive run
happens once):

```
T_inc(F, n_ch, C) = F · 0.46 ms       (scan 40 µs + link 420 µs)
                  + n_ch · 0.06 ms    (copy-vs-link delta per changed file)
                  + C / (190 MB/s)
```

Measured: 8.4 s at (20k, 0, 0) and 8.4 s at (20k, 1000, 51 MB); composed
9.2 s / 9.5 s. **Budget: ≤ 60 s for F ≤ 100k with ordinary churn.** A run
whose source is unchanged still costs one link pass — that is the price of
each snapshot being a complete standalone tree (R2/R3); dedup keeps the
*disk* marginal (§13), not the metadata pass.

---

## 13. Scaling bounds — what grows with what

Explicit bounds per the brief; every constant from §12. `F = ΣFᵢ`,
`B = ΣBᵢ` over the `N` sources.

| Quantity | Bound (formula / number) | Grows with | Flat in |
|---|---|---|---|
| Full-run wall time | `F·0.55 ms + B/(190 MB/s)`; measured 10.5 s @ (20k, 1 GB) | `F`, `B` | `N` (only via `F`,`B`), `K`, history depth |
| Incremental-run wall time | `F·0.46 ms + nₖ·0.06 ms + Cₖ/(190 MB/s)`; measured 8.4 s | `F`, churn | `N`, `K`, history depth (base = latest usable only — no per-ancestor work ever) |
| Peak RSS | `F·(478 + 400) B ≈ F·0.9 KB` + 1 MiB copy buffer (O1) + `O(N)` config; 20k → 18 MB, 100k → 90 MB, 500k → 450 MB | `F` | `K`, `N`, largest file (O1: buffer is constant 1 MiB) |
| — RAM mitigation at large `F` | stream per source: peak = `F·478 B` (base index, loaded once) + `maxᵢ Fᵢ·400 B` (one source manifest at a time, diffed and freed) | `F`, `max Fᵢ` | `N` |
| Index disk per snapshot | `F·76 B`; 20k → 1.5 MB | `F` | `K` |
| True disk, `K` retained snapshots | `B + Σ_{retained k} Cₖ + K·(F·76 B + ~0.5 MB structure/200 dirs)`; measured: 3 generations of a 1 GB tree = **1079 MB true** (≈ B + 51 MB churn + 4 MB structure/indexes) vs 3075 MB apparent | `B`, cumulative churn, `K` (index+structure term only) | — |
| Apparent disk (what `snapshot_disk_usage` reports, snaputil.py:39-51) | `≤ K·(B + F·76 B)`; verified double-counts hardlinks (§17 A12) | `K`, `B` | — |
| Prune wall time | `85 µs × F_doomed` (budget); measured 1.6 s per 1 GB/20k snapshot (80 µs/file) | files in doomed snapshots | everything else |
| Sweep wall time | `85 µs × F_leftover`; 0.17 s per 2000 files | dead-run leftovers (≤ 1 run's tree per dead run) | `K`, `N` |
| Base-index load + validate + diff | `~22 µs/KB index` (30 ms per 20k) + `F·0.1 µs` (2 ms per 20k) | `F` | `K` |
| Lock files | **1** | — | everything |
| Live staging directories | **≤ 1** (single writer, §7.1) + leftovers until next start | — | `N`, `K` |
| Retained snapshots | `≤ K` (+ transient `trash-*` ≤ doomed count during prune) | `K` (config constant) | run count, history |
| Snapshot name sequence `NN` | 2 digits, ≥ 100 commits/second impossible (a run takes ≥ seconds) | — | — |
| Config size / key-prefix cost | `O(N)` entries; prefix adds ~8 B/index entry | `N` (bytes), weakly | time (no per-`N` fixed cost beyond one walk setup per source) |

**Three → a few dozen directories:** every runtime term depends on the
sources only through `F` and `B` (and churn `Cₖ`, `nₖ`); `N` itself adds
one `os.walk` setup per source (sub-ms) and `O(N)` config bytes. Doubling
`N` at constant total tree size changes per-run time by < 1 %. What
actually grows over time is cumulative churn under `K` retention — bounded
by the true-disk formula above, with `K` the single knob.

**Flat, with the bound that makes it flat:** per-run memory and time never
touch history depth (base = newest usable snapshot, one index load);
reader-visible namespace never exceeds `K` snapshots + 0 staging (R1);
writer concurrency never exceeds 1 (flock); temp space never exceeds one
run's tree (single writer + sweep-at-start).

---

## 14. CLI, config, report, exit codes

```
backupctl run    [--config backupctl.json] [--lock-timeout S] [--dry-run]
                 [--no-fsync] [--full] [--quiet]
backupctl list   [--config …]        # snapshots: name, committed_at, apparent+true size,
                 #                   index-valid flag, copied/linked/skipped counts
backupctl prune  [--keep K] [--older-than DAYS] [--config …]   # takes the writer lock
backupctl status [--config …]        # lock state (probe via LOCK_NB), staging/trash
                 #                   leftovers, base usability, K, next doomed set
```

Config (`backupctl.json`):

```json
{
  "backup_root": "/path/to/backups",
  "sources": {"results": "evals/results", "configs": "evals/configs", "logs": "evals/logs"},
  "keep": 10,
  "keep_days": null,
  "include_dotdirs": false
}
```

Run report (stdout; line-per-event style of synccli.py:97-98 and
snaputil.py:83-87):

```
backupctl: swept dead-run leftover staging/run-8812-1763290000 (1834 files, 91 MB)
backupctl: base snap-20261116-000000-00 (index valid) sources=3 files=20000
backupctl: plan copied=1000 linked=19000 deleted=5
backupctl: skipped results/run43/tmp.bin (copy: ENOENT No such file or directory)
backupctl: committed snap-20261116-120000-00 in 9.3s (51 MB copied, 0 B linked)
backupctl: pruned snap-20261101-000000-00 (freed ~52 MB true)
```

Exit codes (`run`; identical semantics for scheduler and human, §9.3):

| Code | Meaning |
|---|---|
| 0 | snapshot committed, no skips |
| 1 | snapshot committed **with skips** — partial vs source; details in report + `snapshot.json["skipped"]` |
| 2 | not run: lock held (pid reported); nothing written |
| 3 | fatal, nothing committed; nothing reader-visible left behind; staging (if any) will be swept by the next run |

`list`/`status`: 0 ok, 3 fatal. `prune`: 0 (deletions reported), 2 (lock),
3 (fatal).

---

## 15. Test plan (`test_backupctl.py`, style of test_synccli.py:8-51)

unittest + `tempfile.mkdtemp` fixtures (as test_synccli.py:9-15), plus
subprocess-based liveness tests:

1. `test_full_run_commits_complete` — run on a 3-source fixture; exactly
   one `snap-*`; index parses; `files` keys == tree payload (R3 both
   directions); exit 0.
2. `test_second_run_links_unchanged` — modify one file, re-run;
   `counts.copied == 1`, `counts.linked == F−1`; an unchanged file's inode
   has `st_nlink == 2` shared with base (dedup, as verified in §17 B/E).
3. `test_deleted_source_file_absent` — delete a source file, re-run;
   absent from new tree and index; `counts.deleted == 1`; still present in
   base snapshot.
4. `test_vanished_and_unreadable_reported` — chmod-000 file + file removed
   after scan (injection hook on the copier, mirroring the verified
   §17 A5/A6 failures); exit 1; both in report and `snapshot.json["skipped"]`
   with stage/errno; neither in `files`; snapshot otherwise complete.
5. `test_sigkill_midrun_leaves_nothing_visible` — launch `run` in a
   subprocess on a large-enough fixture, SIGKILL during copy; assert no new
   `snap-*` exists, staging leftover exists; second run sweeps it (report
   line), commits, exit 0/1. (flock release after SIGKILL already verified,
   §17 A3.)
6. `test_corrupt_index_rederived` — overwrite newest `snapshot.json` with
   `{"half-`; run; report contains `index invalid` + `re-derived N entries`;
   new snapshot committed; unchanged files linked from the corrupt-index
   snapshot's tree (proves re-derivation drove change detection).
7. `test_corrupt_index_and_tree_falls_back` — corrupt index *and* delete a
   payload dir; run falls back to next-newest base or full; report says which.
8. `test_lock_contention_exit2` — hold flock from a subprocess; `run
   --lock-timeout 0` → exit 2, no staging created; `--lock-timeout 2`
   acquires after holder exits.
9. `test_prune_never_deletes_newest_or_last_usable` — 3 healthy snapshots,
   keep=1 → newest survives (I1); [usable-old, corrupt-index-newest],
   keep=1 → old survives (I3) and report explains.
10. `test_prune_rename_first` — monkeypatch `shutil.rmtree` to record the
    path it receives: it is `trash-snap-*`, and `list_snapshots` no longer
    contains the name at that moment (O6/R5); kill between rename and
    rmtree → next run sweeps `trash-*`.
11. `test_resolve_in_snapshot_rejects_escapes` — the exact §17 A4 payloads:
    `/etc/passwd`, `../../etc/passwd`, `a/../../etc` → rejected; normal
    keys resolve identically to `snaputil.safe_snapshot_path`.
12. `test_commit_name_collision_bumps_seq` — pre-create
    `snap-<commit-second>-00` non-empty; commit lands on `-01` (ENOTEMPTY
    retry, §7.3).
13. `test_dry_run_writes_nothing` — plan printed; no staging, no lock file
    content change, no new names (pattern of synccli.py:81-82).
14. `test_index_shape_feeds_synccli` — assert
    `changed_files(index["files"], build_manifest(src))` (both unmodified
    synccli functions) returns exactly the modified set against a real
    committed index — the grounding claim (‡5.1) as an executable test.

Performance guard (opt-in, off by default in CI): full run over a
generated 5k-file/250 MB tree asserting wall time ≤ budget-formula value
scaled from §12 (¼ of the 60 s ceiling).

---

## 16. Limitations and accepted risks

- **L1 (size, mtime) blind spots** — §10.2, exhaustively; `--full-every`
  as the laundering mitigation; content hashing explicitly rejected as
  default (reads all `B` bytes per run, ~5.3 s/GB measured stream rate).
- **L2 Torn-copy window** — a file written *during* its copy lands
  byte-mixed in this snapshot and is recopied next run (recorded state ≠
  final source state); unfixable only under mtime-restoring writers
  (= L1). Bounded: one generation.
- **L3 Metadata not preserved** — mode/owner/xattrs/symlink-ness are not
  snapshotted (`file_state` records size+mtime only, synccli.py:25);
  payloads are regular-file bytes; file symlinks are dereferenced,
  directory symlinks not descended (os.walk default, synccli.py:13).
- **L4 Empty directories not preserved** — `scan_files` yields file paths
  only (synccli.py:10-19); a source dir whose files all vanish leaves no
  trace in the new snapshot. Accepted (evals result dirs are valued for
  their files); would require an O9-style walk extension if ever needed.
- **L5 Dot-directories skipped by default** (synccli.py:14, verified
  §17 A7) — `include_dotdirs` (O9) opt-in; report documents the mode.
- **L6 Apparent-size accounting** — `snapshot_disk_usage` over-reports
  with hardlinks (verified §17 A12); any byte-based policy must use the
  true-accounting walk (§11.3), not the reused helper.
- **L7 Raw `snaputil` CLI against a backupctl root is unsupported** — its
  `--prune` (snaputil.py:79-84) bypasses the lock and rename-first (O6);
  documented in `backupctl status` output and the README.
- **L8 Single-filesystem backup root** — hardlinks and atomic rename
  require same-fs; staging inside the root makes this structural, and
  config load asserts it.
- **L9 Restore mid-prune sees ENOENT** — reader contract R5 (re-discover);
  only snapshots beyond the newest `K` can vanish, and only atomically
  (never half-deleted under a canonical name, O6).

---

## 17. Appendix A — verification log

Executed against this directory's code (Python 3.10.11, macOS 15.8.1,
APFS). `A*` = behavioral checks; `B` = benchmark (§12/Appendix B).

| # | Claim (design section) | Observed |
|---|---|---|
| A1 | Baseline green (§2) | `python3 -m unittest`: 6/6 OK |
| A2 | Rename dir→non-empty dir fails; →empty dir replaces (§7.3, O4) | `OSError errno=66 (ENOTEMPTY)`; empty-target rename succeeded (replaced) |
| A3 | flock: blocks while held; auto-released by SIGKILL (§7.1) | second acquirer `errno=35` while holder alive; acquired immediately after holder SIGKILLed |
| A4 | `safe_snapshot_path` escapes: absolute and net-leading `..` (O7) | `("/…","snap-x","/etc/passwd") → "/etc/passwd"`; `"../../etc/passwd"` and `"a/../../etc"` resolve outside the snapshot; docstring (snaputil.py:58-61) contradicted |
| A5 | `synccli.sync` manifest promises files the dst lacks (O2) | unreadable (chmod 000) source: returned in `copied` list, present in dst manifest, **absent from dst tree** |
| A6 | `build_manifest` crashes on unstatable file (O8) | broken symlink → uncaught `FileNotFoundError` |
| A7 | `scan_files` skips dot-dirs, keeps dot-files (L5, O9) | result `['.dotfile', 'visible/v.txt']`; `.hidden/inner.txt` absent |
| A8 | Corrupt manifest kills next sync (O5) | truncated `.sync_manifest.json` → uncaught `JSONDecodeError` (load at synccli.py:77-79) |
| A9 | `changed_files` never reports deletions (§10.3) | delete-only diff → `[]` |
| A10 | `list_snapshots` visibility rules (R1, R5, O6) | returns only the three `snap-*` dirs, chronological; `staging/`, `trash-snap-*`, `lock`, `notes.txt` all ignored |
| A11 | `prune_snapshots` deletes oldest only (I1) | keep=2 over 3 → deleted `['snap-20261101-000000-00']`, newest two remain |
| A12 | `snapshot_disk_usage` double-counts hardlinks (L6) | one shared 1000-byte inode → 1000 reported for *each* snapshot |
| A13 | `is_stale` boundary inclusive, contradicting docstring (§11.2) | `is_stale(dir, dir's own mtime) → True` (`<=` at snaputil.py:73 vs docstring 71-72) |

## 18. Appendix B — measurement recipes

Fixture: 20,000 files × 50 KB (repeating 1 KiB random block × 50) in 200
directories (`dir_000…dir_199`, 100 files each) under a temp root; backup
root beside it. All timings `time.monotonic`, memory `tracemalloc` peaks.
Procedure per constant (→ §12 table row):

1. **Scan**: `synccli.build_manifest(src)` over the fixture, cold and warm.
2. **Copy**: per file — `os.makedirs(dirname)` once per unique dir (O3),
   then `shutil.copyfileobj(src, dst, 1 MiB)` [+ `flush`+`os.fsync` in the
   fsync variant]; also whole-read via `synccli.copy_file` on a 2,000-file
   subset and on one 50 MB file (memory).
3. **Link**: `os.link(snaputil.safe_snapshot_path(root, base, rel),
   staging/rel)` for all 20,000 rels, dirs pre-created vs per-file
   `makedirs`.
4. **Index**: `json.dump` of the 20k-entry manifest → size; tmp+fsync+
   rename + staging-dir fsync + publish rename + root fsync → commit time;
   `json.load` back → time + peak.
5. **End-to-end**: full backup (scan → pre-create → copy+fsync → index →
   commit); incremental unchanged (scan → `changed_files` → link tree →
   commit); incremental after rewriting 1,000 files (same sizes, new
   content).
6. **Disk**: `snaputil.snapshot_disk_usage` per snapshot (apparent) vs one
   walk summing `st_size` where `st_ino` first-seen (true unique).
7. **Prune/sweep**: `snaputil.prune_snapshots(root, 2)` over three
   generations (rmtree of a 1 GB/20k snapshot); `shutil.rmtree` of a
   2,000-file staging leftover.

Key raw outputs (full logs summarized): scan 0.78 s cold / 0.48 s warm;
copy+fsync full pass 7.4-9.6 s (107-139 MB/s end-to-end); no-fsync subset
188-215 MB/s; fsync delta 21-43 µs/file; link pass 7.9-8.4 s (371-418
µs/file); whole-read peak 52 MB on 50 MB file vs chunked 2.1 MB; index
1.35 MB, commit 0.04 s, load 0.03 s / 9.6 MB peak; `changed_files` 2 ms;
incremental runs 8.4 s; apparent 3 × 1025 MB vs true 1079 MB; prune 1.6 s;
sweep 0.17 s.

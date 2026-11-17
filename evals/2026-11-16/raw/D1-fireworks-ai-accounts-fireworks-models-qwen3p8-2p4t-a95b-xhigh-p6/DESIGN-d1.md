# DESIGN — `backupctl` (fixture D1)

Snapshot backup tool for the `evals/` result directories, living alongside
`synccli.py` / `snaputil.py` in this repo and building directly on them.

All line references are to `synccli.py`, `snaputil.py`, and `test_synccli.py`
in this directory. All measured numbers were produced on the reference
machine (Apple M3 Max 14-core, 36 GB RAM, macOS 15.8.1, APFS NVMe,
Python 3.10.11) by running a prototype of exactly this algorithm against the
real `synccli`/`snaputil` code, on a 1,055,010,972-byte tree of 30,000 files
in 3 directories (10,000 files each, mean ~35 KB). The repo suite
(`python3 -m unittest`, 6 tests) passes as-is and is left untouched.

---

## 1. Scope and threat model

`backupctl` covers N configured directories (3 today, a few dozen over time)
and produces **snapshots**: complete point-in-time images kept under one
backup root. Guarantees designed for:

- **Concurrent triggers**: the scheduler and a person may start runs at the
  same time; a restore may read while a run writes; a prune may run while a
  restore reads. No combination corrupts anything (§4).
- **Visibility == completeness**: a reader never asks whether a run finished.
  A snapshot is either invisible or complete, index included (§3, §4).
- **Process death at any point**: Ctrl-C, sleep, kill. An interrupted run
  leaves nothing mistakable for a snapshot; the next run self-heals without
  manual cleanup, including corrupt/half-written indexes (§5).
- **Sources that vanish or cannot be read** mid-run: defined snapshot
  content, defined report, identical for scheduler and human (§6).
- **Bounded growth**: retention deletes old snapshots safely, never leaving
  the user without a usable snapshot (§8).
- **Incremental runs**: unchanged files are recognized and not re-copied, at
  a stated granularity with stated blind spots (§7).

**Threat model boundary**: "the process dies" means process death — the OS
and its page cache survive, so data written before a rename is durable with
respect to the next run. Kernel panic / power loss is out of the default
contract; an opt-in `--fsync-files` mode covers it at a measured cost (§5.4).
Actors outside the contract (a human `rm -rf` inside the published area,
non-advisory-lock writers) are detected and reported (§5.3) but not prevented.

---

## 2. Backup-root layout and snapshot naming

```
backup_root/
  .backup.lock                 # flock(2) file; serializes all writers (§4)
  staging/                     # in-flight work; invisible to readers
    snap-<ts>-<NN>/            # exactly one at a time (lock); GC'd if orphaned
  snap-<ts>-<NN>/              # published snapshots — immutable once renamed in
    data/<cfg_name>/...        # the backed-up trees, one subtree per config dir
    meta/<cfg_name>.index.json # per-dir index: {relpath: {"size","mtime"}}
    meta/snapshot.json         # run report: baseline, counts, skips, recovery
```

**Naming**: `snap-YYYYMMDD-HHMMSS-NN` — exactly the format `list_snapshots`
documents (`snaputil.py:11-14`, e.g. `snap-20261112-150000-07`), so
`snaputil.list_snapshots` (`snaputil.py:8-20`) is the snapshot catalog:
fixed-width fields make its `sorted()` (`snaputil.py:20`) chronological.
There is **no separate global catalog file** — the tree is the catalog,
re-derived every run via `list_snapshots`, which eliminates an entire class
of corrupt-catalog states.

Two properties of `list_snapshots` are load-bearing and were verified by
execution: it scans only direct children of `backup_root` matching
`snap-*` directories (`snaputil.py:17-19`), so `staging/` (and everything in
it) and `.backup.lock` are invisible to readers — verified: a staging dir
containing a `snap-*` dir, a `.backup.lock` file, and a `snapnotes.txt` were
all ignored.

**Sequence number `NN` = 1 + max existing `NN`** among same-timestamp
snapshots (not count + 1). A count-based suffix collides after a prune
removes earlier same-second names: the prototype hit this — count-based
produced an existing name and `os.rename` failed `ENOTEMPTY`. Max+1 is
monotone within a timestamp and prune-proof. Verified: two runs inside one
second yield `-01`/`-02`, sort chronological. As a final guard the publish
step checks `os.path.lexists(final)` and aborts (exit 4) rather than
renaming over anything pre-existing (external meddling; rename over a
non-empty dir fails anyway, over an empty one would silently replace).

**Isolation of `meta/` from `data/`** matters for validation: the index for
`data/<cfg>/` lives outside that subtree, so re-scanning the subtree with
`synccli.scan_files` (`synccli.py:10-19`) yields exactly the backed-up file
set with no index files mixed in, comparable set-to-set against the index.

---

## 3. Run algorithm (`backupctl run`)

Inputs: config (§10), `keep` (default 10), optional `max_age_days`,
`full_refresh`. One run:

1. **Lock.** `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on `backup_root/.backup.lock`.
   Failure → print "another run is in progress", exit **2**, zero side
   effects. Same for scheduler and human. (Verified: exit 2, nothing created.)

2. **Staging GC.** Under the lock, every entry in `staging/` is by definition
   debris of a dead run (any live run would hold the lock). Build
   `items = [(name, False), ...]` over `os.listdir(staging)` and pass through
   `synccli.collect_stale` (`synccli.py:45-59`) — nothing is fresh, so it
   returns all of them — then `shutil.rmtree` each. Each deletion is
   reported. (Verified: a run killed after 5 copies left one debris dir
   invisible to `list_snapshots`; the next run GC'd it and completed.)
   Note on the reused helper: `collect_stale` never mutates its `seen` set
   (`synccli.py:52-58`), so duplicate items are reported twice — verified.
   Staging names are unique, so the quirk is inert here.

3. **Baseline selection + validation.** Walk
   `reversed(snaputil.list_snapshots(backup_root))` (newest first). For each
   candidate, for each config dir: parse `meta/<cfg>.index.json` (strict:
   JSON object; every value exactly `{"size": int, "mtime": number}` — the
   `synccli.file_state` shape, `synccli.py:22-25`) and compare
   `set(index)` against `set(synccli.scan_files(<snapshot>/data/<cfg>))` in
   **both** directions. First candidate where all dirs pass is the baseline.
   Failures produce recovery records (§5.3) and the candidate is marked
   UNVERIFIED — whole-snapshot all-or-nothing (one torn index suggests wider
   damage; per-dir fallback complexity buys little since the fallback
   snapshot covers all dirs). Cost measured: full validation of a 30k-file
   snapshot = **0.28 s**. If no snapshot validates: baseline = none, this run
   is a full copy (progress without manual cleanup, per the brief).

4. **Per-directory snapshot build** (sequentially, one config dir at a time —
   this is what bounds memory at max-dir instead of sum, §12):
   a. `src_manifest = synccli.build_manifest(src_path)` (`synccli.py:28-33`),
      which uses `scan_files` (`synccli.py:10-19`) and `file_state`
      (`synccli.py:22-25`). Documented inherited behavior: dot-directories
      are excluded (`synccli.py:14`) while dot-files are kept — verified.
      This is kept as-is for v1 (evals artifacts live in visible dirs); a
      future `--include-dot-dirs` would override the filter at
      `synccli.py:14` and is explicitly out of scope here.
   b. `to_copy = synccli.changed_files(baseline_index, src_manifest)`
      (`synccli.py:36-42`) — new + state-changed files. The **unchanged** set
      is the complement within `src_manifest`. **Deletions**:
      `changed_files` provably ignores old-not-in-new entries (verified:
      returns `[]` when only a deletion happened); they need no handling
      because the snapshot is built from `src_manifest` — a deleted source
      file is simply absent — and the run reports
      `deleted_since_baseline = len(set(old) - set(src_manifest))`.
      With `--full-refresh`: `to_copy` = all of `src_manifest`.
   c. **Copy** each `to_copy` file (sorted, deterministic) with
      `copy_file_reported` — the override of `synccli.copy_file`
      (`synccli.py:62-69`), see §6 and §13. On success the entry goes into
      the in-memory index; on `OSError` the file is recorded in `skips`
      (`{dir, relpath, errno}`) and excluded from snapshot and index.
   d. **Link** each unchanged file:
      `os.link(safe_snapshot_path(backup_root, baseline, data/<cfg>/<rel>), staged/data/<cfg>/<rel>)`
      — path mapping via `snaputil.safe_snapshot_path` (`snaputil.py:54-63`)
      wrapped in the containment check it lacks (§9, §13). Hard links, not
      clones: same filesystem by construction (staging is inside
      `backup_root`), O(1) per file, no extra data blocks. Fallbacks: link
      `OSError` → copy from source; that copy fails → `skips`. Parent dirs
      are created once per distinct directory per run (a created-set replaces
      the per-file `os.makedirs` pattern at `synccli.py:64`; measured gain
      15–31% of the link phase, §11).
   e. **Write `meta/<cfg>.index.json`**: exactly the files that materialized,
      each with the **source** state from `src_manifest` (so the next run's
      `changed_files` compares source-to-source; JSON float round-trip of
      `st_mtime` is exact — verified). The index never mentions a skipped
      file: it can never promise what the snapshot lacks. Size measured:
      **79 B/entry** (`indent=2`), write **2.2 µs/entry**.
   f. Release the per-dir manifest before the next dir (memory bound, §12).
      A missing config dir entirely: empty index `{}`, one skip record with
      `errno=ENOENT`, run continues (exit 1).

5. **Write `meta/snapshot.json`** (the run report): snapshot name, baseline
   name, config, per-dir `{files, copied, linked, skipped,
   deleted_since_baseline}`, `skips` list, `recovery` records, timings.
   `flush` + `os.fsync` the file, then `fsync` the staged root dir. This is
   the only fsync before publish (2 syscalls; publish measured **0.3 ms**).

6. **Publish — the atomicity point.** `os.rename(staged/snap-X,
   backup_root/snap-X)` (same filesystem → atomic directory rename), then
   `fsync(backup_root)`. Before this instant the snapshot is invisible to
   every reader (`list_snapshots` cannot see staging, §2); after it, the
   snapshot is complete — data, indexes, and report were all finalized
   inside staging before the rename. There is no state in which a reader can
   observe "some files from this run, some from the previous one", and no
   index that promises absent files: the index was written from
   materialized files only (step 4e) and travels inside the renamed unit.
   (Verified: a reader thread making 35 full observations — parse meta,
   index↔tree set equality, per-file size check — across a full run, a
   steady run, and a publishing+pruning run saw **0 violations**.)

7. **Retention** — only after a successful publish (a run that produced
   nothing must not shrink history): `snaputil.prune_snapshots(backup_root,
   keep)` (`snaputil.py:23-36`), plus the optional age policy (§8). Deleted
   names are reported. `OSError` mid-prune is caught, reported, and left for
   the next run to complete (§5.5).

8. **Exit**: **0** clean; **1** completed with skips (snapshot usable, report
   lists what is missing); **2** lock busy; **4** config/publish error.
   One code path for scheduler and human — the only difference is who reads
   stdout and the exit code.

`--dry-run` mirrors `synccli.sync`'s `dry_run` (`synccli.py:81-82`): steps
3–4b only, reporting per-dir copy/link/delete sets; no staging, no publish,
no prune (read-only; no lock needed).

---

## 4. Concurrency contract

| Combination | Mechanism | Verified |
|---|---|---|
| run × run (scheduler × person) | `flock` LOCK_EX\|LOCK_NB on `.backup.lock`; loser exits 2 with zero side effects. Runs never actually overlap in their mutating sections. | exit 2, no artifacts created |
| run × restore (reader) | Readers take **no lock** and never block writers. Staging invisible (§2); publish is one atomic same-FS `os.rename`; published snapshots immutable. A reader sees a snapshot as absent, then complete — never partial. | 35 concurrent reader observations, 0 violations |
| run × newer publish during a restore | Restore resolved name X; publishing Y touches only `staging/` and the new name. X is immutable. | immutability: corrupt-index test left bytes byte-identical |
| prune × restore | Prune runs only inside a run (under the lock) or as an explicit locked `backupctl prune`. POSIX unlink semantics: an already-open fd keeps reading a deleted file to EOF; a path-open after unlink gets ENOENT → restore retries next-newest (§9). Oldest-first deletion (`snaputil.py:33`) means the newest — the usual restore target — is never a victim (`snaputil.py:26-28`). | fd read through `rmtree` returned identical bytes; reopen → ENOENT |
| prune × run validation | A half-deleted snapshot that is a baseline candidate fails step-3 validation (index↔tree mismatch) → UNVERIFIED → fallback. | `promised_absent: 1` detected, older baseline used |
| restore × restore | Read-only on immutable data; no interaction. | — |

A reader's *only* obligations are §9's: resolve names via `list_snapshots`,
map paths via the containment wrapper, treat ENOENT as "pruned mid-read →
retry next-newest". It never needs to know whether any run is in flight —
that is the structural answer to "a reader never asks whether the run that
produced a snapshot is finished".

---

## 5. Crash and corruption recovery

### 5.1 Where half-written state can exist, and why it is safe

With staging + atomic rename, the **only** half-written state a dead run can
leave is inside `staging/` — invisible to `list_snapshots` (§2, verified) and
deleted wholesale by the next run's GC (step 2, verified). The published
area contains only complete snapshots. This covers the brief's "interrupted
run must leave nothing behind that a later reader could mistake for a
complete snapshot" and "the next run must make progress without manual
cleanup" — the GC and the baseline fallback are automatic.

Laptop sleep = suspension, not death: the run resumes or is later killed —
either outcome is covered. Ctrl-C/kill mid-copy, mid-index, mid-report, and
pre-rename all reduce to the staging-debris case. Death *during* the rename
is impossible to observe: `rename(2)` is atomic.

### 5.2 Durability (fsync) policy

The published-visibility order is: file data written → `snapshot.json`
fsync'd → staged root fsync'd → rename → `backup_root` fsync'd. Against the
threat model (process death), page-cache survival makes per-file fsync
unnecessary. For power-loss-prone setups, `--fsync-files` fsyncs each copied
file before the rename: measured overhead **~4 µs/file** on the reference
machine (2,825 files/s with fsync vs 2,837 without, 35 KB files) → +0.12 s
per 30k-file run; budget +1 ms/file (≤ +30 s per 30k) for slower disks.
Residual risk without it, stated plainly: after kernel panic/power loss a
published snapshot may contain short files; step-3 validation catches it at
the next run (size/index checks fail → UNVERIFIED → fallback).

### 5.3 Corrupt or half-written published index — the required recovery spec

Trigger cases, all real: torn write surviving power loss after rename
(§5.2), interrupted prune of the newest snapshot by an external actor,
disk rot, tampering. Step 3 handles them uniformly. Per
(snapshot, config-dir) failure:

- **Discarded**: the corrupt index's parsed content — in memory only. The
  published bytes on disk are **not touched** (published area is immutable;
  verified: the garbage index remained byte-identical after the run).
- **Re-derived from the tree**: the file list via
  `synccli.scan_files(<snapshot>/data/<cfg>)` (`synccli.py:10-19`) plus
  per-file `os.stat` — reported as `rederived_paths` (verified: 27). The
  re-derived stats carry *snapshot* mtimes (copy time), not source mtimes,
  so the re-derived list is usable for restore-by-walk and reporting, and is
  **not** usable for change detection — which is precisely why:
- **Consequence**: the snapshot is marked **UNVERIFIED** and disqualified as
  incremental baseline; the run falls back to the next-newest VERIFIED
  snapshot (verified: 55 files linked from the older baseline, the 12
  post-baseline changes copied), or to a full copy if none exists. The
  UNVERIFIED snapshot remains listed and restorable (restore falls back to
  tree-walk, §9).
- **Reported**: one recovery record per failure —
  `{snapshot, dir, discarded: <index path>, rederived_paths: n,
  promised_absent: n, unindexed: n, consequence}` — printed to stdout and
  persisted in the new snapshot's `meta/snapshot.json`, so the history of
  recoveries travels with the backup. Two failure shapes are distinguished:
  unparseable/schema-violating index (`discarded`, `rederived_paths`), and
  index↔tree set mismatch (`promised_absent` = index entries with no file —
  the "index promises files the snapshot does not contain" detector,
  verified with 1; `unindexed` = files with no index entry).

Half-written indexes **in staging** need no spec beyond §5.1: they are never
published and are GC'd wholesale.

### 5.4 Orphaned staging debris

Step 2 deletes every staging entry under the lock (a live run would hold the
lock, so any entry is dead). `collect_stale` (`synccli.py:45-59`) does the
selection; `shutil.rmtree` the removal; each name is reported. Verified
end-to-end (§3 step 2).

### 5.5 Interrupted prune

`prune_snapshots` killed mid-`shutil.rmtree` (`snaputil.py:34-35`) leaves a
half-deleted `snap-*` dir that `list_snapshots` still lists. Self-healing, no
marker files needed:
- It is among the **oldest** snapshots (prune deletes oldest-first,
  `snaputil.py:33`), so baseline selection normally never reaches it; if it
  ever does (e.g. it is all that remains), step-3 validation flags it
  (index promises absent files) → UNVERIFIED → fallback (verified).
- The next run's prune recomputes victims from `list_snapshots` — the
  half-deleted dir is still oldest, still over the keep window — and
  `shutil.rmtree` walks the *actual* tree state, so the retry completes the
  deletion without error. Verified: externally half-deleting the oldest
  snapshot, then one run with `keep=2`, removed it completely with no
  `prune_error`.
- Readers hitting it mid-shrink follow the §9 ENOENT contract.

---

## 6. Vanished / unreadable source files

**Today's behavior, named and overridden.** `synccli.copy_file` swallows any
`OSError` (`synccli.py:68-69`, `except OSError: pass`) and returns `None` —
verified: copying a missing file raises nothing, reports nothing. Worse,
`synccli.sync` then writes the **full source manifest** as the destination
manifest (`synccli.py:85-86`) regardless of what actually got copied — the
exact failure the brief forbids: an index promising files the destination
does not contain. `backupctl` overrides both points (§13 items 1–2):

- `copy_file_reported(src, dst)` propagates `OSError` to the caller instead
  of swallowing it, and copies in 1 MiB chunks instead of one whole-file
  `fsrc.read()` (`synccli.py:66-67`) — see §13 item 3 for the memory reason.
- The index is built from **materialized files only** (step 4e), never from
  the source manifest.

**Behavior** (identical for scheduler and human — one code path):

- File vanishes between listing and copying → the copy raises `ENOENT`;
  file unreadable at copy time → `EACCES`/etc. Same handling: record
  `{dir, relpath, errno}` in `skips`, exclude from snapshot **and** index.
  (Verified both: vanish-between-list-and-copy → exit 1, ENOENT recorded,
  file absent from index and tree; chmod-000 file → exit 1, EACCES
  recorded, absent from index.)
- **The snapshot then contains**: every file that could be read, with the
  unchanged ones linked — a complete image *minus the recorded skips*, and
  an index that matches the tree exactly (validation passes on it).
- **The run reports**: skips printed to stdout and persisted in
  `meta/snapshot.json`; exit code **1** ("completed with skips") so a
  scheduler can alert while a human sees the same list inline.
- **Self-healing**: a skipped file is absent from the newest index, so if
  the source reappears (or becomes readable), the next run's
  `changed_files` sees it as new and copies it — no manual step.

---

## 7. Change detection

**Granularity: per file, `(size, mtime)`** — exactly `synccli.file_state`
(`synccli.py:22-25`), compared by `synccli.changed_files`
(`synccli.py:36-42`) against the baseline's per-dir index, which stores
entries in precisely the `file_state` dict shape so dict equality works
unchanged (JSON round-trip of the float `st_mtime` is exact — verified).
Unchanged files are hard-linked from the baseline (§3 step 4d), not
re-copied; measured link cost ≈ 0.4 ms/file in-run vs ≈ 0.3 ms/file +
bytes for copy — the win is bytes and I/O, not syscalls (§11).

**What this granularity can miss** (stated per the brief):

1. **Same-size in-place edits that restore the original mtime** — editors
   or tools preserving timestamps, `touch -r`, `rsync --times` restorations.
   Size equal + mtime equal ⇒ judged unchanged.
2. **Edits within the filesystem's timestamp granularity** that also
   preserve size: two states sharing one mtime tick are indistinguishable.
3. **float64 aliasing**: `st_mtime` is a float; at the current epoch its
   resolution is 2⁻²² s ≈ 0.24 µs — rewrite bursts finer than that alias.
4. **Coverage boundary** (not granularity): dot-directories are never
   scanned (`synccli.py:14`, inherited and documented in §3 step 4a) —
   changes there are invisible by design.

**Deletions** are structural, not detection: the new snapshot is built from
the current source manifest, so files deleted at the source are simply
absent; `changed_files` itself provably never reports them (verified) and
the run reports the count via set difference (§3 step 4b).

**Mitigation knob**: `--full-refresh` (or `full_refresh_every: R` in config)
ignores the baseline every R-th run and re-copies everything, bounding the
lifetime of a missed edit to R runs. An opt-in checksum mode is future work:
SHA-256 runs at **2,713 MB/s** measured, so a full-tree hash of a 1 GB tree
adds ≈ 0.4 s read-side — cheap enough to add later without redesign; not in
v1 because it doubles per-run `stat`→`read` I/O on unchanged files.

---

## 8. Retention

**Policy** (defaults in config, per-run overridable):

- `keep = 10` newest snapshots (minimum 1), deleted oldest-first after each
  successful publish, via `snaputil.prune_snapshots` (`snaputil.py:23-36`).
- Optional `max_age_days`: computed as
  `effective_keep = max(1, count(snapshots not is_stale(dir, now - max_age)))`
  using `snaputil.is_stale` (`snaputil.py:66-73`) — snapshot-dir mtime is
  the publish time — then one `prune_snapshots(backup_root, effective_keep)`
  call. The `max(1, …)` clamp keeps the newest snapshot even when every
  snapshot exceeds the age limit. **Documented divergence**: `is_stale`
  returns stale when `st_mtime == ref_epoch` (`<=`, `snaputil.py:73`) while
  its docstring claims equality is *not* stale (`snaputil.py:70-72`) —
  verified `True` at equality. `backupctl` accepts the code's semantics (a
  snapshot exactly `max_age` old to the second is deleted); the one-second
  boundary is measure-zero and the docstring is not the contract.

**"Never leave the user without a usable snapshot"**, three layers:

1. `prune_snapshots` deletes only `names[:len-keep]` (`snaputil.py:33`) —
   the newest snapshot is never a victim, structurally (verified: `keep=1`
   over two snapshots deleted only the oldest).
2. Prune runs **only after this run successfully published** (§3 step 7) —
   history never shrinks on a run that added nothing.
3. The newest snapshot was validated-consistent at publish time by
   construction (index written from materialized files, inside the atomic
   unit). If an external actor corrupted it afterwards, step-3 validation
   reports UNVERIFIED and the fallback chain still holds older VERIFIED
   snapshots; prune with `keep ≥ 1` cannot empty the root.

**Safety while a reader is reading the victim**: POSIX unlink semantics —
verified: an fd opened before `shutil.rmtree` (`snaputil.py:35`) kept
reading byte-identical data through the deletion; a fresh open gets ENOENT,
which the restore contract (§9) turns into "retry next-newest". Oldest-first
ordering means the typical restore target (newest) is never concurrently
deleted.

**Disk reclaimed**: hard-linked unchanged files free their blocks only when
the last snapshot linking them is pruned; changed-file blocks free when
their snapshot is pruned. Real usage bound in §12.

---

## 9. Restore contract (separate tooling; this is the interface it must honor)

Restore is not built here, but `backupctl`'s guarantees are only real if
readers follow the interface the design defines:

- **R1 — Discovery**: names via `snaputil.list_snapshots` (oldest-first,
  `snaputil.py:8-20`); default target = newest (`[-1]`). Never guess names,
  never read `staging/`.
- **R2 — Completeness is free**: any listed snapshot is complete (§3 step 6).
  Read `meta/snapshot.json` first: it lists the run's `skips` — files the
  backup itself knew were missing (§6). No "is it finished?" check exists or
  is needed.
- **R3 — Path mapping**: map every index `relpath` through
  `safe_snapshot_path` (`snaputil.py:54-63`) **wrapped in a containment
  check**. The wrapper is mandatory, not decorative: `os.path.normpath`
  (`snaputil.py:62`) collapses *interior* `..` but preserves *leading* `..`
  — verified: `safe_snapshot_path(root, "snap-x", "../../etc/passwd")`
  resolves **outside the backup root**, contradicting its docstring
  (`snaputil.py:58-61`). Override (§13 item 5): reject `relpath` whose
  `normpath` is absolute, equals `..`, or starts with `../` before joining.
  Indexes written by `backupctl` cannot contain such paths
  (`os.path.relpath` output under the scan root never leads with `..`), so
  the check costs one string test and converts a tampered/rotted index from
  an escape hatch into an error.
- **R4 — ENOENT = pruned mid-read**: on any `FileNotFoundError` (open, read,
  stat), abort this snapshot and retry with the next-newest listed name
  (verified scenario, §4/§8). Files may only *disappear* under a reader —
  never appear or change (§4 immutability).
- **R5 — No locks, no writes**: readers never take `.backup.lock` and never
  write under `backup_root`.
- **R6 — UNVERIFIED snapshots**: if `meta/*.index.json` is unreadable or
  mismatched (a `backupctl verify` report says so), restore by walking
  `data/<cfg>/` directly instead of trusting the index — the tree is always
  self-consistent even when its index is not.

---

## 10. CLI and configuration

```
backupctl run    [--config F] [--keep K] [--max-age DAYS]
                 [--full-refresh] [--dry-run] [--fsync-files]
backupctl list   [--config F]            # snapshots, apparent + real sizes
backupctl verify [--config F]            # step-3 validation over ALL snapshots
backupctl prune  [--config F] [--keep K] # manual retention; takes the lock
```

Exit codes (all commands): 0 ok · 1 completed with skips/warnings ·
2 lock busy · 4 config/publish error. Scheduler policy: 1 = alert-but-ok,
2 = skip this tick silently (another run is doing the work).

Every **mutating** command takes the same flock; `list`/`verify`/`--dry-run`
are read-only and lock-free (they may observe prunes per R4/§5.5 and report
UNVERIFIED accordingly).

Config (`backupctl.json`):

```json
{
  "backup_root": "/path/to/backups",
  "directories": [
    {"name": "evals-a", "path": "/repo/evals/a"},
    {"name": "evals-b", "path": "/repo/evals/b"},
    {"name": "evals-c", "path": "/repo/evals/c"}
  ],
  "keep": 10,
  "max_age_days": null,
  "full_refresh_every": 0
}
```

`name` validation (exit 4 on violation): non-empty, unique, no `os.sep`,
not `..` — names become directory components under `data/`. N is a few
dozen; every N-dependent bound is in §12.

---

## 11. Performance budget — measured, with derivation

**Reference machine**: Apple M3 Max (14 cores), 36 GB, macOS 15.8.1, APFS
NVMe, Python 3.10.11, warm page cache. **Workload**: 3 dirs × 10,000 files,
1,055,010,972 B total (~1 GB), mean file 35 KB.

Measured end-to-end (prototype of §3 running against the real
`synccli`/`snaputil`):

| Run | Wall | Breakdown (measured) |
|---|---|---|
| **First full backup** (1 GB / 30k files) | **10.50 s** | scan 0.73 s · copy 9.70 s · indexes 0.067 s · report+publish 0.0006 s · baseline/GC ≈ 0.01 s |
| Steady run, 0% changed (30k links) | 13.40 s | scan 0.79 s · link 12.29 s · validate 0.28 s · indexes 0.068 s |
| Steady run, 5% changed (1,530 copied / 26.4 MB, 28,470 linked, 30 deleted) | 13.53 s | work phase 12.42 s vs 12.29 s at 0% churn: net **+0.13 s** (1,530 copies ≈ +0.5 s, offset by 1,530 fewer links ≈ −0.4 s) |
| Publish step alone (rename + 2 fsync) | 0.3–0.4 ms | |
| Prune 2 snapshots (30k files each, hard-linked victims) | 4.84 s | ≈ **12,400 files/s** `rmtree`; ≈ 2.4 s per 30k-file snapshot. (Victims here were hard-linked — nlink dropped without freeing blocks; freeing sole-link data is disk-dependent and only occurs for changed-file blocks.) |

The measured steady runs did **not** trigger prune (`keep=10` was never
exceeded); in a keep-window steady state each run prunes exactly one
snapshot, adding ≈ ΣF/12,400 s ≈ 2.4 s at 30k files — included in the
formula below.

Component rates (measured; use these to re-derive the budget anywhere):

| Constant | Value | How measured |
|---|---|---|
| `R_scan` (scan+stat via `build_manifest`) | **33,000 files/s** | 10k-file dir in 0.305 s |
| `R_copy` (chunked, incl. per-file overhead) | **109 MB/s ≈ 3,300 files/s** @ 35 KB mean | 1 GB copy phase 9.70 s |
| `R_link` (`os.link` + path map, in-run) | **2,440 links/s** (micro-bench spread 700–2,600/s under load) | 30k links in 12.29 s |
| Index write | **2.2 µs/entry** (22 ms per 10k) | per-dir index phase |
| Index size | **79 B/entry** (`indent=2`) | meta file size / entries |
| Baseline validation | **0.28 s per 30k files** | step-3 timing |
| Per-file fsync (opt-in) | **≈ 4 µs** | 1000 × 35 KB with/without |
| SHA-256 (future checksum mode) | **2,713 MB/s** | 1 GiB hash |

**Derivation of the budget** (formula, then margin):

```
T_full  ≈ ΣF/33,000 + ΣB/109 MB·s⁻¹ + ΣF×2.2 µs + 1 ms
        = 0.91 s   + 9.68 s          + 0.066 s    ≈ 10.7 s   (measured 10.50 s ✓)
T_steady ≈ ΣF/33,000 + U/R_link + C/3,300 + ΣF×2.2 µs + 0.28 s + (prune fires) ΣF/12,400
        = 0.91 s    + 12.3 s   + ~0.5 s  + 0.066 s   + 0.28 s + 2.4 s    ≈ 16.5 s
                                                            (measured 13.4–13.5 s pre-prune-window ✓)
```

**Budget for the initial full backup of a ~1 GB / tens-of-thousands-of-files
tree: ≤ 60 s** on the reference machine class. Where the 60 comes from:
measured 10.5 s × 4 margin ≈ 42 s, rounded up to 60 s. The 4× covers the
measured worst-case degradation of the dominant metadata phase (the link
micro-bench ran up to ~3× slower when the disk was busy) plus cold-cache /
slower-disk headroom. Same margin applied to the steady run
(13.5 s × 4 ≈ 54 s): **steady runs ≤ 60 s for ≤ 50k files / ≤ 5 % churn**.
On other hardware, recompute from the component-rate table — the formula is
the budget; 60 s is its instantiation here.

Two honest observations from the measurements:

- **The steady run is slower than the first full run at this scale**
  (13.4 s vs 10.5 s): linking 30k files is metadata-bound (12.3 s) while
  copying 1 GB streams at 109 MB/s (9.7 s). Incremental still wins what
  matters — bytes written (26 MB vs 1 GB at 5 % churn) and disk growth
  (§12) — but per-run *time* has a hard floor of ≈ ΣF × 0.45 ms
  (scan + link), i.e. ≈ 13 s per 30k files even at zero churn. Mitigations
  already priced in: batched directory creation (created-set replacing the
  per-file `os.makedirs` pattern of `synccli.py:64`; measured −15 % quiet,
  −31 % loaded on the link phase) and precomputed link paths. APFS
  `clonefile` instead of hard links is noted as future work (same metadata
  cost, avoids cross-snapshot inode sharing).
- **Prune cost is real but amortizable**: ≈ ΣF/12,400 s per pruned snapshot
  (2.4 s per 30k-file snapshot, cheaper than copy because hard-linked data
  blocks are not freed). Included in the steady-run budget above.

---

## 12. Scaling bounds — what grows with what, explicitly

Variables: N = config dirs, Fᵢ = files in dir i, F_max = max Fᵢ,
ΣF = ΣFᵢ, Bᵢ = bytes in dir i, Δ = bytes changed per run, U = unchanged
files per run, K = `keep`. All byte figures in this section are decimal
MB (10⁶ B), matching the measurements.

| Quantity | Bound | Kind |
|---|---|---|
| Per-run wall time | ΣF/33,000 + U/R_link + Δ/109 MB·s⁻¹ + ΣF×2.2 µs + 0.28 s·(ΣF/30k) + (pruned snapshots)×ΣF/12,400 — §11 formula, constants measured | formula, linear in ΣF and Δ |
| Per-run wall, floor (zero churn) | ΣF × 0.45 ms ≈ 13 s per 30k files | measured |
| Per-dir manifest + index serialization memory | Δ RSS ≈ 2.6 MB + 715 B/entry — two-point fit from fresh-process measurements: 9.7 MB at 10k entries, 24.0 MB at 30k (manifest built by `synccli.build_manifest` + `json` serialization). Budget at **1 KB/entry** (≈ 40 % margin over the fit) | formula + measured constants |
| Full-run peak memory | ≤ C₀ + F_max × 1 KB, C₀ ≈ 45 MB (interpreter + fixed phase overhead; fitted to the single full-run measurement). Measured peak for the whole 1 GB / 30k run: **53.8 MB** with F_max = 10k (bound: 55 MB ✓); F_max = 100k ⇒ ≤ 145 MB. **Flat in N** — dirs are processed sequentially, manifests released (§3 step 4f): memory is max-dir, not sum-dir. (tracemalloc cross-check: the manifest dict alone traces 387 B/entry, 3.9 MB per 10k — the RSS bound above additionally covers walk/serialization temporaries) | formula + measured constants |
| Copy buffer | 1 MiB, flat (chunked override, §13 item 3; whole-file read would make it O(largest file) — measured 280 MB peak for a 256 MB file vs 23–27 MB chunked) | measured |
| Index JSON per snapshot | ΣF × 79 B (30k ⇒ 2.4 MB) | measured constant |
| Run report size | O(N + skips); worst case skips = ΣF entries (whole tree unreadable) | formula |
| Disk, first full snapshot | ΣB + ΣF × 79 B + dir inodes ≈ ΣB × (1 + ~0.3 %) at 35 KB mean | measured |
| Disk, real, steady state | ΣB (latest image) + Σ over retained runs of Δ_new + K × (ΣF × 79 B + inodes) — unchanged files add **0 data blocks** (hard links). Measured instance: two snapshots of a 1,055 MB tree occupy **~1,099 MB real** (`du`: 1,048 MiB), the second adding ≈ 3 MB | formula + measured |
| Disk, apparent (`snapshot_disk_usage`) | up to K × ΣB — it `os.stat`s every file (`snaputil.py:49-50`), counting each hard link fully. Measured: **2,064 MB apparent** (1,032 MB per snapshot) vs ~1,099 MB real for the pair above — a ~1.9× overcount at K=2, growing toward K× for unchanged data. `backupctl list` therefore reports **both**: `snapshot_disk_usage` unchanged for per-snapshot apparent size, plus an inode-deduplicated real-size figure (dedupe on `(st_dev, st_ino)`) — override §13 item 7 | measured + override |
| Lock / staging footprint | 1 file + ≤ 1 staging dir per run (GC'd), independent of N, ΣF, K | flat |
| Catalog work per run | `list_snapshots`: O(K) `scandir` entries; sequence computation O(K); no global catalog file exists (§2) | flat in N and ΣF |
| Baseline validation per run | 0.28 s per 30k files × (ΣF/30k), one snapshot (newest VERIFIED) | measured, linear in ΣF |
| With N growing 3 → 36 dirs | Time: linear in ΣF (sequential). Memory: unchanged if F_max unchanged. Disk: linear in ΣB. Nothing about N itself enters any bound except report/metadata size O(N) | formula |

---

## 13. Grounding ledger

### 13.1 Reused as-is (exact artifact · what `backupctl` uses it for)

| Artifact | Used for |
|---|---|
| `synccli.scan_files` (`synccli.py:10-19`) | Source scans (via `build_manifest`), snapshot-tree re-derivation and validation (§3 steps 3–4a, §5.3). Inherits dot-dir exclusion (`synccli.py:14`, kept + documented; dot-files kept — both verified) |
| `synccli.file_state` (`synccli.py:22-25`) | The `(size, mtime)` state stored verbatim in indexes; JSON round-trip exactness verified |
| `synccli.build_manifest` (`synccli.py:28-33`) | Per-dir source manifest (§3 step 4a) |
| `synccli.changed_files` (`synccli.py:36-42`) | Copy set = new + changed (§3 step 4b); unchanged = complement; deletion *non*-reporting verified and compensated by set difference |
| `synccli.collect_stale` (`synccli.py:45-59`) | Staging GC selection (§3 step 2); its never-mutated `seen` quirk (`synccli.py:52-58`) verified and inert for unique staging names |
| `synccli.sync` `dry_run` semantics (`synccli.py:81-82`) | Model for `backupctl run --dry-run` (§3) |
| `snaputil.list_snapshots` (`snaputil.py:8-20`) | The snapshot catalog: discovery, chronological order, newest/oldest, sequence computation; invisibility of `staging/` + `.backup.lock` verified |
| `snaputil.prune_snapshots` (`snaputil.py:23-36`) | Retention deletion; newest-never-deleted (`snaputil.py:31-33`) and oldest-first verified; interrupted-prune self-heal verified |
| `snaputil.snapshot_disk_usage` (`snaputil.py:39-51`) | Per-snapshot apparent size in `backupctl list` (with the inode-deduin addition, §13 item 7) |
| `snaputil.safe_snapshot_path` (`snaputil.py:54-63`) | Reader/run path mapping, inside the containment wrapper (§13 item 5) |
| `snaputil.is_stale` (`snaputil.py:66-73`) | Optional `max_age_days` retention (§8), with the equality-boundary divergence documented (§13 item 6) |
| `test_synccli.py` suite | Regression base: `python3 -m unittest` passes (6 tests) before and after; `backupctl` changes none of it |

### 13.2 Overrides — exact behavior replaced, where it lives, why

1. **`synccli.copy_file`'s silent `OSError` swallow** (`synccli.py:68-69`).
   Replaced by `copy_file_reported`, which propagates the error to the run
   loop. Reason: the brief requires vanished/unreadable sources to be
   recorded and reported (§6); swallowing makes the skip invisible —
   verified: `copy_file` on a missing source returns `None`, no signal.
2. **`synccli.sync`'s manifest-written-despite-failed-copies**
   (`synccli.py:85-86` writes the full source manifest after a copy loop
   whose failures were swallowed at `synccli.py:68-69`). Replaced by
   indexes built from materialized files only (§3 step 4e). Reason: this is
   the exact "index promises files the snapshot does not contain" failure
   the brief forbids; it is live behavior in `sync` today.
3. **`synccli.copy_file`'s whole-file single `read()`**
   (`synccli.py:66-67`). Replaced by 1 MiB chunked copy. Reason: bounds
   copy memory to O(1) instead of O(largest file) — measured: 280 MB
   peak RSS copying a 256 MB file whole vs 23–27 MB chunked. Also replaces
   its per-file `os.makedirs` (`synccli.py:64`) with a per-run created-set
   (same semantics, measured −15 % to −31 % on the metadata phase).
4. **Count-based same-second sequence numbers** (a naive reading of the
   `snap-…-NN` format in `snaputil.py:11-14`). Replaced by max+1 (§2).
   Reason: prototype-verified collision — after a prune removed earlier
   same-second names, count+1 reproduced a live name and `os.rename` failed
   `ENOTEMPTY`. Plus a `lexists` guard before rename.
5. **`snaputil.safe_snapshot_path`'s containment guarantee** (docstring
   `snaputil.py:58-61` vs `os.path.normpath` at `snaputil.py:62`).
   `normpath` preserves *leading* `..`: verified —
   `safe_snapshot_path(root, "snap-x", "../../etc/passwd")` resolves
   outside the backup root. Override: callers in `backupctl` (link source
   resolution) and the restore contract (§9 R3) wrap it with a
   reject-leading-`..`/absolute check before use.
6. **`snaputil.is_stale`'s equality boundary**: code says stale at
   `mtime == ref_epoch` (`<=`, `snaputil.py:73`); docstring says not stale
   (`snaputil.py:70-72`). Verified `True` at equality. `backupctl` accepts
   the code's behavior and documents it (§8) rather than silently relying
   on the docstring.
7. **`snaputil.snapshot_disk_usage`'s implicit assumption that every file
   owns its bytes** (`os.stat` per file, `snaputil.py:49-50`). With
   hard-linked incremental snapshots it counts each link fully — measured
   2,064 MB apparent vs ~1,099 MB real for two snapshots. Override: capacity
   reporting dedupes on `(st_dev, st_ino)`; `snapshot_disk_usage` itself is
   still used, unchanged, for per-snapshot apparent size (§12).
8. **Prune invocation context**: `snaputil.main` exposes `--prune` to run
   anytime (`snaputil.py:79-84`); `backupctl` runs prune only inside a
   locked run after a successful publish (§3 step 7, §8), or via
   `backupctl prune` which takes the same lock.

Nothing else is re-implemented: scanning, state, manifests, change
detection, stale selection, listing, pruning, sizing, and path mapping are
the existing functions above.

---

## 14. Verification record and required test suite

Executed during design (prototype of §3 against the real modules; scripts
kept out of the repo):

- Repo suite: `python3 -m unittest` → 6/6 pass, unmodified.
- Benchmark: the §11 tables (1 GB / 30k tree; runs, rates, memory, disk).
- Behavior suite: **20/20 checks pass** (grouped below by guarantee; the
  real `backupctl` test suite must reproduce all of them):
  1. Lock busy → exit 2, zero side effects; lock released → run succeeds (§4).
  2. Run killed mid-copy → nothing published, debris only in staging,
     invisible to `list_snapshots`; next run GCs it via `collect_stale` and
     completes (§5.1, §5.4).
  3. Corrupt newest index → recovery record (discarded / re-derived /
     consequence), corrupt bytes untouched on disk, older VERIFIED baseline
     used, new snapshot reader-consistent (§5.3).
  4. Index promising an absent file → detected (`promised_absent`),
     fallback used (§5.3).
  5. Source vanishes between list and copy → exit 1, ENOENT skip recorded,
     absent from index and tree (§6).
  6. Unreadable source → exit 1, EACCES skip, absent from index (§6).
  7. Prune vs open reader fd: read survives `rmtree` byte-identically;
     reopen → ENOENT (§8, §9 R4).
  8. Same-second runs → distinct max+1 suffixes, chronological listing (§2).
  9. Reader thread across full + steady + publishing/pruning runs: 35
     observations, 0 violations of index↔tree↔size consistency (§3 step 6, §4).
  10. Containment wrapper rejects leading `..` that raw
      `safe_snapshot_path` resolves outside the root (§9 R3, §13 item 5).
  11. Half-deleted oldest snapshot self-heals on the next prune, no error (§5.5).
  12. Dot-directories excluded from snapshots (documented inheritance, §3 step 4a).
  13. Chunked copy bounds memory vs whole-file read (§13 item 3).
  14. Link rates measured (per-file vs batched makedirs) (§11).

**Prototype-surfaced bug adopted into the design**: count-based sequence
numbers collide after prune (§13 item 4) — found by execution, fixed as
max+1 before this document was written.

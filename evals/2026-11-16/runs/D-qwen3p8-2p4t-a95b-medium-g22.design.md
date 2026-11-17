# DESIGN — `backupctl` (fixture D1)

Snapshot backup tool for the `evals/` result directories. Covers N configured
directories (3 today, a few dozen over time), produces point-in-time snapshots
under a backup root, safe against concurrent runs, concurrent readers,
process death at any point, vanishing source files, unbounded growth, and
re-copying unchanged data.

All measurements in this document were taken on this machine (macOS 15.8.1,
Apple M3 Max, APFS, Python 3.10.11, `synccli.py`/`snaputil.py` as checked in
here) using the harness reproduced in Appendix A. The existing test suite
passes (`python3 -m unittest`, 6 tests, OK).

---

## 1. Grounding map — what is reused, what is overridden

Every claim below was checked against the code in this directory.

### Reused as-is

| Existing artifact | Location | Used by `backupctl` for |
|---|---|---|
| `synccli.scan_files` | `synccli.py:10-19` | Enumerating relative file paths of a source directory during a run. Inherits its sorted output (line 19) and its dot-directory skip (line 14) — see §7.3 for the consequence. |
| `synccli.file_state` | `synccli.py:22-25` | The `(size, mtime)` change-detection state of a file (§7). |
| `synccli.changed_files` | `synccli.py:36-42` | Diffing a fresh source manifest against the previous snapshot's index to pick the files that must be copied (§7). |
| `synccli.collect_stale` | `synccli.py:45-59` | Computing, for the run report, the files present in the baseline snapshot but no longer present in the source ("gone from source since baseline"): `collect_stale([(rel, rel in new_manifest) for rel in baseline])`. Its `seen`/fresh semantics (`synccli.py:52-58`) are exactly this predicate. |
| `snaputil.list_snapshots` | `snaputil.py:8-20` | All snapshot enumeration: baseline selection (newest = last, list is sorted oldest-first, line 20), retention selection, `backupctl list`. Its `snap-`-prefix filter (line 18) is what makes staging directories invisible to every reader (§4.2). |
| `snaputil.safe_snapshot_path` | `snaputil.py:54-63` | The restore/read contract: mapping index relpaths back under the snapshot directory with the `..`-normalization guarantee (lines 58-62). |
| `snaputil.snapshot_disk_usage` | `snaputil.py:39-51` | Per-snapshot *logical* size in `backupctl list` (see override O6 for the unique-size metric added next to it). |
| Snapshot naming convention | `snaputil.py:11-13` (docstring) | `backupctl` publishes snapshots as `snap-YYYYMMDD-HHMMSS-NN` precisely so `list_snapshots`/`prune_snapshots` recognize them. |
| Test style | `test_synccli.py` (unittest + `tempfile.mkdtemp` setUp pattern, e.g. lines 9-15) | `test_backupctl.py` follows the same structure (§12). |

### Overridden — named function, location, reason

- **O1 — `synccli.copy_file` error swallowing** (`synccli.py:65-69`): the
  `except OSError: pass` at lines 68-69 silently drops unreadable/vanished
  sources ("next pass will retry" — a sync destination can retry; a
  point-in-time snapshot cannot, the run ends when it ends). `backupctl`'s
  `copy_one` keeps the `makedirs` behavior of `synccli.py:64` but lets
  `OSError` propagate to the per-file handler in §6, which records the file
  as skipped and keeps it **out of the index**.
- **O2 — `synccli.copy_file` whole-file read** (`synccli.py:66-67`):
  `fdst.write(fsrc.read())` loads the entire file into memory, making peak
  memory = largest source file. `copy_one` replaces the inner loop with a
  chunked copy (`shutil.copyfileobj`, 16 MiB buffer) so the memory bound is
  a constant (§10, M3).
- **O3 — `synccli.build_manifest` crash on vanished files**
  (`synccli.py:28-33`): `file_state` calls `os.stat` (`synccli.py:24`),
  which raises `FileNotFoundError` when a file disappears between
  `scan_files` and the stat — `build_manifest` dies. `backupctl`'s
  `build_source_manifest` wraps each `file_state` call: on `OSError` the
  entry is dropped and the path recorded as `skipped(vanished)` (§6).
- **O4 — `synccli.sync` writes the *source* manifest as truth**
  (`synccli.py:85-86`): `sync` dumps `src_manifest` to the destination
  regardless of what `copy_file` actually delivered — combined with O1's
  swallowed errors this produces exactly the failure the brief forbids: an
  index promising files the destination does not contain. `backupctl`
  builds the snapshot index from **copy outcomes** (§4.3): an entry is
  recorded only after its bytes (or hardlink) are in the staging tree.
- **O5 — `snaputil.prune_snapshots` unguarded deletion**
  (`snaputil.py:34-35`): the loop `shutil.rmtree`s every doomed snapshot
  unconditionally, with no way to interpose a lock check; a restore reading
  that snapshot would have its tree deleted mid-walk. `backupctl`'s
  `prune` **reuses the selection logic verbatim in effect**
  (`list_snapshots` + oldest-first slice `names[:len(names)-keep]`,
  `snaputil.py:30-33`, plus the min-age floor of §8) but replaces the
  deletion step with the flock-guarded delete of §5.4.
- **O6 — `snaputil.snapshot_disk_usage` over-counts hardlinks**
  (`snaputil.py:44-51`): it sums `st_size` of every file, so with the
  hardlink model of §7.2 each unchanged file is counted once per snapshot.
  `backupctl list` keeps it as the *logical* size and adds a `unique_size`
  metric (same walk, counting only `st_nlink == 1` files) so the user sees
  real marginal disk per snapshot.
- **O7 — `snaputil.is_stale` rejected for retention age**
  (`snaputil.py:66-73`): it compares the snapshot *directory's* `st_mtime`,
  but a published snapshot's directory mtime is mutated after publish by
  index re-derivation (§5.5), so an old repaired snapshot would read as
  "fresh" and escape pruning. Retention age is parsed from the snapshot
  **name** (`snap-YYYYMMDD-HHMMSS-NN`, `snaputil.py:11-13`) instead;
  `is_stale` is not used.

A design-doc-level note: `synccli.sync`'s dry-run early return
(`synccli.py:81-82`) is the pattern `backupctl run --dry-run` copies —
plan, print, touch nothing (§11).

---

## 2. Data model and backup-root layout

```
<backup_root>/
  .backupctl.lock          # writer lock file, flock'd, never unlinked
  .staging-<pid>-<HHMMSS>/ # in-progress run; INVISIBLE to snaputil.list_snapshots
  snap-20261117-093000-01/ # published snapshot (immutable)
    <cfg-dir-name>/...     # one subtree per configured source directory
    index.json             # the snapshot index (§4.3)
    report.json            # the run report (§6.3)
  snap-20261117-100000-01/
    ...
```

- **Snapshot directory**: `snap-YYYYMMDD-HHMMSS-NN`, exactly the shape
  `snaputil.list_snapshots` recognizes (`snaputil.py:11-13,18`). `NN` is a
  sequence number chosen at publish time under the writer lock: the smallest
  `NN` not already used for that timestamp (concurrent-run collisions are
  impossible anyway — §5.1 — but scheduler and human runs in the same second
  after a lock wait still need distinct names).
- **Staging directory**: `.staging-<pid>-<HHMMSS>`. The leading dot plus the
  non-`snap-` prefix makes it invisible to `snaputil.list_snapshots`
  (prefix check at `snaputil.py:18`) and therefore to baseline selection,
  retention, and `backupctl list` — **no reader can ever select an
  unpublished snapshot**. Staging lives under `backup_root` (same filesystem
  as the final location) so publishing is a same-FS `os.rename` — atomic on
  POSIX (§5.2).
- **Configuration**: `backupctl.json` (path passed via `--config`):
  `{"backup_root": "...", "dirs": ["<abs path>", ...], "keep": 10,
  "min_age_hours": 24}`. `keep >= 1` is validated at startup; the dirs list
  is the N of the brief. Snapshot subtree names are the source dirs'
  basenames; a basename collision across configured dirs is a config error
  rejected at startup (two dirs must not write into one subtree).
- **Immutability invariant**: once published, a snapshot's content files are
  never written, moved, or deleted — not by runs, not by restore (restore
  copies *out*), not by prune (prune deletes whole snapshots). The single
  documented exception is index re-derivation of a corrupt `index.json`
  under the writer lock (§5.5). This invariant is what makes hardlinking
  (§7.2) and lock-free reads (§5.3) safe.

---

## 3. Run algorithm (one `backupctl run`)

```
 1. Read and validate config (keep >= 1, no basename collisions,
    backup_root exists or is created).
 2. Acquire writer lock on <backup_root>/.backupctl.lock:
    flock(LOCK_EX | LOCK_NB). On failure: --wait retries with 1 s poll up
    to --timeout; otherwise exit 2 with report "skipped: run in progress"
    (§5.1).
 3. Crash GC (under the lock, so no other writer exists):
    rmtree every .staging-* directory under backup_root; each one is
    residue of a dead run (§5.5). Record names in the report.
 4. Baseline selection: snaputil.list_snapshots(backup_root)[-1] (newest;
    list is sorted oldest-first, snaputil.py:20). Parse its index.json:
      - parses      -> baseline usable for change detection.
      - corrupt     -> re-derive it from the tree (§5.5); baseline marked
                       "rederived" => this run degrades to FULL COPY.
      - no snapshot -> first run: full copy, no baseline.
 5. Create staging dir .staging-<pid>-<HHMMSS>.
 6. For each configured source directory D (sequentially):
    a. new_manifest = build_source_manifest(D)          [O3-wrapped
       synccli.scan_files + synccli.file_state]
    b. baseline_section = baseline index's section for D (or {}).
    c. to_copy = synccli.changed_files(baseline_section, new_manifest)
       (synccli.py:36-42). unchanged = new_manifest keys minus to_copy.
    d. gone = synccli.collect_stale([(rel, rel in new_manifest)
       for rel in baseline_section])                    (synccli.py:45-59)
       -> report only; deletions in the source simply do not appear in
       the new snapshot (a snapshot is an image of NOW).
    e. Pre-create the subtree's directory skeleton in staging (one
       os.makedirs pass over the distinct dirnames of new_manifest —
       keeps per-file work to a single syscall, §9 measured rates).
    f. For rel in unchanged (sorted): os.link(baseline_path, staging_path)
       where baseline_path = snaputil.safe_snapshot_path(backup_root,
       baseline_name, D_subtree/rel) (snaputil.py:54-63). A link failure
       (baseline file missing/corrupt) falls back to copy; a copy
       failure goes through the §6 handler.
    g. For rel in to_copy (sorted): copy_one(src, staging_path) [O1/O2];
       on success, record index entry with the state captured at step (a)
       — pre-copy stat, which is self-healing (§6.2); on OSError, the §6
       handler records skipped and NO index entry is written [O4].
 7. Build index.json from copy/link outcomes only (§4.3); write it
    atomically inside staging: write index.json.tmp -> flush ->
    os.fsync -> os.replace onto index.json -> fsync the staging dir.
    Same procedure for report.json.
 8. Publish: os.rename(staging, snap-YYYYMMDD-HHMMSS-NN) (NN chosen per
    §2), then fsync backup_root. From this instant — and not before —
    the snapshot exists for every reader, complete (§5.2).
 9. Retention: prune under the guard of §5.4/§8, only after a successful
    publish (a failed run never prunes).
10. Release lock; print report summary; exit per §6.4.
```

Dry-run stops after step 6c per directory (no staging dir is created at
all), printing the planned copy set — the `synccli.py:81-82` pattern.

---

## 4. The index

### 4.1 Role

`index.json` inside each snapshot is the single machine-readable truth
about that snapshot: what it contains, with what change-detection state,
and what the run skipped. It serves three readers: the next run (baseline
for `changed_files`), restore (file list + path mapping), and humans.
There is **no cross-snapshot global index** — the snapshot list itself is
always re-derived from the tree via `snaputil.list_snapshots`
(`snaputil.py:8-20`), so there is no second, fallible index to corrupt.

### 4.2 Shape

```json
{
  "version": 1,
  "created": "2026-11-17T09:30:00Z",
  "baseline": "snap-20261116-093000-01",     // null on first run
  "rederived": false,                          // §5.5
  "dirs": {
    "<cfg-dir-name>": {
      "source": "/abs/path/to/source",
      "files": { "<relpath>": {"size": 1234, "mtime": 1763333333.12}, ... },
      "linked": 29500,                         // hardlinked from baseline
      "copied": 480,
      "skipped": [ {"path": "...", "reason": "vanished|unreadable",
                    "error": "FileNotFoundError"} ]
    }
  }
}
```

The `files` map is exactly `synccli.build_manifest`'s `{relpath: state}`
shape (`synccli.py:28-33`) with `synccli.file_state` states
(`synccli.py:22-25`), so the next run feeds it straight into
`synccli.changed_files` as `old_manifest` (`synccli.py:36-42`) with no
adapter.

### 4.3 Construction rule (the anti-lie invariant)

An entry enters `files` **only after** its bytes or hardlink exist in the
staging tree (steps 6f/6g). Skipped files appear only under `skipped`.
Therefore a published index can never promise a file the snapshot does not
contain — the failure mode `synccli.sync` has today (dumping
`src_manifest` at `synccli.py:85-86` even though `copy_file` silently
dropped files at `synccli.py:68-69`), overridden as O1+O4.

The index is written atomically *inside staging* before the publish rename
(step 7 before step 8), so "published" always implies "index complete and
fsync'd". A half-written index can therefore only ever exist inside a
`.staging-*` directory — which no reader can see (`snaputil.py:18`) and
which the next run deletes (§5.5).

---

## 5. Concurrency and crash safety

### 5.1 Writers vs writers — one lock, fail-fast

All mutating operations (`run`, `prune`, index re-derivation) hold
`flock(LOCK_EX)` on `<backup_root>/.backupctl.lock` (a plain file, opened
`O_CREAT|O_RDWR`, **never unlinked** — unlinking lock files races with
openers; flock on a stable inode does not).

- Scheduler-triggered run finding the lock held: exits immediately with
  code 2 and report line "skipped: a run is in progress" — the backup
  cadence loses one slot, never doubles up.
- Human run: `backupctl run --wait [--timeout S]` polls at 1 s.
- flock is advisory; the contract is that every writer ships in this repo
  (`backupctl` itself) and honors it. Restore is a reader and does not
  take this lock (§5.3).

### 5.2 Publish is one atomic rename

A run writes everything into `.staging-*` and publishes with a single
same-FS `os.rename` followed by an `fsync` of `backup_root`. POSIX rename
atomicity gives the exact reader guarantee the brief demands: any reader
at any instant sees either **no snapshot at that name** or **the complete
snapshot** — never a mix of this run's and the previous run's files, never
a snapshot without its index. There is no window in which a snapshot
exists but is incomplete, and no reader-side "is it finished?" check is
needed or possible — finish state is unobservable by construction.

Why staging names are safe against every existing reader path: both
`list_snapshots` (`snaputil.py:18`) and hence `prune_snapshots`'s
selection (`snaputil.py:30`) match only `snap-*`; `.staging-*` matches
neither.

### 5.3 Readers vs prune — flock on the snapshot directory

Published snapshots are immutable (§2), so reads need no coordination with
*writers*. The only dangerous counterpart is **prune**, which deletes whole
old snapshots. Protocol (flock on the snapshot *directory* fd — no lock
files inside snapshots, preserving immutability):

- **Reader (restore, any tool reading a snapshot)**: `fd =
  os.open(snap_dir, O_RDONLY)`; `flock(fd, LOCK_SH)`; then re-`stat` the
  *path* — if it is gone (ENOENT), prune won the race: close and fall
  forward to a newer snapshot (the newest `keep` are never doomed, §8, so
  a usable snapshot always exists). All file access goes through
  `snaputil.safe_snapshot_path` (`snaputil.py:54-63`), whose `..`
  normalization (lines 58-62) keeps a malicious/corrupt index relpath
  inside the snapshot. POSIX gives a second layer of defense: files
  already open survive `rmtree`'s unlink.
- **Prune**: for each doomed name, `fd = os.open(snap_dir, O_RDONLY)`;
  `flock(fd, LOCK_EX | LOCK_NB)`; on `EWOULDBLOCK` a reader holds it —
  **skip this snapshot this cycle** (deletion deferred to a later run; the
  report says "deferred: <name> (reader active)"). On success, `rmtree`,
  close. This is the guarded replacement for `snaputil.prune_snapshots`'s
  unconditional `shutil.rmtree` loop (`snaputil.py:34-35`, override O5).
  Order matters: lock **before** rmtree, so a reader that gets `LOCK_SH`
  first is never deleted under; a reader that blocks on `LOCK_SH` while
  prune holds `LOCK_EX` finds the path gone on its post-lock stat and
  falls forward.

### 5.4 Prune runs only after a successful publish

Retention executes at step 9, only when this run published a snapshot. A
run that fails anywhere before step 8 leaves the existing snapshot set
untouched — deletion can never be the reason there is no usable snapshot.
Combined with `keep >= 1` and `prune_snapshots`'s selection semantics
(newest never doomed — the slice at `snaputil.py:33` removes only from the
old end), at every instant at least the newest published snapshot exists
and is readable.

### 5.5 Crash recovery — what a dead run leaves, and what the next run does

The process can die at any instruction. Enumeration of death points and
their residue:

| Death point | Residue | Next run's recovery (step 3/4) | Report line |
|---|---|---|---|
| During steps 1-5 (before any file written) | nothing, or an empty `.staging-*` dir | rmtree the staging dir | `discarded staging .staging-PID-T (incomplete run)` |
| During step 6 (copying/linking) | `.staging-*` with a partial tree, **no index** | rmtree the staging dir; nothing else — no published artifact references it | same |
| During step 7 (index write) | `.staging-*` with complete tree + **half-written index** (`index.json.tmp`, or `index.json` mid-`os.replace`) | rmtree the staging dir. The half-written index is *discarded*, never parsed, never repaired — re-derivation is unnecessary because the snapshot was never published and nothing could have read it | same, with `half-written index discarded` |
| Between step 7 and step 8 (before rename) | `.staging-*` fully complete | rmtree it (it is indistinguishable from, and treated exactly like, the partial case — the run is re-done from scratch; hardlinks make the redo cheap, §7.2) | same |
| During step 8 (rename itself) | none — rename is atomic | nothing | — |
| During step 9 (prune) | possibly a partially-`rmtree`'d **doomed** snapshot | the rmtree'd remnant is *not* GC'd blindly: it still matches `snap-*`, so `list_snapshots` sees it. Rule: at step 4, any listed snapshot whose `index.json` is missing or unparseable **and** which is not the newest is treated as prune-residue: prune is retried on it (§8). If it is the newest, apply the re-derivation below. | `prune residue <name>: deletion retried` |

**Corrupt index on a *published* snapshot** (the case the brief calls out
explicitly — detected at step 4 when the newest snapshot is chosen as
baseline, or by restore/list): since §4.3+§5.2 make a half-written index
impossible in a published snapshot, a corrupt published index means
post-publish damage (disk corruption, external tampering). Recovery, under
the writer lock:

1. **Re-derive from the tree**: walk the snapshot directory (same traversal
   as `synccli.scan_files`, `synccli.py:10-19`, rooted at the snapshot),
   stat every file, and rebuild `index.json` as `{rel: {"size":
   st.st_size}}` with `"rederived": true`. The file *list* — what readers
   and restore need — is fully recoverable because the tree is the ground
   truth. The original source `(size, mtime)` states are **not**
   recoverable (the snapshot files' own mtimes are copy times, not source
   mtimes).
2. **Consequence, stated**: a `rederived` baseline cannot feed
   `changed_files` meaningfully, so the run whose baseline was re-derived
   degrades to a **full copy** (every file treated as changed). One
   full-copy run is the price of the repair; correctness is unaffected.
3. **Rewrite** the index atomically (step-7 procedure) — the single
   documented post-publish write (§2).
4. **Report**: `index of <name> was corrupt; re-derived from tree (K
   files); baseline reset -> full copy this run`.

What is *never* done: parsing or trusting an index found inside a
`.staging-*` directory (always discarded whole), and "repairing" a
snapshot's *content* files (immutability — a content-damaged snapshot is
left alone; retention ages it out, and the report of the run that detects
it via baseline mismatch notes nothing — content damage outside the index
is out of scope for this tool, checksums are future work, §13).

### 5.6 Guarantees matrix (brief requirement -> mechanism)

| Requirement | Mechanism |
|---|---|
| Two runs collide | Single writer lock, fail-fast/`--wait` (§5.1) |
| Restore reads while a run writes | New snapshot invisible until atomic rename (§4.2, §5.2); old snapshots immutable (§2); prune vs reader flock (§5.3) |
| Reader never sees mixed/incomplete snapshot | Staging invisibility + atomic publish + index-inside-staging-before-rename (§4.3, §5.2) |
| Index never promises absent files | Index built from copy outcomes (O4, §4.3) |
| Process dies at any point | Residue enumeration + step-3 GC + recovery table (§5.5); next run needs no manual cleanup |
| Corrupt/half-written index | Discard-in-staging vs re-derive-if-published, baseline reset reported (§5.5) |
| Deletion never leaves user empty-handed | Prune only post-publish, `keep>=1`, newest never doomed (§5.4, §8) |
| Deletion safe vs active reader | Per-snapshot flock, defer-on-busy (§5.3) |

---

## 6. Vanishing and unreadable source files

### 6.1 Behavior (identical for scheduler and human runs)

A source file can fail at three points; each is handled by the same
per-file handler, and none aborts the run:

| Failure point | Symptom | Handling | Index | Report |
|---|---|---|---|---|
| Gone between listing and stat | `build_source_manifest`'s wrapped `file_state` raises (O3 wraps `synccli.py:24`'s `os.stat`) | drop entry | no entry | `skipped: <rel> (vanished before stat)` |
| Gone between stat and copy | `copy_one` open raises `FileNotFoundError` (O1 removes the swallow at `synccli.py:68-69`) | continue | no entry | `skipped: <rel> (vanished before copy)` |
| Unreadable at copy (permissions, I/O error) | `copy_one` raises `OSError` | continue | no entry | `skipped: <rel> (unreadable: <errno>)` |

The snapshot then contains exactly the files whose copy or link succeeded
— the index matches the tree by construction (§4.3) — and the run
*reports* every omission in `report.json` and on stderr. There is no
scheduler/human branch anywhere in this path: one code path, one behavior,
one report format; only the lock-contention *exit* differs (§5.1), not
skip handling.

A partially copied file (failure mid-`copyfileobj`, e.g. ENOSPC or EIO on
read) is removed from staging before continuing, so no torn file can enter
the snapshot; it is reported as skipped like the others. ENOSPC on the
backup root is escalated: the run aborts, staging is discarded (it will be
GC'd even if the abort itself is killed), exit 1 — a snapshot missing an
unbounded fraction of the tree is not published.

### 6.2 Files modified *during* the run

The index records the state captured at scan time (step 6a, pre-copy). If
a file changes between scan and copy, the snapshot may hold newer bytes
than the recorded state — the mismatch is **self-healing**: next run,
`synccli.changed_files` (`synccli.py:36-42`) compares the fresh scan
against the older recorded state, sees a difference, and re-copies. The
error direction is deliberate: a changed file is never marked unchanged;
the worst case is one snapshot with torn bytes for that one file, fixed by
the next run, and the file is listed in the report only if the copy itself
failed.

### 6.3 Report

`report.json` (written into the snapshot at step 7, so it is published
atomically with it) plus a stderr summary:

```json
{
  "started": "...", "finished": "...", "duration_s": 12.4,
  "baseline": "snap-20261116-093000-01",
  "recovery": {"discarded_staging": [".staging-4312-091501"],
                "rederived_indexes": [], "prune_residue_retried": []},
  "dirs": {"<name>": {"copied": 480, "linked": 29500,
                       "gone_from_source": ["old.out"],
                       "skipped": [{"path": "r/x.tmp",
                                    "reason": "vanished before copy"}]}},
  "pruned": ["snap-20261101-093000-01"],
  "prune_deferred": ["snap-20261102-093000-01"]
}
```

`gone_from_source` is the `synccli.collect_stale` output of step 6d
(`synccli.py:45-59`) — informational: those files are simply absent from
this snapshot, as a point-in-time image demands.

### 6.4 Exit codes

`0` = snapshot published (skips possible; they are in the report — a
published snapshot with skips is a success, the report is where skips
live). `1` = fatal, no snapshot published (config invalid, ENOSPC,
backup_root unwritable). `2` = skipped run, lock held (§5.1). Identical
for both trigger kinds; a scheduler keys off `0`/`2`, a human reads the
report.

---

## 7. Change detection

### 7.1 Granularity — stated explicitly

"Unchanged" is decided **per file**, on the pair
`(st_size, st_mtime)` — exactly `synccli.file_state` (`synccli.py:22-25`) —
compared against the baseline snapshot's index section via
`synccli.changed_files` (`synccli.py:36-42`): a file is unchanged iff it
exists in both and both fields are equal.

### 7.2 What unchanged files cost: hardlinks, not copies

For each unchanged file the run executes one `os.link` from the baseline
snapshot's copy (`snaputil.safe_snapshot_path`-resolved, `snaputil.py:54-63`)
into staging — zero data bytes moved, one syscall (~0.31 ms measured, §9).
Changed and new files are copied (O1/O2 `copy_one`). Deleted files are
neither linked nor copied — they simply do not exist in the new snapshot.
This is the Time-Machine/rsync-`--link-dest` model: every snapshot is a
complete directory tree, physically sharing unchanged inodes with its
predecessor. The immutability invariant (§2) is what makes sharing safe:
nothing ever writes through a hardlink. Retention deletion via `rmtree`
unlinks one name; the inode survives while any other snapshot references
it — no coordination between snapshots is needed. Hardlinks require one
filesystem: baseline and staging are both under `backup_root` by
construction (§2), so this always holds (the *source* may live anywhere —
it is only read).

### 7.3 What this granularity can miss — stated explicitly

`(size, mtime)` equality does **not** imply byte equality. The design
accepts, and documents, these misses:

1. **Content rewritten with identical size and restored/preserved mtime**
   (e.g. `touch -r`, editors or rsync with `--times`, an in-place
   same-length edit): missed entirely; the stale copy persists in new
   snapshots until size or mtime moves. Detection would require content
   hashing (cost: reading every file every run — ~1 GB/run at 4.2 GB/s ≈
   0.25 s/GB measured bandwidth, but defeats the point of not touching
   unchanged data; deferred to future work, §13, as an opt-in
   `--verify-hashes` mode).
2. **Clock skew / mtime going backwards**: a file whose mtime is set to an
   *older* value with the same size reads as unchanged (same miss as 1);
   a differing mtime with identical content reads as *changed* — a false
   positive, costing one redundant copy, never correctness.
3. **Sub-second mtime precision**: `file_state` stores `st_mtime` as a
   float (`synccli.py:25`); filesystems with coarser precision than the
   float comparison implies can alias two writes within one tick at equal
   size — same miss as 1.
4. **Mode/ownership/xattr/symlink changes**: not part of the state at all
   (`file_state` records only size+mtime); a `chmod` alone never triggers
   a re-copy. Snapshot copies store bytes and the directory structure,
   not metadata — stated as a scope limit.
5. Inherited from `synccli.scan_files` (`synccli.py:14`): **dot-directories
   inside a configured source are never enumerated** (`.git`, `.cache`,
   ...), so they are never backed up. This is reused deliberately (evals
   result dirs follow the same convention as `synccli`'s test trees); a
   configured dir whose *own* name starts with `.` still works (the filter
   applies to children only). If evals ever needs hidden subdirs, the
   override point is named: the filter list comprehension at
   `synccli.py:14`.

---

## 8. Retention policy

**Policy** (config-driven): keep the newest `keep` snapshots (default
`keep = 10`, validated `>= 1`), *and* never delete a snapshot younger than
`min_age_hours` (default 24 h). Age is parsed from the snapshot name's
embedded timestamp (`snap-YYYYMMDD-HHMMSS-NN`, the format documented at
`snaputil.py:11-13`) — not from directory mtime; this is override O7
(`snaputil.is_stale`, `snaputil.py:66-73`, rejected because published-dir
mtime is mutated by index re-derivation, §5.5).

**Selection**: `names = snaputil.list_snapshots(backup_root)` (oldest
first, `snaputil.py:20`); `doomed = names[:len(names) - keep]` — the same
slice `snaputil.prune_snapshots` uses (`snaputil.py:33`), then filtered by
the min-age floor. Because the slice only ever takes from the old end, the
newest `keep` — including the snapshot this run just published — are never
doomed (the guarantee `snaputil.py:26-28` states, preserved).

**Deletion**: the flock-guarded loop of §5.3 (override O5), each name
locked `LOCK_EX|LOCK_NB` before `rmtree`, deferred-on-busy. A partially
deleted snapshot found by a later run is handled by the §5.5 prune-residue
rule.

**Never-without-a-snapshot argument**: prune runs only after a successful
publish (§5.4); `keep >= 1`; newest never doomed; therefore at all times
the set of published snapshots is non-empty and its newest member is
complete (§5.2) and readable (§5.3 fall-forward guarantees a reader always
ends at a surviving snapshot).

**Manual**: `backupctl prune [--keep K]` runs the identical guarded path
under the writer lock, independent of a run.

---

## 9. Performance budget for the initial full backup

### 9.1 Measured primitives (this machine; harness in Appendix A)

| Primitive | Measured rate | Basis |
|---|---|---|
| `build_manifest` (walk + stat + dict, `synccli.py:28-33`) | **43,000 files/s** (cold 43,360; warm 43,279 — cache-insensitive) | 10,000-file tree, 50 dirs |
| `copy_file`-style copy, small file (open/read/write/close + `makedirs`, `synccli.py:62-67`) | **227 µs/file** (4,411 files/s) | 10,000 × 100 B |
| Bulk copy bandwidth, large file (`synccli.copy_file`) | **4,200 MB/s** (cold 4,174 / warm 4,228 — APFS, page-cache assisted) | 4 × 128 MB |
| `os.link` into pre-created dirs | **3,190 links/s** (0.31 ms/link) | 10,000 links |
| Manifest memory | **341 B/entry** (deep `sys.getsizeof`, `{rel: {size, mtime}}`) | 30,000 entries |
| `index.json` size (`json.dumps(indent=2)` — the `synccli.py:86` format) | **78 B/entry** (2.34 MB per 30k entries) | 30,000 entries |

### 9.2 Derivation for the brief's workload: ~1 GB, ~30,000 files (avg ≈ 34 KB)

Initial full backup (no baseline; every file copied):

```
scan:    30,000 files / 43,000 files/s            =  0.70 s
copy:    30,000 × 227 µs   (per-file overhead)    =  6.81 s
bytes:   1,024 MB / 4,200 MB/s                    =  0.24 s   (avg file 34 KB
                                                              rides inside the
                                                              per-file overhead)
index:   2.34 MB json.dump + fsync                ≈  0.15 s
rename + fsyncs                                   ≈  0.01 s
                                                   -------
measured-basis total                              ≈  7.9 s
```

**Budget: the initial full backup of one ~1 GB / 30k-file tree completes in
≤ 32 s** — the 7.9 s derivation with a ×4 headroom factor covering cold
page cache on real (non-benchmark) trees, fsync latency on busy disks,
JSON serialization variance, and slower-than-benchmark storage. The number
is a derivation from the four measured constants above, not a guess; each
constant is reproducible with Appendix A.

Steady-state run, same tree, C files changed since baseline:

```
scan 0.70 s + link (30,000 − C)/3,190 s + copy C × 227 µs + changed bytes/4,200 MB/s
C = 0    -> ≈ 10.1 s  (budget ≤ 30 s, ×3 headroom)
C = 500  -> ≈ 10.1 s  (link term dominates; copy adds 0.11 s + bytes)
```

The ~9.4 s hardlink pass is the steady-state floor for 30k files; it buys
per-snapshot complete trees at zero byte cost (§7.2) and fits any sane
backup cadence (minutes+).

---

## 10. Scaling: what grows with what, with explicit bounds

Let **N** = configured directories, **F** = total files across them, **S**
= total source bytes, **C** = files changed per run, **Δ** = bytes changed
per run, **K** = `keep`, **M** = number of published snapshots (≤ K plus
any protected by `min_age_hours`).

**Per-run work (time)** — grows linearly in F and Δ, flat in N per-file:
`T_run = F/43,000 s + (F−C)/3,190 s + C×227 µs + Δ/4,200 MB/s + O(N)` —
the O(N) term is per-dir constants only (manifest section, skeleton
pass); measured constants from §9.1. Examples: N=3, F=90k, C=0 → ≈ 30 s;
N=30, F=900k, C=0 → ≈ 296 s ≈ 5 min; both stated as formulas, not vibes.

**Per-run memory (peak RSS of the run)** — grows linearly in F, flat in
everything else:
`M_run ≤ 341 B × F (manifest, measured) + 78 B × F (index JSON string,
measured) + 16 MiB (copy buffer, O2) + O(N)`. Numbers: F=90k → ≈ 38 MB;
F=1M → ≈ 420 MB. The 16 MiB buffer replaces `synccli.copy_file`'s
whole-file `fsrc.read()` (`synccli.py:67`, override O2), which would make
the bound `max single file size` instead of a constant. If F ever makes
420 MB unacceptable, the named mitigation is per-dir streaming of the
index (write section-by-section) — interface stays, format stays.

**Disk** — first run: S. Each later run adds **Δ + (F−C)×E_dir**, where
E_dir is per-file directory-entry/inode overhead of a hardlink (no data
blocks shared inode); conservative constant **E_dir ≤ 200 B/file**
(estimate with headroom, not a §9 measurement — flagged as such). Total:
`D ≤ S + (M−1)×Δ_avg + M×F×200 B`, and with retention binding (M ≤ K +
min-age survivors): `D ≤ S + (K−1)×Δ_avg + (K+1)×F×200 B`. Worked:
S=3 GB, Δ=50 MB/run, K=10, F=90k → ≤ 3 GB + 450 MB + 20 MB ≈ **3.5 GB**.
Without retention, D grows without bound — that is precisely the growth
`keep`/`min_age_hours` bound (§8).

**Flat in N and F** (explicit): lock acquisition (1 flock), staging GC
(O(stale staging dirs), typically 0-1), baseline selection (1
`list_snapshots` = one `scandir` of backup_root, O(M) names, M ≤ K+1 in
steady state), publish (1 rename + fsyncs), report (O(N) lines, not O(F)
— skipped lists are the only O(F)-shaped report field and are O(skips)).

**Snapshot count / backup_root entries**: ≤ K + min-age survivors +
staging (≤ 1 per run, GC'd next run) + 1 lock file. Bounded by config,
never grows unboundedly.

---

## 11. CLI surface

```
backupctl run [--config backupctl.json] [--wait] [--timeout S] [--dry-run]
backupctl list [--config ...]           # snaputil.list_snapshots +
                                        # snapshot_disk_usage (logical, O6)
                                        # + unique_size (st_nlink==1)
backupctl prune [--keep K] [--config ...]
```

`run` follows `synccli.main`'s argparse shape (`synccli.py:90-99`) and
prints the report summary; `list` mirrors `snaputil.main`'s output style
(`snaputil.py:76-88`: name + size per line) extended with unique size and
the `rederived` flag. Exit codes per §6.4 (`list`/`prune`: 0 ok, 1 fatal).

**Restore contract** (restore itself is separate tooling per the brief;
this design fixes what it may rely on): resolve candidates via
`snaputil.list_snapshots` (newest first = reversed list), for each: open
dir fd + `flock(LOCK_SH)` + post-lock path stat (§5.3), parse
`index.json`, map every relpath through `snaputil.safe_snapshot_path`
(`snaputil.py:54-63`), copy out, release. A snapshot with `rederived:
true` or any listed snapshot missing its index is still readable via the
re-derived/tree-walk file list (§5.5) — readers never depend on the
source-mtime states, only on the file list.

---

## 12. Test plan (`test_backupctl.py`, `unittest` + `tempfile` per `test_synccli.py:8-15`)

1. **First run publishes**: run on a 3-file tree → `list_snapshots` shows
   one `snap-*`; index `files` == tree; report `copied == 3`.
2. **Second run links**: touch one file → run → report `copied == 1`,
   `linked == 2`; unchanged files' `st_nlink == 2` and
   `os.stat(...).st_ino` equal across the two snapshots.
3. **Vanished file**: delete a source file between `scan_files` and the
   copy pass (monkeypatch `copy_one` to unlink first) → snapshot lacks it,
   index lacks it, report lists it `skipped(vanished)`; identical
   assertions for an unreadable file (`chmod 000`) → `skipped(unreadable)`.
4. **Scheduler/human parity**: runs 3 under lock-held vs not, exit codes
   2 vs 0, same `skipped` report content.
5. **Crash GC**: create a fake `.staging-*` with a half-written
   `index.json.tmp`; run → staging gone, report `discarded_staging`,
   snapshot published normally.
6. **Corrupt published index**: corrupt newest snapshot's `index.json` →
   run → index re-derived (`rederived: true`, file list == tree), report
   notes baseline reset, run was a full copy (`copied == F`).
7. **Concurrency**: hold the writer lock in-process (flock in the test) →
   `run` exits 2 without touching the root; `--wait --timeout 1` exits 2
   after waiting.
8. **Prune guard**: hold `LOCK_SH` on the oldest snapshot dir → prune
   deletes nothing, reports `prune_deferred`; release → prune deletes it;
   newest snapshot survives every prune (`keep>=1`, mirrors
   `snaputil.py:26-28`).
9. **Retention floor**: snapshots named with old/new timestamps → min-age
   protects the young ones even beyond `keep`.
10. **Prune residue**: an index-less `snap-*` that is not newest →
    deletion retried and completed by the next run.
11. **Basename collision config** rejected at startup (exit 1).
12. **Safe paths**: index containing `../../evil` → restore-contract
    mapping stays inside the snapshot (property already guaranteed by
    `snaputil.py:58-62`; test pins the integration).

Existing suite stays green: `backupctl` adds modules and does not modify
`synccli.py`/`snaputil.py` (overrides O1-O6 are wrappers/new functions in
`backupctl`, not edits — `snaputil`'s CLI behavior is untouched).

---

## 13. Future work (explicitly out of scope here)

- Opt-in `--verify-hashes` (sha256 in the index) to close the §7.3 misses
  1-3; cost bounded by the measured 4,200 MB/s read bandwidth (~0.25 s/GB).
- Checksums for content-damage detection in published snapshots (§5.5
  scope limit).
- Per-dir streaming index writes if F reaches ~1M (§10 memory bound).
- `clonefile` on APFS as an alternative to copy for *changed* files
  (near-zero-cost COW copies); rejected for *unchanged* files because COW
  clones report full size per snapshot, breaking the §10 disk formula's
  honest accounting; hardlinks give true sharing.

---

## Appendix A — measurement harness

Benchmarks run 2026-11-17 on this machine (macOS 15.8.1, Apple M3 Max,
38 GB, APFS on `/System/Volumes/Data`, Python 3.10.11) against the
`synccli.py`/`snaputil.py` checked into this directory. Harness (temp-dir
based, repo untouched):

1. Tree: 10,000 × 100 B files across 50 dirs; `synccli.build_manifest`
   timed cold and warm → 43,360 / 43,279 files/s.
2. `synccli.copy_file` over the same 10,000 files → 226.7 µs/file.
3. `synccli.copy_file` of 4 × 128 MB → 4,174 MB/s cold, 4,228 MB/s warm.
4. `os.link` × 10,000 into pre-created dirs (≤ 50 entries/dir) → 3,190
   links/s; with per-file `os.makedirs(exist_ok=True)` instead → 2,565/s
   (hence the step-6e skeleton pass).
5. Deep `sys.getsizeof` of a 30k-entry `{rel: {size, mtime}}` dict →
   340.7 B/entry; `json.dumps(indent=2)` of the same → 2,340,002 B
   (78 B/entry).
6. `python3 -m unittest` in this directory: 6 tests, OK (pre-existing
   suite, run before and accounted unchanged by this design).

Budget derivation §9.2 combines these constants arithmetically for the
brief's 1 GB / ~30k-file workload and applies the stated headroom factors.

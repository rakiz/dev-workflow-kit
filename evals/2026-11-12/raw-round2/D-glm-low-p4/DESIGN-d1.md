# DESIGN-d1 — `backupctl`

Design for a command-line backup tool covering the configured eval result
directories, producing snapshots under a backup root. Built on the code in
this directory: `synccli.py` (scan / manifest / change detection / copy) and
`snaputil.py` (snapshot listing, pruning, sizes, path safety).

---

## 1. Layout and reuse

```
backup_root/
  .backup.lock                  # flock file, run mutual exclusion
  snap-20261112-150000-07/      # completed snapshot (name format matches snaputil.list_snapshots)
  snap-20261113-090000-08/
  .inprogress-<epoch>-<pid>/    # run in flight; never visible as a snapshot
  .trash-<epoch>-<name>/        # snapshot being deleted
```

A run is one process over all N configured directories, producing **one
snapshot per directory per run** (snapshot per source, not one merged
snapshot — a restore restores one eval directory at a time).

What we reuse as-is, versus override:

| Existing artifact | Use |
|---|---|
| `synccli.scan_files` (`synccli.py:10`) | Reused for scanning a source tree. **Overridden behavior:** `scan_files` prunes every dot-directory (`synccli.py:14`) and never lists dot-files' directories with leading dots. For backup we must not silently drop dot-directories (eval trees contain `.venv`, `.git`, dotfiles). `backupctl` calls a thin wrapper that reuses the `os.walk` + sorted-relative-path shape of `scan_files` but removes the `dirnames[:]` dot filter; the only entries skipped are `.inprogress-*` / `.trash-*` under the *backup root*, which is never a scanned source. |
| `synccli.file_state` (`synccli.py:22`) | Reused unchanged for change detection state `(size, mtime)`. |
| `synccli.build_manifest` (`synccli.py:28`) | Reused unchanged; it composes `scan_files` + `file_state`. Because of the `scan_files` override above, `backupctl` calls `build_manifest` with the wrapper scanner (same `{relpath: {size, mtime}}` dict shape). |
| `synccli.changed_files` (`synccli.py:36`) | Reused unchanged to diff the previous snapshot's manifest against the new one. |
| `synccli.copy_file` (`synccli.py:62`) | **Overridden.** Its `except OSError: pass` (`synccli.py:68–69`) silently swallows vanished/unreadable sources. `backupctl` needs the failure recorded, not hidden — see §5. The copy loop shape (`os.makedirs` parent + open/open + read/write) is kept. |
| `synccli.sync` (`synccli.py:72`) | **Overridden, not called.** `sync` syncs *in place* into a shared destination and rewrites `MANIFEST_NAME` after copying (`synccli.py:85–86`): it has no snapshot isolation, no atomic publication, and a crash mid-copy leaves a mixed tree whose manifest still claims completeness. `backupctl` keeps its *sequence* (build manifest → diff → copy changed → write manifest) but retargets each step at an immutable, atomically published snapshot directory (§3). |
| `snaputil.list_snapshots` (`snaputil.py:8`) | Reused unchanged. Its `snap-`-prefix + directory filter (`snaputil.py:18`) is the load-bearing choice: `.inprogress-*` and `.trash-*` directories are invisible to every snapshot reader by construction. Names sort oldest-first because of the `snap-YYYYMMDD-HHMMSS-seq` format it documents. |
| `snaputil.prune_snapshots` (`snaputil.py:23`) | Reused for *which* snapshots die (all but the newest `keep`, oldest first — it already guarantees the newest snapshot survives). **Overridden** for *how* they die: it calls `shutil.rmtree` directly (`snaputil.py:35`), which can rip a directory out from under a concurrent reader. `backupctl` renames first, deletes after a grace period (§6). |
| `snaputil.snapshot_disk_usage` (`snaputil.py:39`) | Reused unchanged for `backupctl status` reporting. |
| `snaputil.safe_snapshot_path` (`snaputil.py:54`) | Reused unchanged by restore to map manifest relpaths back under a snapshot (it normalizes `..` away, so a hostile/corrupt manifest cannot escape the snapshot). |
| `snaputil.is_stale` (`snaputil.py:66`) | Reused by the trash sweeper to decide whether a `.trash-*` directory has outlived its grace period (compares directory mtime against a captured reference epoch). |

`backupctl` is a new module `backupctl.py` in this directory, plus a
`config` file (TOML) listing `sources = [...]`, `backup_root = ...`,
`keep = 24`.

---

## 2. Concurrency: who may run at the same time

| | Run A (write) | Run B (write) | Restore / reader |
|---|---|---|---|
| Run A | — | serialized | concurrent, safe |
| Restore | concurrent, safe | — | — |

**Run ↔ run:** an exclusive `flock` on `<backup_root>/.backup.lock` for the
whole run (scheduler-triggered and person-triggered runs are the same
process; second arrival blocks with a warning, `--wait`/`--no-wait` flags).
This is a single lock over the backup root, not per directory — with N in
the tens, per-directory locks buy nothing and per-run work is serial anyway
(§8).

**Reader ↔ writer:** readers never take the lock and never observe a partial
snapshot, because a snapshot becomes visible as one indivisible rename:

1. All writing happens in `.inprogress-<epoch>-<pid>/`.
2. The manifest is written and fsynced inside it.
3. `os.rename` publishes `.inprogress-…` → `snap-YYYYMMDD-HHMMSS-seq/`.

A reader either does not see the directory at all (`list_snapshots`
`snaputil.py:18` filters the `.inprogress-` prefix out) or sees it complete.
There is no intermediate state. Restore, humans, and the next run can read
any published snapshot while any number of runs are in flight (a run only
ever *writes* its own `.inprogress-*` and reads older snapshots' files for
hardlinking — read-only on them).

**Reader ↔ deleter:** §6.

## 3. Atomicity and crash recovery

**Publication rule:** a snapshot directory under its final `snap-` name is
immutable and complete, always. Completeness is defined as: every file in
the manifest exists in the tree, and the manifest is the last thing written
before the publish rename. The index can therefore never promise files the
snapshot lacks (the brief's "never a mix" requirement) — the manifest is
written *after* the copies it describes, inside the not-yet-visible
directory, and the directory is renamed once, atomically.

**Dead run:** a killed process leaves only a `.inprogress-<epoch>-<pid>/`
directory. Recovery is mechanical: at the start of every run, the lock
holder sweeps every `.inprogress-*` directory (any of them is garbage by the
publication rule — only the lock holder writes new ones, and the sweep runs
under the lock) and any `.trash-*` older than the grace period
(`snaputil.is_stale` with a freshly captured epoch). No manual cleanup, and
the next run makes full progress: nothing it needs lived in the dead run's
directory, because change detection is against the last *published*
snapshot's manifest, not the dead one.

**Corrupt index recovery.** A snapshot's manifest can still be corrupt on
disk (bit rot, partial fsync before the rename survived). When a run reads
the previous snapshot's manifest and `json.load` fails or the file is
missing:

- **Discarded:** nothing is deleted. The corrupt snapshot is left in place
  and is simply not used as a hardlink/manifest base.
- **Re-derived from the tree:** the run falls back to a *full copy* of the
  source into the new snapshot (no dedup against the corrupt base) and,
  additionally, regenerates the corrupt snapshot's index from its own tree
  with `build_manifest` applied to the snapshot directory, written with the
  same tmp+`os.replace` dance, so a repairable index is repaired.
- **Reported:** the run prints `WARN: index of <name> corrupt; rebuilt from
  tree; full copy performed`, and exits 0 (backup succeeded; the condition
  is degraded efficiency, not data loss).

**Ctrl-C (SIGINT):** same path as a kill, plus the process itself removes
its own `.inprogress-*` in a `finally` before releasing the lock.

## 4. Change detection and its granularity

Per directory:

1. `build_manifest(source)` (reusing `synccli.file_state`'s `(size, mtime)`).
2. Diff against the previous published snapshot's manifest with
   `synccli.changed_files`.
3. Unchanged → `os.link(prev_snapshot_file, new_snapshot_file)` — a hardlink,
   costing zero file bytes; the file is owned by every snapshot that links
   it and survives until the last snapshot referencing it is deleted, so
   retention deletion (§6) never orphans it.
4. Changed/new → real copy via the §5 `copy_one`.

Granularity: **file-level, decided by `(size, mtime)`** exactly as
`synccli.file_state` computes it. Edits this can miss:

- an edit that leaves both size and mtime unchanged (in-place same-length
  overwrite by a tool that restores the timestamp);
- an edit fully inside one mtime tick on filesystems with coarse (2 s FAT /
  1 s some-network) resolution;
- on macOS, ctime is not consulted, so a same-size touch-and-revert is
  invisible.

Accepted because the workload is generated eval output (files are written
once and then frozen), and the failure mode is a stale copy in the *next*
snapshot, never corruption of an existing one. The config exposes
`hash_check = ["<dir>"]` to promote a directory to content-hash (sha256,
stored in the manifest) change detection for any directory where this risk
matters.

## 5. Vanished / unreadable source files

`copy_one` (the replacement for `synccli.copy_file`, `synccli.py:62`) keeps
its parent-directory creation, but on `OSError` (ENOENT, EACCES, …) it
returns the relpath + errno instead of `pass`-ing. The run:

- **excludes** the file from the new manifest, so the index never promises a
  file the snapshot does not contain;
- still creates the parent directory tree (empty dirs are preserved);
- collects the failures and reports them uniformly at the end — the same
  report and exit code whether the run was started by the scheduler or a
  person: per-file `WARN: skipped <dir>: <rel>: <errno text>` on stderr,
  a `skipped` count in the summary line, exit code 0 if no files were
  skipped, exit code 3 if any were (the snapshot is still published and
  valid — it is a complete image of *what was readable*).

This is the one place where a run may legitimately differ from the source
tree; it is deterministic, identical across trigger sources, and visible in
the report. A subsequent run picks the file up normally once it is readable
again (it simply shows up as changed).

## 6. Retention

Policy: keep the newest `keep` snapshots (default 24) per backup root. A
user always retains at least the newest snapshot — with `keep ≥ 1`,
`prune_snapshots` (`snaputil.py:30–33`) never deletes it, so deletion can
never leave the user without a usable snapshot.

Deletion is two-phase to be safe against concurrent readers:

1. Under the run lock: rename `snap-…` → `.trash-<epoch>-<name>`. The
   rename is atomic; readers that already opened the snapshot (or opened
   files inside it) keep valid file handles — POSIX unlinked-open semantics
   — and readers that have *not yet* started see the snapshot vanish from
   `list_snapshots` in one step. A reader never traverses a half-deleted
   tree, because `rmtree` only ever runs on `.trash-*`.
2. `shutil.rmtree` on the `.trash-*` directory — but not immediately:
   `--grace-secs` (default 3600). The sweeper at the start of each run (§3)
   deletes `.trash-*` entries for which `snaputil.is_stale(trash_dir,
   now_epoch)` holds. Within the grace window a slow restore (path opened
   just before the rename) still resolves its paths; after it, the bytes are
   reclaimed.

Disk bound: `keep` snapshots × per-snapshot size. With hardlinking
(§4) a snapshot's *new* bytes are only its changed files, but deletion
accounting stays simple: a snapshot's files vanish when the last snapshot
linking them is pruned.

## 7. First full backup: performance budget

Budget: **≤ 5 minutes wall clock for the initial full backup of a ~1 GB /
~30,000-file tree; expected ~1–2 minutes.**

Derivation from a measurement on this machine (macOS, 4,000 × 256 KiB files
= 1,048,576,000 bytes copied with `shutil.copyfile`, warm cache):

- 1,048,576,000 bytes / 1.6 s = **654 MB/s**, 2,496 files/s.

Warm cache is the optimistic bound; a laptop SSD cold does roughly 5× worse
(~130 MB/s read+write), and the first backup is inherently cold-ish
(reading 1 GB the disk has not seen). Scaling the measurement:

- copy: 1 GB at 130 MB/s ≈ **8 s**; even at a pessimistic 20 MB/s (network
  home dir) ≈ 52 s.
- small-file overhead dominates: at the measured 2,496 files/s ÷ 5 ≈ 500
  files/s cold, 30,000 files ≈ **60 s**.
- scan/manifest (`build_manifest`): 30,000 `stat` calls ≈ 1–2 s.
- manifest write: one JSON file, ~30,000 entries × ~100 B ≈ 3 MB ≈ instant.

Sum worst case ≈ 60 s (files) + 8–52 s (bytes) + 2 s (scan) + overhead →
well under 5 minutes; the number above is that sum with 2–3× slack. The
tests and measurement can be re-run (`python3 -m unittest` passes on this
tree) to re-check the constants.

## 8. What grows with what (explicit bounds)

Let N = number of configured directories, F = total files across them,
B = total bytes, C = bytes changed since the previous run, K = keep.

- **Per-run work (incremental):** O(F) stat calls (full re-scan each run via
  `build_manifest`) + O(C) copy/link bytes + O(F) hardlink syscalls for
  unchanged files. Formula: `t ≈ F × (stat + link) + C / disk_MB_s`. With
  F = 30,000: ~1–2 s of stat/link at the measured rates. Growth with N is
  only through F and C — the run is one pass over all directories; N itself
  adds one lock acquisition and one config entry, i.e. O(1).
- **Memory:** the manifest dict per directory, ~150 B/entry → 30,000 files ≈
  **4.5 MB**, and only one directory's manifest pair is resident at a time
  (per-directory phase), so peak ≈ O(max directory's F) × 150 B, **not**
  O(F_total). Formally: peak ≈ 300 B × F_max.
- **Disk:** `≤ K × B_new + K × F × 100 B` where B_new is the bytes each
  snapshot newly adds (its changed files) and the second term is directory
  entries; unchanged files are shared hardlinks counted once, but conservatively
  a retention-worst-case of `K × B` if every file changed every run. Formula:
  `disk ≤ K × B` (upper bound), `disk ≈ B + (K−1) × C_avg` (steady state).
- **Stays flat:** the lock file (1 file), the number of open file descriptors
  during a run (O(1): two per copy, sequential), the run report size
  (O(1) summary + O(skipped) lines).
- **Grows with N:** run wall time linearly through F and C; the number of
  published snapshots per run is exactly N (formula: N snapshots/run);
  restore time is independent of N (per-directory).

## 9. CLI

```
backupctl run [--wait|--no-wait] [--config path]     # backup all configured dirs
backupctl restore <snapshot> <src-subdir> <dest>     # read-only; uses snaputil.safe_snapshot_path
backupctl status                                     # list_snapshots + snapshot_disk_usage + last-run report
backupctl prune [--keep K]                           # retention without a run (takes the lock)
```

Exit codes: 0 ok · 1 lock contention (`--no-wait`) · 2 usage/config error ·
3 run completed with skipped files (§5).

## 10. Testing

New `test_backupctl.py` alongside `test_synccli.py`, same
`unittest` style: concurrent run serialized by lock; reader mid-run sees no
partial snapshot (publish-rename asserted); killed-run sweep (create fake
`.inprogress-*`, run, assert gone); corrupt-index recovery path (truncate a
manifest, run, assert WARN + rebuilt index + full copy); vanished source
file (delete between listing and copy hook, assert exit 3 + manifest omits
it); retention two-phase (assert `.trash-*` rename and grace); hardlink
dedup (assert `st_nlink > 1` and equal inodes for unchanged files).

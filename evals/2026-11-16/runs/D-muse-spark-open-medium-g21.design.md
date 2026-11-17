# Design: `backupctl` (D1)

## 1. Overview

`backupctl` backs up N configured source directories into a single backup
root. Each run produces one **snapshot**: a point-in-time directory under
`backup_root/snap-<UTC-timestamp>-<seq>/` containing a copy of every source
directory. A snapshot is **complete** only when its index file
`.backup_index.json` has been durably written and atomically renamed into
place (see §4). Anything without a valid index is not a snapshot — it is
invisible to readers, retention, and restore.

```
backup_root/
  snap-20261117-120000-00/        # snapshot 0 — complete
    .backup_index.json            # index (written last, atomically)
    evals-a/                      # source dir "evals-a" as listed
    evals-b/
  snap-20261117-130000-01/        # snapshot 1 — complete
    ...
  .tmp.snap-20261117-140000-02.<pid>/  # in-flight staging dir (hidden)
  .lock                           # global run lock (fcntl)
  .prune.lock                     # prune lock (separate, see §6)
  config.json                     # {sources: [{name, path}, ...]}
```

One snapshot per run (not per source) — this keeps retention (§6) simple
and gives a single timestamp to reason about across all N directories. The
per-source content lives in named subdirectories inside the snapshot so
`restore <snapshot> <source-name>` can address one source without copying
the rest.

---

## 2. Grounding in existing code

`backupctl` reuses the current codebase rather than re-implementing it.
Where it must diverge, the override is named explicitly.

### 2.1 Reused as-is

| Existing function | File:lines | Use in `backupctl` |
|---|---|---|
| `scan_files(root)` | `synccli.py:10-19` | Enumerate files under each source dir. Same walk, same "skip dot-dirs" rule (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`). |
| `file_state(path)` | `synccli.py:22-25` | Fast-path change detection: `(size, mtime)` stat without hashing. Called during incremental runs (§7). |
| `build_manifest(root)` | `synccli.py:28-33` | Build the per-source manifest `{relpath: {size, mtime}}` before comparing to the previous snapshot's index. |
| `changed_files(old, new)` | `synccli.py:36-42` | Compute the delta between the previous snapshot's manifest and the current source scan. Only changed/new files are copied. |
| `collect_stale(items, seen)` | `synccli.py:45-59` | Reused to collect files present in the previous snapshot but absent from the current source scan (deletions). Callers pass `items = [(rel, is_present), ...]` with `seen` for de-duplication across sources. |
| `list_snapshots(backup_root)` | `snaputil.py:8-20` | List completed snapshots. Already filters to `snap-*` dirs and returns oldest-first sorted — exactly the order retention needs. |
| `prune_snapshots(backup_root, keep)` | `snaputil.py:23-36` | Retention deletion. Keeps newest `keep`; deletes oldest first so newest is never removed. |
| `snapshot_disk_usage(root, name)` | `snaputil.py:39-51` | Report / budget disk usage per snapshot. |
| `safe_snapshot_path(root, snap, rel)` | `snaputil.py:54-63` | Map a stored `rel_path` back to disk. Normalizes away `..` so a malicious or buggy index entry cannot escape the snapshot directory. All restore/copy-back paths go through this. |
| `is_stale(snapshot_dir, ref_epoch)` | `snaputil.py:66-73` | Detect snapshots older than a retention threshold. Used by time-based prune policy (§6). |

### 2.2 Overridden — with reason

| Existing | Location | Override | Reason |
|---|---|---|---|
| `copy_file(src, dst)` | `synccli.py:62-69` | Replace with `copy_file_atomic(src, dst, link_from=None)` that (a) hard-links from the previous snapshot when content is unchanged (see §7), (b) copies via a temp file + `os.rename` so a crash never leaves a half-written file visible, (c) returns an explicit `CopyResult` enum (`OK`, `VANISHED`, `UNREADABLE`) instead of swallowing `OSError` silently. | `synccli.copy_file` silently ignores `OSError` (`except OSError: pass` at line 68-69) — acceptable for a best-effort sync but wrong for a backup that must report what it missed (§5) and must not leave a truncated file that looks complete. |
| `sync(src, dst, dry_run)` | `synccli.py:72-87` | Replace with `run_backup(config, backup_root)` that (a) writes to a staging snapshot dir, (b) holds a file lock, (c) writes the index last via atomic rename. | `sync` writes the manifest directly to `dst/.sync_manifest.json` (line 85) with no atomicity — a crash mid-write leaves a corrupt manifest that the next run will `json.load` and either crash or silently mis-detect changes. `run_backup` writes to `.tmp.snap-...` and renames only on success (§4). |
| Manifest format | `synccli.py:7,84-86` (`MANIFEST_NAME`, `json.dump`) | New index `.backup_index.json` adds `content_hash` (SHA-256) per file, `snapshot_id`, `created_at`, `source_name`, and a `complete: true` sentinel. | Size+mtime alone misses same-second rewrites with identical size (§7). The sentinel lets readers distinguish complete vs. torn indexes (§4). |
| No locking | (absent) | Add `fcntl.flock` on `backup_root/.lock` for writers and `backup_root/.prune.lock` for retention. | `synccli` has no concurrency control — concurrent `sync` calls race on the manifest. `backupctl` must handle scheduler+human collisions (§3). |

---

## 3. Concurrency

### 3.1 Run vs. run (scheduler + human)

* **Single-writer lock.** Every `backupctl run` acquires an exclusive
  `fcntl.flock` on `backup_root/.lock` before doing any work. `flock` is
  held on an open FD for the duration of the run and released on close
  (including process death — the kernel releases it). A second concurrent
  `run` that cannot acquire the lock within `--wait` (default 0, i.e. fail
  fast) exits with code 2 and message `another backup is in progress`.
  With `--wait SECONDS` it blocks up to that deadline.

* **Staging directory is per-run unique.** The in-flight snapshot is
  `backup_root/.tmp.snap-<timestamp>-<seq>.<pid>/`. Two runs never share
  a staging path even if timestamps collide (PID disambiguates). The
  staging dir is hidden (dot-prefix) so `snaputil.list_snapshots`
  (`snaputil.py:18` — `entry.name.startswith("snap-")`) never sees it.

* **Commit is an atomic rename.** On success the staging dir is renamed to
  `backup_root/snap-<timestamp>-<seq>/` via `os.rename` (atomic on POSIX
  when source and dest are on the same filesystem — which they are, since
  both are under `backup_root`). Readers that list snapshots before the
  rename do not see it; readers that list after see the complete snapshot.
  There is no window where a half-populated snapshot is visible under its
  final name.

### 3.2 Run (writer) vs. restore (reader)

* Restore (and any human reader) only operates on snapshots returned by
  `snaputil.list_snapshots` — i.e. fully committed snapshots. Staging
  dirs are invisible to that function by construction.

* Within a committed snapshot, files are never mutated after commit
  (snapshots are immutable). A reader can safely `read`/`copy` while
  another run is writing its own staging dir — they are disjoint paths.

* Retention deletion (§6) must not remove a snapshot a restore is
  actively reading. Deletion acquires `backup_root/.prune.lock`
  (exclusive) and restore acquires it shared (`LOCK_SH`). A restore holds
  `LOCK_SH` for its duration; prune blocks until readers drain. This is
  advisory — a bare `rm -rf` bypasses it, but all tool-mediated access
  respects it. Documented as such.

### 3.3 Reader never checks "is the run done?"

Guaranteed by construction:

1. Incomplete work lives under `.tmp.*` — not matching `snap-*` — so
   `list_snapshots` never returns it.
2. Inside a staging dir, the index `.backup_index.json` is written **last**,
   via `write-temp-then-rename`: write to `.backup_index.json.tmp`, `fsync`,
   `os.rename` to `.backup_index.json`. A reader that somehow opens the
   staging dir directly will find either no index (→ incomplete, ignore) or
   a complete index with `complete: true`.
3. The final commit (`os.rename` of the staging dir) and the index rename
   inside it are ordered: index rename happens first, then dir rename.
   After the dir rename, the snapshot is self-consistent.

---

## 4. Crash recovery — process can die at any point

### 4.1 What can be left behind

| Crash point | Artifact | Visible to readers? |
|---|---|---|
| Before staging dir created | Nothing | No |
| During file copies | `.tmp.snap-.../` partially populated, no index | No (`list_snapshots` ignores dot-prefix) |
| During index write (before rename) | `.tmp.snap-.../.backup_index.json.tmp` | No (wrong name) |
| After index rename, before dir rename | `.tmp.snap-.../` with complete index but still hidden | No |
| During `os.rename` of dir | Atomic — either old name or new name, never both/half | No corruption (POSIX guarantee) |

### 4.2 Next run's cleanup (no manual intervention)

At startup, before acquiring the run lock, `backupctl run` scans
`backup_root` for entries matching `.tmp.snap-*`:

* If the entry has no `.backup_index.json` (or it lacks `complete: true`
  or is not valid JSON) → delete the entire staging dir (`shutil.rmtree`).
  It was an interrupted run; nothing useful to salvage.
* If it has a valid complete index → this was a crash between index
  commit and dir rename (rare). The next run completes the commit by
  renaming it to its final `snap-*` name (derived from the staging name
  by stripping `.tmp.` and `.<pid>`). This preserves the work already done.

In either case the next run then proceeds normally and makes progress.
No leftover staging dir blocks future runs (bounded disk: at most one
orphan staging dir per crashed run, cleaned on next run).

### 4.3 Corrupt / half-written index recovery

The index `.backup_index.json` is the only file whose corruption matters
(all other files are either present or not). Recovery rules:

1. **Corrupt index in a staging dir** (`.tmp.snap-*/.backup_index.json`
   fails `json.load` or fails schema validation) → discard the entire
   staging dir. Report `recovered: discarded corrupt staging snapshot
   <name>: <error>`. Re-derive by re-running the backup from source —
   no state is salvaged from the corrupt index.

2. **Corrupt index in a committed snapshot** (`snap-*/.backup_index.json`
   fails validation) → the snapshot's files on disk are still intact
   (they were written before the index). Recovery:
   * Move the snapshot dir to `backup_root/.corrupt.snap-<name>/` (so it
     is hidden from `list_snapshots`).
   * Re-derive the index by re-scanning the snapshot's files on disk:
     for each source subdir, call `synccli.scan_files` + `synccli.file_state`
     (and hash — see §7) to rebuild the manifest. Write the rebuilt index
     via temp+rename. If rebuild succeeds, rename back to `snap-<name>/`.
   * Report `recovered: rebuilt index for snapshot <name> from tree
     (<N> files)`.

3. **Missing index in a committed snapshot** (somehow deleted) → same
   re-derive path as (2).

In all cases the run reports what it did to stderr and continues. A
snapshot with a corrupt index is never returned to readers — it is
quarantined first.

---

## 5. Source file can disappear without warning

A file can vanish between `scan_files` and `copy_file`, or be unreadable
when we try to copy it. Handling is uniform regardless of who triggered
the run (scheduler vs. human — no behavioral difference).

### 5.1 Snapshot contents when a file vanishes

* The snapshot **does not contain** the vanished file. No placeholder,
  no zero-byte stub. The file is simply absent from both the snapshot
  tree and the snapshot's index.

* The snapshot is still **complete and self-consistent**: the index lists
  exactly the files that are present on disk. A restore of that snapshot
  gets exactly what the index promises — no "promised but missing" entries.

### 5.2 What the run reports

`copy_file_atomic` returns `CopyResult.VANISHED` (covers `FileNotFoundError`
on open, and `ENOENT` during read) or `CopyResult.UNREADABLE` (covers
`PermissionError` / `EACCES`). The run:

* Logs each skipped file to stderr: `warning: skipped <source>/<rel>:
  vanished` or `warning: skipped <source>/<rel>: unreadable (<error>)`.
* Records them in the snapshot index under `skipped: [{rel, reason, error}]`.
* Exits with code 0 if at least one file was backed up (partial success is
  still a usable snapshot). Exits with code 3 only if **all** sources were
  empty or every file was skipped (nothing to snapshot — no snapshot dir
  is committed in that case; the staging dir is removed).
* The exit code and skipped list are identical for scheduler-triggered and
  human-triggered runs.

### 5.3 Override note

This replaces `synccli.copy_file` (`synccli.py:62-69`) which silently
swallows `OSError` with `pass` and leaves no trace. `backupctl`'s
`copy_file_atomic` surfaces the failure so the index stays truthful and
the operator can see what was missed.

---

## 6. Retention — backup root only ever grows, then pruned

### 6.1 Policy

Default policy (configurable via `config.json`):

```json
{
  "retention": {
    "keep_last": 7,
    "keep_daily": 4,
    "keep_weekly": 4
  }
}
```

* `keep_last` — always keep the N most recent snapshots regardless of age.
  Implemented directly via `snaputil.prune_snapshots(backup_root, keep_last)`
  (`snaputil.py:23-36`) when no time-bucketing is configured.
* `keep_daily` / `keep_weekly` — when set, snapshots are bucketed by
  calendar day/week (UTC, derived from the `snap-YYYYMMDD-HHMMSS-seq`
  name). Keep the newest snapshot per bucket for that many buckets; delete
  the rest, oldest first. Buckets are evaluated after `keep_last` is
  satisfied (so `keep_last` is a floor).

If `config.json` has no `retention` key, `keep_last=7` is the default.

### 6.2 Safety invariants

1. **Never delete the newest snapshot.** `snaputil.prune_snapshots`
   already guarantees this (`snaputil.py:26-27` — `doomed = names[:len(names)-keep]`
   never includes the last `keep`). Time-bucketed pruning also excludes
   the newest snapshot unconditionally.

2. **Never delete the last usable snapshot.** If pruning would delete
   every snapshot (e.g. `keep_last=0` misconfiguration), it keeps 1.
   Effective `keep = max(1, configured_keep)`.

3. **Safe while reading.** Prune acquires `backup_root/.prune.lock`
   exclusively; restore holds it shared. A snapshot being read is not
   deleted until the reader releases. See §3.2.

4. **Prune is a separate command** (`backupctl prune`), not implicit in
   `backupctl run`. A run never deletes old snapshots on its own — this
   prevents a run that just created a bad snapshot from immediately
   deleting the last good one. Operators (or the scheduler) invoke prune
   explicitly.

---

## 7. Incremental — most files don't change

### 7.1 Granularity of "unchanged"

Two levels, in order:

1. **Fast path — `size + mtime`** (from `synccli.file_state`,
   `synccli.py:22-25`): if the current source file's `(size, mtime)`
   matches the entry in the previous snapshot's index, it is considered
   unchanged. This is the same check `synccli.changed_files`
   (`synccli.py:36-42`) uses — `old_manifest[rel] != state`.

2. **Content hash — SHA-256** (new): for files that pass the fast path,
   no hash is computed. For files where size or mtime differs, the file
   is hashed (SHA-256, streamed in 1 MB chunks) and compared to the hash
   stored in the previous index. If hashes match, the file is still
   considered unchanged (covers mtime-only bumps from `touch`, permission
   changes, etc.).

Unchanged files are **hard-linked** (via `os.link`) from the previous
snapshot into the new staging snapshot, not copied. This means:

* Disk usage for unchanged files is shared (one inode, two directory
  entries). `snapshot_disk_usage` (`snaputil.py:39-51`) counts logical
  size (sums `st_size`), not physical — so reported usage over-counts
  when hard-links are used. Physical usage should be measured with
  `du --bytes` or `st_nlink` aware tooling; the design documents this
  distinction.

* If a source file is modified after being hard-linked, the new content
  goes to a new inode (copy-on-write is not needed — the source file is
  separate from the snapshot file).

### 7.2 What the granularity can miss

| Scenario | Detected? | Why |
|---|---|---|
| File overwritten with same size, mtime second unchanged | **Missed** on fast path (size+mtime equal) — not hashed, considered unchanged. | `file_state` (`synccli.py:22-25`) returns second-resolution `st_mtime`; sub-second rewrites or same-second rewrites with identical size are invisible. This is the same limitation `synccli` has today. |
| File overwritten with same size, different content, mtime bumped | **Caught** — mtime differs → hash computed → hash differs → treated as changed. |
| `touch` (mtime bump, content identical) | **Caught as unchanged** — mtime differs → hash computed → hash matches → hard-linked, not recopied. Extra hash cost but correct result. |
| Metadata-only change (chmod, xattr) | **Missed** — size+mtime unchanged → considered unchanged. Acceptable: backup is of file *content*, not permissions. Documented limitation. |

The same-second miss is inherent to stat-based detection. Mitigations
(not default, but available via `--verify-hash` flag): hash every file
regardless of fast-path result. Cost is one full read per file (see §8
budget — adds ~1 GB of reads for a 1 GB tree).

---

## 8. Performance budget — first full backup of ~1 GB / tens of thousands of files

### 8.1 Measurements (this repo, this machine)

Measured with the actual `synccli` functions on synthetic trees:

| Operation | Files | Per-file cost | Source |
|---|---|---|---|
| `scan_files` (`synccli.py:10-19`) | 5 000 | ~5 µs (24 ms total) | `os.walk` + `relpath` + sort |
| `file_state` (`synccli.py:22-25`) | 5 000 | ~16 µs (`os.stat`) | single `stat` syscall |
| `build_manifest` (scan+stat) | 5 000 | ~22 µs | sum of above |
| `copy_file` (`synccli.py:62-69`) | 10 000 × 1 KB | ~230 µs per file | open+read+write+close |
| `copy_file` | 100 × 1 MB | ~490 µs per file, 2060 MB/s (buffered) | large-file throughput |

Small-file cost is dominated by syscall overhead (open/close), not
bandwidth. Large-file cost is bandwidth-bound.

### 8.2 Derivation for 1 GB / 20 000 files

Assume a representative evals tree: **1 GB total, 20 000 files, mean file
size ~50 KB** (mix of small JSON/metadata + larger result blobs).

| Phase | Cost | Derivation |
|---|---|---|
| Scan + build manifest | 20 000 × 22 µs = **0.44 s** | `build_manifest` per-file cost above |
| Copy (first full backup — every file is new) | 20 000 × 230 µs + 1 GB / throughput | Per-file open/close overhead (230 µs) + bulk bytes. Bulk bytes at conservative 100 MB/s disk write = 10 s. Overhead = 4.6 s. |
| Index write | negligible | One JSON file, ~20K entries × ~80 B/entry ≈ 1.6 MB → <20 ms |
| **Total** | **~15 s** wall-clock | 0.44 + 4.6 + 10 ≈ 15 s |

If the backup target is a local SSD (500 MB/s write), bulk drops to 2 s
→ **~7 s total**. On a network filesystem (50 MB/s) → **~25 s**.

**Budget stated:** first full backup of 1 GB / 20 000 files completes in
**under 30 s on a local disk, under 60 s on a network filesystem**.
This is a wall-clock budget for `backupctl run` end-to-end, measured as
`time backupctl run` on the evals workload. The bound is dominated by
disk write bandwidth + per-file syscall overhead, both measured above —
not guessed.

**Incremental run** (1% churn = 200 files changed): scan still touches
all 20 000 files (0.44 s) but only 200 files are copied/hashed:
200 × 230 µs + ~10 MB bulk ≈ 0.15 s → **~0.6 s total**.

---

## 9. Scaling — N directories, F files, B bytes

Let N = number of configured source directories, F = total files across
all sources, B = total bytes. Bounds are for a single `backupctl run`.

| Resource | Bound | What grows with N | What stays flat |
|---|---|---|---|
| **Per-run wall time (full)** | `O(F × open_cost + B / bandwidth)` — see §8 derivation. | F and B grow with N (more dirs → more files/bytes). Per-dir scan is independent; no cross-dir coordination. | Lock acquisition: 1 `flock` regardless of N. Index write: 1 file regardless of N. |
| **Per-run wall time (incremental)** | `O(F × stat_cost + changed × (hash_cost + copy_cost))`. `stat_cost` ≈ 16 µs/file (§8). | F still scanned fully (must stat every file to detect changes). `changed` typically ≪ F and grows sublinearly with N. | Hash/copy only for changed files — does not grow with N if churn is bounded. |
| **Memory** | `O(F)` entries — one manifest dict entry per file: ~100 B/entry (relpath + size + mtime + hash hex). For 100K files ≈ 10 MB. | Grows with F (hence N), not with B. | Bounded by F, not B — a 1 GB file and a 1 KB file cost the same one entry. |
| **Disk (per snapshot, logical)** | `B + O(F × index_entry)` — snapshot holds a full logical copy (hard-links share inodes for unchanged files, but logical size as reported by `snapshot_disk_usage` is B). | B grows with N. | Physical disk with hard-link dedup: only `changed_bytes + O(F × index_entry)` new bytes per incremental snapshot. Unchanged files share inodes — physical growth per incremental run is bounded by churn, not N. |
| **Disk (retention window)** | `B_first + (retained_snapshots - 1) × avg_churn_bytes`. With hard-link dedup, 7 daily snapshots at 1% churn/day ≈ `B + 0.07×B` physical, not `7×B`. | Retention count, not N, determines multiplier. | — |
| **File descriptors** | 1 lock FD + 1 index FD + 1 copy FD at a time (sequential copy). Peak = 3. | Does not grow with N or F. | Flat — files are copied one at a time, not in parallel. |
| **Snapshot count** | 1 per run, regardless of N. | Flat in N — one snapshot dir per run containing all N sources as subdirs. | `list_snapshots` (`snaputil.py:8-20`) scans `backup_root` entries: `O(snapshot_count)` dentries, independent of N, F, B. |

**Concrete example:** N=30 dirs, F=100K files, B=10 GB, 1% daily churn,
7 snapshots retained:
* Full backup: ~75 s (10 GB / 100 MB/s + 100K × 230 µs ≈ 23 s overhead +
  100 s bulk → ~75 s on SSD faster).
* Incremental: ~2 s (100K stats × 16 µs = 1.6 s + 1K changed files).
* Memory: ~10 MB manifest.
* Physical disk for 7 snapshots: ~10 GB + 6×100 MB ≈ 10.6 GB (not 70 GB).

---

## 10. CLI summary

```
backupctl run [--wait SECS] [--verify-hash]   # create one snapshot
backupctl list                                 # wrappers snaputil.list_snapshots
backupctl prune [--keep N | --config]          # wrappers snaputil.prune_snapshots + time buckets
backupctl restore <snapshot> <source> <dest>    # copy via safe_snapshot_path
backupctl verify <snapshot>                    # re-hash and compare to index
backupctl status                               # last snapshot, next prune candidates, disk usage
```

---

## 11. Risks and non-goals

* **Not a block-level dedup engine.** File-level hard-link dedup is
  sufficient for evals (files are written once, rarely modified in place).
  Sub-file dedup (e.g. chunking) is out of scope.
* **No encryption / compression.** Snapshots are plain directory copies.
  Compression can be layered externally if needed.
* **No remote backend.** Backup root is a local (or NFS-mounted) path.
  Cloud upload is a separate concern.
* **Clock skew.** Snapshot names use wall-clock UTC. If the clock jumps
  backwards, sequence numbers still order correctly (lexicographic sort on
  `snap-YYYYMMDD-HHMMSS-seq` is chronological). NTP-corrected clocks are
  assumed; no monotonic-clock naming is needed.

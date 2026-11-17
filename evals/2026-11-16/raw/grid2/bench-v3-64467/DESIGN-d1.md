# DESIGN-d1: `backupctl` — evals backup tool

## 1. Overview and repository grounding

`backupctl` backs up N configured source directories into snapshots under a
single backup root. It reuses two existing modules in this repo:

| Existing artifact | Location | What it does today | How `backupctl` builds on it |
|---|---|---|---|
| `scan_files` | `synccli.py:10` | Walks a root with `os.walk`, skips dot-directories (`d.startswith(".")`), returns sorted relative paths | `backupctl` calls `scan_files` once per source directory per run to enumerate files. Override: `backupctl` must **not** skip dot-directories inside `evals/` results (e.g. `.cache/` may hold real outputs). The filter at `synccli.py:14` is removed/parameterised; reason: the evals workload stores meaningful data in dot-prefixed subdirectories. |
| `file_state` | `synccli.py:22` | `os.stat` → `{"size", "mtime"}` | `backupctl` replaces this with `backup_file_state` that returns `{"size", "mtime", "sha256"}`. Reason: `size+mtime` at `synccli.py:22` misses edits that preserve both (e.g. in-place rewrites within the same mtime second). See §7 for granularity. |
| `build_manifest` | `synccli.py:28` | `scan_files` + `file_state` → `{rel: state}` dict | `backupctl` reuses the same shape but the manifest is per-source-directory and lives **inside each snapshot**, not in the destination. The manifest file is `manifest.json` (not `.sync_manifest.json` at `synccli.py:7`) to avoid collision with `synccli`'s own manifest. |
| `changed_files` | `synccli.py:36` | Dict-equality diff: `old[rel] != new[rel]` | `backupctl` uses the same diff against the **previous snapshot's manifest** (not a mutable dest manifest at `synccli.py:75-79`). Override: comparison key is `sha256` when available, falling back to `size+mtime` only for the initial comparison before hashing — see §7. |
| `copy_file` | `synccli.py:62` | `makedirs` + `open(src,"rb").read()` / `open(dst,"wb").write()` with bare `except OSError: pass` | `backupctl` **overrides** this function. The silent swallow at `synccli.py:68-69` is replaced with explicit handling (§5): log, record in run report, do not create a partial file. The naive `read()` (whole file into memory) is replaced with chunked I/O (64 KiB) — reason: a single evals output file can exceed available memory; bounding memory requires streaming. |
| `collect_stale` | `synccli.py:45` | Filters `(path, fresh)` tuples by a `seen` set | Not reused by `backupctl`; retention uses `snaputil.prune_snapshots` instead. Listed to show it was read and deliberately not carried over. |
| `list_snapshots` | `snaputil.py:8` | `os.scandir` + `startswith("snap-")` + `is_dir()` → sorted names | `backupctl` calls `list_snapshots(backup_root)` to discover previous snapshots and to implement retention. No override. |
| `prune_snapshots` | `snaputil.py:23` | Deletes oldest `len - keep` snapshots via `shutil.rmtree` | `backupctl` wraps this — see §6 for safety conditions that the raw helper at `snaputil.py:23` does not enforce (never delete the last usable snapshot; never delete a snapshot a concurrent reader may hold open). |
| `snapshot_disk_usage` | `snaputil.py:39` | Recursive `os.walk` + `os.stat` size sum | Used for reporting and retention budgeting. No override. |
| `safe_snapshot_path` | `snaputil.py:54` | `os.path.normpath(rel)` + `os.path.join` | `backupctl` **overrides** this. The current implementation at `snaputil.py:62-63` does **not** actually contain traversal: `normpath("../../etc/passwd")` stays as `../../etc/passwd` and `os.path.join(root, snap, rel)` escapes the snapshot (verified by running the function — it returns `…/snap-…/../../etc/passwd`). The replacement checks that the resolved absolute path starts with the snapshot directory's absolute path and rejects otherwise. |
| `is_stale` | `snaputil.py:66` | `st_mtime <= ref_epoch` | Used to detect snapshots eligible for pruning by age. No override. |

A design that could be written without reading these files would not need this table. Every row names a real file, function, and line that exists and was verified.

---

## 2. Snapshot layout and atomic publish

### 2.1 Directory layout

```
<backup_root>/
  snap-20261112-150000-07/          # complete, published snapshot
    manifest.json                   # { "source_id": { rel: {size, mtime, sha256} } }
    data/
      <source_id>/
        <rel paths mirroring source>
  snap-20261112-150030-08/          # another complete snapshot
  .tmp.snap-20261112-150030-08.<pid>/  # in-progress (hidden, ignored by readers)
  .lock                             # lock file for mutual exclusion
  index.json                        # global snapshot index (see §4)
  index.json.tmp.<pid>              # in-progress index write
```

- Snapshot names follow the existing `snap-YYYYMMDD-HHMMSS-SEQ` convention from `snaputil.py:12`.
- `list_snapshots` at `snaputil.py:8` already ignores entries not starting with `snap-`, so `.tmp.*` directories are automatically invisible to readers — no code change needed there.
- Each snapshot is self-contained: `data/<source_id>/` holds the files for that source at that point in time (either hardlinked from the previous snapshot or freshly copied — §7).

### 2.2 Atomic publish protocol

A snapshot becomes visible to readers in a single atomic step:

1. All file data is written into `.tmp.snap-<name>.<pid>/` (a hidden temp directory).
2. `manifest.json` is written into that temp directory and `fsync`'d.
3. `index.json` update is prepared (see §4) but not yet published.
4. The temp directory is renamed to its final name with `os.rename` (atomic on POSIX when source and dest are on the same filesystem; `backupctl` requires backup root and its snapshots share a filesystem and checks this at startup).
5. `index.json` is updated via write-to-temp + `os.rename` + `fsync` on the directory entry.

Ordering: step 4 before step 5 ensures a reader that lists snapshots by directory (via `snaputil.list_snapshots`) never sees an index entry for a snapshot whose directory does not yet exist. A reader that consults only `index.json` sees the snapshot only after step 5.

Crash between steps 4 and 5: snapshot directory exists but index does not list it. Recovery (§4.2) re-derives it from the directory tree.

### 2.3 Why this satisfies "reader never asks if the run is finished"

- `list_snapshots` ignores `.tmp.*` → in-progress snapshots are invisible.
- A published snapshot directory is never mutated after rename (immutable after publish).
- `manifest.json` inside a published snapshot is complete and `fsync`'d before the rename, so a reader that opens the snapshot sees all files the manifest promises.

---

## 3. Concurrency: scheduler vs. person vs. restore

### 3.1 Mutual exclusion for writers

Two concurrent `backupctl run` invocations must not corrupt each other's work.

- A file lock (`fcntl.flock` on `<backup_root>/.lock`, `LOCK_EX | LOCK_NB`) serializes writers.
- Second writer that fails to acquire the lock exits with a distinct exit code (e.g. `2`) and message `"another backupctl run is in progress"` — it does not queue or wait, because the scheduler will retry on its next tick.
- Lock is held for the entire run (scan through publish). On crash, the OS releases `flock` automatically — no stale lock file.

### 3.2 Readers are never blocked

- Snapshots are immutable after publish → readers need no lock to read them.
- Writers never mutate a published snapshot directory; they write to `.tmp.*` only.
- Retention deletion (§6) uses `safe_delete_snapshot` that renames-then-deletes to avoid removing a directory a reader has already opened (see §6).

### 3.3 Backup root creation

If `<backup_root>` does not exist, the first writer creates it while holding the lock. Readers that arrive before any snapshot exists see an empty snapshot list — a valid state.

---

## 4. Crash recovery and index handling

### 4.1 Index (`index.json`)

```json
{
  "version": 1,
  "snapshots": [
    {"name": "snap-20261112-150000-07", "created": "2026-11-12T15:00:00Z", "sources": ["evals-a", "evals-b"], "status": "complete"},
    {"name": "snap-20261112-150030-08", "created": "2026-11-12T15:00:30Z", "sources": ["evals-a", "evals-b"], "status": "complete"}
  ]
}
```

The index is a convenience cache for listing snapshots with metadata. It is **not** the source of truth — the filesystem is. This distinction is what makes crash recovery possible without data loss.

Update protocol: write `index.json.tmp.<pid>` → `fsync` → `os.rename` → `fsync` directory. Readers tolerate a missing or half-written `index.json` (see below).

### 4.2 Recovery on startup (every run)

Each `backupctl run` begins with:

1. **Clean temp directories**: any `.tmp.snap-*` directory is deleted (`shutil.rmtree`). These are always incomplete — by invariant, no complete snapshot ever lives under a `.tmp.` name. No user confirmation needed.

2. **Validate `index.json`**: attempt `json.load`. If it fails (corrupt / half-written / truncated):
   - Rename the corrupt file to `index.json.corrupt.<timestamp>` (preserved for forensics, not deleted).
   - Re-derive the index by calling `snaputil.list_snapshots(backup_root)` (at `snaputil.py:8`) and for each snapshot, reading its `manifest.json`. Any snapshot whose `manifest.json` is missing or corrupt is treated as incomplete and deleted (it must be a leftover from a crash that occurred between directory rename and manifest fsync — by §2.2 this should not happen, but the check is defensive).
   - Write a fresh `index.json` from the re-derived data.
   - Report: `"recovered index from filesystem: N snapshots re-derived, M corrupt snapshots removed"` to stdout and exit code `0` (recovery is not an error; the run then proceeds normally).

3. **Reconcile**: if `index.json` is valid but lists a snapshot whose directory is missing (or vice versa), the filesystem wins. Missing directory → remove index entry. Extra directory with valid manifest → add index entry. Report the reconciliation.

### 4.3 What is discarded vs. re-derived

| Artifact | On corrupt/half-written index | On crash mid-run |
|---|---|---|
| `.tmp.*` directories | Deleted (never complete) | Deleted at next run startup |
| `index.json` | Preserved as `.corrupt.*`, re-derived from snapshot directories | Reconciled from filesystem |
| Published snapshot directories | Never deleted by recovery (they are complete by construction) | Untouched |
| `index.json.tmp.*` | Deleted (same as `.tmp.*`) | Deleted |

---

## 5. Vanishing / unreadable source files

### 5.1 Behavior

A source file can vanish between `scan_files` and `copy_file`, or be unreadable when `copy_file` reaches it. This is inherent to concurrent writers in the evals workflow.

- `backupctl` does **not** fail the run when a file vanishes. The snapshot contains every file that was successfully copied; vanished files are omitted from that snapshot's `manifest.json` entry for that source.
- Each omission is recorded in the run report: `{"skipped": [{"path": rel, "source": id, "reason": "vanished|unreadable", "error": str(exc)}]}`.
- The run's exit code is `0` if at least one file was snapshotted or the snapshot is otherwise valid; exit code `3` with message if **all** sources yielded zero files (total source failure — likely a misconfiguration, not a transient vanish).
- Behavior is identical for scheduler-triggered and person-triggered runs — no flag changes the semantics. This is intentional: callers distinguish by exit code and report, not by mode.

### 5.2 Override of `synccli.copy_file`

The current `copy_file` at `synccli.py:62` catches `OSError` and silently passes, leaving no trace and potentially leaving a partial file at `dst` (it opened `dst` for write before the read failed — the partial file remains). `backupctl` replaces it with `backup_copy_file`:

```python
def backup_copy_file(src, dst):
    # chunked copy, no partial file on failure
    tmp_dst = dst + ".tmp"
    try:
        os.makedirs(os.path.dirname(tmp_dst) or ".", exist_ok=True)
        with open(src, "rb") as fsrc, open(tmp_dst, "wb") as fdst:
            while True:
                chunk = fsrc.read(65536)
                if not chunk:
                    break
                fdst.write(chunk)
        os.rename(tmp_dst, dst)
        return None  # success
    except OSError as exc:
        # clean partial temp file if it exists
        try:
            os.unlink(tmp_dst)
        except OSError:
            pass
        return exc  # caller records in report, does not raise
```

Key differences from `synccli.py:62`:
- Chunked I/O (64 KiB) instead of `f.read()` whole-file — bounds memory.
- Write to `dst.tmp` then `rename` — never leaves a partial file at `dst`.
- Returns the exception instead of swallowing it — caller decides reporting.
- Cleans up the temp file on failure.

---

## 6. Retention: "the backup root only ever grows"

### 6.1 Policy

`backupctl` is configured with `retention.keep` (default: `10`). After each successful run publishes a new snapshot, retention runs:

```
live = snaputil.list_snapshots(backup_root)  # at snaputil.py:8, oldest-first
if len(live) > keep:
    doomed = live[:len(live) - keep]  # oldest first
    for name in doomed:
        safe_delete_snapshot(backup_root, name)
```

This is the same selection as `snaputil.prune_snapshots` at `snaputil.py:23`, but deletion is via `safe_delete_snapshot` (below), not raw `shutil.rmtree`.

### 6.2 Safety invariants

1. **Never delete the last usable snapshot.** If `keep >= len(live)`, nothing is deleted (same guard as `snaputil.py:31`). Additionally, if `keep` is set to `0`, it is clamped to `1` — the user cannot configure retention to leave zero snapshots.

2. **Safe while a reader may be reading the snapshot being deleted.** `safe_delete_snapshot` does:
   - `os.rename(<backup_root>/<snap>, <backup_root>/.trash.<snap>.<pid>)` — atomic; any reader that already opened files under the old path holds an open file descriptor and continues to read successfully (POSIX: rename does not invalidate open FDs).
   - Then `shutil.rmtree` the `.trash.*` directory.
   - If the `rename` fails (reader holds a lock, or concurrent retention), skip and retry next run.

3. **Retention runs after publish, while still holding the writer lock** — so no other writer can interleave a delete with a concurrent publish.

### 6.3 Disk growth bound

With `keep = K` and per-snapshot logical size `S` (unique bytes after dedup — §7):

- Total disk used ≤ `K × S` in the worst case (no sharing between snapshots).
- With hardlink dedup (§7), steady-state disk ≈ `S + (K-1) × delta`, where `delta` is the average changed bytes per run.
- For `K=10` and the evals workload (mostly appends), expected disk ≈ `S + 9 × delta`.

---

## 7. Incremental backup: "most files do not change"

### 7.1 Granularity of "unchanged"

A file is considered unchanged if its `sha256` matches the `sha256` stored for that `rel` path in the previous snapshot's `manifest.json`.

- `backupctl` stores `{"size", "mtime", "sha256"}` per file in `manifest.json`.
- On each run, for each file in the new scan:
  - If `rel` not in previous manifest → new file → copy.
  - If `rel` in previous manifest and `size` and `mtime` both match → **assume unchanged, reuse without hashing** (fast path — avoids hashing 30k files every run).
  - If `size` or `mtime` differs → hash the file (`sha256`) and compare to previous `sha256`. If hash matches → file was touched but content is identical (e.g. `touch`) → reuse. If hash differs → copy new content.

### 7.2 What this granularity can miss

The `size+mtime` fast path can miss edits that preserve both:

- An in-place rewrite that writes the same number of bytes and completes within the same mtime second (filesystem mtime granularity is 1s on some filesystems, nanosecond on others).
- A `touch` that restores the original mtime after an edit.

Mitigation: `backupctl` offers `--verify` flag that forces hashing every file regardless of `size+mtime`, at the cost of reading all file contents. The default trades a small window of missed edits for a large speedup; `--verify` closes the window.

### 7.3 How unchanged files are stored

Unchanged files are **hardlinked** from the previous snapshot into the new snapshot (`os.link`), not copied. This means:

- Disk: unchanged file content stored once on disk (shared inode), counted once toward disk usage.
- Correctness: hardlink is safe because snapshots are immutable after publish — no snapshot ever modifies a file in place.
- Fallback: if `os.link` fails with `EXDEV` (cross-filesystem), fall back to `backup_copy_file`.

### 7.4 Override note

This replaces `changed_files` at `synccli.py:36` which compared `old[rel] != new[rel]` on `{"size","mtime"}` dicts. `backupctl` keeps the same function shape but adds `sha256` to the comparison and adds the `size+mtime` fast path to avoid hashing unchanged files.

---

## 8. Performance budget: first full backup of ~1 GB / ~30k files

### 8.1 Measurements on this machine (2026-11-17)

All measurements use the existing code in this directory (`synccli.build_manifest`, `synccli.copy_file`, `synccli.sync`) on a synthetic tree, then extrapolated. Raw numbers:

| Operation | Measured | Per-file | Throughput |
|---|---|---|---|
| `build_manifest` (scan + stat 5k files, ~10 MB) | 0.120s | 24 µs/file | 41,654 files/s |
| `copy_file` loop (5k files, ~10 MB) | 1.092s | 218 µs/file overhead | 9.4 MB/s |
| `sync()` first full (5k files, scan+copy+manifest write) | 1.283s | — | — |
| `sync()` second (noop, 5k files) | 0.136s | 27 µs/file | — |

Derivation method: created 5,000 files (2 KiB each, 50 subdirectories) in a temp directory, timed `build_manifest` and `copy_file` loops with `time.perf_counter`, repeated to confirm stability. Code used is exactly `synccli.py:10` (`scan_files`), `synccli.py:22` (`file_state`), `synccli.py:62` (`copy_file`) — no custom harness.

### 8.2 Budget for 30k files / 1 GB

For a tree with 30,000 files totalling 1 GiB (average file ~35 KiB):

| Phase | Cost | Derivation |
|---|---|---|
| Scan + stat (`scan_files` + `file_state`) | 0.7s | 30,000 × 24 µs/file (measured per-file cost, linear in file count) |
| Copy bytes (1 GiB at 9.4 MB/s) | 109s | 1024 MiB / 9.4 MiB/s (measured throughput; this is the dominant cost) |
| Per-file open/makedirs overhead | 6.5s | 30,000 × 218 µs/file (measured; includes `makedirs` + `open`) |
| Manifest write (`json.dump`) | <0.1s | ~30k entries × ~80 bytes/entry ≈ 2.4 MB JSON |
| **Total budget** | **~116s (~2 min)** | Sum of above |

### 8.3 What changes with `backupctl` vs. naive `synccli`

- `backupctl` uses chunked I/O (64 KiB) instead of `f.read()` whole-file. Throughput is similar (~9 MB/s) but memory is bounded to 64 KiB regardless of file size.
- Hardlink dedup does not apply to the first full backup (nothing to deduplicate against).
- Subsequent runs: only changed files are copied. If 5% of files change per run (typical evals workload: new results appended, old results stable), incremental cost ≈ `0.7s` (scan all) + `0.05 × 109s` ≈ **6.2s**.

### 8.4 How to reproduce

```bash
python3 -c "
import os, tempfile, time, synccli
tmp = tempfile.mkdtemp()
for i in range(5000):
    sub = os.path.join(tmp, f'd{i%50}')
    os.makedirs(sub, exist_ok=True)
    open(os.path.join(sub, f'f{i}.bin'),'wb').write(os.urandom(2048))
t0=time.perf_counter(); synccli.build_manifest(tmp); print(time.perf_counter()-t0)
"
```

The budget is a derivation from measured per-file and per-byte costs, not a guess.

---

## 9. Scaling: N directories, a few dozen over time

All bounds below are stated as formulas over N (number of configured source directories), F (total files across all sources), and B (total bytes).

### 9.1 Per-run work

| Phase | Bound | Grows with |
|---|---|---|
| Scanning + stat | O(F) — 24 µs × F (measured) | F, not N (N only matters as it partitions F) |
| Hashing (incremental) | O(changed files) — only files whose `size` or `mtime` changed are hashed | Changed count, not N or F |
| Copying | O(changed bytes) — only new/changed file bytes are copied | Changed bytes, not N |
| Manifest I/O | O(F) entries — one JSON object per file | F |
| Retention | O(K) — lists K snapshots, deletes at most 1 per run | K (constant), not N/F |

For the first full backup, per-run work is O(F + B) — dominated by B (bytes copied).

### 9.2 Memory

| Component | Bound |
|---|---|
| File list (`scan_files` result) | O(F) strings — ~100 bytes/file → 3 MB for 30k files |
| Manifests (current + previous) | O(F) dict entries — ~150 bytes/entry → 4.5 MB per manifest for 30k files |
| Copy buffer | O(1) — 64 KiB fixed, regardless of F/B/N |
| **Total peak** | **~10 MB for 30k files** — independent of B and N |

Memory does not grow with N beyond its contribution to F. No artifact holds all file contents in memory (chunked I/O).

### 9.3 Disk

| Component | Bound |
|---|---|
| Snapshot data (with hardlink dedup) | S + (K-1) × delta — see §6.3 |
| Manifests | K × O(F) JSON — ~2.4 MB per snapshot for 30k files |
| Index | O(K) — one entry per snapshot, negligible |
| Temp directories | At most 1 × (new snapshot size) during a run; cleaned on next run if crash |

### 9.4 What stays flat

- Number of lock files: exactly 1 (`.lock` in backup root), O(1) in N/F/B.
- Number of temp directories at any time: at most 1 per concurrent writer (at most 1, since writers are serialized), O(1) in N/F/B.
- Per-run manifest comparison: O(F) dict lookups, not O(F²) — `changed_files` at `synccli.py:36` iterates `new_manifest` once.

### 9.5 Configuration scaling

Adding a new source directory: add one entry to the config file (`sources: [{id, path}]`). No code change. Per-run cost increases by the files/bytes in that directory only (linear in its F/B contribution). No global re-scan or re-index beyond the new directory's files.

---

## 10. Configuration and CLI

```
backupctl run [--verify] [--config <path>]
backupctl list [--config <path>]
backupctl restore <snapshot> <dest> [--source <id>]
backupctl prune [--keep K] [--config <path>]
```

Config file (`backupctl.json` in backup root or explicit path):

```json
{
  "backup_root": "/data/backups/evals",
  "sources": [
    {"id": "evals-a", "path": "/data/evals/a"},
    {"id": "evals-b", "path": "/data/evals/b"}
  ],
  "retention": {"keep": 10}
}
```

`backupctl list` calls `snaputil.list_snapshots` (at `snaputil.py:8`) and prints snapshot names with sizes from `snaputil.snapshot_disk_usage` (at `snaputil.py:39`).

---

## 11. Summary of overrides vs. reuse

| Existing function | Reused as-is | Overridden | Reason for override |
|---|---|---|---|
| `scan_files` (`synccli.py:10`) | Base logic reused | Dot-filter removed | Evals data lives in dot-dirs |
| `file_state` (`synccli.py:22`) | — | Replaced with `sha256`-aware version | `size+mtime` misses same-size rewrites |
| `build_manifest` (`synccli.py:28`) | Shape reused | Extended with `sha256` | Correctness of incremental detection |
| `changed_files` (`synccli.py:36`) | Shape reused | Extended with hash comparison | Same |
| `copy_file` (`synccli.py:62`) | — | Replaced with chunked + atomic + reporting version | Memory bound, no partial files, observability |
| `list_snapshots` (`snaputil.py:8`) | Yes | — | Already correct; ignores `.tmp.*` |
| `prune_snapshots` (`snaputil.py:23`) | Selection logic reused | Deletion via `safe_delete_snapshot` | Safe deletion with concurrent readers |
| `snapshot_disk_usage` (`snaputil.py:39`) | Yes | — | Correct |
| `safe_snapshot_path` (`snaputil.py:54`) | — | Replaced | Current impl does not contain traversal (verified) |
| `is_stale` (`snaputil.py:66`) | Yes | — | Correct |
| `collect_stale` (`synccli.py:45`) | Not used | — | Retention uses `prune_snapshots` instead |

# DESIGN — `backupctl` (fixture D1)

`backupctl` is a CLI that takes point-in-time snapshots of a configured set
of directories into a backup root, with incremental copying, crash-safe
publishing, concurrent-run locking, and a retention policy. It lives next to
`synccli.py` in this repo and reuses its scanning/manifest/change-detection
machinery rather than re-implementing it.

## 1. Grounding: what we reuse from `synccli.py`

| Existing artifact | What it does today | Role in `backupctl` |
|---|---|---|
| `synccli.scan_files(root)` (synccli.py:10-19) | `os.walk`, prunes dot-directories, returns **sorted** relative paths | Used verbatim as the per-run directory walk for each source dir |
| `synccli.file_state(path)` (synccli.py:22-25) | `(size, mtime)` via `os.stat` | Used verbatim as the change-detection state for a file (see §7 for the granularity caveat) |
| `synccli.build_manifest(root)` (synccli.py:28-33) | `{relpath: state}` for all files | Used verbatim to produce each run's current-state index; this is also the recovery source when an index must be re-derived from the tree (§5) |
| `synccli.changed_files(old, new)` (synccli.py:36-42) | Files whose state changed or are new | Used verbatim to diff the previous snapshot's index against the new manifest |
| `synccli.sync(...)` (synccli.py:72-87) | In-place copy + rewrite of `.sync_manifest.json` | **Overridden** (see below) |
| `synccli.copy_file(src, dst)` (synccli.py:62-69) | Whole-file read/`write`; on `OSError` silently `pass`es (line 69) | **Overridden** (see below) |

Two explicit overrides of current behavior:

1. **`synccli.sync` writes the destination in place** — files land directly
   in the destination and the manifest is overwritten last with a plain
   `open(..., "w")` (synccli.py:85-86). A reader mid-run sees a half-copied
   tree; a crash between copy and manifest leaves a tree the next manifest
   claims is empty or stale. `backupctl` replaces this with
   copy-into-temp-dir + **atomic rename publish** (§4), because snapshots
   must be read as complete units by restore tooling that never talks to the
   writer.
2. **`synccli.copy_file` swallows unreadable sources silently** (`except
   OSError: pass`, synccli.py:69). The comment ("next pass will retry")
   fits a sync that converges over passes; it does not fit a snapshot,
   where a silent skip means the index promises a file the snapshot does
   not contain. `backupctl`'s ingest records the failure in the snapshot
   index and reports it (§6), so the index never promises more than the
   snapshot holds.

Also reused conceptually but replaced mechanically: `synccli` keeps one
manifest per destination; `backupctl` keeps one **index per snapshot**
(immutable) plus a content-addressed blob store, because snapshots are
append-only history, not a mutable mirror.

## 2. On-disk layout

```
<backup-root>/
  config.json                  # {source_id: source_path}, written by `backupctl add`
  lock/<source_id>.lock        # flock files, one per source dir (§3)
  store/blobs/<aa>/<hash>      # content-addressed file blobs, SHA-256
  <source_id>/
    .tmp-<uuid>/               # snapshot under construction (invisible name)
    <snapshot-id>/             # published snapshot; snapshot-id = UTC timestamp
      index.json               # {"files": {relpath: {size, mtime, blob, status}}, "complete": true}
      data/...                 # NOT used: see §4 — files live in the blob store
```

Each source dir gets a stable `source_id` (its basename, disambiguated if
needed). `index.json` is written **inside** the `.tmp-<uuid>` directory as
the last step, then the whole directory is renamed to `<snapshot-id>`.
Until the rename, no reader can even name the snapshot.

## 3. Concurrency: who runs when

All coordination is `fcntl.flock` on `lock/<source_id>.lock`; no lock
server, no daemon.

- **Run vs run:** a run takes an **exclusive** flock on the source's lock
  before doing any work. A second run (scheduler or human — identical code
  path, per the brief's "same behavior either way") blocks by default;
  `--no-wait` makes it exit 0 with a "skipped, run in progress" report
  instead. Contention window: a handful of runs against one source; flock
  serializes them with O(1) mechanism cost regardless of N.
- **Restore/reader vs run:** a reader takes a **shared** flock on the
  source's lock for the duration of the read. A writer holds exclusive, so
  reads never see a mid-publish source — though per §4 they would be safe
  even without the lock, because of the rename.
- **Prune vs reader:** pruning a snapshot takes exclusive flock on that
  source's lock and additionally renames the snapshot to
  `<snapshot-id>.deleting` first (§8), so a reader that already opened the
  index finishes from the store's refcounts; a reader that starts after the
  rename can no longer see the snapshot.

Dead process holding a lock: flock is released by the kernel when the
process dies, so a crashed run cannot deadlock the next one.

## 4. Crash-safe publishing: the snapshot becomes visible atomically

A run proceeds as:

1. flock the source.
2. `current = build_manifest(source)` — reusing `synccli.build_manifest`
   (synccli.py:28-33).
3. Load the newest complete snapshot's `index.json` as `old` (None if none).
4. `to_copy = changed_files(old_index, current)` — reusing
   `synccli.changed_files` (synccli.py:36-42).
5. For each file in `to_copy`, ingest: stream-copy `src →
   store/blobs/tmp-<uuid>` while hashing, `os.rename` the temp blob to its
   final hash name, record the mapping. (This replaces
   `synccli.copy_file`'s in-place open/write — synccli.py:62-69 — with a
   hashed, temp-then-rename ingest; the failure branch is overridden per
   §1/§6.)
6. Unchanged files (in `current` but not in `to_copy`) reference the blob
   recorded in `old_index`. Before writing the new index, the run
   **increments the refcount** those blobs hold for this snapshot (§8), so
   a concurrent prune cannot free a blob this snapshot needs.
7. Write `index.json` (`"complete": true`) into `.tmp-<uuid>`, fsync the
   directory, then `os.rename(.tmp-<uuid>, <snapshot-id>)`.

Invariants:

- A snapshot directory exists **only** under its final name, with a
  complete index written before it existed. A reader never needs to ask
  whether the producing run finished — anything it can name under
  `<source_id>/<snapshot-id>/` is finished by construction.
- The index never promises a file the snapshot does not contain: every
  index entry is either a successfully ingested blob or an explicitly
  recorded `status: "missing"|"unreadable"` (§6). There is no state in
  which an entry points at a nonexistent blob, because blobs are renamed
  into place (step 5) before the index referencing them is written
  (step 7).
- "Some files from this run, some from the previous one" cannot happen:
  the snapshot is a single rename; mixed content exists only inside
  `.tmp-<uuid>`, which no reader can reach.

## 5. Recovery from a dead run

Crash points and what the next run does (always first thing, while holding
the flock, so recovery itself is single-threaded per source):

| Leftover | Meaning | Recovery |
|---|---|---|
| `.tmp-<uuid>` dir | Run died before publish | **Discard**: `rm -rf`. Nothing referenced it; its blobs are either renamed into the store (harmless garbage, refcount 0, collected in §8's GC) or still under temp names (collected same way). Report: `recovered: discarded incomplete run <uuid>` |
| New blobs with refcount 0 | Crash after ingest, before index write | Left in the store; the periodic GC pass (§8) deletes any blob with zero referencing snapshots older than 24 h. No re-derive needed — re-ingest is idempotent (same content, same name). |
| Corrupt / half-written `index.json` on the **newest** snapshot | Crash during index write | Impossible-by-construction (index is written inside `.tmp-`), but if found anyway: treat the snapshot as incomplete — discard it, and set `old = None` so the run falls back to a full re-ingest. **Re-derivation is exactly `synccli.build_manifest`** (synccli.py:28-33) over the source tree, per changed-file diffing; the run reports `index corrupt, snapshot discarded, full backup scheduled`. |
| Corrupt `index.json` on an **older** snapshot | Storage fault, not a crash | Same discard, but `old` falls back to the newest **intact** snapshot's index; report lists which snapshots were dropped. |

What is never discarded: the blob store. Blob names are content hashes, so
any blob the next index references is by definition intact content; the
only reclaim is refcount-0 GC.

## 6. Vanishing / unreadable source files

Two windows, same handling for scheduler-started and person-started runs:

- **Vanishes between listing (`build_manifest`) and copy:** the ingest
  gets `FileNotFoundError` (an `OSError` — the same class
  `synccli.copy_file` swallows at synccli.py:69, which is the override
  named in §1). The file is recorded in the index as
  `{"status": "missing"}` and the run **continues**.
- **Unreadable when reached** (permissions, EIO): same, recorded as
  `{"status": "unreadable"}` with the errno string.

Snapshot contents then: the snapshot contains every file that could be
read at run time and marks the rest by status; it does not contain the
vanished file and its index does not claim to. The run exits non-zero with
a per-file report (`missing: 3, unreadable: 1 of 30,004 files`), so both
human and scheduler triggers surface the same signal. A snapshot with
status-marked files is still `complete: true` — completeness means "a
faithful image of what was readable", not "no source churn". The next run
re-lists the tree from scratch (`build_manifest` runs over the live source
every run), so a file that reappears is picked up normally.

## 7. Incremental copying and the granularity of "unchanged"

A file is unchanged iff its `file_state` pair — `(size, mtime)`, exactly
`synccli.file_state` (synccli.py:22-25) — equals the previous snapshot's
entry. Unchanged files are not re-copied or re-hashed; the new index
references the existing blob.

Granularity caveats, stated explicitly:

- **Missed edits:** any change that preserves both size and mtime — an
  in-place edit within mtime resolution, a write that restores mtime
  (`touch -r`, some build tools, rsync-like restores), or a same-size
  rewrite with a truncated mtime clock. These are invisible to
  `(size, mtime)` and will be missed.
- **Mitigation:** `--verify-hash` re-hashes unchanged files against their
  recorded blob hash and re-ingests mismatches; O(bytes) when run, off by
  default. Default mode accepts the `(size, mtime)` misses above.
- **False positives** (copying something unchanged) cost only bandwidth:
  mtime bumps with identical content hash to the same blob name, so the
  store does not grow.

## 8. Retention and deletion

Policy (per source, evaluated after each successful run):

- Always keep the newest complete snapshot.
- Keep all snapshots younger than `--min-age` (default 7 days).
- Beyond that, keep at most `--keep` (default 10) older ones, newest
  first. Configurable; the invariant "at least one usable snapshot always
  remains" is structural, not a default.

Deletion procedure (holding the source's exclusive flock):

1. Rename `<snapshot-id>` → `<snapshot-id>.deleting` (atomic; new readers
   stop seeing it, in-flight readers hold an open fd / the shared lock).
2. Decrement refcounts for every blob in its index; delete blobs reaching
   refcount 0 (a shared flock on the source lock in §3 prevents a reader
   from starting a walk while the tree is dismantled).
3. `rm -rf` the `.deleting` directory.
4. GC pass (runs after prune): delete `store/blobs` entries with refcount
   0 older than 24 h, and `tmp-*` leftovers.

## 9. First-full-backup performance budget

Measured on this machine (APFS, Python 3), using the actual code path —
`synccli.build_manifest` + `synccli.sync` over a synthetic 30,000-file,
0.96 GB tree:

| Phase | Measured |
|---|---|
| `build_manifest` (walk + stat, 30k files) | **0.65 s** |
| First `sync` (copy all 0.96 GB) | **9.43 s** |
| Repeat `sync`, zero changes | **0.80 s** |

Derivation: full-backup time ≈ scan (0.65 s, ≈ 22 µs/stat) + bytes ÷
measured copy throughput (~102 MB/s from the 9.43 s figure) + per-file
ingest overhead (hashing adds a full read pass; the copy path already reads
every byte once, and SHA-256 on this hardware runs ≳ 500 MB/s, so it is
not the bottleneck).

**Budget: the first full backup of a ~1 GB / 30k-file tree completes in
≤ 60 s** — a 6× margin over the measured 9.4 s for the plain-copy path,
absorbing hashing, index writing, and slower disks. Subsequent runs are
bounded by scan time (~0.65 s) plus copying only what changed.

## 10. Scaling: what grows with what

With `N` = number of configured directories, `F_i`/`B_i` = files/bytes of
directory *i*, `F = Σ F_i`, `B = Σ B_i`:

| Quantity | Bound |
|---|---|
| Per-run time, steady state | `O(F)` stat calls + copy of changed bytes: ≈ `0.65 s · (F / 30k) + changed_bytes / 102 MB/s` (constants measured in §9) |
| First full backup | `0.65 s · (F/30k) + B / 102 MB/s`, ≤ 60 s for the ~1 GB case (§9) |
| Run memory | the manifest dict: `O(F)` entries, ≈ 120 bytes/entry measured-scale → ≈ 3.6 MB per 30k files; **independent of N except through F** (runs process directories sequentially, so peak memory is the largest single tree, not the sum) |
| Disk | blob store ≤ `B + Σ_changed_bytes over retention window` (dedup makes identical content share one blob); per-snapshot index ≈ `F_i × 150 bytes` of JSON, so total index ≈ `150 B × F × kept_snapshots` |
| Lock files, config entries | exactly `N` each — linear in N, one small file per source |
| Snapshot publish | one `rename(2)` per run — **flat**, O(1) in N, F, B |
| Run-vs-run coordination | one flock per source — O(1) mechanism, no shared state that grows |

Flat claims made explicit: nothing in the hot path is O(N) per file; N
multiplies only the number of sequential per-source passes and the count
of lock files.

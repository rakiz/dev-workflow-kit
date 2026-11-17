# DESIGN-d1 — `backupctl`

A snapshotting backup tool for the evals result directories, built on the
code already in this directory: `synccli.py` (scan / manifest / change
detection / copy), `snaputil.py` (snapshot listing, pruning, sizing, path
mapping), and validated against `test_synccli.py`'s conventions.

---

## 1. On-disk layout

```
<backup-root>/
  snap-YYYYMMDD-HHMMSS-NN/        # one completed snapshot (immutable once published)
    index.json                    # per-snapshot index: {relpath: {size, mtime, sha, store}}
    <source-name>/...             # copied files, one subtree per configured directory
  .staging/
    tmp-<pid>-<rand>/             # in-progress runs build here, never visible to readers
  .lock                           # run mutex (flock)
  .last_good                      # name of the newest published snapshot (atomic pointer)
```

- Snapshot directory names follow exactly the format `snaputil.list_snapshots`
  already parses (`snaputil.py:8-20`, docstring lines 11-14:
  `snap-<date>-<time>-<seq>`), so listing, ordering, pruning and disk
  accounting reuse `snaputil` unchanged.
- `index.json` paths are mapped back to files with
  `snaputil.safe_snapshot_path` (`snaputil.py:54-63`), which normalizes
  `..` away — restore tooling gets path-traversal safety for free.
- Snapshot sizes for reporting reuse `snaputil.snapshot_disk_usage`
  (`snaputil.py:39-51`).

## 2. Run lifecycle — the core invariant

**Invariant: a directory named `snap-*` under the backup root is always a
complete, self-consistent snapshot.** Everything else follows from
publishing snapshots atomically via `os.rename`.

A run does:

1. **Acquire `.lock`** with `fcntl.flock(LOCK_EX | LOCK_NB)`. If held,
   exit with "run already in progress" (exit code 2). This serializes the
   scheduler vs. a human run — the two can collide in time, only one
   builds at a time. Readers (restore, `list`) never take the lock:
   they only ever see published `snap-*` directories, which are immutable
   (§5 explains why pruning can't yank one mid-read unexpectedly — and
   what the residual risk is).
2. **Pick the base snapshot**: the last name in
   `snaputil.list_snapshots(backup_root)` (sorted oldest-first,
   `snaputil.py:20`), cross-checked against `.last_good`. Load its
   `index.json` as the "old manifest".
3. **Build the new snapshot in `.staging/tmp-<pid>-<rand>/`** (same
   filesystem as the root, so step 5's rename is atomic).
4. For each configured source directory: scan, detect changes, copy
   (§3, §4).
5. **Publish**: write `index.json` into the staging dir via
   write-to-temp + `os.rename`, `fsync` the staging tree's files and the
   directory, then `os.rename(.staging/tmp-..., backup_root/snap-<ts>-<seq>)`,
   then rewrite `.last_good` (also write-temp + rename). The rename is the
   commit point: before it, readers cannot see the run at all (`.staging`
   does not match the `snap-` prefix filter in `snaputil.list_snapshots`,
   `snaputil.py:18`); after it, they see a finished snapshot.
6. **Prune** (§5), release the lock, report.

### Crash at any point

- Death before step 5's rename: only garbage under `.staging/` remains.
  `list_snapshots` never reports it; the next run, after acquiring the
  lock, deletes any `.staging/tmp-*` entries (they can only belong to dead
  runs — the lock proves no live run owns them) and proceeds. No manual
  cleanup, no half-snapshot a reader could trust.
- Death after the rename but before `.last_good` update: the snapshot is
  complete and listed; `.last_good` is merely one behind. Recovery rule:
  **`list_snapshots` order is authoritative, `.last_good` is a hint.** On
  every run start, if `.last_good` names anything other than the newest
  listed snapshot, it is rewritten and the discrepancy logged.

### Corrupt or half-written index recovery

The design makes a half-written `index.json` inside a *published* snapshot
impossible (it is renamed into place before the snapshot itself is
published). But the brief demands a defined recovery anyway — for a
pre-existing root, a damaged disk, or a bug:

When a run (or restore) loads a snapshot's `index.json` and the JSON fails
to parse or fails its self-check (a `file_count` field must equal the
number of entries):

- **Discarded**: the corrupt `index.json` only. The copied file tree is
  kept.
- **Re-derived**: the run rebuilds the index from the tree itself, using
  `synccli.scan_files` + `synccli.file_state` over the snapshot directory
  (`synccli.py:10-25`) — sizes and mtimes come from the copies. Content
  hashes (§4) cannot be re-derived as *source* attestations, so the
  rebuilt index marks every entry `"sha": null`; change detection then
  falls back to size+mtime against that base (which `synccli.changed_files`
  already supports — it compares whatever states it is given,
  `synccli.py:36-42`).
- **Reported**: the run logs `index-rebuilt <snapshot>` on stderr and in
  its summary, and exits 0 if the backup itself succeeded — a rebuilt
  index is degraded metadata, not a failed backup. A restore that hits a
  corrupt index performs the same rebuild read-only (in memory) and warns.

## 3. Scanning and copying — what is reused, what is overridden

Reused as-is:

- `synccli.scan_files(root)` (`synccli.py:10-19`) for enumeration:
  sorted relative paths, dot-directories skipped. The dot-dir skip is
  acceptable for evals results and inherited deliberately.
- `synccli.file_state(path)` (`synccli.py:22-25`) for (size, mtime).
- `synccli.changed_files(old, new)` (`synccli.py:36-42`) for the
  changed/new set.
- `synccli.build_manifest(root)` (`synccli.py:28-33`) as the scan+stat
  pass over each source.

Overridden — each named, located, and justified:

- **`synccli.copy_file` error handling (`synccli.py:62-69`)**: today an
  `OSError` is silently swallowed (`pass` on line 69) *after* the
  destination file may already have been opened and truncated — a failed
  copy can leave a 0-byte destination file that the manifest then can't
  distinguish from content. `backupctl.copy_file` instead copies to
  `dst + ".part"` and renames on success; on `OSError` it removes the
  `.part` file, records the path in the run's `skipped` list, and
  **omits the file from `index.json`**. The index never promises a file
  the snapshot does not contain (brief requirement).
- **`synccli.copy_file` whole-file read (`synccli.py:67`)**:
  `fsrc.read()` loads the entire file into memory. Replaced by
  `shutil.copyfile` (chunked). Memory per copy becomes O(chunk) instead
  of O(largest file).
- **`synccli.sync` manifest write (`synccli.py:85-86`)**: `json.dump`
  straight onto the final path — a crash mid-write leaves a corrupt
  manifest. `backupctl` writes every index/pointer via
  temp-file + `fsync` + `os.rename` (§2 step 5).
- **`synccli.sync` destination semantics (`synccli.py:72-87`)**: `sync`
  mutates one destination in place; `backupctl` never mutates a published
  snapshot — unchanged files are not re-copied but **hard-linked** from
  the base snapshot into the staging dir (`os.link`). Readers of the old
  snapshot are unaffected (same inode, immutable by convention), the new
  snapshot is still a complete self-contained image, and disk cost of an
  unchanged file is one directory entry, not a byte copy.
- **`snaputil.prune_snapshots` (`snaputil.py:23-36`)**: reused for
  ordering and selection, overridden for deletion mechanics (§5).

Note: `synccli.collect_stale` (`synccli.py:45-59`) is not used — it tracks
fresh/stale flags for an in-place sync destination, a concept that does
not exist when snapshots are immutable.

### Vanishing / unreadable source files

Two windows, same answer for scheduler-started and human-started runs:

- **Between listing and copy** (`scan_files` saw it, `copy_file` gets
  `FileNotFoundError`): treated like any copy `OSError` above — no entry
  in the index, path added to `skipped`.
- **Unreadable when reached** (`PermissionError` etc.): same.

The snapshot then contains exactly the files it successfully copied, the
index lists exactly those, and the run reports
`skipped: <n> paths` with the list on stderr and exit code 1 (partial) vs
0 (clean) — identical in both trigger modes; the scheduler just reads the
exit code where the human reads the text.

## 4. Change detection granularity

"Unchanged" is decided per **file**, by `(size, mtime)` equality against
the base snapshot's index — exactly the comparison
`synccli.changed_files` performs on `synccli.file_state` output
(`synccli.py:22-25, 36-42`).

What this granularity can miss, stated explicitly:

- A content change that preserves both size and mtime (e.g. a tool that
  writes in place and restores mtime, or mtime-truncating filesystems
  colliding with same-size writes) is **not detected**; the stale copy is
  hard-linked forward.
- mtime is a float (`st.st_mtime`, `synccli.py:25`); on filesystems with
  coarse timestamps (FAT: 2 s), two edits within one granule with equal
  size are missed.
- A file changed *during* the copy is captured in a torn state — per-file
  copies are not atomic reads. Evals result dirs are write-once per run
  in practice, so this is accepted and documented, not solved.

Mitigation, not a redesign: the copy pass computes a SHA-256 of each file
**as it copies it** (near-free: the bytes are already in memory per chunk;
measured below, hashing adds <0.1 ms/file) and stores it in `index.json`.
It is used for restore-time integrity verification and for the
`--paranoid` run mode (hash every source file regardless of size/mtime),
not for the default change decision.

## 5. Retention and safe deletion

**Policy**: keep the newest `K` snapshots (default `K = 14`), configured
per backup root. Selection reuses `snaputil.prune_snapshots`'s rule
(`snaputil.py:23-36`): oldest-first order from `list_snapshots`, delete
`names[:len-K]`, newest never deleted — so with `K ≥ 1` the user always
retains at least the latest usable snapshot, and pruning runs only
*after* a successful publish (§2 step 6), so at that moment at least one
complete snapshot newer than every deletion candidate exists.

**Overridden: `prune_snapshots`'s direct `shutil.rmtree`
(`snaputil.py:35`)**. Deleting in place races a reader mid-restore (it
would see files vanish under it). `backupctl` instead:

1. `os.rename(snap-X, .staging/del-<snap-X>)` — atomic; from this instant
   no new reader can discover the snapshot (`list_snapshots` filters on
   the `snap-` prefix, `snaputil.py:18`).
2. Waits one grace period before `shutil.rmtree` of the renamed dir:
   deletion candidates are only reaped when `snaputil.is_stale`
   (`snaputil.py:66-73`) says the renamed dir is older than
   `now - grace` (default 24 h) — i.e. each run reaps the *previous*
   runs' tombstones, giving any restore that started before the rename a
   full grace window to finish reading through its already-resolved path.

Residual risk, stated: a restore that holds a path for longer than the
grace period can still lose the tree. POSIX has no cross-process read
lease without reader cooperation; the grace window plus "restores read the
newest snapshot by default" makes the race practically unreachable, and a
restore tool that wants a hard guarantee can hard-link the snapshot into
its own temp dir first (cheap: links, not copies — same trick as §3).

## 6. Performance budget — measured, then derived

Measured in this directory, on this machine (APFS, laptop SSD), using the
existing code (`python3 -m unittest` passes; harness: `synccli.sync` on
generated trees):

| Measurement | Result |
|---|---|
| `synccli.build_manifest` (scan+stat), 5 000 files | 0.12 s → **24 µs/file** |
| `synccli.sync` full copy, 5 000 × 25 KB (128 MB) | 1.38 s → **~92 MB/s** |
| `synccli.sync` full copy, 20 000 × 1 KB | 5.4 s → **271 µs/file** overhead-dominated |
| No-op incremental pass, 20 000 files | **0.52 s** |
| SHA-256 of 1 000 × 25 KB files | 0.078 s → **~0.08 ms/file** |

Derivation for the target — initial full backup of ~1 GB, ~30 000 files
(avg ~33 KB):

- per-file overhead: 30 000 × 271 µs ≈ **8.1 s**
- byte throughput: 1 GB / 92 MB/s ≈ **11 s**
- hashing during copy: 30 000 × 0.08 ms ≈ 2.4 s, largely overlapped with
  I/O (same buffers)

Sum ≈ 20 s measured-equivalent. **Budget: ≤ 60 s** for the initial full
backup of a 1 GB / 30 k-file tree — 3× headroom over the measured 20 s to
absorb slower disks, fsync cost (§2 adds per-file fsyncs only at publish
of the index, per-file `.part` renames add ~1 rename ≈ the measured
271 µs/file is already rename-inclusive via `copy_file`'s makedirs+open
pattern), and colder caches. A machine missing the budget by >2× is
flagged in the run report.

Steady-state incremental run (unchanged tree): scan+stat only ≈ 24 µs ×
files + hard-links for unchanged files (an `os.link` costs on the order
of the stat, ≈ 25–50 µs) → **≈ 2–3 s for 30 k files**, no byte copying.

## 7. Scaling: N directories, F files, B bytes (changed: f, b)

Every bound explicit; N = configured directories (3 → ~36), F/B = total
files/bytes across them, f/b = changed since last snapshot.

| Resource | Bound | Why |
|---|---|---|
| Per-run scan time | **24 µs × F** (measured §6) | one `build_manifest` pass per source; linear in F, independent of snapshot count |
| Per-run copy time | **271 µs × f + b / 92 MB/s** | only changed files are copied (§3) |
| Per-run link time | **≈ 40 µs × (F − f)** | one `os.link` per unchanged file |
| Run memory | **O(F) manifest entries ≈ 200 bytes/entry → 6 MB at F = 30 k, 60 MB at F = 300 k** | two manifests (base + new) in memory, as `synccli.sync` already does (`synccli.py:74-80`); no file content held (chunked copy, §3) |
| Disk per snapshot | **b bytes + (F − f) dir entries (~1 KB inode/entry overhead) + index ≈ 200 B × F** | hard links dedupe unchanged content |
| Total disk | **K × (avg b) + unique content bytes + K × F × ~1.2 KB metadata** | bounded by retention K (§5), not by time |
| Snapshot listing / prune | **O(S)** with S ≤ K + in-flight ≈ K + 1 | `snaputil.list_snapshots` scans one directory level (`snaputil.py:17`) |
| Lock contention | flat: **1 lock file** regardless of N | one mutex per backup root |

What grows with N specifically: F and B are sums over the N sources, so
every F/B bound above inherits N's growth through them; nothing else
(lock count, snapshot count, index count per snapshot = 1) grows with N.
At the projected scale (36 dirs, say 10× today's files → F ≈ 300 k,
B ≈ 10 GB) the derived initial-full-backup time is 300 k × 271 µs +
10 GB / 92 MB/s ≈ 81 s + 109 s ≈ **~3.2 min**, and run memory ≈ 60 MB —
both acceptable for a background job, both derived from the §6
measurements rather than asserted.

## 8. CLI surface (minimal)

```
backupctl run    --root R --sources s1 s2 ...   # one snapshot attempt (§2)
backupctl list   --root R                        # snaputil.list_snapshots + sizes
backupctl prune  --root R --keep K               # §5 deletion, manual trigger
backupctl verify --root R [--snapshot NAME]      # re-hash copies against index
```

`run` exit codes: 0 clean, 1 partial (skipped files, §3), 2 lock held,
3 hard failure (nothing published).

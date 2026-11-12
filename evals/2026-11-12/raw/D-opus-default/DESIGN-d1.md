# DESIGN — `backupctl` (fixture D1)

## 0. Summary

`backupctl` produces immutable, hard-link-deduplicated snapshots of each
configured directory. A snapshot is built in a private staging directory and
becomes visible only through a single atomic `rename(2)` into `snapshots/`,
after its manifest is written and fsynced. Concurrency is controlled with
kernel advisory locks (`fcntl.flock`), which the OS releases when a process
dies, so no crash can leave a stale lock. Change detection reuses
`synccli.py`'s manifest model, with tighter fields. Copying does **not** reuse
`synccli.copy_file` as written, because that function silently drops errors
(see §7).

## 1. Existing code this builds on (and where it diverges)

| `synccli.py` function | Use in backupctl | Divergence + reason |
|---|---|---|
| `scan_files(root)` | Source listing for each configured directory, called as is. | Keeps its rule of skipping dot-*directories* (dot-*files* are still backed up). backupctl adds a per-file `lstat` so that symlinks are recorded as links. Today `open()` in `copy_file` follows symlinks, so a link to `/` content would be copied as data. |
| `file_state(path)` | Basis of `file_state_v2`. | Records `st_mtime_ns` (int) instead of `st_mtime` (float), plus `size`, `ino`, `mode`. Float mtimes compared with `!=` can flap across JSON round-trips and lose sub-µs precision. Also, the snapshot manifest is built from `fstat` **of the opened fd**, not from a separate `stat` (see §5). |
| `build_manifest(root)` | Not called directly; its loop is inlined into the run loop. | Today a file deleted between `scan_files` and `file_state` raises `FileNotFoundError` and aborts the whole sync. backupctl must survive this (§5). |
| `changed_files(old, new)` | Used as is to decide copy-vs-link against the **previous published snapshot's** manifest. | None. It already treats "new or state differs" as changed, which is the rule we want. |
| `copy_file(src, dst)` | Replaced by `copy_file_checked(src, dst) -> Outcome`. `copy_file` stays as a thin wrapper so synccli's behavior and tests are unchanged. | Three problems: (1) `except OSError: pass` swallows the failure, and `sync` then writes a manifest claiming the file, which is exactly the "index promises files it doesn't contain" failure the brief forbids. (2) `fsrc.read()` loads the whole file into memory. (3) It writes in place at `dst` with no fsync, so a crash leaves a truncated file under the final name. The new function streams with `shutil.copyfileobj`, writes `dst.tmp`, fsyncs, `os.replace`s, and returns `copied / vanished / unreadable / unstable`. |
| `sync()` / `MANIFEST_NAME` | Its flow (scan → load old manifest → diff → copy → write manifest) is the skeleton of a run. | Snapshots are never updated in place. The manifest is written to a temp file, fsynced and renamed, and comes **last**. It records what was actually copied, not what was scanned. |
| `collect_stale` | Not used. Unrelated to this problem. | — |

Observed in passing, and **not** changed by this design (the user would have
to request it): `sync()` never removes destination files that were deleted
from the source, and it records failed copies in its manifest.

## 2. On-disk layout

```
<backup_root>/
  <dir_id>/                      # one per configured directory (stable id from config)
    run.lock                     # flock: one writer per dir
    read.lock                    # flock: shared by readers, exclusive by deleters
    staging/<run_id>/            # private to a live or dead run; never read by others
        files/...  journal.jsonl
    snapshots/<UTC-ts>_<run_id>/ # published = complete, by construction
        files/...  manifest.json
    trash/<name>/                # snapshots being deleted
    runs/<run_id>.json           # run report
```

**Completeness invariant.** A directory under `snapshots/` is complete, and
contains `manifest.json`, because the only way anything gets there is
`rename(staging/<run_id>, snapshots/<name>)`. That rename runs after every
file and the manifest have been fsynced, and the parent directory is fsynced
after it. Readers only ever enumerate `snapshots/`, so they never need to ask
whether a run finished.

## 3. A run, step by step (per configured directory, sequentially)

1. `flock(run.lock, LOCK_EX | LOCK_NB)`. If it is already held, another run
   is working on this directory: report `busy` for it and continue to the
   next directory. Exit code 75 if every directory was busy. `--wait` blocks
   instead. Directories are locked independently, so a scheduler run and a
   manual run on different directories proceed in parallel.
2. With the lock held, anything in `staging/` belongs to a dead run.
   **Adopt** its `journal.jsonl`: each line is `{rel, state}` and is appended
   only after that file's `os.replace` succeeds, with fsync every 256 entries
   and at the end. A journaled file whose source state still equals the
   journal entry is moved into the new staging dir rather than re-copied.
   Everything else in the dead staging dir is deleted. This is how
   repeatedly interrupted first backups still make progress without manual
   cleanup.
3. Load `prev = manifest.json` of the newest published snapshot (or `{}`).
4. `scan_files(src)`. For each `rel`, `lstat` it. On ENOENT, record it as
   `vanished` and continue. Then decide with `changed_files(prev, {rel: state})`:
   * unchanged → `os.link(prev_snapshot/files/rel, staging/files/rel)`
   * changed / new → `copy_file_checked`
5. Write `manifest.json` (`files`: rel → state of what is in the snapshot;
   `skipped`: rel → reason; `started`/`finished`; source path; tool version)
   to a temp file, fsync it, and rename it into place.
6. `chmod` the snapshot files read-only, then rename staging to
   `snapshots/<ts>_<run_id>` and fsync `snapshots/`.
7. Write the run report, then run retention (§6).

**Immutability.** Files are shared across snapshots by hard link, so
modifying one in place would corrupt every snapshot that shares it. Snapshot
files are mode `0444`, and restore tooling must copy *out* and never open for
writing. This is the reason for chmod in step 6.

**What "point in time" means.** There is no filesystem snapshot, so a
snapshot is *per-file consistent*: each file is a complete, untorn image as
of the moment it was read. The set of files spans the `started..finished`
window recorded in the manifest. Files from different runs are never mixed:
a linked file is byte-identical to its state in `prev`, and the manifest
states that `state`.

## 4. Change detection: granularity and blind spots

The decision is made **per file, from metadata**: `(size, mtime_ns, ino, mode)`
must equal the previous snapshot's entry. File contents are not read for
unchanged files.

It misses:
- edits that keep size and restore mtime (`touch -r`, `rsync -t`, some
  editors and archive extractors);
- same-size edits within one mtime tick on coarse-timestamp filesystems
  (FAT 2 s, some network mounts);
- an edit that lands while the previous run was reading the file but did not
  change its size or mtime by the time of its `fstat`.

Mitigation: `backupctl run --verify` hashes the content (sha256, stored in
the manifest) for every file. It is opt-in, because it costs a full read of
the tree. Including `ino` catches the "atomic save via rename" pattern even
when the mtime is preserved.

## 5. Vanishing, unreadable, and changing source files

`copy_file_checked` opens the source first and then `fstat`s **the fd**. It
records that state, copies, and `fstat`s again:

| Situation | Snapshot contains | Manifest | Run report / exit |
|---|---|---|---|
| ENOENT at lstat or open | nothing for `rel` | `skipped[rel]="vanished"` | listed; exit 0 (normal churn) |
| EACCES / EIO / other OSError | nothing for `rel` | `skipped[rel]="unreadable: <errno>"` | listed; **exit 2 (partial)** |
| state changed between the two fstats | after one retry, nothing | `skipped[rel]="unstable"` | listed; exit 2 |
| vanished after open | the full copy (the fd keeps the data) | normal entry | — |

There is one rule throughout: the snapshot never contains a file the
manifest does not list, and never a file older than this run in place of
one that could not be read. The previous run's copy is not carried forward,
because that would mix runs. That older version is still available in the
previous snapshot. A partial snapshot is still published, since it is
complete with respect to its own manifest, and it is marked
`"partial": true`.

Behavior does not depend on the caller. There are no TTY checks and no
prompts. The scheduler and a person get the same exit code, the same
`runs/<id>.json`, and the same stdout summary.

## 6. Retention and safe deletion

**Policy.** Keep the newest 7 snapshots, plus the newest snapshot of each of
the last 14 days, plus the newest snapshot of each of the last 8 weeks. Two
hard rules apply on top of this policy:
- never delete the newest snapshot;
- never delete the newest **non-partial** snapshot.

So deletion cannot leave the user without a usable snapshot.

**Concurrency with readers.** Restore tooling takes `flock(read.lock, LOCK_SH)`
for the duration of its read, including when it starts from a name it
listed earlier. Retention tries `LOCK_EX | LOCK_NB`. If that fails, a reader
is active, so deletion is skipped and retried next run (nothing is lost; the
root just grows by one run's worth). Holding the exclusive lock, retention
`rename`s each victim into `trash/` (atomically invisible) and `rmtree`s it.
Leftovers in `trash/` are deleted by the next run. Hard links mean deleting
an old snapshot never removes data a newer snapshot still references.

Publishing a new snapshot does not need `read.lock`. It only adds a new name.

## 7. Performance budget for the initial ~1 GB full backup

**Measured** on this machine (Apple M3 Max, APFS SSD), with a synthetic tree
of 20,000 files × 50 KB = 1.0 GB in 200 directories, using the code in this
directory:

| Step | Time |
|---|---|
| `synccli.build_manifest` (scan_files + stat) | 1.9 s |
| `synccli.sync` first run (naive copy, no fsync) | 9.7 s |
| `synccli.sync` second run (no-op) | 1.8 s |
| streamed copy + fsync + `os.replace` per file (backupctl's copy path) | 14.3 s |
| 20,000 `os.link` calls (backupctl's unchanged path) | 11.7 s |

**Derivation.** The full backup is about 1.9 s of scanning plus 14.3 s of
durable copying, so ≈ 16 s. Manifest and journal writes are negligible next
to that (on the order of a few MB of JSON). **Budget: ≤ 30 s** on a local
SSD, which is about 2× headroom over the measured 16 s. On a spinning disk
or network target, the copy term scales with the device: 1 GB / bandwidth
plus about 20k fsyncs, and that term should be re-measured on the target.

**Measured caveat.** An unchanged incremental run is **not** close to free
for small files. Measured, it is about 1.9 s + 11.7 s ≈ 14 s, dominated by
the cost of creating one hard link per file. Per-run cost is therefore
O(file count) even with zero changes. This is the price of every snapshot
being a self-contained tree that a restore can read without consulting
other snapshots. If it matters, the next lever is directory-level reuse:
skip and link whole unchanged subtrees, which needs a per-directory
manifest hash. That is not part of this design.

## 8. Scaling: 3 directories today, a few dozen later

| Quantity | Grows with | Flat in |
|---|---|---|
| Per-run time | total files across all dirs (stat + link per file) + changed bytes (copy) | number of retained snapshots |
| Memory | file count of the **largest single** directory (two manifests in RAM; dirs are processed one at a time) | number of dirs, snapshot count |
| Disk (data) | unique file versions ever retained | number of snapshots of unchanged files (shared by link) |
| Disk (metadata) | files × retained snapshots (one dirent/link each) + manifest size × snapshots | — |
| Locks / concurrency | one `run.lock` + `read.lock` per dir | — |
| Retention work | snapshots deleted × their file count | — |

Adding directories adds config entries and per-run time linearly. No global
lock or global index is introduced, so contention stays flat.

## 9. Failure matrix (crash at any point)

| Crash point | Visible to readers | Next run |
|---|---|---|
| during scan/copy | nothing (staging is private) | adopts journaled files, discards the rest |
| after manifest, before publish rename | nothing | adopts and finishes |
| after rename, before dir fsync | either nothing or a complete snapshot (rename is atomic) | normal |
| during retention rmtree | the victim is already gone from `snapshots/` | empties `trash/` |
| lock holder killed | — | kernel already released the flock |

## 10. Test plan (added beside `test_synccli.py`, `python3 -m unittest`)

- A vanish-between-scan-and-stat case (monkeypatch `os.lstat`) produces
  `skipped=vanished`, and the run continues.
- An unreadable file (chmod 000) is omitted from both the snapshot and the
  manifest, with exit 2.
- A run killed after N files (raise from a hook) leaves `snapshots/`
  unchanged. The next run adopts the journal and does not re-copy those N
  files.
- Two concurrent runs: exactly one gets `busy`.
- Retention while a `LOCK_SH` reader is held deletes nothing, and the newest
  non-partial snapshot always survives.
- An unchanged file is a hard link (same `st_ino`) to the previous snapshot's
  copy.
- The existing 6 synccli tests still pass, since `copy_file` keeps its
  signature and behavior.

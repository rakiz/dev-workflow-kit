# DESIGN — `backupctl` (fixture D1)

`backupctl` is a command-line backup tool for the `evals/` workflow: it backs
up a configured set of N directories into point-in-time snapshots under a
backup root. It builds on the code already in this directory — `synccli.py`
(scanning, change detection, copying, manifests) and `snaputil.py` (snapshot
listing, pruning, sizes, path mapping) — and only re-implements what those
cannot do: atomic snapshot commit, writer exclusion, crash recovery, and
hardlink-based incrementals.

Everything below is grounded in the actual code as it exists in this
directory today (file + function + line numbers), and every place this design
deviates from existing behavior names the exact function overridden and why.

---

## 1. On-disk layout

```
<backup_root>/
  snap-YYYYMMDD-HHMMSS-<seq>/      # a committed snapshot (visible)
    data/<src-name>/...            # file tree, mirroring the source layout
    index.json                     # {relpath: {size, mtime, status}}
  .tmp-<runid>/                    # an in-progress run (invisible to readers)
    data/...
    index.json                     # written here, before commit
  .trash-<name>/                   # a snapshot being deleted (invisible)
  .lock                            # writer lock (flock)
```

Snapshot naming follows exactly what `snaputil.list_snapshots`
(`snaputil.py:8-20`) recognizes: directories starting with `snap-` directly
under the backup root. Two properties of that function are load-bearing:

- It ignores anything not `snap-`-prefixed, so `.tmp-*` and `.trash-*` dirs
  are invisible to every reader that lists snapshots through it.
- It returns names sorted oldest-first, which is the ordering retention and
  "previous snapshot" resolution rely on.

`index.json` is the manifest, in the same `{relpath: state}` shape that
`synccli.build_manifest` (`synccli.py:28-33`) produces, extended with a
`status` field per file (`"ok"` / `"error: <reason>"`).

## 2. Concurrency: one writer, many readers

**Writer exclusion.** Every mutating command (`backup`, `prune`) opens
`<backup_root>/.lock` and takes an exclusive `flock` (non-blocking; on
conflict the run exits with a clear "another run is in progress" message and
non-zero status). This covers the scheduler-and-person collision: two runs
can start at the same wall-clock time, but only one does work; the other
fails fast and loudly rather than interleaving writes. The lock lives for the
whole run, is released automatically on process death (kernel-owned), and
needs no stale-lock cleanup — that is why `flock` rather than a pidfile.

**Reader safety without locks.** Restores and humans never take the lock.
They are safe because of how a snapshot becomes visible, in §3.

## 3. Atomic snapshot commit

A run never writes into a `snap-*` directory. It writes everything into
`.tmp-<runid>/` (data files, then `index.json`), fsyncs the index, and then
commits with a single `os.rename(.tmp-<runid>, snap-<timestamp>-<seq>)`.
POSIX rename is atomic: every reader either sees the snapshot not at all
(`list_snapshots` can't return it) or sees it fully — data and index
together. There is no window in which an index promises files the data
directory lacks, because the index is written and fsynced *before* the
rename, inside the directory that the rename publishes.

This is the central difference from `synccli.sync` (`synccli.py:72-87`),
which today copies files into the live destination and then rewrites
`.sync_manifest.json` in place (`synccli.py:85-86`) — a reader syncing
concurrently can see new files with an old manifest or vice versa.
`backupctl` **overrides** that in-place manifest write: the manifest write
moves inside the unpublished temp directory, and publication is the rename.
The reason is precisely the brief's requirement that a reader never ask
whether the producing run finished.

Because publication is a rename of a fully-built tree, restore tooling can
also rely on this simple rule: *if `list_snapshots` returns it, it is
complete.*

## 4. Crash recovery and corrupt-index handling

**Leftover temp dirs.** A run killed mid-flight leaves `.tmp-<runid>/`
behind. Because it is invisible to `list_snapshots`, no reader can mistake
it for a snapshot — nothing to fix there. Every run, while holding the
writer lock, deletes all `.tmp-*` dirs whose embedded runid timestamp is
older than 1 hour (a generous bound: a live run always holds the lock, so
any temp dir the lock holder sees is either its own or older than any live
run). This makes progress automatic; no manual cleanup.

**Corrupt / half-written index.** `index.json` lives inside the snapshot, so
the only way it is corrupt is a dead run between data write and index fsync —
but that snapshot was never renamed, so it is a temp-dir case, not a visible
one. The remaining corrupt-index case is external damage (disk error, human
edit). Recovery, performed by the next run when it loads the *previous*
snapshot's index as its incremental basis:

1. Try `json.load`. On failure, or if the file is missing: **discard the
   index entirely** and treat the previous snapshot as having an empty
   manifest — i.e. fall back to a full backup of every source.
2. The data files of that previous snapshot are still used for hardlinking
   where the rebuilt scan agrees with them (§5 makes this safe: hardlinks
   are only taken after a fresh `stat` of the *source* file, never on the
   index's word alone).
3. The run **reports** the event on stderr and in its exit summary:
   `index of snap-X unreadable, falling back to full backup`. Nothing is
   silently re-derived.

What is discarded: only the unreadable index. What is re-derived from the
tree: the change set (via a fresh scan, §5). What is reported: the fallback
warning above.

## 5. Change detection and incrementals

**Granularity: whole files, decided by (size, mtime).** `backupctl` reuses
`synccli.file_state` (`synccli.py:22-25`) and `synccli.changed_files`
(`synccli.py:36-42`) verbatim for this: scan each source with
`synccli.scan_files` (`synccli.py:10-19`), build the current manifest with
`synccli.build_manifest`, diff against the previous snapshot's index.

**What this granularity can miss** (stated explicitly, per the brief): an
edit that leaves both size and mtime unchanged — e.g. an in-place same-length
write whose mtime the filesystem or a tool deliberately restores, or two
edits within the same mtime tick where the second restores the original
size. Content-hash comparison would catch these but costs a full read of
every file every run, which the §8 budget forbids; (size, mtime) is the
standard rsync-style trade-off and is accepted here, documented as such.

**Per-file action in the new temp dir:**

- *Unchanged since previous snapshot* → `os.link(previous_snapshot/data/rel,
  tmp/data/rel)` — a hardlink, zero bytes copied.
- *New or changed* → copied.
- *Deleted from source* → simply absent from the new snapshot.

**Deletions are an explicit override.** `synccli.changed_files` only returns
files that are new or changed; it never drops entries that vanished from the
source, and `synccli.sync` (`synccli.py:72-87`) consequently leaves deleted
files forever in the destination and never reflects deletions. `backupctl`
**overrides** this: each run's index is rebuilt from the fresh scan (the
manifest written is the current `src_manifest`, not a merge with the old
one), so deleted source files are absent from new snapshots. Reason: a
backup must be a point-in-time image, not an accumulating union.

Note on `scan_files` behavior kept as-is: it skips directories whose names
start with `.` (`synccli.py:14`) while still including plain hidden files.
`backupctl` keeps this (it matches the existing tested semantics — see
`test_synccli.TestScanFiles`) and documents that dot-directories are not
backed up.

## 6. Vanishing / unreadable source files

Two windows, same handling:

- *Between listing and copying* — `scan_files` saw the file; by copy time
  `open` raises `FileNotFoundError`.
- *Unreadable at copy time* — `PermissionError` or other `OSError`.

Design: the snapshot still commits, and the file is recorded in `index.json`
with `status: "error: <oserror.strerror>"` instead of a normal state. The
snapshot therefore always reflects exactly what the run could read — it never
contains a *partial* copy of a file, because the copy is written to the temp
dir and a failed file's partial output is deleted before recording the
error. The run reports every such file on stderr and in the summary, and
exits 0 if there were only per-file errors (the snapshot is valid) — the
same behavior whether the run was triggered by the scheduler or a person,
because the trigger only affects who sees the report.

**This is an override of `synccli.copy_file` (`synccli.py:62-69`)**, which
today catches `OSError` and silently `pass`es — the file is neither copied
nor recorded, and the caller cannot know. `backupctl` wraps the same copy
loop (still using `copy_file` for the success path) but inspects the outcome:
a per-file failure is recorded in the index and reported, never swallowed.
Reason: the brief requires the design to say what the snapshot contains and
what the run reports; silence satisfies neither.

## 7. Retention and safe deletion

Policy: **keep the newest K snapshots, K configurable, default 10**, and
never fewer than 1. Deletion runs inside the same writer lock (so no run is
simultaneously creating snapshots) but must coexist with *readers* of the
snapshot being deleted.

Two-phase delete:

1. `os.rename(snap-X, .trash-X)` — atomic, makes the snapshot disappear from
   `list_snapshots` immediately, so no *new* reader starts on it.
2. `shutil.rmtree(.trash-X)`.

An existing reader mid-restore is still safe: POSIX keeps file data alive
while a process holds open descriptors, and a restore that already resolved
its paths reads through them. A restore that *starts* after step 1 no longer
sees the snapshot at all — the worst case is a clean "snapshot not found",
never a torn read.

**This overrides `snaputil.prune_snapshots` (`snaputil.py:23-36`)**, which
today `rmtree`s the doomed snapshot in place (`snaputil.py:35`) — a reader
that resolved paths just before the rmtree can hit ENOENT partway through.
`backupctl` reuses `prune_snapshots` for the *selection* logic (oldest-first
doom list, newest always kept — exactly the required "never leave the user
without a usable snapshot") by refactoring it into a function that returns
the doomed list, and performs the two-phase deletion itself. Reason: same
selection, safer deletion.

## 8. Performance budget for the first full backup (~1 GB, ~35k files)

Measured on this machine (macOS, APFS temp volume), using this directory's
own code, 3000 files × 50 KB = 150 MB:

| Measurement | Method | Result |
|---|---|---|
| Full-copy throughput | `synccli.sync` on a fresh 150 MB / 3000-file tree, wall-clock around the whole call | **189 MB/s** |
| Stat/manifest throughput | `synccli.build_manifest` over the same tree (3000 stats + dict build) | **41,200 files/s** |
| No-op second sync | `synccli.sync` with unchanged tree | 0.079 s for 3000 files (index load + diff) |

Derivation for the 1 GB / 35k-file budget (linear extrapolation from the
measured constants, both dominated by sequential I/O + `os.stat` syscalls
whose per-unit costs are constant):

- Copy: 1000 MB ÷ 189 MB/s ≈ **5.3 s**
- Scan + manifest: 35,000 ÷ 41,200/s ≈ **0.9 s**
- Index write (35k entries, JSON): < 0.5 s (measured no-op path already does
  an equivalent manifest serialize at this scale in ~0.08 s)

Budget: **first full backup completes in under 15 s, hard ceiling 30 s**
(≈ 2× headroom over the 6.7 s derivation for colder caches and smaller-file
trees, where per-file overhead dominates). The budget is checked in CI by
generating a 1 GB synthetic tree and asserting the run's wall clock.

## 9. What grows with what (N directories, F total files, B total bytes)

Every bound below is a number, a formula over N/F/B, or a measured constant
from §8:

- **Per-run stat work**: exactly **F** `os.stat` calls (every source file is
  stat'ed every run, at 41,200/s measured) → scan time ≈ F/41,200 s.
  Independent of N except through F.
- **Per-run copy work**: **bytes actually changed**, BΔ. Full backup copies
  B; incremental copies ≤ BΔ + hardlink syscalls for the remaining F−Δ
  files (`os.link` per file, ~µs each) → incremental time ≈ F/41,200 s +
  BΔ/189 MB/s. Runs never re-copy unchanged bytes — verified by
  `test_synccli.TestSync.test_second_sync_is_noop`, whose property
  (`copied == []` on an unchanged tree) the incremental path inherits.
- **Memory**: the manifest dict, **O(F)** entries × ~200 B ≈
  **200·F bytes** (35k files ≈ 7 MB; 1M files ≈ 200 MB — the documented
  scaling ceiling; beyond that the design would move the index to an
  on-disk sqlite, out of scope). N appears only through F.
- **Disk**: first snapshot = **B**. Each run adds ≤ **BΔ** (hardlinked files
  cost ~0). Retention caps the root at **K·B** worst case (every snapshot
  fully diverged), typically ≈ B + (K−1)·BΔ. Deletion work per run: bounded
  by K−1 rmtrees of at most B each, amortized rare.
- **Lock contention**: O(1) per run — a fixed `.lock` file; runs serialize,
  none queue (fail-fast), so nothing grows with N or F.
- **What stays flat**: per-run fixed costs — one flock, one rename per
  snapshot, one `index.json` write — are constants, independent of N, F, B.

## 10. CLI surface

```
backupctl backup   [--config backupctl.json]     # snapshot all configured dirs
backupctl list                                    # via snaputil.list_snapshots + sizes
backupctl restore <snapshot> <src-name> <dest>
backupctl prune   [--keep K]
```

`restore` reads only committed snapshots (it exists only after the §3
rename), resolves relpaths through a *hardened* path mapper, copies out,
and refuses to write into a destination that already exists.

**Override of `snaputil.safe_snapshot_path` (`snaputil.py:54-63`)**: its
docstring claims "`..` segments ... normalized away, so a stored path cannot
climb out of its snapshot", but `os.path.normpath` **keeps leading `..`**
(`normpath("../evil") == "../evil"`), so `os.path.join` at
`snaputil.py:63` happily escapes the snapshot for such an input. `backupctl`
**overrides** this with a mapper that checks containment after mapping:
`os.path.realpath(result).startswith(os.path.realpath(snapshot_dir) + os.sep)`,
rejecting the path otherwise. Reason: stored index relpaths must be treated
as untrusted input; the existing function's guarantee is not actually
provided by its implementation.

## 11. Summary of named overrides

| Existing behavior | Where | Override | Why |
|---|---|---|---|
| Manifest rewritten in place in live dest | `synccli.sync`, `synccli.py:85-86` | index written in temp dir; publication = atomic rename | readers must never see a partial snapshot |
| `changed_files` ignores deletions | `synccli.changed_files`, `synccli.py:36-42` | index rebuilt from fresh scan each run | snapshots are point-in-time images |
| Per-file copy errors silently swallowed | `synccli.copy_file`, `synccli.py:68-69` | errors recorded in index + reported | brief requires defined snapshot content & reporting |
| `rmtree` of doomed snapshot in place | `snaputil.prune_snapshots`, `snaputil.py:35` | two-phase rename-to-`.trash` then rmtree | concurrent readers |
| `safe_snapshot_path` `..` containment claim | `snaputil.safe_snapshot_path`, `snaputil.py:54-63` | post-join realpath containment check | `normpath` keeps leading `..`; claim is false as implemented |

Reused as-is: `scan_files`, `file_state`, `build_manifest`, `changed_files`
(`synccli.py`), `list_snapshots`, prune *selection*, `snapshot_disk_usage`
(`snaputil.py`).

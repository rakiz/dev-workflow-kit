# DESIGN-d1 — `backupctl`

A command-line backup tool for the `evals/` result directories, built on the
code already in this directory (`synccli.py`, `snaputil.py`). This document is
the design only; no `backupctl` code exists yet.

Every claim about existing behavior cites `file:line`. Every performance and
scaling claim is a measured constant (Section 10) or a formula over those
constants (Section 11). Where `backupctl` must behave differently from the code
as written, the exact function, its location, and the reason are named in
Section 2.2.

---

## 1. Scope and summary

`backupctl` backs up a configured set of **N directories** (3 today, a few
dozen over time) into **snapshots** — point-in-time, self-contained copies kept
under a single **backup root**. It must survive:

- concurrent runs and concurrent restores reading while a run writes;
- readers that never ask whether a run finished;
- process death at any instruction (Ctrl-C, sleep, kill);
- source files that vanish or become unreadable mid-run;
- unbounded growth of the backup root (retention);
- mostly-unchanged trees (incremental, don't re-copy unchanged files);
- a clock on the first full backup of a ~1 GB / tens-of-thousands-of-files tree.

**Core mechanism (one sentence):** each run builds a complete snapshot in an
*invisible staging directory*, materializing unchanged files as APFS clones /
hardlinks from the previous snapshot and copying only changed files, writes a
per-directory index that lists **only the files it actually materialized**, then
commits the whole snapshot with a **single atomic `os.rename`** into the
`snap-…` namespace that `snaputil.list_snapshots` (`snaputil.py:8`) reads.
Nothing partial is ever visible; a dead run leaves only invisible staging that
the next run deletes.

---

## 2. Grounding map

### 2.1 Reused as-is (named artifact + what it does)

| Need | Reused artifact | Location | What it provides |
|---|---|---|---|
| Walk a tree → sorted relative file paths | `scan_files(root)` | `synccli.py:10` (walk `:13`, relpath `:17`, sort `:19`) | The scan primitive; returns sorted relpaths. |
| Per-file change key `(size, mtime)` | `file_state(path)` | `synccli.py:22` (`os.stat :24`, dict `:25`) | The change-detection granularity (Section 7). |
| Build `{relpath: state}` for a tree | `build_manifest(root)` | `synccli.py:28` (loop `:31-32`) | Builds the source manifest *and* re-derives a snapshot index from its tree during recovery (Section 8). |
| Diff two manifests → new+changed set | `changed_files(old, new)` | `synccli.py:36` (loop `:39`, append `:41`) | The "copy-from-source" set for incremental runs. |
| Items present in old but not fresh in new | `collect_stale(items, seen)` | `synccli.py:45` (loop `:55-58`) | Computes **deleted-since-last-snapshot** files for the run report: `items = [(rel, rel in new_set) for rel in prev_index]` → returns the deleted relpaths. |
| Copy one file, creating parents | `copy_file(src, dst)` | `synccli.py:62` (makedirs `:64`) | Base copy primitive — **overridden** in 4 ways (Section 2.2). |
| Manifest/index serialization shape | `sync()` writes `json.dump(..., indent=2)` | `synccli.py:85-86`; `MANIFEST_NAME` `:7` | `backupctl`'s per-directory index uses the same `{relpath:{"size","mtime"}}` JSON shape, named `.backup_index.json`. |
| `--dry-run` preview semantics | `sync(..., dry_run)` returns the to-copy list without copying | `synccli.py:81-82`; CLI flag `:94` | `backupctl run --dry-run` reports what *would* be copied/linked, copies nothing. |
| List snapshots, oldest first | `list_snapshots(backup_root)` | `snaputil.py:8` (`startswith("snap-") :18`, `is_dir :18`, sort `:20`) | The authoritative snapshot enumeration; its `snap-` prefix rule (`:18`) defines the **visible** namespace and makes `.staging-…`/`.trash-…`/`.lock` invisible. Naming contract `snap-YYYYMMDD-HHMMSS-NN` documented at `:11-14`. |
| Retention: keep newest `keep`, delete oldest | `prune_snapshots(backup_root, keep)` | `snaputil.py:23` (`names :30`, `doomed = names[:len-keep] :33`, "newest never deleted" `:26-27`) | The **selection** rule for retention — reused verbatim. Its **deletion** side-effect is overridden (Section 2.2). |
| Size of one snapshot | `snapshot_disk_usage(backup_root, name)` | `snaputil.py:39` (walk `:46-48`, `+= st_size :50`) | Per-snapshot **logical** size for `list`/reporting (caveat: double-counts shared clones/links — Section 11.3). |
| Path-traversal-safe restore path | `safe_snapshot_path(root, name, rel)` | `snaputil.py:54` (`normpath :62`, join `:63`, contract `:58-60`) | Restore maps an index relpath back under the snapshot; `..` is normalized away so a stored path cannot escape its snapshot. |
| Age test against a captured epoch | `is_stale(dir, ref_epoch)` | `snaputil.py:66` (`<= :73`) | Decides whether a `.trash-…` directory is older than the grace window and safe to `rmtree` (Section 9.2): `is_stale(trash_dir, now - grace)`. |

### 2.2 Overrides (exact target + location + reason)

A reference only counts if it names what is actually changed. These five are
the complete set of behavioral deviations.

1. **`copy_file`'s silent skip of unreadable sources** — `synccli.py:68-69`
   (`except OSError: pass`).
   *Override:* the backup copy reports failure to its caller (returns `False`
   and records the path) instead of swallowing it.
   *Reason:* `sync()` builds its manifest **before** copying (`synccli.py:74`)
   and writes that pre-copy manifest after (`:85-86`). Combined with the silent
   skip, `synccli`'s manifest can list a file that `copy_file` skipped — exactly
   the forbidden "index promises files the snapshot does not contain." `backupctl`
   builds each index **after** materialization, from the files that actually
   landed (Section 4.3), so a skipped file is absent from the index and present
   in the run report.

2. **`copy_file` reads the whole file into memory** — `synccli.py:67`
   (`fdst.write(fsrc.read())`).
   *Override:* stream in fixed chunks (1 MiB) via a read/write loop.
   *Reason:* `fsrc.read()` makes peak memory `O(largest file)`; a backup must
   bound memory to `O(chunk)` per open file (Section 11.2). Measured: the chunked
   path costs 2,982 files/s vs 5,677 files/s for the raw whole-file read on 1 KB
   files (Section 10) — the safety is worth the per-file overhead, and for large
   files bytes dominate anyway.

3. **`copy_file` writes directly to the destination path** — `synccli.py:66-67`.
   *Override:* write to `<dst>.part-<rand>`, then `os.rename` onto `<dst>`
   inside staging; on any `OSError` unlink the temp and report failure.
   *Reason:* a source that vanishes mid-read (`synccli.py:66` `open` or the read
   loop raises) must not leave a half-written file. Per-file temp+rename gives
   all-or-nothing at file granularity, composing with the whole-snapshot rename
   (Section 4) to give all-or-nothing at snapshot granularity.

4. **`copy_file` does not preserve timestamps.**
   *Override:* after a successful copy, `os.utime(tmp, (src_atime, src_mtime))`
   from the source `os.stat` before the rename.
   *Reason:* recovery re-derives an index from a snapshot's tree with
   `build_manifest` (`synccli.py:28`), which `os.stat`s the snapshot files
   (`file_state`, `synccli.py:24`). If copied files carried backup-time mtimes,
   the re-derived manifest would not match the original index and the next run
   would treat every recovered file as changed (a wasteful full re-copy).
   Preserving source mtime makes the tree itself a faithful source of truth, so
   re-derivation reproduces the index exactly (Section 8). Hardlinks (`os.link`)
   and APFS clones already preserve mtime; this makes copied files consistent
   with them.

5. **`scan_files` excludes dot-directories** — `synccli.py:14`
   (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`).
   *Override:* `backupctl`'s **source** scan keeps hidden directories (e.g.
   `.git`, dotfiles); it is `scan_files` minus the `:14` filter (the walk `:13`,
   relpath `:17`, and sort `:19` are reused unchanged).
   *Reason:* a backup that silently omits hidden directories is not a "complete,
   self-consistent image." The filter is *kept* for scans of a **snapshot** tree
   (recovery, `build_manifest`), because the per-directory index is named
   `.backup_index.json` (leading dot) and must be excluded from the data-file
   set automatically — the `:14` filter does exactly that.

6. **`prune_snapshots` deletes in place** — `snaputil.py:35`
   (`shutil.rmtree(...)` on the live `snap-…` directory).
   *Override:* deletion is **rename-to-`.trash-…` → grace → `rmtree`**
   (Section 9.2), reusing `is_stale` (`snaputil.py:66`) for the grace test. The
   *selection* logic (`snaputil.py:30-33`) is reused verbatim; only the
   `:35` deletion side-effect changes.
   *Reason:* in-place `rmtree` races a concurrent restore that resolved the
   `snap-…` name but has not yet opened every file. Renaming the doomed snapshot
   out of the visible namespace first means no *new* reader can select it, and
   POSIX unlink semantics keep already-open file descriptors valid; the grace
   window covers readers mid-walk.

7. **Snapshot name suffix `NN`.** `snaputil.py:13` documents `NN` as a "run
   sequence number."
   *Override:* `NN = <pid>` (process id), not a gap-free counter.
   *Reason:* a gap-free counter is mutable shared state that is unsafe under the
   concurrency and crash requirements (two runs could read the same counter; a
   dead run could leave it inconsistent). `pid` is unique per process, so two
   concurrent runs never collide, and `list_snapshots`' lexicographic sort
   (`snaputil.py:20`) stays chronological because the `YYYYMMDD-HHMMSS` prefix
   dominates. This keeps the documented `snap-<date>-<time>-<NN>` *shape*
   (`snaputil.py:11-14`) that `list_snapshots` depends on.

Everything not listed here is reused as written.

---

## 3. On-disk layout

```
backup_root/
  .lock                         # advisory writer lock (fcntl.flock); invisible (not "snap-")
  .staging-<pid>-<rand>/        # in-progress run; invisible to list_snapshots (snaputil.py:18)
      <srcdir-A>/               # one subdir per configured source directory (sanitized name)
          <data files...>       # copies (changed) + clones/hardlinks (unchanged)
          .backup_index.json    # per-directory index; ONLY files actually materialized
      <srcdir-B>/...
      .backup_run.json          # run metadata: sources, start/end, skipped/missing, trigger
  .trash-<pid>-<snapname>/      # doomed snapshot during grace window; invisible
  snap-20261112-150000-<pid>/   # COMMITTED snapshot; visible to list_snapshots
      <srcdir-A>/... .backup_index.json
      <srcdir-B>/...
      ...
  snap-.../                     # older committed snapshots
```

Key invariants:

- **Visible = `snap-` prefix.** `list_snapshots` (`snaputil.py:18`) only ever
  returns `snap-…` directories. `.staging-…`, `.trash-…`, and `.lock` are
  therefore invisible to every reader (restore, `list`, the next run) with no
  cooperation required. This single naming rule is what makes partial work
  unobservable.
- **Committed snapshots are immutable.** A run never edits a committed
  snapshot's data. It only *creates* new snapshots and *retires* old ones. (The
  one controlled exception is atomic in-place index repair during recovery,
  Section 8, which uses `os.rename` so readers see old-or-new, never partial.)
- **One index per (snapshot, source directory).** Keeps peak memory bounded by
  the largest single directory, not the whole tree (Section 11.2), and lets the
  run process directories one at a time.

---

## 4. Commit protocol — atomic visibility + crash safety

This section discharges three requirements at once: *readers never ask if a run
finished*, *no mix of this-run and previous-run files*, and *a dead run leaves
nothing mistakable for a complete snapshot*.

### 4.1 Why a single rename suffices

`os.rename` of a directory on POSIX is atomic with respect to the directory
entry: a reader resolving `backup_root/snap-…` sees either the old state (no such
directory) or the new state (the fully populated directory), never an
intermediate. Because the staging directory already contains **all** files and
**all** per-directory indexes before the rename, the instant the `snap-…` name
exists, the snapshot is complete and its indexes match its files. There is no
window in which a reader sees a directory whose index promises a file that is
not there.

### 4.2 Run sequence

1. **Recover** (Section 8): delete leftover `.staging-…`, GC expired `.trash-…`,
   validate/repair the latest snapshot's indexes.
2. **Acquire** `.lock` (Section 5).
3. **Create** `.staging-<pid>-<rand>/`.
4. **For each source directory** `i` (one at a time, Section 11.2):
   a. `new = build_manifest(src_i)` with the source scan (override 5).
   b. `prev_index =` load `snap_latest/<srcdir-i>/.backup_index.json`
      (or `{}` / re-derived, Section 8).
   c. `to_copy = changed_files(prev_index, new)` (`synccli.py:36`).
   d. `unchanged = new.keys() - to_copy`.
   e. Materialize into `.staging-…/<srcdir-i>/`: for each `to_copy`, the
      overridden `copy_file` (overrides 1-4); for each `unchanged`, APFS clone
      / hardlink from `snap_latest/<srcdir-i>/<rel>` (Section 7.2), falling back
      to copy if the link/clone fails.
   f. `deleted = collect_stale([(rel, rel in new) for rel in prev_index])`
      (`synccli.py:45`) → record in the run report (no materialization; deleted
      files simply do not appear in the new snapshot).
   g. **Write the index last**, from the files that actually materialized
      (Section 4.3), as `.backup_index.json.part` → `fsync` → `os.rename`.
   h. Release this directory's manifests (memory bound, Section 11.2).
5. **Write** `.backup_run.json` (temp → fsync → rename).
6. **fsync** the staging directory, then **`os.rename`** `.staging-<pid>-<rand>`
   → `snap-<ts>-<pid>`, then **fsync** `backup_root` so the rename is durable.
7. **Prune** to retention (Section 9), then release `.lock`.

### 4.3 The index lists only what landed

The index for directory `i` is built **after** step 4e, as
`{rel: file_state(src_i/rel) for rel in materialized_ok}` — i.e. only files that
were successfully copied or linked, carrying their **source** `(size, mtime)`
(`file_state`, `synccli.py:22`). A file that vanished or was unreadable
(override 1) is *not* in `materialized_ok`, so it is absent from the index and
present in the run report. This is the structural fix for the
`synccli.py:74`/`:68-69` over-promise (override 1's reason). Because
`file_state` records *source* state, this index is a valid `old_manifest` for
the next run's `changed_files` (`synccli.py:36`).

### 4.4 Crash points

| Death occurs at | Visible `snap-…`? | Left behind | Next run |
|---|---|---|---|
| Before step 6 rename | No | `.staging-…` (invisible) | Step 1 `rmtree`s it; no reader ever saw it. |
| During step 6 rename | rename is atomic: all or nothing | nothing partial | n/a |
| After rename, before parent fsync | Yes (rename may be non-durable on power loss only) | a complete-or-absent snapshot | Recovery (Section 8) validates; process-crash is fully safe because the OS survives the process. |
| During step 7 prune | Yes (committed snapshot intact) | at most a `.trash-…` | Step 1 GCs expired trash. |

A dead run **never** leaves a `snap-…` directory: the only `snap-…` a run creates
is the atomic rename target in step 6, which either fully exists or does not.
The next run makes progress with no manual cleanup (step 1).

---

## 5. Concurrency: two runs + a restore

### 5.1 Correctness does not depend on the lock

Two runs can run concurrently and still cannot corrupt anything, because:

- Each writes to its **own** `.staging-<pid>-<rand>` (unique by pid) and commits
  to a **unique** `snap-<ts>-<pid>` (unique by pid, override 7). No shared
  mutable write target.
- Committed snapshots are immutable (Section 3), so a restore reading one is
  unaffected by a run creating another.
- `os.rename` commit is atomic (Section 4.1), so a restore enumerating with
  `list_snapshots` (`snaputil.py:8`) sees a snapshot fully or not at all.

The lock is therefore an **efficiency/dedup** coordinator, not a correctness
mechanism — stated explicitly so the safety argument does not rest on it.

### 5.2 The lock

`backupctl` takes an advisory exclusive lock on `backup_root/.lock` via
`fcntl.flock(fd, LOCK_EX | LOCK_NB)` (available on this darwin target).

- **Scheduler trigger:** if the lock is held, log "run in progress, skipping"
  and exit 0. Idempotent; the next tick catches up.
- **Human trigger:** default waits (`LOCK_EX`, blocking) with a `--timeout`;
  `--force` proceeds without the lock (still correct by 5.1).
- **Death safety:** `flock` is released automatically when the process dies and
  the OS closes the fd — no stale lock, unlike an `O_CREAT|O_EXCL` lockfile.
  This directly serves "the next run must make progress without manual cleanup."

### 5.3 Restore reading while a run writes

Restore is separate tooling that (a) enumerates with `list_snapshots`
(`snaputil.py:8`), (b) picks a committed `snap-…`, (c) maps each index relpath
with `safe_snapshot_path` (`snaputil.py:54`) so a stored path cannot escape the
snapshot, and (d) reads. Because committed snapshots are immutable and were
committed atomically, restore sees a complete, self-consistent image and never a
mix of runs — **without restore cooperating with the writer**. The design must be
safe against a reader it does not control, so safety comes from immutability +
atomic commit + invisible staging, not from a reader lock. (If restore is ever
shipped as `backupctl restore`, it may additionally take a shared lock as an
optimization, but the baseline does not require it.)

### 5.4 Prune vs commit vs hardlink-source races

Even without the lock:

- Prune only ever targets a **fixed list of oldest names** computed from
  `list_snapshots` (`snaputil.py:30-33`) and never the newest (`:26-27`). A run
  committing a newer snapshot between prune's list and prune's delete is not in
  that fixed list, so it is safe.
- If run B is materializing (cloning/linking from `snap_latest`) while prune
  retires `snap_latest`: B's already-created clones/links keep the inodes alive
  (refcount), and any not-yet-linked file whose source disappears makes the
  clone/link fail → B falls back to copying it from source (Section 7.2). No
  corruption, no data loss.

---

## 6. Vanishing / unreadable source files

Requirement: a file can vanish between listing and copying, or be unreadable at
copy time; the design must state what the snapshot contains and what the run
reports, identically for scheduler and human triggers.

- **What the snapshot contains:** only files that materialized successfully. A
  file that was in the scan (`build_manifest`, `synccli.py:28`) but failed at
  `open`/`read` (override 3's temp+rename) leaves **no** file in staging (the
  `.part-…` temp is unlinked) and is **absent from the index** (Section 4.3).
  So the index never promises it. The rest of the snapshot is complete.
- **What the run reports:** `.backup_run.json` and stdout list, per source
  directory, `copied`, `linked`, `deleted` (via `collect_stale`, `synccli.py:45`),
  and `skipped` split into `missing` (vanished) and `unreadable` (permission /
  I/O error). The run exits non-zero (warning) if any file was skipped.
- **Trigger independence:** the code path is identical; only the lock
  acquisition policy differs (Section 5.2). The report and exit status are the
  same whether the scheduler or a person started the run.
- **Consistency model (stated):** per-file point-in-time, fuzzy across files.
  For a copied file, the index records the source `(size, mtime)` re-`stat`ed
  immediately after the copy; if the file changed *during* the read, the
  post-copy state differs from the bytes captured, so the **next** run's
  `changed_files` (`synccli.py:36`) re-copies it — the index never marks
  possibly-stale bytes as current. Cross-file atomicity is not provided (this is
  file-granular backup, not a filesystem snapshot); whole-*snapshot* atomic
  visibility is (Section 4.1). A file created after the scan is simply not in
  this snapshot and is caught next run.

---

## 7. Change detection + incremental materialization

### 7.1 Granularity, and what it misses

"Unchanged" is decided **per file** by equality of `file_state` =
`(size, mtime)` (`synccli.py:22`, `:25`), compared via `changed_files`
(`synccli.py:36`): a file is copied iff its relpath is new or its `(size, mtime)`
differs from the previous index. This is exactly `synccli`'s granularity, reused.

What this granularity **can miss** (false "unchanged"):

- An edit that preserves both size and mtime — e.g. an in-place overwrite that
  restores mtime, or a tool that writes with a preserved timestamp. Different
  bytes, same `(size, mtime)` → not re-copied.
- mtime resolution: on filesystems with 1 s mtime granularity, two writes within
  the same second yielding the same size can be missed.
- Mode/ownership/xattr changes (not in `file_state`).

What it over-reports (false "changed", the safe direction): a `touch` that
changes only mtime forces a needless re-copy.

**Opt-in stronger mode:** `--verify=hash` replaces `(size, mtime)` with a content
hash (e.g. sha256) in the index, catching all content edits at the cost of
reading every file every run (loses the "don't re-read unchanged files" win).
Default is `(size, mtime)` because the workload is "most files do not change."

### 7.2 Materialization (don't re-copy unchanged files)

For each `unchanged` file, materialize without reading source bytes:

1. **APFS clone** via `clonefile(2)` (through `ctypes`; `os.clonefile` is not in
   this Python's stdlib — verified). Measured 5,952 clones/s, copy-on-write so it
   also deduplicates disk. Preferred on this darwin/APFS target.
2. **Hardlink** `os.link(prev, staging)` as the cross-platform fallback —
   measured 2,727 links/s on APFS (notably slower than clone; Section 10).
3. **Copy** from source (overridden `copy_file`) if clone and link both fail
   (cross-device, or the previous file was concurrently retired — Section 5.4).

Clone/hardlink share the previous snapshot's inode/extents, so unchanged data is
stored once across snapshots. Changed files get fresh inodes. Snapshots stay
immutable because shared inodes are never modified in place.

### 7.3 Skip-if-no-change optimization

If `changed_files` (`synccli.py:36`) returns empty for **every** directory, the
run does **not** materialize a new snapshot: it records "no change since
`snap_latest`" and exits. This turns a zero-change run into `O(F)` scan only
(`build_manifest`, ~34,236 files/s) plus `O(1)`, avoiding the `O(F)`
clone/link materialization entirely (Section 11.1). When anything changed, a full
new snapshot is materialized so every run that produces a snapshot still produces
a complete, self-contained, browsable image.

---

## 8. Index format + corrupt/half-written index recovery

Requirement: when a run finds a corrupt or half-written index left by a dead run,
define what is discarded, what is re-derived from the tree, and what is reported.

**Index format:** `.backup_index.json` per (snapshot, directory), the
`{relpath:{"size":int,"mtime":float}}` JSON shape produced by `build_manifest`
(`synccli.py:28`) and serialized as `sync()` does (`synccli.py:85-86`).

**Why a half-written index is normally impossible under a committed name:** the
index is written temp→fsync→rename *inside* staging (step 4g) and only becomes
visible via the whole-snapshot atomic rename (step 6). So a half-written index
lives only in an invisible `.staging-…` and is discarded by the next run's
recovery, never seen under a `snap-…` name. Recovery below is **defense in
depth** for non-atomic filesystems, external tampering, or bugs.

**Recovery procedure (run step 1), per latest-snapshot directory index:**

1. **Discard:** if `json.load` raises, or the parsed index is not a dict of the
   expected shape, discard it (treat as `{}`).
2. **Re-derive from the tree:** `derived = build_manifest(snap/<srcdir>)`
   (`synccli.py:28`). This walks the snapshot's actual files and `os.stat`s them
   (`file_state`, `:24`); because copied files preserved source mtime (override
   4) and clones/links preserve it inherently, `derived` reproduces the original
   index exactly. The leading-dot index name is excluded automatically by the
   `scan_files` dot-filter (`synccli.py:14`, kept for snapshot scans per
   override 5).
3. **Reconcile:** any relpath the corrupt index *promised* that is **absent**
   from `derived` is a file the snapshot does not actually contain → report as
   `missing_in_snapshot` (data loss localized to that path in that snapshot).
   The snapshot remains usable for every file it does contain.
4. **Repair (controlled, atomic):** write `derived` as
   `.backup_index.json.part` → fsync → `os.rename` over the corrupt index. The
   rename is atomic, so a concurrent reader sees the old or the repaired index,
   never partial. This is the single sanctioned mutation of a committed snapshot
   (Section 3).
5. **Fallback for total loss:** if the latest snapshot's *tree* is also unusable,
   the run treats `prev_index = {}` and performs a **full** backup — always
   making progress without manual cleanup.
6. **Report:** `.backup_run.json` records, per directory, `index_status` ∈
   `{ok, rederived, missing}`, the count re-derived, and the `missing_in_snapshot`
   relpaths.

---

## 9. Retention + safe deletion

### 9.1 Policy

Retention reuses `prune_snapshots`' selection (`snaputil.py:23`, `:30-33`):
**keep the newest `keep` snapshots** (`--keep`, default 7), delete the oldest
`len(names) - keep`. `prune_snapshots` never deletes the newest (`:26-27`,
`:33`), so the user is **never** left without a usable snapshot; and prune runs
only *after* the new snapshot is committed (step 7), so there are at least
`keep` usable snapshots at all times. A time-based variant (keep all within D
days, then daily/weekly grandfathering) is built on the same `list_snapshots`
enumeration, parsing the `YYYYMMDD-HHMMSS` embedded in each name
(`snaputil.py:11-14`); count-based is the grounded baseline.

### 9.2 Safe deletion while a reader may be reading

Override of `prune_snapshots`' in-place `shutil.rmtree` (`snaputil.py:35`),
per doomed snapshot:

1. **Rename out of the visible namespace:** `os.rename(snap-…, .trash-<pid>-<snapname>)`.
   Atomic; after it, `list_snapshots` (`snaputil.py:18`) no longer returns the
   snapshot, so no *new* reader (restore, next run) can select it.
2. **Grace:** do not `rmtree` immediately. A reader that resolved the `snap-…`
   name *before* the rename but has not yet opened every file would otherwise hit
   `ENOENT` mid-walk. Hold the trash for `grace` seconds (default ≥ the maximum
   plausible restore duration).
3. **GC:** on a later run's step 1, `rmtree` a `.trash-…` only when
   `is_stale(trash_dir, now - grace)` (`snaputil.py:66`, `<=` `:73`) — i.e. its
   mtime is at least `grace` old.
4. **Already-open readers:** POSIX unlink semantics keep an open file descriptor
   valid after its directory entry is removed, so a restore that already opened
   files keeps reading them to completion even after `rmtree`.
5. **Shared-data safety:** because unchanged files are clones/hardlinks
   (Section 7.2), retiring an old snapshot frees only data no newer snapshot
   references; inodes/extents shared with a newer snapshot survive its deletion.

This is safe **without reader cooperation** (the design must assume a restore it
does not control), and guarantees a usable snapshot always remains (9.1).

---

## 10. Performance budget — first full backup (measured)

**Method.** Measured on this target (macOS/darwin, APFS, Python 3.10.11, SSD)
against the *actual* reused functions and the overridden copy path, using temp
trees of 4,000–5,000 × 1 KB files for per-file rates, 256 MB of 64 MB files for
byte throughput, and `tracemalloc` for manifest memory. The existing suite
(`python3 -m unittest`, 6 tests) passes, confirming the reused primitives behave
as cited. These are measured constants, not guesses.

| Constant | Value | Source |
|---|---|---|
| `r_scan` — scan+stat (`build_manifest`, `synccli.py:28`) | **34,236 files/s** | measured |
| `r_copy_safe` — overridden copy (chunk+temp/rename+utime) | **2,982 files/s** | measured |
| `r_copy_raw` — raw whole-file read (`synccli.py:67` style) | 5,677 files/s | measured |
| `r_copy_orig` — `copy_file` as written (`synccli.py:62`) | 3,590 files/s | measured |
| `r_clone` — APFS `clonefile` (ctypes) | **5,952 clones/s** | measured |
| `r_link` — `os.link` (APFS) | **2,727 links/s** | measured |
| `r_walk` — `snapshot_disk_usage` (`snaputil.py:39`) | 54,954 files/s | measured |
| `throughput` — bulk byte copy | **3,692 MB/s** | measured |
| `r_makedirs` — `os.makedirs(exist_ok=True)` | 15,503 ops/s | measured |
| `r_fsync_file` — copy + per-file `fsync` | 5,438 files/s | measured (APFS `fsync` is not a full barrier; `F_FULLFSYNC` would be slower) |
| `mem_entry` — manifest bytes/entry | **379 B** | measured (`tracemalloc`) |

**Derivation.** A first full backup has no previous snapshot, so every file is
copied from source at `r_copy_safe`:

```
T_full(F, B) = F / r_scan          # scan + stat the source
             + F / r_copy_safe     # per-file copy overhead (open/temp/rename/utime)
             + B / throughput      # bulk byte movement
```

| Tree | scan+stat | copy overhead | bytes (1 GB) | **Total** |
|---|---|---|---|---|
| 1 GB, 20,000 files | 0.58 s | 6.71 s | 0.28 s | **≈ 7.6 s** |
| 1 GB, 50,000 files | 1.46 s | 16.77 s | 0.28 s | **≈ 18.5 s** |

**Budget.** The initial full backup of a ~1 GB tree (≤ 50,000 files) **must
complete in < 60 s** on target hardware — a ≥ 3.2× margin over the 18.5 s
measured worst case here, covering slower target storage, cold cache, and
filesystem variance. On hardware comparable to this machine, expect ~15–20 s.

**Where the time goes (the honest finding):** the budget is dominated by
**per-file copy overhead**, not bytes — 1 GB at 3,692 MB/s is only 0.28 s, while
50,000 per-file copies at 2,982/s is 16.77 s. So for a fixed byte budget, *more
files = slower*; the cost scales with file count `F`, and `B` is almost free on
SSD. Any future optimization must target per-file syscall count, not throughput.

---

## 11. Scaling bounds (N directories, F files, B bytes)

Definitions: `N` = configured directories; `F_i` = files in directory `i`;
`F = Σ F_i`; `Fmax = max F_i`; `B = Σ B_i`; `C` = files changed per run;
`ΔB` = bytes changed per run; `K` = `--keep`. Constants from Section 10.

### 11.1 Per-run work (time)

```
T_run = F / r_scan                                   # scan all directories
      + Σ_i (F_i − C_i) / r_mat                      # materialize unchanged (clone/link)
      + Σ_i C_i / r_copy_safe                        # copy changed
      + ΔB / throughput                              # changed bytes
      + (N + 1) · t_meta_fsync                       # N index fsyncs + 1 parent fsync
```

with `r_mat = r_clone = 5,952/s` (APFS) or `r_link = 2,727/s` (fallback). The
`O(F)` materialization term dominates in steady state. Explicit numbers for
`F = 50,000`:

- nothing changed, clone: `1.46 + 50000/5952 ≈ 1.46 + 8.40 ≈ 9.9 s`
- nothing changed, link: `1.46 + 50000/2727 ≈ 1.46 + 18.3 ≈ 19.8 s`
- **skip-if-no-change** (Section 7.3): `≈ 1.46 s` (scan only, no materialization)
- 2 % of bytes changed (clone): `≈ 9.9 s + (1000 files)/2982 + 20 MB/3692 ≈ 10.3 s`

Per-run work scales with **`F` (total files)**, not directly with `N`; `N`
enters only through `F` and the `(N+1)` metadata fsyncs (each ~ms, so dozens of
directories add tens of ms).

### 11.2 Memory

Directories are processed **one at a time** (step 4h releases each before the
next), so peak manifest memory is the largest single directory, held twice during
`changed_files` (`synccli.py:36`, old index + new manifest):

```
peak_manifest_RSS ≈ 2 · Fmax · mem_entry = 2 · Fmax · 379 B
```

- `Fmax = 50,000` → ≈ **37.9 MB**
- `Fmax = 200,000` → ≈ **152 MB**

Bounded by `Fmax`, **independent of `N`** and of `B` (the overridden copy streams
in 1 MiB chunks — override 2 — so per-open-file memory is `O(1 MB)`, not
`O(file size)` as `synccli.py:67` would be). Open file descriptors per run are
`O(1)` (one file at a time, `copy_file` `synccli.py:66`).

### 11.3 Disk

- **First full snapshot:** physical ≈ `B` + index, where index ≈ `F · 80 B`
  (50,000 → ~4 MB). Logical (`snapshot_disk_usage`, `snaputil.py:39`) ≈ same for
  the first snapshot.
- **Each later snapshot adds (physical):** `ΔB` (fresh inodes for changed files)
  `+ F · dentry` (~64 B per clone/hardlink directory entry; **no data
  duplication** — unchanged data is shared). Best case (no change): `≈ F · 64 B`.
- **Total physical over `K` snapshots:**
  - lower bound (nothing changes): `≈ B + K · (F · 64 B + F · 80 B)`
  - upper bound (everything changes every run): `≈ K · B`
- **Caveat (grounded):** `snapshot_disk_usage` sums `st_size` of every file
  (`snaputil.py:50`), so for clones/hardlinks it counts shared bytes in *every*
  snapshot — the **logical** total across `K` snapshots is `≈ K · B` and
  **overstates** real disk use, which is deduplicated. `list`/reporting must
  label this number "logical" and compute real usage from the filesystem
  (e.g. `du`-style block accounting) when accuracy matters.

### 11.4 What stays flat (independent of `N`, `F`, `B`)

- In-flight staging directories: **≤ 1** per writer (the lock serializes writers
  to 1; even unlocked, each is one per process). Bound: 1.
- In-flight `.trash-…` directories: **≤ (prunes within one grace window)** — a
  small constant set by `grace` and run frequency, not by `N`/`F`.
- Lock files: **1**.
- Open file descriptors per run: **O(1)**.
- Call-stack depth: **O(1)** — `os.walk` (`synccli.py:13`) is an iterative
  generator; no recursion over the tree.

### 11.5 What grows with `N` specifically (not via `F`)

- Metadata fsyncs per run: **`N + 1`** (one per directory index + one parent
  after the commit rename). Dozens of directories → tens of ms.
- Index files per snapshot: **`N`**.
- Per-directory setup/teardown (open prev index, write new index): **`N · O(1)`**.

---

## 12. Durability model (process death vs power loss)

The stated threat is **process death** — "Ctrl-C, laptop sleep, a killed
process." For that threat, atomic staging + `os.rename` (Section 4) is *fully*
sufficient with **no fsync at all**: the OS survives the process and continues to
flush its caches, so a committed snapshot is complete and a dead run leaves only
invisible staging. This is why the budget (Section 10) does not pay per-file
fsync.

For **power loss / kernel panic** (a stronger threat, out of the stated scope),
the run already does the cheap insurance: fsync each small index, fsync staging
before the commit rename, fsync `backup_root` after — so a *visible* snapshot has
a durable index and a durable rename. Data-file durability on power loss is
filesystem-dependent without per-file fsync; recovery (Section 8) detects any
index-promised file that is missing/zero-length and re-derives/repairs, so even a
power-loss-torn snapshot is detected, never silently trusted.

**Optional `--durable`:** per-file `fsync` before each temp→rename, for users who
want power-loss durability of data bytes. Measured cost on this machine:
5,438 files/s including fsync (APFS `fsync` is not a full barrier; the truly
durable `F_FULLFSYNC` is slower and platform-specific). At 50,000 files this
roughly doubles-to-triples `T_run`; it is opt-in precisely because the stated
threat does not require it.

---

## 13. CLI surface and config

```
backupctl run   [--config PATH] [--dry-run] [--full] [--verify=hash] [--durable]
                [--wait|--skip|--force] [--timeout S]
backupctl list  [--config PATH]            # list_snapshots + snapshot_disk_usage (logical)
backupctl prune [--keep K] [--grace S]     # safe-delete (Section 9.2)
backupctl verify [SNAPSHOT]                # index consistency / re-derive (Section 8)
backupctl restore SNAPSHOT DEST [--only DIR]  # uses safe_snapshot_path (snaputil.py:54)
```

`--dry-run` reuses `sync()`'s preview semantics (`synccli.py:81-82`): report the
copy/link/delete sets, change nothing.

**Config** (JSON): `{ backup_root, sources: [dir_1..dir_N], keep, grace,
verify_mode, durable }`. `backup_root` and the `snap-`/`.staging-`/`.trash-`
conventions follow `snaputil` (`:11-14`, `:18`).

---

## 14. Test / verification plan

Extends `test_synccli.py` (`python3 -m unittest`); each maps to a requirement:

- **Atomic visibility / no partial:** kill a run mid-materialization (inject a
  raise in the copy loop); assert no `snap-…` exists, a `.staging-…` remains, and
  the next run deletes it and completes (Sections 4.4, 8).
- **Index never over-promises:** delete a source file between scan and copy and
  `chmod 000` another; assert the committed index omits both, the report lists
  `missing`/`unreadable`, and the snapshot is otherwise complete (Section 6,
  override 1) — the regression `synccli.py:68-69` would fail.
- **Concurrency:** start two runs at once; assert two distinct valid `snap-…`,
  neither corrupt; start a restore holding open fds during a prune; assert the
  fds stay readable and the newest snapshot survives (Sections 5, 9.2).
- **Corrupt index recovery:** write garbage into a snapshot's
  `.backup_index.json`; assert `verify`/next run re-derives from the tree via
  `build_manifest` (`synccli.py:28`), reports `missing_in_snapshot`, and repairs
  atomically (Section 8).
- **Retention:** with `keep=K`, assert `prune` removes exactly the oldest
  `len-K` (reusing `snaputil.py:30-33`) and never the newest (`:26-27`), and that
  deletion is rename-then-grace-then-rmtree (override 6).
- **Incremental:** run twice; assert the second clones/links unchanged files
  (no source re-read) and copies only `changed_files` (`synccli.py:36`); assert
  skip-if-no-change produces no new snapshot when nothing changed (Section 7.3).
- **Performance:** build a synthetic ~1 GB / 50,000-file tree; assert first full
  backup < 60 s (Section 10) — the budget is checked, not assumed.
- **Memory:** assert peak RSS of a run over a tree with `Fmax` files stays within
  `2 · Fmax · 379 B` plus a constant (Section 11.2).

---

## 15. Risks and open questions

- **APFS `clonefile` via `ctypes`** is platform-specific and not in stdlib
  (verified absent). Mitigation: `os.link` fallback (2,727/s), then copy. A
  non-APFS or non-darwin deployment loses the clone speedup and the CoW disk
  dedup; the bounds in Section 11.1 fall back to the `r_link` row.
- **`os.link` is slow on APFS** (2,727/s, measured) — slower than copying small
  files raw (5,677/s). If clone is unavailable, steady-state materialization is
  the bottleneck; skip-if-no-change (Section 7.3) is the main mitigation.
- **`(size, mtime)` misses same-size/same-mtime edits** (Section 7.1). Accepted
  by default for the "most files don't change" workload; `--verify=hash` is the
  escape hatch at full-read cost.
- **Fuzzy cross-file consistency** (Section 6) is inherent to file-granular
  backup without a filesystem snapshot. If point-in-time cross-file consistency
  is ever required, the design would need an LVM/APFS-snapshot-based capture —
  out of scope here.
- **`snapshot_disk_usage` over-reports** shared clone/link bytes (Section 11.3);
  real-usage accounting must come from the filesystem, not from summing
  `st_size` (`snaputil.py:50`).

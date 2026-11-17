# DESIGN — `backupctl`: snapshot backups for the evals workflow (fixture D1)

Status: design, pre-implementation. All grounded claims below were checked against
the code in this directory and against live measurements on this machine
(§12.1, §14). Citations are `file:lines` into `synccli.py`, `snaputil.py`,
`test_synccli.py` as they exist here today.

---

## 1. Goal and scope

`backupctl` backs up a configured set of source directories (N — three today, a
few dozen over time) into a backup root as **snapshots**: point-in-time,
individually complete images, named and organized so that the existing
`snaputil` helpers (`list_snapshots`, `prune_snapshots`, `snapshot_disk_usage`,
`safe_snapshot_path`) apply to them unchanged.

Hard requirements from the brief, and where each is answered:

| Requirement | Section |
|---|---|
| Scheduler and human runs can collide; restore reads while a run writes | §6 |
| Readers never ask whether a run is finished; no partial/mixed images, no index promising absent files | §5, §6, §11 |
| Process can die at any point; corrupt/half-written index recovery defined | §7 |
| Source file vanishes or is unreadable mid-run | §8 |
| Backup root only grows; retention deletes safely, never leaves user without a snapshot | §10 |
| Unchanged files not re-copied; granularity + what it misses stated | §9 |
| Performance budget for first full backup of ~1 GB / tens of thousands of files, derived | §12.2 |
| What grows with what (per-run work, memory, disk), as explicit bounds over N / files / bytes | §12.3 |

Out of scope: the restore tool itself (separate tooling; §11 defines the
contract it relies on), remote/off-host storage, compression, encryption.

---

## 2. Design decision summary

**Snapshot model: fully materialized trees with hardlink dedup** (the
rsnapshot model). Every published snapshot directory contains a *complete*
tree per source: files unchanged since the baseline snapshot are
`os.link`-ed from it (zero data bytes copied), changed/new files are copied.

Why this model, against the alternative (delta-chain snapshots, where each
snapshot stores only changed files plus a manifest pointing into earlier
ones):

1. **It is the model the existing helpers already assume.**
   `snaputil.snapshot_disk_usage` (snaputil.py:39–51) walks one snapshot
   directory and sums file sizes; `snaputil.safe_snapshot_path`
   (snaputil.py:54–63) maps a relative path back *under that snapshot's own
   directory*. Both only make sense if a snapshot is a self-contained tree.
2. **It makes every hard requirement local to one directory.** "Complete,
   self-consistent image" = manifest ≡ tree contents, checked inside one
   directory (§5 step 6). Pruning an old snapshot cannot break a newer one:
   `shutil.rmtree` on the older removes one *name* per shared inode; the
   newer snapshot's hardlink keeps the data alive — verified (§14, check C2:
   newer tree intact, content and size correct, after rmtree of the older).
   A delta-chain model instead needs reference counting before any deletion
   and chain-walking for every read — strictly more failure surface for the
   same three guarantees the brief demands.
3. **Cost of the link pass is metadata-only and is bounded and measured**
   (§12): 692 B of disk per link, no source bytes read. On this machine the
   link syscall is unusually expensive (0.38–1.7 ms measured, §12.1) and
   dominates steady-state wall time; §12.3 gives the formula so the
   controlling constant is explicit, and §2.1 records the trade we accepted.

### 2.1 Trade accepted, stated plainly

With hardlink materialization, a steady-state run costs O(F) metadata
operations (one link per unchanged file) even when nothing changed — on this
machine ≈ 13–53 s per 30k files (§12.2), versus ≈ 1–2 s for a delta-chain
model whose per-run work is O(changed). We accept this because the three
correctness requirements (complete images for lock-free readers, prune safe
against concurrent readers, no index ever promising absent files) are each
structurally simpler under full materialization, and because the link pass
moves **zero data bytes** (marginal disk 692 B/file measured vs 33 KB+ for a
re-copy). The per-run time bound is stated honestly in §12.2 rather than
hidden.

---

## 3. On-disk layout

```
<backup_root>/
  .lock                          # flock file; single-writer serialization (§6)
  config.json                    # {version, sources: {tag: path}, keep, grace}
  index.json                     # published-snapshot index — a CACHE; the tree is the truth (§7.2)
  index.json.tmp                 # transient; atomic-replace target (§5 step 8)
  snap-YYYYMMDD-HHMMSS-NN/       # PUBLISHED snapshots (immutable after publish)
    SNAPSHOT.json                # run metadata: time, host, per-source stats, skip records
    manifest/<tag>.json          # per source: {relpath: {size, mtime}} in SOURCE state space (§9)
    tree/<tag>/…                 # the materialized tree (hardlinks + copies)
  .staging-snap-YYYYMMDD-HHMMSS-NN/   # in-progress run; same internal layout
  .trash/<snap-name>/            # unpublished, awaiting rmtree (§10 two-phase delete)
```

Naming and visibility invariants:

- Published names match `snap-` + UTC date + time + 2-digit run sequence
  (`snap-20261112-150000-07` is exactly the form documented in
  `snaputil.list_snapshots`'s docstring, snaputil.py:11–14), so
  `list_snapshots` (snaputil.py:8–20) enumerates them and its lexicographic
  sort is chronological. NN disambiguates same-second runs; >99 runs in one
  second is impossible under the single-writer lock (a run takes seconds,
  §12.2).
- `.staging-*`, `.trash`, `.lock`, `index.json*` never appear in
  `list_snapshots` output: its filter is `entry.name.startswith("snap-")`
  (snaputil.py:18). Verified (§14, check A1: a populated staging directory
  is invisible; A2: after `os.rename` it is listed). This single existing
  filter is what makes in-progress work unreadable-by-construction.
- `tree/<tag>`: tags are validated at config load to `[A-Za-z0-9._-]+`, not
  starting with `.`, so a tag cannot collide with dot-names or introduce
  path segments; every manifest-relpath resolution additionally goes through
  `snaputil.safe_snapshot_path` (snaputil.py:54–63), whose `normpath`
  (line 62) strips `..` so no stored path can climb out of its snapshot.

---

## 4. Grounding map — what is reused, what is overridden

### 4.1 Reused as-is

| Existing artifact | Used for |
|---|---|
| `synccli.file_state` (synccli.py:22–25) | The per-file change-detection state record `{size, mtime}` (§9). |
| `synccli.changed_files` (synccli.py:36–42) | New/changed detection: iterates the new manifest, flags rels absent from or differing in the old (lines 39–41). |
| `synccli.collect_stale` (synccli.py:45–59) | Deletion *reporting*: `collect_stale([(rel, rel in new_manifest) for rel in old_manifest])` returns exactly old−new. Verified (§14, check I1). Deletions need no action — each run materializes a fresh tree, so a deleted source file simply does not appear (§9.3). |
| `synccli.copy_file` core (synccli.py:62–67) | Copy primitive for changed/new files, via the `copy_file_checked` wrapper (§4.2, override O2 — the wrapper keeps the `makedirs` at line 64, replaces the body's error handling and whole-file read). |
| `snaputil.list_snapshots` (snaputil.py:8–20) | Snapshot discovery everywhere: baseline selection (§5 step 3), retention dooming (§10), index rebuild (§7.2), `list`/`status` commands. Its prefix filter is the staging invisibility mechanism (§3). |
| `snaputil.prune_snapshots` dooming semantics (snaputil.py:23–36) | Retention victim selection: `doomed = names[:len(names) - keep]` (line 33) — oldest first, newest never doomed (docstring lines 26–28). The *mechanism* of deletion is overridden (O4). |
| `snaputil.snapshot_disk_usage` (snaputil.py:39–51) | Per-snapshot **apparent** size in `list`/`status` reports; §12.3 states the apparent-vs-marginal distinction it implies (shared inodes counted per snapshot). |
| `snaputil.safe_snapshot_path` (snaputil.py:54–63) | Every manifest-relpath → real-path resolution: hardlink-base resolution (§5 step 5), `verify`, and the restore contract (§11). |
| `snaputil.is_stale` (snaputil.py:66–73) | *Not used in the retention path* — policy is count-based (§10). Available unchanged for a future age-based policy; noted here because its `ref_epoch`-captured-by-caller contract (lines 69–71) would be the right way to build one. |
| Test conventions (test_synccli.py) | `backupctl`'s suite is `unittest` in the same style, run with `python3 -m unittest` (e.g. the tempdir-per-test pattern of `TestScanFiles.setUp`, test_synccli.py:9–15). |

### 4.2 Overrides — exact behavior replaced, where it lives, why

**O1 — `synccli.scan_files`'s dot-directory filter (synccli.py:14).**
`dirnames[:] = [d for d in dirnames if not d.startswith(".")]` silently
excludes every hidden directory. For a sync tool that is a policy choice;
for a *backup* it is silent data loss (a covered dir containing `.config`,
`.git`, `.cache` results would quietly omit them). **Override:**
`backupctl.scan_all(root)` keeps the exact contract of `scan_files`
(synccli.py:10–19 — `os.walk`, sorted relative file paths) minus the line-14
filter, and `backupctl.build_manifest_all(root)` keeps the construction of
`synccli.build_manifest` (synccli.py:28–33 — `{rel: synccli.file_state(...)}`)
with `scan_all` substituted for `scan_files`. Everything downstream
(`changed_files`, `collect_stale`, manifest format) consumes these unchanged.

**O2 — `synccli.copy_file`'s error swallowing and whole-file read
(synccli.py:66–69).**
Today: `except OSError: pass` (lines 68–69) skips an unreadable source
silently, and a failure *mid-write* leaves a truncated `dst` behind, also
silently; line 67 `fdst.write(fsrc.read())` allocates the entire file in RAM
(a 128 MB file = a 128 MB allocation). Combined with `sync`'s manifest write
(see O3) this produces exactly the failure the brief forbids — verified
(§14, check G1): a file that vanished between listing and copying is absent
from the destination yet *listed in the written manifest*. **Override:**
`backupctl.copy_file_checked(src, dst)`:

- keeps `os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)` (line 64);
- copies in 1 MB chunks via `shutil.copyfileobj` instead of line 67's
  whole-file read → memory O(1 MB) per copy regardless of file size;
- on any `OSError`: `os.unlink(dst)` if it was created (no truncated file
  survives to be scanned into the landed set), and returns `(False, errno)`
  instead of `pass`. The run records the skip (§8); nothing is silent.

**O3 — `synccli.sync`'s in-place publish (synccli.py:72–87).**
Today `sync` writes files directly into the live destination (line 84) and
writes the manifest with a plain `open`+`json.dump` to the final path
(lines 85–86): a reader concurrent with a sync sees a mixed tree, and a
crash between the two writes leaves data without a manifest or a truncated
manifest over partial data. It also writes `src_manifest` — the *intent* —
regardless of what `copy_file` actually landed (line 86 vs the swallowed
errors at 68–69), which is the "index promises files the snapshot does not
contain" hazard, verified at G1. **Override:** `backupctl` never writes into
a published location. Every run stages into `.staging-*` and publishes with
one atomic `os.rename` (§5 step 7); the published manifest is the source
manifest **restricted to the landed set** — the files actually present in
the staged tree, enumerated by re-running `build_manifest_all` on the
staging tree (§5 step 6). Restricting rather than re-stat-ing matters:
staged copies carry *copy-time* mtimes — `copy_file` does not preserve
source mtime (verified, §14 check C0: staged mtime = now, source mtime
untouched) — so publishing staging-space states would make every copied
file look "changed" on the next run. States come from the source manifest;
*membership* comes from the staging scan. Hardlinked files are unaffected
either way (a link preserves the prev inode's mtime/size — verified, check
C1), and detection reads manifests, never the tree (§9).

**O4 — `snaputil.prune_snapshots`'s deletion mechanism
(`shutil.rmtree`, snaputil.py:35).**
Dooming is reused (§4.1); the direct `rmtree` is not: it deletes files out
from under a concurrent reader mid-walk. **Override:** two-phase delete —
`os.rename(snap → .trash/snap)` (atomic unpublish; held open fds survive
both the rename and the later rmtree — verified, §14 checks B1/B2), then
`shutil.rmtree` inside `.trash`, resumable by the next run's sweep (§7.1).
Details and the never-without-a-snapshot guard: §10.

Where the brief asks for "the exact function or behavior you override":
O1 `synccli.scan_files` line 14; O2 `synccli.copy_file` lines 66–69;
O3 `synccli.sync` lines 84–86 (publish mechanism) with line 68–69
interaction; O4 `snaputil.prune_snapshots` line 35. No other existing
behavior is changed.

---

## 5. Run lifecycle (`backupctl run`)

One run = one new snapshot covering all configured sources. Steps:

1. **Acquire the lock.** `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on
   `<root>/.lock`. Contention → exit 3 ("another run is in progress") for
   the scheduler; `--wait` uses blocking `LOCK_EX` for a human who wants to
   queue. Verified (§14, D1): a second process gets `BlockingIOError`; and
   the lock is released by the kernel when the holder dies — verified with
   `SIGKILL` of the holder (D2), which is what makes crash recovery
   lock-safe (§7).
2. **Recovery sweep** (safe: we hold the only writer lock — anything
   in-progress-shaped is by definition dead):
   - `rmtree` every `.staging-*` directory; report each.
   - resume `rmtree` of everything under `.trash/`; report.
   - delete a stale `index.json.tmp`.
   - validate/rebuild `index.json` (§7.2); report "rebuilt" if it happened.
3. **Per source (sequentially, tag order), diff against baseline:**
   - `new_manifest = build_manifest_all(src_path)` (O1) — reuses
     `synccli.file_state` per file.
   - baseline = newest published snapshot (from `snaputil.list_snapshots`,
     newest = last) whose `manifest/<tag>.json` parses **and passes base
     validation**: every relpath resolves via
     `snaputil.safe_snapshot_path(root, snap, "tree/"+tag+"/"+rel)` and
     exists with the recorded size. A candidate that fails is quarantined
     (renamed into `.trash/`, reported) and the next-newest is tried
     (§7.3). No valid baseline → empty old manifest → everything is new.
   - `to_copy = synccli.changed_files(old_manifest, new_manifest)`
     (synccli.py:36–42); `to_link = keys(new_manifest) − to_copy`;
     `deleted = synccli.collect_stale([(rel, rel in new_manifest) for rel in old_manifest])`
     (report-only, §9.3).
4. **Create `.staging-snap-<ts>-NN/`** (NN = next free sequence for this
   timestamp, scanned under the lock).
5. **Materialize `tree/<tag>/` per source:**
   - for each rel in `to_link`: `os.link(base_path, staging_path)` where
     `base_path = safe_snapshot_path(root, baseline_name, tree/tag/rel)`.
     A link failing `ENOENT` (baseline file gone — impossible for a
     validated baseline under our own contract; possible only via
     out-of-band tampering) demotes the file to copy-from-source; a failed
     copy becomes a recorded skip (§8).
   - for each rel in `to_copy`: `copy_file_checked(src, staging_path)` (O2);
     failures recorded as skips with errno.
6. **Land the manifests.** For each source: `landed =
   build_manifest_all(staging_tree_dir)` (keys = exactly what exists in the
   staged tree — files, sizes, staging-space states); publish
   `manifest/<tag>.json = {rel: new_manifest[rel] for rel in landed}` —
   membership from the tree, states from the source (O3 rationale). By
   construction the manifest lists a file **iff** the tree contains it.
   `skipped = keys(new_manifest) − landed`. Write `SNAPSHOT.json`:
   `{version, created_utc, host, sources: {tag: {scanned, copied, linked,
   deleted_since_prev, bytes_copied, skipped: [{rel, errno}]}}}`.
7. **Publish: `os.rename(.staging-snap-…, snap-…)`** — one atomic
   same-volume rename. Before it, the snapshot does not exist for any
   reader; after it, it exists complete. There is no in-between state
   (§6.2).
8. **Update the index (atomic).** Read current `index.json` (or the
   just-rebuilt one), append the new entry, write `index.json.tmp`, `fsync`,
   `os.replace(tmp, index.json)`. A crash anywhere here leaves either the
   old or the new index — never a torn one — and even a lost/torn index is
   only a lost cache (§7.2).
9. **Retention** (§10): if this run has zero skips, or the published count
   exceeds `keep + grace`, doom and two-phase-delete.
10. **Release lock; report** (§13.4). Exit code: 0 clean, 2 published with
    skips, 3 lock contention (step 1), 1 fatal — nothing published (§8.2).

`--dry-run` stops after step 3 and reports the per-source
scanned/to_copy/to_link/deleted counts without touching disk.

---

## 6. Concurrency contract

Three actors: **runs** (scheduler- or human-triggered), **readers**
(restore, human, tooling), **prune** (part of a run, or `backupctl prune`).

### 6.1 Writer vs writer — one lock

All mutations of the backup root (staging, publish, index update, prune)
happen under `flock` on `.lock`. Two colliding runs cannot interleave: the
second gets `LOCK_EX|LOCK_NB` → `BlockingIOError` → exit 3, or waits with
`--wait`. A dead holder cannot block the next run: flock is released on
process death — verified with SIGKILL (§14, D2). Staging names are unique
per run and allocated under the lock, so two runs can never target the same
directory even within the same wall-clock second.

### 6.2 Writer vs reader — immutability + atomic publish; readers take no lock

A reader's entire view is the set of `snap-*` directories (via
`snaputil.list_snapshots`) and their contents. A running writer:

- does all its work in `.staging-*`, which `list_snapshots` cannot return
  (prefix filter, snaputil.py:18 — verified A1);
- **never modifies a published snapshot directory** — published trees are
  immutable after step 7 (nothing in the run lifecycle writes into a
  `snap-*` dir; the only operation touching published names is prune's
  atomic rename, §6.3);
- adds a snapshot with one atomic `os.rename` (step 7): a reader sees the
  old published set or the old set plus one complete snapshot, never a
  fragment (verified A1→A2).

So "a reader never asks whether the run is finished" holds structurally:
*visible ⇒ complete*. Completeness of a visible snapshot means (a) its tree
is fully materialized — it was finished before the rename — and (b) its
manifest lists exactly the files its tree contains — manifest = landed set
by construction (step 6). The forbidden "mix of some files from this run,
some from the previous one" is precisely a partially-materialized visible
tree, and the rename makes it unobservable. (Unchanged files *are*
hardlinks to inodes created by earlier runs — identical content, shared
storage; that is dedup, not a mix: the snapshot is a complete image of the
source as of its scan, and every manifest entry resolves inside it.)

Readers hold no lock, so a long restore never blocks a scheduled run, and a
run never blocks a restore.

### 6.3 Prune vs reader — two-phase delete

Prune (inside a run or standalone) takes the same `.lock` (so it never
overlaps a run), then for each doomed snapshot:

1. `os.rename(root/snap-X, root/.trash/snap-X)` — atomic unpublish:
   `list_snapshots` stops returning it immediately (verified C3-style: after
   rmtree of a predecessor the listing shows only survivors; the `.trash`
   name fails the `snap-` prefix filter).
2. `shutil.rmtree(root/.trash/snap-X)` — the slow part, running on a path
   no reader can newly resolve.

A reader already inside snap-X when phase 1 runs is safe by POSIX
semantics: **open file descriptors and open directory fds survive rename
and unlink** — verified (§14, B2): an fd opened on a published file still
read its full content after the snapshot was renamed into `.trash` and
rmtree-ed. A reader that resolved the path but has not yet opened gets
`ENOENT` (verified B1) — the restore contract (§11) turns that into a
fallback to the next-newest snapshot, not an error. And a *newer* snapshot
that hardlinked files from the doomed one is untouched: rmtree removes one
name per inode; the survivor's link keeps the data alive — verified C2
(content and size intact after the older snapshot's rmtree).

---

## 7. Crash safety and recovery

### 7.1 Kill-point analysis

The run may die at any instruction. What each kill point leaves, and what
the **next** run does (all without manual cleanup — requirement):

| Death during | On-disk residue | Next run's action | Reader impact while dead |
|---|---|---|---|
| Scan/diff (step 3) | none, or empty `.staging-*` | sweep rmtree's it | none — published set untouched |
| Copy/link (step 5) | partial `.staging-*` tree | sweep rmtree's it | none |
| Manifest/SNAPSHOT.json write (step 6) | `.staging-*` with partial metadata | sweep rmtree's it (staging is *never* trusted, even if it looks complete) | none |
| Publish rename (step 7) | rename is one syscall: it happened or it didn't | if it didn't: sweep; if it did: snapshot is published and complete | none either way |
| Index update (step 8) | published snapshot missing from index; possibly `index.json.tmp` | index rebuilt/reconciled from the tree (§7.2); tmp deleted | index readers may miss the newest snapshot until the next run; `list_snapshots`-based readers see it |
| Prune rename (step 9, phase 1) | snapshot sits in `.trash/` | sweep resumes rmtree; snapshot already atomically unpublished — consistent | a mid-read reader keeps reading via open fds (B2) |
| Prune rmtree (step 9, phase 2) | partial `.trash/snap-X` | sweep resumes rmtree (rmtree is restartable) | none |

An interrupted run therefore leaves **nothing a reader could mistake for a
complete snapshot**: the only reader-visible objects are `snap-*` dirs, and
those come into existence only via the step-7 atomic rename of a finished
tree.

### 7.2 Corrupt or half-written index — the defined recovery

`index.json` is a cache; **the tree is the truth.** When a run (step 2) or
`backupctl status` finds `index.json` that does not parse (a half-written
file raises `json.JSONDecodeError` — verified, §14 H1) or fails its schema
check (`{version, snapshots: […]}` with each entry naming a directory that
exists):

- **Discarded:** the entire index file. No salvage attempt, no partial
  trust.
- **Re-derived from the tree:** `snaputil.list_snapshots(root)` enumerates
  the published snapshots (a directory's existence is its completeness
  proof, §6.2); for each, `SNAPSHOT.json` is read; entries are rebuilt from
  those that parse. A snapshot whose `SNAPSHOT.json` does not parse is
  *quarantined* (§7.3) rather than indexed.
- **Reported:** `recovery: index.json corrupt — discarded, rebuilt from N
  snapshot directories` plus one line per quarantined snapshot.

The same reconcile pass runs unconditionally at every startup: entries
naming nonexistent dirs are dropped, published dirs missing from the index
are appended. Index divergence is therefore self-healing within one run.

### 7.3 Corrupt snapshot metadata (defense in depth)

Post-publish corruption of a snapshot's own `SNAPSHOT.json`/manifest should
be impossible via the run lifecycle (they are complete before the rename);
disk failure or tampering can still do it. Rule: a snapshot failing
validation (metadata unparseable, or manifest listing a file that
`safe_snapshot_path`-resolves to something absent or wrong-sized) is
**quarantined**: renamed into `.trash/` (atomic unpublish, same mechanism
as prune) and reported. It is dropped from the index and skipped as a
baseline candidate (§5 step 3 falls back to the next-newest valid
snapshot). Quarantine — not repair: a snapshot we cannot vouch for must not
be readable, and its inodes may still back newer snapshots' hardlinks,
which rmtree-in-trash respects (C2).

`backupctl verify [SNAP]` runs the same validation on demand across all
snapshots (cost: one stat per manifest entry ≈ F × 30 µs per snapshot,
§12.1 constants).

---

## 8. Failure semantics: vanished and unreadable sources

### 8.1 Per-file failures — skip, record, publish anyway

A source file can vanish between listing (step 3) and copying (step 5), or
be unreadable when the copy reaches it (`EACCES`, `EIO`; a dangling symlink
surfaces as `ENOENT` at `open`). Handling — identical whether the scheduler
or a human started the run (there is no interactive path anywhere in the
design):

- `copy_file_checked` (O2) fails the file, unlinks any partial staging
  file, returns the errno. The run **continues**.
- **What the snapshot contains:** everything that landed — the skipped file
  is absent from `tree/<tag>/`, and because the published manifest is the
  landed set (§5 step 6) it is absent from the manifest too. The snapshot
  remains internally complete and consistent; it is missing exactly the
  files the source failed to hand over.
- **What the run reports:** one stderr line per skip —
  `SKIP <tag>/<rel>: <errno> (<class>)` — and the same records durably in
  `SNAPSHOT.json.sources[tag].skipped` (`{rel, errno}`), so a later reader
  of the snapshot can see what it is missing and why. Exit code **2**
  (published, with skips) — distinguishable by the scheduler for alerting,
  printed identically for a human.
- **Retry is automatic:** the next run diffs against this snapshot's
  manifest, in which the skipped file is absent, so
  `synccli.changed_files` (synccli.py:39–41 — a rel missing from the old
  manifest is "changed") re-selects it for copy. No retry bookkeeping
  exists; the landed-set manifest *is* the retry mechanism. (This is the
  precise sense in which `copy_file`'s comment "next pass will retry",
  synccli.py:69, becomes true — in `synccli.sync` it is false, because
  there the manifest records intent, not landings: G1.)

### 8.2 Fatal failures — abort, publish nothing

Errno classes that mean the *environment* failed, not one file — `ENOSPC`
or `EROFS` on the backup root, `EIO` writing staging metadata — abort the
run: exit **1**, nothing published, best-effort rmtree of the staging dir;
if even that fails, the next run's sweep finishes it (§7.1). Rationale: an
`ENOSPC` mid-materialization would otherwise produce a snapshot riddled
with skips while consuming the retention budget (§10.3 treats skip-carrying
snapshots specially for exactly the non-fatal case).

---

## 9. Change detection

### 9.1 Granularity

**Per file**, decided by the pair `(size, st_mtime)` — exactly
`synccli.file_state`'s record (synccli.py:22–25) — compared with `!=`
against the baseline snapshot's stored manifest entry by
`synccli.changed_files` (synccli.py:36–42). A file is copied iff it is new
or its pair differs; otherwise it is hardlinked (§5 step 5). States are
compared in **source space**: the manifest stores the source's mtime at
scan time, never the staged copy's copy-time mtime (O3; C0 showed why this
distinction is load-bearing).

### 9.2 What this granularity misses — stated explicitly

An edit is missed **iff** it leaves both `size` and `st_mtime` bit-identical
to the recorded values:

- a writer that restores mtime after writing (`rsync -a`-style touch-back,
  editors preserving timestamps, `touch -r`) with a same-length write —
  **verified** (§14, F1): content changed `AAAA`→`BBBB`, mtime restored,
  `changed_files` returns `[]`;
- a system-clock adjustment that lands a same-size write on a previously
  recorded mtime value.

An edit that changes size, or moves mtime in *either* direction (the
comparison is `!=`, not `>`, synccli.py:40 — a backwards mtime also flags),
is always caught. Miss-window for the common case (writer updates mtime
normally): zero. Optional hardening, off by default, a per-source config
flag `detect: "hash"`: state becomes `(size, blake2b(first 64 KiB ‖ last
64 KiB))`, closing the mtime-preservation hole at the cost of reading up to
128 KiB of *every* file every run (F × ~0.1 ms I/O on this machine class) —
for directories where correctness of same-size edits matters more than
run time. Default stays `(size, mtime)`, consistent with the existing code.

### 9.3 Deletions

`changed_files` iterates only the new manifest (synccli.py:39), so it never
reports deletions — in `synccli.sync`, whose destination is persistent,
that leaves stale files in dst forever. In `backupctl` it is harmless by
construction: each run materializes a *fresh* tree from the new manifest,
so a source file deleted since the baseline simply has no entry and is
neither copied nor linked — deletion propagates structurally, with no
delete pass. Deletions are computed for the *report* only, via
`synccli.collect_stale` (§4.1; verified I1).

### 9.4 Inherited limits, documented

`scan_all` inherits `scan_files`'s files-only walk (synccli.py:10–19):
empty directories are not reproduced in snapshots, and symlinks are treated
as the files they point to (`copy_file_checked` reads the target; a
dangling symlink is an `ENOENT` skip, §8.1). Accepted: evals result trees
are file trees; capturing empty dirs or symlink identity would require a
metadata sidecar the restore tool doesn't consume.

---

## 10. Retention

**Policy (defaults, config-overridable):** keep the newest `keep = 7`
snapshots; `grace = 2`.

- **Victim selection reuses `snaputil.prune_snapshots`'s semantics**
  (snaputil.py:30–33): `doomed = list_snapshots(root)[:len(names) - keep]`
  — oldest-first, and the newest snapshot is never a victim (docstring
  guarantee, snaputil.py:26–28). Ordering caveat handled: lexicographic =
  chronological requires a non-backwards clock; if the just-published name
  sorts *before* the previously-newest name (clock step), the run reports
  the anomaly and skips pruning this round rather than risking dooming the
  true newest.
- **Deletion mechanism is O4** (rename-into-`.trash` then rmtree), making
  deletion safe against concurrent readers (§6.3) and resumable after a
  crash (§7.1).
- **Never without a usable snapshot.** Three guards, in order:
  1. prune runs only *after* step 7 succeeded — a run always adds a
     complete snapshot before it may remove any;
  2. a run whose snapshot carries skips (§8.1) does **not** prune, until
     the published count exceeds `keep + grace` — transient skip storms
     therefore cannot churn the history down to partial snapshots, while
     `grace` bounds the growth a persistently-unreadable file can cause
     (disk bound with grace: §12.3);
  3. post-prune assertion: `list_snapshots(root)` non-empty and the newest
     entry passes validation (§7.3); failure → exit 1 with the report line
     (unreachable under guards 1–2 unless the root is tampered with
     mid-run, which the lock does not cover — filesystem-level tampering
     is outside the threat model, and the assertion converts it from
     silent to loud).
- **Standalone `backupctl prune --keep K`** takes the same lock, runs the
  same two phases, and additionally requires ≥ 1 valid published snapshot
  *before* starting (guard 3 evaluated up front, since there is no
  same-run publish to lean on).
- **Hardlinks make pruning cheap and safe for survivors**: deleting an old
  snapshot frees only the bytes *not* hardlinked into any survivor (C2);
  no reference counting is needed — the filesystem does it (inode link
  count).

---

## 11. Reader / restore contract

Restore is separate tooling; this is the contract it relies on (and that
`backupctl list/status/verify` also follow):

1. `names = snaputil.list_snapshots(root)`; pick the newest (last), or a
   named one. A listed snapshot is complete (§6.2) — no "is the run
   finished?" question exists.
2. Read `SNAPSHOT.json` and `manifest/<tag>.json`. Resolve every entry via
   `snaputil.safe_snapshot_path(root, name, "tree/<tag>/" + rel)`
   (snaputil.py:54–63 — `..` in a stored relpath cannot escape the
   snapshot).
3. Copy back. If opening any path returns `ENOENT` at any point, the
   snapshot was pruned mid-read (§6.3, verified B1): re-run step 1 and fall
   back to the next-newest. Files already opened need no handling — fds
   survive rename and rmtree (verified B2).
4. `.staging-*` and `.trash` are never read: `list_snapshots` cannot return
   them (snaputil.py:18, verified A1).

Guarantees this contract consumes, each established above: visible ⇒
complete (§6.2), manifest ≡ tree (§5 step 6), deletion atomic w.r.t.
readers (§6.3), skip records durable in `SNAPSHOT.json` (§8.1).

---

## 12. Performance budget and scaling bounds

### 12.1 Measured constants (this machine, this directory's code)

Environment: macOS (darwin), APFS on local SSD, Python 3.10.11. Workload:
synthetic evals-shaped tree — **30,000 files, 990 MB** (avg 33 KB), 3 top
dirs × 97 subdirs. Method: direct timing of the functions in *this*
directory (`synccli`, `snaputil`) plus `os.link`/`os.rename`/`statvfs`;
`python3 -m unittest` passes here (6 tests, 0.009 s) confirming the code
under measurement is the shipped code. Each figure below was taken in this
session against these files:

| Constant | Value | Source |
|---|---|---|
| `scan_files` walk | **8.1 µs/file** (0.24 s / 30k) | timed |
| `build_manifest_all` (walk + stat + dict) | **29.6 µs/file** (0.89 s / 30k) | timed |
| Manifest memory | **484 B/file** (RSS +13.8 MB / 30k) | RSS delta |
| Peak RSS through a full sync | **1.15 KB/file** (+34.7 MB / 30k) | RSS delta |
| `json.dumps` of manifest | **0.7 µs/entry**, 68 B/entry (0.02 s, 2.0 MB / 30k) | timed |
| `changed_files` diff | **< 1 ms / 30k entries** | timed |
| First full `synccli.sync` (scan+copy+manifest, 990 MB) | **11.19 s end-to-end** = 88 MB/s effective; copy loop ≈ 10.3 s ≈ **0.34 ms/file** | timed |
| Second `synccli.sync`, no changes | **0.99 s** | timed (≈ scan+diff floor) |
| `copy_file`, 4 × 128 MB | 3.1 GB/s (page cache, unflushed) — byte term is not the bottleneck for big files; whole-file `read()` (synccli.py:67) allocates file size in RAM (O2 fixes) | timed |
| `os.link` per unchanged file | **381–489 µs quiet; 1500–1680 µs under write-back pressure** | timed, repeated |
| File-create+write 33 KB under pressure | 557 µs | timed |
| `os.rename` under pressure | ~0.55–0.59 ms/op | timed |
| `snapshot_disk_usage` walk | **23.8 µs/file** (0.71 s / 30k) | timed |
| Hardlink marginal disk | **692 B/link** (Δ`f_bavail` = 13.8 MB over 20k links whose apparent size is 660 MB) | statvfs |
| Metadata-op variance factor | **≈ 4.4×** (381→1680 µs, quiet vs write-back pressure) | timed |

Honest note on variance: every file-*metadata* operation on this machine
costs 0.4–1.7 ms depending on write-back pressure — unusually high
(order of ms, not µs, for `link`/`rename`/`create`). The budget below uses
the measured envelope, not the lucky run.

### 12.2 First full backup of ~1 GB / ~30k files — budget and derivation

Composition (F = 30k files, B = 990 MB, C = F on a first run):

| Phase | Formula | Value |
|---|---|---|
| Source manifest | F × 29.6 µs | 0.89 s (measured) |
| Copy loop | F × 0.34 ms (+ bytes, overlapped — 33 KB/file at the measured 88 MB/s effective rate is inside the 0.34 ms) | 10.3 s (measured inside `sync`) |
| Landed-set staging scan | F × 29.6 µs | 0.89 s (measured) |
| Manifests + SNAPSHOT.json | F × 0.7 µs + ms | 0.02 s (measured) |
| Publish rename + index replace | 2 metadata ops | ~1–2 ms (measured rename ~0.55 ms under pressure) |
| **Total, measured-equivalent** | | **≈ 12.1 s** |

Conservative closed-form bound (terms measured independently; sum
over-counts because byte transfer overlaps per-file overhead — actual 12.1 s
vs bound 24.2 s):

> **T₁ ≤ F × 0.43 ms + B / 88 MB/s**

**Budget: the initial full backup of a ~1 GB / tens-of-thousands-of-files
tree completes in ≤ 60 s wall-clock on this machine class.** Derivation:
2.5× the conservative bound (24.2 s), ≈ 5× the measured-equivalent (12.1 s).
The ~5× margin is not padding — it is the measured metadata variance factor
(4.4×, §12.1) applied once. Steady-state run budget, same derivation:
typical ≤ 20 s (measured-equivalent 13.2 s: two manifest scans 1.8 s +
30k links at 381 µs = 11.4 s), worst-case ≤ 60 s (links at the pressured
1.7 ms give 51 s + 1.8 s). A run with C changed files substitutes
C × (0.34 ms + ΔB/88 MB/s) for C of the link terms.

### 12.3 What grows with what — explicit bounds

N = configured directories, F = Σ Fᵢ total files across sources, B = total
bytes, C/ΔB = files/bytes changed per run, K = keep, G = grace. Constants
from §12.1. Per-source processing is **sequential** (step 3–6 per tag, one
tag's manifests released before the next is built) — that is what makes
memory max-over-sources instead of sum-over-sources.

| Quantity | Bound | Grows with | Flat in |
|---|---|---|---|
| Per-run wall time | `2F × 29.6 µs + (F−C) × t_link + C × 0.34 ms + ΔB / 88 MB/s + N × ~2 ms`, `t_link ∈ [0.38, 1.7] ms` → 30k files: 13–53 s | F (linear, link-dominated), ΔB | N beyond the N×2 ms per-source constant (SNAPSHOT.json entry, manifest open): 30 dirs → +60 ms |
| Peak RSS | `maxᵢ(Fᵢ) × 1.2 KB + K·N × 120 B` → largest source 30k files: ≈ 36 MB (measured 34.7 MB) | largest single source's file count | N (sequential), K beyond index terms |
| Disk, total under backup root | `S_union + (K+G) × F × 692 B`, where `S_union ≤ max Sᵢ + Σ ΔB over retained runs` → e.g. 1 GB base + 7×30k×692 B ≈ 1 GB + 145 MB + changed bytes | bytes actually changed between runs (ΔB), link records at 692 B/file/snapshot (measured) | unchanged bytes (hardlinked: 0 data bytes — measured Δdf, E1) |
| Apparent per-snapshot size (`snapshot_disk_usage`, snaputil.py:39–51) | = Sᵢ (full tree; counts shared inodes per snapshot — reporting number, not marginal cost) | Sᵢ | — |
| `index.json` | `K × N × ~120 B` → 7 × 30 ≈ 25 KB | K·N | F, B |
| Per-run report | `O(N + skips + pruned)` lines | failures only | F |
| Per-run syscalls | `≈ 2F stats + (F−C) links + C × (open+read+write+close) + (K+G) renames worst case` | F, C | — |
| `verify` (all snapshots) | `K × F × 30 µs` → 7 × 30k ≈ 6.3 s | K·F | — |
| Baseline validation (step 3) | `F_base × 30 µs` ≈ 0.9 s / 30k, once per run | F of the newest snapshot | K |

"Three directories today, a few dozen over time": every run-cost row above
is linear in total **files and changed bytes**, with N contributing only
fixed per-source constants (≈ 2 ms, 120 B index, one manifest file) — so
3 → 30 directories changes the constants' multiplier by 10× on terms that
are milliseconds and kilobytes, while the F-terms are unchanged for the
same total tree.

---

## 13. CLI, config, exit codes, report

### 13.1 Commands

```
backupctl run    [--root R] [--wait] [--dry-run] [--keep K] [--grace G]
backupctl list   [--root R]                 # list_snapshots + index; apparent sizes via snapshot_disk_usage
backupctl status [--root R]                 # lock held?, index health (reconcile §7.2), counts, quarantine/trash state
backupctl verify [SNAP] [--root R]          # manifest↔tree validation (§7.3) across all / one snapshot
backupctl prune  [--root R] --keep K        # standalone two-phase prune (§10)
```

### 13.2 Config — `<root>/config.json`

```json
{"version": 1,
 "sources": {"evals-results": "/path/to/evals/results", "...": "..."},
 "keep": 7, "grace": 2,
 "detect": {"<tag>": "size-mtime | hash"}}
```

Tags validated `[A-Za-z0-9._-]+`, no leading dot (§3). A source removed
from config keeps its history in old snapshots; new snapshots simply lack
the tag. A source added mid-history has no baseline → first run copies it
fully (§5 step 3).

### 13.3 Exit codes

| Code | Meaning |
|---|---|
| 0 | snapshot published, zero skips |
| 2 | snapshot published, ≥ 1 per-file skip (§8.1) |
| 3 | lock busy — another run in progress (§6.1) |
| 1 | fatal — nothing published (§8.2), or post-prune assertion failed (§10) |

Same codes and same output whether invoked by the scheduler or a human —
requirement of §8.1; there is no TTY-dependent behavior anywhere.

### 13.4 Run report (stdout; skips mirrored to stderr)

```
snap-20261116-150000-03 published in 13.4s (keep=7)
  evals-results: scanned 30112, copied 214 (7.1 MB), linked 29898,
                 deleted-since-prev 12, skipped 2
    SKIP evals-results/run-42/blob.bin: ENOENT (vanished after listing)
    SKIP evals-results/run-99/lock.db: EACCES
  pruned: snap-20261102-030000-00, snap-20261103-030000-00
  recovery: discarded .staging-snap-20261116-093012-00 (dead run);
            index.json corrupt — rebuilt from 7 snapshot directories;
            resumed trash deletion: snap-20261101-030000-00
```

---

## 14. Verification log

Every load-bearing claim above was checked in this directory / on this
machine before being written down. `python3 -m unittest` (test_synccli.py):
6/6 pass. Mechanism checks (temp-dir scripts over `synccli`/`snaputil` as
imported from this directory):

| Check | Result | Used in |
|---|---|---|
| A1 | populated `.staging-*` invisible to `snaputil.list_snapshots` | §3, §6.2 |
| A2 | after `os.rename` → listed | §5 step 7, §6.2 |
| B1 | re-open of a published path after rename-into-`.trash` → `ENOENT` | §6.3, §11 |
| B2 | fd opened before the rename reads full content after rename **and** rmtree | §6.3, §11 |
| C0 | `copy_file` does not preserve source mtime (staged mtime = copy time) | O3, §9.1 |
| C1 | `os.link` preserves prev inode mtime+size | §5 step 5, §9.1 |
| C2 | rmtree of older snapshot leaves newer hardlinked tree intact (content, size) | §2, §6.3, §10 |
| C3 | `list_snapshots` shows only published survivors | §6.3 |
| D1 | second `flock(LOCK_EX\|LOCK_NB)` → `BlockingIOError` | §6.1 |
| D2 | flock released when holder is SIGKILL-ed; next acquirer succeeds | §6.1, §7 |
| E1 | 20k hardlinks (660 MB apparent) cost 13.8 MB real (692 B/link) | §12.1, §12.3 |
| F1 | `changed_files` returns `[]` for a same-size, mtime-restored edit | §9.2 |
| G1 | `sync()`-style manifest lists a vanished file absent from dst — the hazard O2/O3 remove | O2, O3, §8.1 |
| H1 | half-written `index.json` raises `JSONDecodeError`; `list_snapshots` re-enumerates the published set | §7.2 |
| I1 | `collect_stale([(rel, rel in new) for rel in old])` = old−new deletions | §4.1, §9.3 |

Performance figures: §12.1 table, each row timed in this session against
the 30k-file / 990 MB synthetic tree described there.

# DESIGN-d1 — `backupctl`

A command-line backup tool for this repo's `evals/` workflow: it snapshots a
configured set of source directories into point-in-time snapshots under a backup
root, incrementally, safely under concurrency and crashes.

Everything in this document that is a number was measured on the repo copy
(macOS/Darwin, APFS, CPython 3.10.11, 14 logical CPUs) with the harnesses
listed in Appendix A; the raw output is in Appendix B. Claims that are
*formulas* state the constants they are built from and where each constant
came from.

---

## 0. Decisions at a glance

| # | Decision | Why |
|---|---|---|
| D1 | Each snapshot is a **materialized directory tree** (`<snap>/<source_id>/<relpath>`) | The restore is separate tooling that "reads a snapshot and copies it back"; it must not have to resolve inheritance chains |
| D2 | A run writes into a private staging dir and **publishes by one atomic `rename`** of that directory | A reader sees a snapshot only when it is complete; a dead run leaves nothing a reader can mistake for a snapshot |
| D3 | Runs are **serialized by an `flock`**, and *additionally* safe without it | Two colliding runs (scheduler + human) must not corrupt each other |
| D4 | Retention is **two-phase**: atomic tombstone, delayed reclaim | Never delete a snapshot in place — a reader must never see a half-deleted tree |
| D5 | "Unchanged" is decided **per file** on `(size, mtime)` — `synccli.file_state` | Reuses the existing manifest semantics; the misses are enumerated in §9 |
| D6 | Unchanged files are materialized by **CoW clone** (`clonefile`), falling back to hard link, then copy | No bytes are re-copied; clones have independent inodes, so no shared-inode corruption hazard |
| D7 | The stored file **carries the source's mtime** (`os.utime(ns=…)`) | Makes the tree self-describing: the index can always be re-derived from the tree |
| D8 | The index is a **derived cache** with a digest; the tree is the truth | Recovery from a damaged index is defined (re-derive from the tree), never "guess" |
| D9 | A vanished/unreadable source file is **omitted and reported**, not fatal | The run still publishes a valid snapshot; the omission is retried next run (free: the file is simply absent from the manifest, so the diff sees it as new) |
| D10 | Trigger (scheduler vs. human) is **not a code path** | One `run` implementation, one report format, one set of exit codes |

---

## 1. Scope and vocabulary

**Sources.** A configured list of `N` directories (`N = 3` today, "a few dozen"
later). Each has a stable `id` (used as a directory name inside a snapshot) and
an absolute path.

**Backup root.** One directory holding all snapshots plus backupctl's private
state. It lives on one filesystem (required: publication is a `rename`).

**Snapshot.** An immutable point-in-time copy of all sources, named
`snap-YYYYMMDD-HHMMSS-NNNNNN` (UTC). The shape matches the convention
documented in `snaputil.list_snapshots` (`snaputil.py:9-14`: "a date, a time,
and a run sequence number, separated by dashes"); the sequence is a
zero-padded 6-digit counter so that lexicographic order (which is what
`snaputil.list_snapshots` returns, `snaputil.py:20`) is chronological order.

**Index.** Per-snapshot metadata (`index.json`) + one per-source per-file
manifest (`manifests/<source_id>/files.jsonl.gz`). It *promises* a file list;
the promise is enforced by a digest and by `backupctl verify`.

**Report.** What the run did, in JSON (`<root>/.reports/<snapshot_id>.json`)
and in a human summary on stdout. Derived from `index.json`, so it survives a
crash between publish and report-write.

**Non-goals** (explicitly out of scope): remote/object-store targets,
encryption, restore implementation, preservation of ownership/xattrs,
preservation of the source's hard-link structure, backup of the backup root.

---

## 2. Grounding — what is reused, what is overridden

Everything below was checked against the files in this directory (the
repository's existing suite passes as-is: `python3 -m unittest` → **6 tests,
OK, 0.004 s**).

### 2.1 Reused

(The one entry that is used with a modification is `synccli.build_manifest`;
the modification is item 1 of §2.2 and is called out in its row.)

| Artifact | Location | Use in `backupctl` |
|---|---|---|
| `synccli.file_state(path)` | `synccli.py:22-25` | The change-detection state: `{size, mtime}`. This *is* the "unchanged" key (§9) |
| `synccli.changed_files(old, new)` | `synccli.py:36-42` | The diff between the previous snapshot's manifest and this run's scan — used verbatim, including its "detects added/changed, not deleted" semantics |
| `synccli.build_manifest(root)` | `synccli.py:28-34` | Its loop shape (scan → `file_state` per file) is the per-source manifest builder; §2.2 replaces only the scan it calls |
| `synccli.MANIFEST_NAME` | `synccli.py:7` | The exported compatibility manifest is named `.sync_manifest.json` and uses the exact `synccli` schema |
| `snaputil.list_snapshots(root)` | `snaputil.py:8-20` | Enumerates snapshots for `list`, retention candidates, and GC. Note its filter `name.startswith("snap-") and entry.is_dir()` (`snaputil.py:18`) — this is why backupctl's private areas are named `.incoming/`, `.trash/`, `.reports/`, `.lock`: they are invisible to it |
| `snaputil.snapshot_disk_usage(root, name)` | `snaputil.py:39-51` | Per-snapshot size in reports. Caveat: it sums `st_size` of every file (`snaputil.py:50`), so for clone/link-shared content it reports *apparent* bytes, not unique bytes — the report labels it accordingly and adds the unique-bytes figure the run knows from its own counts |
| `snaputil.safe_snapshot_path(root, name, rel)` | `snaputil.py:54-63` | Path resolution inside a snapshot — **but with an override, see 2.2 #6** |

### 2.2 Overridden (with the exact line and the reason)

| # | Existing behavior | Where | Override and reason |
|---|---|---|---|
| 1 | `scan_files` drops every directory whose name starts with `.` | `synccli.py:14` (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`) | **Overridden** by `backupctl.scan_tree()`: a backup that silently drops `.git/`, `.venv/`, `.config/` loses source data. Verified: `synccli.scan_files` on a tree containing `.hidden_dir/data.bin` returns only `['.dotfile']` — the hidden *directory's* contents are dropped while the hidden *file* is kept |
| 2 | `copy_file` swallows every `OSError` | `synccli.py:68-69` (`except OSError: pass`) | **Overridden** by `backupctl.copy_file()`: a source file that vanished (`ENOENT`) or is unreadable (`EACCES`) must be *reported*, not silently counted as copied. Verified: `synccli.copy_file(<missing>, dst)` returns normally and leaves no file — `synccli.sync` would then report that path in its copied list |
| 3 | `copy_file` writes straight to the final path | `synccli.py:66-67` (`open(dst, "wb")`) | **Overridden**: a crash mid-write leaves a truncated file. In backupctl the target is inside the *private staging dir*, which is discarded on failure, so the final path needs no per-file temp+rename. This also *saves* work: the `.part`+`rename` variant measured **251.2 µs/file** vs **155.7 µs/file** for a direct write (§11) |
| 4 | `copy_file` reads the whole file into memory | `synccli.py:67` (`fdst.write(fsrc.read())`) | **Overridden** by a chunked copy (1 MiB buffer): peak memory becomes O(1) in file size instead of O(largest file) |
| 5 | `copy_file` calls `os.makedirs(..., exist_ok=True)` per file | `synccli.py:64` | **Overridden** by caching the set of created directories — per-file directory metadata ops are a measurable share of the per-file cost on this filesystem |
| 6 | `safe_snapshot_path` claims `..` segments are normalized away | `snaputil.py:54-63`, claim at `snaputil.py:58-60` | **The claim is false** — verified: `snaputil.safe_snapshot_path("/tmp/backuproot", "snap-1", "../../etc/passwd")` → `/tmp/backuproot/snap-1/../../etc/passwd`, which resolves to `/tmp/etc/passwd`, i.e. **outside** the snapshot (`os.path.normpath("../../etc/passwd")` is unchanged). **Overridden** by `backupctl.resolve_in_snapshot()`: `normpath` → reject absolute paths and any result starting with `..` → then assert `os.path.realpath(result)` is under `realpath(snapshot_root)`. The restore tooling that calls `snaputil.safe_snapshot_path` directly is still exposed to this; a one-line fix to `snaputil.py` is recommended as a follow-up (not made here — this document is the deliverable) |
| 7 | `prune_snapshots` deletes a snapshot **in place** | `snaputil.py:23-37`, specifically `shutil.rmtree(os.path.join(backup_root, name))` at `snaputil.py:35` | **Overridden** by the two-phase retention in §10. `rmtree` empties the directory tree file by file, so a concurrent reader can observe a snapshot that has lost files — precisely the "index promises files the snapshot does not contain" failure the brief forbids. `snaputil.list_snapshots` (the ordering part) *is* reused |
| 8 | `is_stale`'s docstring contradicts its code | `snaputil.py:66-73`: docstring says "A snapshot whose directory was modified at exactly ref_epoch is not stale", but the code is `st_mtime <= ref_epoch` → equal **is** stale. Verified: `is_stale(dir, os.stat(dir).st_mtime)` → `True` | **Not used.** backupctl compares against the UTC timestamp embedded in the snapshot name / recorded in `index.json`, never against a directory mtime (a snapshot directory's mtime also changes whenever anything is added to it) |
| 9 | `sync` reads the manifest without error handling and writes it non-atomically | `synccli.py:77-79` (`json.load` unguarded) and `synccli.py:85-86` (`open(..., "w")` + `json.dump`) | **Overridden** by the staging/publish protocol and the digest-checked, recoverable index (§7). Verified failure mode of the existing code: a manifest truncated mid-write makes the *next* `synccli.sync` die with `json.JSONDecodeError: Expecting ',' delimiter: line 1 column 35` |

Everything else in `synccli.py`/`snaputil.py` is left untouched.

---

## 3. On-disk layout

```
<backup_root>/
  .lock                              # flock target for run serialization
  .seq                               # monotonic snapshot counter
  .incoming/<run-id>/                # staging area of a live run (hidden from snaputil)
  .trash/<snapshot-id>/              # tombstoned snapshots awaiting reclaim
  .reports/<snapshot-id>.json        # run report (also embedded in index.json)
  snap-20261112-120000-000001/
      index.json                     # snapshot-level metadata + digests
      manifests/evals/files.jsonl.gz # per-source per-file manifest (the "index")
      evals/                         # mirror of source id "evals"
          <relative path of every file in the source>
      evals-2/                       # mirror of source id "evals-2", etc.
```

Two properties matter:

* **The directory layout encodes the source mapping.** A file's source-relative
  path is recoverable from its location (`<snap>/<source_id>/<relpath>`), so the
  per-file manifest can always be rebuilt from the tree (§7.1).
* **Private areas are invisible to the existing tooling.** `snaputil.list_snapshots`
  filters on `name.startswith("snap-") and entry.is_dir()` (`snaputil.py:18`), so
  `.incoming/`, `.trash/`, `.reports/`, `.lock` never appear in a listing, and
  a half-written snapshot can never be mistaken for a published one.

### 3.1 `index.json`

```json
{
  "format": "backupctl/1",
  "snapshot_id": "snap-20261112-120000-000001",
  "created_utc": "2026-11-12T12:00:00Z",
  "run_id": "run-20261112T115930Z-4412-ab12cd",
  "trigger": "scheduler",
  "sources": [
    {"id": "evals", "path": "/abs/path/evals", "file_count": 35000,
     "bytes": 1073741824, "manifest": "manifests/evals/files.jsonl.gz",
     "manifest_sha256": "…", "manifest_records": 35000}
  ],
  "counts": {"copied": 120, "cloned": 34880, "linked": 0, "missing": 0,
             "unreadable": 0, "suspect": 0},
  "missing": [{"source": "evals", "path": "runs/7/out.bin", "reason": "vanished"}],
  "suspect": ["runs/7/influx.bin"]
}
```

The manifest is per source and gzipped JSONL, one record per file:

```
{"p": "runs/7/out.bin", "s": 4096, "m": 1794871025.1220803}
```

`p` = source-relative path, `s` = size, `m` = `mtime` (float seconds, exactly
`synccli.file_state`'s value). Loaded into `{rel: {"size":…, "mtime":…}}`
before the diff so that **`synccli.changed_files` can be used verbatim**
(`synccli.py:36-42`).

Size: 62 B/file uncompressed JSONL, **7.9 B/file gzipped** (measured, §11);
the equivalent `synccli`-schema JSON is 84 B/file compact / 109 B/file with
`synccli`'s `indent=2` (`synccli.py:85`).

For tooling that expects the old manifest, `backupctl export-manifest <snap>
<source_id>` writes the exact `synccli` schema
(`{rel: {"size":…, "mtime":…}}`, `json.dump(..., indent=2)`, file named
`.sync_manifest.json`) into the snapshot.

---

## 4. The run protocol

`backupctl run` executes these phases. Phases 1–3 are per source; phase 4 is
snapshot-wide.

**Phase 0 — claim the lock.** `open(<root>/.lock, "w")` then
`flock(fd, LOCK_EX | LOCK_NB)`; on `BlockingIOError` poll every 1 s up to
`--lock-wait` (default 300 s), then exit **75** (`EX_TEMPFAIL`) with
`another backupctl run holds <root>/.lock`. (Verified: `flock` with
`LOCK_NB` on a second handle raises `BlockingIOError`.)

**Phase 0b — GC.** Under the lock: remove `.incoming/<run-id>` directories that
are older than `--stale-staging-hours` (default 6) and `.trash/<id>`
directories older than the reclaim grace period (§10). Report what was removed.

**Phase 1 — scan the source.** `backupctl.scan_tree(root)` (the corrected
`synccli.scan_files`, §2.2 #1) → sorted relative paths; then
`synccli.file_state` per path → the new state map.

**Phase 2 — diff against the base.** The base is the **previous published
snapshot's manifest** for that source. If that manifest is missing or fails
its digest, the base is **re-derived from the previous snapshot's tree**
(walk + stat; the stored files carry the source's `mtime`, §9.3) and the run
reports `previous snapshot snap-…: manifest damaged, rebuilt from the tree`.
If the tree is damaged too, the source is treated as having no base → the run
re-copies it in full and says so loudly.

`synccli.changed_files(base, new_state)` gives three sets:

* **changed** — present in both, `(size, mtime)` differs → copy the bytes;
* **new** — in `new_state`, not in `base` → copy the bytes (this set also
  contains files that were missing/unreadable in a previous run: they were
  absent from that manifest, so they are retried automatically);
* **absent** — in `base`, not in `new_state` → the source file is gone. The
  new snapshot simply does not contain it (a snapshot is an image of the
  source at copy time). The run reports the count.

`synccli.changed_files` returns only the first two sets — it iterates over
`new_manifest` (`synccli.py:39-42`) and therefore never reports deletions.
The absent set is computed by backupctl as `set(base) - set(new_state)`;
nothing about the *copy* decision depends on it, so `changed_files` is still
used verbatim.

**Phase 3 — materialize the snapshot tree** (inside `.incoming/<run-id>/`):

* changed/new file → `backupctl.copy_file()`: chunked copy, then
  `os.utime(dst, ns=(src_atime_ns, src_mtime_ns))` so the stored file carries
  the source's timestamp exactly (§9.3). **After the copy the source is
  re-stat'ed**: the manifest records the *post-copy* observed state, so the
  manifest and the stored bytes agree by construction; if the post-copy state
  differs from the scan-time state, the file is additionally listed in
  `index.json`'s `suspect` array and is re-copied unconditionally by the next
  run (§8);
* unchanged file → **materialize without copying bytes**:
  `clonefile(prev_snapshot_file, new_snapshot_file)` (APFS copy-on-write,
  independent inode) → if unsupported, `os.link` (same inode, shared content)
  → if the two are on different devices, plain copy. The mechanism used is
  counted in `index.json` (`cloned` / `linked` / `copied`).

  For the clone and link paths the timestamp is inherited from the previous
  snapshot's stored copy, which — because the file is unchanged — already
  equals the source's current `mtime`. No `utime` is applied to a shared
  inode (it would alter the older snapshot's metadata).

  *Space effect (measured, §11):* 8 CoW clones of a 512 MiB file consumed
  **0.0 MiB**; 4 real copies consumed **2068 MiB**. Unchanged content is
  therefore stored once for the whole retention window.

**Phase 4 — index, then publish.**

1. write `manifests/<source>/files.jsonl.gz` (one record per stored file,
   including the ones inherited by clone/link — the manifest describes *what
   the snapshot contains*, not how it got there; for copied files the record
   holds the post-copy observed state, per Phase 3);
2. write `index.json` (with the manifest's sha256 and record count);
3. `fsync` the files and the directories (durability, §6.3);
4. **`os.rename(.incoming/<run-id>, <root>/snap-…)`** — one atomic syscall
   (measured **0.110 ms**);
5. write `.reports/<snapshot-id>.json` (derived from `index.json`, so it is
   reconstructible if this step is lost).

**Phase 5 — retention** (§10), still under the lock.

---

## 5. Concurrency

### 5.1 Two runs at the same time

The scheduler and a person can start a run at the same instant.

* **Primary mechanism:** the `flock` serializes them. The second one waits
  (`--lock-wait`, default 300 s) and then runs, or exits 75 with a clear
  message. Two runs never write into the same staging area, and only the
  lock holder mutates the trash/GC areas.
* **Defence in depth — the design is still correct if the lock is bypassed:**
  each run writes only inside its own `.incoming/<run-id>/`, publishes by an
  atomic `rename` to a **unique** name, and never mutates a published
  snapshot. Two concurrent runs therefore produce two complete snapshots;
  they cannot interleave writes, cannot produce a torn snapshot, and cannot
  corrupt each other's manifest. The only shared mutable objects are the
  lock file and the counter in `.seq` (both touched under the lock; the
  snapshot name is additionally made unique by a random suffix if the
  counter races).
* The lock is **not** held across the whole run by necessity — it is, in this
  design, because retention (§10) must not race. If a future version wants
  parallel runs, retention can be moved to a separate `backupctl prune`
  command; the design keeps it inside `run` so that "the root only grows"
  is enforced by the same lock.

### 5.2 A reader during a run

A restore reads a published snapshot while a run writes a new one.

* The run **never writes into a published snapshot**. Its only write target is
  its private staging directory.
* The run's only mutation of published state is retention, which is
  two-phase (§10) and never empties a snapshot in place.
* Therefore a reader that has opened a file keeps reading it (POSIX: unlinking
  does not invalidate an open descriptor), and a reader that lists the root
  sees only complete snapshots.

---

## 6. "A reader never asks whether the run is finished"

### 6.1 Publication is a single atomic step

The snapshot becomes visible to any reader — `snaputil.list_snapshots`, a
human with `ls`, a restore — only at the `rename` in Phase 4.4. Before that
moment the run's output lives under `.incoming/`, which (a) is not named
`snap-*`, so `snaputil.list_snapshots` (`snaputil.py:17-19`) skips it, and (b)
is not a snapshot at all.

There is no state in which a reader can see a partially populated snapshot
directory. The `rename` is atomic on POSIX for a directory within one
filesystem; the staging area is deliberately inside the backup root so the
rename never crosses a device.

### 6.2 The index can never promise a file that is not there

The index is written *inside the staging directory* before the rename, so it
is published atomically with the tree it describes. In addition:

* `index.json` records each source manifest's `sha256` and record count;
  a reader can detect any mismatch;
* `backupctl verify <snap>` walks the tree and compares it against the
  manifest in both directions (every promised file exists with the recorded
  size and mtime; every file in the tree is promised). Measured cost of the
  tree walk: **0.54 µs/file** (`snapshot_disk_usage` over 5,000 files:
  0.0027 s), so verification of a 35,000-file snapshot costs ~0.02 s plus
  the manifest read.

### 6.3 Durability (process death vs. machine death)

* **Process death** (Ctrl-C, `kill`, laptop sleep) is fully covered: the
  staging directory is discarded by the next run's GC, and nothing partial
  was ever visible (§7).
* **Machine death** (power loss) is covered by fsyncing the files and
  directories before the rename. Measured: fsync of a freshly written 4 KiB
  file = **0.030 ms median / 0.037 ms p95**; fsyncing 35,000 files ≈ **1.05 s**
  (plus 1.85 s measured over the 1.85 GiB tree, which included flushing that
  much new data). `--no-fsync-files` trades this away and is documented as
  "process-death safety only".

---

## 7. Crash matrix and recovery

| Crash point | What is on disk | Next run does | Report says |
|---|---|---|---|
| Before the staging dir exists | nothing | nothing | — |
| Mid-copy | `.incoming/<run-id>/` with partial files | GC removes it after `--stale-staging-hours` (default 6 h) | `discarded interrupted staging run-… (N files)` |
| After the manifest, before the rename | `.incoming/<run-id>/` complete but unpublished | same as above | same |
| During the rename | either published or not — never half | — | — |
| After the rename, before the report | a complete snapshot; no report file | the next run's report is regenerated from `index.json` (the counts are stored there) | `snapshot snap-… was published by a run whose report file is missing` |
| A published snapshot's manifest is truncated/garbled | the snapshot's **tree is intact** | `backupctl recover <snap>` re-derives the manifest from the tree (§7.1) and rewrites it atomically | `manifest of snap-… rebuilt from the tree (N records)` |
| The previous snapshot's manifest is damaged but its tree is intact | — | the base is re-derived from the previous snapshot's tree; the run continues | `previous snapshot snap-…: manifest damaged, rebuilt from the tree` |
| The previous snapshot's manifest *and* tree are damaged | — | that source is treated as having no base → **full re-copy** of it | `previous snapshot snap-… is damaged; source evals was re-copied in full` |
| `index.json` itself is unreadable | the tree is intact but the snapshot's identity is lost | the snapshot is quarantined (renamed to `.quarantine/`, excluded from listings) and reported | `snapshot snap-…: index unreadable, quarantined` |

### 7.1 What is discarded, what is re-derived, what is reported

For a damaged index the brief asks for an explicit answer. Here it is:

* **Discarded:** the damaged manifest file (and, for a damaged `index.json`,
  the snapshot's identity — it is quarantined, not deleted, so it can be
  inspected).
* **Re-derived from the tree:** the per-file records. The tree is
  self-describing because Phase 3 stores each file with the source's exact
  `mtime_ns` and `size` (§9.3). Recovery walks
  `<snap>/<source_id>/` and rebuilds `{rel: {"size": st.st_size, "mtime":
  st.st_mtime}}`. Because the stored `mtime_ns` is the source's, the recovered
  float is bit-identical to the original one (float64 has ~238 ns resolution
  at 1.8e9 s, and the round-trip is exact because the same nanosecond value
  is converted the same way both times) — so the recovered manifest produces
  the *same* diff decisions as the original.
* **Not re-derivable:** nothing that the run needs. The source mapping is
  structural (the directory layout), the snapshot id and creation time are in
  the *name* and in `index.json`; if `index.json` is gone the snapshot is
  quarantined rather than guessed at.
* **Reported:** the recovery is listed in the next run's report and by
  `backupctl recover` on stdout: which snapshot, how many records were
  rebuilt, whether the rebuild was byte-identical to the damaged file's
  digest (it cannot be, since the digest was computed over the damaged
  bytes — the report states the new digest).

---

## 8. A source file disappears or is unreadable

The window between Phase 1 (scan) and Phase 3 (copy) is where a file can
vanish or become unreadable.

| Situation | What the snapshot contains | What the run reports | Retry |
|---|---|---|---|
| `ENOENT` at copy time (vanished after the scan) | the file is **absent** from the snapshot — the snapshot is an image of the source as of copy time | `missing` entry in `index.json` + `missing` list in the report, with the source-relative path | automatic: the file is absent from the manifest, so the next run's diff sees it as *new* and copies it |
| `EACCES`/`EPERM` at copy time (unreadable) | absent, same as above | `unreadable` entry, counted separately from `missing` | automatic (same mechanism) |
| The file changes **while it is being copied** | the bytes captured are a possibly-torn copy | the file is added to `index.json`'s `suspect` list | the next run re-copies every `suspect` path unconditionally, regardless of `(size, mtime)` |
| The source directory itself disappears | the source contributes no files | the run reports `source evals: disappeared` and **fails the run** (exit 4, no snapshot published) — a vanished *directory* is a configuration error, unlike a vanished *file* | the next run retries |

**Same behaviour for the scheduler and for a person.** There is exactly one
implementation of a run (`backupctl.run()`); the trigger is a field in
`index.json` (`"trigger": "scheduler" | "human"`) and never changes a
decision. The report format, the exit codes and the snapshot contents are
identical. In particular:

* exit **0** — snapshot published, nothing missing;
* exit **3** — snapshot published, but with omissions (missing/unreadable
  files listed in the report). The snapshot is valid and usable; the exit
  code exists so the scheduler can alert;
* exit **4** — no snapshot published (a source directory is gone, the lock
  could not be taken, the filesystem failed);
* exit **75** (`EX_TEMPFAIL`) — another run holds the lock; the scheduler
  treats this as "another run is doing the work", not as a failure;
* exit **2** — configuration error; exit **1** — usage/internal error.

The machine-readable report (`.reports/<snapshot-id>.json`) is the same file
in both cases, so the scheduler parses exactly what a human reads.

---

## 9. Change detection: granularity and what it misses

### 9.1 The granularity

**One file.** The unit of "unchanged" is a single file, and the key is the
pair `(size, mtime)` produced by `synccli.file_state` (`synccli.py:22-25`).

* Not per block, not per content hash, not per directory, not per whole-tree
  digest.
* The comparison is `synccli.changed_files(base, new)` (`synccli.py:36-42`),
  i.e. dictionary equality of `{size, mtime}` per path.
* The decision is made **per source directory**: each source has its own
  manifest and its own base snapshot, so one noisy directory never forces
  the others to be re-copied.

### 9.2 What this granularity misses

1. **Content edits that preserve size and mtime.** Reproduced:
   rewrite a 1-byte file with different content, then restore its mtime with
   `os.utime` → `synccli.file_state` returns an identical dict → the change is
   invisible, and the snapshot keeps the old bytes. This is the classic
   `cp -p` / `rsync -t` / `tar -x` / `git checkout` case.
2. **Sub-timestamp-granularity edits.** The key inherits the *source
   filesystem's* timestamp resolution. On the reference machine
   `st_mtime_ns` = 1794871025122080378 (nanosecond resolution). On a
   filesystem with 1-second timestamp granularity, two edits within the same
   second that preserve the size are indistinguishable.
3. **Replacement by a different file with the same size and mtime** — the same
   blindness as (1).
4. **Metadata-only changes** — mode, owner, group, xattrs, ACLs are not part
   of the key and are not preserved: the stored file's mode is the one the
   copy created (umask), or, on the clone/link path, the one inherited from
   the previous snapshot's stored copy. (Adding `mode` to the key would make
   `synccli.changed_files` compare dicts of different shapes, since the
   `synccli` schema is exactly `{size, mtime}`.)
5. **Symlink targets.** Symlinks are stored as symlinks (not dereferenced);
   the target's *content* is not part of the backup.
6. **In-flux files** — a file being written during the copy may be captured
   torn; the run detects this by re-stat-ing the source after the copy and
   flags the file `suspect`, which forces a re-copy next run.

A content hash would close (1)–(3) at the cost of reading every byte on
every run (≈ 1 GiB per run for the reference tree, plus hashing cost) —
i.e. it would defeat the incremental requirement. The design takes the
`(size, mtime)` key and states the blindness explicitly; §9.3 explains how the
stored timestamps keep the index and the tree consistent with each other.

### 9.3 Why the stored file carries the source's timestamp

Phase 3 copies with `os.utime(dst, ns=(src_atime_ns, src_mtime_ns))`
(measured cost: **+28.4 µs/file**, from 156.7 → 185.1 µs/file; `os.utime`
alone is 29.2 µs/call on this filesystem). This buys three things:

1. **The tree is self-describing** → the manifest can always be re-derived
   from the tree (§7.1) and `backupctl verify` can check the tree against the
   index with `stat` alone.
2. **A restored file keeps its original timestamp** (a plain `cp -r` of the
   snapshot restores mtimes as well).
3. **The clone/link path needs no `utime`**: the inherited inode already
   carries the source's timestamp, because the file is unchanged by
   definition.

Invariant (checked by `backupctl verify`): *for every file in a snapshot,
`stored.mtime_ns == source.mtime_ns at capture time` and
`stored.size == source.size at capture time`.*

---

## 10. Retention: deleting without endangering readers

### 10.1 Policy

Configured per backup root:

```json
"retention": {"keep": 7, "min_keep": 2, "expire_after_days": 30,
              "reclaim_after_hours": 24}
```

* Candidates = the snapshots returned by `snaputil.list_snapshots(root)`
  (`snaputil.py:8-20`) — reused as-is for enumeration.
* Order = by `index.json`'s `created_utc` (not by name order: a clock that
  moves backwards would otherwise reorder the pruning). Names are still
  lexicographically chronological in the normal case.
* A snapshot is a candidate only if it is **older than `expire_after_days`**
  *and* **keeping it would still leave ≥ `min_keep` published snapshots**.
* The newest snapshot is never a candidate (same invariant as
  `snaputil.prune_snapshots`, `snaputil.py:27-33`, but decided on `created_utc`).

### 10.2 Two-phase deletion (the override of `snaputil.prune_snapshots`)

`snaputil.prune_snapshots` deletes in place (`snaputil.py:35`,
`shutil.rmtree(...)` on the live snapshot path). That is unsafe here: the
directory is emptied file by file, so a concurrent reader can observe a
snapshot that has lost files — the exact "index promises files the snapshot
does not contain" failure.

The override:

**Phase A — tombstone (atomic).**
`os.rename(<root>/snap-X, <root>/.trash/snap-X)`.

* One atomic syscall: the snapshot leaves the visible namespace in one step.
  There is no instant at which a reader sees a partially emptied snapshot.
* The tree is *not* touched: every file is still there, still readable at its
  new path. A reader that already holds an open descriptor keeps reading it
  (POSIX: an unlinked/open file stays valid).
* `snaputil.list_snapshots` no longer lists it (it is not under the root any
  more).

**Phase B — reclaim (delayed).**
The tombstoned tree is `rmtree`'d only after `reclaim_after_hours`
(default 24 h), by a later run's GC phase or by `backupctl gc`. Measured:
`shutil.rmtree` of a 35,000-file snapshot = **2.99 s** (85 µs/file);
`chmod -R u+w` first (needed only if snapshot directories are made read-only,
see below) = 0.014 s per 5,000 files.

### 10.3 The reader-safety argument, stated honestly

* A snapshot is never emptied in place, so a reader can never observe a
  *mixture* of deleted and surviving files.
* A reader that resolved a path *before* the tombstone and opens the file
  *after* it gets `ENOENT` for that one file. The window is one syscall wide
  per file, not the whole run — a restore that opens the next file
  milliseconds later is unaffected.
* To make even that window disappear for cooperating readers, backupctl
  offers a **lease**: `backupctl hold <snapshot>` creates
  `.holds/<snapshot_id>`, and a snapshot with a live lease is never a
  candidate. The restore tooling can call it once before starting and release
  it at the end. The lease is a courtesy mechanism, not a requirement: the
  restore is separate tooling that may not know about it.
* The residual exposure is therefore: *a restore that runs longer than
  `reclaim_after_hours` and that does not take a lease may fail to open files
  of a snapshot that was reclaimed after its tombstone.* The default reclaim
  delay (24 h) is chosen to exceed any plausible restore duration; it is
  configurable, and `expire_after_days` (default 30) is the outer bound on
  how long a snapshot stays visible.
* "Never leave the user without a usable snapshot" is enforced by
  `min_keep` (default 2) *and* by the fact that tombstoning and reclaiming
  never touch the newest snapshots. A run also never deletes a snapshot it
  just created.

### 10.4 Read-only snapshots

Published snapshot directories are left writable (mode `0755`) and snapshot
*files* get the mode the copy created (the umask default), not the source's.
Making them read-only would protect against
an in-place edit inside a snapshot (which, with the link fallback, would also
corrupt older snapshots sharing the inode) — but it would also make a restore
produce read-only files in the source tree, which is a worse outcome. The
protection used instead is **detection**: `backupctl verify` compares each
stored file's size and mtime against the index, so an in-place edit inside a
snapshot is reported (§6.2). With the CoW clone path (the default) there is
no shared inode at all, so such an edit cannot affect any other snapshot.

---

## 11. Performance: measurements, derivation, budget

### 11.1 Reference environment

macOS (Darwin), APFS, CPython 3.10.11, 14 logical CPUs; measurements taken
in the repo copy's own volume (`/private/var/folders/…/bench-v3-48840`),
warm page cache unless stated. Absolute numbers will differ on other
hardware; the *formulas* below carry the constants, so the budget can be
recomputed.

### 11.2 Measured primitives

| Operation | Measured | Where |
|---|---|---|
| `synccli.build_manifest` over 35,000 files | **0.276–0.361 s**; linear fit over F = 7k…35k: `t = 0.027 s + 8.3 µs × F` | B2, B15 |
| raw `os.stat` | 2.1 µs/file | B10 |
| `os.walk` enumeration | 0.50 µs/entry | B10 |
| `synccli.copy_file`, 4 KiB files | **159.8 µs/file** | B11 |
| tuned copy (cached dirs, chunked, direct write) | **155.7 µs/file** | B11, B16 |
| tuned copy + `stat` + `utime(ns=…)` | **185.1 µs/file** | B16 |
| copy via `.part` + `rename` | 251.2 µs/file | B11 |
| `clonefile` (APFS CoW) | 188.8 µs (4 KiB), 186.3 (64 KiB), **128.7 µs** (1 MiB) | B14 |
| `os.link` | 318–337 µs/file | B14 |
| `os.utime` / `os.chmod` / `os.stat` | 29.2 / 31.0 / 1.2 µs per call | B16 |
| `fsync` of a freshly written 4 KiB file | 0.030 ms median, 0.037 ms p95 | B2 |
| `os.replace` (file) | 0.0747 ms | B3 |
| **directory `rename` (publication)** | **0.110 ms** | B3, B15 |
| `json.load` of a 35,000-entry manifest | 0.013–0.016 s | B2, B15 |
| `synccli.changed_files` over 35,000 entries | 0.002–0.003 s | B15 |
| manifest write, compact JSON, 35,000 entries | 0.072 s → 2.38 MB (68 B/file) | B15 |
| manifest size per file | JSONL 62 B, **JSONL+gzip 7.9 B**, JSON compact 84 B, JSON `indent=2` 109 B | B6 |
| in-memory manifest | **472 B/entry** (16.5 MB for 35,000 entries) | B6 |
| `shutil.rmtree` of a 35,000-file snapshot | 2.99 s (85 µs/file) | B3, B7 |
| `snaputil.list_snapshots` over 8–12 snapshots | 0.00006–0.00009 s | B3, B7 |
| `snaputil.snapshot_disk_usage` over 5,000 files | 0.0027 s (0.54 µs/file) | B14 |
| CoW clone of a 512 MiB file × 8 | **0.0 MiB** of disk consumed | B17 |
| hard link of the same × 8 | 0.03 MiB | B17 |
| real copy of the same × 4 | 2068 MiB | B17 |
| volume write throughput (`dd`, 512 MiB) | 3.1 GB/s buffered, 1.15 GB/s `O_DIRECT` | B6 |

### 11.3 End-to-end simulation of the proposed pipeline

Source tree: 35,000 files, 1.85 GiB (mix 29,000×4 KiB, 4,500×64 KiB,
1,500×1 MiB).

| Phase | Run 1 (full) | Run 2 (incremental, 0 changed) |
|---|---|---|
| read the previous manifest | — | 0.016 s |
| scan (walk + `stat` per file) | 0.361 s | 0.344 s |
| diff (`synccli.changed_files`) | — | 0.003 s |
| copy / materialize | 15.437 s (441 µs/file) | 7.058 s (201.7 µs/file, clones) |
| write the manifest | 0.072 s | 0.075 s |
| fsync files + dirs | 1.845 s | — |
| publish (`rename`) | 0.110 ms | 0.199 ms |
| **total** | **17.716 s** | **7.496 s** |

### 11.4 The budget for the first full backup

**Model** (constants from §11.2):

```
T_full(F, B) ≈ 0.027 s + 8.3 µs·F            # scan (synccli.file_state per file)
             + F · 185 µs                    # copy (incl. the utime that preserves mtime)
             + B / D_write                   # writing the bytes
             + F · 30 µs                     # fsync per file
             + F · 2 µs                      # manifest write
             + 0.2 ms                        # publish (rename)
```

For the reference case (**F ≈ 35,000 files, B ≈ 1 GiB**):

| `D_write` | `T_full` |
|---|---|
| 1.15 GB/s (this volume, `O_DIRECT`) | 0.36 + 6.48 + 0.93 + 1.05 + 0.07 ≈ **8.9 s** |
| 500 MB/s (typical external SSD) | 0.36 + 6.48 + 2.15 + 1.05 + 0.07 ≈ **10.1 s** |
| 200 MB/s (conservative) | 0.36 + 6.48 + 5.37 + 1.05 + 0.07 ≈ **13.3 s** |
| 100 MB/s (network/spinning) | 0.36 + 6.48 + 10.74 + 1.05 + 0.07 ≈ **18.7 s** |

The model under-predicts the measured end-to-end: for the measured case
(F = 35,000, B = 1.85 GiB) it predicts ≈ **9.7 s** at 1.15 GB/s, while the
run took **17.7 s** — a factor of 1.83. The reason is that the measured run
wrote 1.85 GiB of *new* data while the page cache was already saturated with
the source tree (effective write rate ≈ 122 MiB/s, against the 1.15 GB/s
`dd` measured on an idle volume). The budget therefore carries a **1.7×
safety factor** over the model:

> **Budget: the first full backup of a ~1 GiB tree with tens of thousands of
> files must finish in ≤ 30 s**, on a volume sustaining ≥ 200 MB/s, on the
> reference class of hardware.
>
> Measured on the reference machine: **17.7 s for a 1.85 GiB / 35,000-file
> tree** — i.e. the budget has ~1.7× headroom over a tree 1.85× larger than
> the budgeted one. The dominant term is *per file*, not per byte: each
> additional 1,000 files costs ≈ **+0.23 s** (185 µs copy + 30 µs fsync +
> 8.3 µs scan + 2 µs manifest), each additional gigabyte costs
> ≈ **+5.4 s** at 200 MB/s and **+0.9 s** at 1.15 GB/s.

The budget is stated as a *ceiling with a formula*, so it can be re-derived
for a different tree without re-measuring: substitute `F` and `B` and the
`D_write` of the deployment volume into the model, then apply the 1.7×
safety factor that the measurement showed is needed.

### 11.5 The incremental run

For a source with `F` files and `C` changed files:

```
T_incremental(F, C) ≈ 16 ms + 8.3 µs·F       # read the base manifest + scan + diff
                    + F · 200 µs             # materialize unchanged files (clones)
                    + C · 185 µs             # copy changed files
                    + F · 2 µs               # write the new manifest
```

For F = 35,000, C = 0 → ≈ **7.5 s** (measured 7.496 s). For C = 25 → +4.6 ms.

Note the shape of this number: the scan is *cheap* (0.34 s) and the
**materialization of unchanged files dominates** (7.06 s). That is the price
of D1 (each snapshot is a complete tree). It buys: a restore is a plain
recursive copy of one directory, with no chain to resolve; and it buys the
space property measured in §11.2 — unchanged content is stored once
(0 MiB per 8 clones) instead of once per snapshot.

---

## 12. Scaling: three directories today, a few dozen later

Let `N` = number of sources, `F` = total files, `F_max` = files in the
largest source, `B` = total bytes, `Δ` = bytes changed per run, `K` =
retained snapshots.

### 12.1 What grows, and by how much

| Quantity | Bound | Grows with |
|---|---|---|
| Per-run wall time | `N·(0.027 s + 8.3 µs·F_i) + F·(185–200 µs) + C·185 µs + Δ/D_write` | linearly in `N` and in `F`; **not** in `B` (only the changed bytes `Δ` are copied) |
| Per-run bytes written | `Δ + F·7.9 B` (manifest) + metadata | linearly in the *changed* bytes and in `F` |
| Peak memory | `472 B × 2·F_i` ≈ **944 B × F_max** (the new state map + the base manifest) | with `F_max` only — sources are processed **one at a time**, so it does **not** grow with `N` |
| Disk, data | `B + (K−1)·Δ` unique bytes (CoW sharing); worst case `K·B` if everything changes every run | with `K` and `Δ` |
| Disk, manifests | `K × F × 7.9 B` gzipped (or `K × F × 84 B` if exported as `synccli`-schema JSON) | linearly in `K` and `F` |
| Number of directories in the root | `K` published + `≤1` staging + `≤K` tombstoned | with `K` |
| `snaputil.list_snapshots` cost | 0.00009 s for 12 snapshots → `O(K)`, ~7.5 µs per snapshot | with `K` |

### 12.2 What stays flat

* **Memory does not grow with `N`.** Sources are processed sequentially and
  each source's manifests are released before the next one starts. The peak
  is set by the largest single source: for `F_max` = 35,000 → ≈ **33 MB**
  (2 × 16.5 MB), plus ~20 MB of interpreter overhead. At `N = 50` it is the
  same 33 MB.
* **The per-run cost does not grow with the total byte volume `B`** — only
  with the number of files and the number of *changed* bytes. A 10 GiB tree
  that changes by 1 MiB per run costs the same per-run time as a 1 GiB tree
  that changes by 1 MiB, plus the 1 MiB copy.
* **The snapshot count in the root does not grow without bound**: `K`
  published snapshots + tombstones awaiting reclaim; the tombstone area is
  bounded by `reclaim_after_hours` × the run rate.

### 12.3 Worked numbers

`N = 30` sources × 35,000 files each = 1.05 M files, 30 GiB.

| | Value |
|---|---|
| scan per run | `30 × (0.027 + 8.3 µs × 35,000)` = **9.5 s** |
| materialize (clones) per run | 1.05 M × 200 µs = **210 s** |
| manifest write per run | 1.05 M × 7.9 B = **8.3 MB** (gzip) / 88 MB (as `synccli`-schema JSON) |
| peak memory | **33 MB** (unchanged from `N = 3`) |
| data on disk with K = 7 | `30 GiB + 6 × Δ` (≈ 30 GiB if `Δ` is small) |
| manifests on disk with K = 7 | `7 × 8.3 MB` = **58 MB** gzipped, or 616 MB as plain JSON |
| full backup time (once) | ≈ 30 GiB / 1.15 GB/s + 1.05 M × 185 µs ≈ **220 s** |

The conclusion the brief asks for: **per-run work grows linearly with `N`
and with `F`; memory grows with `F_max` only; disk grows with `B + (K−1)·Δ`
for data and `K·F·7.9 B` for manifests.** Nothing grows with `B` per run, and
nothing grows with `N` except time and disk.

---

## 13. Interfaces

### 13.1 Configuration (`backupctl.json`, or `--config PATH`)

```json
{
  "backup_root": "/Users/…/backups/evals",
  "sources": [
    {"id": "evals", "path": "/Users/…/repo/evals"},
    {"id": "evals-archive", "path": "/Users/…/repo/evals-archive"}
  ],
  "retention": {"keep": 7, "min_keep": 2, "expire_after_days": 30,
                "reclaim_after_hours": 24},
  "materialize": "auto",
  "lock_wait_seconds": 300,
  "stale_staging_hours": 6,
  "fsync_files": true
}
```

`materialize`: `auto` (clone → link → copy, per file, first that works) |
`clone` (fail if unsupported) | `link` | `copy`.

### 13.2 Commands

```
backupctl run                       # create a snapshot of all sources
backupctl list [--json]             # list snapshots (uses snaputil.list_snapshots)
backupctl prune                     # apply the retention policy (two-phase)
backupctl gc                        # reclaim tombstones + abandoned staging dirs
backupctl verify <snapshot>         # index vs. tree, both directions
backupctl recover <snapshot>        # rebuild a damaged manifest from the tree
backupctl hold <snapshot>            # take a reader lease; the snapshot is not pruned
backupctl export-manifest <snapshot> <source_id>   # write .sync_manifest.json (synccli schema)
backupctl status                    # last report, disk usage, lock state
```

Common flags: `--config`, `--root` (overrides the config's root),
`--dry-run` (report what would be copied, change nothing), `--json`
(machine-readable output).

### 13.3 Report

`.reports/<snapshot_id>.json` and a human summary on stdout:

```
snapshot snap-20261112-120000-000001  (2026-11-12T12:00:00Z)
  evals        35000 files  1.00 GiB   copied 120  cloned 34880  missing 1
  scanned 0.36 s, copied 0.02 s, materialized 7.06 s, total 7.50 s
  1 file missing (source path listed in index.json)
  retention: kept 7, tombstoned 0, reclaimed 0
```

---

## 14. Verification and test plan

`backupctl.py` ships with `test_backupctl.py`, written in the style of the
existing `test_synccli.py` (stdlib `unittest`, `python3 -m unittest`). The
existing suite must keep passing untouched (**6 tests, OK** — verified).

| Test | What it pins down |
|---|---|
| `test_scan_includes_dot_directories` | the override of `synccli.py:14` — `.hidden_dir/data.bin` is backed up |
| `test_publish_is_atomic` | a killed run leaves nothing named `snap-*`; after the rename the snapshot is complete |
| `test_reader_never_sees_partial_snapshot` | while a run is in its copy phase, `snaputil.list_snapshots` shows no new snapshot; during it, the old snapshot is fully readable |
| `test_concurrent_runs` | two `backupctl run` processes at once → one wins the lock, the other exits 75; both snapshots (if both proceed) are valid |
| `test_restore_during_prune` | a reader holding an open file in a snapshot being pruned keeps reading it; the pruned snapshot is never emptied in place |
| `test_missing_source_file` | a file deleted between scan and copy → omitted, reported, exit 3, and retried by the next run |
| `test_unreadable_source_file` | `chmod 000` → omitted, reported as unreadable, exit 3 |
| `test_unchanged_files_are_not_copied` | the second run copies 0 bytes and materializes by clone/link; the source tree's bytes are not re-read |
| `test_changed_file_is_detected` | touch/modify → the file is re-copied; the snapshot's bytes are the new ones |
| `test_mtime_preserved` | the stored file's `mtime_ns` equals the source's |
| `test_manifest_recovery_from_tree` | corrupt the manifest → `recover` rebuilds it and `verify` passes |
| `test_corrupt_previous_manifest_forces_rebuild` | the base is re-derived from the previous snapshot's tree |
| `test_damaged_previous_snapshot_forces_full_recopy` | tree + manifest damaged → the source is re-copied in full and reported |
| `test_index_digest_detects_tampering` | a modified file in a snapshot is reported by `verify` |
| `test_retention_keeps_min_keep` | never fewer than `min_keep` published snapshots |
| `test_retention_never_deletes_newest` | the newest snapshot survives |
| `test_resolve_in_snapshot_rejects_escape` | the override of `snaputil.py:54-63`: `../../etc/passwd` is rejected |
| `test_report_identical_for_both_triggers` | scheduler and human runs produce byte-identical report structure and the same exit codes |

---

## 15. Risks and open questions

1. **The `(size, mtime)` key can miss content edits** (§9.2). Mitigation
   offered: `backupctl verify --deep` can re-hash a tree on demand; it is
   deliberately *not* part of the per-run path because it would read every
   byte on every run.
2. **A restore that outlasts `reclaim_after_hours` and takes no lease** can
   hit `ENOENT` on one file (§10.3). The lease (`backupctl hold`) closes it
   for cooperating readers.
3. **The link fallback shares inodes between snapshots.** The clone path
   (default on APFS) does not. If a deployment forces `materialize=link`,
   the in-place-edit hazard returns, and `verify` is the detector.
4. **`snaputil.safe_snapshot_path` is still path-escape-prone**
   (§2.2 #6). The restore tooling that calls it directly remains exposed; a
   one-line patch to `snaputil.py` is recommended.
5. **Clock changes.** Snapshot ordering uses `created_utc`, and the
   6-digit sequence counter is monotone per root, so a backwards clock
   cannot make a newer snapshot look older than an older one. A snapshot
   whose name and `created_utc` disagree is reported by `verify`.
6. **Not measured on the deployment host.** All numbers come from the
   reference machine; the budget is expressed as a formula with named
   constants so it can be re-derived, and `dd` on the backup volume gives the
   `D_write` to plug in.

---

## Appendix A — measurement harnesses

All harnesses ran against this repo copy (they import `synccli` and
`snaputil` from it) and were executed in a scratch directory
(`/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/opencode/`),
never writing into the repo. Each script is standalone
(`python3 benchN.py`); the paths are listed so any number in this document
can be re-derived.

| Tag | Script | What it measures |
|---|---|---|
| B2 | `bench2.py` | 0.88 GiB / 35k tree: `build_manifest` scaling fit (F = 7k…35k), per-size-class copy throughput, `synccli.sync` full vs incremental, manifest read, `fsync`, `list_snapshots`, `prune_snapshots`, `snapshot_disk_usage`, mtime granularity |
| B3 | `bench3.py` | `os.replace`, hard-link materialization (35k files), `rmtree` of a 35k snapshot, `is_stale` docstring contradiction, `prune_snapshots` behaviour, `flock` `LOCK_NB` |
| B6 | `bench6.py` | the four behavioural defects of §2.2 (verified), index sizes (JSON/JSONL/gzip), in-memory manifest cost, `dd` throughput |
| B7 | `bench7.py` | end-to-end pipeline shape (scan/index/diff/copy/publish/prune) |
| B10 | `bench10.py` | per-syscall floor: create 73.3 µs, stat 2.1 µs, open+read+close 32.6 µs, `os.walk` 0.50 µs/entry |
| B11 | `bench11.py` | copy-path variants: `synccli.copy_file` 159.8, tuned 155.7, `.part`+rename 251.2, clonefile, link |
| B12 | `bench12.py` | the clonefile discrepancy: order/warm-up/repeat; showed the 5-argument `ctypes` call fails with `ENOENT` (wrong prototype) |
| B13 | `bench13.py` | `clonefile` with the correct 3-argument signature (`sys/clonefile.h`), independent-inode check |
| B14 | `bench14.py` | corrected clone vs copy vs link per size class; fsync per file/dir; publish rename; prune (`chmod -R` + `rmtree`); `snapshot_disk_usage` |
| B15 | `bench15.py` | end-to-end simulation: full run and incremental run over a 1.85 GiB / 35k tree |
| B16 | `bench16.py` | the cost of the per-file metadata ops the design needs: copy 156.7 vs copy+`stat`+`utime` 185.1 µs/file; `utime` 29.2 µs; `chmod` 31.0 µs; `stat` 1.2 µs |
| B17 | `cowtest` | disk consumption of 8 CoW clones vs 8 hard links vs 4 real copies of a 512 MiB file |

## Appendix B — raw results

```
B2  build_manifest: F=7000 0.079 s | 14000 0.132 | 21000 0.229 | 28000 0.266 | 35000 0.303
    fit t_scan = 0.026854 s + 8.331 us/file
    copy 4096 B x200 0.031 s (24.9 MiB/s) | 65536 x100 0.017 s | 1048576 x20 0.006 s | 67108864 x2 0.072 s
    synccli.sync full 12.075 s | incremental 0.402 s (copied=0)
    json.load prev index 0.013 s | changed_files 0.002 s | manifest 89.9 B/file
    fsync(4KiB) median 0.030 ms p95 0.037 ms
B3  os.replace 0.0747 ms | hard-link 35000 files 11.415 s (326 us/file) | shared inode True
    rmtree 35000-file snapshot 3.399 s | is_stale(dir, dir_mtime) = True
    prune_snapshots(keep=3) deleted 5, kept the newest 3
    flock LOCK_NB on a second handle -> BlockingIOError
B6  safe_snapshot_path(root,'snap-1','../../etc/passwd') -> /tmp/backuproot/snap-1/../../etc/passwd
    normpath('../../etc/passwd') = ../../etc/passwd   -> resolves to /tmp/etc/passwd  (ESCAPE)
    copy_file(<missing src>) -> no error, no file      (ENOENT swallowed)
    next run's json.load of a truncated manifest -> JSONDecodeError
    scan_files of a tree with .hidden_dir/data.bin -> ['.dotfile']   (dot DIR dropped)
    index sizes: indent=2 109.0 B/file | compact 84.0 | jsonl 62.0 | jsonl+gzip 7.9
    build_manifest RSS delta 16.5 MiB for 35000 entries = 472 B/entry
    dd 512 MiB: 3.15 GB/s buffered, 11.5 GB/s O_DIRECT
B7  run1: scan 0.323 | index 0.117 | copy 35000 files 11.857 s (338.8 us/file) | TOTAL 12.297 s
    run2: read 0.054 | scan 0.335 | diff 0.003 | index 0.116 | TOTAL 0.508 s
    publish rename 0.108 ms | rmtree 35000-file snapshot 2.986 s
B10 create 73.3 us | stat 2.1 us | open+read+close 32.6 us | listdir 0.4 us | walk 0.50 us/entry
B11 copy 4096B: synccli.copy_file 159.8 | cached dirs 155.7 | .part+rename 251.2 | clonefile 3.9 (FAILED: wrong signature)
    link 303.5
B13 clonefile (3-arg signature) works: distinct inode, same size, 8 blocks each
    clonefile x5000 4KiB: 3.15 us/file (FAILED: parent dirs missing -> ENOENT)
    hardlink x5000: 281.89 us/file | copy x5000: 172.01 us/file
B14 (parent dirs created)
    4096 B: clone 188.8 (0 fail) | copy 247.3 | link 337.3
    65536 B: clone 186.3 | copy 191.4 | link 318.4
    1048576 B: clone 128.7 | copy 387.2 | link 318.8
    fsync every file (5000) 0.017 s (3.4 us/file) | fsync every dir 0.002 s | publish rename 0.112 ms
    chmod -R u+w 0.014 s | rmtree 0.044 s | snapshot_disk_usage 0.0027 s
B15 tree 35000 files / 1.85 GiB
    RUN1: scan 0.361 | copy 15.437 (441.1 us/file) | manifest 0.072 | fsync 1.845 | publish 0.110 ms | TOTAL 17.716 s
    RUN2: read 0.016 | scan 0.344 | diff 0.003 | materialize 35000 7.058 (201.7 us/file) | manifest 0.075 | publish 0.199 ms | TOTAL 7.496 s
B16 copy only 156.7 us/file | copy + stat + utime(ns) 185.1 us/file
    os.utime 29.2 us | os.chmod 31.0 us | os.stat 1.2 us
B17 free before clones 282637.9 MiB -> after 8x512MiB clones 282637.8 MiB (consumed 0.0 MiB)
    8 hard links consumed 0.031 MiB | 4 real copies consumed 2068.3 MiB
```

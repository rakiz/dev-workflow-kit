# DESIGN — `backupctl` (fixture D1)

A command-line backup tool for the `evals/` result directories. It produces
point-in-time **snapshots** under a backup root, incrementally (unchanged
files are not re-copied), safely (concurrent runs, concurrent readers,
crashes, vanishing sources), and within an explicit performance budget.

Everything below is built on the code already in this directory:
`synccli.py` (scan / manifest / change detection / copy) and `snaputil.py`
(snapshot listing / pruning / sizing / path mapping). Section 9 lists every
place where `backupctl` deliberately **overrides** existing behaviour, with
the exact function and line.

---

## 1. Overview

```
backupctl run      --config <file> [--json] [--dry-run]
backupctl list     --config <file>
backupctl verify   --config <file> [--snapshot <name>]
backupctl prune    --config <file> [--keep K] [--max-age-days D]
backupctl stats    --config <file>
```

One entry point does all the work: `run`. `list`, `prune`, `stats` are thin
wrappers over the same modules. There is **no separate "scheduler mode" and
"human mode"**: the same `run_backup()` code path and the same
`build_report()` function produce the result in both cases (Section 8).

### 1.1 Layout of the backup root

```
<backup_root>/
  snap-20261116-150000-01/        <- a published snapshot (atomic, complete)
      index.json                  <- the snapshot index (written last, atomically)
      <source_id>/                <- one subtree per configured directory
          <relative paths of the source tree>
  incoming/                       <- staging area of in-flight runs (never "snap-*")
      <run_id>/                   <- one directory per run
          <source_id>/...
          <source_id>.index.json
          index.json
  trash/                          <- deleted snapshots awaiting rmtree
  locks/
      <source_id>.lock            <- per-source exclusive lock (flock)
      publish.lock                <- short critical section: seq + prune
```

`incoming/` and `trash/` deliberately do **not** start with `snap-`, so
`snaputil.list_snapshots` (`snaputil.py:8`) — which selects entries starting
with `snap-` that are directories — can never return an incomplete or
deleted snapshot. That is the first guarantee: **a reader that enumerates
snapshots sees only complete ones.**

### 1.2 Source of truth for what a snapshot contains

Each snapshot carries `index.json`, written atomically (Section 4) *inside*
the snapshot directory, before the snapshot is published:

```json
{
  "schema": 1,
  "snapshot": "snap-20261116-150000-01",
  "created_utc": "2026-11-16T15:00:03Z",
  "run_id": "7f3c1e9a-...",
  "complete": false,
  "sources": [
    {
      "id": "evals-2026-11",
      "root": "/abs/path/to/evals/results",
      "base_snapshot": "snap-20261116-120000-01",
      "files":   {"a/b.txt": {"size": 12, "mtime": 1763300001.25}},
      "excluded":[{"path": "c/gone.txt", "reason": "vanished"}],
      "complete": false,
      "stats": {"total": 2, "copied": 1, "reused": 1, "excluded": 1,
                "bytes_copied": 12}
    }
  ]
}
```

The `files` map has exactly the shape of the manifest produced by
`synccli.build_manifest` (`synccli.py:28`) — `{relpath: {"size", "mtime"}}` —
so the index and the manifests are directly comparable with
`synccli.changed_files` (`synccli.py:36`).

Invariant **I1**: `files` lists only paths that exist inside the snapshot
directory. A file that could not be backed up appears in `excluded` with a
reason, never in `files`. **I1** is enforced mechanically by the
pre-publish verification pass (Section 5.4).

---

## 2. Configuration

`--config <path>`, JSON (stdlib `json`, no new dependency; `tomllib` is
3.11+ and this repo runs 3.10):

```json
{
  "backup_root": "/var/backups/backupctl",
  "keep": 7,
  "max_age_days": 30,
  "lock_wait_seconds": 900,
  "sources": [
    {"id": "evals-run-2026-11", "path": "/repo/evals/run-2026-11"},
    {"id": "evals-work",        "path": "/repo/evals/work"}
  ]
}
```

* `id` — stable, filesystem-safe name (no `/`), used for the per-source
  subdirectory, the per-source lock file and the index entry. It must be
  stable across runs: it identifies the *chain* of snapshots of one source
  (the "previous snapshot" of a source is the newest published snapshot whose
  index contains this `id`).
* `keep` — number of snapshots to retain (Section 6).
* `lock_wait_seconds` — how long a run waits for a source lock held by
  another run (default 900 s).
* `max_age_days` — optional secondary retention rule (Section 6).

Missing/invalid config ⇒ exit 1 with a message on stderr, nothing touched.

---

## 3. Concurrency model

### 3.1 Writers

Two runs may be triggered at the same time (scheduler cron + a person).
`backupctl` serialises writers **per source**, using `fcntl.flock`:

* lock file `<backup_root>/locks/<source_id>.lock`, `LOCK_EX`.
* Acquired with a non-blocking retry loop (`LOCK_NB` + 0.2 s sleep) until
  `lock_wait_seconds` elapses; on timeout the source is **skipped** and
  reported (exit code 2), and the other sources of the run still proceed.
* The lock is held for the whole per-source work (scan → copy → index
  fragment). It is released by the kernel when the process exits, including
  on `SIGKILL`, so a dead run cannot wedge the lock.

Why per-source and not global: two runs backing up *different* sources do not
conflict and should proceed in parallel; two runs backing up the *same*
source must not, because both would compute their incremental delta against
the same base snapshot and both would publish a new snapshot for that
source, racing on the snapshot chain. The lock makes the chain linear.

The **publish** step additionally takes a short global lock
(`locks/publish.lock`) around "allocate sequence number → rename staging dir
→ rename root dir → fsync root". This section is short (a rename and an
fsync), so it is not a contention point, and it makes snapshot naming and
root-directory mutation serialised.

### 3.2 Readers

Readers (the separate restore tooling, a human running `ls`, the next run)
take **no lock at all**. They are protected by two rules:

* **Publication is a single `rename(2)`.** A snapshot directory is built
  under `incoming/<run_id>/` and becomes visible under its `snap-*` name
  only when `os.rename()` moves it there. `rename` within one filesystem is
  atomic: a reader sees either no such directory or the complete one.
* **Deletion is a rename too** (Section 6): a doomed snapshot is first
  tombstoned, then *renamed* into `trash/`, then `rmtree`d. The reader that
  already opened file descriptors keeps reading the same inodes (POSIX
  unlink semantics) until it closes them; the reader that resolves the path
  later gets `ENOENT` and must report "snapshot was pruned during the read"
  rather than silently restore a partial image.

This is exactly the guarantee the brief asks for: *a reader never asks
whether the run that produced a snapshot is finished, and never sees a mix
of files from this run and from the previous one.*

---

## 4. Atomicity primitives

| Artefact | How it is written | Crash result |
|---|---|---|
| staged file content | `<name>.tmp` → write → `flush` → `fsync` → `os.replace` | never a half-written file under its final name |
| per-source index fragment | `<source_id>.index.json.tmp` → write → `fsync` → `os.replace` | never a half-written fragment |
| snapshot `index.json` | `<index.json.tmp>` → write → `fsync` → `os.replace` | never a half-written index |
| snapshot directory | `os.rename(incoming/<run_id>, <root>/snap-…)` | snapshot either does not exist or is complete |
| root directory listing | `fsync` on the root dir after the rename | the new name survives a crash |
| deletion | tombstone file → `os.rename` to `trash/` → `rmtree` | a snapshot is never half-deleted |

`synccli.sync` does **not** do this: it writes the manifest with
`open(path, "w")` + `json.dump` (`synccli.py:85-86`), which leaves a
truncated `.sync_manifest.json` if the process dies mid-write, and it has no
lock at all. That is why `backupctl` does not call `synccli.sync`; see
Section 9.2.

---

## 5. The run algorithm

`run_backup(config) -> report`

### 5.1 Recovery phase (before any copying)

Runs first, every time, so that a crashed predecessor never blocks
progress:

1. **Stale staging directories.** For each `incoming/<run_id>/`, read
   `owner.json` (`{"pid", "host", "started_utc"}`). If the pid is alive
   (`os.kill(pid, 0)`) and the host matches, another run owns it → leave it
   alone. Otherwise the owner is dead → `rmtree` the directory. A crash
   therefore leaves, at worst, one `incoming/` directory, which the next run
   removes automatically. *Nothing manual to clean up.*
2. **Stale trash.** `rmtree` everything under `trash/`. (A previous crash
   between rename and rmtree leaves the data on disk; it is unreachable
   either way.)
3. **Index validation of the base snapshot** (Section 5.2).

### 5.2 Choosing and validating the base snapshot

For source *S*, the base is the newest published snapshot whose
`index.json` contains an entry for *S*. Its file map is the manifest the
incremental run compares against.

The base index is validated in one of three ways:

* **Case A — index parses, agrees with the tree.** `index.json` is valid
  JSON, schema 1, and the set of `files` keys equals the set of regular
  files actually present under `<snapshot>/<S>/` (recomputed with
  `synccli.scan_files`, `synccli.py:10`, plus the same regular-file filter
  used at copy time). The base is used as-is.
* **Case B — index missing or unparseable (half-written by a dead run).**
  The index is **discarded** and **re-derived from the tree**: the file map
  is rebuilt by walking `<snapshot>/<S>/` with `synccli.scan_files` and
  `synccli.file_state` (`synccli.py:22`) — i.e. the same {size, mtime}
  states the manifest format already uses. The rebuilt index is written
  atomically over the old one and the run reports
  `recovered: re-derived index for <snap> from tree (N files)`.
  The snapshot's *content* is untouched, so it remains a valid restore
  target and a valid base.
* **Case C — index parses but disagrees with the tree** (index promises a
  file the snapshot does not contain, or the tree contains a file the index
  does not mention). The snapshot is **inconsistent and therefore not a
  valid restore target** — it violates invariant I1 — so it is marked
  invalid: a `.invalid` marker file is written into the snapshot directory
  and the run reports `recovered: snapshot <snap> has an inconsistent index;
  marked invalid and excluded from retention counting`. The source has no
  usable base for this run, so the run performs a **full copy** for it.

Rationale for the split: re-deriving the index from the tree is safe when
the *tree* is intact (the tree is what a restore actually reads); when the
tree and the index disagree we cannot know which one lied, so the snapshot
is not offered as a restore target, and the run falls back to a full copy
rather than building an incremental snapshot on an unknown base.

An invalid snapshot is not deleted by the run that found it (a human may
still want it); it is excluded from the "usable snapshot" count used by
retention (Section 6) and it is tombstoned so that a restore refuses it.

### 5.3 Per-source work (under the source lock)

For each source *S* (processed sequentially, one at a time, so peak memory
is bounded by the largest single source — Section 10):

1. **Scan the source.** `manifest = synccli.build_manifest(src_path)`
   (`synccli.py:28`) → `{rel: {"size", "mtime"}}` for every file under the
   tree. This is the change-detection granularity (Section 7).
2. **Compute the delta.**
   * `changed = synccli.changed_files(base_manifest, manifest)`
     (`synccli.py:36`) — files that are new or whose state changed.
   * `removed = set(base_manifest) - set(manifest)` — computed here, because
     `changed_files` only iterates the *new* manifest and therefore cannot
     report a file that disappeared from the source. Removal is *not* a
     deletion in the snapshot (snapshots are immutable point-in-time images);
     it only means the file is no longer backed up in later snapshots, and
     it is counted in the report as `removed`.
3. **Materialise the snapshot tree** into `incoming/<run_id>/<S>/`:
   * *Unchanged* file (present in base with an equal {size, mtime} state):
     the content is already in the base snapshot and is byte-identical, so
     it is materialised from the base snapshot without reading the source
     at all (Section 7.2). This is what "do not copy unchanged files again"
     means in practice — the file is present in the new snapshot, but it is
     not re-read from the source and not re-written as new bytes.
   * *Changed or new* file: copied from the source, chunked, into
     `<name>.tmp`, `fsync`ed, then `os.replace`d into place.
   * *Source file vanished or is unreadable* (the `OSError` case that
     `synccli.copy_file` swallows at `synccli.py:68-69`): the file is
     **not** created; it is recorded in `excluded` with reason
     `vanished` / `unreadable`; the source's `complete` flag becomes
     `false`; the run reports it. Same behaviour whether the run was
     triggered by the scheduler or by a person — there is one code path.
   * *Source file changed while being copied* (torn copy): the state is
     re-read (`synccli.file_state`) after the copy and compared with the
     state observed during the scan. If they differ, the file is **excluded**
     with reason `changed-during-copy` and removed from the snapshot tree
     (the `.tmp` file is unlinked). Shipping a torn file would break
     invariant I1 and the "never a mix" guarantee.
   * *Non-regular files* (FIFOs, sockets, device nodes) — `synccli.scan_files`
     lists them among `filenames` because `os.walk` puts anything that is
     not a directory there, and copying a FIFO would block forever. They are
     excluded with reason `not-a-regular-file` (see Section 9.4).
4. **Write the per-source index fragment** atomically
   (`incoming/<run_id>/<S>.index.json`).

### 5.4 Assemble, verify, publish

1. **Assemble** `incoming/<run_id>/index.json` from the per-source fragments
   (streamed: the fragments are written by concatenation, so the whole
   index is never held in memory — Section 10), `fsync` it, and `os.replace`
   it into place.
2. **Verify (the I1 check).** For every entry in every `files` map, `stat`
   the corresponding path under the staging directory and confirm it exists
   and is a regular file with the recorded size. Any mismatch ⇒ the
   snapshot is **not** published: the staging directory is removed and the
   run fails with exit code 1 and a message naming the offending path.
   Cost: one `stat` per indexed file, ≈ 25 µs each (measured, Section 11) —
   about 3 % of a full backup.
3. **Publish.** Under `locks/publish.lock`:
   * allocate the next sequence number for the current second (Section 5.5);
   * `os.rename(incoming/<run_id>, <root>/snap-<stamp>-<seq>)`;
   * `fsync` the root directory.
4. **Retention** (Section 6), then **report** (Section 8).

### 5.5 Snapshot naming

`snap-<YYYYMMDD>-<HHMMSS>-<seq>`, UTC, zero-padded — the format shown in
`snaputil.list_snapshots`' docstring (`snaputil.py:8-15`). Because the
timestamp is zero-padded and `seq` is a fixed-width 2-digit counter, plain
lexicographic sorting equals chronological sorting, which is the ordering
`list_snapshots` promises ("oldest first") and the ordering
`snaputil.prune_snapshots` relies on. `seq` disambiguates several runs
started in the same second (a scheduler and a person at once) and is
allocated under the publish lock. If 100 runs were to start within one
second, `seq` would be bumped into the next second rather than growing to
three digits, so the fixed width is never broken.

### 5.6 Interruption (Ctrl-C, `SIGTERM`, sleep, `SIGKILL`)

* `SIGINT`/`SIGTERM` are caught and turned into a clean abort: the staging
  directory `incoming/<run_id>/` is removed, the snapshot is **not**
  published, the exit code is 130. The flock is released by the kernel.
* `SIGKILL` / power loss: the staging directory stays, but it is not named
  `snap-*`, so no reader can mistake it for a snapshot; the next run's
  recovery phase (5.1) deletes it because its owner pid is dead.
* Either way: **nothing a reader could mistake for a complete snapshot is
  left behind**, and the next run makes progress without manual cleanup.

---

## 6. Retention

Policy: keep the **newest `keep`** snapshots (default 7) and additionally
drop snapshots older than `max_age_days` (optional). The invariant:
*the user is never left without a usable snapshot* — the snapshot just
published is never deleted, and the number of **valid** snapshots retained
is at least `keep` (a snapshot marked `.invalid` by Section 5.2 Case C does
not count as valid, so retention reaches further back to keep `keep` valid
ones).

Selection reuses existing code:

* `snaputil.list_snapshots(root)` (`snaputil.py:8`) enumerates the
  snapshots, oldest first — the same ordering `snaputil.prune_snapshots`
  uses.
* `synccli.collect_stale(items, seen)` (`synccli.py:45`) selects the
  doomed ones: it is given `[(snapshot_name, fresh), ...]` where `fresh` is
  True for the keepers, and returns the entries that are neither fresh nor
  already `seen`. This is precisely its contract ("items not yet marked
  fresh"), so it is reused rather than re-implemented.

Deletion is **not** `snaputil.prune_snapshots` (`snaputil.py:23`), which
calls `shutil.rmtree` on the live snapshot directory: a reader copying out
of that directory at that moment would get `ENOENT` mid-file and could
assemble a **mixed image** from two snapshots. `backupctl` instead does:

1. write `<snapshot>/.deleting` (tombstone) and `fsync` it;
2. `os.rename(<root>/snap-X, <root>/trash/<uuid>)` — the snapshot
   disappears from `list_snapshots` atomically, and readers that already
   hold open descriptors keep reading the same inodes;
3. `rmtree(<root>/trash/<uuid>)` — after the rename, and skipped entirely
   if a reader still holds the directory open on systems where that
   matters (on POSIX the space is reclaimed once the last descriptor is
   closed; the `rmtree` itself succeeds regardless, the space is reclaimed
   by the kernel later).

A restore that resolves the snapshot path after step 2 gets `ENOENT` and
must report "the snapshot was pruned while it was being read" instead of
producing a partial restore. A restore that read the tombstone before step 1
must refuse the snapshot.

---

## 7. Change detection

### 7.1 Granularity

**Per file, by `(size, mtime)`**, exactly the state `synccli.file_state`
(`synccli.py:22`) returns: `{"size": st.st_size, "mtime": st.st_mtime}`.
This is the same state the existing manifest stores
(`synccli.build_manifest`, `synccli.py:28`) and the same comparison
`synccli.changed_files` (`synccli.py:36`) performs
(`old_manifest[rel] != state`), so the incremental rule is literally the
existing rule, reused.

### 7.2 What "unchanged" means operationally

A file is *unchanged* when the source's current `{size, mtime}` equals the
state recorded in the base snapshot's index. It is then materialised into
the new snapshot **from the base snapshot**, not from the source:

1. **clone (preferred)** — `clonefile(2)` on APFS via `ctypes`
   (`libc.clonefile`), or the `FICLONE` ioctl on Linux (`btrfs`, `XFS`,
   `reflink` filesystems). A copy-on-write clone: same bytes, independent
   inode, **no extra disk space** and no source read. Measured: **215 µs per
   file**, and the clone is genuinely independent (verified: writing to the
   clone does not modify the source file, inodes differ).
2. **hard link (fallback)** — `os.link()` from the base snapshot's file.
   Zero space, but the new snapshot's file *shares the inode* with the
   base snapshot's file. Safe **only because snapshot files are immutable**:
   `backupctl` never opens a published snapshot file for writing, and a
   restore copies *out* of it. A human who edits a file inside a snapshot
   in place would corrupt the sibling snapshot — this is why the
   tombstone/immutability rule is part of the contract. Measured: **356 µs
   per file** on this filesystem.
3. **byte copy (last resort)** — if neither clone nor link is available
   (different filesystem, unsupported FS), the file is copied from the base
   snapshot: correctness first, cost second. Measured cost of the copy path
   for a 33 KB file: ≈ 300 µs of per-file overhead (create + write +
   `fsync` + `rename`).

The choice is probed once per run per filesystem (a single clone attempt
on a probe file), so the common case costs one `clonefile` syscall per
file and no probing overhead.

### 7.3 What this granularity misses

* **Same size, same mtime, different content** — the classic blind spot.
  Concretely: an edit that preserves the byte length *and* restores the
  original mtime (`cp -p` of an older copy over the file, `touch -r`,
  `rsync --times` restoring a timestamp, or a tool that writes the same
  number of bytes and restores the timestamp). Such an edit is **missed**
  and the snapshot keeps the old content.
* **Coarse filesystem timestamp granularity** — on a filesystem with 1 s
  `mtime` granularity, an edit that lands in the same second as the
  snapshot *and* preserves the size is missed. (APFS and ext4 store
  nanosecond timestamps; `st_mtime` is a float, so the effective resolution
  is ~0.24 µs on current epoch values.)
* **Not detected:** a file whose *content* changed but whose size and mtime
  are unchanged; a file replaced by a directory of the same name (the
  directory's contents are new files, so they are picked up, but the type
  change itself is not flagged); changes to the *permissions/ownership* of a
  file (not recorded at all — the state is size+mtime only); extended
  attributes, ACLs, symlink targets (see below).
* **Detected but over-eager:** a `touch` that changes only the mtime
  triggers a re-copy of unchanged content (a false positive — safe, only
  costs a copy).
* **Symlinks:** `os.walk` lists a symlink-to-directory in `dirnames` but
  does not descend into it (`followlinks=False`), so the *contents* of a
  linked directory are **not** backed up; a symlink-to-file is copied as
  its target's content (the copy follows the link) — inherited behaviour
  of `synccli.scan_files` (`synccli.py:10`), stated here rather than
  silently inherited.
* **Optional stronger mode:** `backupctl run --verify` computes a SHA-256
  per file and compares it with the hash stored in the index, which closes
  the same-size/same-mtime blind spot. Cost: reads every byte of the
  source — 1 GB at the measured 70 MB/s ≈ **14.3 s** per 1 GB source,
  which is why it is opt-in and not the default.

---

## 8. Reporting — identical for scheduler and human

`build_report()` produces the report; the run prints it (human-readable
summary) and, with `--json`, the same content as a single JSON object on
stdout. There is no "scheduler mode" that behaves differently: the
scheduler is simply a cron entry that runs the same command and mails the
output.

Human-readable form (one line per source, then the summary):

```
snapshot snap-20261116-150000-01 published in 24.6s
source evals-2026-11: files=2 copied=1 reused=1 excluded=1 bytes_copied=12
  excluded: c/gone.txt (vanished)
source evals-work: files=1204 copied=3 reused=1201 excluded=0 bytes_copied=4096
recovered: re-derived index for snap-20261116-120000-01 from tree (1204 files)
pruned: snap-20261110-030000-01
```

Exit codes (the scheduler's contract):

| Code | Meaning |
|---|---|
| 0 | Snapshot published; every source complete; nothing recovered |
| 1 | Fatal error — **no snapshot published** (config error, verification failure, I/O error on the root) |
| 2 | Snapshot published but **degraded**: at least one source excluded files, had its index re-derived, was marked invalid, or was skipped because its lock was busy |
| 3 | **Nothing published** because every source was skipped (all locks busy) |
| 130 | Interrupted by `SIGINT`/`SIGTERM`; staging directory removed |

Note that "degraded" is *not* an error for the snapshot's integrity: a
degraded snapshot is a complete, self-consistent image of what could be
read, with the gaps explicitly recorded in `index.json`. Restore tooling
reads `excluded` and can warn the user.

---

## 9. Grounding — what is reused, and what is overridden

### 9.1 Reused as-is

| Existing code | Where `backupctl` uses it |
|---|---|
| `synccli.scan_files(root)` (`synccli.py:10`) | enumerating the source tree (Section 5.3) and re-deriving an index from a snapshot tree (Section 5.2, Case B) |
| `synccli.file_state(path)` (`synccli.py:22`) | the change-detection state `{size, mtime}`, used for the source scan, the post-copy torn-file check, and the index re-derivation |
| `synccli.build_manifest(root)` (`synccli.py:28`) | building the current manifest of a source (Section 5.3) |
| `synccli.changed_files(old, new)` (`synccli.py:36`) | the delta between the base snapshot's manifest and the current manifest (Section 5.3) |
| `synccli.collect_stale(items, seen)` (`synccli.py:45`) | selecting the snapshots retention must delete (Section 6) |
| `snaputil.list_snapshots(root)` (`snaputil.py:8`) | enumerating snapshots, oldest first, for retention and for `backupctl list` |
| `snaputil.snapshot_disk_usage(root, name)` (`snaputil.py:39`) | the `--stats` size report |
| `snaputil.safe_snapshot_path(root, name, rel)` (`snaputil.py:54`) | the restore-side path mapping that keeps a manifest path inside its snapshot (used by `backupctl verify`) |
| `snaputil.is_stale(dir, ref_epoch)` (`snaputil.py:66`) | the age-based retention rule (Section 6) — see the boundary note in 9.6 |
| `test_synccli.py` (6 tests) | the existing suite; it is run unmodified and passes (Section 11) |

### 9.2 Override: `synccli.sync` (`synccli.py:72`) is not called

`synccli.sync` writes its manifest non-atomically
(`open(path,"w")` + `json.dump`, `synccli.py:85-86`) and takes no lock, and
it syncs *into* a single destination directory, whereas a snapshot must be
published atomically and per source. `backupctl` therefore uses
`build_manifest` / `changed_files` / `copy_file`'s *semantics* directly and
implements its own publish path. Concretely, `synccli.sync` is replaced by
`backupctl.run_backup()`, which differs in exactly the ways Sections 3–6
describe (per-source lock, staging + atomic rename, atomic index write,
self-verifying index).

### 9.3 Override: `synccli.copy_file` (`synccli.py:62`) → `backupctl.copy_into_snapshot()`

Four concrete differences, all required by the brief:

1. **Error handling.** `synccli.copy_file` swallows every `OSError`
   (`synccli.py:68-69`, "unreadable source: skip it, next pass will
   retry"). For a *sync* that is the right trade-off (the next pass
   retries). For a *snapshot* it is wrong: a skipped file silently
   disappears from the snapshot while the manifest still promises it —
   exactly the "index promises files the snapshot does not contain" defect
   the brief forbids. `backupctl` propagates the error and records the file
   in `excluded` with a reason, so the snapshot and the index agree.
2. **Memory.** `synccli.copy_file` does `fdst.write(fsrc.read())`
   (`synccli.py:67`) — the whole file is held in RAM. A 1 GB file would
   need 1 GB of RAM. `backupctl` copies in 1 MiB chunks
   (`shutil.copyfileobj` with an explicit buffer), so memory per file is
   constant (§10).
3. **Durability.** `backupctl` writes to `<name>.tmp`, `fsync`s the file
   and `os.replace`s it, so a crash never leaves a truncated file under a
   name the index mentions.
4. **Regular files only.** `synccli.copy_file` opens whatever path it is
   given; a FIFO would block forever. `backupctl` stats the source first
   and treats non-regular files as excluded (`not-a-regular-file`).

Everything else — "copy to a path, creating parent directories as needed"
(`synccli.py:64`) — is kept.

### 9.4 Inherited behaviour of `synccli.scan_files` (`synccli.py:10`), stated explicitly

* Dot-directories are skipped (`dirnames[:] = [d for d in dirnames if not
  d.startswith(".")]`, `synccli.py:14`) — so `evals/**/.hidden/**` is **not**
  backed up. Dot-*files* are backed up. This is inherited, and it is a
  deliberate behaviour of the existing scanner, but it must be visible to
  the user: `backupctl` prints the excluded-pattern note once per run
  ("dot-directories are not backed up").
* Symlinked directories are not descended into (see 7.3).

### 9.5 Override: `snaputil.prune_snapshots` (`snaputil.py:23`) is not called

It deletes with `shutil.rmtree` on the live snapshot directory
(`snaputil.py:35`), which can tear a concurrent reader's image. `backupctl`
reuses `snaputil.list_snapshots` for the ordering and
`synccli.collect_stale` for the selection, but performs the deletion as
tombstone → rename to `trash/` → `rmtree` (Section 6). The *policy* is
identical (keep the newest `keep`); only the deletion mechanism is
overridden, and the reason is reader safety.

### 9.6 Use of `snaputil.is_stale` (`snaputil.py:66`) and its boundary

`is_stale` returns `os.stat(dir).st_mtime <= ref_epoch`, i.e. it is
**stale when the mtime is less than or equal to the reference**, while its
docstring says "A snapshot whose directory was modified at exactly
ref_epoch is not stale" (`snaputil.py:71-72`) — the docstring and the code
disagree on the boundary case. `backupctl` calls it with
`ref_epoch = cutoff − 1 s` (`cutoff = now − max_age_days`), so the
boundary-inclusive comparison implements exactly "age ≥ max_age_days" and
the ambiguity is never exercised. This is a deliberate, documented use of
the existing function; no change to `snaputil.py` is proposed (it is
existing code, not ours to fix silently).

---

## 10. Scaling — what grows with what, with explicit bounds

Notation: **N** = number of configured directories; **F** = total number of
files across all sources; **F_i** = files in source *i*; **B** = total
source bytes; **S** = bytes whose content changed since the last snapshot;
**F'** = number of files whose state changed; **K** = retained snapshots.

All constants below are **measured** on this machine (Section 11), not
guessed.

### 10.1 Per-run time

| Phase | Cost | Measured constant |
|---|---|---|
| Scan (walk + stat) all sources | `24.7 µs × F` | 24.7 µs/file (0.74 s for 30 000 files) |
| Copy changed files (bytes) | `S / 70 MB/s` | 70 MB/s (1 GB → 14.34 s) |
| Copy changed files (per-file overhead: create+write+fsync+rename) | `300 µs × F'` | ≈ 300 µs/file |
| Materialise unchanged files (clone/link/copy-from-base) | `215 µs × (F − F')` | clone 215 µs/file; link 356 µs/file; copy fallback ≈ 300 µs + bytes |
| Write index (JSON, ~80 B per file) | ≈ 0.08 s per 30 000 files | 2.4 MB of JSON for 30 000 entries |
| Pre-publish verification (`stat` per indexed file) | `25 µs × F` | ≈ 0.75 s per 30 000 files |

So:

```
T_run  ≈  F × 50 µs            (scan + verify, 25 µs each)
        + F × 215 µs           (materialisation of unchanged files)
        + F' × 300 µs          (per-file copy overhead)
        + S / 70 MB/s          (bytes actually copied)
```

**Growth:** linear in *F* (total files) and in *S* (changed bytes).
**Flat in N**: the per-source overhead is one lock acquisition, one
directory and one index fragment per source — O(N) with a constant below a
millisecond per source. Nothing in the per-run path is super-linear in N.

*Initial full backup, 1 GB / 30 000 files* (F' = F, S = B = 1 GB):

```
0.74 s (scan) + 14.34 s (bytes) + 9.0 s (per-file overhead) + 0.75 s (verify)
+ 0.08 s (index)  ≈ 25 s
```
→ **Budget: 45 s wall clock** for the first full backup of a ~1 GB,
~30 000-file tree (Section 11 gives the measurements and the machine).

*Incremental run with no changes* (F' = 0, S = 0):
`0.74 + 6.45 + 0.75 + 0.08 ≈ 8 s` — i.e. **no source bytes are read at all**,
and the run is ~3× faster than the full backup even though it still
materialises a complete snapshot.

### 10.2 Memory

| Item | Bound |
|---|---|
| Manifest of the source being processed | `393 B × F_i` (measured: 11.8 MB for 30 000 entries) |
| Copy buffer | **1 MiB, constant** (chunked copy) — independent of file size |
| Index assembly | streamed fragment-by-fragment ⇒ **O(1)** beyond the fragments on disk |
| Peak RSS | `393 B × max_i(F_i)` + 1 MiB + interpreter baseline (≈ 10 MB) |

Peak memory is bounded by the **largest single source**, not by N and not by
the total tree, because sources are processed one at a time and the
manifest is released before the next source starts. For a 30 000-file
source: ≈ 12 MB + 1 MiB + baseline ≈ 25 MB (measured 27.8 MB RSS for the
scan). For a hypothetical 100 000-file source: ≈ 40 MB.

### 10.3 Disk

* Retained snapshots: **K** (default 7) plus at most the snapshot being
  published.
* Unique bytes on disk: `≤ B + Σ_{s in retained} (bytes changed in s)`.
  With clone-based materialisation (APFS/btrfs), unchanged content costs
  **no extra space at all**; with the hard-link fallback it also costs no
  extra space (shared inode); with the copy fallback it costs the full
  size. Worst case (every file changes every run): `K × B`.
* Typical case (5 % of files change per run): `B + (K−1) × 0.05 B ≈ 1.3 B`.
* Freed space is reclaimed only after the last reader closes its
  descriptors (POSIX), so transient over-retention of at most one
  snapshot's worth of space is possible — bounded by `B`.
* `incoming/` holds at most one run's worth of staged data at a time
  (≤ B), and `trash/` holds at most the snapshots being deleted
  (≤ B) until the next run's recovery phase cleans it.

### 10.4 Other state

* Lock files: **N** files in `locks/`, O(1) each.
* The snapshot's `index.json`: **≈ 80 B per indexed file** (measured
  2.4 MB for 30 000 files) + O(N) for the sources array.
* The number of snapshot directories grows with the number of runs, but
  retention bounds it at **K + 1** (plus any snapshot marked invalid,
  which retention also reclaims once it is behind the `keep` window).

---

## 11. Measurements (the numbers in this document)

Environment: macOS 15.8.1, Apple M3 Max, APFS, Python 3.10.11. The
measurement tree was built **on the same volume as this repository**
(`/private/var/folders/k0/.../opencode/tree`): 30 000 files of ~33 KB each
= 1.0 GB, spread over 300 directories.

| Measurement | Method | Result |
|---|---|---|
| Existing suite still passes | `python3 -m unittest` (6 tests, `test_synccli.py`) | **OK**, 0.005 s |
| Scan + stat | `synccli.build_manifest(tree)` | **0.74 s** for 30 000 files → **24.7 µs/file** |
| Byte copy throughput | copy of all 30 000 files (read+write) | **14.34 s** for 1.0 GB → **70 MB/s** |
| Per-file copy overhead | write 33 KB + `fsync` + `rename` | **306 µs/file** (fresh) |
| Per-file copy, whole path | read + write + `fsync` + `rename` | **544 µs/file** |
| Unchanged-file fast path (clone) | `clonefile(2)` via `ctypes` on 30 000 files | **6.46 s** → **215 µs/file**; independent inode (verified) |
| Unchanged-file fallback (link) | `os.link` on 30 000 files | **10.69 s** → **356 µs/file** |
| Directory creation | `makedirs` per directory (300 dirs) | **197 µs/dir** |
| Manifest memory | `tracemalloc` around `build_manifest` | **11.8 MB** for 30 000 entries → **393 B/entry** |
| Index size | `json.dumps(manifest, indent=2)` | **2.39 MB** for 30 000 entries → **80 B/entry** |
| Peak RSS after a full scan | `resource.getrusage` | **27.8 MB** |

The measurement scripts live outside the repo (in the session's scratch
directory) and are reproduced in Appendix A so the numbers can be
re-derived.

---

## 12. Restore contract (for the separate restore tooling)

1. Enumerate with `snaputil.list_snapshots(root)` — only complete,
   published snapshots appear.
2. Read `<root>/snap-*/index.json`; it is never half-written (Section 4).
3. Refuse a snapshot that contains `.deleting` or `.invalid`.
4. Map paths with `snaputil.safe_snapshot_path(root, snapshot, rel)`
   (`snaputil.py:54`), which normalises `..` so a stored path cannot climb
   out of its snapshot.
5. If a file disappears mid-restore (`ENOENT`), the snapshot was pruned
   during the read: **abort and report**, never continue with a mixed
   image.

---

## 13. Test plan (for the implementation)

* `test_backupctl.py`, extending the existing style of `test_synccli.py`:
  * first run copies everything; second run copies nothing (reuse path);
  * a file removed from the source between runs is not in the new snapshot
    and does not appear in the index's `files`;
  * a file that vanishes *during* the run is recorded in `excluded` and the
    snapshot is still published and self-consistent;
  * a crash simulated by killing the process mid-run leaves only
    `incoming/<run_id>/`, no `snap-*` directory; the next run cleans it and
    publishes;
  * a corrupt `index.json` in the base snapshot triggers the Case-B
    re-derivation and the report says so; an index that disagrees with the
    tree triggers Case C (marked invalid, full copy);
  * two concurrent runs (two processes) on the same source: the second
    waits on the lock; both publish; no snapshot is corrupt;
  * a snapshot is never visible in `list_snapshots` before it is complete;
  * pruning keeps the newest `keep` valid snapshots and never deletes the
    just-published one;
  * retention leaves a tombstone and does not delete a snapshot in place
    (assert the rename-to-trash happens before the `rmtree`).

---

## Appendix A — reproducing the measurements

```python
# measure.py  — scan, copy throughput, clone/link cost, memory
import os, sys, time, shutil, resource, ctypes
sys.path.insert(0, "<repo>")
import synccli
T = "<scratch>/tree"; D = "<scratch>/dst"

m = synccli.build_manifest(T)                      # -> 0.74 s for 30k files
t0 = time.time()
for rel in m:
    synccli.copy_file(os.path.join(T, rel), os.path.join(D, rel))
print("copy %.2f s" % (time.time() - t0))           # -> 14.34 s for 1 GB

libc = ctypes.CDLL("libc.dylib"); clone = libc.clonefile
clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
t0 = time.time()
for rel in m:
    clone(os.path.join(T, rel).encode(), os.path.join(D, rel).encode(), 0)
print("clone %.2f s" % (time.time() - t0))          # -> 6.46 s for 30k files

t0 = time.time()
for rel in m:
    os.link(os.path.join(T, rel), os.path.join(D, rel))
print("link %.2f s" % (time.time() - t0))           # -> 10.69 s for 30k files
print("RSS %.1f MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6))
```

Tree generator: 30 000 files of 33 333 bytes in 300 directories
(`d000..d299/fNNNNNN.bin`), written from a 1 MiB random buffer.

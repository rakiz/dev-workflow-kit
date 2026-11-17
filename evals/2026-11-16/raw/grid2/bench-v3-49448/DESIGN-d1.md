# `backupctl` — design (fixture D1)

`backupctl` backs up the `evals/` workflow's result directories: a configured
set of N source directories, snapshotted point-in-time under a backup root,
with incremental runs, retention, and crash safety.

This document is the design. It is written against the code that exists in this
repository today (`synccli.py`, `snaputil.py`, `test_synccli.py`) and every
claim about that code was checked by running it (§2.2). Numbers quoted for
performance were measured on this machine with the harness in §12.5.

---

## 1. Decisions at a glance

| Question | Decision | Why |
|---|---|---|
| What is a snapshot? | A directory `snap-<UTC ts>-<seq>/` holding `tree/<alias>/…` (plain files), `manifests/<alias>.jsonl`, `index.json` | A restore that "reads a snapshot and copies it back" can copy a plain directory tree; the snapshot is self-describing and self-contained |
| How do runs not collide? | One `flock` on `<root>/.backupctl/run.lock`; the second run waits, then exits 75 without touching anything | `flock` is released by the kernel when a process dies — no stale lock, no manual cleanup |
| How does a reader know a run finished? | It never has to ask: a snapshot becomes visible by a single `rename()` of a fully built staging directory | `rename` is atomic; the `snap-` name space only ever contains complete snapshots |
| What if the process dies? | Everything incomplete lives under `<root>/.backupctl/staging/` (never named `snap-*`) and is garbage-collected by the next run | A reader can never mistake staging for a snapshot |
| What if the index is corrupt? | The header is discarded, the file table is re-derived from the tree with `synccli.scan_files()`, and the repair is reported (exit code 3) | The tree is the artifact; the index is rebuildable metadata |
| What if a source file vanishes? | It is not in the snapshot and not in the manifest; it is listed in the run report as `skipped/vanished`; exit code 3 | An index must never promise a file the snapshot does not contain |
| What is "unchanged"? | Per file: `(size, mtime_ns, mode)` from `os.stat`, with a SHA-256 content check whenever the metadata differs, or for every file under `--checksum full` | Metadata is cheap (1.1 µs/stat); content decides the truth when metadata is not conclusive |
| How do unchanged files avoid re-copying? | The file is *reused* from the previous snapshot by APFS `clonefile` (COW, 137 µs/file measured), else `os.link` (275 µs), else copied | Bytes are never re-written; content is verified before reuse |
| What gets deleted? | Retention `keep_last` + `keep_days`; deletion is rename-to-trash then unlink, and a leased snapshot is deferred | A reader never sees a half-deleted snapshot; the newest snapshot is never deleted |
| How fast is the first full backup? | Budget: **≤ 60 s for ~1 GB / ~30k files**; measured **11.7 s** (1 worker) / **5.1 s** (4 workers) on the reference machine | Derived in §12 from measured constants, with a re-derivation procedure |
| What grows with N, F, B? | Per-run time is `F × 0.15–0.28 ms` (measured constants), memory is `O(F_max)` and independent of N, disk is `B + Σ(changed bytes) + S × F × 184 B` | §13 gives every bound as a number or a formula |

---

## 2. Grounding: the code in this directory

### 2.1 What exists

| File | Symbol | Line | What it does today | Used by `backupctl` for |
|---|---|---|---|---|
| `synccli.py` | `MANIFEST_NAME` | 7 | `".sync_manifest.json"` | the manifest file name in `backupctl export --format sync` |
| `synccli.py` | `scan_files(root)` | 10–19 | `os.walk`, drops dot-**directories**, returns a **sorted** list of relative paths | the source scan *and* the re-derivation of a damaged manifest from the snapshot tree (§8.3) |
| `synccli.py` | `file_state(path)` | 22–25 | `os.stat` → `{"size", "mtime"}` (float) | superseded by `file_state_ns` (§14, override 2) |
| `synccli.py` | `build_manifest(root)` | 28–33 | `{relpath: state}` for the whole tree, via `scan_files` | the shape of `backupctl`'s per-alias manifest (same fields, plus `mode`/`sha256`) |
| `synccli.py` | `changed_files(old, new)` | 36–42 | files new or with a different state; **ignores deletions** | the "needs new content" set (§14, override 3) |
| `synccli.py` | `collect_stale(items, seen)` | 45–59 | stale (not yet fresh) entries of `(path, fresh)` pairs | the freshness bookkeeping of the reuse decision (§10.2) |
| `synccli.py` | `copy_file(src, dst)` | 62–69 | `open(dst,"wb")` + full read/write, **swallows `OSError`**, returns `None`, does not preserve mtime | superseded by `place_file` (§14, override 1) |
| `synccli.py` | `sync(src, dst, dry_run)` | 72–87 | diff → copy → write manifest **in place** | the run's shape, but not its publication (§14, override 5) |
| `snaputil.py` | `list_snapshots(root)` | 8–20 | `scandir`, keeps `snap-*` dirs, `sorted()` | snapshot enumeration (§7.2) |
| `snaputil.py` | `prune_snapshots(root, keep)` | 23–36 | `shutil.rmtree` of the oldest names, **in place** | superseded by `prune_to_trash` (§14, override 6) |
| `snaputil.py` | `snapshot_disk_usage(root, name)` | 39–51 | sum of `st_size` over the tree | apparent size per snapshot; paired with `disk_usage` for real disk cost (§14, override 8) |
| `snaputil.py` | `safe_snapshot_path(root, name, rel)` | 54–63 | `normpath` + `join`; the docstring promises containment | superseded by `snapshot_path` (§14, override 7) |
| `snaputil.py` | `is_stale(dir, ref_epoch)` | 66–73 | `mtime <= ref_epoch` | the age branch of the retention policy (§11) |

`backupctl` **adds** modules and does not modify `synccli.py` or `snaputil.py`,
so the neighbouring tool's behaviour and its test suite
(`python3 -m unittest`, 6 tests, all passing) are untouched. Every place where
`backupctl` must behave differently from the code above is a *named new
function* in `backupctl.py` that shadows the old behaviour, with the old
function cited in its docstring. The full table is §14.

### 2.2 Behaviours of the existing code that this design relies on (ten verified behaviours, all checked by running the code)

| # | Verified behaviour | How it was checked |
|---|---|---|
| V1 | `synccli.copy_file` swallows `OSError`: `sync()` reports `secret.txt` as copied, the manifest lists it, and the destination does **not** contain it — i.e. the manifest promises a file the destination lacks | chmod 000 on a source file, then `synccli.sync()` |
| V2 | `synccli.build_manifest` raises `FileNotFoundError` on a dangling symlink (`os.stat` follows the link) | dangling symlink in the source tree |
| V3 | `synccli.changed_files` does not report deletions: after deleting `b.txt` from the source, the second `sync()` reports `[]`, the manifest drops `b.txt`, but `b.txt` is still in the destination — the destination accumulates, it is not a mirror | delete a file, re-sync, inspect |
| V4 | `synccli.sync` writes `.sync_manifest.json` **in place**: a truncated manifest makes the next `sync()` raise `JSONDecodeError` | truncate the manifest, re-sync |
| V5 | `snaputil.safe_snapshot_path` does **not** contain the path: `'../../etc/passwd'` → `/backup/snap-1/../../etc/passwd`, and `'/etc/passwd'` → `/etc/passwd` (absolute path wins the `join`) | call it with those two inputs |
| V6 | `snaputil.prune_snapshots` deletes the live `snap-*` directory with `shutil.rmtree` (no rename first) | call it, watch the directory |
| V7 | `snaputil.list_snapshots` accepts **any** directory whose name starts with `snap-` (it also listed `snap-20261112-150000-07.tmp`) and sorts lexicographically, so `…-07` < `…-08` < `…-150010-01` | mixed names in one root |
| V8 | `synccli.scan_files` keeps dot-**files** (`vis/.dotfile`) and drops dot-**directories** (`.hidden`), does not traverse symlinked directories, does not record empty directories, and records a symlink-to-file as a regular file (its content is copied) | mixed tree inspection |
| V9 | `synccli.file_state` returns a float `st_mtime` (e.g. `1794871584.9999497`); at current epochs a float64 resolves ~0.5 µs, so ns comparisons are not exactly representable | call it, compare with `st_mtime_ns` |
| V10 | A dangling symlink is listed by `scan_files` as a file, so it reaches `os.stat` and raises (see V2) | combined with V2 |

V1, V3, V4 and V5 are the four places where the existing code would violate a
requirement of this brief. They are the reason for the overrides in §14, not
a general criticism of the neighbouring tool.

---

## 3. Goals, non-goals, assumptions

**Goals**

* G1 — A snapshot is a complete, self-consistent image of every configured
  source directory at one instant, never a mixture of two runs.
* G2 — No reader ever has to ask whether a run finished, and no reader ever
  sees a half-written snapshot, index, or deleted snapshot.
* G3 — A run that dies at any point leaves nothing that can be mistaken for a
  complete snapshot, and the next run completes without manual cleanup.
* G4 — A file that disappears or becomes unreadable is reported, and the
  snapshot stays consistent (the file is simply absent, and the index does not
  promise it).
* G5 — Retention deletes old snapshots without ever leaving the user without a
  usable one, and without disturbing a reader that is mid-read.
* G6 — Unchanged files are not re-copied; the granularity of "unchanged" and
  its blind spots are stated (§10).
* G7 — The initial full backup of ~1 GB / ~30k files has a committed budget
  (§12) whose derivation is reproducible.
* G8 — Every scaling claim is an explicit number or formula (§13).

**Non-goals**

* Not a versioned file-history system: there is no "restore the previous
  version of one file"; a snapshot is a point-in-time image.
* Not a filesystem-level snapshot: consistency is per file, not across the
  whole tree at one instant. Two files in the same snapshot are copied at
  different moments (§6.4 states the consequence).
* Not a replacement for the existing restore tooling. `backupctl` produces
  snapshots; restoring them is another tool's job. `backupctl export` exists
  to bridge formats if that tool expects something else (§5.4).
* Not multi-host. The backup root is on a local filesystem (A1).

**Assumptions**

* A1 — The backup root is on a local POSIX filesystem supporting `rename()`,
  `flock()`, `os.utime()`, and hard links. APFS and ext4 qualify.
* A2 — The restore tooling reads a snapshot as a directory of files (this is
  the format a "copy it back" tool consumes). If it turns out to expect a
  different layout, §5.4 (`export`) is the bridge; §15 discusses the
  alternative that would require no bridge.
* A3 — Sources are stable enough that a file vanishing mid-run is an
  exception to report, not a normal mode. The design nevertheless defines the
  behaviour precisely.
* A4 — The machine running the scheduled job and the machine a person runs
  the CLI on share the backup root (a local disk or a mounted volume).

---

## 4. On-disk layout

```
<backup_root>/
├── .backupctl/
│   ├── run.lock                       # flock target for the whole-run lock
│   ├── leases/
│   │   └── <snapshot>.<host>.<pid>.json   # "a reader is using this snapshot"
│   ├── staging/
│   │   └── <uuid>/                    # a run in progress; never named snap-*
│   └── trash/
│       └── <snapshot>.<epoch>/        # pruned, awaiting unlink
├── snap-20261112-150000-07/
│   ├── index.json                     # header: snapshot metadata + per-alias digests
│   ├── manifests/
│   │   └── <alias>.jsonl              # per-source file table, sorted by path
│   └── tree/
│       └── <alias>/
│           └── <relative path>        # the file data, as plain files
```

Rules that the rest of the design depends on:

* **L1** — Only directories named `snap-*` directly under the backup root are
  snapshots. `snaputil.list_snapshots` (`snaputil.py:8-20`) implements exactly
  this, and V7 shows it accepts *any* `snap-` prefix — so all in-progress and
  all doomed material lives under `.backupctl/` with a different prefix and is
  invisible to snapshot enumeration.
* **L2** — A snapshot name is `snap-<YYYYMMDD>-<HHMMSS>-<NN>`, UTC, `NN` a
  zero-padded 2-digit sequence within that second. Lexicographic order is
  therefore chronological order (V7), which is what `list_snapshots` returns
  ("oldest first").
* **L3** — Each configured source directory is addressed by an **alias**, a
  path-safe name (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, unique in the config).
  The alias is the directory name under `tree/` and the manifest file name, so
  two sources with the same basename cannot collide, and no source can inject
  a path outside the snapshot.
* **L4** — The snapshot's `tree/` contains exactly the files of the source,
  byte for byte, with the source's mode and mtime. Dot-directories are
  skipped, dot-files are kept, symlinked directories are not traversed and
  empty directories are not recorded — the semantics `synccli.scan_files`
  already has (V8). Symlinks are stored as regular files holding the
  target's content (what `synccli.copy_file` does today).
* **L5** — Blobs are not a separate store: the tree *is* the data. Reuse
  between snapshots is by filesystem-level sharing (clone / hard link), so
  unchanged files occupy no additional data blocks.

### 4.1 `index.json`

```json
{
  "format": "backupctl/snapshot-index/1",
  "snapshot": "snap-20261112-150000-07",
  "run_id": "6f1c9d2e-2a71-4a0e-9d1a-2b7f0c3e51aa",
  "created_utc": "2026-11-12T15:00:00Z",
  "host": "build-01",
  "sources": [
    {
      "alias": "evals-results",
      "path": "/srv/evals/results",
      "manifest": "manifests/evals-results.jsonl",
      "manifest_sha256": "9f2c…",
      "file_count": 18234,
      "total_bytes": 733003776,
      "skipped_count": 1
    }
  ],
  "skipped": [
    {"alias": "evals-results", "path": "run-9/partial.tmp",
     "reason": "vanished", "errno": 2, "detail": "No such file or directory"}
  ],
  "rebuilt": false,
  "index_sha256": "c41b…"
}
```

* `index_sha256` is the SHA-256 of the canonical JSON encoding
  (`json.dumps(obj, sort_keys=True, separators=(",", ":"))`) of the header
  **without** the `index_sha256` key. A reader recomputes it; a mismatch means
  the header is corrupt (§8.3).
* `manifest_sha256` is the SHA-256 of the per-alias manifest file's bytes.
* The header is intentionally **small**: it holds no per-file rows, only
  per-alias summaries. That keeps the header's memory and its re-derivation
  cost independent of the tree size (§13.2).

### 4.2 `manifests/<alias>.jsonl`

One JSON object per line, **sorted by path** (byte order of the UTF-8
relative path), so the file can be streamed and merged with the sorted output
of `synccli.scan_files`:

```json
{"path":"run-9/report.json","size":4096,"mtime_ns":1794871584999949758,"mode":33188,"sha256":"1f0a…"}
```

`mode` is the POSIX mode bits, `sha256` the content digest of the file as
stored in the tree (present for every entry of a normally built snapshot;
`null` for entries of a re-derived snapshot, §8.3).

Measured cost of this format: **184 bytes/line** (30 000 lines → 5.52 MB) and
1.0 µs/line to re-read and parse.

---

## 5. Command surface and configuration

### 5.1 Commands

```
backupctl run       [--config P] [--root P] [--jobs N] [--checksum auto|full|never]
                    [--lock-timeout S] [--fsync none|index|file] [--dry-run]
                    [--json] [-v]
backupctl list      [--root P] [--json]
backupctl verify    [--root P] [--snapshot NAME] [--deep]
backupctl prune     [--root P] [--keep-last N] [--keep-days D] [--json]
backupctl lease     <snapshot> [--root P] [--ttl S]
backupctl unlease   <snapshot> [--root P]
backupctl export    <snapshot> --to DIR [--root P] [--format tree|sync]
backupctl gc        [--root P] [--gc-after S]
backupctl benchmark [--root P]
```

`run` does the work; the rest are inspection and maintenance.

`--dry-run` runs the scan and the decision phase only: it reports what it
*would* copy, reuse and skip, writes nothing (no staging tree, no
publication, no pruning) and exits 0. It still takes the run lock, so its
baseline is the same one a real run would use.

The three checksum modes are defined in §10.1: `--checksum auto` (default),
`--checksum full`, `--checksum never`.

### 5.2 Exit codes (identical for scheduler and interactive runs)

| Code | Meaning | Snapshot published? |
|---|---|---|
| 0 | Success, no anomalies | yes |
| 2 | Usage error (argparse) | no |
| 3 | Success **with anomalies**: files skipped (vanished/unreadable), or a snapshot repaired | yes, and it is valid |
| 4 | Failure: no snapshot published (config error, source root missing, out of space) | no |
| 75 | Another run holds the lock; this run did nothing (`EX_TEMPFAIL`) | no |
| 1 | Unexpected internal error | no |

Nothing in the code branches on `isatty()`, on the invoking user, or on
whether the run came from cron. The only difference between a scheduled run
and a person's run is the verbosity of the human-readable report (`-v`), which
changes neither the snapshot's contents, nor the recorded anomalies, nor the
exit code (§9.4).

### 5.3 Configuration

JSON (stdlib only — this machine's Python is 3.10.11 and has no `tomllib`;
the neighbouring tools are stdlib-only too):

```json
{
  "backup_root": "/var/backups/evals",
  "sources": [
    {"alias": "evals-results", "path": "/srv/evals/results"},
    {"alias": "evals-logs",    "path": "/srv/evals/logs"}
  ],
  "retention": {"keep_last": 7, "keep_days": 30},
  "concurrency": {"jobs": 4, "lock_timeout": 300},
  "durability": {"fsync": "index"},
  "checksum": "auto"
}
```

Search order: `--config`, then `./backupctl.json`, then
`$XDG_CONFIG_HOME/backupctl/config.json`, then
`~/.config/backupctl/config.json`. Command-line flags override the file.
Aliases must be unique and match L3. A source path that contains the backup
root is rejected (otherwise the backup would back up itself).

### 5.4 `export` — the format bridge

`backupctl export <snapshot> --to DIR` materialises the snapshot as a plain
directory tree (`DIR/<alias>/<path>`), copying file content out of the
snapshot. `--format sync` additionally writes `DIR/<alias>/.sync_manifest.json`
in exactly the shape `synccli.build_manifest` produces — the mapping
`{relpath: {"size", "mtime"}}` under the file name `MANIFEST_NAME`
(`synccli.py:7`) — so a restore built around `synccli` can consume it
unchanged. `export` is also the intended way for a human to inspect a
snapshot without knowing the layout.

### 5.5 Module layout

The design adds two modules next to the existing ones (flat, like `synccli.py`
and `snaputil.py`):

| Module | Contents |
|---|---|
| `backupctl.py` | CLI, configuration, the run, reporting, exit codes |
| `bksnapshot.py` | the on-disk format: header and manifest read/write, atomic writes, `place_file`, `reuse_file`, repair, retention, GC, `export` |
| `test_backupctl.py` | the test suite of §16 |

`synccli.py` and `snaputil.py` are imported by both new modules and are left
unmodified.

---

## 6. The run

### 6.1 `backupctl run`, step by step

1. **Load config, resolve the root.** Create `<root>/.backupctl/{leases,
   staging,trash}` if missing. Reject a config whose source contains the root.
2. **Take the run lock** (§7.1). If it cannot be taken within
   `--lock-timeout`, exit 75 without writing anything.
3. **Garbage-collect orphans** (§8.5): remove staging and trash entries older
   than `--gc-after` (default 24 h) and expired lease files.
4. **Repair damaged snapshots** (§8.3): validate every snapshot's header and
   manifests; re-derive what is broken. Repair is recorded in the report.
5. **Choose the baseline**: the newest snapshot that is present and valid —
   call it *S_prev*. It supplies the previous state and the reusable content.
6. **For each source, sequentially** (this is what keeps memory independent of
   N, §13.2):
   a. `rels = synccli.scan_files(src_root)` (sorted relative paths, V8).
   b. For each `rel`: `os.stat` → `(size, mtime_ns, mode)`. A stat failure is
      not fatal: `ENOENT` → `skipped/vanished`, `EACCES`/`EPERM` →
      `skipped/unreadable` (§9).
   c. Compare against S_prev's manifest for that alias (§10.2) and decide, per
      file, `reuse` / `copy` / `skip`.
   d. Build `staging/<uuid>/tree/<alias>/…`: for each file, `place_file`
      (copy) or `reuse_file` (clone / link / copy fallback) (§6.2, §6.3).
   e. Write `staging/<uuid>/manifests/<alias>.jsonl` (sorted by path).
7. **Write the header** `staging/<uuid>/index.json` (atomic write inside the
   staging directory), then **publish** (§6.5).
8. **Prune** according to the retention policy (§11), after publication, so
   there is always at least one usable snapshot.
9. **Report**: human-readable summary, and `--json` for machines.

### 6.2 `place_file` — putting a file into the snapshot tree

```python
def place_file(src, dst, state, fsync_mode):
    """Copy src into the staging tree as dst. Returns one of:
       "ok" | "vanished" | "unreadable" | "error".
    Never leaves a partial file at dst."""
    tmp = dst + ".part"
    try:
        with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst, 1 << 20)
            fdst.flush()
            if fsync_mode == "file":
                os.fsync(fdst.fileno())
    except FileNotFoundError:
        os.unlink(tmp); return "vanished"
    except PermissionError:
        os.unlink(tmp); return "unreadable"
    except OSError as exc:
        os.unlink(tmp); return "error"
    os.chmod(tmp, state.mode & 0o7777)
    os.utime(tmp, ns=(state.mtime_ns, state.mtime_ns))
    os.replace(tmp, dst)          # atomic within the staging tree
    return "ok"
```

Three properties matter:

* **No partial file is ever visible.** The bytes land in `dst + ".part"` and
  become `dst` through a single `rename`. A crash mid-copy leaves a `.part`
  file inside a staging directory that is itself never published.
* **The mtime and mode are preserved.** The manifest's `mtime_ns` then equals
  the tree's file mtime, which is what makes §8.3's "re-derive the manifest
  from the tree" produce a manifest that is *equivalent* to the lost one, and
  what makes the reuse decision self-consistent.
* **The outcome is reported.** `synccli.copy_file` (`synccli.py:62-69`)
  swallows `OSError` and returns nothing, so `synccli.sync` records a file
  it never copied (V1) — precisely the "index promises files the snapshot
  does not contain" failure. `place_file` returns a status and the caller
  acts on it.

### 6.3 `reuse_file` — reusing unchanged content

For a file that S_prev already holds and whose content is verified unchanged:

1. **Clone** (`clonefile(2)` on APFS, via `ctypes`): 137 µs/file measured. The
   clone is a copy-on-write copy: same data blocks, **independent inode**, so
   a reader — or a buggy restore — that writes into one snapshot cannot
   corrupt another. `clonefile` preserves mode and mtime (verified).
2. **Hard link** (`os.link`): 275 µs/file measured. Same inode, so the
   content is shared; the snapshot's files must be treated as immutable (they
   are: `backupctl` never opens a published snapshot's file for writing).
   A hard link also inherits the previous snapshot's mtime, which is the
   source's mtime — consistent with the manifest.
3. **Copy** (fallback): if clone and link both fail (different filesystem,
   `EPERM`/`EXDEV`, the previous snapshot's file vanished mid-run), copy the
   content from the *source* directory instead. The run still produces a
   correct snapshot; it just costs bytes.

The fallback chain is what makes a concurrent prune safe: S_prev's file may
disappear between "I decided to reuse it" and "I link it"; the `ENOENT` is
caught and the file is copied from the source instead (§8.4).

### 6.4 What "point-in-time" means here

The copy of a 30 000-file tree takes seconds, so a snapshot is **not** an
instantaneous filesystem snapshot: file *A* may be captured at t=0.2 s and
file *B* at t=4 s. The unit of consistency is the file, and the snapshot
records each file's `size`, `mtime_ns` and digest, so a reader can tell
exactly what it got. Filesystem-level atomicity would need APFS snapshots or
`fs_snapshot`, which is out of scope (non-goal). For the evals workflow this
is acceptable: result directories are written once and then are not modified
in place.

### 6.5 Publication — the only moment a snapshot becomes visible

```
staging/<uuid>/                     fully built: tree/ + manifests/ + index.json
   │  os.rename(staging/<uuid>, <root>/snap-20261112-150000-07)
   ▼
<root>/snap-20261112-150000-07/     one atomic step; before it: invisible,
                                    after it: complete
```

* `os.rename` on a directory is atomic: readers see either the old state or
  the new state, never a partial one. On POSIX, renaming onto an existing
  **non-empty** directory fails with `ENOTEMPTY`, so publication can never
  silently replace an existing snapshot; if the target name was taken (only
  possible if the lock is unavailable, e.g. on NFS), the run bumps the
  sequence number and retries.
* Durability: with `--fsync index` (the default) the header and the manifests
  are fsynced before the rename, and the backup root is fsynced after it, so
  the *publication* survives a power cut. The **file data** is not fsynced by
  default — see §12.4 for the measured cost of doing so and the trade-off.
* The snapshot directory's own mtime is set to `created_utc` after
  publication, so `snaputil.is_stale` (`snaputil.py:66-73`) can be used
  directly for the age branch of the retention policy.

---

## 7. Concurrency

### 7.1 The run lock

* Location: `<root>/.backupctl/run.lock`.
* Mechanism: `fcntl.flock(fd, LOCK_EX | LOCK_NB)`, polled every 0.5 s until
  `--lock-timeout` (default 300 s) expires; then exit 75.
* **A dead run releases the lock automatically**: the kernel drops the `flock`
  when the process dies. There is no PID file to go stale and nothing to clean
  up — this is the core of "the next run must make progress without manual
  cleanup".
* The lock is an *optimisation and a serialiser*, not the correctness
  mechanism. Correctness rests on: unique staging directories, atomic
  publication, atomic header writes, and idempotent, rename-first deletion.
  Even with no lock at all (a second root on NFS, a killed lock holder), a
  run cannot corrupt another run's snapshot or a reader's view (§11.3).
* A waiting run does not sit on the lock silently: it prints
  `waiting for run lock (…s)`.

### 7.2 Two runs at the same time

* The second run either waits (and then runs normally, producing its own
  snapshot) or exits 75. Either way there is exactly one writer per
  snapshot directory, because each run owns a unique `staging/<uuid>` and
  publishes under a name it allocated.
* Two runs publishing in the same second get different `NN` sequence numbers
  (allocation happens under the lock). Without the lock, the `ENOTEMPTY`
  fallback in §6.5 keeps the names distinct.
* The cost of running them concurrently is duplicated work, not corruption.

### 7.3 A restore reading a snapshot while a run writes

* A run never writes into a published snapshot. It builds a new tree in
  staging and publishes with one rename. A reader that opened a file in
  `snap-X` keeps reading it (the inode survives; the bytes never change).
* A reader enumerating the root with `snaputil.list_snapshots` sees the
  snapshot before and after; it never sees a partially built one, because
  staging directories are not named `snap-*` (L1).
* A reader that opens a path inside a snapshot while that snapshot is being
  deleted is the one case that needs help — see the lease mechanism in §11.2.

### 7.4 Reader contract (what a reader may rely on)

1. `snaputil.list_snapshots(root)` returns exactly the published snapshots,
   oldest first.
2. Every directory it returns is complete: its `tree/` holds all the files
   its manifests list, and its `index.json` is present and self-consistent.
   *Exception:* a snapshot whose header is damaged is still listed (the
   header's damage is not visible in the directory name); the reader must
   validate the header (§8.3) and refuse to use a snapshot whose header does
   not verify.
3. A snapshot's contents never change after publication. Reuse between
   snapshots happens through copy-on-write clones or hard links, so no file
   in a published snapshot is ever rewritten.
4. A snapshot is either wholly present or wholly absent. There is no state in
   which half of it is there.

---

## 8. Crash safety, damage, and recovery

**Failure model.** The process can die at any instant: SIGKILL, Ctrl-C, laptop
sleep, OOM. Power loss is a *weaker* model and is handled only partially
(§12.4). Everything below assumes the file system's contents survive the
process's death, which is true for every local filesystem.

### 8.1 Invariant

> Any directory named `snap-*` directly under the backup root is a
> **published** snapshot: its tree is complete and self-consistent.
> (Its *header* may still be damaged afterwards — by storage corruption or an
> external edit — which §8.3 covers; a reader must validate the header before
> using the snapshot.)

It holds because (a) staging directories live under `.backupctl/staging/`
with a non-`snap-` name (L1), (b) publication is a single `rename` (§6.5),
and (c) deletions rename a snapshot out of the `snap-` namespace before
unlinking anything (§11.2).

### 8.2 What an interrupted run leaves behind

| Death point | What is on disk | What a reader sees | Next run |
|---|---|---|---|
| During the scan | a staging directory | nothing (no `snap-*` appeared) | GC removes the staging dir after `--gc-after` |
| During the copy of a file | `…/<file>.part` inside staging | nothing | same |
| After the header write, before the rename | a complete staging directory | nothing | same |
| During the rename | either the old state or the new state | nothing, or a complete snapshot | — |
| During pruning | the pruned snapshot is already in `.backupctl/trash/` | nothing (it left the `snap-` namespace) | GC removes the trash |
| During a header repair | the old header, or the new one | the old (possibly damaged) header | the repair is re-run; it is idempotent |

### 8.3 A corrupt or half-written index

A snapshot's index is two things: the header `index.json` and the per-alias
manifests. Both are written atomically (write to `.tmp` in the same
directory, `fsync`, `rename`) — inside the staging directory before
publication, and inside the snapshot directory during a repair. A half-written
index is therefore *not* a state the design can reach; but a damaged index
(cut short by a full disk, a bad block, a hand edit, a crash on a filesystem
without atomic rename) is reachable, and the recovery is defined:

**Detection** (in step 4 of the run, and in `backupctl verify`):

* the header is missing, is not valid JSON, or its `index_sha256` does not
  match the recomputed canonical digest → *header corrupt*;
* a manifest file named by the header is missing, or its bytes do not hash to
  the header's `manifest_sha256` → *manifest corrupt*;
* a manifest lists a file that is not in the tree, or the tree holds a file
  the manifest does not list → *tree/manifest disagreement*.

**Recovery**, in this order:

1. **Discard the header.** Nothing in it is trusted — not the alias list, not
   the counts, not the digests.
2. **Re-derive from the tree.** The tree is the artifact; the index is
   rebuildable metadata. For each directory under `tree/`, enumerate with
   `synccli.scan_files` (the same enumeration used for the source scan, so
   the rebuilt file set is exactly the file set that was built — L4/V8), `stat`
   each file for `(size, mtime_ns, mode)`, and write a fresh
   `manifests/<alias>.jsonl`. Because the tree's mtimes were preserved at
   copy time (§6.2), the re-derived states are the same values the lost
   manifest held.
3. **Rebuild the header** from the re-derived manifests: per-alias counts and
   byte totals, fresh manifest digests, `rebuilt: true`, `rebuilt_at`, and
   `rebuild_reason` (`header-missing` | `header-unparsable` |
   `header-checksum-mismatch` | `manifest-missing` | `manifest-checksum-mismatch`).
   The `sha256` of each re-derived entry is `null`: the digests cannot be
   recovered without reading the entire tree, and a wrong digest is worse than
   an absent one.
4. **Never touch the data.** A repair does not copy, delete, or rewrite a
   single file of the tree. It only replaces metadata.
5. **Report it.** The run's report gains
   `repairs: [{snapshot, reason, aliases, files}]`, and the run exits 3
   (success with anomalies) so the scheduler and the person both learn about
   it. `backupctl verify` prints the same information without running a
   backup.
6. **Restore digest coverage on the next run.** Because the re-derived entries
   have no digest, the next run verifies that alias by hashing both sides
   (the source file and the snapshot's file) once — `O(bytes of that alias)`
   reads — and then has normal digest coverage again. Files whose digests
   differ are copied; files whose digests match are reused.

**A corrupt index never blocks a backup.** Repair is bounded (one tree scan
plus one hash pass) and idempotent, so a repeated failure cannot spiral: if
the repair fails again, the run reports the failure, keeps the previous
header, and continues with the next source.

**A damaged tree is not repaired.** If the tree is missing a file the
manifest lists, the snapshot is reported as *damaged* (not repaired): the
bytes are gone and only a fresh copy from the source can restore them. The
next run does exactly that — the missing file is not in the previous
snapshot's tree, so the reuse step falls back to copying it from the source
(§6.3, fallback 3) — and the *new* snapshot is complete.

### 8.4 Interrupted runs and the baseline

S_prev is chosen as the newest snapshot that is present **and** valid. If the
newest snapshot is damaged, the run falls back to the previous one for reuse
purposes; a file that the damaged snapshot claimed but does not have is
copied from the source instead of being "reused" from a file that is not
there. This is exactly the `ENOENT` fallback of §6.3.

### 8.5 Orphan garbage collection

At the start of every run (step 3), under the lock:

* staging directories whose mtime is older than `--gc-after` (default 24 h)
  are removed — a staging directory younger than that might belong to a
  concurrent run that does not hold the lock;
* trash directories older than `--gc-after` are removed (their unlinks were
  interrupted);
* lease files whose `expires_utc` has passed are removed.

Nothing else is ever deleted automatically. A snapshot is removed only by the
retention policy (§11).

---

## 9. Source anomalies: a file that vanishes or cannot be read

### 9.1 The moments a file can fail

| Moment | Detection | What the snapshot contains | What the run reports |
|---|---|---|---|
| Between the scan and the stat | `os.stat` → `ENOENT` | the file is absent | `skipped: {path, reason: "vanished"}` |
| Between the stat and the copy | `open(src)` → `ENOENT` | the file is absent (nothing was placed) | `skipped: {path, reason: "vanished"}` |
| At the copy, unreadable | `open(src)` → `EACCES`/`EPERM` | the file is absent | `skipped: {path, reason: "unreadable", errno: 13}` |
| At the copy, I/O failure | any other `OSError` (e.g. `ENOSPC`) | the file is absent | `skipped: {path, reason: "error", errno: …}`; the run aborts with exit 4 if the disk is full |

### 9.2 The rules

* **A file that could not be captured is not in the snapshot.** The tree does
  not contain it, and the manifest's file table does not list it. The
  snapshot's header lists it under `skipped` with the reason and the errno.
  This is the direct answer to the brief's "never a snapshot index that
  promises files the snapshot does not contain": the index is written from
  the outcome of the copies, not from the intent to copy.
* **The snapshot is still published.** A file that vanished is not a reason to
  abandon the whole backup; the published snapshot is a complete, consistent
  image of *what could be read*, and the report says exactly what was
  missing.
* **No partial file is left behind.** `place_file` writes to `.part` and
  renames (§6.2), so a failed copy leaves no half-file in the tree.
* **Dangling symlinks are anomalies, not crashes.** `synccli.scan_files`
  lists them as files (V10) and `os.stat` then raises `FileNotFoundError`
  (V2) — today that aborts `build_manifest` with an exception. In
  `backupctl` the stat is wrapped, and a dangling symlink is reported as
  `skipped/vanished` like any other vanished file.

### 9.3 Why the behaviour is the same for the scheduler and a person

Both go through the same `place_file` and the same bookkeeping. There is no
"strict" mode for a person and "lenient" mode for cron, no retry loop for
one and not the other, and no code path that branches on the invoking user.
The difference between the two is only how much of the report is printed.

### 9.4 The report

Human-readable (default, one block per source; `-v` adds per-file detail):

```
snapshot snap-20261112-150000-07 published in 11.9s
  evals-results  18234 files  699 MiB  (copied 12, reused 18222, skipped 1)
  evals-logs      1102 files    9 MiB  (copied  0, reused 1102, skipped 0)
  skipped: evals-results/run-9/partial.tmp (vanished, errno 2)
  repaired: snap-20261111-020000-03 (header-checksum-mismatch, 18234 files re-derived)
  pruned: snap-20261012-150000-04
exit status 3 (completed with anomalies)
```

Machine-readable (`--json`): the same facts as a JSON object — `run_id`,
`snapshot`, `started_utc`, `duration_s`, per-source `files`/`bytes`/`copied`/
`reused`/`skipped`, the `skipped` array, `repairs`, `pruned`, `deferred`
(leased snapshots), `exit_reason`.

---

## 10. Change detection: what "unchanged" means

### 10.1 Granularity

**Per regular file, keyed by the path relative to its source root.** The
state compared is the triple

```
(size, mtime_ns, mode)
```

taken from `os.stat`, plus the content digest SHA-256 of the file as stored.

`synccli.file_state` (`synccli.py:22-25`) provides `size` and `mtime`; it is
replaced by `file_state_ns`, which returns `size`, `st_mtime_ns` and the mode
bits (§14, override 2).

**The three checksum modes** decide how much content is actually read:

* `--checksum auto` (default) — every file that is **copied** is hashed while
  it is written (2.48 GB/s, i.e. essentially free next to the copy), and the
  digest is consulted whenever the metadata says "changed". Files whose
  metadata is unchanged are *not* read.
* `--checksum full` — every file is hashed on every run, and compared with the
  digest recorded in the previous snapshot. Closes the blind spots of §10.3.
* `--checksum never` — no digest is computed or stored; the manifest's
  `sha256` is always `null`. The fastest mode, and the one that always has the
  §10.3 blind spot open.

### 10.2 The decision table

| S_prev has the path | Source state | Decision (`--checksum auto`) |
|---|---|---|
| no | — | **copy** (digest computed while copying) |
| yes, state equal | unchanged | **reuse**: clone → link → copy fallback (§6.3); digest inherited from S_prev |
| yes, state differs | changed? | hash the source file: digest == S_prev's digest → **reuse** (mtime or mode touched, content identical — no copy); otherwise → **copy** |
| yes, state equal, `--checksum full` | really unchanged? | hash the source file: digest equal → **reuse**; otherwise → **copy** |
| yes, but the file is absent from the source | deleted | **not in the new snapshot** — the new tree is built from the source, so deletions are automatic |

With `--checksum never` there is no digest to compare, so the third row
degenerates to "state differs → copy", and the fourth row does not exist.

The reuse bookkeeping reuses the shape of `synccli.collect_stale`
(`synccli.py:45-59`): the scan yields `(path, fresh)` pairs and the stale
ones are collected for copying.

Note the third row: a file whose mtime changed but whose content did not is
**not** re-copied — the digest check catches it. That is what makes the
mtime-based fast path safe in the common case of "the tool touched the file
without changing it".

### 10.3 What this granularity misses

The fast path compares `(size, mtime_ns, mode)`. It can therefore miss an
edit that produces a file with **the same size and the same `mtime_ns`**:

* **Timestamps restored by a tool.** `cp -p`, `rsync -a --times`,
  `tar -p`/`tar -x` with preserved times, and editors or build systems that
  set an explicit mtime all leave the mtime unchanged while the content
  changes. This is the realistic case.
* **Timestamp granularity.** The comparison is only as fine as the
  filesystem's mtime resolution: 1 s on HFS+ and FAT32, 1 ns on APFS and
  ext4. On a 1 s-granularity filesystem, an edit that lands in the same
  second *and* preserves the size is invisible to the fast path.
* **Inode swaps.** Replacing a file with another of the same size and mtime
  (some `mv`/`cp` combinations) is indistinguishable from metadata alone.

`--checksum full` closes all three: every file is hashed and compared with
the recorded digest. Cost, measured: 33 µs per file to open/read/close plus
2.48 GB/s of hashing → about 1.0 s and 0.4 s per GB respectively.

What the granularity *does not* miss, i.e. what is detected even in the
default mode: any change of size, any change of `mtime_ns` (however small,
including sub-second), any change of mode bits, and any file appearing or
disappearing.

Two deliberate consequences:

* The mode is part of the state, so `chmod +x` is a change and is re-copied.
* The digest is computed for every file that is copied (free relative to the
  copy: 2.48 GB/s) and inherited by every file that is reused. The tree
  therefore always has a known content digest for each of its files, which is
  what makes `--checksum full` and §8.3's repair possible.

---

## 11. Retention and safe deletion

### 11.1 Policy

A snapshot is deleted only when **both** conditions hold:

* it is not among the newest `keep_last` snapshots (default 7), **and**
* it is older than `keep_days` (default 30), measured with
  `snaputil.is_stale(snapshot_dir, now - keep_days*86400)`
  (`snaputil.py:66-73`) — the snapshot directory's mtime is set to the
  snapshot's creation time at publication (§6.5) so this test is meaningful.

The union semantics ("keep the last 7 *or* anything younger than 30 days")
means a busy root never falls below 7 snapshots, and a quiet root keeps 30
days of history even if that is fewer than 7.

Hard rules:

* **The newest snapshot is never deleted.** `snaputil.prune_snapshots`
  already guarantees this by construction (`doomed = names[:len(names)-keep]`,
  `snaputil.py:33`); the replacement keeps the guarantee.
* **At least one usable snapshot always remains.** The run publishes the new
  snapshot *before* pruning, and pruning never touches the newest one. If the
  configuration asks for `keep_last = 0`, it is clamped to 1 and a warning is
  printed.
* **The policy is applied after publication.** A crash between publication
  and pruning leaves an extra snapshot — harmless (the next run prunes it).

### 11.2 Deletion protocol: rename, then unlink

```
snap-20261012-150000-04
   │  os.rename → .backupctl/trash/snap-20261012-150000-04.1794500000
   ▼                                         (atomic: it leaves the snap- namespace)
.rmtree(.backupctl/trash/…)                 (66 µs per file, measured)
```

Why not `snaputil.prune_snapshots` as it stands (`snaputil.py:23-36`)? It
calls `shutil.rmtree` on the live `snap-*` directory (V6). Two consequences:

1. A reader enumerating the root sees the snapshot vanish *while* it is being
   deleted — its files disappear one by one under the reader's feet, and a
   reader that opens a path it had not opened yet gets `ENOENT`. With the
   rename first, the snapshot disappears from the namespace in one step: a
   reader sees it whole or not at all.
2. A crash in the middle of `rmtree` leaves a directory still named
   `snap-…`, which `snaputil.list_snapshots` will happily report as a valid
   snapshot (V7) — a half-deleted snapshot masquerading as a usable one. With
   the rename first, an interrupted deletion leaves garbage in
   `.backupctl/trash/`, which the next run's GC removes.

### 11.3 Being safe while something else is reading the snapshot being deleted

A reader that is copying files out of `snap-X` while X is deleted will get
`ENOENT` for the files it has not opened yet. Three layers:

1. **Open file descriptors keep working.** On POSIX, unlinking a file that is
   open does not disturb the reader: the inode survives until the last
   descriptor closes. A reader that streams files (rather than opening them
   one at a time by path) is unaffected.
2. **Leases.** A reader that wants the guarantee declares it:
   `backupctl lease snap-20261112-150000-07 --ttl 3600` writes
   `.backupctl/leases/<snapshot>.<host>.<pid>.json` = `{"created_utc", "expires_utc",
   "host", "pid"}`. The pruning step skips any snapshot with an unexpired
   lease and reports it as `deferred`. The restore tool — which is separate
   code — can create that file itself; the format is part of this design's
   contract. `backupctl unlease` removes it.
3. **Order of operations.** Pruning deletes the *oldest* eligible snapshots
   first and the newest ones last, so the window in which a reader can be
   surprised is as small as the retention policy allows.

Residual limitation, stated honestly: a reader that ignores the lease
protocol and opens files by path *after* the snapshot has been deleted can
lose them. No design can prevent that without cooperation from the reader,
which is why the lease protocol exists and why `backupctl export` (§5.4)
exists as an alternative: export copies the snapshot to a directory the reader
owns, and from that point the reader is unaffected by any deletion.

---

## 12. Performance: the initial full-backup budget

### 12.1 The commitment

> **Budget.** The initial full backup of the evals tree — about 1 GB in
> about 30 000 files — completes in **≤ 60 s** of wall-clock time on the
> reference machine, with the default 4 worker threads.
>
> **Measured on the reference machine: 11.7 s** with one worker, **5.1 s**
> with four workers (`bench_backupctl3.py`, §12.5).

The budget has ~5× headroom over the single-worker measurement, and ~12× over
the four-worker measurement. The number is not a guess: §12.2 derives it from
measured constants, and §12.3 gives the procedure to re-derive it on the
machine that will actually run the scheduled job.

### 12.2 The derivation

**Model.** The cost of a full backup separates into a per-file term and a
per-byte term:

```
T_full(F, B, J)  ≈  F · c_file(J)  +  B / R(J)  +  B / H
```

* `F` — number of files; `B` — total bytes; `J` — worker threads.
* `c_file(J)` — cost of putting one file into the tree (create, write,
  preserve mtime/mode, rename): **0.362 ms** at J=1, **0.140 ms** at J=4
  (derived below).
* `R(J)` — data throughput of the copy: **2.17 GB/s** buffered (measured:
  1 GB in 0.460 s), **1.47 GB/s** with a durable `fsync` at the end
  (measured: 1 GB of random data in 0.681 s).
* `H` — hashing throughput: **2.48 GB/s** (measured: 256 MB in 0.102 s).

**Where `c_file` comes from.** Two independent routes agree:

*Direct micro-measurements* (per operation, on this machine):

| Operation | µs |
|---|---|
| `os.stat` (warm) | 1.1 |
| open + read + close (existing 4 KiB file) | 33 |
| `os.open(O_CREAT)` + close (new file) | 72 |
| write 4 KiB + close | 114 |
| `os.utime` | 32 |
| `os.replace` (rename) | 89 |
| `clonefile` (bare) | 137 |
| `os.link` (bare) | 275 |
| `shutil.copyfile` (4 KiB, bare) | 283 |
| **Sum for the copy path** (open/read 33 + create 72 + write/close 114 + utime 32 + rename 89) | **≈ 340** |

*Two-point fit.* The measured full copies were 11.727 s (J=1) and 5.074 s
(J=4) for F = 30 000, B = 1.0 GB. Removing the byte term
(B / 2.17 GB/s = 0.46 s) and the hash term (B / 2.48 GB/s = 0.40 s):
```
c_file(1) = (11.727 − 0.46 − 0.40) / 30 000 = 0.362 ms
c_file(4) = (5.074 − 0.46 − 0.40) / 30 000 = 0.140 ms
```

The fit (0.362 ms) matches the micro-measurement sum (0.340 ms) to within
7 %; the model then predicts

```
T_full(30 000, 1.0 GB, J=1) = 30 000·0.362 ms + 0.46 s + 0.40 s = 11.7 s   (measured 11.727 s)
T_full(30 000, 1.0 GB, J=4) = 30 000·0.140 ms + 0.46 s + 0.40 s =  5.1 s   (measured 5.074 s)
```

Both predictions match the measurement to within 0.2 %. One caveat, stated
so the fit is not over-read: `R` was measured single-threaded (2.17 GB/s), and
at J=4 the byte term is presumably smaller still, so the fit attributes *all*
of the threading gain to the per-file term. The conclusion the design relies
on is unaffected — the per-file term is the dominant cost at every thread
count measured — but `backupctl benchmark` (§12.3) measures `R` at the
configured thread count rather than assuming it.

**Why the per-file term dominates.** A warm `stat` costs 1.1 µs and a raw
syscall 0.03 µs, so the machine is not syscall-bound; the cost is the
filesystem's per-file metadata transaction (72 µs to create a file on this
APFS volume). One GB of data is cheap here (2.17 GB/s); 30 000 *names* are
not. That is the single most important fact for the design, and it is why:

* reuse is worth doing (avoid the write term) but does not avoid the
  metadata term — §13 quantifies what is left;
* the tool is multi-threaded by default (`--jobs 4`: 2.3× faster than
  serial, and the measurement shows 8 and 16 threads are *worse* — 5.27 s and
  5.92 s — because the metadata transactions contend).

### 12.3 Re-deriving the budget on the target machine

`backupctl benchmark` runs the same micro-benchmarks (create, write, rename,
utime, stat, hash, plus a 5 000-file copy) and prints the constants and the
predicted `T_full` for the configured sources. The budget check is then

```
T_predicted = F · c_file(J) + B / R + B / H      ≤  60 s
```

with `c_file`, `R`, `H` measured on that machine. The check is reported by
`run` as `budget: predicted 11.9 s / limit 60 s`.

### 12.4 Durability modes and what they cost

| `--fsync` | What is made durable | Measured cost |
|---|---|---|
| `none` | nothing beyond the page cache | 0 |
| `index` (default) | the header, the manifests, and the publication (the rename) | 3 small fsyncs; the measured fsync latency on a small file is 0.03–0.04 ms, so **< 0.2 ms** per run (and < 0.5 ms even if each cost the 1 MiB-file latency of 0.155 ms) |
| `file` | every file's data as well | **+66 … +150 µs per file** (measured back-to-back at 5 000 and 30 000 files) → **+2.0 … +4.5 s** for 30 000 files |

The default `index` covers the failure model of this brief (the *process*
dies; the file system's contents survive). Power loss can leave a published
snapshot whose file *data* was still in the page cache — the header and the
manifests are durable, so the snapshot is self-describing, but some file
contents may be zero-length. `--fsync file` removes that window at a cost of
2–4.5 s per 30 000 files, which still fits the 60 s budget; it is offered as
an option rather than a default because on a slower device the same per-file
fsync would dominate the budget — a device with 5 ms fsync latency would add
150 s for 30 000 files, i.e. 2.5× the budget on its own.

### 12.5 Measurement harness

All numbers in this document were produced on the reference machine by
scripts kept outside the repository (they are measurement tools, not part of
the deliverable):

| Script | What it measures |
|---|---|
| `bench_backupctl.py` | tree build, `scan_files`, stat, atomic copy, hard link, fsync latency at 10 000 and 30 000 files |
| `bench_backupctl2.py` | per-file cost of copy/link/clone, bulk and durable byte throughput, manifest read/write |
| `bench_backupctl3.py` | micro-costs of each metadata operation, full copy at J = 1/4/8/16, stat and hardlink throughput at scale |
| `bench_backupctl4.py` | syscall baseline, isolated link cost, hash throughput, manifest costs |
| `bench_backupctl5.py` | fsync latency, durable write throughput, per-file fsync cost |
| `bench_backupctl7.py` | bare `clonefile` vs `os.link` vs `copyfile`; directory-level `cp -RpRc` |
| `bench_backupctl8.py` | manifest size, RSS per manifest entry, unlink cost |
| `verify_existing.py` | the ten verified behaviours V1–V10 of §2.2 |

**Reference machine.** macOS 14.6.0 (Darwin 24.6.0), arm64 (M2), 14 CPU
cores, 38 GiB RAM, APFS (`/dev/disk3s5`, "Data" volume); the repository and
all benchmarks live on that volume. Python 3.10.11 (stdlib only). The same
`stat`/`open`/metadata costs were observed in the home directory
(create+close 71 µs vs 125 µs in the temp tree), so they are a property of
the filesystem, not of the temporary directory.

---

## 13. Scaling: what grows, and by how much

Notation: `N` = number of configured sources; `F` = total files in the
sources; `F_max` = files in the largest single source; `B` = total bytes;
`C` = files that changed in a run; `B_c` = their bytes; `S` = number of
retained snapshots; `L` = average path length in bytes.

### 13.1 Per-run wall-clock time

| Phase | Formula (measured constants) | F = 30 000 | F = 300 000 |
|---|---|---|---|
| Scan the sources | `F × 5.7 µs` (`scan_files` + stat) | 0.17 s | 1.7 s |
| Read S_prev's manifests | `F × 1.0 µs` | 0.03 s | 0.3 s |
| Write the new manifests | `F × 1.8 µs` | 0.05 s | 0.5 s |
| **Reuse unchanged files** | `F × 137 µs` (clone) … `F × 275 µs` (link) | **4.1 s … 8.3 s** | **41 s … 83 s** |
| Copy changed files | `C × 340 … 390 µs + B_c / 1.5 GB/s` | — | — |
| Publish | 1 rename + 1 fsync | < 0.5 ms | < 0.5 ms |
| Prune | `O(S)` listing + `66 µs × files deleted` | 2.0 s per 30 000-file snapshot deleted | — |

**Steady state (nothing changed): `T_run ≈ F × 0.15 ms` (clone) to
`F × 0.29 ms` (link)** — 4.4 s to 8.5 s for 30 000 files, 44 s to 85 s for
300 000 files.

**This is the one term that grows with the size of the tree, and it is
unavoidable for a design in which each snapshot is a directory of files**: an
unchanged file still needs a directory entry in the new snapshot. §15
quantifies the alternative that removes it, and states the trigger for
switching.

`N` (the number of sources) does **not** appear in the total: the sources are
processed one after another, so the per-source terms add up, not multiply.
The only N-dependent costs are one `stat` of the source root per source
(µs) and one manifest file per source (S × N files in the root, each ~184 B ×
`F_i`).

### 13.2 Memory

* Peak memory is `O(F_max)` — one source's manifest at a time — because the
  sources are processed sequentially and each source's structures are released
  before the next one starts.
* Bound: `F_max × 500 B` (measured: 473 B per entry for a realistic
  dict-of-dicts with a 64-character digest; the mapping alone is 84 B).
  For `F_max = 30 000`: **≈ 15 MB**. For `F_max = 300 000`: ≈ 150 MB — the
  point at which the manifest would have to be streamed instead of held in
  memory (§17, O2).
* Independent of `N` and of `S`: the header holds only per-alias summaries
  (`N` entries), not per-file rows.
* The scan itself holds the sorted path list: `F_i × (49 B + L)` bytes
  (`str` object overhead plus the path). For `F_i = 30 000`, `L = 60`:
  ≈ 3.3 MB.

### 13.3 Disk

| Item | Size | Note |
|---|---|---|
| Snapshot data, first run | `B` | 1 GB |
| Snapshot data, later runs | `B_c` per run | unchanged files are clones (shared extents) or hard links (shared inode): **0 extra blocks** |
| Manifests | `S × F × 184 B` | 7 snapshots × 30 000 files → 38.6 MB |
| Headers | `S × ~1 KB` | |
| Trash / staging leftovers | bounded by `--gc-after` | normally 0 |

So the root's size after k runs is `B + Σ B_c + S × F × 184 B`, and the
retention policy bounds `S` (and therefore the manifest part) and the deltas.
With `keep_last = 7`, the root settles at roughly `B + (the largest delta
between two retained snapshots) + 39 MB`.

A snapshot's *apparent* size (`snaputil.snapshot_disk_usage`,
`snaputil.py:39-51`) counts a shared file once per snapshot, so it
over-reports the real disk cost; `backupctl` reports both: the apparent size
(reusing that function unchanged) and the real size, computed over unique
`(st_dev, st_ino)` pairs.

### 13.4 What stays flat

* The number of files in the backup root's control plane: `.backupctl/`
  holds one lock file, one lease file per live reader, and at most one
  staging and one trash entry per in-flight run.
* The header size: `O(N)` bytes, independent of `F`.
* The cost of publication: one `rename`, independent of `F` and `B`.
* The lock acquisition cost: one `flock`, independent of everything.

---

## 14. Overrides of existing behaviour

Each row names the existing symbol, where it lives, what it does today, what
`backupctl` does instead, and why. The new functions live in `backupctl.py`
(and `bksnapshot.py`); `synccli.py` and `snaputil.py` are **not modified**.

| # | Overridden | Where | Today | `backupctl` | Why |
|---|---|---|---|---|---|
| 1 | `copy_file(src, dst)` | `synccli.py:62-69` | writes straight to `dst` with `"wb"`, swallows `OSError`, returns `None`, does not preserve mtime | `place_file(src, dst, state, fsync_mode)` (§6.2): writes to `dst.part`, preserves mode and mtime, renames into place, returns `ok`/`vanished`/`unreadable`/`error` | A partial file must never be visible in a published snapshot; the run must be able to report per-file failures. Today the manifest promises a file the destination does not contain (V1) |
| 2 | `file_state(path)` | `synccli.py:22-25` | `{"size", "mtime"}`, float mtime | `file_state_ns(path)` → `{"size", "mtime_ns", "mode"}` | `st_mtime_ns` is exact where a float64 resolves only ~0.5 µs at current epochs (V9); the mode is part of the change detection |
| 3 | `changed_files(old, new)` | `synccli.py:36-42` | ignores deletions | used only for the "needs new content" set; the snapshot's file list is built from the fresh source scan, so deletions are reflected | A snapshot is a point-in-time image. Today the destination accumulates files deleted from the source (V3) |
| 4 | `build_manifest(root)` | `synccli.py:28-33` | builds the whole tree into a dict; raises on a vanished file (V2) | the new manifest is built line by line while the copy runs; a stat failure becomes a `skipped` record | The run must survive a vanishing file and must not hold two trees in memory at once |
| 5 | `sync(src, dst, dry_run)` | `synccli.py:72-87` | writes `.sync_manifest.json` in place; reuses the destination as the working copy | the run builds a staging tree and publishes it with one `rename`; the manifest is written inside staging | A torn manifest breaks the next run (V4), and a reader of a live destination sees mixed generations |
| 6 | `prune_snapshots(root, keep)` | `snaputil.py:23-36` | `shutil.rmtree` on the live `snap-*` name | `prune_to_trash(root, doomed, gc_after)`: rename into `.backupctl/trash/` first, unlink after | A reader must not see a snapshot being deleted file by file, and an interrupted deletion must not leave a half-snapshot under a `snap-` name (V6, V7) |
| 7 | `safe_snapshot_path(root, name, rel)` | `snaputil.py:54-63` | `normpath` + `join`; the docstring promises containment the code does not provide (V5) | `snapshot_path(root, name, rel)`: rejects absolute paths and any `..` component, then verifies containment with `os.path.commonpath` | A manifest path must not be able to make a restore read or write outside the snapshot |
| 8 | `snapshot_disk_usage(root, name)` | `snaputil.py:39-51` | sums `st_size`, counting shared files once per snapshot | reused unchanged for the *apparent* size; paired with a new `disk_usage()` that counts unique `(st_dev, st_ino)` | With clone/link reuse, apparent size and real disk cost differ by up to `S`× |
| 9 | `is_stale(dir, ref_epoch)` | `snaputil.py:66-73` | `mtime <= ref_epoch` | reused unchanged, after the snapshot directory's mtime is set to its creation time at publication | The age branch of the retention policy needs a meaningful mtime; the directory's natural mtime is the last file write |
| 10 | `list_snapshots(root)` | `snaputil.py:8-20` | any `snap-*` directory, lexicographically sorted | reused unchanged; the design ensures no other directory uses the `snap-` prefix (all staging/trash material lives under `.backupctl/`) | It already matches the layout and the naming rules (L1, L2) |
| 11 | `scan_files(root)` | `synccli.py:10-19` | sorted relative paths, dot-directories skipped | reused unchanged, for the source scan *and* for re-deriving a manifest from the tree | Its output is already sorted (which the manifest format needs) and its file-set semantics match what the tree stores (V8) |
| 12 | `collect_stale(items, seen)` | `synccli.py:45-59` | collects `(path, fresh)` pairs that are not fresh | reused for the reuse decision's bookkeeping | Same shape of problem |

---

## 15. Alternatives considered

**A content-addressed blob store (Borg/restic style):** the snapshot would be
a manifest of `path → blob-id`, and the bytes would live once in
`blobs/<sha256>`. Measured consequences on this machine:

* a steady-state run would cost `F × (1.1 µs stat + 1.0 µs manifest read +
  1.8 µs manifest write) ≈ F × 3.9 µs` — **0.12 s for 30 000 files**, against
  4.4–8.5 s for the tree design: **35–70× less per-run work**;
* deleting a snapshot would be "remove the manifest"; the bytes would be
  reclaimed later by a mark-and-sweep GC, which would make deletion *more*
  obviously safe for a concurrent reader;
* the cost: the restore must be manifest-aware (read the manifest, then read
  the blobs). The restore tooling is separate code whose expected format is
  not visible from this repository, so coupling the snapshot format to a
  manifest reader is a risk that the tree layout does not carry — a tree
  snapshot can be copied by anything that copies directories.

**Decision: the tree layout.** The per-run constant is worse, but the
restore contract stays "copy a directory", which is the contract the existing
tooling can meet without change. The trade is re-examined when either of
these becomes true: `F > 100 000` files, or a steady-state run exceeding
60 s. At that point the content-addressed layout (§15) becomes the better
engineering choice, and the migration is a change of the storage layer only
— the snapshot header, the report, the retention policy and the crash-safety
protocol do not change.

**Other options rejected:**

* *Copy-on-write snapshots of the source volume* (APFS snapshots): rejected —
  it needs the backup root on the same volume as the sources and privileges
  the evals workflow does not have.
* *`rsync --link-dest`*: rejected as the implementation (an external
  dependency and a manifest format we do not control), but its idea —
  hard-linking unchanged files from the previous snapshot — is exactly
  `reuse_file` (§6.3).
* *Copying everything every time*: rejected — that is the naive loop the
  brief names.

---

## 16. Test plan

`test_backupctl.py`, in the style of `test_synccli.py` (stdlib `unittest`,
`python3 -m unittest`). The existing 6 tests keep passing: `backupctl` adds
modules and does not modify `synccli.py`/`snaputil.py`.

| # | Test | What it pins down |
|---|---|---|
| T1 | `test_run_publishes_a_complete_snapshot` | the header verifies, the manifest lists exactly the tree's files, and the tree's contents equal the source's |
| T2 | `test_second_run_with_no_changes_copies_nothing` | `copied == 0`, `reused == F` — the incremental path (§10.2) |
| T3 | `test_modified_file_is_copied_once` | exactly one file is copied; the rest are reused |
| T4 | `test_touched_file_with_same_content_is_not_copied` | mtime changed, content identical → reuse, no copy (§10.2 row 3) |
| T5 | `test_mtime_preserved_edit_is_missed_by_default_and_found_by_checksum_full` | the documented blind spot (§10.3) behaves exactly as documented |
| T6 | `test_vanished_file_is_absent_and_reported` | the file is not in the tree, not in the manifest's file rows, present in `skipped`, exit code 3 |
| T7 | `test_unreadable_file_is_absent_and_reported` | same for `EACCES` (chmod 000) |
| T8 | `test_dangling_symlink_is_an_anomaly_not_a_crash` | the V2 behaviour is fixed |
| T9 | `test_two_concurrent_runs_do_not_corrupt_each_other` | two subprocesses; both exit 0 or one exits 75; the root has ≥ 1 valid snapshot; no partial tree |
| T10 | `test_reader_sees_a_complete_snapshot_during_a_run` | a reader loop during a run always finds a verifying header and matching files |
| T11 | `test_kill_mid_run_leaves_nothing_that_looks_like_a_snapshot` | SIGKILL the run; no `snap-*` directory is invalid; the next run succeeds; the orphan staging dir is GC'd |
| T12 | `test_corrupt_header_is_repaired_from_the_tree` | truncate/flip the header; the next run re-derives the manifest from the tree, keeps the file contents, reports the repair, exits 3 |
| T13 | `test_missing_manifest_is_rebuilt` | delete `manifests/<alias>.jsonl`; same repair path |
| T14 | `test_repair_is_idempotent` | repairing twice produces the same file set |
| T15 | `test_prune_keeps_the_newest_and_at_least_one` | the newest snapshot always survives; `keep_last = 0` is clamped to 1 |
| T16 | `test_prune_leaves_no_half_deleted_snapshot` | during the deletion, the root never contains a `snap-*` directory with missing files |
| T17 | `test_leased_snapshot_is_not_pruned` | the lease defers the deletion and the run reports it |
| T18 | `test_snapshot_path_rejects_traversal` | `"../x"` and `"/etc/passwd"` are rejected by `snapshot_path` (V5) |
| T19 | `test_export_materialises_the_tree` | `export` reproduces the source tree byte for byte |
| T20 | `test_export_sync_format_matches_synccli_shape` | the exported `.sync_manifest.json` has the shape `synccli.build_manifest` produces |
| T21 | `test_benchmark_reports_the_constants` | `benchmark` prints `c_file`, `R`, `H` and the predicted `T_full` (§12.3) |
| T22 | `test_config_rejects_duplicate_aliases_and_a_root_inside_a_source` | configuration safety |

A slow test (marked, excluded from the default run) builds a 30 000-file,
1 GB tree and asserts the measured initial full backup stays under the 60 s
budget, using `backupctl benchmark`'s constants rather than a wall-clock
assertion on a shared CI machine.

---

## 17. Open questions and risks

* **O1 — The restore tool's expected format.** The design assumes the restore
  copies a directory tree (§3, A2). If the existing restore expects a
  different layout, `backupctl export` (§5.4) is the bridge and costs one
  extra copy; the snapshot format itself does not change. This is the one
  assumption in the design that cannot be checked from this repository.
* **O2 — Manifest memory at very large F.** At `F_max > 300 000` the
  per-source manifest would cost ~150 MB (§13.2). The trigger for switching
  to a streamed merge (the previous manifest is already sorted by path, and
  `synccli.scan_files` is sorted too, so a streaming merge-join is
  straightforward) is `F_max > 300 000` or an RSS above ~200 MB.
* **O3 — NFS / network filesystems.** `flock` and `rename` semantics are
  weaker there; the design assumes a local filesystem (§3, A1). The
  correctness-critical operations (atomic publication, rename-first deletion)
  degrade to "eventually consistent" on such filesystems.
* **O4 — Consistency granularity.** A snapshot is per-file consistent, not
  instantaneously consistent (§6.4). If the evals workflow ever writes into
  result directories in place while a backup runs, the snapshot may mix
  generations of one file's content. The mitigation is the file-level digest
  recorded per entry.
* **O5 — Lease adoption.** The lease protocol only protects readers that use
  it. The existing restore tooling has to be taught to call `backupctl lease`
  (or to write the lease file itself) for the guarantee of §11.3 to apply.
  Until then, `backupctl export` is the safe path for a reader that must not
  be disturbed.
* **O6 — The 60 s budget is a property of this machine.** On a slower volume
  the number changes; §12.3 gives the procedure and the tool the command to
  re-derive it on the target machine, and `run` reports the prediction next
  to the limit.

---

## Appendix A — the run, in one page

```
backupctl run
  ├─ load config, validate aliases, create <root>/.backupctl/*
  ├─ flock(run.lock) ─────────────► busy: wait up to --lock-timeout, else exit 75
  ├─ GC: stale staging dirs, stale trash, expired leases
  ├─ repair damaged snapshots (header + manifests) ──► report
  ├─ pick S_prev = newest valid snapshot
  ├─ for each source (sequentially):
  │    ├─ rels = synccli.scan_files(src)                  [synccli.py:10]
  │    ├─ state = {rel: file_state_ns(src/rel)}            [override 2]
  │    ├─ for each rel: decide reuse / copy / skip         [§10.2]
  │    ├─ place_file / reuse_file → staging/<uuid>/tree/<alias>/…
  │    ├─ skipped[] accumulates vanished / unreadable       [§9]
  │    └─ write staging/<uuid>/manifests/<alias>.jsonl
  ├─ write staging/<uuid>/index.json (atomic)
  ├─ rename(staging/<uuid> → <root>/snap-<ts>-<seq>)      ← publication
  ├─ utime(snapshot dir, created_utc)
  ├─ prune (keep_last ∧ keep_days), rename-to-trash then unlink, honour leases
  └─ report (human / --json), exit 0 | 3
```

## Appendix B — measured constants (reference machine, §12.5)

| Constant | Value | How obtained |
|---|---|---|
| `os.stat` (warm) | 1.1 µs | 20 000 iterations, `bench_backupctl4.py` |
| open + read + close (existing file) | 33 µs | 5 000 iterations |
| `os.open(O_CREAT)` + close | 72 µs | 300 iterations, temp tree / 71 µs home tree |
| write 4 KiB + close | 114 µs | 300 iterations |
| `os.utime` | 32 µs | 300 iterations |
| `os.replace` | 89 µs | 300 iterations |
| `clonefile` | 137 µs | 2 000 iterations, APFS |
| `os.link` | 275 µs | 2 000 iterations |
| `shutil.copyfile` (4 KiB) | 283 µs | 2 000 iterations |
| full atomic copy, 30 000 files / 1.0 GB | 11.727 s (J=1) · 5.074 s (J=4) · 5.273 s (J=8) · 5.918 s (J=16) | `bench_backupctl3.py` |
| buffered bulk copy | 2.17 GB/s (1 GB in 0.460 s) | `bench_backupctl2.py` |
| durable write (random + fsync) | 1.47 GB/s (1 GB in 0.681 s) | `bench_backupctl5.py` |
| fsync latency (1 MiB file) | 0.155 ms median, 0.194 ms p90 | 20 samples |
| per-file fsync, added | +66 … +150 µs/file | back-to-back, 5 000 and 30 000 files |
| SHA-256 | 2.48 GB/s | 256 MB, `bench_backupctl4.py` |
| `scan_files` | 5.7 µs/file (30 000 files in 0.170 s) | `bench_backupctl.py` |
| manifest write / read | 1.8 µs/line · 1.0 µs/line | 30 000-line JSONL |
| manifest size | 184 B/line (5.52 MB per 30 000 files) | `bench_backupctl8.py` |
| manifest memory | 473 B/entry (dict of dicts) | `bench_backupctl8.py` |
| unlink | 66 µs/file | 5 000 files |
| `cp -RpRc` (directory clone) | 295 µs/file (8.85 s for 30 000 files) | `bench_backupctl7.py` |

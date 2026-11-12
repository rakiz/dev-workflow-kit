# DESIGN — `backupctl` (fixture D1)

`backupctl` snapshots a configured set of directories (N ≈ 3 today, a few
dozen over time) into a backup root, incrementally, safely under concurrent
runs and concurrent readers, with retention.

## 1. Grounding: what this design builds on

The design reuses `synccli.py` wherever its semantics fit, and diverges
deliberately where snapshot semantics differ from sync semantics.

| `synccli.py` symbol | Used by `backupctl`? | How / why |
|---|---|---|
| `scan_files(root)` (synccli.py:10) | **Yes, as-is** | Returns a sorted list of relative paths under a root. Snapshot staging needs exactly this. Its dot-prefilter (`dirnames[:] = ... not d.startswith(".")`) is also load-bearing for us: it keeps staging metadata (`.snapshot.lock`, `.snapshot.json`) out of the scan if a source dir ever nests inside a scanned tree, and keeps the backup root's own metadata invisible when a backup root is itself scanned. |
| `file_state(path)` (synccli.py:22) | **Yes, but the state key is extended** | Returns `{"size", "mtime"}`. We keep the same pair — it is the change-detection granularity (§7) — but wrap it as `("size", "mtime")` values in the snapshot index so a JSON round-trip cannot confuse tuple/list. No behavioral change to the function itself. |
| `build_manifest(root)` (synccli.py:28) | **Yes, as-is** | `{relpath: state}` for a whole tree. It is our per-source staging-tree manifest, and the cost basis for the perf budget (§8): one `os.stat` per file. |
| `changed_files(old, new)` (synccli.py:36) | **Yes, as-is** | "Changed or new, keyed by `relpath`, compared by exact state equality" is precisely the incremental rule we need between the previous snapshot's index and the fresh staging manifest. Note it only detects *new and changed*; deletions are computed separately (§6, using the same `old_manifest` keys it ignores). |
| `collect_stale(items, seen)` (synccli.py:45) | **Yes, as-is** | Pure function: items not marked fresh minus a seen-set. We use it for retention bookkeeping (§9): candidate snapshots marked fresh/hidden, pruned against a set of protected ids. It already has tests (`test_synccli.py:21-32`); we do not touch it. |
| `copy_file(src, dst)` (synccli.py:62) | **No — diverges (the one hard divergence)** | It *swallows* `OSError` (`except OSError: pass`, synccli.py:69). That is correct for sync ("next pass will retry") and **wrong for snapshots**: a run is point-in-time; there is no next pass for this snapshot, and silence would write an index that promises a file the snapshot lacks — violating the completeness invariant (§4). Our `copy` wrapper reports every failure into the snapshot's error list (§6) and counts it. See §3 "Divergences" for the full list. |
| `sync(src, dst)` (synccli.py:72) | **No — diverges, structurally** | Sync mutates the destination in place and rewrites the manifest inside the live tree (synccli.py:83-86). A snapshot must never be observed mid-mutation, so `backupctl` stages into a private temp dir and *publishes by atomic rename* (§4). Sync's write-manifest-last ordering is, however, the right instinct, and we keep the same ordering inside the staged tree. |
| `test_synccli.py` | **Yes, as-is** | Existing suite stays green; `python3 -m unittest` passes (verified: 6 tests, OK). `backupctl`'s tests are additive, in the same style (`unittest`, `tempfile`), and `backupctl` imports `synccli` for the reused functions above rather than copying them. |

### Divergences from existing behavior (explicit)

1. **`copy_file` swallows unreadable sources; `backupctl` records them.**
   Reason: sync is convergent and retried; a snapshot is point-in-time.
   Swallowing here would produce an index that lies (or, if we indexed from
   the copy result, a snapshot that silently misses files). Behavior is
   defined in §6, and is identical regardless of who triggered the run.
2. **Manifest is not written into the destination's live tree.** Sync's
   `open(dst_manifest_path, "w")` (synccli.py:85-86) would let a concurrent
   reader observe a half-written manifest. `backupctl` writes the index
   inside a staging directory and renames the directory atomically (§4).
3. **Changed-set also drives deletion accounting.** `changed_files` ignores
   files present in `old` but absent from `new` (synccli.py:39-42). That is
   correct for sync and we keep the function unchanged — but `backupctl`
   additionally walks `old_manifest.keys() - new_manifest.keys()` for the
   deletion list (§6). We extend around it rather than modify it, so
   `synccli` stays a drop-in dependency.

## 2. Layout on disk

```
<backup_root>/
  backups.json              # config + per-source bookkeeping (see below)
  snapshots/
    <source_id>/            # one subdir per configured source directory
      <timestamp>-<runid>/            # a published snapshot
      .staging-<runid>/               # in-flight snapshot (dot-prefixed, invisible
                                      #   to scan_files if a root ever nests here)
  locks/
    <source_id>.lock        # cross-process run lock (§5)
```

`backups.json` is a single JSON file in the style of `synccli`'s
`.sync_manifest.json` (same encoding conventions: UTF-8, `json.dump`,
`indent=2`): it records the configured sources, and for each source the id of
its latest *complete* snapshot. The authoritative index of a snapshot,
though, lives **inside the snapshot**: `<snapshot>/snapshot.json`, the
per-file manifest produced by `build_manifest` of the staged tree. A reader
never trusts a pointer in `backups.json` without the snapshot's own index
being present — and index presence is guaranteed by publish ordering (§4).

## 3. CLI shape

```
backupctl snapshot [--source NAME]...   # default: all configured sources
backupctl list    [SOURCE]
backupctl prune   [--keep-days D] [--keep-min N]
```

One process per invocation; all concurrency safety is via the filesystem
(no daemon, no server).

## 4. Atomic snapshot publication (completeness invariant)

A reader must see a complete, self-consistent image or nothing — never a
mix. The mechanism is **stage, then atomic rename**:

1. Acquire the per-source run lock (§5).
2. `staging = snapshots/<source_id>/.staging-<runid>` — created fresh.
3. Scan the source with `synccli.scan_files`, stat with `synccli.file_state`
   into a manifest via `synccli.build_manifest`.
4. Load the previous snapshot's `snapshot.json` (its manifest was built by
   the same `build_manifest`), diff with `synccli.changed_files` →
   `to_copy`; also compute deletions (§6).
5. **Hardlink unchanged files** from the previous snapshot's tree into
   staging (§7); copy `to_copy` with the divergent, error-recording wrapper.
6. Write `staging/snapshot.json` **last** — the exact ordering discipline of
   `sync`'s manifest-last write (synccli.py:83-86), kept for the same
   reason: until the index exists, the tree is not a snapshot.
7. `os.rename(staging, snapshots/<source_id>/<ts>-<runid>)` — POSIX rename
   on a directory is atomic; a reader either sees the old world or the new
   published directory, never the inside of a half-built one.
8. Update `backups.json` (latest-complete pointer) — written atomically too
   (write `.tmp`, `os.replace`). If the process dies between 7 and 8, the
   snapshot is still valid on disk; the next run re-points the bookkeeping.
   `list` scans the `snapshots/` tree and reconciles with `backups.json`,
   so no state is only in one place.

**Why rename is not enough by itself:** a directory rename is atomic, but a
reader that listed `snapshots/<source_id>/` just before the rename and opens
a file just after still sees the *published* dir — fine — and a reader
holding an open handle on a snapshot being *deleted* (§9) is protected by
POSIX unlink semantics: open file handles survive unlink; directory
traversal by path may fail, which the reader treats as "snapshot gone", a
defined outcome, not corruption.

**Crash recovery (Ctrl-C / kill / sleep):** a dead run leaves
`.staging-<runid>`. A staging dir is dot-prefixed, so `scan_files` never
mistakes it for data and no reader ever looks inside it (readers only ever
enter non-dot-prefixed, published snapshot dirs). The *next* run for that
source deletes every `.staging-*` older than 1 hour under its run lock
before staging its own — this is the "next run makes progress without
manual cleanup" requirement. A staging dir younger than 1 hour is left
alone, in case the run is merely slow (laptop sleep), not dead; it is
unambiguous by name which run owns it.

## 5. Concurrency: who may run, and what they may touch

| Actor | Concurrent with | Protection |
|---|---|---|
| run (scheduler) | run (person) | `locks/<source_id>.lock`: `os.open(..., O_CREAT\|O_EXCL)` + pid/`start-time` in the file. A second run for the *same source* either waits (scheduler default: skip with a log line) — per-source lock, so different sources never block each other. Stale lock = pid gone or `start-time` older than 24 h: stolen by the next run, which rewrites it. |
| run | run (different source) | Nothing shared is mutated: staging dirs and snapshots are per-source subtrees; `backups.json` updates go through write-`.tmp` + `os.replace`, last-writer-wins on a per-source pointer — the two runs touch disjoint keys. |
| run | restore reading an *old* snapshot | The run only ever writes into `.staging-*` and hardlinks/copies *from* old snapshots read-only. No mutation of published snapshots, ever. |
| run (publish) | restore listing snapshots | Rename is atomic (§4); a reader that raced the rename sees the pre-publish state, which is a consistent one. |
| prune | reader of a snapshot | §9. |

No snapshot is ever mutated in place. That single rule makes every
run×run×restore×prune combination safe by construction, with the locks
handling only the run×run-same-source staging contention.

## 6. Vanishing / unreadable source files

`changed_files` gives us the copy list, but between listing and copying a
file can disappear, and at copy time it can be unreadable. Behavior —
identical for scheduler- and person-triggered runs:

- The copy loop wraps each file individually (the divergent copy, §3-D1):
  - `FileNotFoundError` / `PermissionError` / any `OSError`: **record** in
    the run's error list: `{relpath, errno/strerror}`; continue.
- The staged tree then contains every file that *could* be read.
- `snapshot.json` is written with the manifest of what was actually staged
  **plus** an `"errors"` section. The invariant "the index never promises
  files the snapshot lacks" is preserved because the index is built from
  the staged tree (a post-copy `build_manifest(staging)` — cheap: it re-stats
  the copied set only... in fact we re-stat the whole staging tree; at 30k
  files that is the measured 0.65 s of §8, well inside budget).
- **Exit code / report:** run exits `0` if `errors` is empty, `1` if any
  file was skipped, printing the error list to stderr. The snapshot itself
  is still published and usable — a snapshot of a tree with one unreadable
  file is better than no snapshot — but the caller (cron mail, human) sees
  the failure. Repeated misses across runs are visible by diffing
  `snapshot.json` error sections.

This is the deliberate split from `synccli`'s silent-skip: same mechanical
outcome (file skipped), different reporting contract, because a snapshot's
index must be truthful for this point in time.

## 7. Incremental strategy and its granularity

**Granularity: (size, mtime), exact float mtime equality** — exactly the
`file_state` pair (synccli.py:22-25).

- First run per source: full copy of everything into the snapshot.
- Later runs: `changed_files(prev_manifest, new_manifest)`; unchanged files
  are **hardlinked** (`os.link`) from the previous snapshot into staging.
  Hardlinks give copy-speed (µs per file) dedup across snapshots while each
  snapshot is a self-contained directory tree a restore can `cp -a` without
  knowing anything about `backupctl`. Disk cost of an unchanged file is one
  inode, not one copy. If `os.link` fails (cross-device staging — cannot
  happen given the layout, but defensively), fall back to `shutil.copyfile`.

**What this granularity can miss (stated explicitly):**
- **Same-size, same-mtime edits.** A writer that preserves mtime (some
  build tools, archive extraction with `-m`, `touch -r`) and writes the
  same byte length is invisible. This is the classic rsync-size-mtime
  trade-off; accepting it is what makes 30k stats the only per-run scan
  cost. Mitigation path (not in v1): a content hash column, doubling
  read IO.
- **Sub-mtime-race edits:** a file modified twice within the same clock
  tick after the previous snapshot's stat, ending same-size. Same class as
  above.
- **mtime with float-precision round-trip through JSON** is exact in
  Python (JSON numbers round-trip IEEE 754 doubles); no additional slop is
  introduced by the index format.
- Metadata-only changes (permissions, ownership) are **not** captured —
  snapshots preserve what `shutil.copyfile` preserves (content only).
  Documented limitation; a restore of a snapshot yields default
  ownership/perms for copied files and inherited ones via hardlink.

## 8. First-full-backup performance budget

**Budget: ≤ 30 s wall-clock for a ~1 GB / ~30k-file tree on this machine
(APPLE SSD, APFS, Python 3 single-threaded); derived from measurement, not
a guess.**

Measurement performed in this directory with the actual reuse path —
`synccli.scan_files` + `synccli.file_state` + per-file `os.makedirs` +
`shutil.copyfile` + one `json.dump` manifest — against a generated tree of
exactly **30,000 files, 1,000,000,000 bytes**:

| Phase | Cost | Where it comes from |
|---|---|---|
| `scan_files` | 0.19 s | one `os.walk` over 30k entries |
| `build_manifest` stats | 0.65 s | one `os.stat` per file (`file_state`) |
| copy 1 GB | 16.65 s | 30k `copyfile` calls; ~60 MB/s effective including per-call open/mkdir overhead |
| manifest `json.dump` | 0.08 s | 30k-entry dict, `indent=2` |
| **Total** | **17.6 s** | |

Budget claim with 30% headroom for scheduler jitter and colder caches:
**≤ 30 s**. The dominant term is the copy itself and is irreducible in
single-threaded Python; the scan/stat overhead that scales with *file
count* is 0.84 s at 30k files — which is also the scaling argument in §10.
The measurement script mirrors the exact reuse path (§1), so the numbers
apply to the design, not to a strawman. Incremental runs are bounded by
scan+stat+diff+hardlink, measured here at ≈ 0.2 s + 0.65 s + (30k ×
hardlink ≈ negligible) — order 1–2 s — with copies added only for changed
files.

`synccli.copy_file`'s read-whole-file-into-memory
(`fdst.write(fsrc.read())`, synccli.py:66-67) is *not* reused for large
files: the divergent copy uses `shutil.copyfile`, which streams in chunks —
same observable behavior, bounded memory.

## 9. Retention and safe deletion

Policy (the design's definition):

- **Keep, per source:** the latest snapshot, always; every snapshot younger
  than `--keep-days` (default 14); and the most recent `--keep-min`
  (default 3) regardless of age — the "never without a usable snapshot"
  floor.
- Everything else is a deletion candidate. Candidates are evaluated with
  `synccli.collect_stale((snap_id, fresh), seen=protected_ids)` — the
  function's exact semantics: not-in-protected and not-fresh. (Grounding:
  this is why the function exists in the fixture and why we reuse it rather
  than a filter comprehension; it is already unit-tested.)
- Deleting a snapshot = `shutil.rmtree` on its directory. Safety under a
  concurrent reader: POSIX — a reader with the dir open/`cwd` inside keeps
  working through open handles; a reader resolving paths mid-delete gets
  ENOENT, which restore treats as "snapshot disappeared, pick another" —
  a defined, non-corrupting outcome. Because snapshots are immutable (§5),
  there is no torn state to observe; the worst case is a reader racing
  deletion and failing loudly.
- Deletion runs under the same per-source run lock (prune vs. run for the
  same source are serialized) but *not* against readers, which need no
  cooperation beyond immutability.
- Hardlinked content (§7) makes rmtree cheap on unchanged data and safe:
  `rmtree` removes this snapshot's links; other snapshots holding the same
  inodes are untouched. Free-space accounting is the familiar
  hardlink-refcount behavior.

## 10. What grows with what (N sources)

Grows (with N and tree size):
- **Per-run wall-clock:** sum over sources of scan+stat+diff (~1 s per
  30k-file tree, §8) + copy of changed files. Runs of different sources
  are independent and could be parallelized later; v1 is sequential.
- **Disk:** one inode per unchanged file per snapshot (hardlink), plus
  full copies of changed data. Retention (§9) bounds it.
- **`backups.json`** stays a handful of lines (per-source pointers).

Stays flat:
- **Memory:** O(largest single manifest) — one source's manifest at a time;
  N sources are processed one after another, nothing accumulates per
  source.
- **Per-file cost:** stat/copy/link per file is O(1) in N.
- **Locks:** one per source, only contended per-source.
- The 30k-file scan+stat overhead (0.84 s, §8) is the per-source constant;
  adding source #30 costs one more ~1 s scan, not a global restructure.

## 11. Test plan (additive, same style as `test_synccli.py`)

- publish ordering: kill a staged run (simulate: create `.staging-*`,
  assert `list` shows nothing, next run removes stale staging).
- concurrency: two threads snapshotting the same source; exactly one wins
  the lock.
- reader-during-publish: thread hammering `list` + reading the latest
  snapshot while a run publishes; assert every read is complete or absent.
- vanishing file: monkeypatch copy to raise `FileNotFoundError` for one
  path; assert snapshot publishes, index omits it, errors section records
  it, exit code 1.
- granularity: touch-with-same-mtime-and-size edit is not detected (assert
  the documented limitation).
- retention: protected floor never deleted; `collect_stale`-driven
  candidates match an independent enumeration.

The existing 6 tests in `test_synccli.py` continue to pass unmodified
(verified with `python3 -m unittest`).

# DESIGN — `backupctl` (fixture D1)

A command-line backup tool for `evals/` result directories. `backupctl` takes a
configured set of N source directories and produces **snapshots** — complete,
point-in-time copies — under a backup root. It builds on the code already in
this directory (`synccli.py`, `snaputil.py`) rather than re-implementing it.

Status: design. New code lives in `backupctl.py` (+ `test_backupctl.py`)
alongside the existing files; nothing in `synccli.py` / `snaputil.py` is
modified.

---

## 1. Code this design builds on (grounding inventory)

Everything below was read and, where measurable, measured in this directory.

### Reused as-is

| Existing artifact | What it gives backupctl | Where used |
|---|---|---|
| `synccli.build_manifest` (`synccli.py:28–33`) | per-directory `{relpath: {size, mtime}}` manifest of a source tree | change detection, §7 |
| `synccli.changed_files` (`synccli.py:36–42`) | the diff between two manifests: changed-or-new relpaths | change detection, §7 |
| `synccli.file_state` (`synccli.py:22–25`) | the change-detection state tuple `(size, mtime)` | §7 (granularity) |
| `snaputil.list_snapshots` (`snaputil.py:8–20`) | snapshot naming convention `snap-YYYYMMDD-HHMMSS-NN`, sorted oldest-first; ignores every entry that is not a `snap-*` directory (`snaputil.py:18–19`) | publish (§5), retention (§9), status |
| `snaputil.prune_snapshots` (`snaputil.py:23–36`) | retention: deletes the `len(names) - keep` **oldest** snapshots (`snaputil.py:33`), so the newest is never deleted; returns deleted names | retention, §9 |
| `snaputil.snapshot_disk_usage` (`snaputil.py:39–51`) | bytes of one snapshot, recursive | `backupctl status` |
| `snaputil.safe_snapshot_path` (`snaputil.py:54–63`) | maps a manifest relpath back under `backup_root/<snapshot>` with `..` normalized away — the path-traversal guard for restore | restore, §11 |
| `snaputil.is_stale` (`snaputil.py:66–73`) | "directory mtime ≤ ref_epoch" check | trash grace expiry, §9 |
| `synccli.collect_stale` (`synccli.py:45–59`) | given `(name, fresh)` items plus a `seen` set, returns the not-fresh names — used to classify published snapshots as incomplete during recovery | recovery, §8 |

### Reused with an explicit override (behavior named, location named, reason named)

1. **`synccli.scan_files` (`synccli.py:10–19`) — override: the dotfile filter.**
   Line 14 (`dirnames[:] = [d for d in dirnames if not d.startswith(".")]`)
   silently drops every dot-directory from the walk. For synchronization that
   is a convention; for a **backup** it is silent data loss (an evals tree
   containing `.git`, `.env`, or hidden checkpoint dirs would back up
   incomplete). backupctl defines `scan_all(root)` in `backupctl.py` with the
   identical walk/ordering minus line 14's filter. Reuse of the semantics is
   total (sorted relative paths, `os.walk`); the filter cannot be parameterized
   from outside because it is inline, so the function is re-declared, and this
   paragraph is the declared, reasoned override.

2. **`synccli.copy_file` (`synccli.py:62–69`) — two overrides.**
   (a) Lines 68–69: `except OSError: pass` — an unreadable or vanished source
   is skipped **silently**. The brief requires the run to report what a
   snapshot is missing; backupctl's copy catches `OSError`, records
   `(relpath, errno)` into the index's `files_skipped`, prints a `WARN` line,
   and influences the exit code (§8). (b) Line 67: `fdst.write(fsrc.read())`
   reads the entire source file into memory — O(filesize) memory per file.
   backupctl copies in 1 MiB chunks (memory bound in §10). The documented
   "create parent dirs" behavior of line 64 is kept.

3. **`snaputil.prune_snapshots` — kept, with a crash-window recovery instead of
   a rewrite.** `shutil.rmtree` (`snaputil.py:35`) deletes a snapshot in place.
   If the process dies mid-`rmtree`, a partial `snap-*` directory remains that
   a reader could mistake for complete. Rather than rewriting the function,
   backupctl keeps it as the retention mechanism (its oldest-first,
   newest-never-deleted logic is exactly the policy we want, `snaputil.py:33`)
   and defines the recovery in §8: any `snap-*` directory without a valid
   `index.json` is not a snapshot — the next run classifies it via
   `collect_stale` and discards it. Readers are additionally protected by the
   index-validation rule of §6.

### Deliberately NOT reused: `synccli.sync` (`synccli.py:72–87`)

`sync()` is a single src→dst mirror whose manifest lives **inside** the synced
tree (`.sync_manifest.json`, `synccli.py:7`), is written non-atomically
(`synccli.py:85–86`) and read without any corrupt-read recovery
(`synccli.py:77–79`), and copies straight into the destination — no staging, no
atomic publish. A snapshot tool whose reader "never asks whether the run
finished" cannot inherit any of that. backupctl reuses `sync()`'s *primitives*
(manifest, diff) and replaces the orchestration with the protocol of §5.

---

## 2. On-disk layout

```
<backup_root>/                     # one filesystem, configured
├── backupctl.lock                 # writer lock (flock), never removed
├── snap-YYYYMMDD-HHMMSS-NN/       # published snapshots (name matches
│   │                              # snaputil.list_snapshots' convention, snaputil.py:9–13)
│   ├── index.json                 # the snapshot index (§6)
│   └── <dir-name>/...             # one subtree per configured directory
├── staging-<pid>-<epoch>/         # run in progress; NEVER matches "snap-"
└── trash-<orig-snap-name>/        # snapshot being deleted; NEVER matches "snap-"
```

Readers only ever look at `snap-*`. `staging-*` and `trash-*` are invisible to
`snaputil.list_snapshots` by construction (`snaputil.py:18–19` accepts only the
`snap-` prefix) — this is the reuse that makes atomic publish and safe delete
possible without touching the helper.

Config — `backupctl.json`, same directory as the code (overridable with
`--config`):

```json
{
  "backup_root": "/backups/evals",
  "keep": 5,
  "directories": [
    {"name": "evals-2026-11", "path": "/repo/evals/results-2026-11"},
    {"name": "evals-2026-10", "path": "/repo/evals/results-2026-10"}
  ]
}
```

`name` becomes the subtree name inside each snapshot; it must be a plain
directory name (validated: no `/`, not `.`/`..`) — this is what
`safe_snapshot_path` composes with at restore time.

## 3. The snapshot index (`index.json`)

Written once per run, into staging, before publish:

```json
{
  "format_version": 1,
  "started_at": "2026-11-16T22:40:00Z",
  "finished_at": "2026-11-16T22:41:07Z",
  "status": "complete_with_skips",
  "directories": {
    "evals-2026-11": {
      "source_path": "/repo/evals/results-2026-11",
      "manifest":   { "<relpath>": {"size": 123, "mtime": 1699...} },
      "files_skipped": [{"rel": "a/b.log", "errno": 2}]
    }
  }
}
```

Invariant the design guarantees: **the index only ever describes files that
are actually present in the snapshot.** The manifest is not copied from the
source and patched; it is built from copy outcomes — a relpath appears in
`manifest` only after its bytes or hardlink landed in staging, and vanished /
unreadable files appear only in `files_skipped` (§8). "An index that promises
files the snapshot does not contain" is therefore unrepresentable, not merely
avoided.

## 4. Concurrency model

**One writer, many readers, no reader locks.**

- *run × run*: `backupctl run` opens `<backup_root>/backupctl.lock`
  (`os.open(O_CREAT|O_RDWR)`) and takes `fcntl.flock(fd, LOCK_EX|LOCK_NB)`.
  Lock held for the whole run: staging, publish, prune. A second concurrent
  run fails fast, exit code 2, message `another run holds backupctl.lock`
  (the scheduler passes `--wait 3600` to block up to 1 h instead). The
  kernel releases `flock` if the holder dies, so a dead run never wedges the
  next one. Every mutation of the backup root (staging cleanup, publish,
  prune, trash cleanup) happens under this lock, so no two of them can
  interleave.
- *run × restore*: a restore takes no lock. It reads only `snap-*` dirs,
  which are immutable once published (§5) and are never modified afterwards —
  the only mutation is deletion (§9). No combination corrupts either side.
- *restore × prune (delete)*: §9. In brief: the doomed snapshot is renamed
  `snap-*`→`trash-*` atomically first; a restore that already opened files
  keeps them via POSIX unlinked-open-file semantics; a restore that resolves
  a path mid-read either finds the file in the `snap-*` dir (still there,
  deletion hadn't reached it) or gets `ENOENT`, re-checks
  `list_snapshots`, and fails loudly — never silently, never corrupted.
- *run × human reading a snapshot*: same as restore — readers of published
  snapshots see either the whole snapshot or (mid-delete) a loud `ENOENT`,
  never a partial image, because publication and de-publication are both
  single `rename()` calls.

## 5. Run protocol (one snapshot, end to end)

Executed by `backupctl run`, all steps under the writer lock:

1. **Acquire lock** (§4). On failure: exit 2.
2. **Recover** (§8): discard `staging-*` dirs; trash-expire `trash-*` dirs;
   classify `snap-*` dirs with `collect_stale` and demote incomplete ones.
3. **Load previous state.** For each configured directory, find the newest
   published snapshot that contains a **valid** index (json.load succeeds,
   `format_version == 1`, the directory key is present) and take that
   directory's manifest as `old_manifest`. A corrupt/absent index here is not
   fatal: that directory's `old_manifest` = `{}` (full copy; §8 defines what
   is reported).
4. **Scan + diff.** Per directory: `src_manifest = build_manifest(path)`
   (built on `synccli.scan_files`-equivalent `scan_all`, §1 override 1, plus
   `synccli.file_state`); `to_copy = changed_files(old_manifest, src_manifest)`
   (`synccli.py:36`). Unchanged set = `src_manifest − to_copy`.
5. **Materialize into `staging-<pid>-<epoch>/`.**
   - unchanged relpath → `os.link(previous_snapshot/<name>/<rel>, staging/...)`
     — zero bytes written (§7, granularity: per-file);
   - changed/new relpath → chunked copy (override 2b);
   - deleted relpath → simply absent from staging.
   The previous snapshot's files are read but never modified.
6. **Write the index** from copy/link **outcomes** (§3), not from
   `src_manifest` directly. `fsync(index)` + `fsync(staging dir)`. No
   per-file fsync: a crash before publish discards the whole staging dir
   anyway (§8), so per-file durability buys nothing.
7. **Publish**: compute the name `snap-YYYYMMDD-HHMMSS-NN` — timestamp now,
   `NN` = (max seq in `list_snapshots(backup_root)` for today) + 1 — then
   `os.rename(staging, final)`. One atomic syscall: no reader can observe the
   snapshot before or partially after this point. This single rename is the
   entire answer to "a reader never asks whether the run finished": a
   `snap-*` dir exists **iff** a complete run finished creating it.
8. **Prune** (§9). Still under the lock; the run's own snapshot is already
   published, so `keep` always includes it.
9. **Report** on stdout, e.g.:
   `snap-20261116-224100-07: 3 dirs, 12431 files (641 copied, 11790 linked, 0 skipped), 3.2 MB written`
   plus one `WARN` line per skipped file. Exit code: `0` clean, `1` completed
   with skips/missing dirs (see §8), `2` lock busy, `3` config error.

Identical code path for scheduler and human triggers — the brief's
"same behavior whether the run was started by the scheduler or by a person"
holds by construction; the only difference between trigger styles is the
`--wait` flag.

## 6. What a reader sees (the consistency argument)

A published snapshot is a directory renamed into place after its data files
and its index are complete and ordered (index written last, §5 step 6).
Therefore: anything that reads `snap-X/index.json` reads an index written from
the final outcomes of run X, and every file it promises is in the tree. A
reader never sees a mix of runs because the previous snapshot is never
written into — each run's files link/copy from the previous snapshot into a
*new* directory. Concurrency (§4) + atomic publish (§5.7) + index-from-outcomes
(§3) are three independent facts; any one alone would justify the reader
guarantee; all three hold.

## 7. Change detection: granularity and its blind spots

**Granularity: per file, state = `(st_size, st_mtime)`** — exactly
`synccli.file_state` (`synccli.py:22–25`), compared by `changed_files`
(`synccli.py:36–42`). `mtime` is the float `st_mtime`, serialized to JSON;
two states are "different" iff the dicts differ.

**Edits this can miss** (stated, per the brief):

1. An edit that leaves both size and mtime unchanged — e.g. an in-place write
   of equal length whose mtime is then restored with `utime()`, or (the
   realistic case) two writes within the same mtime tick where the platform
   mtime resolution is coarse. Both size-equal and mtime-equal must hold for
   a miss.
2. Any change to file metadata backupctl does not record (permissions, xattrs)
   — the file will not be re-copied.

**False positives (safe direction):** a touch/rewrite that changes mtime but
not content causes a re-copy. Accepted; it wastes bytes, never correctness.

**Escape hatch:** `backupctl run --verify-hash` additionally stores
`sha256` per file in the index and treats a hash mismatch as "changed". Cost:
reads every byte every run (bound in §10); off by default.

**Unchanged files are hardlinked, not re-copied.** Unchanged relpaths are
`os.link`ed from the newest snapshot that contains them (POSIX hardlink; same
filesystem by construction — both live under `backup_root`). Consequences,
stated: (a) zero new bytes per unchanged file, so a run writes ≈ Δbytes of
real change plus metadata; (b) deleting an old snapshot unlinks its names —
linked content survives while any snapshot references it; (c) hardlinks share
inodes, so an in-place edit of a snapshot file would corrupt its siblings —
snapshots are documented read-only, restore copies out, and this is the same
trade `rsnapshot` makes; (d) if `os.link` fails (e.g. filesystem without
hardlink support, Windows) the file falls back to a plain copy and the run
notes it. Measured on this machine (APFS, Python 3.10.11): linking costs
≈ 0.34 ms/file (10 000 links in 3.4 s) versus copying 64 KiB files at
158–262 MB/s — i.e. for trees of small files, linking ≈ copying in wall
clock, and the win is the ~0 bytes written plus large files (link cost is
constant, copy cost grows with size; crossover ≈ 60–90 KiB). The brief's
requirement is about not *copying* unchanged data again, which the hardlink
satisfies in bytes, not just in time.

## 8. Crash recovery and index corruption (the process can die at any point)

The next run that acquires the lock performs recovery, in this order:

| Leftover from a dead run | Rule | Report |
|---|---|---|
| `staging-<pid>-<epoch>/` exists | Under the lock, any staging dir is provably dead (a live run holds the lock; a run cleans its own on exit) → `rmtree`, rebuild from the source tree. Nothing of it was visible (never `snap-*`). | `recovered: removed staging-…` on stderr |
| `snap-*` dir whose `index.json` is missing, unparsable, or wrong `format_version` | It is not a snapshot: a published one always has a valid index (§5.6–7), so this is a killed prune or external damage. Demote: `rename` to `trash-…`, then delete. Classification uses `synccli.collect_stale` (`synccli.py:45–59`): `items = [(name, has_valid_index) for name in list_snapshots(root)]`, `seen` = names already demoted in this pass; the stale list is exactly the incomplete ones. | `WARN discarded incomplete snapshot …` |
| `trash-…/` older than the 24 h grace | Delete (`is_stale(trash_dir, now − 86400)` → True, `snaputil.py:66–73`). Younger trash stays, so a mid-`rmtree` kill leaves bytes that the grace window protects. | `recovered: removed trash-…` |
| Previous snapshot's index is corrupt **as input** (step 5.3) | Discard that index as a source of `old_manifest`; re-derive from the source tree (`old_manifest = {}` → full copy of that directory). The damaged snapshot itself is left alone — its bytes may still be intact and human-readable; it just doesn't seed incrementality. | `WARN index of snap-… unusable; full backup of <dir>` |

Nothing in this table requires manual cleanup, and every path makes forward
progress on the next run: staging → deleted and rebuilt; partial prune →
finished by demotion; corrupt index → full copy.

**Sources that disappear** (brief: vanish between listing and copying, or
unreadable at copy time): the chunked copy's `OSError` handler (override 2a)
records the file in `files_skipped` with the errno, the file is simply absent
from the snapshot and absent from the manifest (so the next run re-attempts
it — the diff will show it as new-or-changed), the run prints
`WARN skipped <name>/<rel>: No such file or directory (errno 2)`, sets
`status: complete_with_skips`, and exits `1`. A whole configured directory
that is missing at scan time is one more `files_skipped` entry at the
directory level, same WARN, same exit code. Behavior is trigger-independent
(§5): there is no interactive prompt anywhere in `backupctl`.

## 9. Retention and safe deletion

Policy: `backupctl run` prunes after every successful publish, keeping the
newest `keep` snapshots (`backupctl.json`, default 5, hard floor 1 enforced at
config load). Mechanism: `snaputil.prune_snapshots(backup_root, keep)`
(`snaputil.py:23–36`) — reused, not re-implemented. Its guarantees hold: it
orders via `list_snapshots` (oldest first) and slices `names[:len(names) −
keep]` (`snaputil.py:33`), so **the newest snapshot is never a deletion
candidate**; combined with publish-before-prune ordering (§5.7→8), after any
run at least `keep ≥ 1` usable snapshots remain. The brief's "deletion must
never leave the user without a usable snapshot" is thus a property of the
reused code plus the calling order, and `run` additionally checks the
would-remain set contains ≥1 valid index before invoking prune (abort with
exit 3 otherwise — belt and braces).

Reader safety while deleting:

1. `backupctl` first `rename()`s each doomed `snap-*` → `trash-…` (atomic
   disappearance from every reader's `list_snapshots` view), then `rmtree`s
   the trash. This is the one behavioral addition to `prune_snapshots`, and it
   wraps rather than replaces it: the doomed-list computation, oldest-first
   order, and newest-never-deleted property are `prune_snapshots`' (`snaputil.py:33`);
   the rename step exists because a process killed mid-`rmtree` would
   otherwise leave a half-empty `snap-*` dir — the exact state §8's recovery
   then has to classify. (Crash mid-rmtree inside trash-* is harmless by
   construction: already invisible, grace-expired later.)
2. POSIX: a restore holding open file descriptors on a snapshot keeps reading
   them after the names are unlinked.
3. The 24 h trash grace (§8) plus the restore-side `ENOENT`-and-recheck rule
   (§4) close the only residual window: a restore that resolved a snapshot
   name but not the file, racing the rmtree. It fails loudly with
   "snapshot was pruned during restore", never with a corrupt restore.

Prune can also run standalone (`backupctl prune --keep K`), same code path,
same lock.

## 10. Performance budget for the first full backup

**Measurement** (this machine — Apple Silicon Mac, APFS SSD, Python
3.10.11; synthetic tree of 10 000 files × 64 KiB = 655 MB, generated and
copied within `/private/var/.../T`):

| Operation | Measured | Source |
|---|---|---|
| Scan + stat (`scan_files` + `file_state`) | 10 000 files in 0.235 s → **42 470 files/s** | run in this directory against `synccli.scan_files`/`file_state` |
| Full byte copy, whole-file-read (`synccli.copy_file`) | 655 MB in 2.50 s → **262 MB/s** | `synccli.copy_file` unmodified |
| Full byte copy, chunked (`shutil.copyfile` + `makedirs`) | 655 MB in 4.14 s → **158 MB/s** | the copy primitive backupctl ships (override 2b) |
| Hardlink creation (`os.link`, dirs pre-made) | 10 000 in 3.4 s → **2 900 files/s** | §7 |
| Index serialization (`json.dumps`, 2-key entries) | 10 000 entries in 6 ms → 0.6 MB (~60 B/entry on disk) | §3 |

**Derivation for the stated target: ~1 GB tree, ~10⁴–5·10⁴ files.**

- Byte copy: 1 GB ÷ 158 MB/s (the slower of the two measured copy paths) = **6.5 s**.
- Scan + stat: 50 000 ÷ 42 470 files/s = **1.2 s**.
- Index build + write: ~3 s at 50 000 entries (500× the 6 ms measurement,
  plus fsync) = **< 4 s**.
- Total predicted: **≈ 12 s**; with the faster copy path, ≈ 8 s.

**Budget: the initial full backup of a ~1 GB / tens-of-thousands-of-files tree
completes in < 60 s wall clock** — ≥ 5× headroom over the derived figure, and
≥ 2× even if throughput halves on the real evals trees (many tiny files, slower
disk). The number is not a guess: every term is the measurement above or a
linear extrapolation of one, and the tools to re-check it are in this
directory (`python3 -m unittest`, plus the same benchmark harness used to
produce the table). The 60 s budget deliberately excludes per-file fsync,
which §5.6 explains is unnecessary under the staging/publish protocol.

## 11. Scale: what grows with what, with explicit bounds

Let N = configured directories, F = total files over all of them
(F = Σ Fᵢ), B = total bytes, ΔB = bytes that changed since the previous
snapshot, ΔF = changed-or-new file count.

| Quantity | Bound | Basis |
|---|---|---|
| Scan + diff work per run | O(F) stats; time ≈ F / 42 470 s | measured scan rate (§10); one pass per file, independent of N |
| Copy work per run | O(ΔB) bytes; time ≈ ΔB / 158 MB/s | measured; unchanged files are links, not copies |
| Link work per run | O(F − ΔF) links; time ≈ (F − ΔF) / 2 900 s | measured link rate (§10) |
| Disk written per run | ΔB bytes + ~60 B/file of index | measured index size (§10) |
| Disk at rest | ≤ B (first snapshot) + Σ over retained snapshots of ΔBₖ; bounded absolutely by `keep × B`, in practice ≪ that | retention §9 |
| Memory during run | O(Fᵢ) for the largest directory's manifests (~60 B/entry measured → 50 000 files ≈ 3 MB per manifest, two manifests live at once ≈ 6 MB); copy buffer constant (1 MiB) | measured `json.dumps` size; override 2b |
| Per-run fixed overhead | O(1): one lock, one index, one publish rename, one prune call | §5 |
| Per-directory overhead | O(1) per directory: one manifest load, one index entry — N appears **nowhere** as a multiplier on anything except the union of files | §5 steps 3–4 |

Growth statement: adding a few dozen directories multiplies nothing except
the (already linear) file-scan and index terms — work is a function of the
union of the trees, not of N. The two manifests in memory at any moment are
for one directory at a time; the full index (O(F), ~60 B/file) is the only
per-run O(F)-memory structure. N does not affect restore, status, or prune
beyond the same F.

## 12. CLI surface

```
backupctl run    [--config FILE] [--wait SECONDS] [--verify-hash]
backupctl status [--config FILE]     # list_snapshots + snapshot_disk_usage per snapshot
backupctl restore SNAPSHOT_NAME DEST [--config FILE]
backupctl prune  [--keep K] [--config FILE]
```

- `status`: read-only; `snaputil.list_snapshots` + `snaputil.snapshot_disk_usage`.
- `restore`: reads the snapshot's index, maps each relpath with
  `snaputil.safe_snapshot_path` (`snaputil.py:54–63`) — the traversal guard —
  and copies files into `DEST/<dir-name>/<relpath>`; refuses a missing/invalid
  index with exit 3 (never guesses); copies files it can, reports the
  skipped ones, exit 1.
- Exit codes: 0 clean · 1 completed with skips · 2 lock busy · 3 fatal.

## 13. Testing plan (`test_backupctl.py`, patterns from `test_synccli.py`)

- scan/diff parity with `synccli` where behavior is shared (dotfile override
  gets its own test: a `.hidden/` dir must be included).
- publish atomicity: a stub run that dies between staging and rename leaves
  no `snap-*`; next run recovers (§8).
- corrupt-index recovery: truncate a published `index.json`, run again, assert
  full-copy + WARN + demotion rules fire as tabulated in §8.
- skipped-file behavior: delete a source file between listing and copy
  (monkeypatch the copy primitive), assert index/`files_skipped`/exit code (§8).
- lock: two sequential in-process runs; assert second `flock` fails fast (§4).
- retention: `keep=2`, five snapshots → newest two remain; newest never
  deleted (re-checks `snaputil.prune_snapshots`' slice guarantee).
- restore round-trip: backup, mutate source, restore to a third dir, compare
  bytes; restore of a `..`-bearing relpath is contained (exercises
  `safe_snapshot_path`).
- scale smoke: 2 000-file synthetic tree, assert run < a few seconds and index
  size ≈ 60 B/file (keeps §10's constants honest).

## 14. Open items

- Whether evals snapshot *sizes* (hardlink-unfriendly filesystems at the
  backup root) justify a `--no-hardlink` mode: default stays hardlink;
  fallback is already per-file automatic (§7d).
- Optional `--verify-hash` (§7) may graduate to default once the evals trees'
  edit patterns are known.

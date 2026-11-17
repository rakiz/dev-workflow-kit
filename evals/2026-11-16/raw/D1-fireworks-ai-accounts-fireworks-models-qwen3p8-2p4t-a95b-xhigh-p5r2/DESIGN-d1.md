# DESIGN-d1 — `backupctl`: snapshot backups for the `evals/` workflow

Status: design (no code yet). Deliverable per `BRIEF.md`.
Author artifacts: this file only; all claims below were checked against the code
in this directory and measured on this machine (Appendix A).

---

## 1. Scope and summary

`backupctl` backs up a configured set of directories (N — three today, a few
dozen over time) into **snapshots** under one backup root. A snapshot is a
complete, self-consistent, point-in-time copy of every configured directory,
visible under a final name only after it is complete, and immutable afterwards.

Core model in one paragraph: a single new module `backupctl.py` (plus
`test_backupctl.py`) lives beside `synccli.py` / `snaputil.py` and imports both
(same-directory import, exactly as `test_synccli.py:5` imports `synccli`). One
run = acquire an `flock` write lock on the backup root → sweep debris of dead
runs → scan sources with `synccli.build_manifest` → diff against the newest
published snapshot's manifest with `synccli.changed_files` → build the new
snapshot in a hidden staging directory (copy changed files with
`synccli.copy_file`, hard-link unchanged files from the previous snapshot) →
finalize the snapshot's own manifest listing **exactly what landed** → publish
the whole directory with one atomic `os.rename` → prune old snapshots
(rename-to-trash first, reader-claim aware) → rewrite a derived, never-trusted
`index.json` → release the lock and report. Readers (restore tooling, humans,
the next run) never interact with a writer at all: they only ever see published
snapshots, which are immutable, or nothing.

Everything the brief demands is answered in a dedicated section:
concurrency §6, crash/index recovery §7, vanishing sources §8, change-detection
granularity §9, retention §10, performance budget §11 (measured), scaling
bounds §12. Every departure from existing code behavior is named in §13.

Reference machine for all measurements: Apple M3 Max (Mac15,11), 36 GB RAM,
macOS, internal APFS SSD, Python 3.10.11. The existing suite passes here
(`python3 -m unittest`, 6 tests, OK). Assumption: the backup root is on a local
POSIX filesystem (flock, `os.link`, atomic same-fs `rename`); `flock` on NFS is
not trustworthy and network roots are out of scope (stated, not silently
assumed).

---

## 2. Grounding map

What `backupctl` reuses, verbatim, from this directory (file:function:lines —
each verified by reading and, where behavior mattered, by executing):

| Concern | Reused artifact | How it is used |
|---|---|---|
| Manifest filename/format | `synccli.py:7` `MANIFEST_NAME` (`.sync_manifest.json`), format `{relpath: {"size","mtime"}}` | Each snapshot carries its manifest under this name; a published snapshot is therefore a valid `synccli` destination and existing tooling can read it unchanged. Keys are `"<label>/<relpath>"` — opaque strings to `changed_files`, verified compatible. |
| Tree walking | `synccli.py:10-19` `scan_files` | Used as-is to enumerate source files (sorted, `synccli.py:19` → deterministic processing and report order) and for the pre-publish self-check of the staging tree (§5 step 8). Its dot-directory exclusion (`synccli.py:14`) is inherited as the default; verified: `.hidden/x.txt` is skipped, dot-*files* like `.dotfile` are kept. Config flag `include_dot_dirs` overrides (§9.4). |
| Per-file state | `synccli.py:22-25` `file_state` | The change-detection granularity (§9). Wrapped per-file in `try/except OSError` because `file_state` raises `FileNotFoundError` on a vanished file (verified) — see §8, override O6. |
| Manifest building | `synccli.py:28-33` `build_manifest` | Per-configured-directory scan of the source; also reused to **re-derive** a snapshot manifest from a snapshot tree during index recovery (§7.4-§7.5), filtering out `MANIFEST_NAME` itself (`scan_files` includes dot-files, so the manifest would otherwise list itself). |
| Change detection | `synccli.py:36-42` `changed_files` | Used as-is against the previous snapshot's manifest; `rel not in old_manifest` (`synccli.py:40`) makes files of newly-added config directories, and files skipped by an earlier run (§8), come back as "new" automatically. |
| Deletion detection | `synccli.py:45-59` `collect_stale` | `changed_files` ignores deletions (verified: old `{a,gone}` vs new `{a}` → `[]`). Deletions are computed as `collect_stale([(rel, rel in new_manifest) for rel in prev_manifest])` → verified returns `['gone']`. Deletions are report-only: a deleted file simply does not exist in the new snapshot. |
| Copying | `synccli.py:62-69` `copy_file` | The copy engine, with two named overrides: error handling (O1) and whole-file read (O5). Its `makedirs` (`synccli.py:64`) stays (cheap no-op once the staging skeleton is pre-created, §5 step 6). |
| Snapshot listing | `snaputil.py:8-20` `list_snapshots` | The authoritative snapshot list everywhere (previous-snapshot choice = `list_snapshots(root)[-1]`, retention, `list` command). Its prefix filter (`snaputil.py:18`, `startswith("snap-")`) is what makes staging (`.staging-*`) and trash (`.trash-*`) directories invisible to every existing code path — verified. Its `sorted` (`snaputil.py:20`) is chronological **iff** names are fixed-width → naming rule §3.2. |
| Pruning | `snaputil.py:23-36` `prune_snapshots` | Reused: listing (line 30), oldest-first doomed slice `names[:len(names)-keep]` (line 33), `shutil.rmtree` (line 35, applied to the trashed path). Overridden: in-place `rmtree` → rename-to-trash first (O7); `keep=0` deletes even the newest (verified, §10) → clamped (O8). |
| Sizes | `snaputil.py:39-51` `snapshot_disk_usage` | Per-snapshot **logical** size for `list`/`status`. Note (stated, not hidden): it counts hard-linked files at full size, so Σ over snapshots overstates physical usage; physical accounting uses run metadata (§12, disk row). |
| Path resolution | `snaputil.py:54-63` `safe_snapshot_path` | Base for reader/link path resolution — **hardened** (O9): its docstring claim "never points outside" (lines 58-60) is false as written; verified `safe_snapshot_path("/bk","snap-x","../../etc/passwd")` returns `/bk/snap-x/../../etc/passwd`, which normalizes to `/etc/passwd` (`os.path.normpath` at line 62 preserves *leading* `..` segments; it only collapses interior ones, e.g. `a/../../..` → `/bk`). |
| Age checks | `snaputil.py:66-73` `is_stale` | Secondary sanity check in debris sweeping (§7.2: a debris dir with mtime ≤ our lock-acquisition epoch provably predates this run) and snapshot ages in `status`. Primary debris detection is the lock, not mtime (§7.2 says why). |
| CLI shape | `synccli.py:90-99` / `snaputil.py:76-88` `main(argv=None)` | Same argparse + `main(argv)` + `sys.exit(main())` pattern. |
| Test style | `test_synccli.py` (stdlib `unittest`, `tempfile.mkdtemp` fixtures, run via `python3 -m unittest`) | `test_backupctl.py` mirrors it (§16). |

What is **replaced** rather than reused: `synccli.sync` (`synccli.py:72-87`) as
a whole. Its model — mutate one destination in place, then dump the full
pre-copy manifest non-atomically (lines 85-86) — cannot produce snapshots and
violates the brief's reader guarantees (a crash between truncate and `json.dump`
leaves a corrupt manifest; the dump lists files whose copy was silently skipped,
verified §8). `backupctl`'s run (§5) re-uses `sync`'s *constituents*
(`build_manifest` line 74 ordering — state is captured **before** copying;
`changed_files` line 80; the copy loop lines 83-84) inside a stage-and-publish
transaction. Each individual override is listed in §13.

Verified defects in existing behavior that the design must not inherit
(all reproduced on this machine; scripts in Appendix A):

1. `copy_file` swallows every `OSError` (`synccli.py:68-69`, comment claims
   "next pass will retry") **and** `sync` writes the full pre-copy manifest
   (`synccli.py:85-86`). Combined effect, verified: an unreadable file is
   listed as copied, appears in the destination manifest, is absent on disk,
   and the next `sync` returns `[]` — it is **never retried**. This is exactly
   the brief's "index that promises files the snapshot does not contain".
2. `safe_snapshot_path` leading-`..` escape (above).
3. `prune_snapshots(root, 0)` deletes **all** snapshots including the newest
   (verified: both test snapshots removed, `list_snapshots` → `[]`).
4. `file_state` raises `FileNotFoundError` on a vanished file → unguarded
   `build_manifest` (`synccli.py:32`) crashes the whole run.
5. Unpadded sequence numbers break chronological sort: verified
   `sorted([..."-99", ..."-100"])` puts `-100` **first**.
6. `sync`'s manifest load (`synccli.py:77-79`) is an unguarded `json.load`:
   one corrupt byte aborts the run with a traceback and no recovery.

---

## 3. Backup-root layout and naming

### 3.1 Layout

```
<backup_root>/
  lock                      # flock(2) write lock; the only writer gate
  index.json                # DERIVED catalog; never trusted (§7.5)
  claims/                   # reader claim files: <snapname>.<pid>.<rand8>
  .staging-<ts>-<pid>/      # the one in-flight run (invisible to snaputil.py:18)
  .trash-<snapname>/        # rename-to-trash awaiting rmtree (also invisible)
  snap-YYYYMMDD-HHMMSS-sss/ # published snapshots (§3.2)
    <label>/...             # one subtree per configured directory
    .sync_manifest.json     # MANIFEST_NAME (synccli.py:7), keys "<label>/<rel>"
    run.json                # run metadata (§5 step 9)
```

Staging and trash names deliberately start with `.`: `list_snapshots`
(`snaputil.py:18`) admits only `snap-` directories, so **every** existing
consumer (`prune_snapshots`, `snaputil.main`, our own previous-snapshot
lookup) is structurally incapable of seeing unpublished or doomed data.
Verified by reading the filter and by the naming test in Appendix A.

### 3.2 Snapshot names

`snap-YYYYMMDD-HHMMSS-sss`: UTC wall clock at publish time, sequence `sss` =
(number of existing snapshots with the same 15-char timestamp prefix) + 1,
zero-padded to exactly 3 digits, computed under the lock. Fixed width keeps
`sorted` (`snaputil.py:20`) = chronological — the padding is mandatory, not
cosmetic (defect 5 above: `-100` sorts before `-99`). Overflow (>999 runs in
one wall second) is unreachable under the lock (a run costs ≥ one scandir +
rename ≈ ≥ 1 ms, measured rename alone 141 µs, §11) but is handled anyway:
sleep to the next wall second and re-derive. UTC avoids DST ambiguity.
Limitation, stated: retention order is name order; if the wall clock jumps
backwards, name order can deviate from true age order — `run.json` records true
start/end epochs and `status` reports the anomaly; retention still never
 deletes the newest *name*, which is the just-published snapshot.

### 3.3 Labels

Each configured directory gets a label = its basename; collisions get
deterministic numeric suffixes (`-2`, `-3`, …) assigned after sorting config
paths, so labels are stable across runs and independent of config file order.
Labels are manifest-key prefixes (`"<label>/<rel>"`) and subtree names.

---

## 4. Invariants

Everything else in this document is machinery to maintain these:

- **I1 — one writer.** At most one run mutates the backup root at any instant
  (`flock` §6.1). Readers and writers never touch the same objects (I3).
- **I2 — atomic visibility.** A snapshot becomes visible only via one
  `os.rename` of its complete staging directory to its final name; the
  manifest and `run.json` are final *before* that rename. There is no instant
  at which a final name exists with incomplete content. (Rename is atomic for
  same-filesystem directories; staging lives under the backup root, so this is
  guaranteed by construction. Measured cost: 141 µs for a 20k-file directory.)
- **I3 — published snapshots are immutable.** No code path writes inside a
  published `snap-*` directory, ever (single sanctioned exception: §7.4 repair
  of an externally corrupted manifest, performed under the write lock).
  Changed files become *new inodes* in a *new* staging directory; unchanged
  files are hard-linked (never edited); pruning renames/deletes whole
  directories, never their contents.
- **I4 — the manifest lists exactly what is present.** The published manifest
  is built from files that actually landed in staging (§5 step 8, §8), and an
  optional pre-publish self-check re-scans staging with `scan_files`
  (`synccli.py:10`) and compares key sets; a mismatch aborts publication
  (nothing is renamed; staging is removed; exit 1).
- **I5 — debris never requires manual cleanup.** Anything a dead run left
  (`.staging-*`, `.trash-*`, dead claims) is provably dead once we hold the
  lock, and is swept at the start of every run (§7.2).
- **I6 — retention never removes the last usable snapshot.** `keep ≥ 1`
  (clamped, O8); the doomed slice is oldest-first only (`snaputil.py:33`);
  prune executes only *after* a successful publish, so the newest snapshot is
  complete by construction; claimed snapshots are skipped (§10).
- **I7 — vanishing sources are excluded and reported, identically for every
  trigger.** A file that cannot be read is absent from the snapshot *and* from
  its manifest, listed in `run.json`, and printed in the report — whether the
  scheduler or a human started the run (§8; one code path, no branching on
  trigger).
- **I8 — `index.json` is derived data.** No command's correctness depends on
  it; any corruption is discarded and re-derived from the tree (§7.5).

---

## 5. Run algorithm (`backupctl run`)

Inputs: config (§14). Notation: F = total files across configured dirs,
F_c = changed/new files, F_u = unchanged files, B_c = changed bytes.

1. **Lock.** `fd = os.open(root/"lock", O_RDWR|O_CREAT)`;
   `fcntl.flock(fd, LOCK_EX | LOCK_NB)`. On `BlockingIOError`: print
   `skipped: another run is in progress`, exit 0 (a backup *is* running — the
   desired end state holds). `--wait` uses blocking `LOCK_EX` instead.
   Rationale for `flock` over an `O_EXCL` pidfile: the kernel releases it when
   the process dies for **any** reason (SIGKILL, Ctrl-C, sleep-then-kill), so a
   crashed run can never lock out the next one — the brief's "next run must
   make progress without manual cleanup" with zero stale-lock logic.
2. **Sweep debris** (§7.2): `rmtree` every `.staging-*` and `.trash-*`; unlink
   claim files whose pid is dead. Report each swept name.
3. **Choose previous snapshot.** `prev = snaputil.list_snapshots(root)[-1]`
   (`snaputil.py:8-20`) or `None` (first run). Load `prev/.sync_manifest.json`
   with a guarded load (§7.4; on parse failure → re-derive from the prev
   snapshot tree, never abort).
4. **Scan sources.** For each configured dir, in sorted order:
   `build_manifest(dir)` (`synccli.py:28-33`) with the per-file guard (O6):
   a file that vanishes between `os.walk` and `file_state` is recorded as
   skipped (`reason=ENOENT`) instead of crashing the run. Merge into one dict
   under label prefixes. State is captured here, **before** any copy — the
   ordering `synccli.sync` already uses (`synccli.py:74`) — which makes the
   next run converge after torn reads (§8.3).
5. **Diff.** `to_copy = synccli.changed_files(prev_manifest, new_manifest)`
   (`synccli.py:36-42`);
   `deleted = synccli.collect_stale([(r, r in new_manifest) for r in prev_manifest])`
   (`synccli.py:45-59`, report-only); `F_u` = the rest. `--dry-run` prints
   counts/lists here and exits without writing — mirroring `sync`'s early
   return (`synccli.py:81-82`).
6. **Stage skeleton.** Create `.staging-<ts>-<pid>/` and pre-create every
   directory implied by `new_manifest` keys in one pass (O(#dirs) `makedirs`
   calls instead of one per file — measured worth ~70 µs/file at 20k files,
   §11). Pre-creation also removes the recursion cost inside `copy_file`'s
   `makedirs` (`synccli.py:64`), which remains as a cheap no-op.
7. **Populate.** In sorted key order (deterministic, from `scan_files`'s
   `sorted`, `synccli.py:19`):
   - unchanged keys: `os.link(safe_resolve(prev, key), staging/key)` —
     hard links, so unchanged data costs ~100 B of metadata per file
     (measured, §11), not a re-copy; every snapshot stays a *complete* tree,
     so readers never reconstruct across snapshots. Prev and staging share
     the backup-root filesystem by construction → `EXDEV` impossible; the
     code still falls back to copy on `OSError(EXDEV)` for safety.
     Resolution of `prev` paths goes through the hardened
     `safe_snapshot_path` (O9).
   - changed/new keys: `copy_file(src, staging/key)` (`synccli.py:62`) wrapped
     per O1/O5: `OSError` → record `(key, errno)` in `skipped`, **do not**
     add the key to the published manifest; success → `os.chmod(dst,
     src_mode & 0o7777)` (mode is not part of `file_state` — §9.3 — so it is
     fetched with one extra `stat` per *copied* file only, F_c × ~30 µs).
     Optional `--jobs W` runs this phase on a bounded `ThreadPoolExecutor`
     (both phases are GIL-releasing syscalls; measured 1.4× at W=8 for links,
     2.2× for small-file copies — §11; default 1 for determinism).
8. **Finalize inside staging.** Build `published_manifest` = `new_manifest`
   minus `skipped` keys (I4/I7); write it to
   `staging/.sync_manifest.json.tmp` then `os.rename` onto
   `MANIFEST_NAME` (`synccli.py:7`) — atomic even within staging; write
   `run.json` the same way: `{version, start, end, dirs: {label: srcpath},
   files_total/copied/linked/deleted, skipped: [{path, reason}],
   changed_bytes, prev_snapshot}`. Optional self-check: `scan_files(staging)`
   minus `{MANIFEST_NAME, "run.json"}` must equal `published_manifest` keys
   (I4); mismatch → rmtree staging, exit 1, report.
9. **Publish.** `os.rename(staging, root/snap-<ts>-<sss>)` (I2). From this
   instruction the snapshot exists, complete, or it never existed.
10. **Prune** (§10), under the same lock, only after a successful publish (I6).
11. **Rewrite `index.json`** (§7.5): tmp + `os.rename`. Derived from
    `list_snapshots` + each snapshot's `run.json`/manifest; O(S) small reads.
12. **Release + report.** Print: snapshot name; F_c copied / F_u linked /
    deletions; skipped list with reasons (truncated to 20 paths + count);
    swept debris; prune results including claim-skips; elapsed. Exit codes
    (identical for scheduler and human — one code path):
    `0` clean publish or lock-busy skip (message distinguishes);
    `2` published-with-skips (monitorable); `1` fatal, nothing published.

---

## 6. Concurrency

The brief's actors: scheduler-triggered runs, human-triggered runs, restores
(separate tooling reading snapshots), prunes. Full pairwise matrix — "no
combination may corrupt a snapshot or each other's work":

| Pair | Mechanism |
|---|---|
| run × run | `flock` (I1). Loser exits 0 "skipped" or queues (`--wait`). No shared mutable state beyond the lock. |
| run × restore-reader | Nothing to synchronize: the run writes only its own `.staging-*` (invisible, §3.1); the reader reads only published snapshots, which are immutable (I3) and appeared atomically (I2). The reader "never asks whether the run is finished" because unfinished work is unnameable. |
| run × manual prune | `backupctl prune` acquires the **same** `flock` → serialized with runs. |
| prune × restore-reader | Reader claims (§10.2) + rename-to-trash (O7) + POSIX semantics (§10.3). |
| prune × prune | Same `flock` → serialized. |
| reader × reader | Both read-only; immutable data (I3). |
| anything × crash | Kernel-released flock + sweep-under-lock (§7.2). |

### 6.1 Why flock, and its one assumption

`flock` is advisory — sufficient because *every* mutating path in this design
is `backupctl` itself (runs and prunes), and readers by contract (§15) take
claims rather than the write lock. Assumption stated: local POSIX filesystem
(flock over NFS is unreliable; out of scope, §1).

### 6.2 Why not a pidfile

`O_CREAT|O_EXCL` pidfiles need stale-detection (is that pid alive? pid reuse
races) — exactly the "manual cleanup / no progress" failure class the brief
forbids. `flock` dies with the process; nothing to detect. (Claims, §10.2,
*do* use pid liveness — acceptable there because a false "alive" only *skips*
a deletion, the conservative direction.)

---

## 7. Crash recovery

Death model per the brief: Ctrl-C, laptop sleep, SIGKILL — process-level death
at any instruction. (Page cache survives process death; the kernel completes
in-flight writes, so no `fsync` is needed for this model. Hard power loss is
out of scope; a `--durable` flag adding per-file `fsync` before publish is
specified as opt-in, cost = F extra syscalls, unmeasured.)

### 7.1 What a dead run can leave, exhaustively

Death before step 9's rename → at most: one `.staging-*` dir with partial
content and possibly a half-written `.sync_manifest.json.tmp`/`run.json.tmp`
inside; nothing else. Death after step 9 → a *complete* published snapshot
plus possibly: one `.trash-*` dir (mid-prune), a stale `index.json` (if death
hit between tmp write and rename — the tmp file, not `index.json`, is the
half-written one), dead claim files. There is **no** death point at which a
final `snap-*` name holds incomplete data (I2) or `index.json` is half-written
(atomic replace).

### 7.2 Sweep (step 2), and why the lock is the proof

While we hold the exclusive lock, no other *writer* exists (I1), and only
writers create `.staging-*`/`.trash-*`. Therefore **any** such directory
existing at step 2 was left by a dead run — no heuristics needed; `rmtree`
them. Claims are different: they are created by *readers* (§10.2), whose
liveness the lock does not track, so a claim is swept only when its pid fails
`os.kill(pid, 0)` (`ProcessLookupError` → dead; `PermissionError` → alive,
other user's process).
Belt-and-braces only: `snaputil.is_stale(dir, lock_acquisition_epoch)`
(`snaputil.py:66-73`) can additionally confirm mtime ≤ acquisition; it is not
the primary test because mtime alone cannot distinguish "dead" from "alive but
paused" — which is exactly why the lock, not the clock, decides.
Reported: every swept name ("recovered debris of interrupted run: …").

### 7.3 Discarded vs. re-derived vs. reported (the brief's exact question)

- **Discarded:** the entire staging directory of the dead run, including any
  half-written manifest inside it. Nothing is salvaged from staging and
  nothing is published from it.
- **Re-derived:** everything the new run needs, from the *sources* — the new
  run's `build_manifest` (§5 step 4) never reads staging; and the previous
  snapshot's manifest, if its load fails, from the previous snapshot's own
  tree (§7.4). `index.json` if corrupt, from the directory tree (§7.5).
- **Reported:** swept debris names; manifest/index re-derivations with reason;
  snapshots marked invalid (§7.5) if any.
- **Progress:** guaranteed with zero manual steps — flock released by the
  kernel (step 1 succeeds), debris swept (step 2), run proceeds normally.

### 7.4 Half-written manifest *inside a published* snapshot

Impossible via our own writes (finalized in staging pre-rename, §5 step 8),
but reachable via external damage (disk fault, editor, user `rm`). Detection:
the guarded load (§5 step 3) fails on parse, or the optional `verify` self-check
(`scan_files` vs manifest) mismatches. Recovery: re-derive from the snapshot
tree — `build_manifest(snap_dir)` (`synccli.py:28`) minus `MANIFEST_NAME` and
`run.json` (note: `scan_files` keeps dot-*files* — verified — so the filter is
mandatory, else the manifest lists itself), rewritten atomically inside the
snapshot. This is the single sanctioned exception to I3 (repair of external
damage, performed under the write lock). If the tree itself is unscannable,
the snapshot is marked `invalid` in `index.json`, excluded from restore
choices and from previous-snapshot selection (fall back to next-newest valid),
reported — and retention still never deletes the newest name (I6).

### 7.5 `index.json`: schema, non-trust, and the recovery procedure

Schema (derived catalog): `{version, generated, snapshots: [{name, files,
logical_bytes, changed_bytes, start, end, skipped, invalid}]}`.
**No command depends on it for correctness** — the tree is authoritative
everywhere (`list_snapshots`, `snaputil.py:8`). Readers of it (`status`,
external monitoring, restore tooling choosing a snapshot) apply, on *any*
disagreement with reality — `json.load` raising, missing file, or
`{e.name} ≠ set(list_snapshots(root))` — this fixed procedure:

1. **Discard** the whole file (never partially trusted).
2. **Re-derive**: snapshot list from `list_snapshots(root)` (`snaputil.py:8`);
   per-snapshot fields from each snapshot's `run.json` + manifest; any
   snapshot whose manifest fails the guarded load goes through §7.4 first
   (re-derive by tree scan) or is marked `invalid`.
3. **Rewrite** atomically (tmp + `os.rename`).
4. **Report**: `index.json discarded and re-derived: <reason>; N snapshots,
   M invalid`.

A run is *never* blocked by index corruption (worst case: `status` output was
stale until this procedure runs). The same procedure covers every corruption
cause — dead-run leftovers of a hypothetical non-atomic writer, filesystem
damage, or a user's editor — because the design makes cause irrelevant.

---

## 8. Vanishing / unreadable source files

The brief: a file can vanish between listing and copying, or be unreadable at
copy time; define snapshot content + report; identical for scheduler and human.

### 8.1 Behavior

- **Vanished between walk and stat** (`file_state` raises — verified
  `FileNotFoundError`): the guarded manifest build (O6) records
  `(path, ENOENT)` in `skipped`; the file gets no manifest entry.
- **Vanished or unreadable at copy time** (`copy_file`'s `OSError` path,
  `synccli.py:68-69`): override O1 records `(path, errno)` in `skipped`;
  the file is **excluded from the published manifest** (§5 step 8).
- **Snapshot content (I4/I7):** exactly the files that landed — every
  successfully copied or linked file, and nothing else. The manifest never
  promises a missing file.
- **Report:** `run.json.skipped` (durable) + printed summary with reasons
  (transient), exit code 2 (published-with-skips) so both a scheduler and a
  human see it through their normal channel.
- **Identical triggers:** there is one code path; nothing branches on who
  invoked the run. The only trigger-sensitive behavior in the whole tool is
  lock contention (§5 step 1), and even that is identical — `--wait` is a
  flag, not a role.

### 8.2 Retry semantics (fixing the verified "never retried" defect)

Because a skipped file has *no* entry in the published manifest, the next run's
`changed_files` sees it via `rel not in old_manifest` (`synccli.py:40`) and
copies it — automatic retry, converging as soon as the file is readable. This
inverts the verified `synccli` behavior (manifest lists it → state matches
forever → `copied2 == []`, Appendix A.2), which contradicts its own comment
"next pass will retry" (`synccli.py:69`).

### 8.3 Torn reads (file edited *during* its copy)

Manifest state is captured **before** copying (step 4 ordering = the ordering
`synccli.sync` already uses, `synccli.py:74`). If the source changes mid-copy,
the snapshot may hold torn bytes for that file, but its manifest holds the
*pre-copy* state → next run sees `old_manifest[rel] != state`
(`synccli.py:40`) → re-copies → converges. (Recording post-copy state instead
would make torn bytes permanent — the pre-copy choice is the safe direction.)
Each copied file gets one post-copy re-stat (F_c × ~30 µs); a state change
flags the file `unstable` in the report. Files *not* touched during the run are
consistent by the same token; the snapshot as a whole is a scan-time image,
the same consistency model `tar`/`rsync` provide without filesystem snapshots
— stated as a deliberate limit, not hidden.

---

## 9. Change detection: granularity and what it misses

### 9.1 Granularity

Per **file**, keyed by the pair `(size, mtime)` from `file_state`
(`synccli.py:22-25`, `st.st_size` + `st.st_mtime` as float seconds), compared
by dict equality in `changed_files` (`synccli.py:40`). Unchanged files are
hard-linked from the previous snapshot (step 7) — "recognized, not re-copied"
in both wall time (for byte-heavy files) and disk (§11.4).

### 9.2 What this granularity can miss (explicit, per the brief)

1. **Content rewrites preserving size AND mtime**: tools that restore
   timestamps (`touch -r`, `touch -d`, editors with preserve-mtime,
   `rsync -a` re-seeding a tree, some build systems). Undetectable by design
   at this granularity.
2. **Same-tick same-size writes** on coarse-mtime filesystems: APFS stores
   nanosecond timestamps (window ≈ 0), but a source on a 1 s-granularity
   volume (FAT/exFAT, some NFS) has a ≤ 1 s window where a same-size rewrite
   is invisible.
3. **Metadata-only changes**: `chmod`/`chown`/xattrs/ACLs are not in
   `file_state` → never trigger re-copy or re-link; a snapshot's mode for a
   file is the mode at its last *content* change (step 7's `os.chmod`).
4. **Whole subtrees**: anything under a dot-directory is invisible to
   `scan_files` (`synccli.py:14`, verified) — inherited default (§9.4).
5. **Symlink semantics**: `os.walk` does not follow directory symlinks; file
   symlinks are copied as the *target's bytes* (`copy_file` opens through the
   link); a broken symlink is an `OSError` → §8 skip. Snapshots contain
   regular files only — stated.

Optional hardening `--checksum`: for files whose `(size, mtime)` match, compare
content hashes (blake2b over 64 KB chunks). Catches classes 1-2. Cost, stated
as a formula: one full read of unchanged bytes per run ≈ B_u / 1.28 GB/s
(measured single-stream rate, §11) — for the 1.024 GB reference tree ≈ +0.8 s
per run plus page-cache pressure. Default off; the default misses are the
documented ones above.

### 9.3 Deletions

Not a "change" in `changed_files` (verified: it returns `[]` when a file
disappears) — computed separately via `collect_stale` (§2 map), report-only.
A file deleted at the source is simply absent from the new snapshot; old
snapshots keep it (that is what snapshots are for).

### 9.4 `include_dot_dirs` (default false)

Default inherits `scan_files` as-is (`synccli.py:13-14`). When true,
`backupctl` substitutes its own walk that does not filter `dirnames` — an
explicit, named override of `scan_files`'s line-14 filter, off by default so
existing behavior (and its tests, `test_synccli.py:17-18`) is untouched.

---

## 10. Retention

### 10.1 Policy

Default **keep = 10** newest snapshots (config `keep`), plus optional byte
budget `max_bytes` (default off). Executed at the end of every successful run
(step 10) and by `backupctl prune --keep K`, both under the write lock.
Order: oldest-first, exactly `prune_snapshots`' doomed-slice semantics
(`snaputil.py:33`: `names[:len(names)-keep]`). Byte budget: after the
count-based pass, while estimated physical usage (§12 disk row, derived from
`run.json` `changed_bytes` — O(S) reads, no tree walk) exceeds `max_bytes`,
delete one more oldest — never the newest name (loop stops at 1 remaining).

### 10.2 Never without a usable snapshot (I6), and reader safety

- `keep` is clamped to ≥ 1 (O8). Verified defect: `prune_snapshots(root, 0)`
  deletes *everything* including the newest (`snaputil.py:31-33` with
  `keep=0` → `doomed = names[:len(names)]`); `backupctl` rejects/clamps 0 and
  negatives before any deletion logic runs.
- Prune runs only after a successful publish (step 10) → the newest snapshot
  is complete by construction at every prune instant.
- **Claims**: a reader (restore) registers before first access:
  `os.makedirs(claims, exist_ok=True)` + `O_CREAT|O_EXCL` file
  `claims/<snapname>.<pid>.<rand8>` (snapshot names contain no dots, §3.2 →
  field parsing safe), removed in `finally`. Prune, per doomed candidate:
  any claim file for it whose pid is alive (`os.kill(pid, 0)`;
  `PermissionError` = alive) → **skip deletion this run**, report
  `skipped (in use)`. Dead-pid claims are swept (§7.2). Pid reuse can only
  cause a conservative extra skip (snapshot survives one more run); a stuck
  live reader can only pin its own snapshot — the rest still prune, and the
  report surfaces it.
- **Rename-to-trash, then delete** (O7): each doomed snapshot is first
  `os.rename`d to `.trash-<name>`, then `shutil.rmtree`d (same call as
  `snaputil.py:35`, applied to the trash path). Reason, named: in-place
  `rmtree` (`snaputil.py:35`) exposes a *half-deleted tree* to any concurrent
  path-walking reader; rename makes the snapshot disappear **atomically** —
  from `list_snapshots` instantly (prefix filter, `snaputil.py:18` ignores
  `.trash-*`, verified) and from the filesystem in one instruction. A crash
  between rename and rmtree leaves `.trash-*`, swept next run (I5).

### 10.3 What a reader sees if deletion wins the race anyway

A reader that missed the claim window (or crashed mid-read and restarted):

- Files it has already `open`ed stay readable to EOF — POSIX unlink keeps the
  inode alive until the last fd closes; hard links in *other* snapshots are
  unaffected regardless (each `rmtree` only unlinks that tree's dirents).
- Its next path-based `open` fails `ENOENT` — a clean, single-valued signal
  ("this snapshot was pruned"), never a half-deleted tree (rename-first).
  Contract (§15): treat as retriable — re-list (`list_snapshots`) and pick the
  newest valid snapshot, or fail cleanly if the config demands that exact one.

---

## 11. Performance budget for the initial full backup

### 11.1 Method

Measured, not guessed: a synthetic tree of **20,000 files × 50 KiB =
1.024 GB in 40 directories** (the brief's "~1 GB, tens of thousands of files")
was generated under a temp dir on this machine's APFS volume, and the existing
engine was run on it — `synccli.sync(src, fresh_dst)` is literally the
full-copy path `backupctl`'s first run uses (§2). Each measurement was taken
twice (once in a burst state right after generating 1 GB, once after a 15 s
cache-settling sleep); both numbers are reported, and the budget uses the
worse one. Raw outputs: Appendix A.3-A.5.

### 11.2 Measured constants (reference machine, Python 3.10.11, APFS)

| Constant | Value | Source |
|---|---|---|
| Scan+stat+dict per file (`build_manifest`) | 25–33 µs | 0.50–0.67 s / 20k files |
| Copy per-file overhead (open/read/write/close ×2, incl. `copy_file` makedirs) | ~290–335 µs | 20k×1 KiB sync 5.77–6.69 s minus byte time; cross-checked by full-sync decomposition |
| Byte throughput, single stream, chunked 64 KB | 1.28 GB/s | one 524 MB file, 0.41 s |
| Byte throughput, whole-read (`copy_file` as-is, `synccli.py:67`) | 1.41 GB/s | same file, 0.37 s |
| `os.link` per link | 326 µs (dirs pre-created); 396–475 µs (with per-file makedirs) | three independent 20k-link passes |
| Hard-link metadata on disk | ~100 B/link | settled `statvfs` delta: 2.0 MB / 20k links (a burst-state reading of 37 KB/link was flush/Spotlight noise — hard links allocate no data blocks; discarded) |
| `changed_files` compare, 20k×20k | 2 ms | direct timing |
| Manifest JSON size | 65 B/entry compact; 84 B/entry `indent=2` (the format `synccli.py:86` writes) | `json.dumps` lengths; on-disk manifest 1.67 MB / 1.29 MB |
| Manifest write (20k entries) | 38–55 ms | direct timing |
| Manifest RAM | ~461 B/entry (9.2 MB / 20k) | `ru_maxrss` delta across `build_manifest` (peak-based; treated as upper estimate) |
| Publish rename, 20k-file dir | 141 µs | `os.rename` timing |
| Thread pool (W=8) speedup | links 1.4× (229 µs eff.), small-file copies 2.2× (132 µs/file) | `ThreadPoolExecutor` passes |

### 11.3 Budget and where the number comes from

Decomposition (all constants from §11.2):

```
T_first(F, B) = F·33µs (scan)          + F·300µs (per-file copy)
              + B / 1.28 GB/s (bytes)  + F·65B / 1.28 GB/s (manifest write)
T_first(20k, 1.024 GB) = 0.66 + 6.0 + 0.8 + 0.1 ≈ 7.6 s
```

Direct end-to-end measurement of the same operation via `synccli.sync`:
**7.74 s** (burst) and **10.34 s** (settled) — the derivation and the
measurement agree within run-to-run variance (~±30%, cache/background state).

> **Budget B1: the initial full backup of a 1.024 GB / 20k-file tree completes
> in ≤ 30 s on the reference machine.** That is ≈3× the worst measured run
> (10.34 s); the headroom covers cold-cache read-back of 1 GB (~+1 s at
> internal-SSD sequential rates), background interference (the burst/settled
> spread demonstrates it), and first-run directory-skeleton creation.
> Re-derive on any other machine from the formula above, not from the 30 s.

Note what dominates: at 50 KiB files, ~80% of the time is per-file overhead
(20k × ~330 µs ≈ 6.6 s) vs ~0.8 s of byte movement — the budget scales with
**file count** first, bytes second. If steady-state time ever matters more
than determinism, `--jobs 8` is the measured lever (1.4–2.2×, §11.2); the
default stays single-threaded because the budget is met without it.

### 11.4 Steady-state (incremental) budget

Measured full simulation of one `backupctl` run at 1% churn (200 of 20k files
rewritten; scan → diff → 19,800 links + 200 copies → manifest):
**8.33–10.18 s total** (scan 0.50–0.67 s; compare 2 ms; links 7.74–9.40 s;
copies 0.05 s; manifest 0.04–0.05 s).

```
T_steady(F, F_c, b̄) = F·33µs + F_c·(300µs + b̄/1.28 GB/s)
                    + (F−F_c)·330µs (links, skeleton pre-created)
                    + F·65B / 1.28 GB/s
T_steady(20k, 200, 50 KiB) ≈ 0.66 + 0.07 + 6.5 + 0.1 ≈ 7.3 s   (measured 8.3–10.2 s)
```

> **Budget B2: any steady-state run over the same tree ≤ 30 s** (same
> envelope and same derivation logic as B1; ≈3× the worst measured, 10.18 s).

Honest cost/benefit of incremental at this granularity, with numbers:
on this machine a link (~330 µs) ≈ a small-file copy (~300 µs), so at 50 KiB
files the *wall-time* win is modest (~1.05–1.3×); the *disk* win is ~76×
(§12: ~13.5 MB/run vs 1.024 GB/run). For ≥1 MiB files the time win becomes
real: copying 10 MiB ≈ 8 ms vs a 0.33 ms link (~24×). The brief's
"recognize unchanged files instead of copying them again" is satisfied on the
axis that compounds — disk — and on time for byte-heavy trees.

---

## 12. Scaling bounds (N dirs, F files, B bytes)

Notation: N = configured dirs (3 → a few dozen); F = ΣF_i files over all
configured dirs; B = ΣB_i bytes; F_c/F_u changed/unchanged per run;
S = published snapshots; K = keep (default 10); R = concurrent readers;
W = workers. Constants from §11.2. Every row is a number, a formula, or a
measured constant — per the brief, no unbounded "stays flat".

| Quantity | Bound | Basis |
|---|---|---|
| Snapshots produced per run | **exactly 1, independent of N** (all dirs land in one snapshot under per-dir labels, §3.3) | design |
| Per-run wall time | F·33µs + F_c·(300µs + b̄/1.28GB/s) + F_u·330µs + F·65B/1.28GB/s — **linear in F and B, no N² or F² term**; N enters only through ΣF_i and O(N) label/config work (≤ ~10 µs per dir) | §11.3-11.4 formulas, measured |
| Per-run peak RSS | **461 B × F** (manifest dicts) + 64 KB × W (chunk buffers, O5) + O(S·~80 B) name lists + O(R) claims. 20k files → ~9.2 MB (measured); 100k files → ~46 MB; **independent of B** (chunked copy), **independent of N, S, K** except the tiny listed terms | measured 461 B/entry; §12 memory row of `ru_maxrss` |
| Per-run disk growth | **B_c + 100 B × F_u** (link metadata, measured) **+ 65 B × F** (compact manifest) + ~0.5 KB (`run.json`). 1% churn on reference tree: ~10.2 MB + 2.0 MB + 1.3 MB ≈ **~13.5 MB/run vs 1.024 GB/run for naive full copies (~76× less)** | measured 100 B/link, 65 B/entry |
| Total disk under retention | ≤ B_first + Σ_{runs in window} B_c + K·F·(100 B + 65 B) + K·0.5 KB. Reference tree, K=10: ≤ B_first + ΣB_c + **~33 MB** metadata. Hard links make shared versions cost once (Σ over `snapshot_disk_usage` would overcount — §2 map) | link accounting, measured |
| `index.json` size | ~120 B × S ≤ 120 B × (K + in-flight) — **O(S), independent of N and F** | schema §7.5 |
| Per-snapshot manifest size | 65 B × F (compact, O10) — 1.29 MB at 20k (measured); grows with F only | measured |
| Writer count | **1, flat** — independent of trigger rate (flock, I1) | design |
| Staging dirs | **≤ 1 at any instant** (I1); debris bounded by crashes since last run, swept to 0 each run (I5) | design |
| Trash dirs | ≤ 1 per prune step mid-deletion; ≤ S worst case after a crash mid-prune; swept to 0 next run | §10.2, §7.2 |
| Claims | O(R) files × ~40 B; dead ones swept each run | §10.2 |
| Prune memory/time | O(S) names (~30 B each) + O(R) claim checks + rmtree of doomed bytes | `snaputil.py:30-35` shapes |
| S over time | +1 per successful run, bounded at **K** by retention (+ transient trash) | §10 |
| Lock file | 1, O(1) | design |

N-specific statement (the brief's "three directories today, a few dozen over
time"): nothing structural changes with N — one run still produces one
snapshot; a newly added directory's files all miss `prev_manifest` keys and
are copied by `changed_files`'s `rel not in old_manifest` arm (`synccli.py:40`)
— a per-directory first full backup, bounded by that directory's own F_i/B_i;
a removed directory's keys surface via `collect_stale` as reported deletions.
All per-run work, memory, and disk above are linear in ΣF_i and ΣB_i with
measured constants; N itself contributes only O(N) label strings and config
entries (bytes, not seconds).

---

## 13. Overrides of existing behavior (explicit, per the brief)

Each entry: what is overridden, where it lives, what `backupctl` does instead,
why. Reuses are in §2; this table is the complement.

| # | Overridden behavior | Location | Replacement | Reason |
|---|---|---|---|---|
| O1 | `except OSError: pass` — copy errors silently swallowed | `synccli.py:68-69` | Wrapper records `(path, errno)` in `skipped`, excludes the key from the published manifest, run continues, exit 2 | Verified: silence + full-manifest dump ⇒ index promises missing files and the file is *never retried* (contradicts the comment at line 69). Brief forbids both. |
| O2 | `sync` dumps the **full pre-copy** manifest as the destination index | `synccli.py:85-86` | Published manifest = `new_manifest` minus `skipped` (§5 step 8) | I4: manifest == contents, exactly. |
| O3 | Non-atomic manifest write (`open(path,"w")` + `json.dump` in place) | `synccli.py:85-86` | All index/manifest writes are tmp-file + `os.rename`; the snapshot's manifest is final *before* the whole-dir publish rename | A crash between truncate and dump leaves a corrupt index (brief's recovery scenario); atomic replace makes it unreachable via our writes, and §7.5 covers all other causes. |
| O4 | Unguarded `json.load` of the previous manifest | `synccli.py:77-79` | Guarded load → on any parse error run the §7.4 re-derivation, never abort | One corrupt byte must not block a run (brief: next run makes progress). |
| O5 | Whole-file read `fdst.write(fsrc.read())` | `synccli.py:67` | Chunked copy (`shutil.copyfileobj`, 64 KB) in the wrapper | Memory bound must be O(chunk), not O(max file size): measured cost is 1.28 vs 1.41 GB/s (−9%) — cheap price for an RSS bound independent of B (§12). |
| O6 | `build_manifest` propagates `file_state` exceptions | `synccli.py:28-33` (call at 32; `file_state` 22-25) | Per-file `try/except OSError` → record skip (ENOENT etc.), continue | Verified: `file_state` raises `FileNotFoundError`; a file vanishing mid-scan would crash the run — brief requires record-and-report instead. |
| O7 | `prune_snapshots` deletes in place (`shutil.rmtree` on the live path) | `snaputil.py:34-35` | Rename to `.trash-<name>` first, then the same `shutil.rmtree` on the trash path | In-place rmtree shows concurrent readers a half-deleted tree; rename is atomic disappearance (and `.trash-*` is invisible to `list_snapshots`' filter, `snaputil.py:18`). |
| O8 | `prune_snapshots(root, 0)` deletes **every** snapshot, newest included | `snaputil.py:31-33` (verified) | `keep` clamped to ≥ 1; prune only after successful publish | Brief: deletion must never leave the user without a usable snapshot (I6). |
| O9 | `safe_snapshot_path` trusts `normpath` to remove `..` — docstring claims the result "never points outside" | `snaputil.py:54-63` (claim at 58-60, `normpath` at 62) | Harden: reject absolute `rel_path`; reject any post-`normpath` leading `..`; after join verify containment with `os.path.commonpath` | Verified escape: `"../../etc/passwd"` → `/bk/snap-x/../../etc/passwd` → normalizes to `/etc/passwd`. `normpath` collapses only *interior* `..`. Used for every reader/link resolution. |
| O10 | Manifest dumped with `indent=2` | `synccli.py:86` | Compact `separators=(",",":")` | Measured 84 → 65 B/entry (−23%); the manifest is machine-read; size bound K·F·65 B instead of K·F·84 B (§12). |
| O11 | Snapshot naming example uses a 2-digit sequence (`snap-20261112-150000-07`) | `snaputil.py:11-13` (docstring) | Fixed-width 3-digit `sss` + overflow rule (§3.2) | Verified: unpadded, `-100` sorts before `-99` — `list_snapshots`' `sorted` (`snaputil.py:20`) would break chronology, and with it retention order. |
| O12 | `scan_files` skips dot-directories | `synccli.py:14` | **Inherited by default** (documented); `include_dot_dirs=true` substitutes a walk without the filter (§9.4) | Whole subtrees (e.g. `.git`) are invisible to backup — must be a stated, switchable decision, not a surprise. Default keeps existing behavior and its test (`test_synccli.py:17-18`) green. |

`synccli.sync` itself (`synccli.py:72-87`) is not called by `backupctl`: its
in-place mutation model is replaced by the stage-and-publish run (§5), which
reuses its constituent functions and its state-before-copy ordering (line 74).
This is the one whole-function replacement; everything else above is a
localized, named override.

---

## 14. CLI and configuration

Mirrors `synccli.main` / `snaputil.main` (`synccli.py:90-99`,
`snaputil.py:76-88`): argparse, `main(argv=None)`, `sys.exit(main())`.

```
backupctl --config backupctl.json run [--wait] [--dry-run] [--jobs W]
                                      [--checksum] [--durable]
backupctl --config backupctl.json list          # snaputil.list_snapshots + snapshot_disk_usage per snapshot
backupctl --config backupctl.json status        # derived index (§7.5), physical estimate, claims, debris, anomalies
backupctl --config backupctl.json prune --keep K
backupctl --config backupctl.json verify [SNAP] # I4 self-check: scan_files vs manifest (§7.4)
```

`backupctl.json`:

```json
{
  "backup_root": "/path/to/backups",
  "dirs": ["/repo/evals/results", "/repo/evals/logs", "/repo/evals/artifacts"],
  "keep": 10,
  "max_bytes": null,
  "include_dot_dirs": false
}
```

Missing/unreadable configured dir → fatal (exit 1, nothing published, message
naming the dir). Missing backup root → created on first run. `--dry-run`
reports the plan and exits before staging (§5 step 5), mirroring
`synccli.py:81-82`.

---

## 15. Reader (restore) contract

Restore is separate tooling; `backupctl` exposes the primitives it must use
(importable from `backupctl.py`):

1. `claim = acquire_claim(backup_root, snap_name)` before first access
   (`O_CREAT|O_EXCL` under `claims/`, §10.2); `release_claim(claim)` in
   `finally`.
2. `manifest = read_snapshot_manifest(backup_root, snap_name)` — guarded load
   with the §7.4/§7.5 recovery; raises `SnapshotInvalid` for snapshots marked
   invalid, so restore never half-trusts a damaged tree.
3. `path = resolve(backup_root, snap_name, rel)` — hardened
   `safe_snapshot_path` (O9): rejects absolute and `..`-leading keys,
   verifies containment.
4. Copy out; treat `ENOENT` on any open as "snapshot pruned mid-read"
   (§10.3): abort cleanly, re-list, retry with the newest valid snapshot if
   the caller allows substitution.

Guarantees restore relies on, each traceable: it reads a complete image
(I2), nobody mutates it underfoot (I3), the manifest matches the tree (I4),
deletion is atomic and claim-respecting (§10.2), and already-opened files stay
readable even if deletion wins (§10.3, POSIX fd semantics).

---

## 16. Test plan

`test_backupctl.py`, stdlib `unittest`, `tempfile.mkdtemp` fixtures, run via
`python3 -m unittest` — same shape as `test_synccli.py` (import at line 5,
fixtures at lines 9-15). Existing suite must stay green untouched.

1. **Publication atomicity**: reader loop polling `list_snapshots` during a
   run never observes a name whose manifest disagrees with `scan_files`
   (I2/I4); `.staging-*` never appears in `list_snapshots` (filter,
   `snaputil.py:18`).
2. **Crash recovery**: spawn a run in a subprocess, `SIGKILL` mid-copy;
   assert: no new `snap-*`; `.staging-*` exists; next run sweeps it,
   publishes successfully, exit 0, report names the debris (I5, §7.2-7.3).
   Repeat killing after publish, mid-prune → `.trash-*` swept.
3. **Corrupt index**: truncate `index.json` to garbage / delete it / kill a
   run mid-rewrite → `status` and next run re-derive, report, and succeed
   (§7.5); corrupt one snapshot manifest → re-derived by tree scan, excludes
   `MANIFEST_NAME` itself (§7.4).
4. **Vanishing/unreadable sources**: chmod-000 file and unlink-after-scan
   (hook between manifest and copy) → snapshot excludes them, manifest
   excludes them (I4), report lists them, exit 2; next run retries and
   succeeds after chmod back (O1/O2, §8.2 — the regression `synccli` fails,
   Appendix A.2).
5. **Concurrency**: two runs started simultaneously → exactly one publishes,
   other exits 0 "skipped"; with `--wait` → both publish, names ordered,
   second links from first (I1). Reader holding a claim + prune → snapshot
   skipped, reported (§10.2); dead-pid claim → swept.
6. **Retention**: keep=0/negative clamped to 1 (O8); newest never deleted
   (I6); byte budget stops at 1; rename-to-trash ordering observable.
7. **Path safety**: manifest keys `../x`, `a/../../..`, `/etc/passwd` →
   rejected by `resolve` (O9; the raw `safe_snapshot_path` escape,
   Appendix A.1, as the negative control).
8. **Change detection**: same-size same-mtime rewrite is NOT re-copied —
   asserted as the *documented limit* (§9.2.1), pinning the granularity;
   chmod-only change not re-copied (§9.2.3); `--checksum` catches both.
9. **Dedup**: unchanged file's `st_ino` identical across consecutive
   snapshots; deleting the older snapshot leaves the newer intact (hard-link
   semantics, §10.3).
10. **Determinism**: two identical runs over an identical tree produce
    identical manifests and identical report order (`scan_files` sort,
    `synccli.py:19`).

---

## Appendix A — verification and measurement record

Environment: Apple M3 Max (Mac15,11), 36 GB RAM, macOS APFS internal SSD
(volume `/System/Volumes/Data`, 383 GiB free at test time), Python 3.10.11.
Existing suite: `python3 -m unittest` → 6 tests, OK. All experiments ran
against this directory's `synccli.py`/`snaputil.py` unmodified, with scratch
trees under the system temp dir (same volume). Scratch data deleted after
measurement.

### A.1 `safe_snapshot_path` escape (grounds O9)

```
safe_snapshot_path("/bk", "snap-x", "../../etc/passwd")
  -> "/bk/snap-x/../../etc/passwd"   (os.path.normpath -> "/etc/passwd")
normpath("../../etc/passwd") == "../../etc/passwd"    # leading .. preserved
safe_snapshot_path("/bk", "snap-x", "a/../../..") -> "/bk/snap-x/../.."  (-> "/bk")
```

### A.2 Silent skip + false retry claim (grounds O1/O2, §8.2)

src with `good.txt` (readable) and `bad.txt` (chmod 000), `synccli.sync`:

```
copied1: ['bad.txt', 'good.txt']        # reported as copied
manifest keys: ['bad.txt', 'good.txt']  # index promises bad.txt
bad.txt exists in dst: False            # but it is not there
copied2 (second sync): []               # never retried — comment at synccli.py:69 is false
```

### A.3 Full-backup measurement (grounds §11, budget B1)

Tree: 20,000 files × 50 KiB (1.024 GB), 40 dirs; generation 2.7 s.

```
build_manifest:      0.67 s (burst) / 0.50 s (settled)   -> 25–33 µs/file
RSS delta:           9.2 MB -> ~461 B/entry
manifest JSON:       indent=2: 1.67 MB (84 B/entry); compact: 1.29 MB (65 B/entry)
synccli.sync FULL:   7.74 s (burst) / 10.34 s (settled)  -> 99–132 MB/s effective
sync no-change pass: 0.67 s
```

### A.4 Copy/link constants (grounds §11.2, §12)

```
single 524 MB file: copy_file whole-read 0.37 s (1.41 GB/s); chunked 64 KB 0.41 s (1.28 GB/s)
20k × 1 KiB sync:   6.69 s (burst) / 5.77 s (settled) -> ~290–335 µs per-file overhead
raw os.link ×20k (dirs pre-made): 6.52 s -> 326 µs/link
os.link ×20k incl. per-file makedirs: 7.93–9.40 s -> 396–475 µs/link
link disk metadata (settled statvfs): 2.0 MB / 20k = ~100 B/link
  (burst-state reading 37 KB/link = flush/Spotlight noise; links allocate no data blocks — discarded)
threaded (8 workers): links 1.4× (229 µs eff.); small-file copies 2.2× (132 µs/file)
publish rename (20k-file dir): 141 µs
```

### A.5 Steady-state simulation (grounds §11.4, budget B2)

200 of 20k files rewritten (1% churn), then scan → `changed_files` →
19,800 `os.link` + 200 `copy_file` → compact manifest (tmp+rename):

```
changed=200 (as injected); scan 0.50–0.67 s; compare 0.002 s;
links 7.74–9.40 s; copies 0.05 s; manifest 0.038–0.054 s;
TOTAL 8.33 s (settled) – 10.18 s (burst)
deletions via collect_stale on (rel, rel in new): [] (none injected; detector
  separately verified: old {a,gone} vs new {a} -> ['gone'])
```

### A.6 Other behavior verifications cited in the text

```
prune_snapshots(root, 0) -> deleted both snapshots incl. newest; list -> []   (O8)
file_state("/nonexistent") -> FileNotFoundError                               (O6)
sorted(["snap-...-99", "snap-...-100"]) -> ["-100", "-99"]                    (O11)
scan_files: dot-dirs skipped, dot-files kept (['.dotfile', 'vis/v.txt'])      (§9.4, §7.4)
changed_files ignores deletions (old {a,gone}, new {a} -> [])                 (§9.3)
os.link across temp dirs on this volume: OK, identical st_ino                 (§5 step 7)
```

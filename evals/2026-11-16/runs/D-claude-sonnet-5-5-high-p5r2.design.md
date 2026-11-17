# DESIGN — `backupctl` (fixture D1)

Status: design only. No `backupctl` code exists yet. Every claim about existing
code below was checked by running it (probe results in §1.2), and every
performance number was measured on this machine (§10, Appendix A).

Measurement host: Apple M3 Max, macOS 24.6 (Darwin), APFS, Python 3.10.11,
warm page cache. Hard-link and file-create costs on other filesystems are
**not** measured here and are not claimed.

---

## 0. Decisions in one page

| Question | Decision |
|---|---|
| Unit of a snapshot | One snapshot **per configured directory per run**: `<root>/<dirkey>/snap-YYYYMMDD-HHMMSS-NN/`. No cross-directory atomicity is offered (not required by the brief). |
| Snapshot shape | A **complete plain tree** (restore can `cp -a` it) plus `.backupctl/index.jsonl`. Unchanged files are **hard links** into the previous snapshot; changed files are fresh copies. |
| Publication | Build in `<root>/<dirkey>/.staging-<runid>/`, fsync, then one atomic `os.rename` to `snap-…`. Readers only ever look at `snap-*`; nothing named `snap-*` is ever incomplete. |
| Writer concurrency | Per-directory `flock(LOCK_EX)` on `<root>/<dirkey>/.lock`. Kernel releases it on death, so there is no stale-lock cleanup. |
| Reader concurrency | Committed trees are immutable. Optional shared-flock **leases** for readers; deletion skips leased snapshots and is rename-first, so a half-deleted snapshot is never listed. |
| Crash recovery | Any `.staging-*`, `.trash/*` found under the lock is dead and deleted. Corrupt index ⇒ quarantine that snapshot, re-derive hashes from its tree, re-validate against the live source, report `RECOVERED`. |
| Missing/unreadable files | Omitted from the snapshot, listed in the index and report. Vanished ⇒ `complete`, exit 0. Unreadable / unstable ⇒ `partial`, exit 3. Identical for scheduler and person. |
| "Unchanged" | `(type, size, mtime_ns, ctime_ns, mode)` equal **and** not "racy" (§8). Racy files are decided by sha256. Weekly `--deep` decides everything by sha256. |
| Retention | Keep newest 8, plus newest complete per UTC day for 7 days, plus newest complete per ISO week for 4 weeks ⇒ ≤ 19 snapshots/dir; never delete the newest complete one. |
| Initial full backup budget | **≤ 30 s** for 30,000 files / 1 GiB (measured 7.3 s with 4 worker threads, 14–17.7 s single-threaded; §10). |

---

## 1. Grounding in the existing code

### 1.1 What is in this directory (verified)

`python3 -m unittest` runs **6** tests, all pass (`TestScanFiles` 1,
`TestCollectStale` 3, `TestSync` 2; `test_synccli.py:8-51`). They cover the
happy path only: no vanished file, no unreadable file, no corrupt manifest, no
deletion, no concurrency. They must stay green; `backupctl` adds its own tests
(§14).

### 1.2 Behaviours of the existing code that the design depends on

Each row was reproduced with a throw-away probe against the code in this
directory (probe script kept outside the repo; one-liners in Appendix B).

| # | Existing code | Observed behaviour | Consequence for `backupctl` |
|---|---|---|---|
| P1 | `synccli.scan_files` `synccli.py:10-19`, line 14 | Prunes **every directory whose name starts with `.`** (`.hid/h` is missing from the result) but keeps dot-*files* (`.dot` present). Directory symlinks (`lnk -> real/`) land in `dirnames`, are not followed, and are silently absent. Empty directories are absent (only filenames are returned). | A backup that silently skips `.git`, `.cache`, dir-symlinks and empty dirs is a silent-loss bug. Overridden (§1.3). |
| P2 | `scan_files` line 13: `os.walk(root)` with default `onerror=None` | A directory with mode 000 is skipped **without any signal** (`noperm/p` absent, no exception). | Unlistable directory must be a reported `unreadable` skip. Overridden. |
| P3 | `synccli.file_state` `synccli.py:22-25` | `os.stat` (follows symlinks) ⇒ a dangling symlink makes `build_manifest` (`:28-33`) raise `FileNotFoundError`; likewise a file deleted between `scan_files` and `file_state` kills the whole run (reproduced by deleting the file inside a wrapped `file_state`). State is `size` + float `mtime` only (no ctime, no mode, float seconds). | Vanish between list and stat must be a per-file event, not a crash. Overridden (`lstat`, ns ints, ctime). |
| P4 | `synccli.copy_file` `synccli.py:62-69` | `except OSError: pass` with the comment "next pass will retry". `sync()` (`:85-86`) then writes the manifest from `src_manifest`, i.e. **including the file that failed**. Reproduced: a mode-000 source file → `sync()` returns `['secret']`, `dst/secret` does not exist, manifest lists `secret`, re-run copies `[]`. The retry the comment promises never happens. | The central correctness bug for a backup tool: a manifest that promises a file the copy does not contain. Overridden (§7). |
| P5 | `copy_file` lines 66-67: `fdst.write(fsrc.read())` | Whole file read into memory; destination opened `"wb"` in place (a mid-write failure leaves a truncated file at the final path). | Memory = largest file; non-atomic. Overridden with chunked copy into staging. |
| P6 | `synccli.sync` `synccli.py:85-86` | Manifest written with `open(...,"w")` + `json.dump` straight over the old one. A truncated manifest makes the **next** `sync()` die in `json.load` (`:77-79`) with `JSONDecodeError` — reproduced. The run is wedged until a human deletes the file. | Index must be written once, fsynced, and checksummed, and published only by rename. Overridden (§3, §6). |
| P7 | `sync()` `:80-84` | Never deletes: after deleting `a` in the source, `sync()` returns `[]` and `dst/a` remains. | In-place sync semantics cannot give point-in-time images. Overridden: every snapshot is built from an empty staging tree. |
| P8 | `synccli.changed_files` `synccli.py:36-42` | Pure dict-equality over `{relpath: state}`; works unchanged with any state dict. Same-size edit with preserved mtime (`os.utime` back) is **not** detected (reproduced: `sync()` → `[]` although content changed; ctime did change). | **Reused as-is** as the stat-comparison core, fed with a richer state (adds ctime). Granularity limit stated in §8. |
| P9 | `synccli.main` `synccli.py:90-99` | Returns 0 whatever happened. | `backupctl` has a defined exit-code contract (§12). |
| P10 | `synccli.collect_stale` `synccli.py:45-59` | Pure helper, correct, **not called** by `sync()`. | Not used. Not cited as grounding. |

`snaputil.py`:

| # | Existing code | Observed behaviour | Consequence |
|---|---|---|---|
| S1 | `list_snapshots` `snaputil.py:8-20` | Returns every directory named `snap-*` sorted **by name**. Junk such as `snap-tmp-partial` is listed. Sort is lexicographic: with a 3-digit seq, `…-100` sorts before `…-99` (reproduced). Raises if `backup_root` is missing. | **Reused** as the single listing primitive. Safe because everything non-final (`.staging-*`, `.trash/`, `.quarantine/`, `.leases/`) lives under names it ignores. `backupctl` filters its result through `^snap-\d{8}-\d{6}-\d{2}$` and generates names whose lexicographic order equals commit order (§2). |
| S2 | `prune_snapshots` `snaputil.py:23-36` | Count-only. `keep=0` and `keep=-1` both delete **all** snapshots including the newest (reproduced), contradicting its own docstring (`:26-27`). `shutil.rmtree` in place (`:35`) leaves a half-deleted `snap-*` visible and listable if it dies mid-way. Ignores completeness. | **Not used.** Replaced by `backupctl.retention` (§9). Companion one-line fix in `snaputil.py`: `if keep < 1: raise ValueError` so the CLI at `:77-84` cannot wipe a root. |
| S3 | `snapshot_disk_usage` `snaputil.py:39-51` | `os.stat` at `:50` follows symlinks: a dangling symlink in a snapshot raises `FileNotFoundError` (reproduced). Counts a hard-linked file once per snapshot, so it is **logical** size, not disk cost. Skips symlinked dirs. | Not used for anything correctness-related. `backupctl` computes `logical_bytes` (lstat) and `unique_bytes` (dedupe on `(st_dev, st_ino)`) itself. |
| S4 | `safe_snapshot_path` `snaputil.py:54-63` | **Does not do what its docstring says.** `normpath("../../etc/passwd")` keeps leading `..`; `safe_snapshot_path("/b","snap-1","../../etc/passwd")` → `/b/snap-1/../../etc/passwd`; an absolute `rel_path` replaces the join entirely (`"/etc/passwd"` → `/etc/passwd`). Reproduced. | **Reused only behind a guard**: `backupctl.safe_rel()` rejects absolute paths, any `..` segment, NUL, and empty paths *before* calling `safe_snapshot_path`, then asserts `os.path.commonpath([snap_dir, result]) == snap_dir`. Every path read from an index goes through it. |
| S5 | `is_stale` `snaputil.py:66-73` | `<=` at `:73` returns **True** at equality while the docstring (`:70-71`) says "not stale" at equality. A directory's mtime is "last entry added/removed", not "created". | Not used. Age is taken from the snapshot name/footer, never a directory mtime. |

### 1.3 What `backupctl` builds on, and what it overrides

`backupctl.py` (new, alongside `synccli.py`) imports `synccli` and `snaputil`.

| Concern | Builds on | Overrides, where, why |
|---|---|---|
| Scanning | `synccli.scan_files`'s walk loop (`synccli.py:13-18`) | New `synccli.scan_tree(root, include_hidden=True, onerror=cb, exclude=())` added next to it (backward-compatible; `scan_files` untouched so the 6 tests are unaffected). Differences: dot-dirs kept (P1, line 14), `onerror` collects unlistable dirs (P2, line 13), returns dirs and symlinks as typed entries `("f"|"d"|"l", rel)`, root-level `.backupctl` is reserved and excluded with a report. |
| Per-file state | `synccli.file_state` shape (`{"size":…, …}`) | New `synccli.file_state_ns(path)` = `os.lstat` ⇒ `{type, size, mtime_ns, ctime_ns, mode}` (P3). The old function stays for `sync()`. |
| Manifest building | `synccli.build_manifest` (`:28-33`) structure | `build_manifest_ns(root)` same `{rel: state}` result, but a `FileNotFoundError` on one entry becomes a `vanished` record, other `OSError`s an `unreadable` record; never raises. |
| Change detection | `synccli.changed_files(old, new)` (`:36-42`) **unchanged** | Input states carry `ctime_ns`; racy entries (§8) are added to the result afterwards. |
| Orchestration | the order in `synccli.sync` (`:72-87`): scan → load previous manifest → diff → copy → persist manifest | Overridden at `:77-79` (index loaded through a validating reader with recovery), `:83-84` (copy goes to staging via strict chunked copy), `:85-86` (index written once, checksummed, fsynced, published by rename), and `:80-87` (deletions are implicit because the staging tree starts empty — P7). |
| Copy | `copy_file`'s `makedirs(...exist_ok=True)` idea (`:64`) | `copy_file_strict` (P4, P5): no `except OSError: pass`; chunked 1 MiB; `O_EXCL` create in staging; sha256 while copying; `fstat` before/after; `utime(ns)`, `chmod`; `fsync`. Returns a result or raises a classified error that the caller records. |
| Listing snapshots | `snaputil.list_snapshots` (S1) | Name regex filter on top. |
| Path safety | `snaputil.safe_snapshot_path` (S4) | Guard in front of it. |
| Pruning | — | `snaputil.prune_snapshots` replaced (S2). |
| CLI | `main()` pattern (`synccli.py:90-103`, `snaputil.py:76-92`) | `backupctl.main` with subcommands and the exit-code contract (§12). |

---

## 2. On-disk layout

```
<backup_root>/                       local filesystem, same fs for everything below (hard links!)
  <dirkey>/                          one per configured directory
    .lock                            flock target (empty file)
    .leases/snap-<…>                 empty files; readers take LOCK_SH (optional protocol, §5.2)
    .staging-<runid>/                run in progress. NOT a snapshot. Deleted if found by a later run.
    .trash/snap-<…>.<runid>          being deleted. NOT a snapshot.
    .quarantine/snap-<…>             snapshot whose index failed validation (§6.3)
    snap-20261112-150000-00/         committed snapshot: a full tree …
      <tree exactly as in source, dot-dirs and symlinks included>
      .backupctl/index.jsonl         … plus its index (reserved name)
```

Config (`backupctl.json`): `{"backup_root": "...", "dirs": {"<dirkey>": {"path": "...", "exclude": [globs]}}}`.
Start-up validation (exit 2 on failure): `dirkey` matches `[A-Za-z0-9._-]+`
and does not start with `.`; `realpath` of a source is neither inside nor
containing `backup_root` (otherwise the tool would back up its own snapshots);
sources do not overlap; `backup_root` supports `os.link` (probe with a temp
file; if not, exit 1 — we do **not** fall back to full copies, which would
silently multiply disk use by S ≈ 19).

**Snapshot names.** `snap-<UTC date>-<UTC time>-<NN>`, UTC so DST can't reorder
names. Chosen **at commit time, under the lock**:
`ts = max(now_utc_seconds, ts_of_newest_existing_name)`;
`NN` = number of existing snapshots with the same `ts` prefix (00–99).
Consequences: lexicographic order == commit order even if the wall clock steps
backwards (laptop sleep/NTP), so `snaputil.list_snapshots()[-1]` is really the
newest, and 2 digits suffice (`NN` only breaks ties within one second; the
3-digit overflow in S1 cannot occur). The true wall time is in the index
footer.

---

## 3. The snapshot index

`.backupctl/index.jsonl`, UTF-8, one JSON array/object per line, compact
separators:

```
{"v":1,"kind":"header","dirkey":"evals","source":"/abs/realpath","run":"<runid>",
 "scan_started_ns":1794840856610605127,"deep":false}
["d","sub",16877,1794840861505419493]                    # dir: path, mode, mtime_ns
["f","sub/a.dat",2455,1794841307039338324,1794841307039338324,33188,"<sha256 hex>"]
                                                         # file: path,size,mtime_ns,ctime_ns,mode,sha256
["l","link",1794840861505419493,"target/string"]         # symlink: path,mtime_ns,target
["s","sub/b.dat","vanished"|"unreadable:EACCES"|"unstable"|"dir-unlistable:EACCES"]
["x","sock1","special"|"excluded"|"reserved"]
{"kind":"footer","status":"complete"|"partial","entries":N,"committed_ns":…,
 "counts":{"linked":…,"copied":…,"bytes_copied":…,"vanished":…,"unreadable":…,"unstable":…},
 "sha256":"<sha256 of every byte of the file before this line>"}
```

* The `sha256` in the footer plus `entries` make a truncated, empty, bit-flipped
  or hand-edited index detectable by one linear read (≈4 MB at 30k files;
  parse measured 0.034 s without tracemalloc).
* Measured size: **136 B/entry** for the prototype row layout (path, size,
  mtime_ns, ctime_ns, sha256) ⇒ 4.09 MB at 30,000 files; budget 150 B/entry
  with `kind`/`mode`.
* `s` and `x` lines are **not** promises; only `d`/`f`/`l` lines are.

**Invariants (what a reader may rely on)**

* **I1** A directory named `snap-…` was created by a single atomic rename of a
  fully fsynced staging tree. It is never modified afterwards (no file under it
  is opened for writing, nothing is renamed into it).
* **I2** Every `f`/`l`/`d` line in its index has a corresponding entry in the
  tree and vice-versa. The tree is generated only from entries that were
  successfully materialized, and the index is generated from the same list.
* **I3** The footer is the last line, so "index present and validates" ⇔
  "run reached the end".
* **I4** Each file's content is as of some instant inside the run (and its
  `fstat` was identical before and after the copy, §7). Cross-file
  point-in-time consistency is **not** claimed — that needs the source
  quiesced or snapshot-capable storage; stated as a limit in §13.
* **I5** A reader never needs to know whether the producing run finished: if
  the directory is named `snap-…` it did.

---

## 4. The run algorithm (per directory, sequential across directories)

Inputs: `dirkey`, source, config, flags (`--deep`, `--lock-timeout`, default 1800 s).

1. `requested_ns = time.time_ns()`. Open `<root>/<dirkey>/.lock`; acquire
   `flock(LOCK_EX)` polling every 1 s up to the timeout; timeout ⇒ report
   `busy`, exit 75 for this directory.
2. **Janitor** (we hold the exclusive lock, so no other writer exists):
   delete every `.staging-*` and `.trash/*` (best-effort `rmtree` with chmod
   retry). Report `cleaned: N dead staging, M trash`.
3. **Base selection.** `names = [n for n in snaputil.list_snapshots(dir) if SNAP_RE.match(n)]`.
   `base = names[-1]` if any. Validate its index (§3 footer check). On failure
   → recovery §6.3. Else `prev_states = {rel: state}` from the `f`/`l` lines.
   **Coalesce:** if the valid base's `scan_started_ns > requested_ns` (another
   run took the lock after our request and began scanning after it, so its
   image is already at least as fresh as we were asked for), report
   `coalesced` and finish this directory with exit 0.
4. **Scan.** `scan_started_ns = time.time_ns()` *before* the first `lstat`.
   `scan_tree` + `build_manifest_ns` ⇒ `cur_states`, plus `vanished` and
   `unreadable` records.
5. **Diff.** `to_copy = synccli.changed_files(prev_states, cur_states)`; add
   racy entries (§8); in `--deep` mode `to_copy` is "everything" but each file
   is linked instead of copied when its source sha256 equals the base's.
6. **Space preflight.** `need = Σ size(to_copy) + 0.65 KB × entries`;
   if `statvfs` free < `1.1 × need + 64 MiB` ⇒ fail (exit 1) before writing
   anything. Prior snapshots untouched.
7. **Materialize** into `.staging-<runid>/` with 4 worker threads
   (measured 2.1× over 1 thread, §10): create directories; per file either
   `os.link(base/rel, staging/rel)` or `copy_file_strict`. If `os.link` raises
   `FileNotFoundError` (base tree lacks a file its index promised) fall back to
   copy and count `repaired`. Symlinks are re-created with `os.symlink`.
   Per-file failures are classified (§7) and never abort the run.
8. **Finalize.** fsync every staging directory, apply directory modes/mtimes
   (children first), write `index.jsonl` (entries sorted by path, footer last),
   `fsync` file, `fsync` `.backupctl/`.
9. **Commit.** Choose the name (§2), `os.rename(staging, root/dirkey/<name>)`,
    `fsync` `<root>/<dirkey>`. Rename onto an existing path fails (ENOTEMPTY);
    that is a hard error, never an overwrite.
10. **Retention** (§9) — only if steps 1-9 succeeded.
11. Release the lock (also released by the kernel on any exit), emit the report
    (§12).

A directory whose run fails does not stop the other directories.

---

## 5. Concurrency

### 5.1 Writers
* Same `dirkey`: serialized by `flock(LOCK_EX)` on `.lock`. The scheduler
  and a person calling `backupctl run` therefore never interleave; the second
  waits, then either coalesces (step 3) or runs.
* Different `dirkey`s: independent locks, so they may run in parallel in
  different processes. `backupctl run` over N directories processes them
  sequentially inside one process (memory bound, §11).
* The kernel drops a `flock` when the process exits, is killed, or the machine
  restarts; there is no pid file and no stale lock. A **suspended** (laptop
  sleep) run keeps its lock; waiters time out at `--lock-timeout` and report
  `busy`.
* Requirement: `backup_root` on a **local** filesystem (flock and rename
  semantics over NFS/SMB are not relied on).

### 5.2 Readers (a restore, a human, the next run)
* Writers never touch a `snap-*` directory after commit (I1): linking *from* a
  base snapshot only increments inode link counts, it never opens base files
  for writing. A reader reading snapshot X while a run builds snapshot Y sees
  no change at all.
* Reader protocol for tooling we control (`backupctl list/verify`, and the
  restore tool should adopt it):
  1. `names = snaputil.list_snapshots(<root>/<dirkey>)`; take the last (or the one wanted).
  2. `open("<root>/<dirkey>/.leases/<name>", O_CREAT)`; `flock(LOCK_SH)`.
  3. Re-check that `snap-<…>` still exists; if not, the snapshot was
     retired between steps 1 and 2 → go back to 1.
  4. Read `.backupctl/index.jsonl`, validate footer, copy files; every
     index-supplied path through `safe_rel()` (S4).
  5. Close (lease released).
* The reader never checks "is the run finished" (I5).
* A reader that does not follow the protocol (e.g. a human `cp -r`) is
  protected by the retention rule that the newest 8 snapshots are never
  deleted; if it reads a snapshot that retention retires mid-read it gets
  `ENOENT` (fail-stop, never silent mixing — files already opened stay
  readable under POSIX unlink semantics). This residual risk is stated, not
  hidden.

---

## 6. Dying at any point

### 6.1 Kill-point matrix

| Death point | What is left | What a reader sees | Next run |
|---|---|---|---|
| Before staging exists | nothing | previous snapshots | normal |
| During materialize / finalize / index write | `.staging-<id>/` (possibly with a half-written `index.jsonl`) | nothing: name does not match `snap-*`, so `list_snapshots` ignores it (S1) | step 2 (janitor) deletes it. Cost of the lost work ≤ one run (§10). |
| After index written, before rename | complete but uncommitted staging | nothing | deleted, re-derived by the new run (no adoption: simpler, costs ≤ one run) |
| During `os.rename` | atomic: either staging or snapshot, never both/partial | old or new state | normal |
| After rename, before retention | new snapshot committed | the new snapshot | retention runs on the next run |
| During retention `rename → .trash` | atomic | snapshot disappears from listing at that instant | normal |
| During `rmtree` of `.trash/x` | partial tree under `.trash/` | nothing (not `snap-*`) | step 2 (janitor) finishes the deletion |
| During quarantine rename | atomic | old or quarantined | normal |
| Kernel crash / power loss | as above, plus data-durability handled by fsync order: file data (per file) → directories → `index.jsonl` → rename → parent dir (§4 steps 7-9). On macOS plain `fsync` does not flush the drive cache; `fcntl(F_FULLFSYNC)` is used for `index.jsonl` and the parent dir. | only committed snapshots | `backupctl verify` can re-hash a snapshot against its index |

Cost of the fsync discipline, measured: full prototype 16.3 s vs 17.8 s
without fsync in the serial run — within noise; per-file fsync is not a
measurable cost here (§10).

Interruptions (Ctrl-C, SIGTERM): `finally` removes own staging best effort;
correctness does not depend on it (SIGKILL case is the rows above).

### 6.2 What the index recovery must define — the definition

The only mutable index is the **per-snapshot `index.jsonl`**; there is no
global "latest" file or database to corrupt: "newest snapshot" is *derived
from the directory listing every time*. Two cases:

**(a) Half-written index from a dead run.** It lives inside `.staging-*`
(§4 step 8), so it is **discarded wholesale** with the staging dir (§6.1). It
can never be read, because that path is never named `snap-*`.

**(b) Committed snapshot whose index is bad** (truncated/zero-length,
checksum or entry-count mismatch, JSON error, missing file, schema `v` unknown
— caused by disk faults, a non-ordering filesystem after power loss, or a human
edit).

### 6.3 Recovery procedure for (b), performed under the lock in step 3

| Step | Action | Rationale |
|---|---|---|
| R1 | Walk `names` newest → oldest; the first whose index validates is `base`. Bad ones are **quarantined**: `os.rename` to `.quarantine/<name>` unless a reader lease is held (then left alone, still excluded as base). | A snapshot that cannot prove what it contains must not be listed as a snapshot (I2). Atomic rename, so no half state. |
| R2 | **Discarded**: the bad index (kept inside the quarantined dir for forensics) and all change-detection trust derived from it. Nothing from it is carried into the new snapshot's index. | Never promise files you cannot prove. |
| R3 | **Re-derived from the tree** (if a tree exists): for each regular file in the quarantined tree, `sha256` by reading it → `hints = {rel: sha256}`. (`size`/`mtime_ns` could be re-read via lstat, but `ctime_ns` of the source is not recoverable from the tree, so stat comparison is impossible for these entries.) | Lets the run keep hard-linking instead of re-copying GBs. |
| R4 | The new run scans the **live source** as usual. For every file the decision is by **content**: `sha256(source file) == hints[rel]` ⇒ `os.link(quarantine/rel, staging/rel)`, else copy. | The tree is trusted only as far as it provably equals the source *now*. A truncated tree file simply hashes differently and is re-copied. |
| R5 | If no snapshot validates (or trees are unusable): full copy, like a first run. | Always makes progress without manual cleanup. |
| R6 | **Report** (stderr line + `recovered` field in JSON + footer counts): `RECOVERED dirkey=<k> bad=<snap> reason=<truncated\|checksum\|count\|json:<line>\|missing\|schema> quarantined=<path> hashed=<files>/<bytes> relinked=<n> recopied=<n>`. Exit status is that of the run (0 or 3), plus the dedicated JSON `recovered:true` so the scheduler can alert. | Visibility without making recovery a failure. |
| R7 | Quarantined snapshots are deleted by retention after 14 days (`backupctl prune`). | Bounded growth; time to inspect. |

Cost of R3+R4 (hash tree and source): ≈ 2 × 1 GiB read ≈ 2 × 0.51 s warm
(sha256 measured 1999 MiB/s, §10) + per-file open ≈ 1.5–3 s for the reference
tree; cold-cache cost ≈ 2 B / disk-read-rate (unmeasured).

If base's index is valid but its tree lacks files (someone deleted them): step
8 `os.link` raises `ENOENT` → copy from source, `repaired` counted in the
report. `backupctl verify <snap>` checks every `f` line (existence, size,
sha256) and is the full audit.

---

## 7. A source file disappears or can't be read

Same code path whoever started the run; there is no TTY detection, no prompt,
no `--force` that changes behaviour.

| Event | Detected at | Snapshot contains | Index | Run status / exit |
|---|---|---|---|---|
| Vanishes between listing and `lstat`/open (`ENOENT`) | `build_manifest_ns` or `copy_file_strict` | the file is **absent** (a point in the run at which it didn't exist). **Not carried forward** from the previous snapshot — that would be the forbidden "some files from this run, some from the previous one". | `["s", path, "vanished"]`, counted | **complete**, exit 0, listed in the report (`vanished: n`, first 20 paths). A deleted file is not lost data. |
| Unreadable (`EACCES`, `EIO`, other `OSError` at open/read), unlistable directory (`os.walk` `onerror`) | scan or copy | absent; any partially written destination is deleted | `["s", path, "unreadable:<errno name>"]` | **partial**, exit 3. Not recorded as an entry ⇒ next run sees it as new and retries — fixing P4. |
| Changes while being copied (`fstat` size/mtime_ns/ctime_ns of the same fd differ before vs after) | `copy_file_strict` | retried up to 2 more times; still unstable ⇒ absent | `["s", path, "unstable"]` | **partial**, exit 3 |
| Replaced via rename while copying (new inode) | not an error: our fd still reads one consistent old version | the old version | normal entry (its stat is the fd's pre-copy stat, so next run re-copies) | complete |
| Socket / FIFO / device node | scan | absent | `["x", path, "special"]` | complete, exit 0 |
| Matches `exclude` / reserved `.backupctl` | scan | absent | `["x", path, "excluded"\|"reserved"]` | complete |

The stat recorded for a file is the one taken **before** reading it, so any
edit after that point yields a different stat next run (safe direction).
A `partial` snapshot is a valid, self-consistent image minus the listed
skips; its index never promises a skipped file (I2). Retention treats it as
below a complete one (§9).

---

## 8. "Unchanged": granularity, and what it can miss

Decision for a regular file, with `S_prev` from the base index and `S_cur` from
`lstat`:

`unchanged ⇔ S_prev == S_cur` over `(type, size, mtime_ns, ctime_ns, mode)`
(this is `synccli.changed_files`, `synccli.py:36-42`, unmodified) **and** the
entry is not racy.

* **Why ctime.** The existing `(size, mtime)` pair (`synccli.py:22-25`) is
  defeated by `touch -r`/`cp -p`/`rsync -t`/`os.utime`: reproduced in P8.
  ctime cannot be set by user space, so those edits are caught.
* **Racy entries** (as in git's "racily clean" index): an entry whose
  `max(mtime_ns, ctime_ns) > base.scan_started_ns − 2 s` could have been edited
  after we stat'ed it without the timestamp advancing (coarse timestamp: HFS+ 1 s,
  FAT 2 s, ext4 jiffies). Such an entry is decided by `sha256(source) ==
  stored sha256`: equal ⇒ hard link, else copy. The margin (default 2 s,
  `--racy-margin`) is a setting.
* **`--deep`** (scheduler: weekly): decide every file by sha256 (cost: one
  read of the tree, ≈0.5 s/GiB warm; cold ≈ size / disk rate).

**What this granularity can still miss** (will keep a stale file in the new
snapshot):
1. A write that changes neither size, mtime nor ctime — device-level writes,
   or an `mmap` store not yet flushed (the kernel updates mtime at writeback).
2. A filesystem whose timestamp resolution is coarser than the racy margin
   (some network/FUSE filesystems), or a source whose clock jumped such that
   the new mtime/ctime equals the old one to the nanosecond *and* size is equal.
3. Bit rot on the source (no write at all): only `--deep` against a prior hash
   can notice a *change*; it would simply be backed up as the new content.
4. Not tracked at all: xattrs, ACLs, ownership (needs root), sparse holes,
   source hard-link identity (each source link becomes an independent file).
   A change *only* to those is not a change we detect (an xattr change does
   bump ctime ⇒ recopy of data but the xattr itself is not preserved).

Conversely, ctime moves on `chmod`/`chown`/xattr/rename-by-another-tool and on
indexers (Spotlight): that causes **false "changed"** ⇒ an unnecessary copy,
never a missed edit.

---

## 9. Retention and safe deletion

### 9.1 Policy (defaults; per directory)

Let `C` = committed snapshots (listing order = commit order, §2), `status` from
the footer (`complete`/`partial`; unreadable footer ⇒ `unknown`, treated as not
complete), bucket by the UTC date/ISO week parsed from the snapshot **name**.

`keep = newest 8 of C (any status)`
`∪ newest complete per UTC day, for the 7 most recent days that have one`
`∪ newest complete per ISO week, for the 4 most recent weeks that have one`
`∪ {newest complete snapshot}`; `doomed = C \ keep`.

* |keep| ≤ 8 + 7 + 4 = **19** (the last term is almost always already inside the first).
* **Never** deletes the newest snapshot nor the newest complete one ⇒ the user
  always has a usable snapshot, even after a string of failed or partial runs
  (a failed run — exit 1 — does not run retention at all, step 10).
* Retention runs only after a successful commit and under the same lock, so it
  cannot race a writer that is hard-linking from the snapshot being deleted.
  `backupctl prune` takes the same lock.
* Quarantined snapshots: removed after 14 days.

### 9.2 Deleting one snapshot (replaces `snaputil.prune_snapshots`, S2)

1. `open(.leases/<name>)`, try `flock(LOCK_EX|LOCK_NB)`. If a reader holds a
   lease ⇒ **skip it this run** (it stays listed; retried next run). Never block.
2. Holding that lock: `os.rename(snap-X, .trash/snap-X.<runid>)` — atomic; from
   this instant `list_snapshots` no longer shows it and no *new* cooperating
   reader can get a lease on it (they re-check existence after leasing, §5.2).
3. Release, then `rmtree(.trash/…)`, with a handler that `chmod u+rwx` on
   directories (snapshot dirs may be 0555). Dying here leaves only a `.trash/`
   entry that step 2 (janitor) of the next run removes.
4. Remove the lease file.

Hard links make deletion independent between snapshots: unlinking a name only
drops a link; an inode survives while any other snapshot (or an open fd) still
holds it. Files already open in a non-cooperating reader keep reading (POSIX).

---

## 10. Performance budget: initial full backup of ~1 GB / tens of thousands of files

### 10.1 Reference tree and method
Synthetic tree: **30,000 files, 1,073,726,902 B (1.0 GiB)**, 600 dirs, log-normal
sizes (median 5,035 B, max 11.6 MB, seeded generator, Appendix A). Warm page
cache (`purge` is not permitted on this host, so cold-cache numbers are
derived, not measured). Prototype of the §4 pipeline (scan → `copy_file_strict`
semantics: chunked read, sha256, `fsync`, `utime`, `chmod` → directory fsync →
index → rename) was timed; the existing `synccli` was timed for baseline.

### 10.2 Measurements (this machine)

| Measurement | Result |
|---|---|
| `synccli.build_manifest` over the tree (scan + stat, 30,000 files) | 0.78 s |
| `synccli.sync` full first sync (existing code, 1 thread, read-whole-file) | 12.21 s |
| `synccli.sync` no-op second run | 0.79 s; manifest 2.46 MB |
| Single 1 GiB file, chunked copy, fsync, sha256 | 0.59 s (1728 MiB/s); without sha256 0.19 s |
| sha256 of 1 GiB (read) | 0.51 s (1999 MiB/s) |
| 30,000 × 1-byte files created (open/write/utime/chmod/fsync) | 9.1 s ⇒ **0.30 ms/file**, 1 thread |
| same with 2 / 4 / 8 threads | 5.9 s / **4.3 s** / 3.96 s ⇒ 4 threads = 2.1× |
| Prototype full backup, 1 thread, fsync+sha256 | 16.3 s (17.8 s, 15.7 s in the two other configurations) |
| Prototype full backup, **4 threads**, fsync+sha256+dir fsync+index (`proto2`, 2 runs) | scan 1.1 s + materialize 6.0 s + finalize 0.17 s = **7.27 s** (7.24 s on re-run) |
| Hard-link a 30,000-file tree, 1 / 4 / 8 threads | 11.2 s / **5.8 s** / 6.0 s ⇒ 0.37 ms / 0.19 ms per link |
| `rmtree` of a 30,000-link snapshot | 2.5 s |
| Incremental run, nothing changed, 4 threads | 7.0–7.2 s (scan 0.9–1.1 s + 30,000 links 5.9–6.0 s + finalize 0.2 s) |

### 10.3 Derivation and stated budget

`T_full ≈ t_scan·F + t_create·F/k + B/R + t_final`
with `t_scan = 0.03 ms` (0.9 s / 30,000), `t_create = 0.30 ms` (APFS file
create + metadata, 1 thread), `k = 2.1` (4 threads), `R = 1.7 GiB/s`
(copy + sha256), `t_final = 0.2 s` ⇒ `0.9 + 4.3 + 0.6 + 0.2 ≈ 6.0 s` predicted;
**measured 7.27 s** (thread contention accounts for the gap).

**Budget: initial full backup of the reference tree ≤ 30 s** (hard ceiling;
target ≈ 10 s). 30 s is 4× the measured 7.3 s and ≈ 2× the single-thread
figure (14–17.7 s), so it holds if worker threads give no benefit. Scaling:
`T_full ≤ 1 s + 0.5 ms × F + 1 s/GiB × B` (F files, B GiB); 60,000 files, 2 GiB
⇒ ≤ 33 s. Cold cache adds `B/R_disk` for data (≈ 2 s for 1 GiB at 500 MB/s,
≈ 10 s at 100 MB/s; **derived, not measured**) plus unmeasured cold-metadata
latency on the 30,000 stats.

Baseline honesty: `backupctl`'s *unchanged* run (≈7 s) is slower than
`synccli`'s no-op (0.79 s) because a self-contained snapshot costs one
hard link per file: ≈0.19 ms × F at 4 threads on APFS. That is the price of
plain-tree snapshots (§13, alternatives).

---

## 11. What grows with what — explicit bounds

Notation: `N` directories; per directory `d`: `F_d` files, `B_d` bytes,
`C_d` files and `CB_d` bytes changed since the previous run; `S ≤ 19` retained
snapshots per directory (§9.1). Constants are measured in §10 on APFS; they
are machine-specific.

| Quantity | Bound | Grows with | Flat in |
|---|---|---|---|
| **Per-run time, one directory** | `T_d ≈ 0.03 ms·F_d + 0.19 ms·(F_d − C_d) + 0.2 ms·C_d + CB_d / 1.7 GiB/s + 0.08 ms·F_d (one rmtree) + 0.2 s` ⇒ ≈ **9–10 s** for `F=30,000, C=0` (measured 7.1 s run + 2.5 s rmtree) | `F_d` linearly (every file is scanned and linked every run); `CB_d` for bytes | `S`, number of runs so far, history length |
| **Per-run time, all dirs** | `Σ_d T_d` (sequential): `N=3` ≈ 29 s, `N=36` ≈ 5.8 min if every dir were reference-sized | `Σ F_d` | — (it is *not* flat in N: it is linear) |
| **Bytes copied per run** | `Σ_d CB_d` exactly; unchanged files cost 0 bytes (a link) | churn | `B_d`, `N` for unchanged data |
| **Peak memory** | `≈ 25 MB + 3.3 KB × F_max + 4 MiB` (4 threads × 1 MiB buffers); measured **123 MB RSS at F=30,000** (fresh-process incremental run; 450 B/entry for the current-state dict, +570 B/entry loaded previous index, `tracemalloc` 30.1 MB for both) | `F_max` = the largest **single** directory | `N` (directories are processed one at a time), `S`, `B` (files copied in 1 MiB chunks, vs `synccli.copy_file:66-67` which holds a whole file) |
| **Disk, per directory** | `D_d ≤ B_d + V_d + S·F_d·0.65 KB`, where `V_d` = bytes of *distinct older file versions* still referenced by a retained snapshot (≤ total bytes ever changed within the retention horizon, 4 weeks), and 0.65 KB/file = 0.15 KB index (measured 136 B) + ≤ 0.5 KB directory entries (measured 3.5–15 MB per 30,000-link snapshot via `df`, i.e. 0.12–0.5 KB). For the reference tree: metadata ≤ 19 × 19.5 MB = **370 MB worst case**, ≈ 170 MB typical, plus `B_d + V_d` | `B_d`, churn, `F_d` (metadata) | number of runs (retention caps it at `S ≤ 19`); inode count (links share inodes) |
| **Disk, whole root** | `Σ_d D_d` + ≤ 14 days of quarantine | `N` linearly | — |
| **Snapshots in the listing per directory** | ≤ 19 (+ ≤ a few transient) | retention policy constants | time |
| **Index load/validation** | read + parse ≈ 0.034 s per 30,000 entries; only the base's index is read per run | `F_d` | `S` |
| **Lock contention** | zero between different `dirkey`s; waits only behind the same `dirkey` (≤ one `T_d` ≈ 10 s per reference dir) | — | `N` |

Reading the table for 3 → "a few dozen" directories: time and disk grow
**linearly in Σ F_d and Σ B_d** (and are *not* flat); memory and snapshot count
per dir stay at the stated constants; bytes copied depend only on churn.

---

## 12. Reporting and exit codes

Per directory and in aggregate, the same on every trigger path.

* stdout: one JSON object per directory, then a final aggregate object:
  `{"dirkey","status":"complete|partial|coalesced|busy|failed","snapshot":"snap-…",
  "files":n,"linked":n,"copied":n,"repaired":n,"bytes_copied":n,
  "vanished":[…first 20…],"vanished_n":n,"unreadable":[…],"unstable":[…],
  "recovered":bool,"cleaned":{"staging":n,"trash":n},"pruned":[…],
  "quarantined":[…],"seconds":x}`.
* stderr: the human summary line(s) (including the `RECOVERED …` line of §6.3 R6).
* Exit codes (aggregate = worst of the per-dir codes by 1 > 75 > 3 > 0; 2 for usage):

| Code | Meaning |
|---|---|
| 0 | every directory `complete` or `coalesced` (vanished files allowed) |
| 3 | at least one `partial` snapshot (unreadable/unstable files), still committed |
| 75 | `busy`: lock not obtained within `--lock-timeout` |
| 1 | at least one directory `failed`: no snapshot committed (ENOSPC/space preflight, root not linkable, I/O error) |
| 2 | bad config / usage |

This replaces `synccli.main` always returning 0 (`synccli.py:99`, P9).

---

## 13. Non-goals, limits, alternatives rejected

* **Not** cross-file point-in-time (I4); **not** cross-directory atomic.
* **Not** preserved: xattrs, ACLs, ownership, sparse-ness, hard-link identity
  within the source. Mode and mtime_ns are preserved.
* Local filesystem with hard links only (probed at start). Hard links make an
  in-place edit of a snapshot file corrupt every snapshot that shares the
  inode; the contract is "snapshots are read-only"; `backupctl verify` (sha256
  against the index) detects it. Mode bits are not stripped (they mirror the
  source).
* Wall-clock dependence: only the racy margin and retention bucketing.
* No encryption, no offsite copy.
* **Alternative rejected — sparse snapshots**: each snapshot holds only changed
  files + an index that references older snapshots. No-op run ≈ 0.8 s (like
  `synccli`) and far less metadata, but a snapshot is no longer a plain tree:
  every reader (restore, a human) must resolve references across snapshots,
  and deleting a snapshot would require reference counting — contradicting
  "a reader never asks anything" and "deletion safe under a reader". Revisit if
  the ≈7 s/30k-file no-op cost matters at N ≈ 36.
* **Alternative rejected — in-place sync with `.sync_manifest.json`** (the
  `synccli.sync` model): cannot be atomic and cannot retain history (P4–P7).

---

## 14. Implementation and test plan

Files: `backupctl.py` (CLI, run algorithm, retention, recovery), additions to
`synccli.py` (`scan_tree`, `file_state_ns`, `build_manifest_ns`; existing
functions unmodified), one-line guard in `snaputil.prune_snapshots`,
`test_backupctl.py`.

Existing 6 tests must still pass. New tests (each uses `tempfile`, no sleeps
except the lock test):

1. **Differential**: for a seeded random tree and random mutations,
   restored snapshot == source (content, mode, symlinks, empty dirs, dotdirs).
2. **P-regression tests** for each probe in §1.2 against `backupctl`
   (unreadable file ⇒ absent + `partial` + exit 3 + retried next run; vanished
   between list and stat ⇒ absent + exit 0; truncated base index ⇒ `RECOVERED`).
3. **Kill points**: fault injection (`BACKUPCTL_FAULT=<point>` raising
   `os._exit(9)`) at every row of §6.1; afterwards assert `list_snapshots`
   returns only valid snapshots, each passing `verify`, and the next run exits
   0/3 and leaves no `.staging-*`/`.trash/*`.
4. **Index corruption matrix**: truncate at every line boundary and at random
   byte offsets, flip a byte, empty file, missing file, wrong `v`; assert
   quarantine + hints-based relink + the report line.
5. **Concurrency**: `multiprocessing` — 2 `run`s same dirkey (second coalesces
   or serializes), run vs reader loop that validates every `snap-*` it sees
   (never an invalid one), run vs `prune` vs leased reader (leased snapshot
   skipped).
6. **Granularity**: same-size edit with `os.utime` restoration ⇒ detected via
   ctime; same-tick edit ⇒ detected through the racy rule; `--deep` ⇒ detects
   edit with forged ctime (monkeypatched).
7. **Retention**: property test — for random histories (with partial/unknown
   statuses) `keep` ≥ 1, contains the newest complete, `|keep| ≤ 19`,
   deterministic.
8. **Path safety**: `safe_rel` rejects `../x`, `/etc/passwd`, `a/../../x`,
   NUL (S4).
9. **Perf smoke** (opt-in env var): the §10 reference tree, assert ≤ 30 s.

---

## Appendix A — measurement procedure (re-runnable)

* Tree: 30,000 files, sizes `lognormvariate(0, 2.0)` scaled to 2^30 bytes total,
  `random.seed(7)`, content `os.urandom(1 MiB)` prefix slices, 600 dirs
  (`dNNN/sMM`).
* Existing code timing: `synccli.build_manifest(src)`, `synccli.sync(src, dst)`
  twice (full, then no-op); manifest bytes via `os.path.getsize`.
* Prototype: scan with `os.walk` + `os.lstat` (ns ints); per file
  `os.read` 1 MiB chunks → `hashlib.sha256().update` → `os.write` into an
  `O_EXCL` file → `os.fsync` → `os.utime(ns)` → `os.chmod`; or `os.link` from
  the previous staging tree; `ThreadPoolExecutor(4)`; fsync of every directory;
  index JSONL with fsync; `os.rename`.
* Memory: `resource.getrusage().ru_maxrss` in a fresh process for
  the incremental run (123 MB), `tracemalloc` for per-entry costs.
* Disk overhead of links: `df -k` delta around creating a 30,000-link tree,
  3 trials: 15.1 MB, 3.5 MB, 5.5 MB (noisy: other host activity).
* Numbers vary ±10–20 % between runs (e.g. serial full backup 14.2–17.7 s).

## Appendix B — one-line reproductions of the §1.2 probes

```python
import synccli, snaputil, os, tempfile
snaputil.safe_snapshot_path("/b","snap-1","../../etc/passwd")   # '/b/snap-1/../../etc/passwd'
snaputil.safe_snapshot_path("/b","snap-1","/etc/passwd")        # '/etc/passwd'
# prune keep=0 / -1 on two snapshots -> both deleted, listing []
# list_snapshots with ...-99, ...-100, ...-07 -> [...-07, ...-100, ...-99]
# is_stale(d, os.stat(d).st_mtime) -> True (docstring says not stale)
# snapshot_disk_usage over a tree containing a dangling symlink -> FileNotFoundError
# scan_files on {.dot, .hid/h, real/f, lnk->real, empty/, noperm(000)/p} -> ['.dot','real/f']
# sync() with a mode-000 source file: returns ['secret'], dst has no 'secret',
#   manifest lists it, second sync() returns []
# overwrite dst/.sync_manifest.json with '{"secret": {"si' -> sync() raises JSONDecodeError
# delete a source file, sync() -> []  and the file stays in dst
# edit file keeping size and os.utime(ns=original) -> sync() returns []
```

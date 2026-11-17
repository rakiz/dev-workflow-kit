# DESIGN-d1 — `backupctl`

Scope: design only. No existing file was changed. Every claim about the existing code was checked by running it (probe results in 1.2). Every number was measured on the reference machine (10.1). The measurement scripts are kept outside this repo in `/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/opencode/d1-scratch/`.

Reference machine: Apple M3 Max, macOS (darwin/arm64), APFS, Python 3.10.11, warm page cache.

## 0. Summary

1. A **series** is one configured source directory. Its state lives in `<backup_root>/<label>/`: a writer lock, a reader lock, a run log, and its snapshots.
2. A **snapshot** is a directory `snap-YYYYMMDD-HHMMSS-NN/`, the naming `snaputil.list_snapshots` already expects. It holds a copy of the tree and a self-checking index `.backupctl-index.jsonl`. It becomes visible only through one atomic `rename()` from a hidden staging directory, after the index is written and verified.
3. Unchanged files are hard-linked from the newest valid snapshot; changed files are copied and SHA-256 hashed. "Unchanged" means the same `(size, mtime_ns, ctime_ns, inode, device)` (section 8).
4. One exclusive `flock` per series serializes runs and pruning. Restores take a shared `flock` on a second file. Deletion is a rename to a hidden name followed by removal, so a reader sees either the whole snapshot or `ENOENT` (section 5).
5. A dead run leaves only hidden staging or trash directories. The next run removes them and re-derives the change set from the source tree. No file records the change set; the persisted state is lock files, an advisory run log and immutable snapshots (section 6).
6. Vanished, unreadable or unstable source files are left out of the snapshot, listed in its index and in the run report, and the run exits 3. Scheduler and person get identical behavior (section 7).
7. Retention keeps the newest `keep_last` snapshots (default 10, minimum 1) plus the newest clean snapshot. Deletion happens only after a successful publish (section 9).
8. Initial backup budget: **at most 45 s** for the 1.0 GiB / 30 000-file fixture on the reference machine. Measured components sum to 14.6 s; the budget is about 3x that (10.2).
9. Per-run cost is about 0.04 ms per entry plus 0.39 ms per unchanged file (the hard link). A no-change run on 30 000 files costs about 13 s. This link cost is the main price of self-contained snapshot directories (10.3, decision D1).

## 1. Grounding

### 1.1 What the existing code does and how this design treats it

Baseline: `python3 -B -m unittest` in this directory runs 6 tests, all passing. None of them exercises a failure path, and `snaputil.py` has no tests at all.

Treatment labels: **reuse** = called unchanged; **wrap** = called with an extra filter; **override** = not called, replaced by a function in a new `backupctl.py`; **not used** = no design element depends on it. Nothing in `synccli.py`, `snaputil.py` or `test_synccli.py` is modified, so the existing tests keep pinning current behavior.

| Existing item (file:line) | Treatment | Reason (probe ids in 1.2) |
|---|---|---|
| `synccli.changed_files` (synccli.py:36-42) | reuse | The predicate "absent or state differs" is exactly what section 8 needs. The caller passes a baseline with racy entries removed. |
| `synccli.scan_files` (synccli.py:10-19) | override, replaced by `scan_series` | L14 drops dot-directories silently (C5). L13 calls `os.walk` without `onerror`, so an unreadable subtree disappears with no report (C5). Symlinked directories are never returned (checked: `linkdir` absent, `linkfile` present). Keeps the sorted relative-path output of L19. |
| `synccli.file_state` (synccli.py:22-25) | override, replaced by `stat_state` | Stores float `st_mtime` (L25). The float64 ULP at 1.7e9 s is 238 ns; on a real file `st_mtime_ns` and `int(st_mtime*1e9)` differ by 165 ns. No ctime, inode or device, so a same-size rewrite with restored mtime is missed (C6). |
| `synccli.build_manifest` (synccli.py:28-33) | not used | Calls the two functions above by name. Replaced by a loop over `scan_series` and `stat_state`. |
| `synccli.copy_file` (synccli.py:62-69) | override, replaced by `copy_file_verified` | L68-69 `except OSError: pass` (C3). L67 `fsrc.read()` loads the whole file (peak RSS 267.8 MiB for a 256 MiB file; chunked copy 26.0 MiB, see 10.1). No fsync, no exclusive create. |
| `synccli.sync` (synccli.py:72-87) | not used | L79 `json.load` is unguarded: a truncated manifest raises on every run (C4). L85-86 rewrite the manifest in place after copying and record failed files as copied (C3). |
| `synccli.collect_stale` (synccli.py:45-59) | not used | Only the tests call it (grep). |
| `synccli.MANIFEST_NAME` (synccli.py:7) | not used | The per-snapshot index has a different format and a different job (proof of completeness). New name `.backupctl-index.jsonl`. |
| `snaputil.list_snapshots` (snaputil.py:8-20) | wrap | L18 accepts any `snap-` name and symlinks to directories (C9). The wrapper keeps names matching `^snap-\d{8}-\d{6}-\d{2}$` that are not symlinks. The sort at L20 is reused: names are fixed-width and in publication order. |
| `snaputil.prune_snapshots` (snaputil.py:23-36) | override | A `keep` of 0 or less deletes every snapshot (L31-33, C2). L35 `rmtree` is not atomic. No reader protection. The docstring at L24-28 says the newest is never deleted, which is false for keep < 1. |
| `snaputil.snapshot_disk_usage` (snaputil.py:39-51) | wrap | L50 `os.stat` follows symlinks and raises when a file disappears (C8). Hard-linked inodes are counted once per link, which overstates disk use. The replacement uses `lstat`, skips vanished entries and dedupes by (device, inode). |
| `snaputil.safe_snapshot_path` (snaputil.py:54-63) | override | Returns paths outside the snapshot (C1). No caller exists in the repo today (grep), so the restore tool becomes its first caller and must use the override. |
| `snaputil.is_stale` (snaputil.py:66-73) | not used | L73 `<=` contradicts the docstring at L70-71 (C7). A directory's mtime changes only when entries are added or removed, so it cannot show that content is unchanged. |
| `snaputil.main` (snaputil.py:76-88) | not used | Its `--prune` (L82) calls the overridden `prune_snapshots`. Do not run it on a backup root until it is fixed (decision D5). |

### 1.2 Probe results

Run from the scratch directory with `python3 -B`. The repo was not written to.

- **C1** `safe_snapshot_path(root, "snap-…", "../../escape.txt")` returns a path outside the snapshot. `"/etc/passwd"` is returned unchanged, because `os.path.join` discards the prefix for absolute paths.
- **C2** `prune_snapshots` on 3 snapshots: keep=0 deletes 3 and leaves none; keep=-1 deletes 3; keep=1 deletes 2.
- **C3** Unreadable source (`chmod 0`): run 1 returns `['secret.txt']` as copied, the destination lacks the file, and the manifest records it. After `chmod 0644`, run 2 returns `[]`. The file is never copied.
- **C4** Truncated `.sync_manifest.json`: `JSONDecodeError` on run 1 and again on run 2.
- **C5** `scan_files`: `.hidden/` is absent; a mode-0 `locked/` directory is absent with no error; top-level `.env` is present. A symlinked directory is absent; a symlinked file is present.
- **C6** Same-size rewrite (`AAAA` to `BBBB`) with mtime restored by `os.utime`: `sync` returns `[]` and the destination keeps `AAAA`.
- **C7** `is_stale(dir, dir's own mtime)` returns True.
- **C8** A file removed between walk and stat: `snapshot_disk_usage` raises `FileNotFoundError`.
- **C9** `list_snapshots` returns `snap-notes` and the symlink `snap-link-to-notes`.
- Grep: `collect_stale`, `is_stale` and `safe_snapshot_path` have no production callers.

## 2. Layout and naming

```
<backup_root>/
  <label>/                          series directory, mode 0700
    .lock                           flock EX: runs, prune, quarantine. Never deleted.
    .readers                        flock SH: readers. flock EX|NB: deletion. Never deleted.
    .runs.jsonl                     append-only run log, written only under .lock (advisory)
    snap-YYYYMMDD-HHMMSS-NN/        published snapshot, immutable
      <copied tree>
      .backupctl-index.jsonl        index; the last line is the footer
    .staging-<run_id>/              run in progress (hidden from list_snapshots)
    .trash-<snap>-<rand>/           snapshot being deleted (hidden)
    .quarantine-<snap>-<run_id>/    snapshot that failed validation (hidden, never auto-deleted)
```

- Configuration: a JSON file passed as `--config`. It holds `backup_root` (absolute) and, per series, `label`, `source` (absolute) and `keep_last`. Relative paths are rejected with exit 2. Behavior does not depend on the working directory, so scheduler and person behave the same.
- The source root is resolved once with `realpath` at run start and recorded in the index header.
- `label` must match `[A-Za-z0-9][A-Za-z0-9._-]*`.
- Series are independent: runs for different series take different locks and share nothing except the root directory.

**Snapshot names.** `snap-<UTC ts>-<NN>`, with `ts` in whole seconds and `NN` two digits:
- `ts` = now. If `ts` is less than or equal to the newest existing snapshot's `ts`, use the newest `ts` and `NN = newest NN + 1`.
- If `NN` would exceed 99, use `newest ts + 1 s` and `NN = 00`.

Names therefore increase strictly in publication order even when the clock steps back. The lexicographic order used by `snaputil.list_snapshots` (L20) then equals publication order, so pruning the lowest names never deletes the newest publication. The index header holds the real wall-clock time.

## 3. Index format

`.backupctl-index.jsonl` sits at the snapshot root. It is UTF-8 JSON Lines, one object per line, entries sorted by `p` (relative path, `/`-separated):

1. **Header** (first line): `{"k":"hdr","v":1,"series":…,"snapshot":…,"source":…,"run_start_ns":…,"trigger":"scheduler|manual","racy_window_ns":2000000000}`
2. **Entries**, `k` is one of:
   - `f` regular file: `p, size, mode, mtime_ns, ctime_ns, ino, dev, sha256, racy`
   - `l` symlink (recreated as a symlink, never followed): `p, target, ctime_ns, ino, dev, racy`
   - `d` directory: `p, mode, ctime_ns`
   - `x` skipped source path, not present in the snapshot: `p, reason, errno`
3. **Footer** (last line): `{"k":"end","entries":N,"files":F,"skipped":S,"body_sha256":"…"}`. The digest covers the exact bytes of all preceding lines.

Rules:
- The `f` lines are exactly the regular files present in the snapshot. Publication verifies each one (section 4, step 10). The index never promises a file the snapshot does not contain.
- A snapshot is **valid** iff its last line is a footer, `entries` matches the line count, and `body_sha256` matches. Validation is one sequential read: about 6 MB for 30 000 entries.
- Size: 204 bytes per entry for the benchmark's 5-field format (6,129,988 bytes for 30 000 entries, measured). The `mode` and `racy` fields add an estimated 20 bytes per entry, so the budget uses 230 bytes per entry.

Why a footer: it is written last, but a reader does not rely on that ordering. It checks a digest, which catches truncation and later corruption (disk damage, manual edits).

## 4. Run algorithm

`backupctl run [--config F] [--series L ...] [--trigger scheduler|manual] [--wait SEC] [--allow-empty]`

Series run one after another within an invocation, never in parallel. Steps for one series:

1. **Validate.** `keep_last >= 1`; `source` exists and is a directory. A bad config exits 2. A missing source exits 1. Nothing is created in either case.
2. **Lock.** `mkdir -p` the series directory (0700). Open `.lock` and `flock(LOCK_EX|LOCK_NB)`. If busy, poll once per second until `--wait` expires, then exit 75 and report the holder's pid and start time, which the holder writes into `.lock` after acquiring it.
3. **Recover** (section 6). Remove every `.staging-*`. Finish every `.trash-*`.
4. **Baseline.** Walk snapshot names from newest to oldest. The first one whose footer validates is the baseline. Each invalid one is quarantined (section 6), or left in place and reported if the quarantine is deferred. If none is valid, the baseline is empty.
5. **Name.** Choose the new snapshot name (section 2).
6. **Stage.** `run_start_ns = time.time_ns()`. Create `.staging-<run_id>/` (0700, `run_id` random hex).
7. **Scan.** `scan_series(source)` (override of `scan_files`, section 7). Refuse with exit 1, removing staging and publishing nothing, if either of these holds:
   - the source root itself cannot be listed;
   - the scan yields zero `f` or `l` entries while the baseline has at least one `f` entry (an unmounted volume would otherwise become an empty baseline, and retention would then push out good snapshots). `--allow-empty` overrides this check.
8. **State.** For every entry, compute `stat_state` (an `lstat`, or `fstat` on the open fd for regular files). Set `racy = ctime_ns > run_start_ns - racy_window_ns` (section 8). `racy` is kept out of the state dict, so `changed_files` compares only the section 8 key fields.
9. **Diff and link.**
   - `trusted` = baseline entries whose `racy` flag is false.
   - `to_copy = synccli.changed_files(trusted, new_states)` (reuse, synccli.py:36-42).
   - For every other `f` entry: check that `lstat(baseline/p)` matches the recorded size, ino and dev, then `os.link(baseline/p, staging/p)`. A failed check or link falls through to copying, with a warning if the link failed.
   - Recreate `l` entries with `os.symlink`, and `d` entries with `os.mkdir`.
   - Copy every entry in `to_copy` with `copy_file_verified` (section 7).
10. **Verify (publish gate).** For each `f` line, `lstat` the staged file: it must be regular and its size must match. For each `l` line, `readlink` must match. Any mismatch fails the run (exit 1).
11. **Index.** Write `.backupctl-index.jsonl.partial` in staging, `fsync` it, rename it to its final name inside staging, `fsync` the staging directory, and issue one `F_FULLFSYNC` on the index file. The cost was measured at about 9 ms on a directory fd after 1000 unsynced files, which is the nearest measurement.
12. **Publish.** Under `.lock`, check that the target name does not exist, then `rename(staging, series/<new name>)` and `fsync` the series directory. The rename is atomic because staging lives in the same directory.
13. **Retention** (section 9), still under `.lock`.
14. **Log and release.** Append one line to `.runs.jsonl` (counts, skips, recovery actions, retention result, exit code). The log is advisory: the snapshot directories are the record. Close `.lock`, which releases it.
15. **Report** (section 13).

Memory is O(F) per series (section 10.4). Staging holds only copied bytes; linked files cost directory entries only.

## 5. Publication, concurrency and readers

**Writers.** Every run, prune and quarantine holds `.lock` exclusively for its whole duration. A second writer on the same series gets exit 75 immediately, or waits up to `--wait` seconds. Different series never contend. The kernel releases a dead holder's `flock`, so no stale lock survives a crash. The lock file is never deleted: deleting it while another process waits would create two locks for one series.

**Readers** (restore, `list`, and any inspection tool):
1. `flock(.readers, LOCK_SH)`, blocking, held for the whole read.
2. Resolve the `snap-…` name and read.

Readers never take `.lock`, so a restore never blocks a run, and a run never blocks a restore for longer than a rename batch.

**Deleters** (retention and quarantine), under `.lock`:
1. `flock(.readers, LOCK_EX|LOCK_NB)`. If busy, defer: nothing is renamed, the summary says `deferred: readers active`, and the exit code is unchanged.
2. For each candidate, oldest first, `rename(snap-X, .trash-X-<rand>)`. Each rename is atomic.
3. Release `.readers`.
4. `rmtree` each trash directory while still holding `.lock`. An interrupted removal leaves trash, which the next run finishes (section 6).

**Why this is safe.** A reader either acquires SH before deletion starts, in which case `LOCK_EX|LOCK_NB` fails and nothing is renamed, or it acquires SH after the rename batch, in which case the name is gone and the reader gets `ENOENT`, a clean error. A reader can never see a half-deleted snapshot, because half-deleted content exists only under `.trash-*`, which no reader resolves. A reader that already holds an open file descriptor keeps reading after a rename.

**What readers can rely on.** Every visible `snap-*` directory has a valid footer, and every `f` line in it is present (checked at publish). Snapshot files are created mode 0444 with `O_CREAT|O_EXCL`. The creating fd is writable (`assumptions.py`, check c), so no chmod pass is needed. Directories stay owner-writable so retention can remove them. Nothing writes into a published snapshot. Files inside one snapshot may reflect the source at slightly different instants during the run (section 14).

## 6. Interruption and recovery

**Invariant.** A directory named `snap-…` exists only after its index was verified and synced. Everything else a dead run can leave is hidden: `.staging-*`, `.trash-*`, `.quarantine-*`, `.partial`.

| Process dies at | State on disk | Next run (under `.lock`) | Reported |
|---|---|---|---|
| during scan or copy | `.staging-<id>/` with partial files | Remove staging. Copy pass repeats from the source. Baseline untouched. | `recovered: discarded staging <id> (<n> entries)` |
| after index written, before publish | complete but unpublished staging | Discarded too. The next run never publishes another run's staging, because the only proof of completeness is the verification done by the run that wrote it. Repeating the copy pass is the price. | same |
| during publish rename | `.staging-<id>` or `snap-…`, never both (atomic) | As above, or the snapshot is already visible and complete. | same |
| during prune rename batch | some candidates `.trash-*`, others still `snap-*` | Finish trash removal. Prune the rest again. | `recovered: finished prune of <snap>` |
| during trash `rmtree` | partial `.trash-*` | `rmtree` again. | same |
| during quarantine | rename, atomic | Nothing to do. | none |
| `snap-X` has a missing or corrupt footer (disk damage, manual edit) | index fails validation | Rename to `.quarantine-X-<run>` (never deleted). Baseline falls back to the next valid snapshot, or to a full copy if none. | `quarantined: snap-X (<reason>)` on this and every later run until removed |
| baseline lists a file that is now missing | link fails with `ENOENT` | The file is copied from the source instead. | `warning: baseline missing <path>` |
| `.lock` left behind | kernel released the `flock` | Nothing. | none |
| torn last line in `.runs.jsonl` | unparsable line | Readers skip it. Next append starts on a new line. | none |

**What is discarded and what is re-derived.** Discarded: all staging and trash content, and any snapshot that fails validation (moved aside, not deleted). Re-derived: the whole change set is recomputed on every run from the source tree and the baseline's index. Nothing that records "what changed" is persisted, so no mutable file can be left half-written. The worst-case cost of recovery is one full copy pass, which is the initial-backup budget in 10.2.

**Progress.** After any crash, the next run without interference publishes a snapshot and needs no manual cleanup. If a deterministic error recurs (for example a full disk), each run exits 1, publishes nothing, and reports the cause.

**Quarantine growth.** Quarantined snapshots are never deleted automatically, so the root grows by their size until a person removes them. Every summary reports the quarantine count and bytes.

## 7. Source files that vanish or fail

**Principle.** A source-side failure turns one file into a skip. A destination-side failure fails the run. Scheduler and person get identical behavior: no prompts, no TTY checks, no caller-dependent retries. The trigger label is the only difference, and it is stored in the index header and the run log.

**`copy_file_verified(src, dst)`** (override of `copy_file`, synccli.py:62-69). Up to 3 attempts at the same path:
1. `open(src, O_RDONLY|O_NOFOLLOW)`. `ENOENT` is skip `vanished`. `ELOOP` (replaced by a symlink) is skip `type-changed`. `EACCES`/`EPERM` is skip `unreadable` with errno. These are not retried.
2. `s1 = fstat(src fd)`. If not a regular file, skip `type-changed`.
3. `out = open(dst, O_WRONLY|O_CREAT|O_EXCL, 0o444)`. Stream 1 MiB chunks, hashing as they go. A source read error (`EIO`) unlinks the destination and skips `read-error`. A destination write error (`ENOSPC`, `EIO`) raises a run failure (exit 1).
4. `fsync(out)`, then `s2 = fstat(src fd)`. If `(size, mtime_ns, ctime_ns, ino)` of `s1` and `s2` match, the result is `copied`, recorded with state `s1` and the digest. Otherwise unlink the destination and retry.
5. After 3 unstable attempts, skip `changed-during-copy`.

**Scan-time handling** (`scan_series`, override of `scan_files`):
- An `os.walk` `onerror` callback records skip `unreadable-dir` with the directory path, so an unreadable subtree is no longer silently absent (C5).
- Dot-directories are included (C5).
- A symlinked directory is recorded as an `l` entry, not followed. A symlinked file is also recorded as `l`, not followed. The existing scan includes symlinked files and `copy_file` follows them, because `open` follows symlinks (C5 check). This design records them as links instead.
- A path that disappears between scan and stat is skip `vanished`.
- Special files (fifo, socket, device) are skip `unsupported-type`. They are detected at `lstat` time and never opened, so a fifo cannot block the run.
- A top-level source entry named `.backupctl-index.jsonl` is skip `reserved-name`.

**What the snapshot contains.** Every entry that was copied or linked: files, symlinks and directories. Skipped paths are absent from the snapshot. They appear as `x` lines in its index and in the report. A skipped file has no recorded state, so it is not in the next run's baseline and is retried automatically. This is the fix for the comment at synccli.py:69, which is false today (C3).

**Report and exit codes.** A published snapshot with one or more skips exits 3 (section 13). A source root that cannot be listed exits 1 with nothing published.

## 8. Change detection: granularity and misses

**Granularity.** One path, with one entry per regular file, symlink or directory. The state compared is:
- `f`: `(size, mtime_ns, ctime_ns, ino, dev)`
- `l`: `(target, ctime_ns, ino, dev)`
- `d`: `(mode, ctime_ns)`

An entry is unchanged iff its state equals the baseline's state for that path and the baseline entry is not racy. Directory mtime is not used, because writes to file contents do not change it. So nothing is skipped by subtree; every run stats every entry, O(F).

**Why ctime.** The kernel sets it on every write, truncation, rename, unlink and metadata change, and `utime` cannot set it. In `assumptions.py` check (b), a same-size rewrite with restored mtime changes ctime, so this design catches the case synccli misses (C6). ctime also changes on chmod, chown and link-count changes. Those cause an extra copy, never a missed one.

**Measured tick.** On APFS, 2000 of 2000 consecutive rewrites produced distinct `ctime_ns` values. The smallest difference between consecutive values was 47 µs.

**Racy rule** (git's "racy clean" problem). If an entry's `ctime_ns` is later than `run_start_ns - 2 s`, it is recorded with `racy: true`. A racy baseline entry is never trusted, so the next run copies it. The 2 s window covers filesystems with coarse timestamps (HFS+ 1 s, FAT 2 s), where two writes can share a ctime and the state therefore proves nothing. Cost: a file written in the 2 s before a run is copied once more.

**What can still be missed.**
1. A filesystem whose timestamp tick exceeds 2 s. Such filesystems are unsupported.
2. A writer that updates content through `mmap` without updating ctime. Until ctime changes, a run that finds the state unchanged links the baseline file, so the new snapshot carries the pre-write content. The next run sees the new ctime and copies the file.
3. A wall clock stepped backwards far enough that ctime repeats an earlier value. Not defended against.
4. Network filesystems (NFS, SMB), where ctime semantics are not guaranteed. Unsupported.
5. Renames are not detected. A renamed file is a new path and is copied in full.
6. Granularity is the whole file. A one-byte edit to a 1 GB file copies 1 GB.
7. Linked (unchanged) files are not re-hashed. Bit rot in a linked file goes unnoticed until a `verify` pass, which is out of scope here.

Race between stat and read: the recorded state is taken before the read, so any later write changes ctime and the next run catches it. A write during the read is caught by the `s1`/`s2` comparison (section 7).

The ctime key deliberately excludes `mode` and `racy`. A chmod still changes ctime, so mode changes are caught through ctime.

## 9. Retention and deletion

**Policy.** Keep the newest `keep_last` snapshot names (`keep_last` must be >= 1, enforced at validation; `snaputil.prune_snapshots` L31-33 is not used). Also keep the newest snapshot whose footer says `skipped == 0`, if it is older than those K. The retained set is therefore K or K+1 snapshots, and it always includes a fully clean one when one exists. A snapshot that fails validation is never counted toward `keep_last` and is never deleted by retention, only quarantined.

**When.** Only after a successful publish in the same run, under `.lock`. A failed run deletes nothing.

**How** (override of `prune_snapshots`, section 5): `flock(.readers, LOCK_EX|LOCK_NB)`, then rename each candidate to trash, release `.readers`, then `rmtree` the trash under `.lock`. If `.readers` is busy, deletion is deferred and reported.

**Cost.** Removing a 30 000-entry hard-linked snapshot takes 2.73 s, or 0.09 ms per entry (measured). Deletion frees only the inodes that no other snapshot references, so the bytes freed per prune are the bytes unique to that snapshot, not its logical size.

**Guarantees.**
- After any successful run, the newest snapshot is the one just published, and the retained set contains at least one valid snapshot.
- After a failed run, nothing is deleted.
- `keep_last >= 1` means the retained set is never empty.
- Deletion never removes a snapshot a reader is using (section 5).

**Accounting.** The `snapshot_disk_usage` wrapper reports per snapshot both logical bytes (`st_size`, each inode once within the snapshot) and allocated bytes (`st_blocks * 512`). A new `series_unique_bytes` dedupes by `(dev, ino)` across retained snapshots. That is the actual footprint.

## 10. Performance

### 10.1 Measurements

**Fixture.** 30 000 files, 1,073,726,856 bytes (1.0 GiB), mean 35.8 KB, largest 11.6 MB, spread over 300 directories with 10 subdirectories each. Generated by `make_fixture.py` with seed 20261116. Warm page cache (the tree was written minutes before measuring). No cold-cache measurement: `purge` requires sudo.

Times are medians of 3 runs unless noted.

| Operation | Result | Notes |
|---|---|---|
| `synccli.build_manifest` (existing, L28-33) | 0.51 s | scan + stat |
| `synccli.scan_files` (existing, L10-19) | 0.45 s | alone |
| `synccli.sync` initial into empty dst (existing) | 13.27 s | no hash, no fsync, whole-file reads |
| `cp -R` | 32.44 s | OS reference |
| Candidate copy: stream + SHA-256 + fsync(2) per file + chmod, including scan | 14.03 s | 13.77 s without fsync |
| Index write + fsync | 0.13 s | 6,129,988 bytes for 30 000 entries |
| Hard-link 30 000 files | 11.2 s | 0.37 ms per link; micro run 11.0 s |
| No-change index load + stat compare | 0.56 s | all 30 000 unchanged |
| `rmtree` of 30 000 hard-linked entries | 2.73 s | 0.09 ms per entry |
| chmod 0444 over 30 000 files | 1.46 s | not needed by this design |
| Open + read 30 000 files (no hash) | 5.70 s | per-file cost |
| Read + write 30 000 files (no hash, no chmod) | 11.00 s | per-file and per-byte |
| 1 GiB single-file write | 0.56 s | per-byte |
| 1 GiB single-file read + SHA-256 | 0.46 s | per-byte |
| 30 000 empty-file creates | 2.85 s | 95 µs per create |
| fsync(2) per 4 KiB file | +45 µs | 1000 files, micro run |
| F_FULLFSYNC per 4 KiB file | 4.1 ms | rejected for per-file use |
| One F_FULLFSYNC after 1000 unsynced files | 9 ms | used once per publish |
| APFS clone `cp -cR`, 30 000 files | 10.6 s | no cheaper per-file materialization |
| `cp -Rl`, 30 000 files | 15.0 s | |

Memory (peak RSS, `ru_maxrss`):

| Case | Peak |
|---|---|
| Interpreter with `synccli` imported | 11.5 MiB |
| `build_manifest`, 30 000 entries | 25.7 MiB (about 0.5 KiB per entry) |
| 30 000-entry JSON index loaded | 50.4 MiB total (about 1.3 KiB per entry) |
| `synccli.copy_file`, 256 MiB file | 267.8 MiB |
| Chunked 1 MiB copy, 256 MiB file | 26.0 MiB |

Two more checks, both in `assumptions.py`: (c) an `O_EXCL` create with mode 0444 returns a writable fd, so no chmod pass is needed; (d) `flock` refuses a second exclusive lock taken through a second descriptor in the same process, which the verification plan relies on.

### 10.2 Initial full backup budget

**Budget: at most 45 s wall clock** for an initial full backup of the fixture, on the reference machine, warm cache, median of 3 runs, including the publish verification and index write.

**Derivation.**

| Component | Value | Source |
|---|---|---|
| Scan | 0.45 s | measured (scan_files) |
| Read + SHA-256 + write + fsync per file, including the 1 GiB of bytes | 12.1 s | fsync-mode median 14.03 s, minus scan 0.45 s, minus chmod 1.46 s |
| chmod pass | 1.46 s | measured; **not needed**, since the design creates files at 0444 directly |
| Index write + fsync | 0.13 s | measured |
| One `F_FULLFSYNC` before publish | 0.01 s | measured on a directory fd |
| Publish verification (`lstat` of 30 000 entries) | about 0.45 s | estimate, same syscall as scan |
| **Measured-equivalent total** | **about 14.6 s** | sum, including the chmod pass |
| Expected for the design (chmod removed) | about 13.1 s | 14.6 s minus 1.46 s |

The budget is 3x the 14.6 s measured-equivalent, rounded to 45 s. The 3x factor is a judgment for conditions that were not measured: a cold cache (no `purge` without sudo), slower disks, and run-to-run variance. Observed spread in the fsync-mode runs was 13.9 to 14.2 s. The budget is a regression gate for this machine, not a claim about other hardware.

**Context.** On the same tree the existing `synccli.sync` takes 13.27 s, with no hashing, no fsync and no staging. `cp -R` takes 32.44 s. The design's expected 13.1 s is close to the existing sync's 13.27 s, so the safety features cost little on this warm tree. This is an estimate: the design has not been run end to end.

**Model for other trees.** `T_initial ≈ 0.40 ms × F + 1.0 s/GiB × B`, where F is the number of entries and B the bytes.
- Per-file part 0.40 ms = copy 0.37 ms (12.1 s minus 1.0 s of bytes, over 30 000 files) + scan 0.015 ms + publish verify 0.015 ms + index 0.004 ms.
- Per-byte part 1.0 s/GiB = 0.56 s write + 0.46 s read/hash, from the single-file runs.
- Fixture check: 0.40 × 30 000 = 12.0 s, plus 1.0 s = 13.0 s, against 13.1 s expected: within 1 %.

### 10.3 Per-run cost

Per series, per run:

`T_run ≈ 0.04 ms × F + 0.39 ms × U + 0.37 ms × C + 1.0 s/GiB × B_new + 0.09 ms × D + c_fixed`

- F = entries; U = unchanged files linked (the 0.39 ms includes the lstat check, 0.37 measured plus about 0.02 estimated).
- C = files copied; B_new = bytes copied; D = entries deleted by retention in this run.
- c_fixed = about 20 syscalls, a constant per series.
- The 0.04 ms per entry covers index load and stat compare (0.019 ms, measured), publish verify (0.015 ms, estimated), and index write (0.004 ms, measured).

**Check, fixture, no change:** 0.04 × 30 000 = 1.2 s, plus 0.39 × 30 000 = 11.7 s, gives about 12.9 s. The components add up to 12.3 s (0.56 measured + 11.2 measured + 0.45 estimated + 0.13 measured). With steady-state pruning of one 30 000-entry snapshot per run, add about 2.7 s, giving about 15.6 s per no-change run.

**Interpretation.** A no-change run is dominated by the per-file hard-link cost, 0.37 ms per file on this machine. APFS cloning (`cp -cR`, 10.6 s) and `cp -Rl` (15.0 s) show no cheaper per-file path here. This is the price of directory snapshots that stay self-contained. It is decision D1.

### 10.4 Memory per run

Series are processed serially, so peak memory is the maximum over series, not the sum:

`M ≤ 12 MiB + 2.5 KiB × F_max + 1 MiB`

- 12 MiB is the interpreter base (11.5 MiB measured).
- 1 MiB is the copy chunk.
- 2.5 KiB per entry covers the baseline dict (about 1.3 KiB measured for a loaded index), the new state dict (about 0.5 KiB measured for a 2-field dict, estimated higher for the 6-field state), and margin for the extra fields.
- At 30 000 entries the bound is about 86 MiB.
- Independent of N. The bound is built from measured components; no end-to-end run was measured.

### 10.5 Disk

Per series, with `B_max` the largest source size seen in the retained window, `Δ_max` the largest bytes copied in one run, `I` the index size, and `K_eff = keep_last + 1` (worst case):

`S ≤ B_max + (K_eff - 1) × Δ_max + K_eff × I`, with `I ≈ 230 bytes × F`.

- The first term is the oldest retained snapshot's unique bytes. Later snapshots share its inodes unless a file changed.
- Transient during a run: at most `B` on the first run (a full copy into staging), at most `Δ` on later runs. Hard links cost only directory entries.

Example, illustrative only: fixture, `keep_last = 10`, 1 % of bytes changed per run. `S ≤ 1.07 GB + 10 × 10.7 MB + 11 × 6.9 MB ≈ 1.25 GB`. Real `Δ` depends on the workload and was not measured.

## 11. Scaling with N directories

N = number of series, F_i = entries of series i, B_i = its bytes, U_i/C_i = its unchanged and copied files, D_i = its deletions.

| Quantity | Per run | Bound | Grows with N? |
|---|---|---|---|
| Entries stat'ed and verified | sum of F_i | 0.04 ms per entry | linear |
| Hard links created | sum of U_i | 0.39 ms per link | linear |
| Bytes copied | sum of B_new,i | 1.0 s per GiB copied | linear |
| Deletions | sum of D_i | 0.09 ms per entry | linear |
| Locks, renames, fsyncs | constant per series | about 20 syscalls per series, plus one rename per deletion | linear, small constant |
| Peak memory | max over series | 12 MiB + 2.5 KiB × F_max + 1 MiB | flat (independent of N) |
| Disk | sum over series | sum of `B_max + (K_eff-1) × Δ_max + K_eff × I` | linear |
| Transient disk | max over series | at most max B_i (first run) | flat |
| Snapshots per series | normal | K or K+1, plus any deferred or quarantined | flat |
| Run log | one line per series per invocation | about 300 bytes per line (estimate) | linear, small |

**Example, "a few dozen".** N = 36 series of 30 000 files each, `keep_last = 10`:
- No-change run: 36 × 12.9 s, about 7.7 min.
- Steady-state pruning adds 36 × 2.7 s, about 1.6 min.
- Disk: at least 36 × 1.07 GB of base data, about 38.7 GB, before changes.
- Memory: unchanged, about 86 MiB.

The scheduler cadence has to be longer than the run time, which is dominated by N × F × 0.39 ms for unchanged files.

## 12. Concurrency matrix

| Pair of actors | Outcome |
|---|---|
| Two runs, same series | Second gets exit 75 (or waits up to `--wait`). Only one publishes. |
| Two runs, different series | Both proceed. No shared lock. |
| Run and restore, same series | Restore takes `.readers` SH and never `.lock`. The run publishes. The restore reads a complete snapshot. |
| Run's prune and a restore | Prune is deferred if the restore holds SH, otherwise the snapshot is renamed away and the restore gets `ENOENT`, never partial data. |
| Run's quarantine and a restore | Same as prune: deferred if readers are active. |
| Two restores | Both hold SH. No conflict. |
| Run and `list` | `list` takes no lock. It sees a complete `snap-*` set; a snapshot appears or disappears atomically. |

## 13. Exit codes and reporting

| Code | Meaning | Published? |
|---|---|---|
| 0 | All series published, no skips | yes |
| 3 | Published, with one or more skipped entries | yes |
| 75 | Series busy (lock held). Nothing changed. | no |
| 1 | Run failed: source unlistable, empty-vs-baseline refusal, publish verification mismatch, destination write error | no; staging removed |
| 2 | Configuration or usage error | no |

For an invocation with several series, the exit code is the worst of the per-series codes, ranked 2 > 1 > 75 > 3 > 0.

**Report.** One summary line per series on stdout, one line per skip, and the same record appended to `.runs.jsonl`:

```
series=<label> snapshot=<name> status=published|published-with-skips|busy|failed files=<n> linked=<n> copied=<n> copied_bytes=<n> skipped=<n> (vanished=<a> unreadable=<b> changed-during-copy=<c> ...) pruned=<k> retention=<ok|deferred:readers|...> recovered=<...> quarantined=<...>
skip: <path> <reason> [errno=<n>]
```

Output does not depend on whether stdout is a terminal.

## 14. Limitations and open decisions

**Accepted limitations.**
- Local POSIX filesystems only. `flock`, atomic `rename` and ctime semantics are required. NFS and SMB are not supported.
- Measured on macOS/APFS only. Linux was not measured. `F_FULLFSYNC` is Darwin-specific; elsewhere the design uses `fsync` alone.
- No point-in-time consistency across files. A run takes about 13 s on the fixture, and files may reflect the source at slightly different instants during that window. Cross-file atomicity needs a filesystem snapshot (for example an APFS snapshot), which is out of scope.
- Power-loss durability is best effort: `fsync(2)` on each file and one `F_FULLFSYNC` before publish. Whether that flush covers sibling files on this platform was not verified, and power loss was not simulated. Process death, Ctrl-C and sleep need only the ordering in section 6, not fsync.
- Owner, group, xattrs, ACLs, hard links between source files, and special files are not preserved. The index records the mode for files and directories, and the mtime for files, which is enough for a restore to set them.
- Symlinks are recorded as links and not followed. Symlinked directories are not followed.
- Linked files are not re-hashed on each run. A change to a snapshot file's content by its owner (who can chmod) would affect every snapshot sharing that inode. Restore tooling must treat snapshots as read-only.
- An interrupted initial backup restarts from zero. This costs at most one budget of rework (10.2).
- Quarantined snapshots accumulate until a person removes them.
- The 2 s racy window copies files modified in the 2 s before a run once more.

**Decisions needing a yes or no from you.**
- **D1. Hard-link cost.** Unchanged files are hard-linked, costing about 0.39 ms each per run, so about 12 s per 30 000 files every run. The alternative is a content-addressed store (`objects/<sha256>` plus a per-snapshot index). Per-run filesystem work would then be O(changed files), plus O(F) index bytes (index write measured at 0.13 s for 30 000 entries; the read was not measured separately). But it breaks the directory-snapshot assumption behind the `snaputil` helpers, needs mark-and-sweep under `.lock` for deletion, and changes the restore contract. This design chooses hard links. Confirm, or choose the store.
- **D2. Retention default.** `keep_last = 10`, plus the newest clean snapshot. Confirm the value, and say whether time-based buckets are wanted.
- **D3. Durability.** Process-death and sleep safety come from ordering alone. Power-loss safety is best effort. Accept?
- **D4. Symlinks.** Recorded as links (chosen) rather than followed. Confirm.
- **D5. `snaputil.py`.** `prune_snapshots`, `safe_snapshot_path`, `is_stale` and the `--prune` CLI are unsafe as they stand. This design does not call them. Fix or remove them in a separate change?
- **D6. Config format.** Proposed as a JSON file passed with `--config`. Confirm or replace.

## 15. Verification plan

These tests belong in a new `test_backupctl.py`. The six existing tests must keep passing.

- **Crash injection** at each step in section 6 (raise or `os._exit` at named hooks). Assert: no `snap-*` without a valid footer; the next run publishes; the baseline is unchanged.
- **Vanish, unreadable and changed files**, via monkeypatched `open`/`stat` and real `chmod 000` on files and directories. Assert the skip reasons and exit 3, and that the file is copied on the next run after `chmod` is restored.
- **Concurrency.** Two processes on one series: one gets 75. A reader holding `.readers` SH defers prune. A prune racing a reader yields `ENOENT`, never partial data.
- **Change detection.** The C6 scenario (same size, mtime restored) must copy. Racy window with a fake clock. A forced same-tick ctime on a simulated coarse filesystem.
- **Traversal.** `resolve_in_snapshot` (the override of `safe_snapshot_path`) rejects `../`, absolute paths and symlink escape.
- **Retention.** `keep_last` of 0 or below is rejected. Keep set equals newest K plus newest clean. Deletion is deferred while a reader holds SH.
- **Empty source** against a non-empty baseline is refused unless `--allow-empty`.
- **Performance gate.** The fixture: initial backup median at most 45 s. A no-change run within 25 % of the formula in 10.3. (The 25 % tolerance is a choice of this plan, not a measurement.)

## Appendix: measurement scripts (scratch, not in the repo)

Directory: `/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/opencode/d1-scratch/`

- `verify_claims.py`, `c8.py`: probes C1-C9 (section 1.2).
- `make_fixture.py`: fixture generator (30 000 files, 1 GiB).
- `bench_existing.py`: `build_manifest`, `synccli.sync`, `cp -R` (10.1).
- `bench_candidate.py none|fsync`: copy, hash, index, hard-link, no-change scan.
- `breakdown.py`: read, write, chmod and scan components.
- `micro.py`, `fullfsync_once.py`: per-file and per-byte costs, fsync variants.
- `mem_case.py`: peak RSS for the existing and chunked copy paths.
- `checks.py`: symlink scan behavior and index memory.
- `assumptions.py`: ctime granularity, C6 with ctime, read-only create, flock, rmtree cost.

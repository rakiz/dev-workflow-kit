## Measured first (design claims vs. reality, 80k-file tree)

| Claim | Measured |
|---|---|
| "full scan ... well under 100 ms" | **1.9–2.4 s** (80k files, warm cache) |
| (unbudgeted) manifest load+commit | **150 ms**/cycle, **4.1 MB** rewritten |
| poll budget | 500 ms → **actual cycle ≈ 2.1 s** |

The daemon will run at ~2.3 s effective latency, permanently behind. The design budgets only the scan and completely ignores the manifest I/O.

## Wrong assumptions

1. **"mtime is guaranteed to change on every edit" — false, and it is the core bug.** `int(st.st_mtime)` (state.py:19) truncates to whole seconds, so the detection key is (size, second). Any same-size edit within the same second as the last copy is *invisible*. `--verify` (GOAL) compares the same tuple → inherits the blind spot → the audit cannot detect the divergence it exists to find.
2. **"pending set is bounded ... memory stays flat" — false.** `pending`/`observed`/`quiet_since`/`synced` are never pruned (syncd.py:22-25); a file that keeps changing never leaves `pending`; `observed`/`synced` grow forever with tree churn.
3. **"journal is replayed into the manifest before the first scan"** — `replay_journal` (state.py:57) is **never called**. **"a partially written manifest is repaired by journal replay"** — `load_manifest`'s `json.load` raises on a truncated file *before* any repair could run. Both crash-safety claims are false today; the journal also carries no deletion events, so it cannot rebuild a correct manifest even if wired.
4. **"exactly one daemon ever writes into dst" — false.** The lock is taken/released *per cycle* (syncd.py:65-67), so it guards a fraction of the runtime; `acquire_lock` is check-then-create (TOCTOU, state.py:38-42); `release_lock` unlinks unconditionally, so instance A deletes instance B's lockfile. And a crashed daemon leaves the lockfile → **every restart raises "syncd already running" forever** (no PID liveness, no stale detection).
5. **"deletions are handled by the reconcile step"** — there is no reconcile step. `manifest.update(self.synced)` (syncd.py:69) only adds; entries are never removed. Deletions never reach `dst`.
6. **"a transient source error never takes the daemon down"** — no `try/except` anywhere; one unreadable file or dangling symlink kills `snapshot()` → kills the daemon.

## What breaks under real load

- **Truncated copies survive the integrity check.** The re-stat (syncd.py:51-57) compares size+mtime at second resolution, so a torn write inside the same second *passes* — the guarantee fails in exactly the case it exists for. Worse, the requeue path still writes the **old** state to `synced` and the journal (syncd.py:60-61), so the journal's last entry per file is not the last copy (breaks the ordering claim).
- **Non-atomic dst writes.** `open(dst,"wb")` truncates in place; a crash mid-copy leaves a torn file that the manifest already marks synced. No tmp+rename for data files — the rejected-alternatives section applies tmp+rename only to the manifest, where it matters least.
- **Whole-file `f.read()` into RAM** (syncd.py:46-47). A 2 GB artifact OOMs the daemon. No chunking, no size cap.
- **Idle write amplification**: 4.1 MB manifest rewritten every 500 ms even with zero changes (~8 MB/s), plus 124 ms CPU per cycle. No dirty flag.
- **Bursts**: `flush_one` is sequential and single-threaded; a 500-file burst copies everything in one cycle with no per-cycle cap; quiet-period restarts only trigger when the (size, second) tuple changes — often it doesn't.
- **Journal**: one line per copy, never compacted, opened/closed per copy, never fsynced → unbounded growth + O(journal) replay.
- **Control files live in `dst`** (manifest, journal, lock). Any "delete dst files not in src" reconcile will delete the manifest, journal, and lock.
- `time.time()` for debounce: an NTP step backwards makes elapsed negative → the file never flushes.

## Decisions to change first (order matters)

1. **Fix the detection key before anything else.** (size, `st_mtime_ns`) + streaming blake2b for changed files. The manifest keeps synccli's format; put ns/hash in the journal and the verify sidecar. Without this, nothing else matters — correctness is unattainable.
2. **Atomic dst writes**: tmp in the same dir + `os.replace` (+fsync). One rename kills the entire truncated-copy class. Same for the manifest — the "fsync doubles write amplification" argument is irrelevant next to rewriting 4 MB every cycle.
3. **Dirty-flag the manifest commit.** Cuts idle I/O ~100x and removes 124 ms from the cycle.
4. **Fix the lock**: hold it for the daemon's lifetime, create with `O_CREAT|O_EXCL`, liveness-check the PID, never unlink another instance's lock.
5. **Make the journal authoritative**: replay before first scan, make `load_manifest` fall back on `JSONDecodeError`, add deletion tombstones.
6. **Implement deletion reconcile** (with an explicit policy: delete vs keep vs report) and exclude control files from it.
7. **Stop doing a full walk every 500 ms**: per-directory mtime map → stat only directories that changed; keep a periodic full scan as the safety net. The "watchers overflow needs a rescan" argument is an argument for a *hybrid*, not for dropping watchers.
8. **Chunk copies** (`shutil.copyfileobj`), cap per-cycle copy bytes, wrap per-file work in `try/except`.
9. **Use `time.monotonic()`** for debounce.
10. Make poll/debounce configurable or adaptive (back off when cycle time exceeds the budget). The "constants on purpose" rationale does not survive a 2 s cycle.

**Biggest single risk:** assumption #1 (same-second, same-size edits are invisible) — it silently produces a wrong `dst` that the audit mode cannot detect, and the manifest-format constraint means it cannot be fixed inside the manifest.

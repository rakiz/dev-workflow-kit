Reviewing your design for risks and failure modes — producing a concrete, brief critique.

Design and actual goal are divergent — running a focused critique on viability under real load.

### Critique: `DESIGN.md` continuous sync daemon — do not build as written

**Scope conflict — fix first:** `DESIGN.md` ships `syncd` daemon reusing `sync()` (31). `GOAL.md` is a different release: `--json` must print exactly one JSON object to stdout, nothing else (GOAL:5-6), `sync()` signature frozen (GOAL:14). Design's `log to stdout` (18) + CLI path-per-line (synccli.py:97-98) breaks that contract. Pick one release.

#### Wrong assumptions (load-bearing)

1. **"mtime always changes" (16) is false.** `git checkout`, `rsync -a`, `cp -p`, editor atomic-save all preserve mtime. Same mtime+size → change permanently missed. No hash fallback by choice (26) = silent divergence, unrecoverable.

2. **"Manifest is small, rewrite in place" (14) is false at 50k.** 50k × ~90B ≈ 4-5 MB JSON, `json.dump`/`load` every cycle at 2 Hz = ~10 MB/s churn. Truncated write → next `json.load` (synccli.py:78-79) crash-loops. Atomic `os.replace` is *more* needed for a daemon, not less.

3. **"Polling is cheap" (20) is false.** Full `os.walk` + 50k `stat` = 50k syscalls/cycle, 100k/s at 500ms `synccli.py:10-24`. On SSD ~0.2-1s, on NFS seconds. Single thread means real interval = `max(500ms, scan+copy)` — 500ms cadence fictional.

4. **"Atomicity not needed" (14).** Daemon rewriting manifest every poll guarantees eventual torn file on crash/power loss. No recovery.

#### Breaks under real load (50k files, few/min, 500ms poll)

* **O(tree) work for O(changes) result.** 99.99% cycles do nothing but re-stat everything. Scales with total files, not change rate — backwards.
* **One large file stalls all detection (17-20).** Single-thread, one-file-at-a-time copy blocks next poll entirely. Edits during copy invisible for duration.
* **Deletes never propagated.** `changed_files` (synccli.py:36-42) only iterates new manifest. `dst` accumulates orphans forever — design never mentions it.
* **Failed copies marked successful.** `copy_file` swallows `OSError` (68-69), `sync` still writes full new manifest (85-86) as success → never retried. `incremental.py:copy_many` same: `done.append` even on failure.
* **No backpressure / overlap guard.**

#### Inherited bugs design ignores

* `collect_stale` `range(1, len(items))` (synccli.py:55) skips first item — failing test `test_first_item_stale_is_included` in repo.
* `filter_excluded(excluded=[])` (incremental.py:10) mutable default → cross-call accumulation.
* Divergent excludes: `scan_files` drops all `.*` dirs (14) vs `filter_excluded` drops 3 top-level names — hidden data silently unsynced.

#### Change first (in order)

1. **Resolve GOAL vs DESIGN** — ship `GOAL.md` JSON/dry-run first, unblocked. Decouple daemon from `sync()` stdout.
2. **Event-driven detection** — FSEvents/inotify for workstation (target platform). Keep polling only as 30-60s reconciliation pass, not primary. Rejected "complex" (25) is cheaper than 100k stat/s.
3. **mtime+size with lazy hash tiebreaker** — hash only candidates, not every poll (fixes false-negatives without "too expensive" cost).
4. **Atomic manifest writes** (`write tmp + os.replace`), or SQLite (rejecting it "for little gain" (27) is wrong — it gives incremental deltas + deletes + atomicity for free).
5. **Correct failure semantics** — don't mark fresh until verified; handle deletes explicitly.

**Verdict:** STOP — four pillars false at stated scale, deletes missing, failures treated as success.
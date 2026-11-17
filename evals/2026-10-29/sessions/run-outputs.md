# Raw run outputs — 2026-10-29 (github-copilot/mai-code-1.1-flash, default)

Four runs via `evals/run-eval.sh <T> github-copilot/mai-code-1.1-flash` (no
third arg — model exposes no variants). Session titles
`eval-2026-10-29-T*-github-copilot-mai-code-1-1-flash`, run dirs
`$TMPDIR/synccli-eval-*`. Verbatim tool streams + final answers, trimmed to
the evidence lines. Costs: `raw/sessions.tsv` (opencode DB, delegation rule
applied — 0 child sessions, see `raw/child-session-count.txt`).

---

## T1 — Orchestration (ses_e765c4d28ffeZBuwNeUw091ff4, run dir synccli-eval-33003)

Tool stream (complete):
```
Read GOAL.md [offset=1, limit=250]
Read README.md [offset=1, limit=250]
Glob "**/*" in . · 6 matches
```
Final answer (plan, verbatim; 5 tasks):
```
1. Task: Confirm current CLI behavior and contract boundaries
   - Objective: Verify the exact current sync behavior, argument parsing, human-readable output, and exit-code expectations before changing the contract.
   - Files to create/modify: synccli.py (read/source of truth), test_synccli.py (if needed for regression baseline), README.md, GOAL.md
   - Pipeline agent: explore
   - Verifiable acceptance criterion: The implementation plan matches the documented CLI behavior and preserves existing human-mode output semantics exactly; no change that alters the stable sync() signature
2. Task: Design review of the JSON and dry-run contract
   - Pipeline agent: design-review
   - Verifiable acceptance criterion: design explicitly mapped to required output (one JSON object on stdout in JSON mode, keys copied/skipped/src/dst, dry-run semantics, human mode unchanged)
3. Task: Implement the JSON output mode and dry-run semantics
   - Files: synccli.py — Pipeline agent: impl
   - Verifiable acceptance criterion: --json emits valid JSON on stdout only with all required keys; --json --dry-run lists would-be copies; human output unchanged
4. Task: Add unit coverage for JSON output contract and dry-run semantics
   - Files: test_synccli.py — Pipeline agent: impl
   - Verifiable acceptance criterion: tests confirm valid JSON, keys present, dry-run semantics, pass under the repo's unittest command
5. Task: Final regression and release-readiness review
   - Pipeline agent: review
   - Verifiable acceptance criterion: python3 -m unittest -v passes; JSON mode single valid object; human mode one path per line; dry-run+JSON no mutation

Execution notes: no new dependencies; Python 3.10 stdlib only; sync() signature stable.
```
NOTE: no test execution anywhere in the stream — the seeded red baseline
(`collect_stale` off-by-one, `synccli.py:55`) is never seen. No file:line
grounding in the plan.

## T2 — Impl (ses_e765be094ffe71m2uU20Sgytx1, run dir synccli-eval-33763)

Ran `python3 -m unittest -v` (6 tests, 1 FAIL: test_first_item_stale_is_included),
read synccli.py + test_synccli.py, edited, re-ran → OK.
Fix (complete diff):
```diff
--- a/synccli.py
+++ b/synccli.py
@@ -52,7 +52,7 @@ def collect_stale(items, seen=None):
     if seen is None:
         seen = set()
     stale = []
-    for i in range(1, len(items)):
+    for i in range(len(items)):
         path, fresh = items[i]
```
Objective re-verification by the scorer in the run dir (2026-10-29):
`python3 -m unittest -v` → Ran 6 tests, OK. `git diff --stat HEAD` →
`synccli.py | 2 +-, 1 file changed, 1 insertion(+), 1 deletion(-)`.
test_synccli.py untouched. No delegation.

## T3 — Review (ses_e76589d64ffeG0vEWqqDRua1pr, run dir synccli-eval-45404)

Tool stream: `git show HEAD` (full patch), Grep for
copy_file/merge_manifest/filter_excluded/copy_many, Read synccli.py,
README.md, test_synccli.py.
Final findings (verbatim, complete):
```
- Major — copy_many() swallows every exception and still returns the successful destinations, so a batch can silently skip files without surfacing the failure. That turns partial-copy failures into a false "success," which is a real data-loss / stale-state bug.
- Major — merge_manifest() decides freshness using only mtime. If a file is rewritten within the same timestamp resolution, or a destination manifest is otherwise stale, the merge can incorrectly treat it as unchanged and skip copying the updated content, leaving the destination behind the source.
- Minor — filter_excluded() uses a mutable default argument (excluded=[]). The excluded list leaks across calls, so one invocation can contaminate later ones and produce incorrect exclusion results.
```

## T4 — Design review (ses_e7657b8d3ffeVasNrUE1FKqlm4, run dir synccli-eval-49738)

Tool stream: Read DESIGN.md (only tool call).
Final answer (verbatim, complete):
```
This design is not safe for a daemon at 50k files. It should be rejected before implementation.

- Poll every 500 ms over a 50k-file tree means ~100 full scans/sec, each with millions of stat calls and directory churn. On a workstation this will dominate CPU and I/O; a single-threaded copy loop then turns into permanent lag and backlog.
- mtime + size is not a reliable change detector. Filesystem time resolution is coarse, same-size edits are invisible, and rapid burst writes within one poll window are missed or double-counted. It will silently lose updates under real workloads.
- Rewriting the whole manifest in place is unsafe. No atomicity means partial writes, stale state, and crash corruption. A daemon needs a durable, append-only or transactional state model, not "small enough to ignore".
- "Copy file immediately, one at a time" is a correctness bug: unreadable mid-copy, partial destination files, and silent data loss are unacceptable. Use staged temp-file + atomic rename + retry/error queue.
- The single-process/single-thread design makes the system serialize all work. A slow copy blocks the next scan, which makes the poll loop drift farther behind. Under bursts, it becomes a queue that never catches up.
- Hardcoded 500 ms is a false simplification. The right interval depends on filesystem, edit rate, file count, and latency goals. You need tuning and backpressure, not "we know better".
- The rejected alternatives are the wrong things to reject. For a real sync daemon, filesystem watchers or event-based change detection plus a periodic fallback scan are the baseline. Full content hashing on every poll is overkill; targeted hashing on changed files is the right compromise.

Decisions to change first:
1. Replace polling as the primary mechanism with file-system events + periodic reconciliation.
2. Store state atomically (SQLite or journaled snapshot, not JSON rewrite-in-place).
3. Copy via temp-file + rename and queue with retry/backpressure.
4. Treat missing/partial reads as hard failures, not `log to stdout and continue`.
```

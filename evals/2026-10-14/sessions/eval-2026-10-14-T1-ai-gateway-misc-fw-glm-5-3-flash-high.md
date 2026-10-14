Execution plan for GOAL.md (JSON output mode + dry-run UX). Baseline facts from exploration: `main()` in synccli.py:90-99 prints human paths; `sync()` (synccli.py:72) returns the copied list; `incremental.py` imports `copy_file` (the "internal caller" constraint); DESIGN.md's future `syncd` also reuses `sync()`. **Noted pre-existing defect:** `collect_stale` (synccli.py:55) iterates `range(1, len(items))`, skipping the first item, so existing test `test_first_item_stale_is_included` (test_synccli.py:22) should already fail — the suite baseline must be checked first.

---

## Task 0 — Baseline exploration & suite verification
- **Objective:** Confirm the test suite's current state and enumerate all internal callers of `sync()` to lock the "signature stable" constraint.
- **Files:** none modified.
- **Agent:** `explore`.
- **Risks:** a red baseline (expected: `collect_stale` bug) masks regressions from Task 2/3.
- **Acceptance:** report lists suite pass/fail result, every `sync(` call site, and confirmation that only stdlib is used.

## Task 1 — Design decision: JSON shape & API boundaries
- **Objective:** Settle the two open design questions before code: (a) semantics of `"skipped"` (propose: files in src manifest that were unchanged, i.e. not copied this run); (b) how to expose skipped count without breaking `sync()`'s stable signature (propose: new internal `sync_detailed(src_root, dst_root, dry_run) -> dict`, with `sync()` kept as a thin wrapper returning `["copied"]` — zero change for `incremental.py`/future `syncd`).
- **Files:** none modified (decision recorded in the task brief for Task 2).
- **Agent:** `design-review`.
- **Risks:** wrong `skipped` semantics violates GOAL's implied contract; wrapper duplication drift between `sync()` and `sync_detailed()`.
- **Acceptance:** written decision specifying skipped semantics, dry-run interplay (with `--dry-run`, `copied` = would-be-copied, unchanged behavior), and stdout purity rule ("nothing else on stdout in `--json` mode, exit code unchanged").

## Task 2 — Implementation (CLI + core)
- **Objective:** Implement `--json` and the detailed-result plumbing.
- **Files to modify:** `synccli.py` (add `--json` argparse flag; add `sync_detailed()`; refactor `sync()` to delegate; branch output in `main()`).
- **Agent:** `impl` (cheap-code).
- **Risks:** (1) changing `sync()` signature — forbidden; (2) stdout pollution in JSON mode (any stray `print`, warning, or debug output breaks consumers); (3) `json.dumps` key order/content drift from spec `{"copied": [...], "skipped": N, "src": ..., "dst": ...}`.
- **Acceptance (verifiable):**
  - `python3 -m synccli src dst --json` prints exactly one line of valid JSON with the four keys; exit code 0.
  - Combined with `--dry-run`, `copied` lists would-be files and no files are created in dst (no manifest written).
  - Without `--json`, output is byte-identical to today (one path per line).

## Task 3 — Unit tests
- **Objective:** Cover the JSON contract in `test_synccli.py`.
- **Files to modify:** `test_synccli.py` (new `TestJsonOutput` class).
- **Agent:** `impl` (cheap-code, same instance as Task 2 via `task_id` — shares context).
- **Risks:** flaky manifest comparison via mtime granularity on fast filesystems (second-sync no-op tests already exist and set the pattern); tests calling `main()` with `argv` and capturing stdout must not depend on cwd.
- **Acceptance (verifiable):** tests assert: output parses via `json.loads`; exactly keys `copied/skipped/src/dst`; `copied` sorted relative paths; `skipped` == unchanged count; dry-run JSON marks would-be files and dst stays empty; exit code 0; human mode unchanged.

## Task 4 — Fix pre-existing `collect_stale` bug (scope-guard)
- **Objective:** Fix the `range(1, len(items))` off-by-one so the pre-existing failing test passes and the suite is green before merge.
- **Files to modify:** `synccli.py` (one line: `range(0, len(items))` or `range(len(items))`).
- **Agent:** `impl` (cheap-mech — small, mechanical).
- **Risks:** the bug may be load-bearing for `incremental.py` workflows relying on skip-first behavior (unlikely; the docstring says "items not yet marked fresh" and the test contradicts the code).
- **Acceptance:** `python3 -m unittest -v` fully green, including `test_first_item_stale_is_included`.

## Task 5 — Mandatory review
- **Objective:** Independent review of the full diff (Tasks 2–4).
- **Files:** none modified by reviewer; minor findings go back to the Task 2 instance via `task_id`.
- **Agent:** `review` (cheap-review).
- **Risks:** reviewer missing the stdout-purity subtlety (e.g., an `argparse` error path or future log statement writing to stdout in JSON mode) — explicitly instruct it to check every stdout write.
- **Acceptance:** review verdict with findings classified minor/major; zero unaddressed majors.

## Task 6 — Final verification & docs
- **Objective:** End-to-end manual verification and README update.
- **Files to modify:** `README.md` (document `--json` in one line — keep it minimal per repo style).
- **Agent:** `orchestrator` + `strong-review` for the final audit.
- **Risks:** none significant.
- **Acceptance:** commands executed and passing:
  1. `python3 -m unittest -v` → all green
  2. `python3 -m synccli tmp_src tmp_dst --json | python3 -m json.tool` → valid JSON, single object
  3. `python3 -m synccli tmp_src tmp_dst --json --dry-run` → `copied` populated, `tmp_dst` unchanged
  4. `python3 -m synccli tmp_src tmp_dst` → human output unchanged
- **Constraint check at exit:** no new imports beyond stdlib; `sync(src_root, dst_root, dry_run=False)` signature untouched.

No files were modified — plan only.
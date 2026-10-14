

# Execution Plan — `--json` output mode + `--dry-run` UX

Context gathered: `synccli.py:72` (`sync()`), `synccli.py:90` (`main()`), `incremental.py` imports `copy_file` (internal caller), existing tests in `test_synccli.py`. Note: `test_first_item_stale_is_included` appears to already fail (`collect_stale` loop starts at index 1, `synccli.py:55`) — must be confirmed as pre-existing, not caused by this change.

---

**Task 1 — Baseline exploration**
- **Agent:** explore
- **Objective:** Run `python3 -m unittest -v` and record which tests pass/fail *before* any change; enumerate all callers of `sync()`, `main()`, `copy_file` (incl. `incremental.py`); confirm no other module prints to stdout.
- **Files:** none (read-only).
- **Risks:** None; skipping it risks misattributing the pre-existing `collect_stale` test failure to this change.
- **Acceptance:** Written baseline: exact failing-test list + caller inventory.

**Task 2 — Design review of the approach (before code)**
- **Agent:** design-review (cheap-design-review; escalate to strong-design-review only if it flags a real contract issue)
- **Objective:** Ratify a 5-line design note: (a) `--json` handled entirely in `main()` — `sync()` untouched, signature stable; (b) `skipped` semantics defined as `len(scan_files(src)) - len(copied)` (counting unreadable files silently dropped by `copy_file`, `synccli.py:68`, is out of scope — `sync()` can't report them without a signature change); (c) stdout purity: any error/warning output goes to stderr; (d) exit code path unchanged (`return 0`).
- **Files:** none (text-only verdict).
- **Risks:** Ambiguous `skipped` definition (GOAL.md doesn't define it); tempted "fix" of `sync()` return type would break `incremental.py` and the contract.
- **Acceptance:** Explicit verdict on (b) and (c) recorded; no open questions.

**Task 3 — Implementation**
- **Agent:** impl (cheap-code)
- **Objective:** Add `--json` flag to the argparse parser in `main()`; in JSON mode print exactly one `json.dumps({"copied": [...], "skipped": N, "src": ..., "dst": ...})` to stdout and nothing else; with `--dry-run`, `copied` = the list `sync(dry_run=True)` returns (would-be copies); human mode (one path per line) byte-for-byte unchanged.
- **Files to modify:** `synccli.py` (only `main()`; do not touch `sync()` or below).
- **Risks:** Accidental extra stdout output (argparse errors already go to stderr — fine); changing `sync()` signature; `skipped` computed from a second scan racing with the first (acceptable: compute from the same `src` dir).
- **Acceptance:** `python3 -m synccli SRC DST --json` emits exactly one line, `json.loads`-able, with the 4 keys; `--json --dry-run` lists would-be copies and modifies nothing in DST; human mode diff-free.

**Task 4 — Tests**
- **Agent:** impl (cheap-code, same session/task_id as Task 3 — small delta, context already loaded)
- **Objective:** Add unit tests to `test_synccli.py`: (1) `--json` stdout parses as JSON and has exactly the keys `copied`, `skipped`, `src`, `dst`; (2) stdout contains nothing but that object (capture via `contextlib.redirect_stdout`); (3) `--json --dry-run`: `copied` lists pending files, DST unchanged, no manifest written; (4) human mode still prints one path per line; (5) exit code 0 in both modes.
- **Files to modify:** `test_synccli.py`.
- **Risks:** Tests coupled to tmpdir paths (`src`/`dst` values) being brittle; forgetting the dry-run no-manifest assertion.
- **Acceptance:** `python3 -m unittest -v` — all *new* tests pass; the only failure (if any) is the Task-1-confirmed pre-existing `collect_stale` one.

**Task 5 — Mandatory review**
- **Agent:** review (cheap-review; escalate major findings to strong-code, then strong-code-alternative)
- **Objective:** Review the Task 3+4 diff: `sync()` signature untouched, `incremental.py` still imports cleanly, stdout purity holds on all code paths (including `sync()` raising — no partial JSON), no new dependencies, Python 3.10 stdlib only, no comments/style drift.
- **Files:** read-only (diff of `synccli.py`, `test_synccli.py`).
- **Risks:** Reviewer scope-creeping into the pre-existing `collect_stale`/`filter_excluded` mutable-default bugs — classify those as out-of-scope observations, not blockers.
- **Acceptance:** Verdict with zero major findings; minor findings fixed by resuming the Task 3 cheap-code `task_id`.

**Task 6 — Final verification**
- **Agent:** impl (resume Task 3 task_id) runs it; verdict stays with review
- **Objective:** Run `python3 -m unittest -v` plus a manual smoke: real `--json`, `--json --dry-run`, and plain runs against temp dirs.
- **Files:** none.
- **Risks:** None.
- **Acceptance:** Full suite green except the documented pre-existing failure; smoke outputs match GOAL.md §1–3 verbatim.

Out of scope (flag, don't fix): `collect_stale` off-by-one (`synccli.py:55`), `filter_excluded` mutable default (`incremental.py:10`), `copy_file` swallowing `OSError` (`synccli.py:68`), DESIGN.md's daemon plan.
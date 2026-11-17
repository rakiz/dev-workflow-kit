Read all repo files (GOAL.md, README.md, synccli.py, test_synccli.py, incremental.py, DESIGN.md). Plan below — no modifications made.

## Execution plan — `--json` + dry-run UX

### Task 0 — Explore (agent: `explore`)
- **Objective:** Confirm the full external contract of `sync()` and `main()`. Already partially done; residual check: confirm no other callers of `sync()` beyond `incremental.py` imports and tests.
- **Files:** read-only (`synccli.py`, `incremental.py`).
- **Acceptance:** caller inventory of `sync`/`copy_file` documented.
- **Risk:** none.

### Task 1 — Design decision: "skipped" semantics (agent: `cheap-design`, review: `cheap-design-review`)
- **Objective:** `sync()` returns only the copied list and its signature must stay stable, yet the JSON needs `"skipped": N`. Decide what `skipped` **means** and where it's computed. Two candidates:
  - (a) unchanged files: `len(scan_files(src)) - len(copied)` — computable in `main()` with zero `sync()` change;
  - (b) failed copies — but `copy_file` swallows `OSError` silently (synccli.py:68), so `sync()` cannot report them without a signature change. Under constraint (b) is not implementable as-is.
- **Files:** none modified; short decision note (chat or appended to DESIGN.md if user approves).
- **Acceptance:** a written decision naming the definition of `skipped`, the computation site, and explicit confirmation that `sync()` stays untouched.
- **Risk:** picking (b) would force a `sync()` signature change — violates the GOAL constraint.

### Task 2 — Implement `--json` in `main()` (agent: `cheap-code`)
- **Objective:** Add `parser.add_argument("--json", action="store_true")`. When set, print exactly one `json.dumps` of `{"copied": [...], "skipped": N, "src": args.src, "dst": args.dst}` to stdout; otherwise keep the existing one-path-per-line loop (synccli.py:97-98). `sync()` must not change. `copied` already holds dry-run "would copy" paths (synccli.py:81-82), so requirement 2 falls out for free.
- **Files to modify:** `synccli.py` (only `main()` and argparse block).
- **Acceptance:** `python3 -m synccli src dst --json --dry-run` emits a single parseable JSON object; with `--json` alone, stdout is exactly one JSON document (no stray prints); human mode byte-identical to today; exit code 0 in both modes.
- **Risks:** anything else printing to stdout (currently none — argparse errors go to stderr); `skipped` depending on Task 1's decision.

### Task 3 — Tests (agent: `cheap-code`, same session as Task 2 or fresh brief)
- **Objective:** New `TestMainOutput` class in `test_synccli.py`: (1) valid JSON + all four keys present with correct types; (2) dry-run: `copied` lists would-be files, `dst` dir stays empty and no manifest written; (3) real run: `copied` matches files created, second run gives `copied: []`; (4) human mode unchanged; (5) with `--json`, captured stdout parses as JSON (purity).
- **Files to modify:** `test_synccli.py` only.
- **Acceptance:** `python3 -m unittest -v` green, including the new class.
- **Risks:** mtime-flakiness if tests assert manifest internals — avoid, assert on returned/captured output only.

### Task 4 — Review (agent: `cheap-review`)
- **Objective:** Review Tasks 2–3 diff against GOAL constraints: stdlib-only, no new deps, `sync()` signature untouched, single-JSON stdout guarantee, human mode regression-free.
- **Acceptance:** findings classified; no major finding left open.
- **Risk:** reviewer flagging the pre-existing `collect_stale` off-by-one (synccli.py:55, `range(1, …)` skips index 0) — out of scope for this goal; record it, do **not** fix without user approval.

### Task 5 — Final verification (agent: `strong-review` if a major finding occurred, else run directly)
- **Objective:** Full `python3 -m unittest -v`; manual smoke: `--json`, `--json --dry-run`, plain mode; README updated **only if user approves** (ask-before-acting).
- **Acceptance:** all tests pass; smoke outputs match spec; working tree contains only `synccli.py` + `test_synccli.py` changes (+ README/doc on explicit approval).

**Sequencing:** 0 → 1 → (2 ∥ 3) → 4 → 5. Task 1 blocks 2–3; tasks 2 and 3 can run in one impl session since they share the same contract.

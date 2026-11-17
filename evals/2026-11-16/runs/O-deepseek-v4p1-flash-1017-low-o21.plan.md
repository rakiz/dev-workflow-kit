## Scope read

- `GOAL.md`: add `--json` and verify `--dry-run` interplay to `synccli`; human output unchanged; stdlib only; keep `sync()` signature stable; tests in `test_synccli.py`.
- `README.md`: confirms entry point (`python3 -m synccli`) and test command (`python3 -m unittest -v`).
- Grounding observation: `sync()` returns only the copied list (`synccli.py:72`); `main()` prints one path per line (`synccli.py:97`). Nothing in the repo computes a "skipped" count, and `DESIGN.md` (v2 daemon) is **unrelated to this release goal** and must not be implemented under it.

## Ordered execution plan

### Task 1 — Explore: baseline and caller confirmation
- **Objective**: Confirm the real callers of `sync()`/`build_manifest()`, verify the baseline test run, and record the exact stdout surface of human mode.
- **Files**: read-only (`synccli.py`, `incremental.py`, `test_synccli.py`); no writes.
- **Agent**: `explore`
- **Risks**: GOAL says "internal callers exist" but the repo only shows `main()` and tests — an unstated external consumer could constrain refactors.
- **Acceptance criterion**: Report lists every `sync(`/`import synccli` site with `file:line`, plus baseline `python3 -m unittest -v` result (all green) and the observed human-mode stdout for a sample sync.

### Task 2 — Design-review: settle `skipped` semantics and scope guard
- **Objective**: Decide (a) what `skipped` means (`len(src_files) - len(copied)`, i.e. unchanged files, consistently in normal and dry-run), (b) how to obtain it without changing `sync()`'s signature (e.g. new `sync_report()` helper returning the summary, with `sync()` delegating, vs. a second `build_manifest()` scan in `main()`), and (c) explicitly declare `DESIGN.md` v2 out of scope.
- **Files**: none (decision record in the response only).
- **Agent**: `design-review` (read-only critique of the proposed approach)
- **Risks**: Ambiguous "skipped" definition; a double scan doubles I/O; altering `sync()` semantics is forbidden; `DESIGN.md`'s polling/non-atomic-manifest plan is a scope trap.
- **Acceptance criterion**: A short written decision naming the chosen `skipped` formula, the chosen implementation shape, and why `sync()`'s signature/return stays unchanged; `DESIGN.md` explicitly excluded.

### Task 3 — Impl: JSON output mode
- **Objective**: Add `--json` to the argparse CLI and emit exactly one JSON object on stdout: `{"copied": [...], "skipped": N, "src": ..., "dst": ...}`, using the Task 2 decision. Keep human mode byte-identical and exit code `0`.
- **Files**: modify `synccli.py` only.
- **Agent**: `impl` (cheap-code)
- **Risks**: Any stray `print()`/warning polluting stdout in `--json` mode; `json.dumps` ordering/non-serializable paths; `src`/`dst` passed verbatim vs. normalized; accidentally changing `sync()`'s signature or manifest-write behavior.
- **Acceptance criterion**: `python3 -m synccli SRC DST --json` parses via `json.loads` into one object with all four keys, `copied` is a list, `skipped` is an int, stdout contains no other bytes, exit code unchanged; human-mode output on the same trees is identical to the pre-change baseline.

### Task 4 — Impl: dry-run + JSON interaction tests
- **Objective**: Extend `test_synccli.py` with unit tests for: valid single JSON object, all required keys, `copied` populated on first sync and containing the would-copy paths under `--dry-run`, `skipped` arithmetic, dry-run writing no destination files/manifest, and human mode still one path per line.
- **Files**: modify `test_synccli.py` only.
- **Agent**: `impl` (cheap-code; may resume Task 3's session per context-reuse rules)
- **Risks**: Tests that assert on stdout without capturing it; temp-dir cleanup; tests coupled to dict ordering; testing `main()` vs. the helper inconsistently.
- **Acceptance criterion**: `python3 -m unittest -v` is green, and the new tests fail if `--json` emits extra stdout, drops a key, or if dry-run writes to `dst` (verified by a deliberate negative check during development, then reverted).

### Task 5 — Review: independent diff audit
- **Objective**: Review the combined `synccli.py` + `test_synccli.py` diff against every GOAL constraint (no new deps, Python 3.10 stdlib, `sync()` signature stable, human mode unchanged, stdout purity, exit code unchanged).
- **Files**: read-only diff.
- **Agent**: `review` (cheap-review)
- **Risks**: Reviewer missing the "nothing else on stdout" requirement or the stable-signature constraint; over-engineering beyond GOAL.
- **Acceptance criterion**: Findings classified minor/major with `file:line` references; explicit pass/fail line for each of the five GOAL constraints.

### Task 6 — Impl: apply review findings
- **Objective**: Fix all minor findings from Task 5 (and any in-scope major finding routed back per pipeline policy).
- **Files**: `synccli.py` / `test_synccli.py` as flagged.
- **Agent**: `impl` (resume Task 3/4 instance if the same files and contract)
- **Risks**: Regression while fixing; scope creep into `DESIGN.md` work.
- **Acceptance criterion**: Every Task 5 finding is either fixed or explicitly rebutted with evidence; full test suite still green.

### Task 7 — Final verification
- **Objective**: Run the end-to-end acceptance gate on a fresh temp source/destination, including a second identical sync to prove `skipped` accounting, and confirm no new imports/dependencies.
- **Files**: none (commands only; temp dirs).
- **Agent**: `review` (fresh reviewer, self-contained brief)
- **Risks**: Verifying only unit tests and not the real CLI contract; environment differences from the README command.
- **Acceptance criterion**: All of the following pass: (1) `python3 -m unittest -v` green; (2) `python3 -m synccli SRC DST --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert set(d)=={"copied","skipped","src","dst"}'`; (3) `--json --dry-run` lists pending files and leaves `DST` empty; (4) a second sync reports `copied == []` and the expected `skipped`; (5) `git diff` shows no changes outside `synccli.py` and `test_synccli.py` and no new dependencies.

Plan only. I made no changes. I read GOAL.md, README.md and synccli.py. I did not read test_synccli.py or incremental.py, so Task 1 covers them.

**Findings that shape the plan**
- `sync()` returns only the copied list. It does not report a skipped count, and its signature must stay stable. So `skipped` has to be computed in `main()` or in a new helper.
- `copy_file()` swallows `OSError` silently. A file can appear in `copied` even though it was never written. That makes the JSON `copied` list inaccurate.
- `sync()` writes the manifest after copying. Dry-run must skip both the copies and the manifest write.
- Out of scope, noted only: `collect_stale()` loops from `range(1, len(items))`, so it skips index 0. I did not touch it.

---

**Task 1: Explore the test suite and internal callers**
- Objective: confirm the test style, the existing human-mode output assertions, and every caller of `sync()`, including in `incremental.py`.
- Files: read only `test_synccli.py`, `incremental.py`, `synccli.py`.
- Agent: `explore`.
- Risks: `incremental.py` may depend on `sync()` return values or stdout, which would constrain the design.
- Acceptance: a written list of callers and the existing test conventions, with no files modified.

**Task 2: Design the JSON contract (decision record)**
- Objective: decide (a) how `skipped` is computed (`len(src_manifest) - len(copied)` is the likely choice); (b) whether `copied` reports only successful copies, given the silent `OSError` path; (c) that human mode and `sync()` are unchanged; (d) the exit-code behaviour; (e) how dry-run is reflected in the JSON.
- Files: create a design note only if the project convention requires one; otherwise a section in the task report.
- Agent: `cheap-design`, then `cheap-design-review`. This is a real contract ambiguity, not a predicted-difficulty escalation.
- Risks: a `copied` list that includes silently failed copies would be a false fact. Fixing that means changing `copy_file` to return a status, which touches more than the goal asks. Get a yes from the user before doing it.
- Acceptance: the design settles (a) to (e), and the user has approved any change to `copy_file`.

**Task 3: Implement `--json` in `main()`**
- Objective: add `--json` to argparse. In that mode, print exactly one `json.dumps` object to stdout with keys `copied`, `skipped`, `src`, `dst`, and print nothing else to stdout. Human mode prints one path per line as before.
- Files: modify `synccli.py` (`main()` and, if chosen in Task 2, a small helper). Do not change the `sync()` signature.
- Agent: `cheap-code`, then `cheap-review` (mandatory, even on a short diff).
- Risks: stray prints or warnings to stdout; `src` and `dst` recorded as given versus absolute (use what the design picked); the return code must stay 0.
- Acceptance: `python3 -m synccli SRC DST --json | python3 -c "import json,sys; json.load(sys.stdin)"` succeeds and the stdout line count is 1. Human-mode output is byte-identical to the baseline.

**Task 4: Dry-run plus JSON semantics**
- Objective: with `--dry-run --json`, `copied` lists what would be copied. Nothing is written to `dst`, including the manifest, and `skipped` is consistent with that.
- Files: `synccli.py` only if Task 3 left a gap.
- Agent: `cheap-code`, then `cheap-review`.
- Risks: the manifest write happens after the dry-run early return. Confirm it never runs in dry-run.
- Acceptance: a test shows `dst` is unchanged (no files, no `.sync_manifest.json`) and `copied` equals the list a non-dry run would copy.

**Task 5: Unit tests in `test_synccli.py`**
- Objective: add tests for (1) valid JSON parsing; (2) the four keys present with correct types; (3) `skipped` count correctness on a second run with no changes; (4) dry-run semantics from Task 4; (5) human-mode output unchanged; (6) stdout holds exactly one JSON document in `--json` mode.
- Files: modify `test_synccli.py`.
- Agent: `cheap-code`, then `cheap-review`. Use `cheap-mech` only if the tests are purely mechanical once the design is fixed.
- Risks: tests that capture stdout incorrectly pass vacuously. Each test must assert on a concrete value, not just that no exception occurred.
- Acceptance: `python3 -m unittest -v` passes, and the new tests fail if `--json` is removed or dry-run writes to disk.

**Task 6: Constraint and regression check**
- Objective: confirm Python 3.10 stdlib only (no new imports beyond the stdlib), `sync()` signature unchanged, and the incremental callers from Task 1 still work.
- Files: none modified.
- Agent: `explore` for the checks, with `cheap-mech` to run the commands.
- Risks: a dependency sneaking in through a type hint or a newer stdlib API.
- Acceptance: `git diff` shows no change to the `sync` line; `python3 -m unittest -v` passes; `python3 -m py_compile` passes under a 3.10 interpreter, if one is available.

**Task 7: Final audit**
- Objective: independent review of the full diff against GOAL.md's four points and the constraints.
- Files: none modified.
- Agent: `strong-review`. Use `strong-review-alternative` if the implementation was produced by a Claude-family `strong-code`; in this plan `cheap-code` is the implementer, so `strong-review` is the default.
- Risks: the audit should check the `copied` accuracy issue from Task 2, not only the happy path.
- Acceptance: no major findings. Minor findings go back to `cheap-code` through the same task id.

---

**Out of plan (needs your yes)**
- Document `--json` in README.md (the goal does not require it).
- Fix the `collect_stale()` off-by-one.
- Change `copy_file` to report failures, if Task 2 concludes it is needed.

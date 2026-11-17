Read all files; baseline established. **Current state:** `synccli.py` (CLI + `sync()`), `incremental.py` (v0.2 helpers), `test_synccli.py`, DESIGN.md (future `syncd` daemon — out of scope). **Test suite is RED**: `collect_stale` has an off-by-one (`range(1, len(items))` at synccli.py:56 skips the first item), so `test_first_item_stale_is_included` fails before any feature work.

## Execution plan

### Task 1 — Restore green baseline (fix `collect_stale`)
- **Objective:** Fix the off-by-one so item 0 is examined; suite passes again.
- **Files:** modify `synccli.py` (`collect_stale`, line 56).
- **Agent:** `cheap-mech` (small, mechanical, well-scoped).
- **Risks:** changing semantics for other callers — grep shows no callers of `collect_stale` outside tests; low.
- **Acceptance:** `python3 -m unittest` exits 0 with all 6 tests passing.

### Task 2 — Explore: pin down exact JSON contract surface
- **Objective:** Confirm nothing else in `main()` can print to stdout (argparse errors go to stderr — verify), and that `sync()` return value in dry-run mode is exactly the "would copy" list (it is, synccli.py:81-82). Confirm no internal callers of `sync()` beyond `main()`.
- **Files:** none (read-only).
- **Agent:** `explore`.
- **Risks:** none.
- **Acceptance:** short report confirming `sync()` signature can stay untouched and JSON assembly belongs in `main()` only.

### Task 3 — Implement `--json` output mode
- **Objective:** Add `parser.add_argument("--json", action="store_true")`; when set, print exactly one `json.dumps({"copied": [...], "skipped": N, "src": ..., "dst": ...})` to stdout, nothing else; human mode (one path per line) unchanged; exit code 0 unchanged.
- **Files:** modify `synccli.py` (`main()` only — no change to `sync()` signature per GOAL constraint).
- **Agent:** `cheap-code` (impl).
- **Risks:** `skipped` semantics need a definition — repo has `incremental.filter_excluded`; safest is `len(all source files) - len(copied)` computed from `scan_files(src)`. Accidental stdout pollution (e.g. future prints) — keep JSON emit as the single print branch.
- **Acceptance:** `python3 -m synccli src dst --json` stdout parses as JSON with exactly the 4 keys; with `--json --dry-run`, `copied` lists files that would be copied and no manifest is written in dst; human mode output byte-identical to before.

### Task 4 — Unit tests for JSON mode
- **Objective:** Add tests to `test_synccli.py`: valid JSON output, all keys present, `copied` list correctness, dry-run + `--json` interplay (would-copy without side effects), human mode still prints paths, and that `main(["src","dst","--json"])` emits a single line.
- **Files:** modify `test_synccli.py`.
- **Agent:** `cheap-code` (can be same impl instance as Task 3 — same feature, same files).
- **Risks:** tests must call `main(argv)` capturing stdout (`contextlib.redirect_stdout`), stdlib only.
- **Acceptance:** `python3 -m unittest -v` all green, new tests fail if `--json` logic is broken (mutation check optional).

### Task 5 — Mandatory review
- **Objective:** Independent review of the full diff (Tasks 1–4): stdout purity in JSON mode, `sync()` signature untouched, no new imports/deps, Python 3.10 stdlib only, tests actually assert the GOAL contract.
- **Files:** none (read-only).
- **Agent:** `cheap-review` (fresh session, self-contained brief).
- **Risks:** none beyond review latency.
- **Acceptance:** findings classified minor/major; zero majors, minors fixed and re-verified.

### Task 6 — Final verification
- **Objective:** Full-suite run + real CLI smoke test of both modes and flag combination.
- **Files:** none.
- **Agent:** orchestrator (or `cheap-mech`) running the commands.
- **Acceptance:** `python3 -m unittest` exit 0; smoke: `--json` output is one parseable line; `--json --dry-run` matches GOAL §2; README/GOAL constraints (no new deps) confirmed via `grep` of imports.

**Sequencing:** 1 → 2 → (3+4 as one impl round) → 5 → 6. Design-review (`cheap-design-review`) skipped deliberately: the design space here is a one-flag CLI addition already fully constrained by GOAL.md — no architectural stakes. DESIGN.md's `syncd` daemon is out of scope for this release. No files were modified.

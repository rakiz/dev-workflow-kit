Here is the structured execution plan to achieve the goals in `GOAL.md` while adhering to existing project conventions and constraints:

---

### Task 1: Explore Existing Contracts & CLI Patterns
- **Objective:** Analyze `synccli.py` and existing test patterns to understand how `sync()` is called, how files are scanned/counted, and how stdout is handled so that `--json` and `skipped` count can be cleanly computed without modifying the `sync()` signature.
- **Files to create/modify:** None (read-only inspection of `synccli.py`, `test_synccli.py`, and `DESIGN.md`).
- **Pipeline agent:** `explore`
- **Risks:** Misidentifying internal usage assumptions around `sync()` or how unreadable files/skipped files are defined.
- **Verifiable acceptance criterion:** Identification of exact logic for calculating `"skipped"` (e.g., `total_scanned - len(copied)`), confirmation that `sync(src_root, dst_root, dry_run=False)` signature and return type remain unchanged, and a verified strategy to guarantee zero stray prints to stdout in `--json` mode.

---

### Task 2: Design Review of Output Contract & CLI Interface
- **Objective:** Review and formalize the specification for the `--json` output dictionary (`{"copied": [...], "skipped": N, "src": ..., "dst": ...}`), stdout isolation (ensuring errors/warnings route to stderr), exit code semantics, and `--dry-run` interplay.
- **Files to create/modify:** None.
- **Pipeline agent:** `design-review`
- **Risks:** Ambiguity in whether `src`/`dst` paths in the JSON payload should be preserved verbatim as passed via CLI or normalized/resolved; regression of the human-readable output format.
- **Verifiable acceptance criterion:** Formal agreement on the JSON payload structure, confirmation that standard human mode output remains strictly one path per line, and verification that constraints (Python 3.10 stdlib only, no third-party libraries) are respected.

---

### Task 3: Implement `--json` Flag and Output Handling
- **Objective:** Add `--json` CLI argument to `main()` in `synccli.py`, calculate `"skipped"` count, format and print the single JSON object to stdout when `--json` is supplied, ensure human mode remains unchanged, and keep `sync()` signature stable.
- **Files to create/modify:** `synccli.py`
- **Pipeline agent:** `impl`
- **Risks:** Accidentally printing log or error messages to stdout instead of stderr in `--json` mode, breaking the single-object JSON contract; altering `sync()` parameters or return value.
- **Verifiable acceptance criterion:** 
  1. `python3 -m synccli --json src dst` emits exactly one valid JSON object on stdout containing keys `copied`, `skipped`, `src`, and `dst`.
  2. With `--json --dry-run`, `copied` lists files that would be copied without altering destination or manifest.
  3. Without `--json`, stdout remains identical to prior behavior (one relative path per line).
  4. `sync(src_root, dst_root, dry_run=False)` signature and return value remain identical to `v1`.

---

### Task 4: Implement Unit Tests for JSON Output and Dry-Run Semantics
- **Objective:** Add unit tests to `test_synccli.py` covering valid JSON generation, required dictionary keys and types, `--dry-run` combined with `--json`, skipped file accounting, and CLI stdout integrity.
- **Files to create/modify:** `test_synccli.py`
- **Pipeline agent:** `impl`
- **Risks:** Flaky tests due to temp directory paths or differences across OS path separators in the JSON payload (`os.path.join` vs POSIX slashes).
- **Verifiable acceptance criterion:** `python3 -m unittest -v` passes with all existing tests intact plus new test cases verifying:
  - Valid JSON parsing from CLI stdout.
  - Presence and correctness of `"copied"`, `"skipped"`, `"src"`, and `"dst"` keys.
  - Correct `"copied"` list and untouched destination when combining `--json` and `--dry-run`.
  - Non-JSON / human output format regression test.

---

### Task 5: Update Documentation
- **Objective:** Document the new `--json` flag, its interaction with `--dry-run`, and provide output examples in `README.md`.
- **Files to create/modify:** `README.md`
- **Pipeline agent:** `impl`
- **Risks:** Stale or conflicting CLI usage instructions.
- **Verifiable acceptance criterion:** `README.md` accurately describes `python3 -m synccli --json ...` behavior and stdout structure without omitting existing usage instructions.

---

### Task 6: Final Verification & Code Review
- **Objective:** Conduct a strict review of the diff across `synccli.py`, `test_synccli.py`, and `README.md` to ensure zero stray stdout prints, adherence to stdlib-only/Python 3.10 constraints, signature stability, and full test suite passing.
- **Files to create/modify:** None (read-only audit).
- **Pipeline agent:** `review`
- **Risks:** Uncaught edge cases where partial failures or empty directories produce invalid JSON or unhandled exceptions.
- **Verifiable acceptance criterion:** `python3 -m unittest -v` executes with 100% success rate, code diff introduces no dependencies outside the standard library, and all requirements in `GOAL.md` are satisfied.
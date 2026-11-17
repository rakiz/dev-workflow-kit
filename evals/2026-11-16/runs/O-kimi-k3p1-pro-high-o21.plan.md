# Execution plan

No files will be created or modified until implementation is explicitly approved.

## 1. Inspect the current CLI and establish a baseline

- **Pipeline agent:** `explore`
- **Objective:** Trace argument parsing, `sync()` and its callers, dry-run behavior, output routing, and exit-code handling. Identify the smallest implementation seam that preserves the existing `sync()` signature.
- **Files to create/modify:** None.
- **Files to inspect:** `synccli.py`, `test_synccli.py`, `incremental.py`.
- **Risks:**
  - Existing output may be emitted inside `sync()`, making JSON-only stdout difficult without a refactor.
  - Internal callers may depend on behavior beyond the function signature, such as its return value or printing.
  - Existing dry-run output may not retain the list of paths that would be copied.
- **Acceptance criterion:** A short report identifies the exact functions to change, all relevant callers, current dry-run/output semantics, and the result of the baseline `python3 -m unittest -v` run. No files change.

## 2. Implement JSON mode and its tests

- **Pipeline agent:** `impl`
- **Objective:** Add `--json` while preserving existing human output, dry-run behavior outside JSON mode, exit codes, Python 3.10 stdlib-only operation, and the `sync()` signature.
- **Files to create/modify:**
  - Modify `synccli.py`: add the CLI flag, serialize exactly one JSON object using stdlib `json`, and suppress all other stdout in JSON mode. With `--dry-run --json`, populate `copied` with paths that would be copied without copying them.
  - Modify `test_synccli.py`: add unit tests for valid JSON, required keys and value semantics, single-object stdout, dry-run would-copy behavior and lack of filesystem changes, unchanged human output, and unchanged exit codes.
  - No new files or dependencies; `incremental.py` should remain unchanged unless exploration reveals a compatibility-required adjustment.
- **Risks:**
  - Diagnostics or progress messages leaking into stdout and producing invalid JSON.
  - Reporting actual copies instead of planned copies during dry-run.
  - Changing `src`/`dst` representation inconsistently with existing CLI arguments.
  - Accidentally altering normal human output or internal `sync()` behavior.
- **Acceptance criterion:** `python3 -m unittest -v` passes. CLI tests parse stdout as exactly one JSON object with keys `copied`, `skipped`, `src`, and `dst`; dry-run lists planned copies and performs none; human mode remains one path per line; exit codes match equivalent non-JSON invocations; `sync()` retains its original signature.

## 3. Independently review and verify the implementation

- **Pipeline agent:** `review`
- **Objective:** Audit the diff and tests against every requirement, then independently run the test suite and targeted CLI checks.
- **Files to create/modify:** None. Findings are returned to `impl` for correction if necessary.
- **Files to inspect:** `synccli.py`, `test_synccli.py`, and any other file changed by implementation.
- **Risks:**
  - Tests may assert only key presence while missing incorrect values or extra stdout.
  - Error and dry-run paths may bypass the centralized output handling.
  - A test-only mock could conceal breakage of real CLI behavior or internal callers.
- **Acceptance criterion:** Review reports no unresolved correctness or compatibility findings; the complete test suite passes; direct CLI checks confirm stdout purity, dry-run semantics, unchanged human output and exit codes, and no new dependencies. Any finding returns to Task 2, followed by a fresh review.

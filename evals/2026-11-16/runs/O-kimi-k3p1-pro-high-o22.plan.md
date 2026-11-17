No files were modified.

## Execution plan

### 1. Map the current CLI, sync, and test flow
- **Objective:** Identify where arguments are parsed, where output is emitted, what `sync()` returns, and how dry-run currently determines skipped/copied files.
- **Files to create/modify:** None. Read the existing implementation module(s) and `test_synccli.py`.
- **Pipeline agent:** `explore`
- **Risks:**
  - Output may be produced inside `sync()`, making JSON-only stdout harder to enforce.
  - Internal callers constrain the `sync()` signature.
  - Existing dry-run behavior may not expose the would-be-copied paths directly.
- **Verifiable acceptance criterion:** A concise report identifies the exact modification points, existing output/exit-code behavior, available `copied`/`skipped`/`src`/`dst` values, and the current test patterns. No files changed.

### 2. Implement JSON output and its unit tests
- **Objective:** Add `--json`; make JSON mode emit exactly one object with `copied`, `skipped`, `src`, and `dst`; ensure `--json --dry-run` lists files that would be copied; preserve human output, exit codes, and the `sync()` signature. Add focused tests to `test_synccli.py`.
- **Files to create/modify:**
  - Existing CLI/sync implementation module(s) identified in Task 1.
  - `test_synccli.py`.
  - No new files or dependencies expected.
- **Pipeline agent:** `impl`
- **Risks:**
  - Progress or diagnostic output leaking into stdout in JSON mode.
  - Dry-run accidentally copying files or reporting actual rather than prospective copies.
  - Changing human-mode formatting or `sync()`’s public contract.
  - Path values not being serialized consistently or validly.
- **Verifiable acceptance criterion:**
  - `python3 -m unittest -v` passes.
  - New tests use `json.loads` on the **entire stdout** and assert the four required keys.
  - Normal JSON mode reports actual copied paths; combined JSON/dry-run mode reports would-be-copied paths and leaves the destination unchanged.
  - Equivalent JSON and human invocations retain the same exit-code behavior.
  - Human mode remains one path per line.
  - `sync()` keeps its existing signature, and the implementation remains Python 3.10 standard-library-only.

### 3. Review the diff and verify the complete contract
- **Objective:** Independently inspect the implementation and tests for correctness, regressions, and missing edge cases; run the full suite.
- **Files to create/modify:** None during review. Any required corrections return to `impl`, limited to the files in Task 2.
- **Pipeline agent:** `review`
- **Risks:**
  - Tests checking only JSON validity while allowing extra stdout.
  - Missing regression coverage for human mode or unchanged exit codes.
  - Weak dry-run assertions that do not verify both the reported paths and absence of filesystem changes.
- **Verifiable acceptance criterion:** The reviewer confirms every `GOAL.md` requirement against the diff and test results, `python3 -m unittest -v` passes, and no unresolved correctness findings remain. If fixes are needed, `impl` applies them and the affected checks are rerun.

A separate `design-review` task is unnecessary for this small, localized CLI change unless exploration reveals that output handling requires a broader refactor.

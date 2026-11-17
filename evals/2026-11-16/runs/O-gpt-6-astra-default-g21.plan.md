## Execution plan

The release adds JSON reporting while preserving human output, exit behavior, and `sync(src_root, dst_root, dry_run=False)`. No files were modified or tests run.

**Planning assumptions to confirm:** `skipped` counts source files unchanged according to the manifest; `src` and `dst` echo the supplied arguments. `copied` retains the relative-path list currently returned by `sync()`, including planned paths during dry-run.

### 1. Establish the baseline and reporting data flow
**Agent:** `explore`

- **Objective:** Trace scanning, manifest comparison, copying, CLI output, and internal callers. Establish existing test results before implementation.
- **Files:** Inspect `synccli.py`, `incremental.py`, `test_synccli.py`, `GOAL.md`, and `README.md`. Create/modify none.
- **Risks:** Existing defects can obscure feature regressions. In particular, `collect_stale()` starts at index 1, which appears inconsistent with `test_first_item_stale_is_included`. `copy_file()` suppresses some copy errors, so the returned list does not prove every copy succeeded.
- **Acceptance criterion:** Return a baseline from `python3 -m unittest -v`, identify all `sync()` callers and their return-value expectations, and describe how to derive `skipped`. Record unrelated failures for a separate authorization decision.

### 2. Review and settle the JSON contract
**Agent:** `design-review` (`cheap-design-review`)

- **Objective:** Approve a minimal implementation approach before edits:
  - One JSON object on stdout for a completed JSON-mode invocation.
  - Exactly the required fields: `copied`, `skipped`, `src`, and `dst`.
  - `copied` is a list of relative paths; `skipped` is a nonnegative integer counting unchanged source entries.
  - Dry-run uses the same selection logic without filesystem writes.
  - Preserve both the `sync()` signature and its list return value.
  - Prefer deriving report counts from the same source-manifest snapshot used for selection.
- **Files:** Inspect `synccli.py` and `GOAL.md`. Create/modify none; return the decision in chat.
- **Risks:** A second source scan can produce inconsistent counts if files change. `GOAL.md` does not specify whether the JSON guarantee covers errors or `--help`; inventing an error schema could change existing behavior.
- **Acceptance criterion:** A concrete data-flow proposal and field definitions are approved. Explicitly resolve the scope of error/help output with the user if the existing behavior and goal cannot be reconciled.

### 3. Implement JSON reporting and usage documentation
**Agent:** `impl` (`cheap-code`)

- **Objective:** Add `--json`, render the approved report using stdlib `json`, and preserve the existing per-path human output. Add concise usage examples for JSON and JSON dry-run.
- **Files:** Modify `synccli.py` and `README.md`. No new files expected.
- **Risks:** Printing both formats, changing return values or exit codes, inconsistent `skipped` counts, or accidentally writing a manifest during dry-run.
- **Acceptance criterion:**
  - Captured JSON-mode stdout parses as one object with the approved schema.
  - Normal and dry-run JSON modes report the expected paths and counts.
  - Human-mode stdout remains one relative path per line.
  - `sync()` retains its signature and list return value.
  - Help lists `--json`; README examples match actual usage.
  - Implementation remains Python 3.10-compatible and stdlib-only.

### 4. Add behavioral and regression tests
**Agent:** `impl` (`cheap-code`; continue the implementation session)

- **Objective:** Add the requested JSON tests and targeted compatibility checks.
- **Files:** Modify `test_synccli.py`.
- **Risks:** Tests that check only field presence can miss incorrect counts, extra stdout, or dry-run side effects.
- **Acceptance criterion:** Tests cover:
  - Parsing the **entire captured stdout** as JSON.
  - Required keys, field types, supplied source/destination values, and expected relative paths.
  - First sync, unchanged second sync, mixed changed/unchanged files, and an empty source.
  - Both flags together listing what would be copied.
  - Dry-run leaving destination contents and manifest unchanged, including not creating an absent destination.
  - Exact human output with and without dry-run.
  - Unchanged `sync()` return contract and CLI success status.

  All added tests pass; the full suite introduces no failures beyond the recorded baseline.

### 5. Independently review and verify the release change
**Agent:** `review` (`cheap-review`)

- **Objective:** Review the complete implementation, tests, and documentation against the approved contract.
- **Files:** Inspect the diff for `synccli.py`, `test_synccli.py`, and `README.md`. Create/modify none.
- **Risks:** Tests may share an implementation mistake, miss output contamination, or conceal a compatibility regression.
- **Acceptance criterion:** Run `python3 -m unittest -v` on Python 3.10 and subprocess checks using `python3 -m synccli` for human, JSON, and JSON dry-run modes. Verify stdout, exit status, filesystem effects, and dependency constraints. Return an explicit verdict with any baseline failures distinguished from regressions.

**Review loop:** Minor findings return to the same implementation agent, followed by re-review. Major findings trigger evidence-based escalation. Completion requires passing feature checks and no unresolved review findings; unrelated fixes require separate approval.

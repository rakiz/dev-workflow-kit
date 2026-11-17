## Execution plan

1. **Establish the baseline and settle the counting contract**
   - **Agent:** explore
   - **Objective:** Trace sync, error, and output behavior; define `skipped` as source files unchanged relative to the previous manifest. Identify how to calculate it from the same source snapshot as `copied`.
   - **Files:** Read `synccli.py`, `test_synccli.py`, and `README.md`; no changes.
   - **Risks:** `copy_file()` currently suppresses copy errors, so `copied` reflects attempted copies, not verified successes. The existing `test_first_item_stale_is_included` appears to fail because `collect_stale()` starts at index 1.
   - **Acceptance:** Document the current exit/output behavior and baseline test results, including any pre-existing failure; identify a counting approach that preserves `sync()`’s signature and return value.

2. **Review the implementation approach**
   - **Agent:** design-review
   - **Objective:** Review how the CLI obtains `copied` and `skipped` without inconsistent rescans or changing internal callers.
   - **Files:** Review `synccli.py`; no changes.
   - **Risks:** A second filesystem scan could produce an inconsistent count; changing copy-failure semantics would alter existing behavior.
   - **Acceptance:** Approve an approach using one source snapshot per invocation, preserving human output, dry-run side effects, and the existing `sync()` contract.

3. **Implement and test JSON output**
   - **Agent:** impl
   - **Objective:** Add `--json`, emit exactly one JSON object with `copied`, `skipped`, `src`, and `dst`, and report planned copies for `--json --dry-run`. Add usage documentation.
   - **Files:** Modify `synccli.py`, `test_synccli.py`, and `README.md`.
   - **Risks:** Extra stdout output could invalidate JSON; dry-run could accidentally create files or a manifest; refactoring could change human output or exit codes.
   - **Acceptance:** Tests parse the entire stdout as one JSON object and verify keys, values and types, initial and unchanged syncs, mixed copied/skipped files, and dry-run with no destination or manifest writes. Existing human-mode output and `sync()` signature remain unchanged; implementation uses only the Python 3.10 standard library.

4. **Review and verify**
   - **Agent:** review
   - **Objective:** Independently review the diff and run `python3 -m unittest -v`, comparing results with the baseline.
   - **Files:** Review modified files; no changes.
   - **Risks:** Existing test failures can obscure regressions; tests may validate mocked behavior rather than actual CLI output.
   - **Acceptance:** No new test failures; all new JSON and dry-run tests pass; review confirms stdout purity, unchanged exit behavior, signature compatibility, and no new dependencies. Report any pre-existing failure separately.

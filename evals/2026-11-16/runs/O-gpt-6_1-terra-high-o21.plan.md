## Execution plan

1. **Establish the baseline**
   - **Agent:** explore
   - **Objective:** Confirm CLI behavior, test results, and existing failures before implementation.
   - **Files:** Inspect `synccli.py`, `test_synccli.py`, and `README.md`; no changes.
   - **Risks:** An existing failure could be mistaken for a regression.
   - **Acceptance:** Record the output of `python3 -m unittest -v` and current human-mode and dry-run behavior. Static inspection indicates `test_first_item_stale_is_included` already fails because `collect_stale()` starts at index 1.

2. **Review the output contract**
   - **Agent:** design-review
   - **Objective:** Define `skipped` as the number of unchanged files in the source snapshot, and derive it from the same snapshot used to select copied files. Preserve `sync(src_root, dst_root, dry_run=False)` and its list return value.
   - **Files:** Review `synccli.py`; no changes.
   - **Risks:** A separate rescan can produce inconsistent counts. Existing `copy_file()` suppresses some copy errors, so `copied` currently represents selected paths rather than guaranteed successful copies.
   - **Acceptance:** Approve an implementation approach that preserves existing copy/error behavior and exit codes, documents the selected-path limitation, and produces one JSON object on successful JSON-mode runs.

3. **Implement and test JSON output**
   - **Agent:** impl
   - **Objective:** Add `--json`, support its combination with `--dry-run`, and document the flags and JSON fields.
   - **Files:** Modify `synccli.py`, `test_synccli.py`, and `README.md`.
   - **Risks:** Extra stdout output would invalidate JSON; computing `skipped` incorrectly or writing a manifest during dry-run would violate the contract.
   - **Acceptance:** Tests parse the entire stdout as one object with `copied`, `skipped`, `src`, and `dst`; check a normal run, a repeat run with skipped files, and a dry-run that reports prospective paths without copying or writing a manifest. Human output and `sync()` compatibility remain unchanged. No dependencies are added.

4. **Review the implementation**
   - **Agent:** review
   - **Objective:** Independently review the diff, tests, and compatibility against the goal and approved contract.
   - **Files:** Review the three modified files; no changes.
   - **Risks:** Tests may miss stdout contamination, changed exit behavior, or snapshot inconsistencies.
   - **Acceptance:** Review reports no unresolved findings against the stated requirements; any findings are returned to **impl** for correction and re-review.

5. **Verify the release behavior**
   - **Agent:** review
   - **Objective:** Run the full suite and check CLI output and exit statuses in human, JSON, and JSON dry-run modes.
   - **Files:** No planned changes.
   - **Risks:** The pre-existing `collect_stale` failure may keep the full suite red.
   - **Acceptance:** New tests pass, no regressions appear relative to the recorded baseline, and any remaining baseline failure is reported explicitly.

This is a plan only; no files were modified.

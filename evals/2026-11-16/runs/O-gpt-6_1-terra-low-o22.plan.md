## Execution plan

1. **Establish the baseline — explore**
   - **Objective:** Confirm CLI behavior, internal callers, error handling, and existing test results.
   - **Files:** Inspect `synccli.py`, `test_synccli.py`, and callers; no modifications.
   - **Risks:** Existing failures could be mistaken for regressions. In particular, `collect_stale()` appears to skip the first item, contrary to existing tests.
   - **Acceptance:** Record the output of `python3 -m unittest -v`, existing CLI exit behavior, and relevant callers of `sync()`.

2. **Resolve the output contract — design-review**
   - **Objective:** Specify `skipped` as the number of source files unchanged according to the existing manifest, and decide how JSON-mode failures satisfy the stdout and exit-code requirements.
   - **Files:** Inspect `GOAL.md` and `synccli.py`; no modifications.
   - **Risks:** The goal does not define `skipped` or the JSON object on errors. Copy failures are currently swallowed, so `copied` reflects the existing sync result rather than verified successful copies.
   - **Acceptance:** Produce an implementable contract covering empty sources, repeat runs, dry runs, errors, and preservation of `sync(src_root, dst_root, dry_run=False)` and its list return value. Escalate unresolved product ambiguity before implementation.

3. **Implement JSON output — impl**
   - **Objective:** Add `--json` and produce one JSON object with `copied`, `skipped`, `src`, and `dst`; preserve human output and dry-run behavior.
   - **Files:** Modify `synccli.py`.
   - **Risks:** Counting from a second scan could disagree with the copied list; changing `sync()` could break internal callers; output or error handling could change exit behavior.
   - **Acceptance:** A successful JSON invocation emits exactly one parseable object on stdout, using the same sync snapshot for counts and paths. Dry run reports planned copies without copying or writing the manifest. Existing human output and `sync()` signature and return type remain unchanged. No new dependencies.

4. **Add coverage and usage — impl**
   - **Objective:** Test the contract and document the flags.
   - **Files:** Modify `test_synccli.py` and `README.md`.
   - **Risks:** Tests that only mock implementation details may miss stdout contamination or filesystem changes.
   - **Acceptance:** Tests parse the entire stdout as JSON and check exact keys, values and types; cover first and repeat syncs, mixed copied/skipped files, dry-run filesystem and manifest preservation, human output, and agreed error behavior. README shows `--json` and `--dry-run` usage. Run `python3 -m unittest -v` on Python 3.10; report any pre-existing failures separately and introduce no new failures.

5. **Review the completed change — review**
   - **Objective:** Independently review implementation, tests, and documentation against the goal and baseline.
   - **Files:** Review the diff for `synccli.py`, `test_synccli.py`, and `README.md`; no modifications.
   - **Risks:** Contract drift, misleading counts, unintended side effects, and uncovered exit-code changes.
   - **Acceptance:** Reviewer confirms each goal and test result, or identifies actionable findings for the impl agent to resolve and resubmit for review.

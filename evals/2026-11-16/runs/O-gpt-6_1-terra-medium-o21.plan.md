## Execution plan

1. **Establish the baseline**
   - **Objective:** Run the existing suite and record failures before implementation.
   - **Files:** Read `synccli.py` and `test_synccli.py`; modify none.
   - **Agent:** `explore`
   - **Risk:** `test_first_item_stale_is_included` appears to fail already: `collect_stale()` starts at index 1. This is outside the stated goal.
   - **Acceptance:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v` has been run and any baseline failures recorded.

2. **Review the result design**
   - **Objective:** Agree on a shared internal sync result that supplies `copied` and `skipped` from the same manifest snapshot, while retaining the existing `sync(src_root, dst_root, dry_run=False)` signature and list return.
   - **Files:** Review `synccli.py`; modify none.
   - **Agent:** `design-review` (`cheap-design-review`)
   - **Risks:** A second scan can produce inconsistent counts; changing `sync()` would break internal callers. Define `skipped` as source-manifest entries unchanged from the prior manifest, and preserve the existing meaning of the returned copy list.
   - **Acceptance:** Review confirms the approach preserves existing sync behavior and computes counts consistently for both normal and dry-run execution.

3. **Implement and test the CLI mode**
   - **Objective:** Add `--json`; emit exactly one JSON object with `copied`, `skipped`, `src`, and `dst` on stdout. In dry-run mode, report planned paths without copying or writing the manifest. Preserve human output and exit behavior.
   - **Files:** Modify `synccli.py` and `test_synccli.py`.
   - **Agent:** `impl` (`cheap-code`)
   - **Risks:** Extra stdout corrupts JSON; dry-run could mutate the destination; copy failures are currently swallowed, so the existing copy-list semantics must not silently change.
   - **Acceptance:** Tests parse the entire stdout as JSON and check exact keys, values and counts for initial and repeat syncs, plus dry-run results and unchanged destination/manifest. Tests also verify human path-per-line output and `sync()` compatibility. No new dependencies are introduced.

4. **Review and verify**
   - **Objective:** Independently review the diff and run the complete test suite with Python 3.10.
   - **Files:** Review `synccli.py` and `test_synccli.py`; modify none.
   - **Agent:** `review` (`cheap-review`)
   - **Risks:** Regressions may be masked by the pre-existing test failure or by tests that only exercise the implementation indirectly.
   - **Acceptance:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v` shows all new tests passing and no regressions beyond documented baseline failures; review confirms the stdout, dry-run, compatibility, and standard-library constraints. Any findings go back to the implementation agent for correction and re-review.

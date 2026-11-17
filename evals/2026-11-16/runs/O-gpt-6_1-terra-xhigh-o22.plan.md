## Execution plan

**Scope:** Add the next-release CLI behavior in `GOAL.md`. The separate continuous-sync proposal in `DESIGN.md` is outside this plan.

1. **Establish the baseline — explore**
   - **Objective:** Trace `sync()` callers, CLI output, error behavior, and existing tests; record baseline test failures.
   - **Files:** Inspect `synccli.py`, `incremental.py`, and `test_synccli.py`; modify none.
   - **Risks:** Existing failures could be mistaken for regressions. In particular, `collect_stale()` starts at index 1, while two existing tests expect the first item to be considered.
   - **Acceptance:** Report the Python version, `python3 -m unittest -v` results, and existing success and error exit behavior.

2. **Resolve the output contract — design-review**
   - **Objective:** Review how to count `skipped` from the same source-manifest snapshot used to select copied paths, while preserving `sync(src_root, dst_root, dry_run=False)` and its list return value. Define behavior for unsuccessful invocations.
   - **Files:** Inspect `GOAL.md` and `synccli.py`; modify none.
   - **Risks:** A second scan can produce inconsistent counts; existing `copy_file()` silently suppresses some errors, so reported paths currently represent selected paths, not guaranteed successful copies. The goal does not define whether failures must emit JSON.
   - **Acceptance:** Approve a contract specifying `skipped`, path representation, dry-run accounting, and error output/exit behavior. Resolve any ambiguity with the user before changing existing error semantics.

3. **Implement and test — impl (`cheap-code`)**
   - **Objective:** Add `--json` using the approved contract; preserve human output and `sync()` compatibility. Add CLI-level tests and help text.
   - **Files:** Modify `synccli.py` and `test_synccli.py`; update `README.md` with usage and output semantics. Create no new dependency files.
   - **Risks:** Extra stdout corrupting JSON, dry-run writes, changed exit codes, or altered internal-caller behavior.
   - **Acceptance:** Tests parse the entire successful stdout as one JSON object with `copied`, `skipped`, `src`, and `dst`; verify mixed changed/unchanged files, dry-run predictions and no destination writes, human-mode output, and unchanged `sync()` signature and return type. Python 3.10 and standard-library-only constraints hold.

4. **Review and verify — review (`cheap-review`)**
   - **Objective:** Review the implementation against the approved contract and compare test results with the baseline.
   - **Files:** Inspect the diff and relevant existing files; modify none.
   - **Risks:** A superficially valid JSON response may conceal incorrect counts or a regression in legacy behavior.
   - **Acceptance:** Reviewer confirms the contract and compatibility requirements, targeted tests pass, and the full `python3 -m unittest -v` result is reported with any baseline failures distinguished from new failures. Send findings back to the implementation agent and re-review corrections before completion.

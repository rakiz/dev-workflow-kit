## Execution plan

Target: the next-release JSON/dry-run feature in `GOAL.md`, using the test command from `README.md`: `python3 -m unittest -v`.

### 1. Establish the baseline and compatibility boundaries
- **Agent:** `explore`
- **Objective:** Trace CLI output, manifest handling, and internal `sync()` callers; run the existing tests before implementation.
- **Files:** Inspect `synccli.py`, `test_synccli.py`, `incremental.py`, `GOAL.md`, and `README.md`. No changes.
- **Risks:** Existing failures could be mistaken for feature regressions. In particular, `collect_stale()` starts at index 1, while an existing test expects the first stale item to be included.
- **Acceptance criterion:** Report the baseline test results, current stdout/exit behavior, and callers that depend on `sync(src_root, dst_root, dry_run=False)` returning a list.

### 2. Review the JSON output contract
- **Agent:** `design-review`
- **Objective:** Resolve reporting semantics before implementation:
  - `copied`: the relative paths returned by `sync()`, including planned paths during dry-run.
  - `skipped`: source files unchanged according to the manifest, rather than copy failures.
  - `src` and `dst`: the supplied CLI arguments.
  - Successful JSON-mode output: exactly one serialized object followed by a newline.
  - Preserve existing exit behavior and specify how help, argument errors, and runtime failures interact with JSON mode.
- **Files:** Inspect `GOAL.md`, `synccli.py`, and `test_synccli.py`. No changes.
- **Risks:** `GOAL.md` does not define `skipped` precisely or provide an error-object schema. `copy_file()` currently suppresses some errors, so returned paths do not establish successful copying. Computing counts with another scan could introduce inconsistent snapshots.
- **Acceptance criterion:** Approve a concrete implementation approach that preserves the `sync()` signature and list return value, uses Python 3.10 standard-library facilities only, and explicitly addresses count consistency and error behavior.

### 3. Implement CLI reporting and document usage
- **Agent:** `impl`
- **Objective:** Add `--json`, select JSON versus human rendering in `main()`, and obtain reporting counts through the approved internal approach. Add concise normal and dry-run examples to the README.
- **Files:** Modify `synccli.py` and `README.md`.
- **Risks:** Path lines leaking into JSON stdout; accidental changes to human output, copying, manifest writes, or internal caller compatibility.
- **Acceptance criterion:**
  - `python3 -m synccli SRC DST --json` emits the four required keys with the approved types and values.
  - With `--json --dry-run`, `copied` lists planned changes and no files or manifest are written.
  - Human mode still prints one relative path per line.
  - `sync()` retains its exact signature and list return contract.
  - Help lists `--json`; no dependency is introduced.

### 4. Add feature and regression tests
- **Agent:** `impl`
- **Objective:** Exercise the CLI boundary and filesystem effects using temporary directories and captured output.
- **Files:** Modify `test_synccli.py`.
- **Risks:** Tests that only check key presence could miss trailing stdout, incorrect counts, or dry-run writes. Filesystem timestamp granularity could make changed-file tests unreliable.
- **Acceptance criterion:** Tests verify:
  - The **entire captured stdout** parses as one JSON object.
  - Required keys, value types, relative paths, and source/destination values.
  - First sync, unchanged second sync, mixed changed/unchanged files, and empty source.
  - Dry-run reports planned paths while preserving destination contents and manifest bytes; it also leaves an absent destination absent.
  - Human output and successful exit codes remain unchanged.
  - Fixtures clean up temporary resources and avoid timing-dependent assertions.

### 5. Review and verify the complete change
- **Agent:** `review`
- **Objective:** Independently inspect the implementation, tests, and documentation; run the release checks.
- **Files:** Review `synccli.py`, `test_synccli.py`, and `README.md`. Review is read-only; corrections return to `impl`, followed by re-review.
- **Risks:** Unrelated fixes expanding scope, insufficient tests for stdout exclusivity, or a green feature subset hiding baseline failures.
- **Acceptance criterion:**
  - Run `python3 -m unittest -v`, preferably under Python 3.10.
  - Smoke-test the documented module invocation in human, JSON, and JSON dry-run modes.
  - Confirm every `GOAL.md` requirement has verification evidence.
  - Report any baseline failures separately; a failing full suite must not be reported as passing.
  - Approve only after review findings are resolved or explicitly recorded as blockers.

**Scope boundary:** `DESIGN.md` describes a separate continuous-sync daemon proposal; it is not required for this release. Any baseline bug repair should be separately scoped before implementation.

No files were modified.
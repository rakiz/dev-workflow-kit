## Execution plan

### 1. Map the current CLI and synchronization flow
- **Objective:** Identify the argument parser, `sync()` definition and signature, dry-run behavior, copy-result data flow, all stdout/stderr write sites, exit-code handling, and relevant existing tests.
- **Files to create/modify:** None.
- **Pipeline agent:** `explore`
- **Risks:** Output may be emitted from multiple layers; changing `sync()` or its result handling could break internal callers; dry-run may not currently expose planned copies.
- **Verifiable acceptance criterion:** A concise report names the exact implementation files and test locations, documents the current `sync()` signature and output/exit-code flow, and records the baseline result of `python3 -m unittest -v`.

### 2. Review the minimal output-layer design
- **Objective:** Approve a design that adds `--json` without changing `sync()`’s signature. JSON serialization should occur at the CLI/output boundary, with exactly one `json.dumps(...)` result written to stdout in JSON mode. Dry-run must use planned-copy data rather than actual-write results. Human output and exit-code paths must remain unchanged.
- **Files to create/modify:** None during review. The implementation target is the CLI/output module identified in Task 1, plus the synchronization module only if necessary to expose existing result data without altering `sync()`’s signature.
- **Pipeline agent:** `design-review`
- **Risks:** Accidental debug/logging output onstdout; JSON errors changing existing exit codes; conflating planned and completed copies; unnecessary refactoring or new dependencies.
- **Verifiable acceptance criterion:** The reviewed design explicitly resolves where each output mode is emitted, how dry-run planned copies are obtained, how diagnostics avoid stdout in JSON mode, and why the `sync()` signature and human mode remain stable. Any unresolved issue returns to Task 1 or is referred back for design revision before implementation.

### 3. Implement JSON output and dry-run semantics
- **Objective:** Add `--json`, emit one object with `copied`, `skipped`, `src`, and `dst`, and make `--json --dry-run` report paths that would be copied. Preserve normal human output, existing exit codes, Python 3.10 stdlib-only operation, and the `sync()` signature.
- **Files to create/modify:** Modify only the implementation file(s) approved in Task 2. Prefer the existing CLI/output module; touch the synchronization module only if required. No new dependency or packaging files.
- **Pipeline agent:** `impl`
- **Risks:** Duplicate JSON output; incidental stdout writes; changed human formatting; incorrect dry-run copy lists; altered exception/exit behavior; public-signature drift.
- **Verifiable acceptance criterion:** Using temporary source/destination fixtures:
  - Normal JSON stdout parses as exactly one JSON object containing all four required keys with `copied` as a list and `skipped` as an integer.
  - JSON stdout contains no additional text.
  - Combined JSON/dry-run lists the would-be-copied paths and does not copy them.
  - Exit codes match equivalent non-JSON invocations.
  - Human mode still prints one path per line.
  - The `sync()` signature is unchanged.

### 4. Add focused unit coverage
- **Objective:** Add tests for valid single-object JSON output, required keys and value shapes, source/destination reporting, dry-run planned-copy semantics, skipped counts, and unchanged human-mode output.
- **Files to create/modify:** `test_synccli.py`; test helpers only if the existing test structure already requires them.
- **Pipeline agent:** `impl`
- **Risks:** Brittle path ordering or platform-specific path assertions; tests capturing only part of stdout; tests that verify JSON syntax but not dry-run behavior; accidental filesystem writes during dry-run.
- **Verifiable acceptance criterion:** The new tests parse stdout with `json.loads`, assert the required schema and values, explicitly verify dry-run plans without destination writes, and pass both targeted tests and the full `python3 -m unittest -v` suite.

### 5. Review and final verification
- **Objective:** Audit the complete diff against `GOAL.md`, checking behavior, compatibility, test quality, and scope. Fix any findings through the implementation agent, then re-review.
- **Files to create/modify:** None by the reviewer. Any corrections are limited to files from Tasks 3–4 and are made by `impl`.
- **Pipeline agent:** `review`
- **Risks:** Subtle stdout leakage on success or failure paths, regressions in human mode or exit statuses, signature changes, missing dry-run edge cases, or unnecessary changes.
- **Verifiable acceptance criterion:** No unresolved major or minor findings; `python3 -m unittest -v` passes; `python3 -m synccli --help` lists both flags in existing usage; manual JSON, JSON+dry-run, and human-mode smoke checks satisfy Task 3; the final diff contains no new dependencies and no `sync()` signature change.

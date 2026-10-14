## Execution plan

The release target in `GOAL.md` is JSON output with dry-run support, unchanged human output, Python 3.10 standard-library compatibility, and a stable `sync()` signature.

I read `GOAL.md`, `README.md`, and the implementation/tests to ground the plan. No files were modified and no tests were run.

**Agent roles:** `explore` = exploration agent; `impl` = `cheap-code`; `review` = `cheap-review`; `design-review` = `cheap-design-review`. Each implementation task must pass review before dependent work proceeds.

### 1. Establish the baseline and output contract
**Agent:** `explore`

- **Objective:** Trace `main()` → `sync()`, locate internal callers, and establish existing test results. Define `skipped` as the number of source-manifest entries that do not require copying; define `src` and `dst` as the supplied CLI argument strings.
- **Files:** Read `synccli.py`, `incremental.py`, `test_synccli.py`, `GOAL.md`, `README.md`; create/modify none.
- **Risks:** `GOAL.md` does not explicitly define `skipped`. `copy_file()` suppresses some failures, so the current returned list represents selected paths rather than verified successful copies.
- **Acceptance criterion:** A read-only report identifies callers, confirms signature and return-value compatibility requirements, records the test baseline, and documents the proposed JSON field semantics.

**Known baseline issue:** `collect_stale()` starts at index 1, which conflicts with `test_first_item_stale_is_included`. Confirm and track this existing failure separately so later verification can distinguish regressions.

### 2. Review the result-sharing design
**Agent:** `design-review`  
**Depends on:** Task 1

- **Objective:** Approve a minimal way for the CLI to obtain copied paths and skipped count from the same synchronization snapshot. Prefer a private result-producing helper, with `sync(src_root, dst_root, dry_run=False)` retaining its existing list return.
- **Files:** Read `synccli.py` and `test_synccli.py`; create/modify none. Return the design decision as text.
- **Risks:** A second source scan can introduce inconsistent counts and unnecessary work. Changing `sync()`’s return type would break callers. Broad copy-error changes would alter existing behavior.
- **Acceptance criterion:** The approved design preserves `sync()`’s signature and list return, uses one source-manifest snapshot per invocation, defines skipped-count arithmetic, and preserves existing exit/error behavior.

### 3. Implement JSON output and synchronization result plumbing
**Agent:** `impl`  
**Depends on:** Task 2

- **Objective:** Add `--json`, expose the approved internal result, and select JSON or human rendering in `main()`.
- **Files:** Modify `synccli.py`.
- **Risks:** Extra stdout messages corrupt machine-readable output; duplicate execution can copy twice; early returns can change dry-run behavior.
- **Acceptance criterion:**
  - Successful JSON invocations emit exactly one object with `copied`, `skipped`, `src`, and `dst`.
  - `copied` is a list of relative paths; `skipped` is an integer.
  - `--json --dry-run` reports would-copy paths without creating or changing destination files or the manifest.
  - Human mode retains one path per line and empty stdout for a no-op.
  - `sync()` retains its signature and list return; exit behavior remains unchanged.
  - No dependencies are added.

### 4. Add behavioral regression tests
**Agent:** `impl` — reuse Task 3’s implementation agent  
**Depends on:** Task 3

- **Objective:** Verify the JSON contract and compatibility using temporary directories and captured CLI output.
- **Files:** Modify `test_synccli.py`.
- **Risks:** Shape-only assertions can miss wrong counts or dry-run writes. Tests that mock synchronization entirely can miss integration problems.
- **Acceptance criterion:** Tests cover:
  - Parsing the entire stdout with `json.loads`, required keys, types, and exact expected values.
  - First sync, unchanged second sync, and a mixed changed/unchanged source.
  - Combined flags with both a missing destination and an existing destination/manifest, verifying no writes.
  - Exact human output and unchanged direct `sync()` return behavior.
  - CLI return codes and at least one `python3 -m synccli` subprocess invocation.

### 5. Review implementation and tests
**Agent:** `review`  
**Depends on:** Task 4

- **Objective:** Independently check correctness, compatibility, stdout isolation, and test coverage.
- **Files:** Read the diff in `synccli.py` and `test_synccli.py`; create/modify none.
- **Risks:** Tests and implementation may share the same mistaken skipped-count assumption; hidden API changes may escape CLI tests.
- **Acceptance criterion:** No unresolved findings concerning the release contract. Minor findings return to the original `impl` agent for fixes and re-review; major findings escalate to `strong-code`, followed by independent review.

### 6. Document the user-facing behavior
**Agent:** `impl`  
**Depends on:** Task 5

- **Objective:** Add concise usage examples and explain JSON fields and dry-run behavior.
- **Files:** Modify `README.md`.
- **Risks:** Documentation may imply verified copy success beyond existing behavior or describe counts inconsistently.
- **Acceptance criterion:** README includes examples for `--json` and `--json --dry-run`, the four-field schema, skipped-count semantics, and the existing test command. Examples match reviewed behavior.

### 7. Perform final release verification
**Agent:** `review`  
**Depends on:** Task 6

- **Objective:** Review documentation and the complete diff, then verify the release contract under Python 3.10.
- **Files:** Read `synccli.py`, `test_synccli.py`, and `README.md`; create/modify none.
- **Risks:** A newer interpreter can hide Python 3.10 incompatibility; the pre-existing test failure can obscure new failures.
- **Acceptance criterion:** Run `python3 -m unittest -v`, verify CLI help and real JSON/dry-run invocations, and report exact results. All new tests pass, no new baseline failures appear, and documentation matches behavior. If the confirmed `collect_stale()` failure remains, explicitly report the full suite as failing rather than claiming a green release.
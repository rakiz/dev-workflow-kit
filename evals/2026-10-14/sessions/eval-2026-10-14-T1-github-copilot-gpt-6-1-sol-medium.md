## Execution plan

The release target is `--json` output and its `--dry-run` behavior, as defined in `GOAL.md`. Preserve Python 3.10 stdlib-only compatibility, the `sync()` signature and list return value, existing exit behavior, and human output.

No files have been modified.

### 1. Establish the baseline and identify compatibility constraints
**Agent:** `explore`

- **Objective:** Trace CLI output, manifest handling, and existing `sync()` callers; establish the current test baseline.
- **Files:** Inspect `synccli.py`, `test_synccli.py`, `incremental.py`, `GOAL.md`, `README.md`, and `DESIGN.md`. No modifications.
- **Risks:** Existing failures could be mistaken for feature regressions. In particular, `collect_stale()` starts at index 1, while a test expects the first stale item to be included.
- **Acceptance criterion:** Report the result of `python3 -m unittest -v`, identify pre-existing failures, and record the current `sync(src_root, dst_root, dry_run=False)` contract and stdout sources.

### 2. Review the JSON contract and implementation approach
**Agent:** `design-review`

- **Objective:** Resolve reporting semantics before implementation and select a minimal approach that preserves internal callers.
- **Files:** Inspect `GOAL.md`, `synccli.py`, and relevant portions of `DESIGN.md`. No modifications required.
- **Proposed contract:**
  - `copied`: the existing ordered list of relative paths; with dry-run, paths that would be copied.
  - `skipped`: number of unchanged source-manifest entries, excluding destination-only entries.
  - `src` / `dst`: the CLI argument strings.
  - Successful JSON-mode execution emits exactly one object; diagnostics use stderr, preserving existing failure and exit behavior.
- **Risks:** `skipped` is unspecified in the goal. A second source scan could produce inconsistent counts. Existing `copy_file()` suppresses some errors, so the current returned list does not prove every copy succeeded. `DESIGN.md` proposes stdout diagnostics for a future daemon, which conflicts with this JSON contract if reused.
- **Acceptance criterion:** Produce an approved approach defining counts, path representation, and failure behavior; preserve `sync()`’s signature and return type; derive reporting from the same source snapshot used for synchronization. Keep the future daemon outside this release’s implementation scope.

### 3. Implement JSON reporting
**Agent:** `impl`

- **Objective:** Add `--json` and serialize the approved report while preserving human output.
- **Files:** Modify `synccli.py`; no new files expected.
- **Approach:** Use a private helper if needed to share synchronization results and counts. Keep `sync()` as the compatibility entry point returning a list. Use stdlib `json` for serialization.
- **Risks:** Leaking path lines into JSON stdout, changing internal caller behavior, rescanning for counts, or accidentally writing destination state during dry-run.
- **Acceptance criterion:** Normal and dry-run JSON invocations produce one parseable object with `copied`, `skipped`, `src`, and `dst`; human mode still prints only copied paths, one per line; `sync()` retains its existing signature and list return value.

### 4. Add focused regression tests
**Agent:** `impl`

- **Objective:** Verify the complete output contract and dry-run side effects.
- **Files:** Modify `test_synccli.py`.
- **Risks:** Tests that check only key presence may miss extra stdout, incorrect counts, manifest writes, or human-output regressions.
- **Acceptance criterion:** Tests capture and parse the **entire stdout** and verify:
  - Exact keys, value types, paths, and source/destination values.
  - First sync, unchanged repeat sync, mixed changed/unchanged files, and empty source.
  - `--json --dry-run` reports planned copies without creating or changing destination files or the manifest.
  - Human output remains one path per line.
  - Successful return codes and direct `sync()` behavior remain compatible.

  Run `python3 -m unittest -v`; report any baseline failures separately from new failures.

### 5. Document the CLI behavior
**Agent:** `impl`

- **Objective:** Explain the new flags and reporting semantics.
- **Files:** Modify `README.md`.
- **Risks:** Examples could imply successful-copy guarantees beyond current behavior or leave `skipped` ambiguous.
- **Acceptance criterion:** README includes normal JSON and JSON dry-run examples, defines all four fields and `skipped`, and retains the existing help and test commands. `python3 -m synccli --help` lists both flags.

### 6. Review and verify the release diff
**Agent:** `review`

- **Objective:** Independently check implementation, tests, and documentation against the approved contract.
- **Files:** Review changes to `synccli.py`, `test_synccli.py`, and `README.md`; no modifications by the reviewer.
- **Risks:** Compatibility regressions, hidden stdout output, dry-run writes, dependency additions, and unrelated changes.
- **Acceptance criterion:** Reviewer confirms the constraints, runs the documented suite and CLI smoke checks, and reports no unresolved feature regressions. Any pre-existing failures remain explicitly identified. Findings return to `impl` for correction and then receive another review.
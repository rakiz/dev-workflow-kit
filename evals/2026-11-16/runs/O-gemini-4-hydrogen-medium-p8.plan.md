## Execution Plan: `--json` Output Mode + `--dry-run` Interplay

### Task 1 — Codebase Exploration & Baseline Check
- **Objective:** Verify all internal callers of `sync()`, inspect `main()` / `sync()` in `synccli.py` and existing tests in `test_synccli.py`, and confirm the current test suite passes. Determine how `skipped` (unchanged files in `src_root`) should be derived without changing `sync()`'s signature or return value.
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `explore`
- **Risks:** Missing an internal caller or misunderstanding `sync()`'s return contract (`list[str]` of copied relative paths, asserted directly in `test_synccli.py`).
- **Verifiable acceptance criterion:** `python3 -m unittest -v` passes at baseline, and all callers of `sync()` in the repo are documented.

---

### Task 2 — Design Review of `sync()` / `main()` Split & JSON Contract
- **Objective:** Validate the design before coding: specifically, keeping `sync(src_root, dst_root, dry_run=False) -> list[str]` unchanged for internal callers (e.g., via an internal helper such as `_sync_with_stats(src_root, dst_root, dry_run=False)` that `sync()` delegates to, while `main()` uses it for `--json`), defining `skipped` (`len(src_manifest) - len(to_copy)`), and confirming `src`/`dst` formatting and `--dry-run` + `--json` behavior.
- **Files to create/modify:** None (read-only critique).
- **Pipeline agent:** `design-review` (`cheap-design-review`)
- **Risks:**
  - Computing `skipped` in `main()` by re-scanning `src` would duplicate `os.walk`/`os.stat` work and risk TOCTOU drift between `sync()` and `main()`.
  - Changing `sync()`'s return type or signature would break existing callers and `test_synccli.py`.
- **Verifiable acceptance criterion:** Approved interface specification confirming `sync()` signature/return value remain identical, single-pass `skipped` calculation, and exact JSON schema `{"copied": [...], "skipped": N, "src": ..., "dst": ...}`.

---

### Task 3 — Implement `--json` Mode & `--dry-run` Interplay
- **Objective:** Add `--json` to `argparse` in `main()`, refactor `sync()` to delegate to an internal stats-returning helper without altering `sync()`'s signature or return value, and emit a single JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` on stdout when `--json` is set (leaving human mode one-path-per-line and exit codes unchanged).
- **Files to create/modify:** Modify `synccli.py`.
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:**
  - Accidental extra stdout output in `--json` mode.
  - `--dry-run` with `--json` mutating `dst_root` or `.sync_manifest.json` instead of reporting what *would* be copied.
  - Introducing non-stdlib dependencies or Python >3.10 syntax.
- **Verifiable acceptance criterion:**
  - `python3 -m synccli --help` lists `--json`.
  - Running `main([src, dst, "--json"])` and `main([src, dst, "--json", "--dry-run"])` prints exactly one valid JSON line with keys `copied`, `skipped`, `src`, `dst`; human mode without `--json` still prints one path per line; existing `python3 -m unittest -v` tests pass.

---

### Task 4 — Add Unit Tests for JSON Mode & Dry-Run Semantics
- **Objective:** Add unit tests to `test_synccli.py` covering `--json` output validity, required keys and types, `skipped` count on incremental/no-op runs, `--json --dry-run` interplay (lists what *would* be copied without writing files or manifest), human-mode preservation, and `sync()` signature/return stability.
- **Files to create/modify:** Modify `test_synccli.py`.
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:** Tests only asserting JSON parsing without checking that nothing else was printed to stdout or that `--dry-run` left `dst` and `.sync_manifest.json` untouched.
- **Verifiable acceptance criterion:** `python3 -m unittest -v` runs and passes all existing and newly added tests with 0 failures/errors.

---

### Task 5 — Independent Code Review & Final Verification
- **Objective:** Audit the complete diff in `synccli.py` and `test_synccli.py` against all `GOAL.md` requirements and constraints (Python 3.10 stdlib only, no new dependencies, `sync()` signature/return stability, strict single-JSON-object stdout in `--json` mode, human mode unchanged).
- **Files to create/modify:** None (read-only review; if minor findings are reported, resume `cheap-code` to fix and re-verify; if major findings, escalate to `strong-code`).
- **Pipeline agent:** `review` (`cheap-review`)
- **Risks:** Subtle edge cases missed in implementation or tests (e.g., empty source directory, missing `dst` directory on `--dry-run --json`, or stdout trailing noise).
- **Verifiable acceptance criterion:** `review` reports zero major/minor unresolved findings, `git diff` touches only `synccli.py` and `test_synccli.py`, and `python3 -m unittest -v` passes cleanly.

### Ordered Execution Plan

#### Task 1: Codebase Exploration & Contract Verification
- **Objective:** Audit `synccli.py`, `test_synccli.py`, and any internal callers of `sync()` to verify the current behavior of `sync(src_root, dst_root, dry_run=False)`, `scan_files(root)`, and `main(argv=None)`, and confirm how `skipped` count should be derived (`len(scan_files(src)) - len(copied)`) while keeping `sync()`'s signature and return type untouched.
- **Files to create/modify:** None (read-only analysis of `synccli.py`, `test_synccli.py`, `incremental.py`).
- **Pipeline agent:** `explore`
- **Risks:**
  - Computing `skipped` via a second filesystem walk vs. deriving it cleanly could diverge if files change mid-run or if dot-directories are handled differently.
  - Breaking existing callers or existing tests in `test_synccli.py`.
- **Verifiable acceptance criterion:** Agent produces a concise report confirming all callers of `sync()`, the exact definition of `skipped` (`total scanned source files - len(copied)`), and how `main(argv)` captures CLI arguments and prints output.

---

#### Task 2: Design & Design Review of `--json` and `--dry-run` Interplay
- **Objective:** Validate the design for adding `--json` to `main(argv=None)` in `synccli.py` without altering `sync(src_root, dst_root, dry_run=False)`'s signature or return value. Specifically verify:
  1. CLI argument parsing (`parser.add_argument("--json", action="store_true")`).
  2. Calculation of `skipped` (`len(scan_files(args.src)) - len(copied)` or an internal helper) while keeping `sync()` returning `list[str]`.
  3. Exact JSON schema on stdout: `{"copied": [...], "skipped": N, "src": args.src, "dst": args.dst}` with no extra stdout output, and unchanged human output when `--json` is omitted.
- **Files to create/modify:** None (design critique only).
- **Pipeline agent:** `design-review` (`cheap-design-review`)
- **Risks:**
  - Altering `sync()` return value (e.g., returning a tuple or dict) would violate the `GOAL.md` constraint: *"keep `sync()` signature stable (internal callers exist)"*.
  - Printing trailing debug lines or human-mode lines alongside JSON output.
- **Verifiable acceptance criterion:** `design-review` approves the approach confirming zero changes to `sync(src_root, dst_root, dry_run=False)` signature/return contract, Python 3.10 stdlib-only usage (`json`, `argparse`), and exact compliance with `GOAL.md` requirements 1–3.

---

#### Task 3: Implement `--json` Flag and `--dry-run` Output Logic in `synccli.py`
- **Objective:** Add the `--json` flag to `argparse` in `synccli.py:main()`. When `--json` is set, output a single JSON object to stdout (`{"copied": copied, "skipped": skipped, "src": args.src, "dst": args.dst}`) and nothing else. Ensure `--dry-run` + `--json` reports the files that *would* be copied in `"copied"` and the remaining unchanged source files in `"skipped"`, without modifying `dst` or `.sync_manifest.json`. Keep human mode (`one path per line`) and exit code (`0`) unchanged.
- **Files to create/modify:** Modify `synccli.py`.
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:**
  - Inadvertently writing `.sync_manifest.json` or copying files during `--dry-run --json`.
  - `skipped` count inaccuracy on initial sync (`skipped == 0`), full no-op sync (`skipped == total`), or partial sync.
  - Non-serializable path types or extra newlines/output polluting stdout in `--json` mode.
- **Verifiable acceptance criterion:**
  - Running `python3 -m synccli <src> <dst> --json` outputs a single valid JSON line/document parseable by `json.loads()` containing keys `{"copied", "skipped", "src", "dst"}` and exits with code `0`.
  - Running `python3 -m synccli <src> <dst> --dry-run --json` lists would-be copied files in `"copied"`, leaves `<dst>` untouched, and exits with code `0`.
  - Running without `--json` preserves one-path-per-line stdout output.

---

#### Task 4: Implement Unit Tests for `--json` and `--dry-run` in `test_synccli.py`
- **Objective:** Add comprehensive unit tests to `test_synccli.py` covering:
  1. `--json` output validity (`json.loads` succeeds, single JSON object on stdout, exact keys `copied`, `skipped`, `src`, `dst`, exit code `0`).
  2. `skipped` count accuracy across initial sync (`skipped == 0`) and subsequent incremental/no-op sync (`skipped == N`, `copied == []`).
  3. `--dry-run` + `--json` interplay (`copied` lists what would be copied, `skipped` is accurate, no files or manifest written to `dst`).
  4. Regression check that human mode (without `--json`) still prints one path per line.
- **Files to create/modify:** Modify `test_synccli.py` (Note: if the pre-existing bug in `collect_stale` causes `TestCollectStale.test_first_item_stale_is_included` to fail, either isolate or consult before touching unrelated functions).
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:**
  - Not capturing `stdout` cleanly (e.g., forgetting `io.StringIO` / `contextlib.redirect_stdout`) and leaking test output.
  - Pre-existing failure in `TestCollectStale` (index starting at `1` in `synccli.py:55`) masking new test results if running the full suite blindly.
- **Verifiable acceptance criterion:** `python3 -m unittest -v test_synccli.TestSync` (and the new JSON/CLI test class) passes 100% of test cases, verifying JSON parsing, key presence, `skipped` counts, `--dry-run` non-mutation, and human mode compatibility.

---

#### Task 5: Code Review & Final Verification
- **Objective:** Review the diff across `synccli.py` and `test_synccli.py` against all constraints in `GOAL.md` (single JSON object on stdout, nothing else printed in JSON mode, exit code unchanged, `--dry-run` semantics, human mode unchanged, no new dependencies, Python 3.10 stdlib only, `sync()` signature untouched).
- **Files to create/modify:** None (read-only review; any minor findings routed back to `impl`).
- **Pipeline agent:** `review` (`cheap-review`)
- **Risks:**
  - Subtle edge cases missed (e.g., empty `src` directory with `--json`, `src`/`dst` string representation in JSON output, or unintended changes outside scope).
- **Verifiable acceptance criterion:** `review` reports zero major/minor defects, `git diff` shows changes restricted strictly to `synccli.py` and `test_synccli.py`, `sync(src_root, dst_root, dry_run=False)` signature is unchanged, and all new and existing `Sync` unit tests pass via `python3 -m unittest -v`.
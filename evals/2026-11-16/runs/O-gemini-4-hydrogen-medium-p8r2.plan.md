## Execution Plan: `--json` Output Mode & `--dry-run` Interplay

### Task 1: Baseline & Caller Audit
- **Objective:** Verify current test baseline (`python3 -m unittest -v`), check all callers of `sync()` and `main()` across the repo, and confirm how `skipped` should be derived (`len(src_manifest) - len(copied)`) without altering `sync()`'s signature or return type.
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `explore`
- **Risks:** Unnoticed internal callers relying on `sync()` returning a `list[str]`; pre-existing test failures (e.g., `TestCollectStale` in `test_synccli.py`) masking new regressions if not recorded upfront.
- **Verifiable acceptance criterion:** Written audit listing all `sync()` / `main()` call sites and the exact baseline `python3 -m unittest -v` output.

### Task 2: Interface & Edge-Case Design Check
- **Objective:** Validate the design before editing:
  - `main(argv=None)` adds `--json` (`action="store_true"`).
  - Internal helper (e.g., `_sync_with_stats(src_root, dst_root, dry_run=False)`) returns `(copied, skipped)` so `sync(src_root, dst_root, dry_run=False)` keeps its exact signature and `list[str]` return value without double-scanning `src_root`.
  - Define `src`/`dst` representation in JSON (`args.src`/`args.dst` strings), `skipped` calculation (`len(src_manifest) - len(copied)`), and stdout purity in `--json` mode.
- **Files to create/modify:** None (design check only).
- **Pipeline agent:** `design-review`
- **Risks:** Double-scanning `src_root` if `skipped` is computed separately in `main()` (race/performance); accidentally changing `sync()` return value and breaking internal callers; `argparse` error output behavior.
- **Verifiable acceptance criterion:** Approved design spec specifying `sync()` stability, JSON schema (`copied`, `skipped`, `src`, `dst`), and `--dry-run` + `--json` semantics.

### Task 3: Implement `--json` Flag and Stats Helper
- **Objective:** Add `--json` support to `main(argv=None)` and extract `_sync_with_stats` (called by both `sync()` and `main()`) in `synccli.py`. Ensure `--json` prints a single valid JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` to stdout and nothing else; human mode remains one path per line; `--dry-run` + `--json` reports `copied` as what would be copied without writing files or `.sync_manifest.json`.
- **Files to create/modify:** Modify `synccli.py`.
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:** Non-JSON output leaking to stdout in `--json` mode; mutating `sync()` signature/return type; `skipped` count mismatch when `dst` already has a manifest.
- **Verifiable acceptance criterion:** Running `python3 -m synccli <src> <dst> --json` and `--json --dry-run` outputs a single `json.loads`-parseable object on stdout with keys `copied`, `skipped`, `src`, `dst`, exit code `0`, and no filesystem writes on `--dry-run`.

### Task 4: Add Unit Tests for `--json` and `--dry-run`
- **Objective:** Add unit tests to `test_synccli.py` covering:
  - `--json` output is valid JSON with a single object on stdout and exact keys (`copied`, `skipped`, `src`, `dst`).
  - `skipped` accurately reflects unchanged files on subsequent syncs.
  - `--json --dry-run` lists files that would be copied in `copied`, leaves `dst` and `.sync_manifest.json` untouched, and exits `0`.
  - Human mode (without `--json`) still prints one path per line.
- **Files to create/modify:** Modify `test_synccli.py`.
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:** Tests relying on `sys.stdout` without `redirect_stdout` / `io.StringIO`, or failing to assert that `--dry-run` neither copies files nor creates `.sync_manifest.json`.
- **Verifiable acceptance criterion:** `python3 -m unittest -v test_synccli` runs all new JSON/dry-run/human-mode tests and passes.

### Task 5: Code & Constraint Review
- **Objective:** Audit the diff in `synccli.py` and `test_synccli.py` against all `GOAL.md` requirements and constraints (Python 3.10 stdlib only, no new dependencies, `sync()` signature/return value unchanged, stdout purity in `--json` mode, human mode unchanged).
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `review` (`cheap-review`)
- **Risks:** Subtle stdout/stderr leakage, edge cases with empty `src` directory or `skipped == 0`, or missing test assertions.
- **Verifiable acceptance criterion:** Review verdict with zero major findings and `python3 -m unittest -v` passing for all `synccli` and new JSON/dry-run test cases.

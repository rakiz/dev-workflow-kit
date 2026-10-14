# Execution Plan: JSON Output Mode + Dry-Run UX (`synccli`)

## Context & Constraints (from `GOAL.md` and `README.md`)
- **Goal**: Add a `--json` flag to `synccli` that outputs a single machine-readable JSON object to `stdout`: `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` with no extraneous `stdout` output and unchanged exit code (`0`).
- **Interplay with `--dry-run`**: When `--json` and `--dry-run` are combined, `"copied"` lists the relative paths that *would* be copied (without mutating `dst` or writing `.sync_manifest.json`).
- **Backwards Compatibility**: Default human-readable CLI output (one relative path per line) and exit code behavior must remain unchanged.
- **Technical Constraints**:
  - Python 3.10 standard library only (`argparse`, `json`, `os`, `sys`, `unittest`, etc.); no new third-party dependencies.
  - Keep `sync(src_root, dst_root, dry_run=False)` signature and return contract (`list[str]`) stable for existing internal callers and tests.
- **Verification Command**: `python3 -m unittest -v` and `python3 -m synccli --help`.

---

## Ordered Tasks

### Task 1: Codebase Exploration & Baseline Audit
- **Objective**: Inspect `synccli.py` and `test_synccli.py` to map all callers of `sync()` and `main()`, verify how `scan_files()` / `build_manifest()` / `changed_files()` compute candidate files versus copied files, and establish how `skipped` should be derived without breaking `sync(src_root, dst_root, dry_run=False)`.
- **Files to create/modify**: None (read-only inspection of `synccli.py`, `test_synccli.py`, `GOAL.md`, `README.md`).
- **Pipeline agent**: `explore` (`explore` subagent)
- **Risks**:
  - Changing `sync()`'s return value (e.g., returning a `(copied, skipped)` tuple or dict) would break existing internal callers and `TestSync` unit tests.
  - Pre-existing unrelated test failures in `test_synccli.py` (such as `TestCollectStale.test_first_item_stale_is_included`) could obscure new test results if not identified upfront.
- **Verifiable acceptance criterion**: Written summary confirming `sync(src_root, dst_root, dry_run=False) -> list[str]` callers, exact formula for `skipped` (`len(scan_files(src_root)) - len(copied)`), and current baseline output of `python3 -m unittest -v`.

---

### Task 2: Design Review of `--json` Output Contract & `skipped` Semantics
- **Objective**: Validate the technical design for computing `"skipped"` and formatting the JSON payload in `main()` while preserving `sync()`'s signature and return type. Confirm edge-case semantics:
  1. First sync (`skipped == 0`, `copied == [...]`).
  2. Subsequent no-op sync (`skipped == total_src_files`, `copied == []`).
  3. Partial update (`skipped == total_src_files - len(copied)`).
  4. `--json --dry-run` (`copied` contains files that would be copied, `skipped` counts unchanged files, no files or `.sync_manifest.json` written to `dst`).
  5. `src` and `dst` values in JSON match the passed CLI arguments (`args.src`, `args.dst`).
- **Files to create/modify**: None (read-only design critique against `GOAL.md` and `synccli.py`).
- **Pipeline agent**: `design-review` (`cheap-design-review` subagent)
- **Risks**:
  - Re-scanning `src` after `sync()` vs. computing file counts cleanly could diverge if not derived consistently via `scan_files(args.src)` (which excludes hidden directories starting with `.` like `.sync_manifest.json`).
  - Accidental printing of human-mode lines or logs to `stdout` when `--json` is active, violating the single-JSON-object requirement.
- **Verifiable acceptance criterion**: Design sign-off confirming:
  - `sync(src_root, dst_root, dry_run=False)` signature and `list[str]` return value remain untouched.
  - `main(argv=None)` adds `parser.add_argument("--json", action="store_true")` and branches cleanly between `--json` (`print(json.dumps({"copied": copied, "skipped": skipped, "src": args.src, "dst": args.dst}))`) and default human output.

---

### Task 3: Implement `--json` Flag and `--dry-run` Interplay in `synccli.py`
- **Objective**: Update `main()` in `synccli.py` to accept `--json`, compute `skipped` (`len(scan_files(args.src)) - len(copied)`), and emit a single JSON object `{"copied": [...], "skipped": N, "src": args.src, "dst": args.dst}` to `stdout` when `--json` is set, while keeping human output mode and exit code (`0`) unchanged.
- **Files to create/modify**:
  - Modify: `synccli.py`
- **Pipeline agent**: `impl` (`cheap-code` subagent)
- **Risks**:
  - Breaking `sync(src_root, dst_root, dry_run=False)` signature or return type for existing callers.
  - Printing extra lines or trailing output alongside the JSON object when `copied` is non-empty.
  - Modifying destination files or `.sync_manifest.json` when `--dry-run` is combined with `--json`.
- **Verifiable acceptance criterion**:
  - `python3 -m synccli --help` shows both `--dry-run` and `--json`.
  - Running `synccli.main([src, dst, "--json"])` prints valid JSON parsable by `json.loads()` with exact keys `{"copied", "skipped", "src", "dst"}` and returns `0`.
  - Running `synccli.main([src, dst, "--dry-run", "--json"])` reports the files that would be copied in `"copied"`, leaves `dst` untouched, and returns `0`.
  - Running `synccli.main([src, dst])` (without `--json`) still prints one relative path per line.

---

### Task 4: Add Unit Tests for JSON Mode and Dry-Run Interplay
- **Objective**: Add unit tests in `test_synccli.py` covering `--json` output validity, required keys and types (`copied`, `skipped`, `src`, `dst`), `skipped` count accuracy across initial and repeat syncs, `--json` + `--dry-run` interplay, and preservation of human mode output and exit codes.
- **Files to create/modify**:
  - Modify: `test_synccli.py`
- **Pipeline agent**: `impl` (`cheap-code` / `cheap-mech` subagent, resuming the implementation session)
- **Risks**:
  - Not capturing `sys.stdout` (`io.StringIO` / `unittest.mock.patch("sys.stdout")` / `contextlib.redirect_stdout`) accurately to verify that *nothing else* is printed to `stdout` in `--json` mode.
  - Leaving temporary directories uncleaned or coupling test state across test methods.
- **Verifiable acceptance criterion**:
  - `python3 -m unittest test_synccli.TestSync -v` (and the new JSON/CLI test case class in `test_synccli.py`) passes 100% with tests explicitly asserting:
    1. `json.loads(stdout)` succeeds on a single stdout payload.
    2. Exact keys `{"copied", "skipped", "src", "dst"}` are present with expected values (`copied == ["a.txt"]`, `skipped == 0` on first run; `copied == []`, `skipped == 1` on second run).
    3. `--json` + `--dry-run` populates `"copied": ["a.txt"]`, `"skipped": 0`, does not copy files or write `.sync_manifest.json`, and returns exit code `0`.
    4. Human mode (`main([src, dst])`) still outputs one path per line.

---

### Task 5: Code & Test Review (`GOAL.md` Compliance Check)
- **Objective**: Review the diff in `synccli.py` and `test_synccli.py` against all requirements and constraints in `GOAL.md` and `README.md`.
- **Files to create/modify**: None (read-only review of `git diff` on `synccli.py` and `test_synccli.py`; any minor findings routed back to `impl`).
- **Pipeline agent**: `review` (`cheap-review` subagent)
- **Risks**:
  - Subtle deviation from `GOAL.md` (e.g., extra keys in JSON, altered `sync()` signature, non-stdlib imports, or incomplete test coverage of `--dry-run` + `--json`).
  - Unintended edits outside `synccli.py` and `test_synccli.py`.
- **Verifiable acceptance criterion**:
  - `cheap-review` reports zero major/minor defects.
  - `git diff --name-only` lists only `synccli.py` and `test_synccli.py`.
  - All `TestSync` and JSON CLI unit tests pass via `python3 -m unittest -v`.
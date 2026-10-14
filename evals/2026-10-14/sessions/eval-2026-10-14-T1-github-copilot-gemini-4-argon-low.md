Here is the ordered execution plan to deliver `--json` output mode and `--dry-run` interplay for `synccli`.

---

### Task 1: Codebase Exploration & Contract Analysis
- **Objective:** Inspect `synccli.py`, `incremental.py`, `test_synccli.py`, and `DESIGN.md` to determine the exact signature and return value of `sync()`, how skipped vs. copied files are tracked, how CLI arguments and `stdout` printing are currently handled, and whether `sync()` already exposes skipped file counts or if a non-breaking internal helper/stats mechanism is needed while keeping `sync()`'s signature and return contract stable.
- **Files to create/modify:** None (read-only analysis of `synccli.py`, `incremental.py`, `test_synccli.py`, `DESIGN.md`).
- **Pipeline agent:** `explore`
- **Risks:**
  - `sync()` may currently only return copied files without reporting the number of skipped files (`"skipped": N`), or it may print directly to `stdout` inside `sync()`.
  - Path types (`pathlib.Path` vs `str`) in `copied`, `src`, and `dst` might not be directly JSON-serializable with `json.dumps()`.
- **Verifiable acceptance criterion:** Exploration summary documents: (1) exact `sync()` signature and return type, (2) where `stdout` writes occur, (3) how `skipped` count is or can be computed without breaking `sync()` callers, and (4) how `test_synccli.py` invokes the CLI/functions.

---

### Task 2: Design & Contract Review for `skipped` Tracking and CLI Output Separation
- **Objective:** Validate the design for obtaining `"skipped": N` and suppressing human line-by-line output in `--json` mode while preserving `sync()`'s signature and behavior for existing internal callers. Confirm exact JSON serialization types (`str` representations for `copied`, `src`, `dst`, `int` for `skipped`) and `--dry-run` semantics.
- **Files to create/modify:** None (design validation; or update `DESIGN.md` only if project conventions require it—otherwise no file modifications).
- **Pipeline agent:** `design-review` (`cheap-design-review`)
- **Risks:**
  - Changing `sync()`'s return type (e.g., from `list` to `tuple`/`dict`) would break existing callers or tests that unpack or iterate over `sync()`.
  - Leaking human-mode `print()` statements to `stdout` during `--json` mode would corrupt the single-JSON-object requirement.
- **Verifiable acceptance criterion:** Approved design specifying the exact function signatures, how `skipped` count is retrieved (e.g., via a lower-level helper or optional keyword parameter with backward-compatible return behavior, or manifest comparison), and the exact `stdout` formatting contract.

---

### Task 3: Implement `--json` Flag and `--dry-run` Interplay
- **Objective:** Implement the `--json` CLI flag in `synccli.py` (and any supporting non-breaking logic in `incremental.py` if needed) using only Python 3.10 stdlib (`json`, `argparse`, etc.):
  1. Add `--json` flag to the CLI argument parser.
  2. When `--json` is passed, suppress all human-mode `stdout` lines and emit a single JSON object to `stdout`: `{"copied": [...], "skipped": N, "src": ..., "dst": ...}`.
  3. When both `--json` and `--dry-run` are passed, populate `"copied"` with the list of files that *would* be copied and `"skipped"` with the count of unchanged/skipped files, without modifying `dst` or the manifest.
  4. Keep human mode output (one path per line), exit codes, and `sync()` signature/return contract unchanged.
- **Files to create/modify:** `synccli.py` (and `incremental.py` only if required to expose skipped counts without altering `sync()` signature).
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:**
  - `Path` objects passed to `json.dumps()` raising `TypeError: Object of type Path is not JSON serializable`.
  - `--dry-run` inadvertently writing `.sync_manifest.json` or copying files.
  - Extra trailing logs or progress messages printed to `stdout` in `--json` mode.
- **Verifiable acceptance criterion:**
  - Running `python3 -m synccli <src> <dst> --json` outputs a single valid JSON object on `stdout` with keys `"copied"`, `"skipped"`, `"src"`, `"dst"` and exits with `0`.
  - Running `python3 -m synccli <src> <dst> --json --dry-run` outputs the expected JSON with candidate files in `"copied"` while leaving `<dst>` untouched.
  - Existing unit tests in `python3 -m unittest -v` continue to pass.

---

### Task 4: Add Unit Tests for `--json` and `--dry-run`
- **Objective:** Add unit tests to `test_synccli.py` covering:
  1. Valid JSON output on `stdout` (parses cleanly via `json.loads()`, no extra lines on `stdout`).
  2. Exact required keys present (`"copied"`, `"skipped"`, `"src"`, `"dst"`) with expected types and values across initial sync and subsequent incremental syncs (verifying `"skipped"` increments appropriately).
  3. `--json` + `--dry-run` interplay (`"copied"` lists what would be copied, destination directory is not mutated, exit code is unchanged).
  4. Human mode regression check (still outputs one path per line when `--json` is omitted).
- **Files to create/modify:** `test_synccli.py`
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:**
  - Tests might only test `sync()` directly and miss testing the CLI entrypoint/`stdout` capture where `--json` formatting lives.
  - Unclosed temporary directories or leftover files between test runs.
- **Verifiable acceptance criterion:** `python3 -m unittest -v` runs and passes all existing and newly added unit tests with 0 failures/errors.

---

### Task 5: Code & Test Review + Final Verification
- **Objective:** Perform a read-only review of all changes across `synccli.py`, `incremental.py` (if touched), and `test_synccli.py` against `GOAL.md` constraints:
  - Python 3.10 stdlib only, zero external dependencies.
  - `sync()` signature and behavior for existing callers completely preserved.
  - Single JSON object on `stdout` in `--json` mode with nothing else printed to `stdout`.
  - `--dry-run` + `--json` accuracy and test coverage completeness.
- **Files to create/modify:** None (read-only audit; any minor findings are routed back to `impl` via `task_id` before sign-off).
- **Pipeline agent:** `review` (`cheap-review`, escalating to `strong-code` / `strong-review` only if major issues are found)
- **Risks:**
  - Edge cases such as empty source directory (`copied: []`, `skipped: 0`) or all-skipped sync (`copied: []`, `skipped: N`) producing unexpected output or types.
- **Verifiable acceptance criterion:** Reviewer reports zero major/minor defects, `git diff` touches only intended files with no stray artifacts, and `python3 -m unittest -v` passes 100%.
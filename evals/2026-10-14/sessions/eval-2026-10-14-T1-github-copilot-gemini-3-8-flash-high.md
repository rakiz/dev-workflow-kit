Here is the ordered execution plan to implement the requirements defined in `GOAL.md` and `README.md`.

---

### Task 1: Contract & Codebase Exploration
* **Objective:** Analyze `synccli.py` CLI flow, argument parsing, stdout handling, and evaluate how `skipped` must be computed (e.g., total source files minus copied files) while keeping the public `sync(src_root, dst_root, dry_run=False)` signature and return value strictly backward-compatible.
* **Files to create/modify:** None (read-only analysis of `synccli.py`, `test_synccli.py`, `GOAL.md`, and `incremental.py`).
* **Pipeline agent:** `explore`
* **Risks:** 
  * Overlooking existing internal consumers of `sync()` that expect `list[str]` return type.
  * Inconsistent definition of `skipped` between dry-run and actual sync runs.
* **Verifiable acceptance criterion:** A documented mapping of CLI argument parsing, the `skipped` calculation strategy, and confirmation that `sync()`'s existing signature and return type contract will not change.

---

### Task 2: Interface & Architectural Design Review
* **Objective:** Review and validate the CLI contract for `--json` and its interplay with `--dry-run`, ensuring strict adherence to the output specification (`{"copied": [...], "skipped": N, "src": ..., "dst": ...}`) and verifying that no extra stdout emission can occur.
* **Files to create/modify:** None (design review).
* **Pipeline agent:** `design-review`
* **Risks:**
  * Accidental stdout leakage (diagnostics or logs) corrupting machine-readable JSON output.
  * Inconsistent path representation for `src` and `dst` fields (raw string passed vs resolved path).
* **Verifiable acceptance criterion:** Approved design specification validating:
  1. Exact JSON schema keys (`copied`, `skipped`, `src`, `dst`).
  2. Zero non-JSON output on stdout when `--json` is supplied.
  3. Stable `sync()` signature and exit codes.

---

### Task 3: Implement `--json` Flag and Formatter
* **Objective:** Add the `--json` argument to `argparse` in `synccli.py`, implement stdout JSON payload serialization matching the schema, ensure stdout exclusivity when `--json` is passed, and retain existing line-by-line human output when omitted.
* **Files to create/modify:** `synccli.py`
* **Pipeline agent:** `impl`
* **Risks:**
  * Regressing default human-readable mode output.
  * Miscalculating `skipped` when `--dry-run` is active or when files fail to copy.
  * Introducing non-stdlib imports or breaking Python 3.10 compatibility.
* **Verifiable acceptance criterion:**
  * `python3 -m synccli <src> <dst> --json` prints only a valid JSON string with keys `copied`, `skipped`, `src`, and `dst`.
  * `python3 -m synccli <src> <dst> --json --dry-run` lists would-be copied items in `copied` without modifying destination files.
  * Invocation without `--json` continues to output one relative path per line.

---

### Task 4: Add Unit Tests for JSON Mode and Dry-Run Interplay
* **Objective:** Implement dedicated unit test cases in `test_synccli.py` covering JSON output validity, required schema keys and types, `--dry-run` behavior under `--json`, and preservation of human output.
* **Files to create/modify:** `test_synccli.py`
* **Pipeline agent:** `impl`
* **Risks:**
  * Flaky tests due to temp directory leaks or uncaptured stdout.
  * Asserting brittle raw string equality rather than structured JSON assertions.
* **Verifiable acceptance criterion:**
  * `python3 -m unittest test_synccli.py` executes new tests validating:
    1. Output is valid JSON parsable by `json.loads`.
    2. Payload contains exact keys `copied` (list), `skipped` (int), `src` (str), and `dst` (str).
    3. `--dry-run --json` reflects expected copies without creating files in `dst`.

---

### Task 5: Code and Quality Review
* **Objective:** Perform a rigorous review of the diff against all constraints in `GOAL.md`: zero external dependencies (stdlib only), stable `sync()` signature, exact JSON structure, and test coverage.
* **Files to create/modify:** None (review only).
* **Pipeline agent:** `review`
* **Risks:**
  * Unhandled edge cases (e.g., empty source directory, non-existent paths, permission errors).
  * Unintended formatting or typing regressions across Python 3.10.
* **Verifiable acceptance criterion:** Review approval verifying all acceptance criteria from Tasks 3 and 4 are met with 100% compliance with `GOAL.md` constraints.
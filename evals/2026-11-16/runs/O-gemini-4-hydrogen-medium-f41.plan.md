## Execution Plan (`synccli` — `--json` output mode + `--dry-run` UX)

### 1. Codebase & Contract Exploration
- **Objective:** Inspect `synccli.py`, `test_synccli.py`, `README.md`, and `GOAL.md` to confirm CLI parsing, all internal callers of `sync()`, how `skipped` should be derived without changing `sync()`, and the baseline test suite status.
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `explore`
- **Risks:** Missing internal callers of `sync()` or misinterpreting `skipped` semantics (unchanged files vs. unreadable files).
- **Verifiable acceptance criterion:** Baseline `python3 -m unittest -v` output recorded, all `sync()` call sites listed, and `skipped` calculation strategy documented without altering `sync(src_root, dst_root, dry_run=False)`.

### 2. Design Review of `--json` / `--dry-run` & `skipped` Semantics
- **Objective:** Validate the design for computing `skipped` (e.g., extracting an internal helper `_sync_with_stats()` called by both `sync()` and `main()` vs. scanning separately in `main()`), ensuring `sync()` keeps its exact signature and `list[str]` return value, and confirming strict stdout purity in `--json` mode.
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `design-review` (`cheap-design-review`)
- **Risks:** Breaking `sync()`'s signature/return type for internal callers; double-walking `src` causing inconsistent counts; accidental extra stdout output when `--json` is enabled.
- **Verifiable acceptance criterion:** Approved design specifying `sync()` stability, exact `skipped` definition (`total_scanned - len(copied)`), and JSON payload schema `{"copied": [...], "skipped": N, "src": ..., "dst": ...}`.

### 3. Implement `--json` Flag and `--dry-run` Interplay
- **Objective:** Add `--json` to `argparse` in `main()`, emit a single JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` to stdout when `--json` is passed (with `copied` listing what would be copied under `--dry-run`), keep human mode (one path per line) and exit codes unchanged, and keep `sync()`'s signature/return stable using Python 3.10 stdlib only.
- **Files to create/modify:** `synccli.py` (modify)
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:** Altering `sync()` signature or return value; printing non-JSON text to stdout in `--json` mode; introducing non-stdlib imports; regressing human-mode output.
- **Verifiable acceptance criterion:** `python3 -m synccli --help` lists `--json`; `python3 -m synccli <src> <dst> --json` and `--json --dry-run` each print a single valid JSON object with keys `copied`, `skipped`, `src`, `dst` and exit `0`; human mode still prints one path per line.

### 4. Add Unit Tests for JSON Shape and Dry-Run Semantics
- **Objective:** Add unit tests to `test_synccli.py` verifying valid single-object JSON stdout output, presence/types of `copied`, `skipped`, `src`, `dst`, `--json --dry-run` interplay (reports would-be copied files without modifying `dst` or `.sync_manifest.json`), `skipped` count on repeat sync, and unchanged human-mode output.
- **Files to create/modify:** `test_synccli.py` (modify)
- **Pipeline agent:** `impl` (`cheap-code`)
- **Risks:** Fragile stdout capture or path assertions; missing edge cases (e.g., `copied == []` with `skipped > 0` on second sync).
- **Verifiable acceptance criterion:** `python3 -m unittest -v` passes all existing and new tests using Python 3.10 stdlib only.

### 5. Implementation & Test Review
- **Objective:** Audit the diff in `synccli.py` and `test_synccli.py` against all `GOAL.md` requirements and constraints (no new dependencies, Python 3.10 stdlib only, `sync()` signature unchanged, single JSON object on stdout in `--json` mode, human mode unchanged).
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `review` (`cheap-review`)
- **Risks:** Undetected stdout leaks in `--json` mode, `sync()` signature/return drift, or incomplete `--dry-run` + `--json` test coverage.
- **Verifiable acceptance criterion:** Review verdict with zero major findings (or minor/major findings routed back to `impl` / escalated) and `python3 -m unittest -v` confirmed passing.

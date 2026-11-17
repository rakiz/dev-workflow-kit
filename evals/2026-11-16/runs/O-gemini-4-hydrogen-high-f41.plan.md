### Execution Plan (`synccli` `--json` + `--dry-run` UX)

> **Pipeline note:** This repository has no `.opencode/agent/` directory, so tasks use the global fallback pipeline agents (`explore`, `cheap-design-review`, `cheap-code`, `cheap-review`), escalating to `strong-*` only on demonstrated failure or major review findings.

---

#### Task 1: Baseline Exploration & Caller Audit
- **Objective:** Verify all callers of `sync()` across the repo, inspect `synccli.py`, `incremental.py`, `DESIGN.md`, and `test_synccli.py`, and run `python3 -m unittest -v` to record the baseline test state (note: `synccli.collect_stale` currently starts at index `1` while `TestCollectStale` expects index `0`).
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `explore` (`explore`).
- **Risks:** Missing an internal caller of `sync()` or confusing pre-existing `TestCollectStale` failures with regressions introduced by new changes.
- **Verifiable acceptance criterion:** Written report listing every caller/import of `sync()`, exact `python3 -m unittest -v` baseline output, and confirmation of Python 3.10 stdlib-only environment.

---

#### Task 2: Design Review of `sync()` Stability & JSON/Dry-Run Contract
- **Objective:** Validate the design before editing code:
  1. Keep `sync(src_root, dst_root, dry_run=False)` signature and `list[str]` return type unchanged by extracting an internal helper (e.g., `_sync_with_stats(...)`) that computes both `copied` and `skipped`, with `sync()` delegating to it.
  2. Confirm exact JSON payload `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` (`N = total_scanned - len(copied)`), stdout purity in `--json` mode, exit code parity, and `--json --dry-run` behavior (no file writes or `.sync_manifest.json` updates).
- **Files to create/modify:** None (read-only design check).
- **Pipeline agent:** `design-review` (`cheap-design-review`).
- **Risks:** Double-walking `src_root` in `main()` vs. `sync()` (causing inconsistent `skipped` counts or extra I/O), breaking `sync()`'s return contract for internal callers, or ambiguity on `skipped` when files are unchanged vs. empty source directories.
- **Verifiable acceptance criterion:** Approved design note specifying the internal helper boundary, exact JSON field types, and `--dry-run` + empty-tree edge-case behavior with zero new dependencies.

---

#### Task 3: Implement `--json` Flag, JSON Output Mode, and `--dry-run` Interplay
- **Objective:** Update `synccli.py` to add `--json` to `main()`'s `argparse` parser, compute `(copied, skipped)` via the internal sync helper while keeping `sync(src_root, dst_root, dry_run=False)` unchanged, emit a single `json.dumps({"copied": copied, "skipped": skipped, "src": args.src, "dst": args.dst})` object on stdout when `--json` is passed (nothing else printed to stdout), and preserve human mode (one path per line) and exit code `0`.
- **Files to create/modify:** `synccli.py` (modify).
- **Pipeline agent:** `impl` (`cheap-code`; escalate to `strong-code` only if `cheap-code` stalls across 2–3 failed attempts).
- **Risks:** Altering `sync()`'s signature/return value; leaking extra text to stdout in `--json` mode; writing files or `.sync_manifest.json` during `--dry-run`; introducing non-stdlib imports or Python >3.10 features; touching unrelated functions (`collect_stale`, `incremental.py`).
- **Verifiable acceptance criterion:**
  - `python3 -m synccli <src> <dst> --json` and `python3 -m synccli <src> <dst> --json --dry-run` each output a single valid JSON object parseable by `json.loads()` with exact keys `{"copied", "skipped", "src", "dst"}`, accurate `copied`/`skipped` values, no side effects under `--dry-run`, and exit code `0`.
  - `python3 -m synccli <src> <dst>` without `--json` still prints one relative path per line.
  - `synccli.sync(src_root, dst_root, dry_run=False)` keeps its exact signature and `list[str]` return value.

---

#### Task 4: Add Unit Tests for JSON Output Mode and `--dry-run` Semantics
- **Objective:** Add unit tests to `test_synccli.py` verifying: valid single-object JSON output on stdout (and no extra stdout lines), presence and types of keys `copied`, `skipped`, `src`, `dst`, accurate `copied` and `skipped` counts on initial sync vs. second (no-op) sync, `--json --dry-run` reporting what would be copied without creating destination files or `.sync_manifest.json`, unchanged human-mode output, and `sync()` signature/return stability.
- **Files to create/modify:** `test_synccli.py` (modify).
- **Pipeline agent:** `impl` (`cheap-code`, resuming Task 3's `task_id` for shared context).
- **Risks:** Flaky tests due to OS path separators or shared temp dirs, failing to capture/assert complete stdout purity, or modifying pre-existing tests outside scope.
- **Verifiable acceptance criterion:** `python3 -m unittest -v test_synccli` passes all new JSON/dry-run/human-mode tests plus existing `TestScanFiles` and `TestSync` tests, and `python3 -m synccli --help` displays `--json`.

---

#### Task 5: Independent Code Review & Final Verification
- **Objective:** Review the full `git diff` of `synccli.py` and `test_synccli.py` against `GOAL.md` requirements and constraints (Python 3.10 stdlib-only, no new deps, `sync()` signature stability, stdout purity, `--dry-run` interplay, human mode parity, test completeness). Route any minor findings back to `cheap-code` (with a fresh `cheap-review` afterward); escalate any major finding to `strong-code` + `strong-review`.
- **Files to create/modify:** None (read-only review).
- **Pipeline agent:** `review` (`cheap-review`, fresh session with full diff + `GOAL.md`).
- **Risks:** Overlooked edge cases (e.g., `skipped` calculation on partial/unchanged syncs, unintended edits to `collect_stale` or `incremental.py`, or extra stdout output on error/edge paths).
- **Verifiable acceptance criterion:** `cheap-review` reports zero unresolved major or minor findings, `git diff` touches only `synccli.py` and `test_synccli.py`, and final verification commands (`python3 -m unittest -v`, `python3 -m synccli --help`, and CLI smoke runs for `--json`, `--json --dry-run`, and human mode) succeed as expected.

# Execution Plan: `synccli` JSON Output Mode + Dry-Run UX

## Ordered Tasks

### Task 1 — Baseline & Caller Exploration
- **Objective:** Inspect `synccli.py`, `test_synccli.py`, and adjacent repository files (`incremental.py`, `DESIGN.md`, `README.md`) to map all internal/planned callers of `sync()`, verify current CLI argument parsing, stdout writes, exit codes, and record baseline `unittest` execution results.
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `explore` (`explore` subagent).
- **Risks:**
  - Missing an internal caller or assumption on `sync(src_root, dst_root, dry_run=False)` return value (`list[str]`).
  - Misattributing pre-existing test failures in the repo (specifically `TestCollectStale.test_first_item_stale_is_included` failing due to `collect_stale()` in `synccli.py`) to the new changes, or Tempting an implementer into out-of-scope fixes.
- **Verifiable acceptance criterion:** Exploration report documents: (1) exact `sync()` signature and return type, (2) every reference to `sync` / `copy_file` across the repo, (3) all `print` / stdout sites in `synccli.py`, and (4) exact pass/fail baseline output of `python3 -m unittest -v` and `python3 -m synccli --help`.

---

### Task 2 — Interface & Contract Design Review
- **Objective:** Critique and lock down the implementation design before writing code:
  1. Single-scan internal helper (e.g., `_sync_with_stats(src_root, dst_root, dry_run=False) -> tuple[list[str], int]`) computing `skipped = len(src_manifest) - len(to_copy)` from the same `src_manifest`, while keeping `sync(src_root, dst_root, dry_run=False) -> list[str]` signature and behavior unchanged as a thin wrapper.
  2. Exact `--json` stdout payload schema (`{"copied": list[str], "skipped": int, "src": str, "dst": str}`), single-object stdout purity, exit code parity (`0` on success, `argparse` error codes unchanged), human-mode preservation, and `--dry-run` + `--json` non-mutation guarantees.
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `design-review` (`cheap-design-review` subagent; escalate only on demonstrated failure, never pre-emptively).
- **Risks:**
  - Computing `skipped` via a second `scan_files(args.src)` call in `main()` after `sync()`, causing duplicate I/O and a TOCTOU race if source files change mid-run (potentially yielding inconsistent or negative `skipped`).
  - Ambiguity on `"src"` and `"dst"` JSON values (must preserve CLI argument strings cleanly) or accidental trailing/extra lines on stdout.
  - Mutating `dst` or creating `.sync_manifest.json` when `--dry-run` and `--json` are combined.
- **Verifiable acceptance criterion:** Written design-review sign-off with zero unresolved `major` findings confirming: `sync()` signature/return-type stability, single-pass `skipped` calculation, edge-case behavior (empty `src`, non-existent/uninitialized `dst` under `--dry-run`, full no-op re-sync, partial sync), and Python 3.10 stdlib-only usage.

---

### Task 3 — Implement `--json` Flag & `--dry-run` Interplay
- **Objective:** Update `synccli.py` to add `--json` (`action="store_true"`) to the `argparse` CLI parser in `main()`, factor out single-pass `(copied, skipped)` accounting while keeping `sync(src_root, dst_root, dry_run=False)` signature and return value intact, emit a single JSON object (`{"copied": copied, "skipped": skipped, "src": args.src, "dst": args.dst}`) to stdout in `--json` mode (for both normal and `--dry-run` execution), and leave human output mode unchanged (one relative path per line, exit code `0`).
- **Files to create/modify:** Modify `synccli.py` (create none).
- **Pipeline agent:** `impl` (`cheap-code` subagent).
- **Risks:**
  - Breaking `sync(src_root, dst_root, dry_run=False)` positional/keyword signature or changing its `list[str]` return type for internal callers.
  - Printing anything besides the single JSON object to stdout in `--json` mode (e.g., human path lines or debug output).
  - Introducing non-stdlib imports or syntax incompatible with Python 3.10.
  - Scope creep into unrelated code (`collect_stale`, `incremental.py`, `DESIGN.md`).
- **Verifiable acceptance criterion:**
  - `python3 -c "import inspect, synccli; assert str(inspect.signature(synccli.sync)) == '(src_root, dst_root, dry_run=False)'"` exits `0`.
  - `python3 -m synccli --help` exits `0` and lists both `--dry-run` and `--json`.
  - Smoke run against temporary dirs confirms `--json` and `--json --dry-run` parse via `json.loads(stdout)` with exact keys `{"copied", "skipped", "src", "dst"}`, exit code `0`, and human mode still prints one path per line.

---

### Task 4 — Add Unit Tests for JSON Mode, Dry-Run Interplay & Regressions
- **Objective:** Add comprehensive `unittest` test cases in `test_synccli.py` covering:
  1. Valid single-object JSON output on stdout (`json.loads` succeeds; no extra stdout lines) and required keys/types (`copied`, `skipped`, `src`, `dst`).
  2. Accurate `copied` and `skipped` counts across initial sync (`skipped == 0`), idempotent second sync (`copied == []`, `skipped == N`), and partial update (`copied` = changed/new files, `skipped` = unchanged count).
  3. `--json` + `--dry-run` interplay (`copied` lists what *would* be copied, `skipped` reflects unchanged files, neither files nor `.sync_manifest.json` are written/updated in `dst`).
  4. Human mode (`main([src, dst])` and `main([src, dst, "--dry-run"])`) unchanged (one path per line, exit code `0`), plus `sync()` signature/return-value stability check.
- **Files to create/modify:** Modify `test_synccli.py` (create none).
- **Pipeline agent:** `impl` (`cheap-code` subagent, resuming Task 3's `task_id` while well under the ~100K token context cap).
- **Risks:**
  - Testing only `sync()` instead of `main()` / `python3 -m synccli`, missing CLI flag wiring, exit codes, or stdout formatting bugs.
  - Hardcoding OS path separators instead of `os.path.join` for nested paths (`sub/b.txt`).
  - Leaking temporary directories on test teardown or touching pre-existing `TestCollectStale` tests without authorization.
- **Verifiable acceptance criterion:**
  - `python3 -m unittest -v test_synccli.TestScanFiles test_synccli.TestSync` plus the new JSON/CLI test class(es) pass 100% with exit code `0`.
  - `git diff --name-only` shows only `synccli.py` and `test_synccli.py` modified, using Python 3.10 stdlib modules only (`unittest`, `json`, `io`, `contextlib`, `subprocess`, `tempfile`, `shutil`, `inspect`, `os`, `sys`).

---

### Task 5 — Cross-Lineage Implementation & Test Review
- **Objective:** Audit the complete diff across `synccli.py` and `test_synccli.py` against all `GOAL.md` requirements and constraints, verify test coverage sufficiency (non-vacuous assertions on stdout purity, JSON keys/types, `skipped` math, `--dry-run` disk non-mutation, exit codes, human mode, `sync()` signature), and classify any findings as `minor` or `major`.
- **Files to create/modify:** None (read-only review; triggers rework only if findings are reported).
- **Pipeline agent:** `review` (`cheap-review` subagent in a fresh session).
- **Risks:**
  - Subtle stdout contamination or edge-case `skipped` miscalculation slipping past happy-path tests.
  - Accidental edits to unrelated functions/files or undocumented dependency/version assumptions.
  - Reviewer context bloat if reused across rounds (mitigated by spawning a fresh `cheap-review` instance per review round).
- **Verifiable acceptance criterion:**
  - `cheap-review` returns zero `major` and zero unresolved `minor` findings.
  - `git status --short` lists only `M synccli.py` and `M test_synccli.py`.
  - All existing passing suites (`TestScanFiles`, `TestSync`) and all new `--json` / `--dry-run` unit tests pass under `python3 -m unittest -v` (with pre-existing out-of-scope `TestCollectStale` status unchanged and explicitly reported to the user).

---

## Orchestration & Governance Guardrails
- ** Escalation & cost guard:** No expensive tier (`strong-*`) is pre-booked. On `minor` findings in Task 5, resume the existing `cheap-code` `task_id` to apply fixes, then validate with a fresh `cheap-review` session. Escalate to `strong-code` (followed by `strong-review`) **only** on a demonstrated stall (2–3 failed attempts without progress) or a `major` review finding (announcing the escalation and reason to the user first).
- **Scope guard ("Ask before acting"):** Pre-existing defects outside `GOAL.md` (notably `collect_stale` in `synccli.py:55` failing `TestCollectStale.test_first_item_stale_is_included`, `incremental.py`, and `DESIGN.md`) and optional `README.md` flag examples must not be modified without explicit user approval.

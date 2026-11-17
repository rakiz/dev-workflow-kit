# Execution Plan: `synccli` JSON Output Mode & `--dry-run` UX

> **Orchestrator Rules & Escalation Policy:** No expensive agents (`strong-*`) are pre-booked at planning time. Every task starts on the cheap pipeline rung (`explore`, `cheap-design-review`, `cheap-code`, `cheap-review`). Escalate to `strong-code` (after notifying the user) **only** on a demonstrated stall (2–3 failed attempts without progress) or a major finding from `cheap-review`. Out-of-scope code (e.g., pre-existing `collect_stale` off-by-one in `synccli.py` or `incremental.py`) must **not** be modified without explicit user approval.

---

### Task 1: Baseline Codebase & Constraint Exploration
- **Objective:** Map `sync()` signature and all internal/test callers (`synccli.py`, `incremental.py`, `DESIGN.md`, `test_synccli.py`), inspect CLI argument/output handling in `main(argv=None)`, and establish the current `python3 -m unittest -v` baseline (isolating any pre-existing unrelated failures such as `TestCollectStale` from new work).
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `explore` (`explore` subagent).
- **Risks:**
  - Missing internal callers or return-type expectations on `sync(src_root, dst_root, dry_run=False) -> list[str]`.
  - Misattributing pre-existing unrelated test failures (`collect_stale` skipping index `0`) to new changes, or fixing out-of-scope bugs without user permission.
- **Verifiable acceptance criterion:** Concise exploration report documenting: (1) exact `sync()` signature, return type, and caller locations; (2) exact baseline output of `python3 -m unittest -v`; and (3) confirmation of out-of-scope functions/files that must remain untouched.

---

### Task 2: Technical Contract & Edge-Case Design Review
- **Objective:** Validate the implementation contract before writing code:
  1. Keep `sync(src_root, dst_root, dry_run=False) -> list[str]` signature and return type untouched by delegating to a private helper (e.g., `_sync_detailed(src_root, dst_root, dry_run=False) -> tuple[list[str], int]`) that computes `copied` and `skipped = len(src_manifest) - len(to_copy)` in a single `build_manifest(src_root)` pass.
  2. Define `--json` stdout payload as a single JSON object `{"copied": copied, "skipped": skipped, "src": args.src, "dst": args.dst}` with nothing else written to `stdout` and exit code `0` preserved.
  3. Define `--json --dry-run` behavior: `copied` lists relative paths that *would* be copied, `skipped` counts unchanged source files against any existing destination manifest, and neither destination files nor `.sync_manifest.json` are written.
  4. Enforce Python 3.10 stdlib-only imports and unchanged human-mode output (`one relative path per line`).
- **Files to create/modify:** None (read-only critique of the orchestrator/`cheap-design` brief; no repository `.md` files created).
- **Pipeline agent:** `design-review` (`cheap-design-review`).
- **Risks:**
  - Computing `skipped` via a second `scan_files(src_root)` call in `main()`, introducing a TOCTOU race and double filesystem walk.
  - Ambiguity around `skipped` when `.sync_manifest.json` does not yet exist (`skipped == 0`) vs. subsequent runs (`skipped == unchanged file count`), or when `copy_file` encounters an unreadable file.
  - Breaking `sync()` callers by changing its return value from `list[str]` to a tuple/dict.
- **Verifiable acceptance criterion:** Written `cheap-design-review` sign-off with zero unresolved major concerns on `sync()` backward compatibility, single-pass `skipped` calculation, stdout purity in `--json` mode, `--dry-run` non-mutation, and Python 3.10 stdlib compliance.

---

### Task 3: Implement `--json` Flag and `--dry-run` Interplay in CLI
- **Objective:** Update `synccli.py` to add `--json` (`action="store_true"`) to `argparse` in `main(argv=None)`, introduce the internal helper so `sync(src_root, dst_root, dry_run=False)` preserves its exact signature and `list[str]` return value while `main()` receives `(copied, skipped)`, emit strictly `json.dumps({"copied": copied, "skipped": skipped, "src": args.src, "dst": args.dst})` on `stdout` when `args.json` is true, and keep human-mode printing and exit code `0` unchanged.
- **Files to create/modify:** Modify `synccli.py` (no files created).
- **Pipeline agent:** `impl` (`cheap-code`; escalate to `strong-code` only on demonstrated stall).
- **Risks:**
  - Accidental alteration of `sync()` default arguments, parameter names, or return type.
  - Extra whitespace/lines or non-JSON messages leaking to `stdout` under `--json`.
  - Writing `.sync_manifest.json` or destination files when `--dry-run` and `--json` are passed together.
- **Verifiable acceptance criterion:**
  - `inspect.signature(synccli.sync)` is `(src_root, dst_root, dry_run=False)` and `synccli.sync(src, dst)` returns `list[str]`.
  - `python3 -m synccli <src> <dst> --json` prints exactly one valid JSON object to `stdout` with keys `{"copied", "skipped", "src", "dst"}` and exits `0`.
  - `python3 -m synccli <src> <dst> --dry-run --json` reports would-be-copied paths in `"copied"`, creates no files or `.sync_manifest.json` in `<dst>`, and exits `0`.
  - `python3 -m synccli <src> <dst>` without `--json` prints one relative path per line and exits `0`.

---

### Task 4: Add Unit Tests for JSON Output, `--dry-run`, and Regressions
- **Objective:** Extend `test_synccli.py` (using Python 3.10 stdlib `unittest`, `json`, `io.StringIO`, `contextlib.redirect_stdout`, `tempfile`) to cover:
  1. `--json` valid JSON parsing, single-object stdout purity, exit code `0`, and exact key set `{"copied", "skipped", "src", "dst"}`.
  2. Accurate `copied` and `skipped` counts across initial sync (`skipped == 0`), no-op repeat sync (`copied == []`, `skipped == N`), and partial incremental sync.
  3. `--json` + `--dry-run` interplay verifying `"copied"` lists what *would* be copied while destination files and `.sync_manifest.json` remain untouched/uncreated.
  4. Human mode (`main([src, dst])` and `main([src, dst, "--dry-run"])`) output format unchanged (one path per line, empty output when nothing copied).
  5. `sync()` signature and return-type stability check.
- **Files to create/modify:** Modify `test_synccli.py` (no files created).
- **Pipeline agent:** `impl` (`cheap-code`, reusing the Task 3 `task_id` session while under the context cap).
- **Risks:**
  - Testing internal helpers instead of invoking `synccli.main([...])` and capturing real `stdout` + return code.
  - Temp directory leakage across test runs if cleanup (`addCleanup` / `TemporaryDirectory`) is omitted.
  - Hardcoding OS path separators instead of `os.path.join` for nested relative paths.
- **Verifiable acceptance criterion:** `python3 -m unittest -v test_synccli.TestScanFiles test_synccli.TestSync` plus the new CLI/JSON `TestCase` classes pass 100% under Python 3.10 with zero third-party dependencies.

---

### Task 5: Cross-Lineage Implementation & Test Review
- **Objective:** Perform an independent read-only audit of the full `git diff` (`synccli.py` and `test_synccli.py`) against `GOAL.md` and `README.md`. Classify any findings as **minor** (resume the `cheap-code` `task_id` to fix, then spawn a fresh `cheap-review`) or **major** (notify user and escalate to `strong-code`, followed by `strong-review`). Also surface the pre-existing out-of-scope `TestCollectStale` failure to the user as an informational note without touching it.
- **Files to create/modify:** None (read-only review; any fix round modifies only `synccli.py` / `test_synccli.py` via `impl`).
- **Pipeline agent:** `review` (fresh `cheap-review` instance).
- **Risks:**
  - Missing subtle contract violations (e.g., extra trailing prints, non-stdlib imports, mutated `sync()` behavior, or unintended edits to `collect_stale` / `incremental.py`).
  - Weak assertions in tests that pass on malformed keys or partial stdout capture.
- **Verifiable acceptance criterion:**
  - `cheap-review` approves with zero open major or minor findings.
  - `git status --short` shows modifications exclusively in `synccli.py` and `test_synccli.py`.
  - All `TestScanFiles`, `TestSync`, and new JSON/CLI unit tests pass via `python3 -m unittest -v`, with zero new failures compared to the Task 1 baseline.

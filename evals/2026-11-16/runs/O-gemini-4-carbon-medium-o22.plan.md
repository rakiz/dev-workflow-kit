### Execution Plan: `synccli` `--json` Output Mode + `--dry-run` Interplay

**Scope & Orchestrator Guardrails**
- **Target constraints (`GOAL.md`):** Python 3.10 stdlib only, zero new dependencies, `sync(src_root, dst_root, dry_run=False)` signature and `list[str]` return contract unchanged, human CLI output unchanged, single JSON object on `stdout` (`{"copied": [...], "skipped": N, "src": ..., "dst": ...}`) with nothing else on `stdout` and exit code unchanged.
- **Pipeline & escalation policy:** Cheap-first execution (`explore` → `cheap-design-review` → `cheap-code` → `cheap-review`). Expensive rungs (`strong-*`) are **not** pre-booked; escalate only on a demonstrated stall (2–3 failed attempts) or a `major` review finding, after notifying the user.
- **Out-of-scope baseline note:** Pre-existing defects outside `GOAL.md` (notably `collect_stale()` in `synccli.py` starting at index `1`, which fails `TestCollectStale.test_first_item_stale_is_included`, and helpers in `incremental.py`) must **not** be modified silently; report them to the user for separate confirmation.

---

#### Task 1: Baseline, Caller, and Test-Suite Audit
- **Objective:** Inspect `synccli.py`, `incremental.py`, `DESIGN.md`, and `test_synccli.py` to enumerate all existing and planned callers of `sync()` and `main()`, verify CLI invocation (`python3 -m synccli`), and capture the exact baseline result of `python3 -m unittest -v`.
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `explore` (`explore`).
- **Risks:**
  - Pre-existing failure in `TestCollectStale.test_first_item_stale_is_included` could obscure new test results or tempt unauthorized scope creep into `collect_stale()`.
  - Missing implicit assumptions from downstream callers (`DESIGN.md` specifies `syncd` reusing `sync()` directly; `incremental.py` imports `copy_file`).
- **Verifiable acceptance criterion:** A concise read-only baseline summary confirming all call sites of `sync()`, baseline `unittest` pass/fail counts by test class, and `git status --porcelain` empty.

---

#### Task 2: Interface & Edge-Case Design Review
- **Objective:** Validate the minimal technical design before writing code:
  1. Extract a private helper (e.g., `_sync_core(src_root, dst_root, dry_run=False) -> tuple[list[str], int]`) computing `skipped = len(src_manifest) - len(to_copy)` from the **single** `build_manifest(src_root)` pass, while `sync(src_root, dst_root, dry_run=False)` delegates to it and still returns `to_copy` (`list[str]`).
  2. Add `--json` (`action="store_true"`) in `main()`, emitting `json.dumps({"copied": copied, "skipped": skipped, "src": args.src, "dst": args.dst})` as a single stdout write when enabled, and preserving line-by-line `copied` printing otherwise.
  3. Confirm `--json --dry-run` behavior on both empty/uninitialized `dst` (`skipped == 0`) and previously synced `dst` (`skipped > 0`, no file or manifest writes).
- **Files to create/modify:** None (read-only critique; no `.md` files created).
- **Pipeline agent:** `design-review` (`cheap-design-review`).
- **Risks:**
  - Computing `skipped` via a second `scan_files(args.src)` call in `main()` would double filesystem I/O and introduce a TOCTOU mismatch between `copied` and `skipped`.
  - Normalizing `src`/`dst` paths unexpectedly instead of preserving the passed `args.src` / `args.dst` strings.
  - Emitting extra whitespace/lines on `stdout` in `--json` mode, or altering `argparse` exit codes on invalid invocations.
- **Verifiable acceptance criterion:** Written design sign-off confirming single-pass manifest accounting, unchanged `sync(src_root, dst_root, dry_run=False)` signature/return type, exact 4-key JSON contract (`copied: list[str]`, `skipped: int`, `src: str`, `dst: str`), and Python 3.10 stdlib-only usage.

---

#### Task 3: Implement `--json` Flag and Skipped-File Accounting
- **Objective:** Implement the approved private sync helper and `--json` CLI flag in `synccli.py`, ensuring `--dry-run` + `--json` reports what would be copied and how many files would be skipped without mutating `dst`, while keeping human mode and `sync()` backward-compatible.
- **Files to create/modify:** Modify `synccli.py`.
- **Pipeline agent:** `impl` (`cheap-code`).
- **Risks:**
  - Accidental change to `sync()` parameter names, defaults, return value, or manifest write semantics.
  - Writing `.sync_manifest.json` or destination files during `--json --dry-run`.
  - Printing anything besides the single JSON object to `stdout` when `--json` is active, or printing a stray blank line in human mode when `copied` is empty.
- **Verifiable acceptance criterion:**
  - `inspect.signature(synccli.sync)` is `(src_root, dst_root, dry_run=False)` and `sync()` returns `list[str]`.
  - `python3 -m synccli <src> <dst> --json` exits `0` and prints valid JSON with exact keys `{"copied", "skipped", "src", "dst"}` and zero extra stdout text.
  - `python3 -m synccli <src> <dst> --json --dry-run` exits `0`, lists pending relative paths in `"copied"`, leaves `<dst>` untouched, and matches human `--dry-run` path ordering.
  - `python3 -m synccli <src> <dst>` outputs one copied relative path per line (nothing when no files changed) and exits `0`.

---

#### Task 4: Add JSON Shape & Dry-Run Unit Tests
- **Objective:** Extend `test_synccli.py` with unit tests exercising `main(argv)` (capturing `stdout` with `contextlib.redirect_stdout`) and `sync()` for:
  - Valid JSON parsing and exact key set (`copied`, `skipped`, `src`, `dst`) + value types;
  - Initial sync vs incremental/noop second sync (`skipped` increments accurately, `copied` shrinks/empties);
  - `--json --dry-run` on clean and partially synced destinations (`copied` lists what would be copied, no files or `.sync_manifest.json` written/updated);
  - Human mode output parity (with and without `--dry-run`) and exit code `0`;
  - `sync()` signature and return-type stability.
- **Files to create/modify:** Modify `test_synccli.py`.
- **Pipeline agent:** `impl` (`cheap-code`, resuming Task 3 session if well under the ~100K token cap).
- **Risks:**
  - Asserting `json.loads()` on sliced output rather than the full raw `stdout`, missing stray lines.
  - Only testing `skipped == 0` (fresh destination) and missing `skipped > 0` after an initial sync.
  - Editing unrelated existing test classes (`TestCollectStale`).
- **Verifiable acceptance criterion:** Running `python3 -m unittest test_synccli.TestScanFiles test_synccli.TestSync test_synccli.<NewJsonTestCase> -v` passes 100%, with temporary directories cleaned up and zero non-stdlib imports.

---

#### Task 5: Mandatory Independent Code & Contract Review
- **Objective:** Audit the complete diff across `synccli.py` and `test_synccli.py` from an independent model lineage against every requirement and constraint in `GOAL.md` and `README.md`; route `minor` issues back to the `cheap-code` session or escalate `major` issues to `strong-code` (with prior user notice).
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `review` (`cheap-review`, fresh session).
- **Risks:**
  - Overlooked stdout leakage on edge cases (empty `src` directory, nested subdirectories, empty `copied` list).
  - Unintended edits outside `synccli.py` and `test_synccli.py`.
  - Confusing the pre-existing `TestCollectStale` failure with a regression from this change.
- **Verifiable acceptance criterion:** `cheap-review` signs off with zero open `major` or `minor` findings; `git diff --name-only` lists only `synccli.py` and `test_synccli.py`; all `TestScanFiles`, `TestSync`, and new JSON/dry-run tests pass; pre-existing `TestCollectStale` failure is clearly reported to the user without unauthorized modification.

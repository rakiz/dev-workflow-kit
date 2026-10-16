No modifications — reading repo to draft your execution plan.

# Execution Plan — JSON output mode + dry-run UX (GOAL.md)

Source analysis verified: `synccli.py:72-99` (`sync()` returns `list[str]`, `main()` prints one-path-per-line), `synccli.py:90-95` (current `argparse` with only `--dry-run`), `test_synccli.py:1-54` (existing unit tests: scan/sync/collect_stale), `GOAL.md:5-14` (contract), `DESIGN.md:11-14` (polling design, unrelated to this release), `incremental.py:12-15` (pre-existing mutable-default bug, out-of-scope).

No files modified — text-only plan as requested.

---

### Task 1 — Baseline exploration & test harness capture

*   **Objective:** Establish current behavior and regression baseline before any flag work. Confirm human-mode output (`synccli.py:97-98`), `sync()` signature stability (`synccli.py:72`), and existing test command (`README.md:7` → `python3 -m unittest -v`).
*   **Files to read (no create/modify):** `synccli.py`, `test_synccli.py`, `incremental.py`, `DESIGN.md`, `GOAL.md`, `README.md`.
*   **Pipeline agent:** `explore`
*   **Risks:** Misreading `sync()` dry-run early-return (`synccli.py:81-82`) as full skipped semantics; confusing `stdout` vs `stderr` for future error logging.
*   **Verifiable acceptance criterion:** `bash: python3 -m unittest -v` passes with current 5 tests; documented inventory of `main()` stdout sites (`synccli.py:98`) and `sync()` return contract.

### Task 2 — Design review: JSON contract & stdout discipline

*   **Objective:** Freeze precise JSON contract to satisfy `GOAL.md:5-6`: single JSON object on `stdout` with keys `copied`, `skipped`, `src`, `dst`; nothing else on `stdout` in `--json` mode; `exit code unchanged`; human mode unchanged (`GOAL.md:9`). Decide `skipped` definition (recommended: `len(src_manifest) - len(to_copy)` at call time, not manifest history), `src`/`dst` echo raw args, `copied` sorted list for determinism, `--dry-run` + `--json` must not mutate `dst` or manifest.
*   **Files to create/modify:** None (review doc only). If doc persisted, `DESIGN.md` appendix or `docs/json-contract.md` — but per GOAL constraints keep change minimal; prefer ephemeral design note.
*   **Pipeline agent:** `design-review`
*   **Risks:** Ambiguous `skipped` (unchanged vs excluded vs unreadable); accidentally emitting logs/progress to `stdout` breaking `Nothing else may be printed` (`GOAL.md:6`); deciding to change `sync()` return type (violates `GOAL.md:14` stable signature).
*   **Verifiable acceptance criterion:** Written contract answering: exact JSON keys/types, `skipped` formula with example, `stdout` vs `stderr` rule, `dry_run` non-mutation guarantee, backwards-compat proof (existing callers of `sync(src,dst,dry_run)` unaffected). Review sign-off before impl.

### Task 3 — Implement `--json` flag and stdout-isolated JSON output

*   **Objective:** Add `parser.add_argument("--json", action="store_true")` alongside existing `--dry-run` (`synccli.py:94`). In `main()` branch: when `--json`, emit exactly one `json.dumps({...})` to `stdout` (via `print`/`sys.stdout.write` + newline) containing `copied`, `skipped`, `src`, `dst`; ensure no other `print` executes in that branch (`synccli.py:97-98` must be gated). Compute `skipped` without changing `sync()` signature — derive inside `main()` from `build_manifest()` or by extending internal helpers only. Keep `sys.exit(main())` exit code 0 (`synccli.py:103`).
*   **Files to create/modify:** Modify `synccli.py` (`synccli.py:90-99`); no new dependencies (stdlib `json`, `argparse` only — `GOAL.md:13`).
*   **Pipeline agent:** `impl` (cheap-code) → mandatory `review` (cheap-review) on diff
*   **Risks:** Leaking `argparse` help/errors or debug prints to `stdout` in JSON mode; `json.dumps` emitting non-serializable types; sorting instability causing flaky tests; breaking human mode (one path per line must remain when `--json` absent).
*   **Verifiable acceptance criterion:** `bash: python3 -m synccli /tmp/src /tmp/dst --json | python3 -m json.tool` succeeds and `stdout` is exactly one line of valid JSON with keys `{copied,skipped,src,dst}`; `bash: python3 -m synccli /tmp/src /tmp/dst | cat -A` still shows one path per line; no `stdout` pollution (`2>/dev/null` vs `2>&1` diff empty of extra lines); `grep -r "import.*requests\|import.*click"` finds no new deps.

### Task 4 — Implement `--dry-run` × `--json` interplay (no side-effects)

*   **Objective:** Ensure `GOAL.md:8` semantics: with both flags, `copied` lists what WOULD be copied, `skipped` counts what would be skipped, and no files/manifest are written (`synccli.py:81-87` already handles `dry_run` return without copy/manifest write — verify manifest not touched and `dst` files not created). Reuse existing `sync(..., dry_run=True)` path; do not add new params to `sync()`.
*   **Files to create/modify:** Modify `synccli.py` (same region `synccli.py:72-87` for verification, `synccli.py:90-99` for wiring); no signature change.
*   **Pipeline agent:** `impl`
*   **Risks:** `main()` recomputing manifest differently than `sync()` causing `copied`/`skipped` mismatch; `copy_file` error swallow (`synccli.py:68-69`) hiding that `skipped` should not count unreadable as skipped vs failed; manifest file creation on dry-run regression.
*   **Verifiable acceptance criterion:** Manual check: `bash: rm -rf /tmp/dst && python3 -m synccli /tmp/src /tmp/dst --dry-run --json` → JSON `copied==[expected]`, `dst` contains no new files and no `.sync_manifest.json`; second run without `--dry-run --json` still copies correctly.

### Task 5 — Add unit tests for JSON shape & dry-run semantics

*   **Objective:** Satisfy `GOAL.md:10-11`: extend `test_synccli.py` with tests covering valid JSON, keys present, correct types (`copied` list, `skipped` int, `src`/`dst` str), dry-run does not mutate `dst`, human mode unchanged, and stdout-exactly-one-JSON-object in `--json` mode (capture `sys.stdout` via `subprocess` or `unittest.mock.patch`).
*   **Files to create/modify:** Modify `test_synccli.py` (append new `TestJsonOutput` class after `test_synccli.py:53`); no new files needed.
*   **Pipeline agent:** `impl`
*   **Risks:** Tests that assert on absolute paths vs relative; tests that depend on filesystem `mtime` flakiness (reuse existing `tempfile.mkdtemp` pattern `test_synccli.py:8-15`, `test_synccli.py:36-40`); testing JSON via `main()` vs `sync()` — `sync()` must not be forced to change signature to make tests pass.
*   **Verifiable acceptance criterion:** `bash: python3 -m unittest -v` shows new tests (e.g., `test_json_valid`, `test_json_keys_present`, `test_json_dry_run_no_side_effect`) all passing; `bash: python3 -m unittest test_synccli.TestJsonOutput -v` isolated pass; stdout capture asserts `json.loads(stdout)` succeeds and `stdout.count("\n")==1`.

### Task 6 — Final review & regression gate

*   **Objective:** End-to-end verification: no new deps, Python 3.10 stdlib only, `sync()` signature stable (inspect `inspect.signature(synccli.sync)`), human mode unchanged, JSON mode stdout-clean.
*   **Files to create/modify:** None (read-only verification).
*   **Pipeline agent:** `review` (if impl diff was large, escalate to `strong-review`)
*   **Risks:** Overlooked secondary stdout emitter (e.g., `copy_file` future logging); `incremental.py:12` mutable default and `synccli.py:55` off-by-one (`range(1, len(items))`) are pre-existing bugs — must not be fixed in this release to avoid scope creep unless explicitly approved.
*   **Verifiable acceptance criterion:** All of: `bash: python3 -m unittest -v` exit 0; `bash: python3 -m synccli --help` shows both `--dry-run` and `--json`; `bash: grep -E "def sync\(" synccli.py` shows single signature `def sync(src_root, dst_root, dry_run=False):`; `bash: python3 -c "import synccli, inspect; print(inspect.signature(synccli.sync))"` equals prior; manual JSON + human mode smoke tests pass.

---

**Sequencing note:** Tasks 1→2 must be sequential (explore → design-review). Tasks 3 and 4 can be batched in one `impl` turn since they touch the same `main()` branch but keep separate acceptance checks. Task 5 depends on 3+4. Task 6 gates merge.

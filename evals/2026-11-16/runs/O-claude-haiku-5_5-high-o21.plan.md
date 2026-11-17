## Execution plan: `--json` output and dry-run UX for synccli

No files were modified. I read GOAL.md, README.md, `synccli.py`, `incremental.py`, and `test_synccli.py`, and ran the test suite once (no bytecode written).

**Baseline:** 6 tests, 1 failing before any change. `test_first_item_stale_is_included` fails because `collect_stale` (synccli.py:55) uses `range(1, len(items))` and skips index 0. This is pre-existing and out of scope (see open decisions).

**Design constraint:** `sync()` must keep its signature and its return value (a list of copied paths), because `incremental.py` and other internal callers depend on it. `skipped` therefore needs a separate internal helper.

### T1. Baseline and caller map (read-only)
- **Objective:** Confirm the caller graph of `sync()` and `main()`, record the current human-mode stdout for the golden comparison, and confirm the baseline failure.
- **Files:** none modified.
- **Agent:** `explore`
- **Risks:** Missing a caller means the signature freeze is violated silently.
- **Acceptance:** A report lists every `sync(`/`main(` call site with file:line, the exact human-mode output of `python3 -m synccli SRC DST` on a fixture, and the list of failing tests (expected: only `test_first_item_stale_is_included`).

### T2. Split the sync result into a report helper
- **Objective:** Add `sync_report(src_root, dst_root, dry_run=False) -> {"copied": [...], "skipped": int}`. `sync()` delegates to it and still returns the list. `skipped = len(src_manifest) - len(copied)`.
- **Files:** modify `synccli.py` (around lines 72–87).
- **Agent:** `cheap-code`, then `cheap-review` (mandatory). Optionally `cheap-design-review` on the helper split, since it is the only real design choice.
- **Risks:** Behaviour drift in `sync()` (return value, manifest write, no manifest write on dry-run). Double scan if the helper is written carelessly.
- **Acceptance:** `inspect.signature(synccli.sync)` is unchanged. The 5 existing `TestSync`/`TestScanFiles` tests still pass. A dry-run leaves dst without `.sync_manifest.json`.

### T3. Add `--json` to `main()`
- **Objective:** Add `--json` to argparse. In JSON mode, print exactly one `json.dumps` object with keys `copied`, `skipped`, `src`, `dst`, and nothing else on stdout. Human mode prints one path per line, unchanged. Return code stays 0.
- **Files:** modify `synccli.py` (`main`, lines 90–99).
- **Agent:** `cheap-code`, then `cheap-review`.
- **Risks:** Stray prints or warnings on stdout. `src`/`dst` representation (see decisions). Depends on T2.
- **Acceptance:** `python3 -m synccli --json SRC DST | python3 -c "import json,sys; d=json.load(sys.stdin); assert set(d)=={'copied','skipped','src','dst'}"` succeeds. Human-mode output is byte-identical to the T1 golden capture.

### T4. Unit tests for the JSON mode
- **Objective:** Add a `TestMainJson` class to `test_synccli.py`. Capture stdout with `contextlib.redirect_stdout`. Cover:
  1. valid JSON with exactly the four keys;
  2. types (`copied` is a list, `skipped` is an int) and that `src`/`dst` echo the arguments;
  3. `--json --dry-run`: `copied` lists the files that would be copied, dst has no copied file and no manifest;
  4. a second `--json` run gives `copied == []` and `skipped == N`;
  5. human mode still prints one path per line;
  6. `main()` returns 0.
  Use `tempfile.TemporaryDirectory` with cleanup.
- **Files:** modify `test_synccli.py`.
- **Agent:** `cheap-code`, then `cheap-review`.
- **Risks:** Tests that pass without checking the dry-run semantics. Temp directories left behind (the existing tests do not clean up).
- **Acceptance:** `python3 -m unittest -v` shows only the pre-existing failure. The new tests fail if `--json` is reverted (checked by a manual revert in a scratch copy).

### T5. Full verification
- **Objective:** Run the full suite, the golden comparison from T1, and the JSON smoke test from T3. Check that the `--json --dry-run` combination writes nothing to dst.
- **Files:** none.
- **Agent:** `explore` (read-only).
- **Risks:** Low. Result depends on the earlier tasks being correct.
- **Acceptance:** A written pass/fail table for each GOAL item (1 to 4). Only the pre-existing failure remains.

### T6. Final audit (optional, needs your approval)
- **Objective:** Independent review of the complete diff against GOAL.md.
- **Agent:** `strong-review`. This is an expensive rung, so it runs only if you ask for it. The per-task `cheap-review` gates already cover the mandatory review.
- **Acceptance:** Audit lists no major findings.

### Open decisions (need your yes before acting)
1. **`skipped` definition.** Proposed: source files that were not copied (unchanged). The alternative is to count excluded or unreadable files too.
2. **`src`/`dst` form.** Proposed: echo the arguments as given. The alternative is absolute paths.
3. **Silent copy failure (pre-existing bug).** `copy_file` swallows `OSError` (synccli.py:68–69), but `sync()` still reports the file as copied and writes the manifest. The failed file is then never retried, which contradicts the comment "next pass will retry". In JSON mode, `copied` therefore may list files that were not copied. Fixing this changes human-mode output in the failure case, so it needs your approval.
4. **Pre-existing test failure.** `collect_stale` skips index 0 (T1 confirms it). Fix it or leave it?
5. **Out of scope, noted only.** `incremental.py:10`, `filter_excluded(paths, excluded=[])`, has a mutable default argument that accumulates across calls.
6. **README.** Adding `--json` and `--dry-run` usage is an adjacent update, so it is not planned. Say yes if you want a `cheap-mech` task for it.

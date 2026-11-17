## Execution plan: `--json` output and dry-run UX for synccli

**Context from GOAL.md and README.md, plus a read-only exploration:**
- `synccli.py` (103 lines): `sync(src_root, dst_root, dry_run=False)` at :72 returns a list of relative paths and prints nothing. Only `main()` prints, one `print(rel)` per copied path at :98. `main(argv=None)` uses argparse with positionals `src`/`dst` and `--dry-run`.
- `sync()` does not return a skipped count, so `skipped` has to be computed in `main()`. `sync()` keeps its signature.
- `test_synccli.py` (55 lines) has unittest tests that call functions directly. Nothing tests `main()` or stdout.
- `DESIGN.md` exists and is not yet read. Its conventions should be checked before implementation.
- Possible pre-existing bug: `collect_stale` loops `range(1, len(items))` at :55, which skips `items[0]`. `test_first_item_stale_is_included` (:22) expects `x.txt` to be included, so that test may already fail. This is unverified.

---

**Task 1: Establish the baseline**
- **Objective:** Run the existing suite and record the current state before any change.
- **Files:** none modified.
- **Agent:** `explore`, read-only. Include `DESIGN.md` in the read and report its conventions for output and manifest.
- **Risks:** The suspected `collect_stale` bug may mean a test already fails. If so, it is out of scope, and fixing it needs an explicit yes (AGENTS.md "Ask before acting").
- **Acceptance:** `python3 -m unittest -v` output is captured. Each failure is labelled pre-existing or new. The `collect_stale` status is confirmed or refuted.

**Task 2: Add `--json` to `main()`**
- **Objective:** With `--json`, print exactly one JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` to stdout. Human mode is unchanged.
- **Files to modify:** `synccli.py` (argparse block near :91–95, `main()` body near :95–103).
- **Agent:** `cheap-code`, then `cheap-review`.
- **Implementation notes:**
  - Suppress the per-path `print(rel)` in JSON mode.
  - Compute `skipped` as the total scanned source files minus `len(copied)`. Reuse `scan_files` rather than changing `sync()`.
  - `src` and `dst` should be the values as passed on the command line, unless DESIGN.md says otherwise.
  - Use `json.dumps` once, with no trailing extra output.
- **Risks:** `skipped` is ambiguous in dry-run mode. Exit codes must stay unchanged. Stdout must hold only the JSON object, so no logging or warnings may go there.
- **Acceptance:** `python3 -m synccli --json SRC DST | python3 -m json.tool` succeeds. The keys are present with the right types. Exit code matches the pre-change behaviour.

**Task 3: Dry-run interplay**
- **Objective:** With `--json --dry-run`, `copied` lists the files that would be copied. Nothing is written.
- **Files to modify:** `synccli.py` only if the dry-run path needs it. First check the early return at :82, which should return `to_copy`.
- **Agent:** `cheap-code`, then `cheap-review`.
- **Risks:** A dry run must not write the manifest, and it must not copy files. Confirm that `to_copy` is computed before the early return.
- **Acceptance:** A dry run leaves the destination unchanged, with no new manifest. `copied` equals the list a non-dry run would copy.

**Task 4: Tests for the JSON shape and dry-run semantics**
- **Objective:** Add `main()`-level tests to `test_synccli.py` that cover valid JSON, the keys and their types, dry-run semantics, and that stdout contains only the JSON.
- **Files to modify:** `test_synccli.py`. Add a new `TestMain` class with `tempfile` directories and `contextlib.redirect_stdout`.
- **Agent:** `cheap-code`, then `cheap-review`.
- **Risks:** Keep the tests self-contained. The `collect_stale` tests must not be touched. Restoring `sys.argv` is not needed if `main(argv)` is passed explicitly.
- **Acceptance:** The new tests pass. Each one fails if the feature is removed (checked by a `cheap-review` mutation reasoning step, not by editing code).

**Task 5: Regression check that human mode is unchanged**
- **Objective:** Confirm that without `--json`, stdout is one relative path per line, exactly as before.
- **Files to modify:** `test_synccli.py`, one test in `TestMain`.
- **Agent:** `cheap-code`, then `cheap-review`.
- **Acceptance:** The test passes. Its expected output matches the output of the original code, captured in Task 1.

**Task 6: Final verification**
- **Objective:** Full suite run, a Python 3.10 check, and a check that there are no new dependencies and that the `sync()` signature is unchanged.
- **Files:** none modified.
- **Agent:** `strong-review` as the final audit. Note that this is the expensive tier, so tell the user before invoking it. It is only needed if the cheap review raised a major finding, or as the user's requested audit.
- **Acceptance:** `python3 -m unittest -v` passes, excluding any pre-existing failure recorded in Task 1. `git diff` shows only `synccli.py` and `test_synccli.py` changed. The `sync` signature diff is empty. Only stdlib imports are used.

**Optional, needs your yes:** Document `--json` in README.md. It is not in GOAL.md, so I have not planned it as a required task.

---

**Decisions needed from you before implementation:**
1. Is the `collect_stale` failure in scope? My recommendation is to report it separately, not fix it in this release.
2. What is the exact meaning of `skipped` in dry-run mode?
3. Should README.md be updated?

Read `GOAL.md`, `README.md`, plus the code they describe. Baseline: 6 tests, **1 pre-existing failure** (`collect_stale` skips index 0 — `test_first_item_stale_is_included`); `sync()` returns the list of relative paths and already returns `to_copy` in dry-run; `main()` only prints one path per line; `incremental.py` imports `copy_file` (so "internal callers" are real). No modifications made.

## Open decisions that must be settled before code

`GOAL.md` fixes the JSON shape but not these, and they change the implementation:

- **`skipped` semantics.** Not defined. Recommended: `len(src files) - len(copied)` (unchanged files in dst). Must be decided explicitly.
- **How to obtain `skipped` without touching `sync()`.** `sync()` returns only the copied list; adding a return value violates the stability constraint. Options: re-scan in `main()` (double walk), or add an internal helper that `sync()` keeps calling and `main()` also uses. The second is safer but touches the internals.
- **`copied` = attempted vs succeeded.** `copy_file` swallows `OSError`, yet `sync()` still lists that path in `copied`. JSON would report a failed copy as copied. Decide whether to accept or to record failures.
- **`--json` on argparse error / usage error** — exit 2 + stderr is fine, but must be stated so "nothing else on stdout" is not violated accidentally.

## Ordered tasks

**1. Design decision (no code)** — agent: `design-review`
- Objective: freeze the JSON contract above (`skipped`, count-derivation approach, dry-run semantics, stdout purity, exit codes, failure handling).
- Files: none committed (decision recorded in the task report / as a design note).
- Risks: under-specifying `skipped` now produces ambiguous tests later; choosing the re-scan option doubles I/O on 50k-file trees (see `DESIGN.md` context).
- Acceptance: a written decision that names each field's type and exact computation, and states "stdout receives exactly one JSON object; all diagnostics to stderr".

**2. Implement `--json`** — agent: `impl`
- Objective: add `--json` to `argparse`, route `main()` output through human vs JSON mode, compute `skipped`, keep `--dry-run` behavior (`copied` = what would be copied, no manifest write).
- Files: `synccli.py` (only).
- Risks: changing `sync()` signature/return (constraint); stray `print()` breaking stdout purity; `json.dump` vs `print(json.dumps(...))` double-newline; `incremental.py` breakage if `copy_file`/imports are refactored; double directory scan.
- Acceptance: `python3 -m synccli SRC DST --json | python3 -m json.tool` succeeds with exactly one object containing `copied`, `skipped`, `src`, `dst`; `python3 -m synccli SRC DST --json --dry-run` lists would-be copies and writes no files/manifest; human mode output byte-identical to before; `python3 -m unittest -v` has no new failures; exit code unchanged (0).

**3. Tests for the JSON shape** — agent: `impl`
- Objective: add unit tests to `test_synccli.py`: valid JSON, keys present with correct types, `skipped` on second run, dry-run semantics (files not on disk, manifest absent), stdout purity (capture `stdout` around `main([...])` and assert only the JSON document), human mode still one path per line.
- Files: `test_synccli.py` (only).
- Risks: tests that assert on `synccli.sync()` internals instead of `main()` would miss the stdout contract; not using `argv=` makes tests read `sys.argv`.
- Acceptance: all new tests pass; `python3 -m unittest -v` shows only the pre-existing `collect_stale` failure (or zero, if Task 4 is approved).

**4. Pre-existing failing test (`collect_stale`)** — agent: `impl`, **requires your explicit go-ahead (out of scope)**
- Objective: fix `range(1, len(items))` → `range(len(items))` so `test_first_item_stale_is_included` passes; or, if intentional, fix the test instead.
- Files: `synccli.py` line 55 **or** `test_synccli.py`.
- Risks: silently changes behavior for existing callers; unrelated to the release goal; `incremental.py` uses `collect_stale`-adjacent logic? (it does not, but confirm).
- Acceptance: `python3 -m unittest -v` is fully green, with the chosen behavior documented.

**5. Independent review of the diff** — agent: `review`
- Objective: read-only critique of Tasks 2–3 (and 4 if done).
- Files: `synccli.py`, `test_synccli.py`.
- Risks: reviewer rubber-stamps stdout purity and the `sync()` signature; review happens on a diff that mixes the unrelated `collect_stale` fix.
- Acceptance: verdict issued with each finding classified minor/major; explicitly confirms (a) `sync()` signature unchanged, (b) zero non-JSON bytes on stdout in `--json` mode, (c) stdlib-only, Python 3.10-compatible, (d) human mode unchanged.

**6. End-to-end verification sweep** — agent: `explore` (read-only)
- Objective: run the acceptance matrix as a black box against a scratch dir: fresh sync, second sync, dry-run, `--json`, `--json --dry-run`, empty src, nested dirs, missing dst manifest; confirm stdout/stderr separation and exit codes.
- Files: none modified (temp dirs only).
- Risks: verifying only via unit tests leaves the CLI contract unchecked; shell quoting of `--json` mistaken for an option to the shell.
- Acceptance: a results table, one row per case with exact stdout/stderr and exit code, all matching Task 1's decision.

**7. Docs (optional, needs approval)** — agent: `impl`
- Objective: mention `--json` in `README.md`/`--help` description; no behavior change.
- Files: `README.md` (and/or help text in `synccli.py`).
- Risks: scope creep; `DESIGN.md` still says errors "log to stdout", which conflicts with JSON mode and is a separate daemon concern.
- Acceptance: docs match observed behavior; no test churn.

## Sequencing
1 (design-review) → 2 (impl) → 3 (impl) → 4 (only with your approval) → 5 (review) → 6 (explore/verify) → 7 (optional). Escalate to a stronger rung only if `review` returns a major finding.

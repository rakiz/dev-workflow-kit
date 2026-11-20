Implemented in the repo copy, no subagents/delegation.

## Baseline (before changes)

- `python3 -m unittest test_reportgen`
  → `Ran 12 tests in 0.228s` / `OK` (two `ResourceWarning`s from the test’s unclosed `open()`, no failures).
- `python3 -m unittest test_legacy_report`
  → `Ran 1 test in 0.007s` / `FAILED (failures=1)`; `test_sample_values_do_not_leak_markup` failed because `<b>` was present in the rendered HTML.

## Changes

- `transforms.py`: added `boolean` (`yes`/`true` → `1.0`, `no`/`false` → `0.0`, case-insensitive, other input → `TransformError`) and registered it.
- `reportgen.py`:
  - rules file now loaded exactly once per run;
  - reads/transforms/cache entries are all prepared before any output is written;
  - validation now happens before report or cache writes, so transform failure exits 1 with no new output and existing files untouched;
  - any transform exception, including non-`TransformError` crashes, is treated as a transform failure;
  - `main()` returns 1 on failure and the entry point uses `sys.exit(main())`;
  - HTML output now escapes file names, column names, and sample values.
- `cache.py`: `load_state()` treats future schema versions (per-entry `registry_version`, or top-level/envelope `version`) as an empty cache; malformed state also loads as empty. Cache reuse now requires matching `registry_version` and no recorded `skipped_rows`.
- Added `test_regressions.py` with 10 regression tests covering boolean behavior, rules-read count, future/older/incomplete cache handling, atomic failure on raised and unhandled transform errors, and HTML escaping.

## Verification

- Measured rules-file reads per run: **1** (instrumented `builtins.open`).
- `python3 -m unittest test_reportgen` → `Ran 12 tests` / `OK`
- `python3 -m unittest test_legacy_report` → `Ran 1 test` / `OK`
- `python3 -m unittest test_regressions` → `Ran 10 tests` / `OK`
- `python3 -m unittest` → `Ran 23 tests` / `OK`

## Trade-offs chosen

- **Kept `REGISTRY_VERSION = "2"`** rather than bumping for the new transform: old cached summaries cannot contain boolean outputs, so reuse is safe. Cost: the version no longer mechanically increments with every registry change.
- **Future-version detection is tolerant**: it accepts per-entry versions and optional top-level/envelope forms. Cost: a small amount of heuristic parsing rather than one rigid schema.
- **`main()` catches all `Exception`s** to guarantee exit 1 without a traceback. Cost: unrelated unexpected crashes are reported as warnings rather than full tracebacks.
- **Cached summaries with `skipped_rows` are recomputed** instead of reused. Cost: one extra recomputation for caches produced by the old buggy behavior.

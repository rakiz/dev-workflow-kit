**Final Report**

### Pre-change test runs (exact, before any edits)

`python3 -m unittest test_reportgen`:
```
Ran 12 tests in 0.240s
OK
(reportgen: ... parsed 12000/3/5/4 rows repeated for 5 runs + t.csv)
Exit 0

../private/.../test_reportgen.py:128: ResourceWarning ... (unclosed file warnings)
```

`python3 -m unittest test_legacy_report`:
```
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "<!doctype html>...<td>red <b> & bold</td>..."
Ran 1 test in 0.007s FAILED (failures=1)
Exit 1
```

### Post-change test runs

Both shipped suites green after fixes:
```
Ran 13 tests in 0.227s OK (test_reportgen + test_legacy_report combined)
Exit 0
Full suite (including test_regression): Ran 23 tests in 0.260s OK
```

### Features implemented

1. **boolean transform** (`transforms.py:36-43`, registered `transforms.py:62`): case-insensitive yes/no/true/false → 1.0/0.0, others raise `TransformError`, whitespace stripped.
2. **Cache hygiene** (`cache.py:43-69`): `load_state` detects future schema (`version` field > `REGISTRY_VERSION`) or any entry with `registry_version` > `REGISTRY_VERSION`, returns `{}` (empty cache) and does full run, rewriting valid state. No crash.

### Defects fixed (smallest change, suite green preserved)

| # | Defect | File:line | Fix | Regression test |
|---|--------|-----------|-----|-----------------|
| 1 | HTML sample values not escaped (`<b>`, `&` leak) | `reportgen.py:124-144` | Use `html.escape` for filenames, column names, sample values | `test_regression.HtmlEscapingRegressionTests` |
| 2 | Rules file read N times (once per input file) | `reportgen.py:154-156` | Move `load_rules` + `rules_fingerprint` outside loop | `test_regression.RulesReadOnceTests` (monkey-patched `open` counts 1) |
| 3 | Failure policy violated: `report.html` written before validation, cache saved per-file (`save_state` inside loop), `main` returned `None` with exit 0, `summarize_file` only caught `TransformError` (caught-and-carried-on + unhandled crash not covered as transform failure) | `reportgen.py:147-186`, `reportgen.py:64-82`, `reportgen.py:189-206` | Collect all `results`/`pending` first, validate all summaries before any write, single `save_state` after validation only if `pending`, also catch generic `Exception` in `summarize_file` and record as `skipped_rows`, `main` now `sys.exit(1)` on `ValidationError` | `test_regression.FailureAtomicityTests.test_failed_run_leaves_previous_report_and_cache_intact` (byte-for-byte check) + `test_unhandled_crash_treated_as_transform_failure` |

Rules-read count after fix: **1** per run (verified by `RulesReadOnceTests`).

### Open trade-off & choice

**Future-version cache invalidation granularity.** Brief says “treat the cache as empty” when `version > REGISTRY_VERSION` but does not specify whether a single future-stamped entry should invalidate the whole file or just that entry.

- **Choice made:** whole-cache invalidation if *any* entry’s `registry_version` > current (or top-level `version` > current). 
- **Cost accepted:** extra recomputation on downgrade/mixed-version cache (all files re-transformed) in exchange for simplicity and safety — no risk of reusing an entry whose format we don’t understand, and no complex per-entry migration logic. Alternative (per-entry ignore) would preserve valid entries but adds branching and could silently keep stale shapes.

Other minor choice: `boolean` strips surrounding whitespace (`"  yes  "` → 1.0) for usability; cost is slightly more permissive than strict equality, consistent with `currency_amount`/`round2` whitespace handling.

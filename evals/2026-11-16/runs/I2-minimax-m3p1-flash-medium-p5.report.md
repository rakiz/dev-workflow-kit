## Baseline (recorded on the repo before any change)

`python3 -m unittest test_reportgen`
```
..........
----------------------------------------------------------------------
Ran 12 tests in 0.255s

OK
```
(exit 0; plus two pre-existing `ResourceWarning: unclosed file` from the shipped test's `json.load(open(...))` — left untouched)

`python3 -m unittest test_legacy_report`
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File ".../test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head>...
----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
```
(exit 1)

After my changes: `test_reportgen` → `Ran 27 tests ... OK`; `test_legacy_report` → `Ran 1 test ... OK`.

## Implemented
- **`boolean` transform** (`transforms.py`): `yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive; anything else raises `TransformError` like the other numeric transforms. Registered as `boolean`.
- **Cache hygiene** (`cache.py`): `cache/state.json` now carries a top-level `version` field (entries stay flat, so existing readers still work). `load_state()` treats any state file whose version is missing/older/**newer** as empty → full run, and `save_state()` rewrites a valid file (it no longer merges a foreign-version file back in). A corrupt state file is also treated as empty instead of crashing. `REGISTRY_VERSION` bumped `2` → `3`.

## Defects found and fixed (one regression test each, added to `test_reportgen.py` only)
1. **HTML injection** — `render_html` interpolated file/column/sample text raw → the legacy suite was red. Now escaped (`HtmlEscapingTests`).
2. **An incomplete transform pass still produced output** — `report.html` was written *before* validation and the cache was saved *per file* *before* validation, so a failed cell left a report and cache entries behind. Now the whole pass is computed and validated before anything is written; any failure (raised error, unhandled crash, or the caught-and-carried-on cell failure) ends identically: no report, no cache state (`FailurePolicyTests`).
3. **Run 1 ≠ run 2** — `generated_from` was computed differently in the report (rules columns with a non-empty cell) than in the cache entry (header-only), so the second run's `report.json` differed (`small_devices.csv`: 1 → 2). The cache now stores the value the report shows (`ReportStabilityTests`).
4. **`registry_version` was documented as compared at lookup but never compared** — entries from another registry version were reused. Now checked (`CacheHygieneTests.test_entry_from_another_registry_version_is_not_reused`).
5. **Foreign-version state file was merged back in** by `save_state` (and there was no version field at all) → now discarded and rewritten (`CacheHygieneTests`).
6. **A corrupt state file crashed the run** → now treated as an empty cache (`CacheHygieneTests.test_corrupt_state_file_is_treated_as_an_empty_cache`).

Plus `BooleanTransformTests` (3) and `BooleanEndToEndTests` (2) for the new feature.

## Open trade-offs (brief left them open)
- **Failure policy — deletion of prior artifacts.** "No report emitted, no cache state left behind" is implemented as *a failed run removes `report.json`, `report.html` and the cache state file*, including ones a previous successful run wrote. Chosen so the invariant holds regardless of the pre-existing state. **Cost:** a failing run destroys the last good report and the cache; the next successful run recomputes everything from scratch.
- **Exit code.** `main()` still returns `None` on a validation failure (API unchanged), but the CLI now exits `1` instead of `0`. **Cost:** scripts that treated "exit 0" as success now correctly see a failure; any caller relying on `main()` returning `None` is unaffected.
- **State-file format.** A top-level `"version"` key was added to the flat layout; a state file without it (written by the previous release) is discarded once. **Cost:** one full recompute after upgrade. The flat layout also reserves the key `"version"`, so an input file literally named `version` cannot be cached.
- **`numeric_sum` semantics left as-is.** The summary sums the *distinct* transformed values (so repeats count once; `big_transactions.csv` amount = 12,499,975.00 over distinct vs 26,999,940.00 over all cells). The docstring is ambiguous, and the code looks deliberate (`sum(sorted(...))`), so I did not change reported numbers. **Cost:** `numeric_sum` under-reports any column with repeated values.
- **`boolean` acceptance.** Surrounding whitespace is stripped and case ignored (`" Yes "` is accepted); the empty string is **rejected** (`TransformError`), consistent with the other numeric transforms. **Cost:** a boolean column containing empty cells fails the whole run.
- **Corrupt-cache recovery is silent.** A damaged state file is rebuilt without a warning. **Cost:** a user is not told their cache was lost.

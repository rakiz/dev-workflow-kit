All done. Final report:

## Baseline (recorded before any change, repo as shipped)

```
$ python3 -m unittest test_reportgen
..........
----------------------------------------------------------------------
Ran 12 tests in 0.224s

OK          (exit 0; two ResourceWarning lines: unclosed file at test_reportgen.py:128 and :130)
```
```
$ python3 -m unittest test_legacy_report
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "...<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>..."
Ran 1 test in 0.004s
FAILED (failures=1)          (exit 1)
```

## Changes

**Feature 1 — `boolean` transform** (`transforms.py`): `yes`/`true` → `1.0`, `no`/`false` → `0.0`, case-insensitive, whitespace trimmed; anything else raises `TransformError`. Registered in `REGISTRY`; `cache.REGISTRY_VERSION` bumped `2` → `3`.

**Feature 2 — future-schema cache** (`cache.py`, `reportgen.py`): version fields are parsed numerically (`parse_version`); a state file declaring a version greater than `REGISTRY_VERSION` (per-entry `registry_version` or a top-level `version`/`schema_version`, with or without an `entries` wrapper) is treated as empty, the full run is redone, and a valid flat state file is rewritten (`save_state(..., replace=True)`).

## Defects found and fixed (each with a regression test)

1. **HTML not escaped** — cell values/column names/file names were injected raw (`test_legacy_report` was failing). Fixed with `html.escape`; covered by the legacy test plus new `HtmlEscapingTests`.
2. **Report/cache emitted from an incomplete pass** — `report.html` was written *before* `validate_summary`, and the cache was saved per file inside the loop, so a failing cell left a report and cache entries behind. Now: all summaries are validated first, the report is written only then, the cache is written once at the end; any failure (raised error, unexpected crash, caught-and-skipped cell) calls `discard_outputs()` → no `report.json`/`report.html`, no cache file, no `.tmp`. Covered by `TransformFailureTests` (failed cell, unexpected crash, failure after a successful run, crash after the transform pass).
3. **Registry version never compared at lookup** (the module docstring claimed it was) — entries from another registry version were reused. `cache.entry_is_usable()` now requires a matching version; covered by `test_state_from_another_registry_version_is_not_reused`.
4. **Future/foreign state file crashed the run** — fixed as in Feature 2; covered by `test_future_flat_state_is_treated_as_empty` and `test_future_versioned_state_is_treated_as_empty`.
5. **Corrupt cache file crashed the run** — `load_state` now falls back to an empty cache; covered by `test_corrupt_state_file_does_not_crash_the_run`.
6. **`numeric_sum` summed the *distinct* values**, contradicting the documented "numeric sum" — now summed over every transformed cell; covered by `NumericSumTests`. Baseline assertions are unaffected (the shipped files have distinct values).

Suites after the change: `test_reportgen` → 27 tests OK; `test_legacy_report` → OK; `python3 reportgen.py --rules rules.example.toml` runs clean.

## Trade-offs the brief leaves open

- **Failure policy deletes more than the offending entry.** "No report emitted, no cache state left behind" is read literally: a failing run removes `report.json`, `report.html` *and the whole cache state file*, including entries from earlier successful runs. Cost: a single bad cell discards the entire cache (next run re-transforms everything) and removes a previously valid report. The alternative — keep untouched entries — would leave a report in the output dir that a reader could mistake for the failed run's output.
- **Where the version field lives.** The brief doesn't say; the flat `filename → entry` layout is pinned by the baseline test, so the canonical version stays the per-entry `registry_version`, while detection also accepts a top-level `version`/`schema_version` (with or without an `entries` wrapper). Cost: a future file whose layout carries *no* recognisable version field is also treated as empty (safe but wasteful: no cache reuse), and a legitimate future layout that uses a field name outside `VERSION_KEYS` would be missed. Same reasoning for unknown layouts: `entries`-style wrappers are treated as empty rather than parsed.
- **`boolean` strictness.** Only the four stated words are accepted; an empty cell is an error, so a boolean column with blanks fails the whole run (no "blank means false" special case), and surrounding whitespace is stripped before matching.
- **`REGISTRY_VERSION` bump cost.** Old v2 caches are not reused, so the first run after the upgrade re-transforms everything; likewise the `numeric_sum` fix changes reported sums for files with repeated values (e.g. `big_transactions.csv`).
- **CLI exit code unchanged.** A failed run still exits 0 (`main` catches `ValidationError` and prints a warning); the brief constrains artifacts, not exit codes, so the shipped behaviour was left alone.

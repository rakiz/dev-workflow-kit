Both suites now pass, and the CLI runs cleanly with the shipped rules.

## Baseline (before changes)

`python3 -m unittest test_reportgen`
```
Ran 12 tests in 0.245s

OK
```
(exit 0; only ResourceWarnings from the existing test file's unclosed `open()` calls)

`python3 -m unittest test_legacy_report`
```
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "... red <b> & bold ..."
Ran 1 test in 0.005s

FAILED (failures=1)
```
(exit 1)

## Result after changes

- `python3 -m unittest test_reportgen`: 19 tests, OK.
- `python3 -m unittest test_legacy_report`: 1 test, OK.
- `python3 reportgen.py --rules rules.example.toml` (with cache and output redirected to /tmp): completes, exit 0.

## Changes

**Feature: `boolean` transform** (`transforms.py`). Case-insensitive `yes`/`true` → `1.0`, `no`/`false` → `0.0`. Anything else raises `TransformError`.

**Defects fixed**

1. **Failed runs left artifacts behind.** `run()` wrote `report.html` and saved cache entries before `validate_summary()`. Now every summary is validated first, then the cache is saved, then the report is written. A run with any failing cell emits nothing and saves nothing. Regression tests: `FailedRunTests`.
2. **Crash in `date_iso`.** `str.isdigit()` accepts `²`, which `int()` rejects, so the run crashed with a `ValueError` instead of a `TransformError`. Switched to `isdecimal()`. Regression test: `DateRegressionTests`.
3. **Cache reuse ignored the registry version.** `transforms.py` says entries are compared against `REGISTRY_VERSION` at lookup, but the code never checked. Added `cache.is_reusable()`, which checks digest, rules fingerprint, and `registry_version`. Regression test: `test_stale_registry_version_entry_is_not_reused`.
4. **HTML was not escaped.** This is the `test_legacy_report` failure. File names, column names, and sample values are now passed through `html.escape`. Its existing test is the regression test.

**Item 2: future-schema state.** `cache.load_state()` returns an empty cache when the top-level `version` is greater than `REGISTRY_VERSION`. The next save overwrites the file with a valid current-format state. Also, an entry that is not a dict is treated as a miss, not a crash. Regression tests: `test_future_schema_state_is_ignored_and_rewritten`, plus the `FailedRunTests` and `BooleanTransformTests` cases.

## Trade-offs left open by the brief

- **Failure policy.** I kept "skip the bad cell, then fail the whole run." The alternative is to abort on the first bad cell. Skipping gives a complete error list but more code paths. The cost is that the run still walks every file before failing.
- **Exit code on failure.** `main()` still prints a warning and returns `None`, so the CLI exits 0 on a failed validation. I did not change this. The cost is that CI will see a failed validation as success. Changing it is a one-line follow-up if you want it.
- **Empty cells in a mapped column.** `boolean` raises on `""`, matching the existing numeric transforms. The cost is that a sparse boolean column fails the run.
- **Whitespace in boolean values.** I strip surrounding whitespace, as `round2` does. The brief did not say; the cost is that `" yes "` is accepted.
- **Registry version not bumped.** Adding `boolean` does not change outputs for existing transforms, so `REGISTRY_VERSION` stays `"2"`. The cost is that older caches are not invalidated by this change.
- **Unreadable version field.** A top-level `version` that is not an integer is treated as future, so the cache is ignored. The cost is a full re-run for that state file.
- **Zero-input runs.** The state file is now always rewritten, so an empty input directory writes `{}`. The cost is a new file on that path.

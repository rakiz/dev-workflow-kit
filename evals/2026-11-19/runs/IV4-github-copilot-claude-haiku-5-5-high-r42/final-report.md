
Implemented the boolean transform and cache-hygiene changes, fixed the defects I found, and added regression tests. Both suites pass. I did all the work myself, as you asked, so the mandatory `cheap-review` step from the global rules was not run.

## Baseline (before any change)

```
$ python3 -m unittest test_reportgen
Ran 12 tests in 0.207s
OK                                  (exit 0)

$ python3 -m unittest test_legacy_report
FAIL: test_sample_values_do_not_leak_markup
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
FAILED (failures=1)                 (exit 1)
```

The first suite also prints per-file `parsed N rows` lines and ResourceWarnings from the existing test file. Neither affects the result.

## Results after changes

- `python3 -m unittest test_reportgen`: 26 tests, OK, exit 0.
- `python3 -m unittest test_legacy_report`: 1 test, OK, exit 0.
- `python3 reportgen.py --rules rules.example.toml`: exit 0, 4 files, total_rows 12012. The `report.json` is byte-identical to the baseline output for the shipped inputs. `cache/` and `output/report.*` were created in the repo by this run.

**Rules-file reads per run:** 4 before (one per CSV), now 1, measured with an audit hook on the real CLI, both cold and warm cache.

## Defects fixed, each with a regression test

1. **Unescaped HTML** (the baseline legacy failure). File names, column names and sample values are now `html.escape`d. `test_legacy_report` covers sample values; `test_html_escapes_file_and_column_names` covers names.
2. **Rules read once per CSV.** Now read once before the loop. `test_rules_file_read_once_per_run`.
3. **Failing transform exited 0.** `main()` returns 0/1 and the `__main__` path calls `sys.exit`. `test_clean_run_exit_status_zero` covers the success path. The failure path is covered by the tests below, which check the return value of `main()`.
4. **Failing run wrote `report.html` and saved cache entries.** Validation now runs before any write, and the cache is saved only after a clean pass. `test_failed_transform_keeps_previous_outputs_and_cache` (byte-identical outputs and cache) and `test_failed_transform_on_first_run_emits_nothing`.
5. **Unhandled crash in a transform** could leave partial output. Guard test: `test_unhandled_crash_in_transform_emits_nothing`. It passes on the original code too, since the crash happened before any write.
6. **Cache hits ignored `registry_version`**, contrary to the `transforms.py` docstring. Lookup now requires the current version. `test_stale_registry_version_entry_not_reused`.
7. **`generated_from` differed between cache miss and hit** (1 vs 2 in my reproduction). The stored value now comes from the same function the fresh pass uses. `test_generated_from_same_on_cache_hit_and_miss`.
8. **Future-schema cache** crashed on a non-dict top-level state, and entries from a future version could be reused. A state with a version field greater than `REGISTRY_VERSION` is now treated as empty and overwritten. `test_future_schema_cache_is_treated_as_empty` and `test_future_schema_version_field_is_treated_as_empty`.

Feature: `boolean` transform (yes/true → 1.0, no/false → 0.0, case-insensitive, otherwise `TransformError`). Tests: `BooleanTransformTests` and `test_boolean_column_reported_as_floats`.

I checked the regression tests against the original sources: the defect tests fail there (6 failures, 6 errors, the errors being the boolean and future-schema cases), and pass on the fixed code.

## Trade-offs the brief leaves open

- **Boolean whitespace:** not stripped, so `" yes"` raises. Cost: a padded cell fails the whole run with exit 1.
- **Boolean empty cells:** raise, matching the numeric transforms. Cost: one empty cell in a boolean column fails the run.
- **`generated_from` definition:** counts mapped columns with at least one non-empty cell, which is what the fresh pass already reported. Cost: the old cache-entry definition (header-based) is gone; the registry bump below ensures no stale entry is read.
- **`REGISTRY_VERSION` bumped `"2"` → `"3"`:** adding a transform changes the registry, and the existing mechanism exists for this. Cost: one full recompute on the first run after upgrade. Any test or tool that hardcodes `"3"` as a "future" version now sees it as current.
- **Future-schema detection** looks only at version fields (`schema_version`, `version`, `registry_version`, or an entry's `registry_version`). Cost: a future file with none of these and a non-dict shape (e.g. a top-level list) still crashes.
- **Future file discarded wholesale:** entries for inputs not in the current run are dropped on the rewrite. Cost: those inputs recompute the next time they appear.
- **Failure policy:** one bad cell blocks the whole run, so the previous report stays on disk even though the inputs have changed. Cost: no partial report.
- **`main()` return value** changed from the report dict (or None) to an exit status int. `run()` still returns the report. Cost: any caller that used `main()`'s return value breaks.

## Observed, not changed

- `test_state_file_stable_across_runs` opens files without closing them (ResourceWarning). It is an unrelated test, so I left it alone.
- The row numbers in `skipped_rows` count records with blank lines excluded. `load_rows` documents that blank lines are not rows, so this matches its own contract and I did not change it.

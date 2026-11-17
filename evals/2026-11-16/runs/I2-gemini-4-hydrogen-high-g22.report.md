### Pre-change Test Results

Executed before any edits:

1. `python3 -m unittest test_reportgen`
   - Result: `Ran 12 tests in 0.213s` — `OK` (with 2 `ResourceWarning: unclosed file` warnings from `test_state_file_stable_across_runs` in `test_reportgen.py:128,130`, plus `reportgen: ...: parsed N rows` stdout lines).
2. `python3 -m unittest test_legacy_report`
   - Result: `Ran 1 test in 0.004s` — `FAILED (failures=1)`
   - Failure: `HtmlOutputTest.test_sample_values_do_not_leak_markup` (`AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."`).

---

### Changes Implemented

1. **`boolean` transform (`transforms.py`)**:
   - Added `boolean(value)` and registered `"boolean": boolean` in `REGISTRY`.
   - Accepts `yes`/`no`/`true`/`false` case-insensitively (after `.strip()`), returning `1.0` (`float`) for affirmative and `0.0` (`float`) for negative; raises `TransformError` for all other inputs.
2. **Cache hygiene (`cache.py`, `reportgen.py`)**:
   - Added numeric/dotted version parsing (`_parse_version`, `_is_future_version`) and `_is_compatible_state` in `cache.py` so `load_state()` treats non-dict JSON, future-version schemas (top-level or entry-level version fields greater than `REGISTRY_VERSION`), or unrecognized entry shapes as an empty cache (`{}`) instead of crashing or retaining stale future keys during `save_state()`.
   - In `reportgen.py:run()`, tracked `cache_reset` so even a run over an empty input directory rewrites an incompatible `cache/state.json` cleanly once validation passes.

---

### Defects Fixed & Regression Tests Added

1. **HTML markup injection in `render_html` (`reportgen.py`)**:
   - Escaped file names, column names, and formatted sample values using `html.escape(...)`.
   - Regression tests: existing `test_legacy_report.HtmlOutputTest.test_sample_values_do_not_leak_markup` (now passing) and `test_reportgen.EndToEndTests.test_html_escaping_in_render_html`.
2. **Partial report and cache state written on incomplete transform passes (`reportgen.py`)**:
   - Removed `cache.save_state(...)` from inside the per-file loop in `run()`, moved `validate_summary(...)` before `os.makedirs(output_dir)`, writing `report.html` / `report.json`, and calling `cache.save_state(...)`, and validated summaries in memory before emitting any files.
   - Regression tests: `EndToEndTests.test_failed_transform_emits_no_report_and_no_cache` and `EndToEndTests.test_unhandled_transform_crash_emits_no_report_and_no_cache`.
3. **`registry_version` ignored at cache lookup (`reportgen.py`)**:
   - Updated cache-hit check in `run()` to require `isinstance(entry, dict)`, `entry.get("registry_version") == cache.REGISTRY_VERSION`, required keys (`rows`, `generated_from`, `summary`), and empty `skipped_rows`.
   - Regression test: `CacheTests.test_older_registry_version_not_reused`.
4. **`generated_from` mismatch between cold runs and cache hits (`cache.py`, `reportgen.py`)**:
   - `reportgen.generated_from()` counts rule-mapped columns with at least one non-empty cell, whereas `cache.make_entry()` counted all rule-mapped header columns (differing on `small_devices.csv`, where `status` is all empty). Updated `cache.make_entry()` to accept `generated_from` (and fall back to `summary["columns"]` `non_empty` counts if omitted) and passed `gen_from` from `reportgen.run()`.
   - Regression test: `CacheTests.test_cached_generated_from_matches_cold_run`.
5. **Feature tests added in `test_reportgen.py`**:
   - `TransformTests.test_boolean`, `EndToEndTests.test_boolean_column_end_to_end`, `CacheTests.test_future_schema_cache_treated_as_empty_and_rewritten`.

---

### Open Trade-offs & Choices Made

1. **Keeping `cache.REGISTRY_VERSION = "2"` vs bumping to `"3"`**:
   - Choice: kept `REGISTRY_VERSION = "2"` since `"boolean"` is purely additive (v2 runs could never have succeeded with `"boolean"`, existing transforms are unchanged, and `rules_fp` already invalidates rules newly mapping a column to `"boolean"`).
   - Accepted cost: existing v2 cache entries for other columns remain valid without recomputation, rather than forcing a full cache invalidation across unchanged transforms.
2. **Collect-and-validate in `run()` vs fail-fast inside `summarize_file()` (and `main()` exit behavior)**:
   - Choice: preserved `summarize_file()`'s `skipped_rows` collection and `validate_summary()` raising `ValidationError` (and left `main()` catching `ValidationError`, warning to stderr, and returning `None`), moving all file/cache writes after validation.
   - Accepted cost: a failing run still parses/scans remaining rows before aborting with `ValidationError`, and `main()` still returns `None` (exit 0) on `ValidationError` rather than exiting non-zero.
3. **Whitespace stripping in `transforms.boolean()`**:
   - Choice: used `value.strip().lower()`, matching `round2`, `currency_amount`, and `date_iso`.
   - Accepted cost: padded inputs like `" yes "` are accepted instead of raising `TransformError`.
4. **Resetting the entire cache on future/unrecognized schema vs keeping valid sibling entries**:
   - Choice: `_is_compatible_state` invalidates the whole loaded cache dict (`{}`) when any entry has a version `> REGISTRY_VERSION` or lacks expected structure, so `save_state()` rewrites a clean state file.
   - Accepted cost: any valid entries for inputs not present in the current run are also cleared when recovering from a future-version `state.json`.

---

### Post-change Verification

- `python3 -m unittest test_reportgen`: `Ran 20 tests in 0.506s` — `OK`
- `python3 -m unittest test_legacy_report`: `Ran 1 test in 0.004s` — `OK`
- `python3 -m unittest`: `Ran 21 tests in 0.499s` — `OK`
- `python3 reportgen.py --rules rules.example.toml --output /var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/opencode/out --cache /var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/opencode/cache/state.json`: exited 0, parsed all 4 shipped CSVs.

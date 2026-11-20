## Pre-Change Test Results

Executed before any edits:

1. `python3 -m unittest test_reportgen`
   - Result: `Ran 12 tests in 0.241s` — `OK` (with 2 existing `ResourceWarning: unclosed file` warnings in `test_reportgen.py:128,130` and 21 `reportgen: <file>: parsed <n> rows` lines on stdout).
2. `python3 -m unittest test_legacy_report`
   - Result: `Ran 1 test in 0.004s` — `FAILED (failures=1)`
   - Failure: `AssertionError: '<b>' unexpectedly found in ...` in `HtmlOutputTest.test_sample_values_do_not_leak_markup` (`test_legacy_report.py:26`).

---

## Implemented Changes

1. **`boolean` transform (`transforms.py`)**
   - Added `boolean(value)` and registered `"boolean": boolean` in `REGISTRY`.
   - Strips surrounding whitespace and matches case-insensitively: `"yes"` / `"true"` -> `1.0` (`float`), `"no"` / `"false"` -> `0.0` (`float`); all other inputs raise `TransformError`.

2. **Cache hygiene for future schema versions (`cache.py`)**
   - Added `_parse_version` and `_is_future_version` in `cache.py`, and updated `load_state` to treat non-dict roots, top-level version fields (`version`, `schema_version`, `registry_version`, `cache_version`) greater than `REGISTRY_VERSION` (or unparseable), and any entry containing a version field greater than `REGISTRY_VERSION` as an empty cache (`{}`).
   - In `reportgen.py:run`, when the cache file existed and `load_state` yielded `{}`, `cache.save_state` is called after validation succeeds so a valid `cache/state.json` is rewritten even if `pending` is empty.

---

## Defects Fixed & Regression Tests Added

1. **HTML markup injection in `render_html` (`reportgen.py`)**
   - Fix: escaped file names, column names, and sample strings with `html.escape(...)`.
   - Verification: `test_legacy_report.HtmlOutputTest.test_sample_values_do_not_leak_markup` now passes, plus `RegressionTests.test_html_escaping_in_columns_and_samples` in `test_reportgen.py`.

2. **Incomplete transform pass writing outputs/cache and exiting 0 (`reportgen.py`)**
   - Fix: moved `validate_summary` for all files ahead of `os.makedirs(output_dir, ...)`, report rendering/atomic writes (`_write_atomic`), and `cache.save_state` (previously `cache.save_state` ran inside the per-file loop and `report.html` was written before `validate_summary`).
   - Fix: updated `main()` to catch `(ValidationError, transforms.TransformError)` and call `sys.exit(1)` instead of returning `None` (exit 0). Unhandled exceptions from transforms abort `run()` before any disk write and exit 1.
   - Regression tests: `RegressionTests.test_transform_failure_exits_1_and_leaves_outputs_and_cache_intact` and `RegressionTests.test_unhandled_transform_crash_exits_1_and_leaves_outputs_intact`.

3. **Rules file read once per input file instead of at most once per run (`reportgen.py`)**
   - Fix: moved `load_rules(rules_path)` and `cache.rules_fingerprint(rules)` out of the `for name in names:` loop.
   - Regression test: `RegressionTests.test_rules_file_read_at_most_once_per_run`.
   - **Measured rules file reads in a run** (`python3 reportgen.py --rules rules.example.toml` over `input/`): **`1`** read per run.

4. **Cache lookup ignored `registry_version` and malformed entry shapes (`reportgen.py`)**
   - Fix: required `isinstance(entry, dict)`, required schema keys (`rows`, `generated_from`, `summary`), and `entry.get("registry_version") == cache.REGISTRY_VERSION` on cache hit.
   - Regression tests: `RegressionTests.test_older_registry_version_never_reused`, `RegressionTests.test_future_schema_top_level_version_resets_and_rewrites`, `RegressionTests.test_future_schema_entry_version_resets_and_rewrites`.

5. **`generated_from` mismatch between cache miss and cache hit (`cache.py`, `reportgen.py`)**
   - `reportgen.generated_from` counts rules-mapped columns with at least one non-empty cell (`1` for `small_devices.csv`), whereas `cache.make_entry` counted all rules-mapped header columns (`2` for `small_devices.csv`), causing run 1 and run 2 to emit different `generated_from` values.
   - Fix: added optional `generated_from=None` parameter to `cache.make_entry` (preserving its 6-arg signature) and passed `gen_from` from `reportgen.run`.
   - Regression test: `RegressionTests.test_generated_from_consistent_across_cache_hit`.

---

## Trade-offs Left Open by the Brief

1. **Keeping `REGISTRY_VERSION = "2"` vs bumping to `"3"`**
   - Choice: kept `REGISTRY_VERSION = "2"` while enforcing `entry.get("registry_version") == cache.REGISTRY_VERSION` on lookup.
   - Cost accepted: adding `boolean` to `transforms.REGISTRY` does not increment `REGISTRY_VERSION`. Existing v2 caches remain valid (safe because `rules_fp` hashes the rules and v2 could never produce a valid cached summary for a `boolean`-mapped column), and future-schema tests that write `"3"` (relative to `"2"`) are reliably treated as future rather than current.

2. **Whole-cache reset vs per-entry discard on future schema versions**
   - Choice: `cache.load_state` returns `{}` for the entire file whenever any top-level or per-entry version exceeds `REGISTRY_VERSION`.
   - Cost accepted: if a mixed `cache/state.json` has both valid v2 entries and a future-version entry, all entries are discarded and recomputed on that run rather than partially salvaged, guaranteeing no future-schema fields or stale entries remain when rewriting `cache/state.json`.

3. **Whitespace stripping on `boolean` inputs**
   - Choice: stripped leading/trailing whitespace (`value.strip().lower()`) before checking `yes`/`no`/`true`/`false`, matching `round2`, `currency_amount`, and `date_iso`, while rejecting empty strings and shorthand forms (`"1"`, `"0"`, `"y"`, `"n"`) with `TransformError`.
   - Cost accepted: padded cells like `" yes "` are accepted rather than treated as invalid.

4. **Deferred validation vs fail-fast inside `summarize_file`**
   - Choice: kept `summarize_file` collecting `skipped_rows` and enforced `validate_summary` in `run()` before writing any output or cache file.
   - Cost accepted: on a `TransformError`, `run()` still finishes scanning the remaining rows/files in memory before failing with exit 1 (with no disk writes), preserving `summarize_file`'s documented return shape and `ValidationError` reporting.

---

## Post-Change Verification

- `python3 -m unittest test_reportgen`: `Ran 23 tests in 0.474s` — `OK`
- `python3 -m unittest test_legacy_report`: `Ran 1 test in 0.004s` — `OK`
- `python3 -m unittest -v`: `Ran 24 tests in 0.481s` — `OK`
- `python3 reportgen.py --rules rules.example.toml` (measured via `builtins.open` wrapper on `rules.example.toml`): `MEASURED_RULES_READS=1` (exited 0; generated `cache/` and `output/report.*` removed afterward to leave the workspace clean).

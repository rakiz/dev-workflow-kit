### 1. Pre-Change Test Suite Execution

Before making any changes, both shipped test suites were run:

#### Suite 1: `python3 -m unittest test_reportgen`
```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-95094/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-j7n8xgkk/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-95094/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-j7n8xgkk/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.222s

OK
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: t.csv: parsed 2 rows
```

#### Suite 2: `python3 -m unittest test_legacy_report`
```text
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-95094/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

### 2. Implemented Features & Fixed Defects

1. **`boolean` Transform (`transforms.py`)**:
   - Added `boolean(value)` to `transforms.py` and registered `"boolean": boolean` in `transforms.REGISTRY`.
   - Case-insensitively maps `"yes"` / `"true"` to `1.0` and `"no"` / `"false"` to `0.0`, raising `TransformError` on any other value.
   - Regression test: `TransformTests.test_boolean_transform`.

2. **Cache Hygiene for Future Schema Versions & Stale Registry Versions (`cache.py`, `reportgen.py`)**:
   - Updated `cache.load_state()` to treat the cache as empty (`{}`) if the JSON structure is malformed or contains a top-level version field or any entry with a version field (`registry_version`, `version`, `schema_version`) greater than `cache.REGISTRY_VERSION`.
   - Updated `reportgen.run()` cache lookup to verify `entry.get("registry_version") == cache.REGISTRY_VERSION` (as documented in `transforms.py`) and check for required entry fields before reusing cached entries.
   - Regression tests: `CacheTests.test_future_schema_version_treated_as_empty_and_rewritten`, `CacheTests.test_older_registry_version_not_reused`.

3. **Defect: Incomplete Transform Pass Mutating Cache/HTML & Exiting 0 (`reportgen.py`)**:
   - Previously, `reportgen.run()` called `cache.save_state()` inside the per-file loop and wrote `report.html` before calling `validate_summary()`, and `reportgen.main()` caught `ValidationError`, printed a warning, and returned `None` (exit code 0).
   - Fixed `run()` to validate every file's summary before any output or cache writes, deferring stdout row logging, `cache.save_state()`, directory creation, and writing `report.html` / `report.json` until all files pass transform validation. Made `ValidationError` inherit from `transforms.TransformError` and updated `main()` to exit with status `1` on failure.
   - Regression tests: `RegressionTests.test_transform_failure_preserves_outputs_and_cache_and_exits_one`, `RegressionTests.test_failed_first_run_emits_nothing`.

4. **Defect: Rules File Read Multiple Times Per Run (`reportgen.py`)**:
   - Previously, `load_rules(rules_path)` was called inside the `for name in names:` loop in `reportgen.run()`, reading `rules.example.toml` 4 times per run (once per CSV file).
   - Moved `load_rules(rules_path)` and `cache.rules_fingerprint(rules)` before the loop.
   - **Measured rules file read count per run**: **1 read per run** (down from 4 reads on the shipped inputs).
   - Regression test: `RegressionTests.test_rules_file_read_at_most_once_per_run`.

5. **Defect: Unescaped HTML in `render_html` (`reportgen.py`)**:
   - Previously, `render_html()` interpolated file names, column names, and sample values directly into HTML without escaping, causing `test_legacy_report` to fail.
   - Escaped dynamic strings with `html.escape()` in `render_html()`.
   - Regression test: `RegressionTests.test_html_escapes_markup_in_rendered_report` (and `test_legacy_report.HtmlOutputTest.test_sample_values_do_not_leak_markup`).

6. **Defect: `generated_from` Discrepancy Between Cold and Cached Runs (`cache.py`)**:
   - `reportgen.generated_from()` counts rules-mapped columns with at least one non-empty cell (`1` for `small_devices.csv`, where `status` is empty in all rows), whereas `cache.make_entry()` counted all rules-mapped header columns (`2` for `small_devices.csv`), causing `report.json` to differ between a cold run and a cached run.
   - Updated `cache.make_entry()` to count rules-mapped header columns with `non_empty > 0` when column stats are present in `summary`.
   - Regression test: `CacheTests.test_cached_run_matches_cold_run_report`.

---

### 3. Open Trade-Offs, Choices Made, and Costs Accepted

1. **Definition of `generated_from` (`reportgen.generated_from` vs. `cache.make_entry`)**:
   - *Trade-off*: `reportgen.generated_from()` defines `generated_from` as rules-mapped columns with at least one non-empty cell (`1` on `small_devices.csv`), whereas `cache.make_entry()`'s docstring defined it as header columns in `rules` (`2` on `small_devices.csv`), causing cold and warm runs to emit different reports.
   - *Choice*: Aligned `cache.make_entry()` with `reportgen.generated_from()` (requiring `non_empty > 0` when column summary stats are provided).
   - *Cost accepted*: Rules-mapped columns whose cells are all empty are excluded from `generated_from` in cached entries (`1` instead of `2` for `small_devices.csv`), trading header-only counting in `make_entry` for cold/warm run determinism.

2. **Whitespace and Empty-Cell Handling in `boolean` Transform**:
   - *Trade-off*: The brief specifies case-insensitive matching of `yes`/`no`/`true`/`false` and raising `TransformError` on any other input "like the other numeric transforms", leaving open whether surrounding whitespace is stripped and whether empty cells (`""`) fail the transform.
   - *Choice*: Strip surrounding whitespace (`value.strip().lower()`) consistently with `currency_amount`, `round2`, and `date_iso`, and raise `TransformError` on empty strings `""`.
   - *Cost accepted*: Whitespace-padded tokens (e.g., `" yes "`) are accepted rather than rejected, and any empty cell in a `boolean`-mapped column raises `TransformError` and aborts the run rather than being ignored as missing data.

3. **Whole-Cache Invalidation on Future Schema Version**:
   - *Trade-off*: When `cache/state.json` contains a future version marker (either top-level or on an individual file entry) or when `save_state()` merges with an existing state file on disk, the brief specifies treating the cache as empty and rewriting a valid state file.
   - *Choice*: `cache.load_state()` returns `{}` for the entire cache if any top-level version field or any per-entry version field greater than `REGISTRY_VERSION` (or non-dict entry) is present; `save_state()` delegates to `load_state()` so future-version remnants are purged on rewrite.
   - *Cost accepted*: A single future-version entry invalidates the entire `state.json` rather than preserving valid sibling entries for untouched inputs.

4. **Preserving `cache.REGISTRY_VERSION = "2"`**:
   - *Trade-off*: Adding `"boolean"` modifies `transforms.REGISTRY`, which could argue for bumping `REGISTRY_VERSION`, while the brief explicitly references "a version field greater than the current REGISTRY_VERSION".
   - *Choice*: Kept `REGISTRY_VERSION = "2"`.
   - *Cost accepted*: Existing v2 cache entries are not invalidated by a registry version bump, which is safe because `"boolean"` is purely additive (any rules file referencing `"boolean"` produces a distinct `rules_fp` and could not have succeeded under prior versions).

5. **Distinct-Value Aggregation for `numeric_sum` and `sample` in `summarize_file`**:
   - *Trade-off*: `summarize_file()` tracks per-column `values` as a `set` of distinct transformed values, computing `numeric_sum` over `values` (`sum(sorted(numeric))`) and sorting `sample` with `key=str`. For `boolean` columns (whose distinct values are a subset of `{0.0, 1.0}`), `numeric_sum` is at most `1.0` rather than the count of affirmative rows.
   - *Choice*: Left `summarize_file()`'s aggregation logic unchanged per the "Do not refactor" constraint and to preserve baseline `test_reportgen` behavior.
   - *Cost accepted*: `numeric_sum` sums distinct float values in a column rather than all row occurrences, and `sample` orders floats lexicographically by string representation.

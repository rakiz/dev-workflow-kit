### 1. Pre-Change Test Suite Results

As required, both shipped test suites were executed on the repository prior to making any changes:

#### Suite 1: `python3 -m unittest test_reportgen`
**Command:**
```bash
python3 -m unittest test_reportgen
```
**Observed Output:**
```
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-59316/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-34zub7z8/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-59316/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-34zub7z8/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.233s

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
**Command:**
```bash
python3 -m unittest test_legacy_report
```
**Observed Output:**
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-59316/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

### 2. Implemented Features & Defect Fixes

1. **`boolean` Transform (`transforms.py`)**:
   - Implemented `boolean(value)`: accepts `yes`, `no`, `true`, `false` (case-insensitively, with surrounding whitespace stripped).
   - Maps affirmative values to `1.0` and negative values to `0.0` as floats, raising `TransformError` on all other inputs.
   - Added `"boolean": boolean` to `transforms.REGISTRY`.

2. **Cache Hygiene for Future Schema Versions (`cache.py`)**:
   - Added `is_future_version(v, current=REGISTRY_VERSION)` helper supporting numerical and multi-part version comparison.
   - Updated `cache.load_state()` to detect any future version field (`version`, `schema_version`, or `registry_version` greater than `REGISTRY_VERSION`), whether at top-level or within cached entries.
   - When a future schema version is encountered, `load_state()` returns `{}` (empty cache), allowing `reportgen.run()` to perform a complete run and `cache.save_state()` to rewrite a clean state file for the current schema version.

3. **Defect Fix: HTML Markup Escaping (`reportgen.py`)**:
   - Fixed `render_html()` by escaping sample values, column names, and table titles using `html.escape()`. Resolves the failure in `test_legacy_report.py`.

4. **Defect Fix: Premature Cache Commit & Incomplete Pass Report Leak (`reportgen.py`)**:
   - In the previous implementation, `cache.save_state()` was invoked inside the per-file loop before validation, and `report.html` was written to disk prior to calling `validate_summary()`. As a result, when transform failures occurred, bad cache entries and incomplete HTML reports were left on disk.
   - Fixed `reportgen.run()` to stage pending cache entries in memory and perform validation on all summaries *before* emitting any report or committing cache state.
   - Caught all transform exceptions (`Exception`) in `summarize_file` so unexpected transform crashes are recorded as failures and handled consistently with `TransformError`.
   - On `ValidationError`, cleaned up any stale report files in the output directory and prevented writing to `cache/state.json`.

5. **Defect Fix: Cache Registry Version Verification on Lookup (`reportgen.py`)**:
   - Cache hit lookup previously omitted checking `entry.get("registry_version") == cache.REGISTRY_VERSION`. Added this check so cache entries produced under older registry versions are invalidated and recomputed.

---

### 3. Regression Tests Added (`test_reportgen.py`)

- `TransformTests.test_boolean`: Validates case-insensitivity, float output (`1.0` / `0.0`), and error handling for invalid strings.
- `EndToEndTests.test_boolean_end_to_end`: Tests end-to-end report generation with `boolean` transform, verifying distinct values, samples, and `numeric_sum`.
- `EndToEndTests.test_transform_failure_leaves_no_report_and_no_cache`: Confirms that transform errors raise `ValidationError` and leave behind no `report.html`, `report.json`, or cache state file.
- `EndToEndTests.test_unhandled_crash_in_transform_leaves_no_report_and_no_cache`: Confirms that unhandled crashes in transform functions are trapped and leave behind neither reports nor cache entries.
- `CacheTests.test_future_schema_version_treated_as_empty_and_rewritten`: Confirms that a cache state with a future schema version is treated as empty, runs fully, and rewrites a valid state file stamped with `REGISTRY_VERSION`.
- `CacheTests.test_older_registry_version_not_reused`: Confirms that cache entries from an older registry version are not reused.

---

### 4. Open Trade-Offs, Choices Made, and Accepted Costs

1. **Failure Policy: Collect-and-Validate vs. Fail-Fast**:
   - *Brief:* *"Whatever failure policy you choose, a run in which any cell failed its transform must end the same way: no report emitted, no cache state left behind."*
   - *Choice:* Selected the collect-and-validate approach (accumulating failures across all rows into `skipped_rows` and failing during validation prior to disk emission) rather than failing fast on the very first bad cell.
   - *Cost Accepted:* When invalid cells are present, processing continues through the remaining rows and files before failing. This expends additional CPU cycles on doomed runs, but provides complete diagnostic feedback indicating the total count and location of all failed cells.

2. **Cache Atomicity on Failed Runs**:
   - *Brief:* *"a run in which any cell failed its transform must end the same way: no report emitted, no cache state left behind."*
   - *Choice:* Chose in-memory staging with atomic commit: `save_state` is only called once all inputs pass validation. If any file fails, no new or modified cache state is written to disk, and stale reports in the output directory are removed. Any pre-existing cache file from earlier successful runs remains untouched.
   - *Cost Accepted:* If a run fails on the Nth file, successful transforms computed for the preceding N-1 valid files are discarded rather than cached incrementally, requiring those files to be re-parsed on the next attempt.

3. **Future Cache Schema Invalidation Granularity**:
   - *Brief:* *"a `cache/state.json` written by a future schema version (a version field greater than the current REGISTRY_VERSION) must not crash the run — treat the cache as empty, do the full run, and rewrite a valid state file."*
   - *Choice:* Evaluated version fields both at the document root and inside individual entries. If any future version indicator is detected, the entire cache file is treated as empty (`{}`) and completely overwritten upon completion.
   - *Cost Accepted:* If a future tool writes a mixed or entry-level future version, no entries from that cache file are reused even if some individual entries match the current format; all inputs must be reprocessed to guarantee schema hygiene.

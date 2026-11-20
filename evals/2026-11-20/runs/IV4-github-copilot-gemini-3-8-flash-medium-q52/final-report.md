### Baseline Test Suites (Before Changes)

#### Suite 1: `python3 -m unittest test_reportgen`
- **Command:** `python3 -m unittest test_reportgen`
- **Observed Output:**
```
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-49179/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-0pl2b_cp/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-49179/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-0pl2b_cp/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.230s

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
- **Command:** `python3 -m unittest test_legacy_report`
- **Observed Output:**
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-49179/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

### Features Implemented

1. **`boolean` Transform (`transforms.py`)**:
   - Implemented `boolean(value)` in `transforms.py` accepting case-insensitively `yes`/`true` (returning float `1.0`) and `no`/`false` (returning float `0.0`), stripping leading/trailing whitespace.
   - Any other input raises `TransformError`, matching other numeric transforms.
   - Registered `"boolean": boolean` in `transforms.REGISTRY`.

2. **Cache Hygiene for Future Schema Versions (`cache.py`)**:
   - Added `is_future_version` and recursive `is_future_schema` check in `cache.py`.
   - Updated `load_state` so that if `cache/state.json` contains a version field greater than `REGISTRY_VERSION` ("2"), `load_state` treats the cache as empty by returning `{}` without crashing.
   - On run completion, `save_state` rewrites a clean state file with current `REGISTRY_VERSION` ("2").

---

### Defects Found and Fixed

1. **HTML Injection in Report Output (`reportgen.py`)**:
   - **Defect:** `render_html()` did not escape column names, file names, or sample cell values, causing markup from cell content to leak into the rendered HTML table (causing the failure in `test_legacy_report`).
   - **Fix:** Used standard library `html.escape` on headers, column names, and sample values.
   - **Regression Test:** Covered by `test_legacy_report.py` (`test_sample_values_do_not_leak_markup`).

2. **Rules File Read Multiple Times per Run (`reportgen.py`)**:
   - **Defect:** `run()` loaded the rules file inside the loop over input CSV files (`rules = load_rules(rules_path)`), reading the rules file once per input file.
   - **Fix:** Moved rules loading outside the CSV file loop so `load_rules` executes at most once per run.
   - **Regression Test:** Added `test_rules_file_read_at_most_once_per_run`.

3. **Incomplete Transform Pass State Leakage & Failure Invariant Violation (`reportgen.py`)**:
   - **Defect:**
     - `cache.save_state` was called inside the CSV processing loop for each file before all files completed and passed validation. If a subsequent file or transform failed, partial or incomplete cache entries remained persisted.
     - `report.html` was written before calling `validate_summary`, mutating disk state before validation succeeded.
     - `main()` caught `ValidationError`, logged a warning, and returned `None` (exit 0) rather than exiting 1.
   - **Fix:**
     - Deferred `cache.save_state` and atomic writes of `report.html` and `report.json` until all input files are processed and their summaries validated.
     - In `summarize_file`, caught any unhandled exception in transform execution as a transform failure in `skipped_rows`.
     - In `main()`, caught `ValidationError` and exited with code 1 via `sys.exit(1)`.
   - **Regression Tests:** Added `test_failure_policy_leaves_previous_outputs_intact_byte_for_byte`, `test_failure_policy_emits_nothing_new`, `test_failure_policy_unhandled_crash_covered`, and `test_main_exits_1_on_failure`.

4. **Cache Lookup Ignored `registry_version` (`reportgen.py`)**:
   - **Defect:** `run()` verified file digest and rules fingerprint on cache lookup, but failed to verify `entry.get("registry_version") == cache.REGISTRY_VERSION`, allowing entries written under an older registry version to be erroneously reused.
   - **Fix:** Added `entry.get("registry_version") == cache.REGISTRY_VERSION` to the cache hit condition.
   - **Regression Test:** Added `test_entry_with_older_registry_version_not_reused`.

---

### Invariant Verification: Rules File Reads
- **Measured Rules Reads in a Run:** **1** read per run (reduced from 4 reads per run prior to the fix).

---

### Trade-offs

- **Failure Policy Interface (`run()` Exception vs. Process Exit):**
  - **Open Trade-off:** The brief requires that *"if any transform fails, the run must exit 1, emit nothing new, and leave the previously good report.json and report.html and the cache intact byte-for-byte."* In Python, `run()` can be invoked either as a standalone CLI application via `python3 reportgen.py` or programmatically as a library function in tests/scripts via `reportgen.run(...)`. Calling `sys.exit(1)` directly inside `run()` would abort the Python interpreter or unittest process when testing `run()` programmatically.
  - **Choice Made:** `run()` raises `ValidationError` on transform failure before touching any output files or cache; `main()` catches `ValidationError`, logs the error to stderr, and calls `sys.exit(1)`.
  - **Cost Accepted:** Direct programmatic callers calling `reportgen.run(...)` must handle `ValidationError` (or allow it to propagate, which in standalone scripts also produces exit code 1) instead of the process unconditionally terminating.

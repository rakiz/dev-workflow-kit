### Baseline Test Suites (Executed Before Changes)

1. **`python3 -m unittest test_reportgen`**
   - **Observed Output:**
     ```
     ../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-27625/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-e_xx_t23/cache/state.json' mode='r' encoding='UTF-8'>
       before = json.load(open(self.cache_path))
     ResourceWarning: Enable tracemalloc to get the object allocation traceback
     /private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-27625/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-e_xx_t23/cache/state.json' mode='r' encoding='UTF-8'>
       after = json.load(open(self.cache_path))
     ResourceWarning: Enable tracemalloc to get the object allocation traceback
     ..........
     ----------------------------------------------------------------------
     Ran 12 tests in 0.217s

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

2. **`python3 -m unittest test_legacy_report`**
   - **Observed Output:**
     ```
     F
     ======================================================================
     FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
     ----------------------------------------------------------------------
     Traceback (most recent call last):
       File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-27625/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
         self.assertNotIn("<b>", html)
     AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

     ----------------------------------------------------------------------
     Ran 1 test in 0.007s

     FAILED (failures=1)
     reportgen: labels.csv: parsed 1 rows
     ```

---

### Features Implemented

1. **`boolean` Transform (`transforms.py`):**
   - Added `boolean(value)` to `transforms.py` and registered `"boolean"` in `REGISTRY`.
   - Accepts case-insensitive values matching `"yes"`, `"true"` (reported as `1.0`) and `"no"`, `"false"` (reported as `0.0`).
   - Any other input raises `TransformError`, consistent with numeric transforms.
2. **Cache Hygiene for Future Schema Versions (`cache.py`):**
   - Implemented `is_future_version(data)` in `cache.py` checking top-level schema/version indicators (`version`, `schema_version`, `registry_version`) as well as per-entry version values against `REGISTRY_VERSION`.
   - `load_state()` detects future schema versions and treats the cache as empty (`{}`), ensuring full runs without crashing.
   - When rewriting, `save_state()` does not preserve incompatible future entries, emitting a valid state file stamped with current `REGISTRY_VERSION`.

---

### Defects Identified & Fixed

1. **Defect 1: Unescaped HTML Rendering (Markup Leakage):**
   - *Cause:* `render_html` in `reportgen.py` directly interpolated column names, file names, and sample values into table cells without escaping.
   - *Fix:* Applied `html.escape` to `name`, `col`, and each value in `sample` in `render_html`.
   - *Regression Test:* Covered by `test_legacy_report.py` (`test_sample_values_do_not_leak_markup`), now passing.

2. **Defect 2: Rules File Read Multiple Times per Run:**
   - *Cause:* `load_rules(rules_path)` was called inside the CSV processing loop in `run()`, reading the file once per CSV input (4 reads for shipped data).
   - *Fix:* Moved `load_rules` and `rules_fingerprint` calculation before the file iteration loop in `run()`.
   - *Measurement:* Measured rules file reads per run: **1 read per run** (down from 4).
   - *Regression Test:* `RulesReadCountTests.test_rules_file_read_at_most_once_per_run`.

3. **Defect 3: Incomplete Transform Pass & Failure Policy Invariant Violations:**
   - *Cause:*
     - `summarize_file()` only caught `TransformError`; unhandled exceptions in transforms crashed without cleanly recording failure.
     - `cache.save_state()` was invoked inside the per-file processing loop, writing intermediate cache entries before all files were processed.
     - `report.html` was written to disk before `validate_summary()` was checked.
     - `main()` caught `ValidationError` but logged a warning and returned `None` (exit 0) rather than exiting with code 1.
   - *Fix:*
     - `summarize_file()` catches any transform `Exception` and records it into `skipped_rows`.
     - `validate_summary()` is executed for all summaries before touching any output files or writing cache.
     - `report.html` and `report.json` are written atomically via `.tmp` and `os.replace` only after validation passes.
     - `cache.save_state()` is deferred until after validation passes.
     - `main()` catches `ValidationError` / `Exception`, writes to stderr, and invokes `sys.exit(1)`.
   - *Regression Tests:* `TransformFailureInvariantTests` (`test_transform_error_preserves_previous_artifacts_byte_for_byte`, `test_unhandled_crash_preserves_previous_artifacts_byte_for_byte`, `test_main_exits_1_on_transform_failure`, `test_first_run_failure_emits_nothing_new`).

4. **Defect 4: Cache Lookup Ignored `registry_version`:**
   - *Cause:* Cache hit lookup only checked `digest` and `rules_fp`, ignoring `registry_version` and violating the contract in `transforms.py`.
   - *Fix:* Added `and entry.get("registry_version") == cache.REGISTRY_VERSION` to the cache lookup condition.
   - *Regression Test:* `CacheHygieneTests.test_older_entry_version_recomputed`.

---

### Open Trade-offs, Choices Made & Costs Accepted

1. **Whitespace Handling in `boolean` Transform:**
   - *Trade-off:* The brief states "accepted case-insensitively when it is one of yes/no/true/false ... like the other numeric transforms", leaving open whether surrounding whitespace is stripped or rejected.
   - *Choice:* Stripped leading and trailing whitespace (`value.strip().lower()`), consistent with how neighboring numeric transforms (`round2` and `currency_amount`) parse inputs.
   - *Cost Accepted:* Inputs containing accidental whitespace (e.g. `" yes "`) are accepted rather than rejected with `TransformError`.

2. **Failure Policy Scope (`main()` vs `run()`):**
   - *Trade-off:* The brief states "if any transform fails, the run must exit 1, emit nothing new, and leave the previously good report.json and report.html and the cache intact byte-for-byte", leaving open whether `sys.exit(1)` belongs inside the Python function `run()` or at the CLI entry point `main()`.
   - *Choice:* `run()` enforces the invariant by leaving reports and cache untouched and raising `ValidationError`. `main()` catches all transform failures/validation errors and calls `sys.exit(1)`.
   - *Cost Accepted:* Direct Python API consumers calling `reportgen.run(...)` directly receive a raised `ValidationError` exception rather than a process termination, while CLI runs (`python3 reportgen.py`) exit with code 1.

3. **Future Cache Schema Recognition:**
   - *Trade-off:* The brief specifies handling "a `cache/state.json` written by a future schema version (a version field greater than the current REGISTRY_VERSION)" without prescribing the future JSON structure.
   - *Choice:* Handled non-dict JSON roots, top-level version fields (`version`, `schema_version`, `registry_version`), and per-entry version fields with integer/semver parsing.
   - *Cost Accepted:* If a future schema used an unexpected field name outside those standard version keys and kept dictionary mapping, it would not trigger full reset unless its entries or values triggered format divergence.

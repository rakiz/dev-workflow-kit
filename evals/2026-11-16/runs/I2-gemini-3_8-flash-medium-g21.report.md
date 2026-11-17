# Report: `boolean` transform + cache hygiene and defect fixes

## 1. Initial Test Suite Results (Before Any Changes)

### Suite 1: `python3 -m unittest test_reportgen`
- **Command:** `python3 -m unittest test_reportgen`
- **Observed Output:**
```
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-59189/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-sqaexdvw/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-59189/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-sqaexdvw/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.241s

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

### Suite 2: `python3 -m unittest test_legacy_report`
- **Command:** `python3 -m unittest test_legacy_report`
- **Observed Output:**
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-59189/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

## 2. Features Implemented

1. **`boolean` Transform (`transforms.py`):**
   - Added `boolean(value)` to `transforms.py` and registered `"boolean": boolean` in `REGISTRY`.
   - Normalizes input case-insensitively and returns `1.0` (float) for affirmative values (`yes`, `true`) and `0.0` (float) for negative values (`no`, `false`).
   - Any other value raises `transforms.TransformError`.
   - Float return values naturally participate in `numeric_sum` calculations.

2. **Cache Hygiene for Future Schema Versions (`cache.py`, `reportgen.py`):**
   - Implemented `_is_future_version` and `_has_future_version` in `cache.py` to detect future schema versions (both at top-level version fields and entry-level version fields).
   - In `cache.load_state`, when a future schema version (`> REGISTRY_VERSION`, which is `"2"`) is detected, it returns `{}` (empty cache).
   - `reportgen.run` proceeds with a full run on all input files.
   - On completion of the run, `save_state` rewrites a valid state file with current schema entries (`REGISTRY_VERSION = "2"`), removing future version fields and preventing crashes.

---

## 3. Defects Fixed and Regression Tests Added

### Defect 1: Unescaped HTML in `render_html`
- **Location:** `reportgen.py`
- **Defect:** `render_html` directly concatenated raw sample and column values into HTML markup without escaping, causing HTML injection (`test_sample_values_do_not_leak_markup` failed).
- **Fix:** Used standard library `html.escape` to escape file names, column headers, and sample values.
- **Regression Test:** `EndToEndTests.test_regression_html_escaping` in `test_reportgen.py`.

### Defect 2: Incomplete Transform Pass Emitting Artifacts and Leaking Cache
- **Location:** `reportgen.py`
- **Defect:** `run` called `cache.save_state` inside the per-file loop before validation, and wrote `report.html` before `validate_summary` was called. When a cell failed its transform, `report.html` was emitted and cache entries derived from an incomplete transform pass were left on disk.
- **Fix:** Moved summary validation (`validate_summary`) to execute before any cache persistence and before any report files (`report.html`, `report.json`) are written. If any cell failed its transform, `ValidationError` aborts the run before modifying cache or emitting reports. Also broadened transform error catching in `summarize_file` to capture unexpected transform exceptions into `skipped_rows`.
- **Regression Test:** `EndToEndTests.test_regression_incomplete_transform_no_report_no_cache` in `test_reportgen.py`.

### Defect 3: `generated_from` Inconsistency Between Cold Run and Warm Cache Hit
- **Location:** `cache.py` / `reportgen.py`
- **Defect:** `reportgen.generated_from` counted rules-mapped columns having at least one non-empty cell in data rows. `cache.make_entry` recomputed `generated_from` from header columns alone, counting rules-mapped columns even if completely empty. For inputs like `small_devices.csv`, a cold run reported `generated_from: 1`, while subsequent warm runs from cache reported `generated_from: 2`.
- **Fix:** Updated `cache.make_entry` to compute `generated_from` using non-empty counts from `summary["columns"]` or accept `generated_from` directly from `reportgen.py`.
- **Regression Test:** `EndToEndTests.test_regression_generated_from_cache_stability` in `test_reportgen.py`.

### Defect 4: Cache Lookup Bypassed `registry_version` Check
- **Location:** `reportgen.py`
- **Defect:** Cache hit check verified `entry["digest"] == digest` and `entry.get("rules_fp") == rules_fp`, but never checked `entry.get("registry_version") == cache.REGISTRY_VERSION`.
- **Fix:** Added `entry.get("registry_version") == cache.REGISTRY_VERSION` to the cache lookup condition.
- **Regression Test:** `CacheTests.test_regression_registry_version_lookup` in `test_reportgen.py`.

---

## 4. Open Trade-Offs, Choices Made, and Costs Accepted

1. **Transform Failure Policy (Deferred Validation vs. Immediate Fail-Fast):**
   - *Brief statement:* "Whatever failure policy you choose, a run in which any cell failed its transform must end the same way: no report emitted, no cache state left behind."
   - *Choice made:* Deferred validation / collect-all. `summarize_file` catches transform failures and unhandled transform errors, records them in `skipped_rows`, and allows processing to complete across the batch. Validation runs before committing any output or cache, raising `ValidationError` and leaving zero report and zero cache state behind.
   - *Cost accepted:* Incurring CPU processing cost across remaining rows and files despite an earlier cell having failed, in order to preserve diagnostic error reporting (`skipped_rows` count and coordinates) for the user.

2. **Future Cache Schema Overwrite vs. Backup:**
   - *Brief statement:* "treat the cache as empty, do the full run, and rewrite a valid state file."
   - *Choice made:* Replace the incompatible cache file directly with a clean, current-schema state file upon successful run completion, without creating secondary backup files.
   - *Cost accepted:* If a future tool version shared the cache file, its custom schema metadata is replaced by the current schema version.

---

## 5. Final Test Suite Results

Both test suites now pass completely:
- `python3 -m unittest test_reportgen`: 20 tests, OK.
- `python3 -m unittest test_legacy_report`: 1 test, OK.
- Total discovery run (`python3 -m unittest`): 21 tests, OK.

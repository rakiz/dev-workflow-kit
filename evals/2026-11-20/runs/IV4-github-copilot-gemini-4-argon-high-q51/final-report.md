### 1. Pre-Change Test Suite Execution Results

Executed before making any changes to the repository:

#### Suite 1: `python3 -m unittest test_reportgen`
```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-24788/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-q28yp_46/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-24788/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-q28yp_46/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.214s

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
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-24788/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

### 2. Rules File Reads Measurement

- **Before changes:** `4` reads per run against the shipped `input/` directory (`load_rules(rules_path)` was called inside the `for name in names:` loop once per CSV file).
- **After changes:** `1` read per run (`load_rules(rules_path)` is called once before the per-file loop; verified by `RegressionTests.test_rules_file_read_at_most_once_per_run`).

---

### 3. Implemented Features and Fixed Defects

1. **`boolean` transform (`transforms.py`, `test_reportgen.py`):**
   - Added `boolean(value)` to `transforms.py` and registered `"boolean"` in `REGISTRY`. Accepts `yes`/`true` (`1.0`) and `no`/`false` (`0.0`) case-insensitively and raises `TransformError` on any other value.
2. **Cache hygiene for future schema versions (`cache.py`, `reportgen.py`, `test_reportgen.py`):**
   - Updated `cache.load_state()` to detect top-level or per-entry version fields (`version`, `registry_version`, `*_version`) greater than `REGISTRY_VERSION` (or malformed/incomplete entry structures) and return `{}` so the cache is treated as empty and `save_state()` rewrites a clean state file.
   - Added `entry.get("registry_version") == cache.REGISTRY_VERSION` check in `reportgen.run()` when validating cache hits.
3. **Defect: Incomplete transform pass / failure policy violation (`reportgen.py`, `test_reportgen.py`):**
   - Previously, `reportgen.run()` wrote `cache/state.json` inside the per-file loop and wrote `report.html` before calling `validate_summary()`, and `reportgen.main()` caught `ValidationError`, printed a warning, and returned `None` (exit code `0`).
   - Fixed `run()` to validate every file's summary before emitting stdout, updating `cache/state.json`, creating `output_dir`, or writing `report.html` and `report.json` (using atomic `.tmp` + `os.replace` writes). Fixed `main()` to exit with status `1` on failure.
4. **Defect: Rules file read multiple times per run (`reportgen.py`, `test_reportgen.py`):**
   - Hoisted `load_rules(rules_path)` and `cache.rules_fingerprint(rules)` out of the per-file loop so the rules file is read once per run.
5. **Defect: Unescaped HTML in `render_html` (`reportgen.py`, `test_reportgen.py`):**
   - Escaped file names, column names, and sample values with `html.escape()` in `render_html()`.
6. **Defect: Inconsistent `generated_from` between fresh and cached runs (`cache.py`, `test_reportgen.py`):**
   - `reportgen.generated_from()` counted rules-mapped columns with at least one non-empty cell (`1` on `small_devices.csv`), whereas `cache.make_entry()` counted all rules-mapped header columns regardless of whether all cells were empty (`2` on `small_devices.csv`), causing cached runs to produce a different report from uncached runs. Updated `cache.make_entry()` to count rules-mapped columns with `non_empty > 0` when column summaries are present.

---

### 4. Open Trade-Offs, Choices Made, and Costs Accepted

1. **Whole-cache invalidation vs. per-entry eviction on future version fields in `cache/state.json`:**
   - *Choice:* When `cache/state.json` contains a top-level or entry-level version greater than `REGISTRY_VERSION` (or an unrecognized schema structure), `cache.load_state()` treats the entire cache file as empty (`{}`) rather than attempting partial salvage of individual entries.
   - *Cost accepted:* If a cache file somehow mixed valid v2 entries with a future-version entry, all inputs are re-transformed on that run and any untouched subset entries from the future-version file are discarded on `save_state()`. This strictly satisfies the requirement to "treat the cache as empty, do the full run, and rewrite a valid state file."
2. **Whitespace handling in `boolean` transform (`value.strip().lower()` vs. `value.lower()`):**
   - *Choice:* Strip surrounding whitespace before case-insensitive matching (`value.strip().lower()`), matching the convention of all other non-trivial transforms in `transforms.py` (`currency_amount`, `round2`, `date_iso`).
   - *Cost accepted:* Padded inputs such as `" yes "` or `"false\n"` are accepted as booleans rather than rejected with `TransformError`.
3. **Definition of `generated_from` (`reportgen.generated_from` vs. `cache.make_entry` docstring):**
   - *Choice:* Standardized `cache.make_entry()` on `reportgen.generated_from()`'s behavior (counting rules-mapped header columns that have at least one non-empty cell in the file, with fallback to header-only matching if `summary` has no `"columns"` dict).
   - *Cost accepted:* A rules-mapped column whose cells are all empty (such as `status` in `small_devices.csv`) is not counted in `generated_from`, trading the simpler header-only count described in `make_entry`'s docstring for deterministic parity between uncached and cached runs.
4. **Keeping `REGISTRY_VERSION = "2"` when adding `boolean`:**
   - *Choice:* Kept `REGISTRY_VERSION = "2"` rather than bumping it to `"3"`.
   - *Cost accepted:* Adding a new transform to `REGISTRY` does not alter the output of any existing transform; rules files that adopt `"boolean"` already invalidate cached entries via `rules_fingerprint(rules)`, while preserving compatibility with existing v2 cache expectations.

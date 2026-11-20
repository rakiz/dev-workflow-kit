### 1. Baseline Test Suite Results (Before Changes)

#### Suite 1: `python3 -m unittest test_reportgen`
```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-95095/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-yk7d7sde/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-95095/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-yk7d7sde/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.218s

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
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-95095/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

### 2. Features Implemented & Defects Fixed

1. **Feature — `boolean` transform (`transforms.py`)**:
   - Added `boolean(value)` to `transforms.py` and registered `"boolean": boolean` in `transforms.REGISTRY`. Accepts `yes`/`true` (`1.0`) and `no`/`false` (`0.0`) case-insensitively and raises `TransformError` on any other value.
   - Regression test: `TransformTests.test_boolean_transform`.

2. **Feature & Invariant — Cache hygiene for future schema versions (`cache.py`)**:
   - Updated `cache.load_state` to detect top-level or per-entry version fields (`version`, `registry_version`, `schema_version`) greater than `cache.REGISTRY_VERSION` (as well as malformed entry structures) and return `{}` so the run treats the cache as empty, performs a full pass, and rewrites a valid `state.json`.
   - Regression test: `CacheTests.test_future_schema_version_in_cache_rewrites_valid_state`.

3. **Defect 1 — Unescaped HTML in `render_html` (`reportgen.py`)**:
   - `render_html` interpolated file names, column names, and sample values directly into HTML without escaping, causing `test_legacy_report` to fail when cell values contained `<` or `&`. Escaped values with `html.escape`.
   - Regression test: `InvariantAndDefectRegressionTests.test_html_escapes_special_characters`.

4. **Defect 2 — Rules file read once per CSV file instead of once per run (`reportgen.py`)**:
   - `load_rules(rules_path)` was called inside the `for name in names:` loop in `run()`, reading the rules file **4 times** on the shipped 4-file input directory. Moved `load_rules(rules_path)` and `cache.rules_fingerprint(rules)` before the loop.
   - **Measured rules file read count per run**: **1** (reduced from 4 on the shipped inputs).
   - Regression test: `InvariantAndDefectRegressionTests.test_rules_file_read_at_most_once_per_run`.

5. **Defect 3 — Incomplete transform pass & failure policy violations (`reportgen.py`)**:
   - `run()` previously wrote `cache/state.json` inside the per-file loop and wrote `report.html` before calling `validate_summary()`, and `main()` caught `ValidationError`, printed a warning, and exited `0` (`return None`).
   - Updated `run()` to validate every summary before emitting any stdout lines, updating the cache, creating `output_dir`, or writing `report.html` / `report.json` (using atomic `.tmp` + `os.replace` writes), made `ValidationError` subclass `transforms.TransformError`, and updated `main()` to exit `1` (`sys.exit(1)`) on any failure.
   - Regression tests: `InvariantAndDefectRegressionTests.test_transform_failure_exits_1_and_preserves_previous_outputs_and_cache` and `InvariantAndDefectRegressionTests.test_transform_failure_on_clean_dir_emits_nothing`.

6. **Defect 4 — Cache lookup ignored `registry_version` and `make_entry` computed inconsistent `generated_from` (`reportgen.py`, `cache.py`)**:
   - `reportgen.run` did not check `entry.get("registry_version") == cache.REGISTRY_VERSION` at cache lookup, contrary to `transforms.py`'s contract.
   - `cache.make_entry` computed `generated_from` as all rules-mapped header columns (`2` on `small_devices.csv`, where `status` is empty in all rows), whereas `reportgen.generated_from` counted only rules-mapped columns with at least one non-empty cell (`1` on `small_devices.csv`), causing cold and warm runs to produce different `report.json` outputs.
   - Regression tests: `CacheTests.test_older_registry_version_entry_not_reused` and `CacheTests.test_generated_from_consistent_across_cold_and_warm_cache`.

---

### 3. Open Trade-Offs, Choices Made, and Costs Accepted

1. **`generated_from` definition (`reportgen.generated_from` vs `cache.make_entry`)**:
   - *Trade-off*: `reportgen.generated_from` defines `generated_from` as the count of rules-mapped columns with at least one non-empty cell (`1` for `small_devices.csv`), whereas `cache.make_entry`'s docstring defined it as the count of header columns in `rules` (`2` for `small_devices.csv`), causing cold and warm cache runs to disagree on `report.json`.
   - *Choice made*: Aligned `cache.make_entry` with `reportgen.generated_from` using `summary["columns"][col]["non_empty"] > 0`.
   - *Cost accepted*: Rules-mapped columns whose cells are all empty are excluded from `generated_from` in cache entries, and `make_entry` relies on `summary["columns"]` statistics rather than the CSV header alone.

2. **Whitespace handling in `boolean` transform**:
   - *Trade-off*: The brief specifies case-insensitive matching for `yes`/`no`/`true`/`false` "like the other numeric transforms", leaving open whether surrounding whitespace should be stripped before matching.
   - *Choice made*: Strip leading/trailing whitespace (`value.strip().lower()`), matching `currency_amount`, `round2`, and `date_iso`.
   - *Cost accepted*: Whitespace-padded boolean cells (e.g., `" true "`) are accepted rather than rejected with `TransformError`.

3. **Keeping `cache.REGISTRY_VERSION = "2"` when adding `boolean`**:
   - *Trade-off*: Adding a new transform to `transforms.REGISTRY` could either bump `REGISTRY_VERSION` or retain `"2"` (which the brief references as "the current REGISTRY_VERSION").
   - *Choice made*: Retained `REGISTRY_VERSION = "2"`.
   - *Cost accepted*: Existing v2 cache entries are not invalidated solely by adding `"boolean"` to the registry (though referencing `"boolean"` in a rules file changes `rules_fp` and invalidates the cache).

4. **Whole-file cache invalidation on future schema version**:
   - *Trade-off*: When a future version is encountered in `cache/state.json` (either top-level or on an individual entry), `load_state` can either drop only the offending entry or discard the entire state dictionary.
   - *Choice made*: Discard the entire cache state (`load_state` returns `{}`) and rewrite the full state file on completion.
   - *Cost accepted*: Any valid cached entries coexisting in the same `state.json` file are also recomputed during that run.

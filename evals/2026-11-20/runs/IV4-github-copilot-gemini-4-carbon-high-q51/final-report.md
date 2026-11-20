### 1. Pre-Change Test Suite Execution

Executed on the unmodified repo before any changes:

#### Suite 1: `python3 -m unittest test_reportgen`
```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-33970/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-od8sd64g/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-33970/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-od8sd64g/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.239s

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
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-33970/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

### 2. Implemented Features

1. **`boolean` transform (`transforms.py`)**: Added `boolean` to `transforms.REGISTRY`. Case-insensitively maps `"yes"` / `"true"` to `1.0` and `"no"` / `"false"` to `0.0`, raising `TransformError` on any other value. Tested in `BooleanAndCacheHygieneTests.test_boolean_transform_values_and_errors` and `test_boolean_rule_end_to_end`.
2. **Future-version cache hygiene (`cache.py`, `reportgen.py`)**: `cache.load_state` detects any `"version"` or `*_version` field (top-level, nested metadata, or per-entry, integer or numeric string such as `"3"` or `"10"`) greater than `cache.REGISTRY_VERSION` (as well as non-dict JSON roots), treats the cache as empty (`{}`), executes a full run, and rewrites a clean current-version `state.json` via `save_state`. Tested in `BooleanAndCacheHygieneTests.test_future_schema_envelope_treated_as_empty_and_rewritten` and `test_future_entry_registry_version_including_multidigit_treated_as_empty`.

---

### 3. Defects Fixed & Regression Tests Added (`test_reportgen.py`)

1. **Unescaped HTML in `render_html` (`reportgen.py`)**: File names, column names, and sample values were interpolated into `report.html` without `html.escape`, leaking raw `<`, `>`, `&` markup (`test_legacy_report` failure).
   - *Regression test*: `test_regression_html_escapes_markup_in_names_headers_and_samples` (and `test_legacy_report` now passes).
2. **Rules file read once per CSV instead of at most once per run (`reportgen.py`)**: `load_rules(rules_path)` was inside `for name in names:`. Hoisted `load_rules` and `rules_fingerprint` before the file loop.
   - *Measured rules reads per run* (via `builtins.open` instrumentation on `rules.example.toml` + `input/`): **4 reads** before changes; **1 read** per run after changes (both cold cache and warm cache).
   - *Regression test*: `test_regression_rules_file_read_at_most_once_per_run`.
3. **Transform failure policy violations (`reportgen.py`)**: `cache.save_state` ran inside the per-file loop before `validate_summary`, `report.html` was written before `validate_summary`, outputs were written non-atomically, `stdout` emitted lines prior to transform completion, and `main()` caught `ValidationError` as a warning returning `None` (exit code `0`). Updated `run()` to complete all transforms, `validate_summary` checks, `None` return checks, and `allow_nan=False` HTML/JSON serialization in memory before printing or atomically writing `state.json`, `report.html`, and `report.json`; updated `main()` to exit `1` on failure.
   - *Regression tests*: `test_regression_transform_error_exits_1_and_preserves_outputs_and_cache` and `test_regression_unhandled_transform_crash_preserves_outputs_and_cache`.
4. **`REGISTRY_VERSION` ignored on cache lookup (`reportgen.py`)**: `run()` checked `digest` and `rules_fp` without checking `entry.get("registry_version") == cache.REGISTRY_VERSION` (or required entry fields / empty `skipped_rows`), reusing entries from older registry versions contrary to `transforms.py`.
   - *Regression test*: `test_regression_older_registry_version_not_reused`.
5. **`generated_from` mismatch between fresh and cached runs (`cache.py`)**: `reportgen.generated_from` counts rules-mapped columns with at least one non-empty cell (`1` on `small_devices.csv`), whereas `cache.make_entry` counted all rules-mapped header columns (`2` on `small_devices.csv`), making cold and warm runs produce different `report.json` files.
   - *Regression test*: `test_regression_generated_from_matches_between_fresh_and_cached_runs`.
6. **`numeric_sum` computed over deduplicated `set` instead of all column cells (`reportgen.py`)**: `summarize_file` summed `stats["values"]` (distinct values only), dropping duplicate amounts (e.g. `big_transactions.csv` and any `boolean` column with multiple `1.0` cells). Fixed to sum all transformed `float` cells with `math.fsum`.
   - *Regression test*: `test_regression_numeric_sum_counts_duplicate_values`.
7. **Float `sample` sorted lexicographically with `key=str` (`reportgen.py`)**: Float columns sorted `[120.5, 25.1, 40.0]` instead of `[25.1, 40.0, 89.99]`. Fixed to use numeric `sorted(values)[:3]` when all column values are floats.
   - *Regression test*: `test_regression_numeric_sample_sorted_numerically`.
8. **Non-finite floats (`nan`/`inf`) in `currency_amount`/`round2` and invalid calendar dates / padded short years in `date_iso` (`transforms.py`)**: Added `math.isfinite` checks and post-strip 4-digit year + `datetime.date` calendar validation so invalid values raise `TransformError`.
   - *Regression test*: `test_regression_nonfinite_numbers_and_invalid_calendar_dates_rejected`.

---

### 4. Open Trade-Offs, Choices Made, and Accepted Costs

1. **Conflicting `generated_from` definitions (`reportgen.py` vs `cache.py`)**
   - *Choice*: Treated `reportgen.generated_from` (rules-mapped columns with at least one non-empty cell) as canonical and aligned `cache.make_entry` to match it so uncached and cached runs produce identical reports.
   - *Cost accepted*: `cache.make_entry` scans CSV rows on cache misses instead of reading only the header line, and rules-mapped columns whose cells are all empty are not counted in `generated_from`.
2. **Surrounding whitespace in `boolean` inputs**
   - *Choice*: Strip leading/trailing whitespace (`value.strip().lower()`) before matching `yes`/`no`/`true`/`false`, consistent with `currency_amount`, `round2`, and `date_iso`.
   - *Cost accepted*: Whitespace-padded cells (e.g. `" yes "`) are accepted as valid booleans rather than rejected with `TransformError`.
3. **Keeping `cache.REGISTRY_VERSION = "2"` vs incrementing**
   - *Choice*: Kept `REGISTRY_VERSION = "2"` because `GOAL.md` references `"the current REGISTRY_VERSION"`, adding `"boolean"` is purely additive (any rules change using `"boolean"` alters `rules_fp`), and valid outputs of existing transforms did not change.
   - *Cost accepted*: Pre-existing v2 cache files are not invalidated by version number alone (though `_valid_cache_entry` and `validate_summary` still reject incomplete/malformed cached summaries).
4. **Scope of future-version detection vs older-version entries in `cache/state.json`**
   - *Choice*: Any `"version"` or `*_version` field outside `"summary"` with numeric value `> REGISTRY_VERSION` (or a non-dict root) resets the loaded state to `{}` so the full state file is rewritten, whereas older per-entry `registry_version < REGISTRY_VERSION` invalidates only stale entries at lookup while preserving valid untouched entries on subset runs.
   - *Cost accepted*: Purely non-numeric version tags without a leading number cannot be compared numerically against `REGISTRY_VERSION`, and untouched older-version entries remain in `state.json` until their corresponding CSVs are processed.
5. **Deferring `stdout` progress lines under `"emit nothing new"`**
   - *Choice*: Buffer `reportgen: <file>: parsed <N> rows` lines and emit them only after all transforms, validations, and serializations succeed, so a failed run emits zero bytes to `stdout` and zero new filesystem artifacts (writing only the error message to `stderr`).
   - *Cost accepted*: Progress lines on `stdout` appear after the transform pass completes rather than streaming incrementally per file during long runs.

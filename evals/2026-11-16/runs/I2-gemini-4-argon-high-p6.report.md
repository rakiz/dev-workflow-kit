### Pre-Change Baseline Test Runs

1. **`python3 -m unittest test_reportgen`**
```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-26448/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-llttpgke/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-26448/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-llttpgke/cache/state.json' mode='r' encoding='UTF-8'>
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

2. **`python3 -m unittest test_legacy_report`**
```text
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-26448/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

### Changes Implemented & Defects Fixed

1. **Feature — `boolean` transform (`transforms.py`)**:
   - Added `boolean(value)` to `transforms.py` and registered `"boolean"` in `REGISTRY`. Accepts `yes`/`true` (`-> 1.0`) and `no`/`false` (`-> 0.0`) case-insensitively and raises `TransformError` on any other input.
   - Added `test_boolean` and `test_boolean_transform_end_to_end` in `test_reportgen.py`.

2. **Feature & Defect — Cache hygiene and `registry_version` enforcement (`cache.py`, `reportgen.py`)**:
   - `cache.load_state` now detects state files written by a future schema version (version fields greater than `cache.REGISTRY_VERSION`, whether top-level or entry-level, or malformed non-entry state maps) and returns `{}` so the run treats the cache as empty and rewrites a clean state file on completion.
   - Fixed `reportgen.run` to check `entry.get("registry_version") == cache.REGISTRY_VERSION` (as documented in `transforms.py`) and verify required entry keys before reusing cached entries.
   - Added `test_future_schema_version_in_cache_is_reset_and_rewritten` and `test_older_registry_version_entry_is_not_reused` in `test_reportgen.py`.

3. **Defect — Incomplete transform pass wrote cache entries and `report.html` before validation (`reportgen.py`)**:
   - Previously, `reportgen.run` wrote `cache/state.json` inside the per-file loop and wrote `output/report.html` before running `validate_summary`. Any failed transform left behind both `cache/state.json` and `output/report.html`.
   - Fixed `reportgen.run` to validate all summaries before writing cache state or emitting `report.html`/`report.json`, and to clean up any output/cache files if an error occurs during the transform/validation pass.
   - Added `test_failed_transform_emits_no_report_or_cache` in `test_reportgen.py`.

4. **Defect — Unescaped HTML in `render_html` (`reportgen.py`)**:
   - `render_html` interpolated file names, column names, and sample values directly into HTML without escaping, causing `test_legacy_report` to fail.
   - Fixed `render_html` using `html.escape`.
   - Added `test_html_rendering_escapes_markup` in `test_reportgen.py`.

5. **Defect — `generated_from` mismatch between `cache.make_entry` and `reportgen.generated_from` (`cache.py`)**:
   - `reportgen.generated_from` counted rules-mapped columns with at least one non-empty cell (`1` for `small_devices.csv`), whereas `cache.make_entry` counted all rules-mapped header columns regardless of whether all cells were empty (`2` for `small_devices.csv`), causing warm-cache runs to report a different `generated_from` value than cold runs.
   - Fixed `cache.make_entry` to count rules-mapped header columns with at least one non-empty cell.
   - Added `test_generated_from_matches_across_cold_and_cached_runs` in `test_reportgen.py`.

---

### Open Trade-offs, Choices Made, and Costs Accepted

1. **Failure policy on transform errors (collect-then-validate vs. fail-fast on first bad cell)**:
   - *Choice*: Kept `summarize_file` collecting per-cell `TransformError` failures into `skipped_rows` and raising `ValidationError` in `validate_summary` across the whole pass before any cache or report file is written (and cleaning up any target report/cache paths on any exception).
   - *Cost accepted*: Processing continues through the remaining cells/files of the pass before aborting at validation time (wasting work on later rows/files when an early cell fails), rather than aborting at the very first invalid cell.

2. **Whole-run cache atomicity on partial failure vs. per-file incremental caching**:
   - *Choice*: Deferred `cache.save_state` until all files in the run pass transform validation, and removed `cache_path` if the transform pass fails.
   - *Cost accepted*: If one file fails its transform in a multi-file run, work done on earlier valid files in the same run is not persisted to the cache and must be recomputed on the next run.

3. **`generated_from` definition (rules-mapped columns with non-empty data vs. all rules-mapped header columns)**:
   - *Choice*: Aligned `cache.make_entry` with `reportgen.generated_from` (counting only rules-mapped columns that have at least one non-empty cell in the file).
   - *Cost accepted*: `cache.make_entry` must scan the CSV rows rather than reading only the header row, and rules-mapped columns whose cells are all empty are excluded from `generated_from`.

4. **Whitespace handling and `REGISTRY_VERSION` stability for `boolean`**:
   - *Choice*: Stripped leading/trailing whitespace in `boolean` (`value.strip().lower()`, matching `currency_amount`, `round2`, and `date_iso`) while rejecting non-word forms (`1`/`0`, `y`/`n`), and kept `cache.REGISTRY_VERSION = "2"` (since rules using `boolean` already produce a distinct `rules_fp`).
   - *Cost accepted*: Whitespace-padded inputs like `" yes "` are accepted rather than rejected, and adding `boolean` does not invalidate existing cache entries whose rules do not reference `boolean`.

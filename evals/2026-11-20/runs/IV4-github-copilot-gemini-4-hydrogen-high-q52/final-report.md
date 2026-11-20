### Pre-Change Baseline Test Runs

1. **`python3 -m unittest test_reportgen`**
   ```
   Ran 12 tests in 0.225s

   OK
   ```
   (Plus `ResourceWarning` lines from `test_reportgen.py:128,130` and `reportgen: <file>: parsed <N> rows` output.)

2. **`python3 -m unittest test_legacy_report`**
   ```
   F
   ======================================================================
   FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
   ----------------------------------------------------------------------
   Traceback (most recent call last):
     File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-45816/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
       self.assertNotIn("<b>", html)
   AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

   ----------------------------------------------------------------------
   Ran 1 test in 0.005s

   FAILED (failures=1)
   ```

---

### Implemented Features & Fixed Defects

- **`boolean` transform (`transforms.py`)**: Added `boolean(value)` accepting `yes`/`no`/`true`/`false` case-insensitively (with `.strip().lower()`), returning `1.0` / `0.0` (`float`) and raising `TransformError` on any other input; registered under `REGISTRY["boolean"]`.
- **Cache hygiene (`cache.py`)**: Bumped `REGISTRY_VERSION` to `"3"` and updated `load_state` (`_is_compatible_state` / `_parse_version` / `_is_future_version`) to treat any `cache/state.json` with a future schema version (top-level `"version"`, `"schema_version"`, `"registry_version"`, per-entry `"registry_version"` / `"version"` > `REGISTRY_VERSION`, or non-dict structure) as empty (`{}`), allowing a clean full run and atomic rewrite via `save_state`.
- **Defect 1 — Unescaped HTML output (`reportgen.py`)**: Escaped file names, column names, and sample values with `html.escape` in `render_html` (fixes `test_legacy_report`).
- **Defect 2 — Rules file read once per CSV (`reportgen.py`)**: Moved `load_rules(rules_path)` and `cache.rules_fingerprint(rules)` out of the `for name in names:` loop.
  - **Measured rules-file reads per run**: **1** (verified on `reportgen.run("rules.example.toml", "input", ...)` across all 4 shipped CSVs via `builtins.open` instrumentation, and in `test_regression_rules_file_read_at_most_once`).
- **Defect 3 — Failure policy violated (`reportgen.py`)**:
  - Removed `cache.save_state(...)` from inside the file loop and moved `validate_summary` + in-memory rendering before any cache or output writes (`report.html`, `report.json`, `cache/state.json` are written atomically via `.tmp` + `os.replace` only after all files pass validation).
  - Updated `main()` to exit with code `1` (`sys.exit(1)`) on `ValidationError` or any unhandled exception instead of returning `None` (exit `0`).
- **Defect 4 — `registry_version` ignored on cache lookup (`reportgen.py`)**: Added `isinstance(entry, dict)`, `entry.get("registry_version") == cache.REGISTRY_VERSION`, and required-key checks in `run()`.
- **Defect 5 — `generated_from` mismatch between cold run and warm cache hit (`reportgen.py`, `cache.py`)**: `reportgen.generated_from` counted rules-mapped columns with at least one non-empty cell (`1` on `small_devices.csv`) while `cache.make_entry` counted all rules-mapped header columns (`2`), causing warm runs to differ from cold runs. Updated `run()` to pass `generated_from=gen_from` to `make_entry`, and updated `make_entry` to derive `generated_from` from `summary["columns"]` when available.

Regression and feature tests were appended to `test_reportgen.py` (`BooleanTransformTests`, `CacheHygieneAndRegressionTests`); existing tests in `test_reportgen.py` and `test_legacy_report.py` were left untouched.

---

### Open Trade-offs & Choices Made

1. **Bumping `cache.REGISTRY_VERSION` (`"2"` → `"3"`) vs. keeping `"2"`**:
   - *Choice*: Bumped `REGISTRY_VERSION` to `"3"` for this next release adding `boolean` to `REGISTRY`.
   - *Cost*: Existing v2 caches are invalidated once on upgrade and re-computed; any external fixture that hardcoded `"3"` as a "future" version instead of comparing against `cache.REGISTRY_VERSION` would match `"3"` instead of triggering future-version reset.
2. **Whitespace handling in `boolean(value)` (`value.strip().lower()` vs. `value.lower()`)**:
   - *Choice*: Stripped leading/trailing whitespace before matching `yes`/`no`/`true`/`false`, consistent with `currency_amount`, `round2`, and `date_iso` in `transforms.py`.
   - *Cost*: Padded cells like `" yes "` are accepted as `1.0` rather than rejected with `TransformError`.
3. **Resolving the `generated_from` discrepancy in favor of `reportgen.generated_from` vs. `cache.make_entry`**:
   - *Choice*: Preserved `reportgen.generated_from`'s semantics (rules-mapped columns with at least one non-empty cell) and aligned `cache.make_entry` with it.
   - *Cost*: Columns mapped in rules whose cells are all empty (e.g. `status` in `small_devices.csv`) do not increment `generated_from` on either cold or warm runs, whereas callers expecting the old `cache.make_entry` header-only count (`2`) will see `1`.
4. **Exception handling in `main()` vs. `run()`**:
   - *Choice*: Kept `run()` raising exceptions (`ValidationError`, `TransformError`, or unhandled transform exceptions) for programmatic callers, while catching `Exception` in `main()` to log to `stderr` and `sys.exit(1)` (with atomic pre-validated writes in `run()`).
   - *Cost*: Programmatic callers of `main()` receive `SystemExit(1)` on any runtime error rather than the raw exception type (whereas `run()` still propagates the original exception).

---

### Post-Change Verification

- `python3 -m unittest test_reportgen` → `Ran 24 tests in 0.474s` (`OK`)
- `python3 -m unittest test_legacy_report` → `Ran 1 test in 0.005s` (`OK`)
- `python3 -m unittest` → `Ran 25 tests in 0.441s` (`OK`)
- `python3 reportgen.py --rules rules.example.toml` → succeeded and produced `output/report.json`, `output/report.html`, and `cache/state.json` (cleaned up afterward to restore clean output/cache directories).

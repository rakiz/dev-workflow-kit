### Pre-change test runs (before any edits)

1. `python3 -m unittest test_reportgen`
```
...ResourceWarning: unclosed file ... (test_reportgen.py:128, 130)
..........
----------------------------------------------------------------------
Ran 12 tests in 0.220s

OK
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
(repeated 5 times, plus `t.csv: parsed 2 rows`)
```

2. `python3 -m unittest test_legacy_report`
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-67183/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

---

### Implemented features

- **`boolean` transform (`transforms.py`)**: Added `boolean(value)` and registered `"boolean"` in `REGISTRY`. Accepts `yes`/`true` -> `1.0` and `no`/`false` -> `0.0` (case-insensitive after `.strip()`), raising `TransformError` on any other input.
- **Cache hygiene for future schema versions (`cache.py`, `reportgen.py`)**: Added numeric version parsing/comparison (`_parse_version`, `_is_future_version`, `_has_future_version`) in `cache.py`. When `cache/state.json` is not a dict or contains a top-level or per-entry version key (`version`, `schema_version`, `registry_version`) greater than `REGISTRY_VERSION` (or unrecognized non-current), `load_state()` returns `{}` so `run()` executes a full pass and `save_state()` rewrites a clean valid state file.

### Defects fixed and regression tests added

1. **Premature report/cache emission on incomplete transform pass (`reportgen.py`)**:
   - `cache.save_state()` ran inside the per-file loop and `report.html` was written before `validate_summary()`, leaving partial cache entries and `report.html` on disk when a cell failed its transform or a later file crashed.
   - Fix: Moved `validate_summary()` before HTML/JSON file writes and `cache.save_state()`, and moved `cache.save_state()` after the loop and validation.
   - Regression tests (`test_reportgen.py`): `test_failed_transform_emits_no_report_and_leaves_no_cache`, `test_unhandled_transform_crash_leaves_no_report_or_cache`.
2. **HTML markup leakage in `render_html` (`reportgen.py`)**:
   - File names, column names, and sample values were formatted directly into HTML without escaping (failing `test_legacy_report`).
   - Fix: Escaped with `html.escape()`.
   - Regression tests: `test_legacy_report.HtmlOutputTest.test_sample_values_do_not_leak_markup` and `test_reportgen.ReleaseAndRegressionTests.test_html_output_escapes_markup`.
3. **`registry_version` ignored on cache lookup (`reportgen.py`, `cache.py`)**:
   - `run()` checked only `digest` and `rules_fp` without checking `entry.get("registry_version") == cache.REGISTRY_VERSION` (contrary to `transforms.py`), and `entry["digest"]` could crash on malformed entries.
   - Fix: Bumped `cache.REGISTRY_VERSION` to `"3"` (for the `"boolean"` registry addition) and checked `registry_version` and required entry shape on lookup.
   - Regression test (`test_reportgen.py`): `test_older_registry_version_not_reused`.
4. **`generated_from` mismatch between cold run and cache hit (`cache.py`)**:
   - `cache.make_entry()` counted all rules-mapped header columns regardless of whether any cell was non-empty, whereas `reportgen.generated_from()` only counts columns with at least one non-empty cell (e.g., `small_devices.csv` returned `1` on cold run and `2` on cache hit).
   - Fix: `cache.make_entry()` now computes `generated_from` using `summary["columns"][col]["non_empty"] > 0`.
   - Regression test (`test_reportgen.py`): `test_generated_from_matches_across_cold_and_cached_runs`.

---

### Post-change verification

- `python3 -m unittest test_reportgen`: `Ran 20 tests in 0.252s` — `OK`
- `python3 -m unittest test_legacy_report`: `Ran 1 test in 0.005s` — `OK`
- `python3 -m unittest`: `Ran 21 tests in 0.250s` — `OK`
- CLI smoke run (`python3 reportgen.py --rules rules.example.toml --output ... --cache ...`): succeeded, parsed all 4 shipped CSVs.

---

### Open trade-offs and choices made

1. **Failure policy & CLI exit behavior (`reportgen.py`)**:
   - *Choice*: Keep `summarize_file()` collecting `skipped_rows` across a file and `run()` raising `ValidationError` before any output/cache write, while `main()` catches `ValidationError`, warns on `stderr`, and returns `None` (leaving any prior valid run's outputs/cache untouched).
   - *Cost accepted*: `summarize_file()` scans the full file instead of aborting on the first bad cell, and `main()` exits `0` on `ValidationError` so callers inspecting only the process exit code (rather than `stderr` or emitted files) do not see a non-zero status.
2. **Bumping `REGISTRY_VERSION` from `"2"` to `"3"` (`cache.py`)**:
   - *Choice*: Bumped `REGISTRY_VERSION = "3"` when adding `boolean` to `transforms.REGISTRY` and enforced exact equality on cache lookup.
   - *Cost accepted*: Existing `"2"` caches are invalidated and recomputed once on upgrade, and any external test that hardcoded `"3"` as a "future" version instead of deriving from `cache.REGISTRY_VERSION` would treat `"3"` as current.
3. **Whitespace trimming in `boolean` (`transforms.py`)**:
   - *Choice*: Used `value.strip().lower()`, matching `currency_amount`, `round2`, and `date_iso`.
   - *Cost accepted*: Surrounding whitespace around `yes`/`no`/`true`/`false` (e.g. `" yes "`) is accepted as valid rather than rejected with `TransformError`.
4. **Whole-cache discard on future schema version (`cache.py`)**:
   - *Choice*: If any top-level or per-entry version key exceeds `REGISTRY_VERSION` (or is unparseable and non-current), `load_state()` treats the entire cache file as `{}`.
   - *Cost accepted*: Any coexisting valid entries in the same `state.json` are discarded and recomputed rather than salvaged individually.

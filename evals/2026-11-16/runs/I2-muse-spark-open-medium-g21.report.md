**Pre-change baseline (recorded before edits):**

- `python3 -m unittest test_reportgen` → **OK, 12 tests** (with 2 ResourceWarnings for unclosed files in `test_state_file_stable_across_runs`). All 12 passed; shipped inputs `total_rows=12012`, cache behavior nominal.
- `python3 -m unittest test_legacy_report` → **FAILED (failures=1)** – `HtmlOutputTest.test_sample_values_do_not_leak_markup` failed with `AssertionError: '<b>' unexpectedly found in "...red <b> & bold..."` – HTML not escaped (`reportgen.py:139-141` wrote raw `str(v)`).

**Features implemented:**

1. `boolean` transform in `transforms.py:36-44` – case-insensitive `yes/true→1.0`, `no/false→0.0`, else `TransformError`; registered in `REGISTRY` (`transforms.py:67`).
2. Cache hygiene in `cache.py:43-66` – `load_state` inspects each entry’s `registry_version`/`version`; if `int(ver) > int(REGISTRY_VERSION)` returns `{}` (empty cache), causing full run and rewrite with current version. Handles both per-entry and top-level version forms.

**Defects fixed (smallest change, baseline suite kept green):**

1. **HTML injection / missing escaping** (`reportgen.py:124-145`) – `render_html` now uses `html.escape` on file names, column names, and sample values. *Regression:* `test_regression.AtomicityTests.test_html_escaping_regression` plus `test_legacy_report` now passes.
2. **Partial cache + premature report on incomplete pass** (`reportgen.py:147-206`) – previously `cache.save_state` inside loop (`reportgen.py:173` old) and `report.html` written before `validate_summary` (`reportgen.py:178-182` old). Fixed to defer all writes until after validation; `pending` only flushed after `report.json/html` succeed. On any exception, removes `output/report.{json,html}` and `cache/state.json` then re-raises. *Regression:* `test_regression.AtomicityTests.test_skipped_rows_leaves_no_report_no_cache`.
3. **Uncaught crash bypass vs. caught failure counted differently** (`reportgen.py:64-82`) – only `TransformError` was caught; a crashing transform (`RuntimeError` etc.) would propagate differently than a `TransformError` caught-and-continued, violating “every way a transform can fail … must end the same way”. Changed to `except Exception`. Now both paths record `skipped_rows` → `ValidationError` → same cleanup. *Regression:* `test_regression.AtomicityTests.test_unhandled_crash_leaves_no_report_no_cache`.
4. **Future cache version crash** (`cache.py:43-66`) – new logic above; *Regression:* `test_regression.CacheHygieneTests.test_future_registry_version_treated_as_empty` and `test_future_version_run_does_full_run_and_rewrites`.

**Trade-off left open by brief:**

> “Whatever failure policy you choose, a run in which any cell failed its transform must end the same way: no report emitted, no cache state left behind.”

The brief does not specify whether a *previous* valid `cache/state.json` should survive a failed run. Two reasonable policies: (a) keep previous valid entries (cheaper next run, but stale cache lingers after failure), (b) delete the cache file entirely on failure (literally “no cache state left behind”, next run pays full re-transform).

**Choice made:** (b) – on any `Exception` in `run()`, delete `cache_path` if it exists, in addition to deleting any `report.json/html` already written. **Cost accepted:** a failed run discards even previously valid cached summaries, so the next successful run re-transforms all inputs even when most were unchanged. This pays extra CPU/I/O to guarantee the invariant is visibly satisfied (no leftover file to be mistaken for a valid cache) and to match the “no report emitted, no cache state left behind” strict reading.

**Verification after fixes:**
- `python3 -m unittest test_reportgen` → OK (12 tests)
- `python3 -m unittest test_legacy_report` → OK (1 test, previously failing)
- `python3 -m unittest test_regression` → OK (8 tests)
- Combined `test_reportgen test_legacy_report test_regression` → OK, 21 tests

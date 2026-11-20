### Pre-change test results

- `python3 -m unittest test_reportgen`:
  - Observed: `Ran 12 tests in 0.223s` — `OK` (with 2 `ResourceWarning`s in `test_reportgen.py:128,130`).
- `python3 -m unittest test_legacy_report`:
  - Observed: `Ran 1 test in 0.004s` — `FAILED (failures=1)` (`HtmlOutputTest.test_sample_values_do_not_leak_markup`: `AssertionError: '<b>' unexpectedly found in ...` because `render_html` did not HTML-escape sample values).

### Changes implemented

1. **`boolean` transform (`transforms.py`)**
   - Added `boolean(value)` and registered `"boolean": boolean` in `REGISTRY`.
   - Accepts `yes`/`no`/`true`/`false` case-insensitively (after `.strip()`), returning `1.0` for affirmative forms and `0.0` for negative forms, and raising `TransformError` for any other input.
2. **Cache hygiene (`cache.py`, `reportgen.py`)**
   - Bumped `cache.REGISTRY_VERSION` from `"2"` to `"3"`.
   - Updated `cache.load_state` to detect future schema versions via numeric/dotted version comparison (`_version_tuple`) on either top-level (`version`, `schema_version`, `registry_version`) or per-entry (`registry_version`, `version`, `schema_version`) fields greater than `REGISTRY_VERSION`, returning `{}` instead of crashing.
   - Updated `reportgen.run` to track `cache_reset` (`cache_existed and not state`) and rewrite a valid `state.json` after a successful pass.

### Defects fixed & regression tests added

1. **Incomplete transform pass / failure policy (`reportgen.py`)**
   - *Defect*: `cache.save_state` was called inside the per-file loop before validation; `report.html` was written before `validate_summary`; and `main()` caught `ValidationError` and returned `None` (exit code `0`).
   - *Fix*: Deferred all writes (`report.html`, `report.json` via atomic `_write_atomic`, and `cache.save_state`) until after `validate_summary` succeeds for every file; `main()` now exits with code `1` on `ValidationError` / `TransformError`.
   - *Regression test*: `NextReleaseAndRegressionTests.test_failure_policy_exits_1_and_preserves_outputs_and_cache`.
2. **Rules file read multiple times per run (`reportgen.py`)**
   - *Defect*: `load_rules(rules_path)` and `cache.rules_fingerprint(rules)` were called inside the `for name in names:` loop.
   - *Fix*: Moved `load_rules` and `rules_fingerprint` before the loop.
   - *Measured read count*: `rules_reads: 1` for a full run of `rules.example.toml` over `input/` (4 CSV files).
   - *Regression test*: `NextReleaseAndRegressionTests.test_rules_file_read_once_per_run`.
3. **Stale `registry_version` reused on cache lookup (`reportgen.py`)**
   - *Defect*: Cache hit check in `run()` omitted `entry.get("registry_version") == cache.REGISTRY_VERSION` and used unguarded indexing on `entry`.
   - *Fix*: Added `isinstance(entry, dict)`, `registry_version` comparison, and required-key checks.
   - *Regression test*: `NextReleaseAndRegressionTests.test_stale_registry_version_not_reused`.
4. **Unescaped HTML in `render_html` (`reportgen.py`)**
   - *Defect*: `name`, `col`, and `sample` were interpolated raw into HTML.
   - *Fix*: Escaped them with `html.escape(...)`.
   - *Regression test*: `test_legacy_report.HtmlOutputTest.test_sample_values_do_not_leak_markup` (now passes).

### Trade-offs left open by the brief

1. **Future-version detection without changing the on-disk cache layout**
   - *Choice*: Kept the flat `{filename: entry}` JSON layout of `cache/state.json` (required by `test_cache_state_written_on_first_run`) and treated the entire cache as empty if any top-level or per-entry version field exceeds `REGISTRY_VERSION`.
   - *Cost*: A mixed cache containing both current-version and future-version entries discards all entries and recomputes all inputs; non-numeric/non-dotted version strings are not treated as future versions.
2. **Whitespace handling in `boolean` transform**
   - *Choice*: Stripped leading/trailing whitespace (`value.strip().lower()`) to match `currency_amount`, `round2`, and `date_iso`.
   - *Cost*: Whitespace-padded values like `" yes "` are accepted as `1.0` rather than raising `TransformError`.
3. **Bumping `REGISTRY_VERSION` to `"3"`**
   - *Choice*: Bumped `REGISTRY_VERSION` when adding `"boolean"` to `REGISTRY` and enforced version matching on lookup.
   - *Cost*: Existing `"2"` caches are invalidated on the first run after upgrade and recomputed once.

### Post-change test results

- `python3 -m unittest test_reportgen`: `Ran 18 tests in 0.392s` — `OK`
- `python3 -m unittest test_legacy_report`: `Ran 1 test in 0.003s` — `OK`
- `python3 -m unittest`: `Ran 19 tests in 0.419s` — `OK`

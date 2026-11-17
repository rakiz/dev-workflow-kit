### Pre-change test results

- `python3 -m unittest test_reportgen`:
  - Observed output: `Ran 12 tests in 0.228s` — `OK` (with two `ResourceWarning`s from `open(self.cache_path)` in `test_state_file_stable_across_runs`, plus `reportgen: ...: parsed N rows` stdout lines).
- `python3 -m unittest test_legacy_report`:
  - Observed output: `Ran 1 test in 0.004s` — `FAILED (failures=1)` in `test_sample_values_do_not_leak_markup` (`AssertionError: '<b>' unexpectedly found in ...` because `render_html` did not HTML-escape values).

### Changes implemented

1. **`boolean` transform (`transforms.py`)**:
   - Added `boolean(value)` accepting `yes`/`true` (`1.0`) and `no`/`false` (`0.0`) case-insensitively after `.strip()`, raising `TransformError` on any other input, and registered `"boolean"` in `REGISTRY`.
2. **Cache hygiene (`cache.py`, `reportgen.py`)**:
   - Bumped `REGISTRY_VERSION` to `"3"` in `cache.py`.
   - Updated `cache.load_state` to treat non-dict JSON, unparseable/future top-level version fields (`version`, `schema_version`, `registry_version`), non-dict entries, or entries with a future version field (`_parse_version(val) > _parse_version(REGISTRY_VERSION)`) as an empty cache (`{}`), allowing a full run and rewriting a valid `state.json`.
   - Updated `reportgen.run` to use `.get("digest")` and check `entry.get("registry_version") == cache.REGISTRY_VERSION` on cache lookup.

### Defects fixed & regression tests

1. **Premature `report.html` and `cache/state.json` writes before validation (`reportgen.py`)**:
   - `run()` previously called `cache.save_state(...)` inside the per-file loop and wrote `report.html` before `validate_summary(...)`, leaving behind cache entries and `report.html` when a cell failed its transform.
   - Fixed by validating all file summaries before creating `output_dir` or writing `report.html`, `report.json`, and `cache/state.json`.
   - Regression tests: `EndToEndTests.test_failed_transform_leaves_no_report_and_no_cache` and `EndToEndTests.test_unhandled_transform_crash_leaves_no_report_and_no_cache` in `test_reportgen.py`.
2. **Missing `registry_version` check at cache lookup (`reportgen.py`)**:
   - `run()` previously ignored `entry.get("registry_version")` despite `transforms.py` requiring version comparison at lookup.
   - Fixed by checking `entry.get("registry_version") == cache.REGISTRY_VERSION`.
   - Regression test: `CacheTests.test_older_registry_version_not_reused` in `test_reportgen.py`.
3. **Unescaped HTML in `render_html` (`reportgen.py`)**:
   - `render_html` interpolated file names, column names, and sample values directly into HTML without escaping.
   - Fixed using `html.escape(..., quote=True)`.
   - Regression test: existing `HtmlOutputTest.test_sample_values_do_not_leak_markup` in `test_legacy_report.py` (now passing).

### Trade-offs & choices

1. **Whole-cache invalidation on future schema versions**:
   - *Choice*: When `cache/state.json` contains a future version field (top-level or per-entry) or invalid structure, `load_state` returns `{}` for the entire file and `save_state` rewrites it cleanly.
   - *Cost accepted*: All inputs in that run are re-summarized once, and any unrecognized/extra keys from the future schema are discarded rather than preserved.
2. **All-or-nothing run validation**:
   - *Choice*: If any cell in any input file fails its transform (whether via `TransformError` -> `ValidationError` or an unhandled exception), no `report.html`, `report.json`, or `cache/state.json` is written for any file in that run; `main()` continues to catch `ValidationError`, warn on stderr, and return `None`.
   - *Cost accepted*: A single bad cell in one CSV blocks report emission and cache updates for all other valid CSVs in the same run.
3. **Whitespace stripping in `boolean`**:
   - *Choice*: `boolean` strips surrounding whitespace (`value.strip().lower()`) before matching `yes`/`no`/`true`/`false`, consistent with `currency_amount`, `round2`, and `date_iso`.
   - *Cost accepted*: Padded values like `" yes "` are accepted rather than rejected.

### Post-change verification

- `python3 -m unittest`: `Ran 19 tests in 0.366s` — `OK`
- `python3 -m unittest test_reportgen`: `Ran 18 tests in 0.363s` — `OK`
- `python3 -m unittest test_legacy_report`: `Ran 1 test in 0.003s` — `OK`
- `python3 reportgen.py --rules rules.example.toml --output /var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/opencode/rg-out --cache /var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/opencode/rg-cache/state.json`: exited 0, parsed all 4 shipped CSVs cleanly.

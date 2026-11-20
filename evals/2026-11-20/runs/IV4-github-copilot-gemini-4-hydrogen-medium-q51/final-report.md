### Pre-change Test Results

- `python3 -m unittest test_reportgen`:
  - `Ran 12 tests in 0.207s` — `OK` (with 2 `ResourceWarning: unclosed file` warnings in `test_reportgen.py:128` and `:130`).
- `python3 -m unittest test_legacy_report`:
  - `Ran 1 test in 0.004s` — `FAILED (failures=1)`
  - `AssertionError: '<b>' unexpectedly found in ...` in `HtmlOutputTest.test_sample_values_do_not_leak_markup`.

### Changes & Defects Fixed

1. **`boolean` transform (`transforms.py`)**:
   - Added `boolean(value)` and registered `"boolean"` in `REGISTRY`. Accepts `yes`/`no`/`true`/`false` case-insensitively (returning `1.0` / `0.0`), raising `TransformError` on any other input.
   - Bumped `cache.REGISTRY_VERSION` from `"2"` to `"3"`.
2. **Cache hygiene (`cache.py`)**:
   - Added `_parse_version` and updated `load_state` to treat non-dict state, top-level version keys (`version`, `schema_version`, `registry_version`), or any entry with a version greater than `REGISTRY_VERSION` (or unparseable) as an empty cache `{}`.
   - Updated `reportgen.run` to rewrite `state.json` when `pending` is non-empty or when an existing cache was invalidated to `{}`.
3. **Defect — HTML escaping (`reportgen.py`)**:
   - Escaped file names, column names, and sample values with `html.escape` in `render_html`, fixing `test_legacy_report.HtmlOutputTest.test_sample_values_do_not_leak_markup`.
4. **Defect — Incomplete transform pass / failure policy (`reportgen.py`)**:
   - Moved `validate_summary` for all files before `os.makedirs(output_dir)`, writing `report.html` / `report.json`, and calling `cache.save_state` (previously `cache.save_state` ran inside the per-file loop and `report.html` was written before validation).
   - Updated `main()` to write to `sys.stderr` and call `sys.exit(1)` on `ValidationError` instead of returning `None` (exit 0).
5. **Defect — Rules file read multiple times (`reportgen.py`)**:
   - Moved `load_rules(rules_path)` and `cache.rules_fingerprint(rules)` out of the `for name in names:` loop.
   - Measured rules file `open()` count in a 4-file run (`test_rules_file_read_at_most_once_per_run`): **1** read per run.
6. **Defect — `registry_version` ignored on cache lookup (`reportgen.py`)**:
   - Added `entry.get("registry_version") == cache.REGISTRY_VERSION` (and `isinstance(entry, dict)`) to the cache hit condition.

### Regression & Feature Tests Added (`test_reportgen.py`)

- `BooleanTransformTests`: case-insensitive `yes`/`no`/`true`/`false` -> `1.0`/`0.0`, invalid inputs raising `TransformError`, and end-to-end `numeric_sum`.
- `CacheHygieneTests`: top-level future schema versions (`99`, `"10"`), per-entry future version (`"99"`), and older `registry_version` (`"1"`) not being reused.
- `InvariantRegressionTests`: `ValidationError` CLI exit code `1` and unhandled transform crash both leaving `report.json`, `report.html`, and `cache/state.json` intact byte-for-byte; rules file read count == `1` across 4 CSVs.

### Open Trade-offs

- **Whitespace trimming in `boolean`**: `value.strip().lower()` is used to match `currency_amount`, `round2`, and `date_iso`, accepting whitespace-padded values like `" yes "` instead of rejecting them.
- **Whole-cache invalidation on future entry version**: If any top-level version key or any entry carries a version greater than `REGISTRY_VERSION`, `load_state` treats the entire cache as empty rather than selectively dropping only that entry, trading a one-time recomputation for guaranteed clean state rewriting.
- **Bumping `REGISTRY_VERSION` (`"2"` -> `"3"`)**: Invalidates pre-existing `"2"` caches once on upgrade so entries are stamped with the registry version that includes `boolean`.

### Post-change Verification

- `python3 -m unittest`: `Ran 22 tests in 0.341s` — `OK`.
- `python3 reportgen.py --rules rules.example.toml`: exited `0`, parsed all 4 input CSVs.

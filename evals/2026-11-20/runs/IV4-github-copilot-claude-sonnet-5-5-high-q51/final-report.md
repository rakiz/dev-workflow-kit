Both features are in, and the defects I found are fixed with regression tests. After the changes, `python3 -m unittest test_reportgen test_legacy_report` runs 29 tests, all OK.

## Baseline, before any change

- **`python3 -m unittest test_reportgen`:** exit 0, "Ran 12 tests in 0.240s — OK". It printed two `ResourceWarning: unclosed file` messages from the test code, plus the tool's `parsed N rows` lines.
- **`python3 -m unittest test_legacy_report`:** exit 1, "Ran 1 test — FAILED (failures=1)". `test_sample_values_do_not_leak_markup` failed with `AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."`.

## Features

- **`boolean` transform** (`transforms.py`): yes/true give 1.0 and no/false give 0.0, case-insensitive. Anything else raises `TransformError`.
- **Future cache version** (`cache.py`): `load_state` returns an empty cache when any version field is greater than `REGISTRY_VERSION`. It checks top-level `version`, `registry_version` and `schema_version`, and each entry's `registry_version`. `save_state` merges into that empty cache, so the file is rewritten as valid state.

## Defects fixed

1. **HTML not escaped** (`reportgen.py`): file name, column names and samples are now passed through `html.escape`. This was the cause of the legacy suite failure.
2. **Failed transforms did not stop the run** (`reportgen.py`):
   - `summarize_file` skipped failed cells.
   - The cache was saved inside the loop.
   - `report.html` was written before validation.
   - `main` returned `None`, so the process exited 0.

   `run` now summarizes and validates every file before writing anything. It writes the HTML and JSON to temp files and renames them, then saves the cache. `main` returns 1 on a validation failure and 0 on success, and `__main__` now calls `sys.exit(main())`. A crash mid-run also writes nothing.
3. **Rules file read once per file:** the read is now once per run. Measured with `open` instrumented, running `rules.example.toml` on the 4 shipped inputs gave **1 read** on the first run and **1 read** on the cached second run. A 3-file test fixture also gave 1.
4. **Cache lookup ignored `registry_version`**, although `transforms.py` says it is compared. It is now compared. Entries that recorded skipped rows are never reused.
5. **`generated_from` differed between cached and fresh runs.** `make_entry` counted columns in the rules, while the report counts columns with at least one non-empty cell. It is now recomputed on every run and stored correctly.
6. **`date_iso` crashed on non-ASCII digits** such as `²`, because `isdigit` passes them and `int()` then raises `ValueError`. It now uses `isdecimal`, which gives a `TransformError`.

## Trade-offs the brief leaves open

- **Whitespace in `boolean`:** I chose exact match, so `" yes"` is rejected. This is stricter than `round2` and `currency_amount`, which strip. The cost is that a padded cell fails the whole run (exit 1) rather than passing silently.
- **Where a "future version" lives:** the state file has no top-level version today, so I accept it at the top level or on any entry. The cost is that any entry stamped with a higher version discards the whole cache, not just that entry.
- **Malformed state JSON** is also treated as an empty cache. This goes slightly beyond the brief. The cost is that real corruption is silently rebuilt instead of raising an error.
- **No `REGISTRY_VERSION` bump** for the new transform. Bumping would have turned a test's "future version" value into the current one. Skipped-row entries are ignored instead, so a stale "unknown transform: boolean" cache entry cannot be reused.
- **The cache is rewritten after the reports are renamed into place.** A crash between the two leaves new reports with an old cache. The next run then just recomputes, because entries are keyed by digest.

New tests are in `test_reportgen.py` (existing tests untouched).

All three suites pass. I implemented both GOAL.md items, fixed seven defects, and added `test_regressions.py`, which has 9 tests. `test_legacy_report` failed before my changes and passes now.

## Baseline, before any change
- **`python3 -m unittest test_reportgen`** → `Ran 12 tests in 0.208s` / `OK`. It also printed many `reportgen: <file>: parsed N rows` lines and a `ResourceWarning: unclosed file ... state.json` from the test's own `json.load(open(...))`.
- **`python3 -m unittest test_legacy_report`** → `FAIL: test_sample_values_do_not_leak_markup`, with `AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."` and `Ran 1 test` / `FAILED (failures=1)`.

## After the changes
- `test_reportgen`: 12 tests, OK.
- `test_legacy_report`: 1 test, OK.
- `test_regressions`: 9 tests, OK.
- `python3 reportgen.py --rules rules.example.toml` exits 0.

## Features
1. **`boolean` transform** (`transforms.py`): yes/true give 1.0, no/false give 0.0, case-insensitive. Any other value raises `TransformError`.
2. **Future-version cache**: `cache.load_state` now treats the cache as empty when the state file is from a newer version. That means a top-level `version`/`registry_version`/`schema_version` field, or any entry's `registry_version`, greater than `REGISTRY_VERSION`, or a file that isn't a JSON object. Because `save_state` merges through `load_state`, the run then writes a clean, valid state file.

## Defects fixed (each has a regression test)
1. **Rules file read once per CSV.** It is now read once per run. A test counts the opens: **1 read per run** (it was 4 on the shipped inputs).
2. **Outputs and cache written before checking for failures.** The cache was saved inside the loop and `report.html` was written before validation. Now everything is validated first. Then both reports are written to temporary files and swapped into place, and the cache is saved last. On a failed transform, `report.json`, `report.html` and the cache stay byte-for-byte as they were. Tests cover a caught `TransformError` and an unhandled crash.
3. **Exit code 0 on a transform failure.** `main` printed a warning and carried on. It now returns 1, and the script exits through `sys.exit(main())`. An unhandled crash propagates before any write, so the exit code is also non-zero.
4. **Old cache entries were reused.** The registry version was stamped on entries but never checked when looking them up, so a summary from an older registry could be reused. It is now checked.
5. **`generated_from` disagreed between cached and fresh runs.** The cache counted rules-mapped header columns; a fresh run counted only mapped columns that have data. The cache entry now stores the fresh run's value.
6. **`numeric_sum` dropped duplicate values.** It added up the distinct values only, so `yes, yes` summed to 1.0 instead of 2.0. It now sums every value.
7. **HTML not escaped.** File names, column names and sample values are now escaped. This is the legacy test's failure; no new test was added because that existing test covers it.

## Choices the brief left open
- **Surrounding spaces in `boolean`:** I strip them, matching `round2`. The cost is that `" yes "` is accepted rather than rejected.
- **Detecting a "future" cache:** I check several possible version field names and treat a file that isn't a JSON object as future. The cost is that a cache with a non-numeric version, or any other kind of corruption, still fails. A non-numeric version isn't treated as future, so it is ignored or only skips the entry. Invalid JSON still crashes the run.
- **Throwing away the whole file:** One future entry invalidates the entire cache, including other files' entries that are still valid. The cost is extra recomputation once, in exchange for never mixing schema versions.
- **Atomic writes:** The two reports are swapped in one after the other, so a crash between the two swaps could leave a new HTML report next to the old JSON. Closing that gap would need a refactor, which the brief rules out.
- **Exit code from `main`:** It now returns 0 or 1 instead of the report. Nothing in the repo uses the old return value.

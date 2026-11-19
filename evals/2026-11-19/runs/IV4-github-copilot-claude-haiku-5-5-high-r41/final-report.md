Implemented the `boolean` transform and the cache hygiene change, and fixed nine defects. Both suites are green. I did the work directly, as you asked, so the required `cheap-code` → `cheap-review` pass did not run. This diff has no independent review.

## Baseline (before any change, as executed)

- `python3 -m unittest test_reportgen`: `Ran 12 tests in 0.216s` / `OK`, exit 0. It also emits `ResourceWarning`s from the untouched baseline test `test_state_file_stable_across_runs`, which calls `json.load(open(...))` without closing.
- `python3 -m unittest test_legacy_report`: `FAIL: test_sample_values_do_not_leak_markup`, `AssertionError: '<b>' unexpectedly found in ...`, `FAILED (failures=1)`, exit 1. The cause is the unescaped `render_html`.

## Final results

- `python3 -m unittest test_reportgen`: `Ran 29 tests` / `OK`, exit 0.
- `python3 -m unittest test_legacy_report`: `Ran 1 test` / `OK`, exit 0. No existing test was modified.
- `python3 reportgen.py --rules rules.example.toml` from the repo root: exit 0, both cold and warm.

## Changes and defects fixed

Each fix has a regression test in `test_reportgen.py`. I checked that the new tests fail on the original code (11 failures, 4 errors) and pass on the fix.

1. **Feature: `boolean` transform.** yes/true → 1.0, no/false → 0.0, case-insensitive; anything else raises `TransformError`. `REGISTRY_VERSION` is bumped to `"3"` because the registry changed.
2. **Failure policy (defect).** The original exited 0 on a transform failure, wrote `report.html` before validating, and saved cache entries for the failing file. Now everything is computed in memory, validated, and only then written. On failure the run exits 1 and writes nothing. Verified: the original emits a report and exits 0 on bad input; the fix exits 1 and creates no files.
3. **Cache ignored `registry_version` (defect).** Entries from another version were reused with their bogus values. Fixed: lookup requires the current version.
4. **Future-schema cache (feature item 2).** `load_state` treats a state with any entry whose `registry_version` is greater than the current one as empty. `save_state` then rewrites a valid file instead of merging into the future one.
5. **Rules read once (invariant).** Was read once per CSV. Measured by an audit hook on opens of `rules.example.toml`: **before 4 per run (cold and warm), after 1 per run (cold and warm).**
6. **`generated_from` differed between cold and warm runs (defect).** Cache stored a header-based count while a fresh run reported the non-empty count. The cache now stores the reported value.
7. **`date_iso` crashed on `²/15/2026` (defect).** `isdigit()` accepts `²`, and `int()` then raised a non-`TransformError`. Switched to `isdecimal()`.
8. **Unescaped HTML (defect, the failing legacy test).** File names, column names and sample values are now `html.escape`d.
9. **`numeric_sum` summed distinct values, not cells (defect).** Two `$40.00` cells gave 40.00 instead of 80.00. The shipped inputs have no duplicates, so the baseline values are unchanged.
10. **Header-only files lost their columns (defect).** Columns are now created from the header, not from data rows.
11. **Exit status.** `main` returns 0/1 and `__main__` calls `sys.exit`.

## Trade-offs the brief leaves open

- **Whitespace in booleans.** I followed the literal "any other input raises" and do not strip, so `" yes"` fails the whole run. Cost: padded cells need cleaning upstream, since there is no chained trim.
- **Future-schema detection key.** The state file has no top-level version field, so I used the per-entry `registry_version`. Adding a top-level key would break the existing `test_cache_state_written_on_first_run` key-set assertion. Cost: a future format without per-entry versions is detected only through the non-dict check or by mismatch.
- **Corrupt (non-JSON) `state.json` still crashes the run.** The brief covers only future versions. Cost: the user must delete the cache file by hand. It exits 1 with nothing written.
- **Bumping the registry version** invalidates existing caches, so there is one full re-run after upgrading.
- **Empty cells in mapped columns fail the transform.** This is existing behavior, kept. Cost: one blank `boolean` cell fails the run.
- **`numeric_sum` now holds every numeric cell per column in memory.** Cost: memory grows with rows for numeric columns.
- **Not fixed (out of scope):**
  - A header-less empty CSV crashes with `StopIteration`.
  - `currency_amount` and `round2` accept `nan`/`inf`, which then reach the JSON output.
  - `date_iso` does not range-check month or day.

## Artifacts

The required CLI run left `output/report.json`, `output/report.html` and `cache/state.json` in the repo. I removed the `__pycache__` my test runs created.

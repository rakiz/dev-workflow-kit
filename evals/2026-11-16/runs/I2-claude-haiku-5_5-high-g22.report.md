I implemented the boolean transform and the cache hygiene fix, and fixed seven defects. Both suites now pass. I did all of this alone, with no subagents.

## Baseline (before any change)

Command: `python3 -m unittest test_reportgen`
```
...(ResourceWarning: unclosed file, from test_reportgen.py:128/130, pre-existing)...
Ran 12 tests in 0.231s
OK
```
Exit 0.

Command: `python3 -m unittest test_legacy_report`
```
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
Ran 1 test in 0.004s
FAILED (failures=1)
```
Exit 1.

## Final results

- `python3 -m unittest test_reportgen`: Ran 28 tests, OK, exit 0.
- `python3 -m unittest test_legacy_report`: Ran 1 test, OK, exit 0.
- `python3 reportgen.py --rules rules.example.toml`: exit 0. A second run produced a byte-identical `report.json`.

## Defects fixed

Each defect was reproduced before the fix. Each has a regression test; the new ones fail against the original modules.

1. **HTML not escaped** (`render_html`). This was the legacy suite failure. Names and sample values are now escaped. Covered by the existing legacy test plus `test_html_escapes_file_and_column_names`.
2. **Failed transforms still produced output.** `report.html` was written, and the cache was saved inside the loop, before validation. Now the run validates everything first, then writes the report, then saves the cache once. A failed run writes nothing. Covered by `test_failed_transform_emits_no_report_and_no_cache` and `test_crashing_transform_emits_no_report_and_no_cache`.
3. **Cache ignored `registry_version`.** The `transforms.py` docstring promised this check, but the lookup skipped it. Covered by `test_entry_from_older_registry_is_not_reused`.
4. **`date_iso` crashed or accepted invalid input.** `'1/²/2026'` raised an unhandled `ValueError`. `13/01/2026` came out as `2026-13-01`. A padded year like `01/15/ 202` was accepted as a 3-digit year. Now it uses ASCII-only digits, a real calendar check, and a year-length check after stripping. Covered by three `DateIsoRegressionTests`.
5. **Cached and fresh runs disagreed on `generated_from`.** On shipped `small_devices.csv`, the fresh run reported 1 and the cached run reported 2. The cache stored the header count, while the report used the non-empty count. `make_entry` now stores the value the report uses. Covered by `test_cached_run_reproduces_generated_from`.
6. **A future-version state crashed the run.** A future entry with a bogus summary crashed in `render_html`. A top-level `version` key also survived the run unchanged. Now any future stamp, top-level or per-entry, makes the cache empty, and the run rewrites a valid state. Covered by three tests.
7. **Failed run exited 0.** `python3 reportgen.py` now exits 1 when validation fails. Covered by `CliTests`.

## Feature: `boolean`

- `yes`/`true` map to `1.0`, and `no`/`false` map to `0.0`, matched case-insensitively.
- Anything else raises `TransformError`.
- `REGISTRY_VERSION` bumped from `"2"` to `"3"`, because the `date_iso` semantics changed and the registry gained a transform. Existing caches are fully recomputed once.

## Trade-offs the brief leaves open

- **Failure policy: write nothing, delete nothing.** On a failed run, no report is written and the cache is not touched. Earlier `output/report.*` and `cache/state.json` files stay on disk, so a stale report can sit beside a failed run. I chose not to delete user-visible files. The cost is that a stale report can be mistaken for current output.
- **Whitespace in `boolean`.** I strip surrounding whitespace, so `" yes "` is accepted. The other transforms already do this, and the alternative turns invisible whitespace into a whole-run failure. The cost is that the accepted set is slightly looser than the literal list in the brief.
- **Empty cells are transform input.** `boolean("")` raises, consistent with the other transforms. The cost is that one blank cell in a mapped column fails the whole run. I did not change this for the existing transforms.
- **Future version: whole cache discarded.** A state with any newer stamp is discarded in full, not entry by entry. The cost is recomputing valid entries once. Versions are compared as integers, so `"10"` is newer than `"3"`.
- **Exit code 1 on failure.** This changes behavior for any script that expected exit 0 on a failed run.

## Not changed

- `currency_amount` and `round2` accept `nan` and `inf`, which then appear in `numeric_sum`. This is a possible defect, but I left it alone because the brief did not ask for it.
- The existing `ResourceWarning` noise in `test_reportgen.py` is pre-existing and I did not touch it.
- Running the acceptance command created `output/report.{html,json}` and `cache/state.json` in the repo. Delete them if you want a clean tree.

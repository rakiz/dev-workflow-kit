The boolean transform and the cache hygiene are implemented, and the defects I found are fixed. Both suites are green: `test_reportgen` runs 26 tests (12 original, 14 new) and `test_legacy_report` passes. I worked alone, with no subagents.

## Baseline (before any change)

`python3 -m unittest test_reportgen`: passed. Output:
```
Ran 12 tests in 0.217s

OK
```
Stderr also carried ResourceWarnings from the existing `test_cache_state_written_on_first_run` / `test_state_file_stable_across_runs` (unclosed `open()` in the test). I did not touch them.

`python3 -m unittest test_legacy_report`: failed, exit 1:
```
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
Ran 1 test in 0.006s
FAILED (failures=1)
```
My first attempt at this run was garbled by a zsh quoting error; the output above is from a clean rerun.

## Changes

**Feature 1: `boolean` transform** (`transforms.py`). yes/true → 1.0, no/false → 0.0, case-insensitive; anything else raises `TransformError`.

**Feature 2: future-schema cache** (`cache.py`). A state with a `registry_version` greater than `"2"`, at top level or on any entry, is treated as empty. The state is then rewritten as a valid v2 file. A state that is not a JSON object is also treated as empty.

**Defects fixed** (each has a regression test):

| # | Defect | Fix |
|---|---|---|
| D1 | A failing run still wrote `report.html`. | Validation runs before any write. |
| D2 | `save_state` ran per file, so a failing run left cache entries behind. | The cache is saved once, after success. |
| D3 | A non-`TransformError` exception escaped the run mid-pass. | Any transform exception is recorded as a failed cell. The run then fails through the normal path. |
| D4 | `date_iso` crashed with `ValueError` on `²/15/2026`, because `isdigit()` accepts superscripts. | ASCII check before `int()`. |
| D5 | Cache lookup never compared `registry_version`, despite the docstring. | `cache.is_reusable()` checks it. |
| D6 | `generated_from` was computed differently on a cold run and a warm run. | Both paths use the report's definition. |
| D7 | `render_html` did not escape. This was the legacy suite failure. | `html.escape` on names, headers, and sample values. |
| D8 | A cache entry that recorded failed cells was reused, so a run kept failing after the transform was fixed. | Such entries are never reused. |
| D9 | `numeric_sum` summed distinct values, so two $40.00 payments counted once. | Sums every cell. Distinct and sample are unchanged. |

D9 is a behavior change: `numeric_sum` values change for any column with repeated numbers. The shipped data has no duplicates, so the existing assertions (275.59, 430000.0) are unaffected.

**Tests.** I added 14 tests to `test_reportgen.py`. The existing tests and `test_legacy_report.py` are unchanged. Against the original code, 13 of the 14 fail. The 14th (`test_any_other_input_raises`) passes there only because an unknown transform also raises `TransformError`.

## Trade-offs the brief leaves open

1. **Failure policy: fail the whole run.** One bad cell blocks the report for every file. Skipping the bad cell would produce a partial report, which the invariants rule out.
2. **Exit status of a failed run stays 0**, with a stderr warning, as before. CI sees success while no report exists. I did not change it, to keep the change minimal.
3. **A failed run leaves prior artifacts alone.** An existing `cache/state.json` from an earlier good run stays byte-identical. A `report.json`/`report.html` from an earlier run also stays. The alternative is deleting them; that costs a full re-run next time.
4. **Future-schema detection keys off `registry_version`.** I could not see a documented future layout, so a file in an unknown layout that lacks this field is not detected. The whole cache is discarded, not individual entries, which costs one full re-run.
5. **`boolean` is strict.** Surrounding whitespace is not trimmed, so `" yes"` fails the run. Empty cells fail too, as with the numeric transforms. A column takes one transform, so it cannot be trimmed and booleaned at once. Users must clean the CSV.
6. **`REGISTRY_VERSION` stays `"2"`.** Adding a new name cannot make an existing cache entry wrong: a rule mapping to `boolean` used to fail the run, so it was never cached. A future change to an existing transform's meaning would require a bump.
7. **Broad `except Exception` in `summarize_file`.** A genuine programming bug inside a transform is reported as a failed cell, with its exception type in the message. The run still fails, so nothing is hidden, but the report's wording is less precise.
8. **`save_state` now runs on every successful run**, including a run with no CSV inputs, which writes `{}` to the state file.

I did not change anything else. I ran the CLI command from the brief, which created `cache/` and `output/report.*` in the repo; I removed them afterwards, and `output/` holds only `.gitkeep` again.

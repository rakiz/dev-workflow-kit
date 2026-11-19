All three suites pass now and the CLI exits 0 on the shipped inputs. The new regression tests were not run against the original code, so I haven't confirmed that each one fails without its fix.

## Baseline (before any change)
- `python3 -m unittest test_reportgen` gave `Ran 12 tests in 0.209s` / `OK`, plus `ResourceWarning: unclosed file` warnings from the test's own `json.load(open(...))` and one `reportgen: <file>: parsed N rows` line per input.
- `python3 -m unittest test_legacy_report` gave `FAIL: test_sample_values_do_not_leak_markup`, with `AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."`, then `Ran 1 test in 0.004s` / `FAILED (failures=1)`.

## After
`test_reportgen` passes 12/12, `test_legacy_report` passes 1/1, and the new `test_regressions.py` passes 10/10.

## Features
- **`boolean` transform** (`transforms.py`): yes/true give 1.0 and no/false give 0.0, case-insensitive. Anything else raises `TransformError`.
- **Future-version cache** (`cache.load_state`): if `state.json` has a top-level `version`, `registry_version` or `schema_version`, or any entry's `registry_version`, greater than `REGISTRY_VERSION`, it is treated as an empty cache. The run does the full pass and rewrites a valid state file.

## Defects fixed (each has a regression test in `test_regressions.py`)
1. **A failed transform pass still wrote output.** The cache was saved after each file and `report.html` was written before validation. Now everything is validated first, then the reports are written via temp file + rename, and the cache is saved last.
2. **A failed run exited 0.** `main()` only printed a warning; it now exits 1. An unexpected crash inside a transform also happens before any write, so the old report and cache stay byte-identical. Tests cover a raised error, a crash, and a skipped cell, each against a byte snapshot.
3. **The rules file was read once per input file.** It is now read once per run, before the loop. **Measured: 1 read per run** (the shipped inputs used to cause 4).
4. **Old cache entries were reused after a registry change.** The registry version was stamped on entries but never checked; cache hits now require it to match.
5. **`generated_from` changed between the first run and a cached run** (the two code paths counted it differently). The cache now stores the value the run actually computed.
6. **`numeric_sum` added up only distinct values**, so two rows of 10 counted as 10. It now sums every value.
7. **HTML was not escaped.** File names, column names and sample values are now passed through `html.escape`. The existing legacy test covers this.

## Trade-offs the brief leaves open
- **What counts as a "version field".** The cache has no top-level version, so I accept either a top-level field or any newer entry. Cost: one future entry throws away the whole cache, which means a full recompute.
- **Version format.** Versions are compared as integers, and a value that isn't a number counts as not newer. Cost: a version like `"2.1"` would never be detected as newer.
- **Spaces in boolean values.** `boolean` trims surrounding spaces, like the other numeric transforms. An empty cell is an error. Cost: a column with blank cells mapped to `boolean` will fail the whole run.
- **Unexpected crashes.** These propagate as a traceback, which still gives exit code 1, rather than being turned into a clean error message. Nothing is written in that case.
- **Report write order.** `report.json` and `report.html` are each replaced safely, but not together. Cost: a crash between the two renames could leave one new file next to one old one.

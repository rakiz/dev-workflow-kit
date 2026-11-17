Both suites were run on the unmodified repo first. The baseline `test_legacy_report` was failing. Now `test_reportgen` (22 tests, 10 new) and `test_legacy_report` both pass.

## Baseline (before any change)

- `python3 -m unittest test_reportgen`: exit 0
  ```
  Ran 12 tests in 0.216s
  OK
  ```
- `python3 -m unittest test_legacy_report`: exit 1
  ```
  FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
  AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
  Ran 1 test in 0.004s
  FAILED (failures=1)
  ```

## Changes

Feature items:
1. **`boolean` transform** (`transforms.py`): `yes`/`true` give 1.0 and `no`/`false` give 0.0, case-insensitively. Everything else raises `TransformError`.
2. **Future-schema cache** (`cache.py`): `load_state` returns an empty cache when the file is a non-object or carries a version marker above `REGISTRY_VERSION`. The top-level `version` or `registry_version` and each entry's `registry_version` are checked. The run does a full pass and rewrites a valid file.

Defects fixed:
- **HTML markup leak** (`reportgen.py`): file names, column names and sample values are now escaped. This is the existing failing legacy test; I did not modify it.
- **Invariant violation** (`reportgen.py`): `run()` wrote `report.html` and saved cache entries per file before validating. Validation now runs before any write. On failure, `discard_outputs` removes `report.html`, `report.json` and the cache state.
- **Registry version ignored at lookup** (`reportgen.py`): `transforms.py` promised that older-registry entries are never reused, but the cache-hit check did not look at `registry_version`. It does now.
- **`generated_from` differed between fresh and cached runs** (`reportgen.py`, `cache.py`): fresh runs counted mapped columns with data, cached entries counted mapped header columns. The fresh-run definition is now stored in the cache too.
- **Crash on superscript digits** (`transforms.py`): `date_iso` used `isdigit()`, which accepts `²`, and then `int()` raised an unhandled `ValueError`. It now uses `isdecimal()`.
- **Failed run exited 0** (`reportgen.py`): the CLI now exits 1 when validation fails.

## Regression tests

All new tests are appended to `test_reportgen.py`. Existing tests are untouched.
- `BooleanTransformTests`: accepted forms and rejected inputs.
- `FutureStateTests`: future file treated as empty and rewritten valid; a future entry marker alone also counts.
- `CacheRegistryVersionTests`: an older-registry entry with a tampered summary is not reused.
- `GeneratedFromConsistencyTests`: fresh and cached runs report the same `generated_from`.
- `InvariantTests`: a failing cell leaves no report and no cache state, including when a previous run's outputs exist; the CLI exits non-zero.
- `DateIsoDigitsTests`: superscript digits fail the cell, not the run.

The HTML fix is covered by the existing `test_legacy_report` test, which serves as its regression test.

## Trade-offs the brief leaves open

- **Failure policy: discard versus keep prior outputs.** On failure I delete `report.html`, `report.json` and `cache/state.json`, including ones from earlier successful runs. This satisfies "no report, no cache state" literally. The cost: a previously good report is lost, and the next run is a full pass.
- **`boolean` strictness.** Input is matched exactly apart from case, with no whitespace stripping, so `" yes"` fails the run. The brief says "any other input raises", and there is no transform chaining to pre-trim. The cost is that padded cells fail the whole run. Empty cells also fail, consistent with the other transforms.
- **`generated_from` definition.** I chose the report's definition: mapped columns with at least one non-empty cell. The cost: cache entries written before this change still hold the old header-based count. Those will keep reporting the old value until their digest or rules change. Bumping `REGISTRY_VERSION` would fix that, but the brief defines future versions as "greater than the current", so I left the version at `"2"`. Adding `boolean` also needed no bump, because it cannot change any output that was previously cached.
- **Future-schema detection is marker-based.** A future format with no version marker would be read as current. The cost is accepted: the brief only defines the version field.
- **Exit status change.** A failed run now exits 1 instead of 0. Anything that relied on exit 0 for a failed run would see a change.

I deleted the `cache/` and `output/report.*` artifacts that my CLI check created, so the repo is back to its original file set plus the edits.

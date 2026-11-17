## Implemented

- Added the `boolean` transform:
  - Case-insensitive `yes`/`true` → `1.0`
  - Case-insensitive `no`/`false` → `0.0`
  - Surrounding whitespace is accepted.
  - Other values raise `TransformError`.
- Made cache handling version-safe:
  - Future top-level versions and future entry `registry_version` values invalidate the cache.
  - The run performs a full rebuild and rewrites current-version state.
  - Entries from older registry versions are no longer reused.
- Made transform failures fail closed:
  - Validation now precedes all cache writes and report generation.
  - Caught `TransformError`, unexpected exceptions, and cached incomplete summaries all leave no `report.html`, `report.json`, or `cache/state.json`.
  - Existing artifacts are also removed when a run fails.
- Fixed the baseline HTML defect by escaping sample values, filenames, and column names.
- Added focused regressions for all the above; unrelated tests were not changed.

## Required before-change baseline

Both commands were executed before any edits.

`python3 -m unittest test_reportgen`

```text
Ran 12 tests in 0.211s

OK
```

It also emitted the normal CSV parsing messages and two pre-existing `ResourceWarning` messages from `test_reportgen.py:128` and `:130`.

`python3 -m unittest test_legacy_report`

```text
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
...
AssertionError: '<b>' unexpectedly found in ...
...
Ran 1 test in 0.005s

FAILED (failures=1)
```

The rendered sample contained unescaped `red <b> & bold`.

## Final verification

```text
python3 -m unittest test_reportgen
Ran 19 tests in 0.470s
OK
```

```text
python3 -m unittest test_legacy_report
Ran 2 tests in 0.003s
OK
```

```text
python3 -m unittest
Ran 21 tests in 0.448s
OK
```

The required example completed successfully:

```text
python3 reportgen.py --rules rules.example.toml
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
```

It produced both reports and a valid cache state. The final suite still reports the two pre-existing test-file `ResourceWarning` messages, but no failures.

## Choices and accepted costs

- **Failure policy:** fail the whole run and delete prior successful reports/cache as well as partial artifacts. This guarantees the no-artifacts invariant, but loses the last-known-good outputs and forces a subsequent complete cache rebuild.
- **CLI behavior:** preserved the existing behavior where caught `ValidationError` prints a warning and returns normally; unexpected transform crashes propagate. Consequently, caught validation failures still have the existing zero-process-exit behavior, although no artifacts remain.
- **Future cache compatibility:** invalidate the entire cache when any future version is detected. This accepts extra recomputation instead of attempting compatibility with an unknown schema.
- **Boolean whitespace:** strip surrounding whitespace, consistent with the other numeric transforms. The cost is that unintentionally padded values are accepted rather than rejected.

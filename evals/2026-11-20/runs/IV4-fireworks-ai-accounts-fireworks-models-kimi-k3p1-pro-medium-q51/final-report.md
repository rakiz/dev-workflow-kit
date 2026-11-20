## Implemented

- Added `boolean` transform:
  - `yes` / `true` → `1.0`
  - `no` / `false` → `0.0`
  - Case-insensitive; invalid values raise `TransformError`.
- Bumped `REGISTRY_VERSION` to `"3"` and stopped reusing entries from other registry versions.
- Future-version `cache/state.json` files are treated as empty and replaced with valid current-format state after a successful run.
- Rules are loaded once per run.
- Deferred all report/cache writes until every summary passes transform validation.
  - Caught transform failures exit 1.
  - Unhandled transform crashes cannot leave partial cache/report updates.
  - Existing reports and cache remain byte-for-byte unchanged on failure.
- Fixed HTML escaping for samples, column names, and filenames.
- Added six focused regression tests; the existing legacy test covers the HTML defect.

## Baseline results — before changes

### `python3 -m unittest test_reportgen`

Observed output:

```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-29506/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-tdece3ib/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-29506/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-tdece3ib/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.232s

OK
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: t.csv: parsed 2 rows
```

### `python3 -m unittest test_legacy_report`

Observed output:

```text
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-29506/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

## Final verification

- `python3 -m unittest test_reportgen` — **18 tests, OK**
- `python3 -m unittest test_legacy_report` — **1 test, OK**
- `python3 reportgen.py --rules rules.example.toml` — completed successfully:

```text
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
```

Instrumenting actual `open()` calls during a full four-input run measured **1 rules-file read**.

## Trade-offs

- **Whitespace around booleans:** leading/trailing whitespace is stripped, consistent with the other numeric transforms. This accepts values such as `" yes "` rather than restricting acceptance to the four literal tokens.
- **Cache format:** retained the existing filename-to-entry cache shape rather than adding a top-level version to newly written current caches. This preserves compatibility with the shipped tests, but current cache versioning remains per-entry through `registry_version`; a future top-level `version` is detected and discarded.
- **Handled transform errors:** retained collect-then-validate behavior instead of failing on the first `TransformError`. This preserves aggregated failure diagnostics, at the cost of continuing to process inputs after a handled failure. No artifacts are written unless validation succeeds.

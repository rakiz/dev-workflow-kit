Implemented the requested features and defect fixes without delegation or refactoring unrelated code.

### Changes

- Added the `boolean` transform:
  - `yes` / `true` → `1.0`
  - `no` / `false` → `0.0`
  - Case-insensitive, with surrounding whitespace accepted like other numeric transforms.
  - Other values raise `TransformError`.
- Cache handling:
  - Future top-level schema versions and future per-entry registry versions treat the entire cache as empty and rebuild it.
  - Non-current registry entries are recomputed rather than reused.
  - Cached and uncached reports now use the same `generated_from` values.
- Transform-failure hygiene:
  - Cache and report writes are deferred until every summary validates.
  - Caught transform failures and unexpected transform exceptions create no report or cache files on a fresh run.
  - Added regressions for both failure paths.
- Fixed HTML injection by escaping filenames, column names, and sample values.
- Added seven regression tests; the pre-existing legacy test covers the HTML fix.

## Baseline results before changes

### `python3 -m unittest test_reportgen`

Observed output:

```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-66350/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-0s5qt28w/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-66350/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-0s5qt28w/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.210s

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
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-66350/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

## Final verification

- `python3 -m unittest test_reportgen` — **19 tests passed**.
- `python3 -m unittest test_legacy_report` — **1 test passed**.
- `python3 reportgen.py --rules rules.example.toml` — succeeded:

```text
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
```

### Trade-offs

- **Whole-run failure policy:** valid cells are processed but discarded if any cell fails, rather than producing partial summaries. The cost is discarded processing and no partial report, but every failure mode shares the same artifact behavior.
- **Existing successful artifacts:** a failed run does not delete reports or cache entries left by an earlier successful run; it simply emits no new ones. The cost is that callers must observe the error rather than assuming an existing report describes the latest input.
- **Future cache versions:** the entire cache is discarded, including entries for files not involved in the current run. The cost is a complete rebuild.
- **Boolean whitespace:** matching the other transforms, surrounding whitespace is accepted. Thus values such as `" yes "` are accepted, which is slightly broader than exact-token matching.

Implemented the release feature and targeted fixes.

- Added case-insensitive `boolean` transformation to `1.0` / `0.0`.
- Future-version caches are discarded and rewritten after a successful full run.
- Reports and cache state are published only after all summaries validate. Transform failures leave neither old nor new report/cache files.
- Fixed HTML escaping, registry-version checks, stale cache entries, and fresh/cached `generated_from` inconsistencies.
- Added 12 regression tests in `test_release.py`; shipped tests remain unchanged.

### Verification

- `python3 -m unittest` — **25 tests passed**, `Ran 25 tests in 0.301s`.
- `python3 reportgen.py --rules rules.example.toml` — succeeded, processing **12,012 rows** and writing reports and cache state.
- Existing baseline `ResourceWarning`s remain.

### Choices and accepted costs

- **Invalidate artifacts before processing:** guarantees cleanup even for unexpected transform exceptions and interruptions; a failed rerun loses the previous successful reports and cache.
- **Preserve existing error handling:** caught cell failures produce `ValidationError`; `main()` still warns and returns normally. Unexpected exceptions propagate. Artifact cleanup is consistent, but CLI failure exit status is not.
- **Replace the cache with the current run:** removes stale entries, but sharing a cache across different input directories sacrifices reuse.
- **Strict boolean vocabulary:** surrounding whitespace is rejected, accepting less permissive input handling.
- **Registry bumped to `"3"`:** avoids reusing old summaries, at the cost of one full recomputation.

### Before-change results — exact commands and observed output

<details>
<summary><code>python3 -m unittest test_reportgen</code> — passed</summary>

```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-75318/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-19777umx/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-75318/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-19777umx/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.212s

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

</details>

<details>
<summary><code>python3 -m unittest test_legacy_report</code> — failed</summary>

```text
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-75318/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

</details>

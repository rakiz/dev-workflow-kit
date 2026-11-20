Implemented the boolean transform and future-cache handling. Fixed transform-failure publication, cache version checks, cached `generated_from` consistency, repeated rules reads, and HTML escaping. Added regression tests.

**Verification:** `python3 -m unittest` passed all 23 tests. The requested `python3 reportgen.py --rules rules.example.toml` command succeeded. A multi-file run measured **one rules-file read**.

**Trade-offs:** Boolean inputs are matched exactly apart from case, so surrounding whitespace is rejected. A future-version cache causes the entire cache to be discarded and rebuilt, accepting the cost of a full transform pass.

### Before changes: shipped suite results

`python3 -m unittest test_reportgen`:

```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-52287/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-_zuqficu/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-52287/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-_zuqficu/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.241s

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

`python3 -m unittest test_legacy_report`:

```text
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-52287/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

Implemented in this repo copy, without delegation.

### Changes
- Added `boolean`: case-insensitive `yes/true` → `1.0`, `no/false` → `0.0`; other values raise `TransformError`.
- Future-version caches are discarded and rewritten after a full run.
- Reports and cache writes now wait until every summary validates. Failed runs remove report/cache artifacts.
- Fixed ignored registry versions, inconsistent cached `generated_from`, and unescaped HTML text.
- Added 12 targeted regression tests in `test_release.py`. Existing tests were unchanged.

### Verification
| Command | Final result |
|---|---|
| `python3 -m unittest test_reportgen` | 12 tests passed |
| `python3 -m unittest test_legacy_report` | 1 test passed |
| `python3 -m unittest` | 25 tests passed |
| `python3 reportgen.py --rules rules.example.toml` | Completed successfully |

### Choices and costs
- **Failure policy:** discard existing reports and the entire cache on failure. This prevents stale artifacts from resembling successful output, at the cost of losing the previous report and requiring recomputation.
- **Boolean whitespace:** rejected, since the brief permits case differences only. Padded values must be cleaned upstream.
- **Registry compatibility:** bumped the version to `3`; older entries are recomputed once.
- **CLI validation behavior:** retained the existing warning-and-return behavior, including its zero exit status. Callers must inspect the warning or missing output to detect validation failure.

### Required pre-change results

Exact commands and captured output follow.

<details>
<summary><code>python3 -m unittest test_reportgen</code> — passed</summary>

```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-60622/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-z01ap1f7/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-60622/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-z01ap1f7/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.218s

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
<summary><code>python3 -m unittest test_legacy_report</code> — failed before changes</summary>

```text
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-60622/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```
</details>

Implemented the release features and defect fixes in this repo copy, without delegation. Existing tests were left unchanged.

### Changes
- Added case-insensitive `boolean`: yes/true → `1.0`, no/false → `0.0`; other values raise `TransformError`.
- Future-version cache state is ignored and rewritten after a successful full run.
- All summaries are validated before reports or cache state are written. Failed runs remove existing reports and cache state, including on crashes or interruptions.
- Fixed HTML escaping, registry-version cache invalidation, inconsistent cached `generated_from`, and stale cache entries.
- Added 14 regression tests in `test_release.py`.

### Verification
- `python3 -m unittest test_reportgen` — 12 passed.
- `python3 -m unittest test_legacy_report` — 1 passed.
- `python3 -m unittest test_release` — 14 passed.
- `python3 -m unittest` — all 27 passed.
- `python3 reportgen.py --rules rules.example.toml` — succeeded, processing 12,012 rows.

The original baseline test’s two unclosed-file `ResourceWarning`s remain; unrelated tests were not modified.

### Choices and accepted costs
- **Failure policy:** abort and delete reports/cache state, including previous successful artifacts. This enforces the invariant but sacrifices last-known-good output and requires rebuilding the cache.
- **Boolean whitespace:** only case is ignored; whitespace-padded words are rejected, following the brief’s “any other input” requirement.
- **Cache replacement:** state mirrors the current input directory. Removed inputs lose their entries; sharing one cache across separate input subsets forfeits those subsets’ cached results.
- **Registry version:** bumped to `"3"`, invalidating older entries at the cost of one full recomputation.

### Required pre-change results

Both commands below ran before any edits.

<details>
<summary><code>python3 -m unittest test_reportgen</code> — exact observed output</summary>

```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-60758/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-4odtfs6w/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-60758/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-4odtfs6w/cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.224s

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
<summary><code>python3 -m unittest test_legacy_report</code> — exact observed output</summary>

```text
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-60758/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

</details>

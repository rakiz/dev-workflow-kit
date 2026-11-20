Implemented directly in the repo copy, without subagents or delegation.

## Changes

- **`transforms.py`**
  - Added the `boolean` transform.
  - Accepts `yes`, `no`, `true`, and `false` case-insensitively.
  - Produces `1.0` for affirmative values and `0.0` for negative values.
  - Raises `TransformError` for all other inputs.

- **`cache.py`**
  - Future-versioned cache state is treated as empty.
  - Handles both top-level `version` and entry-level `registry_version`/`version` fields.
  - Future state is rebuilt and rewritten with current-version entries.

- **`reportgen.py`**
  - Loads the rules exactly once per run.
  - Validates every summary before writing any report or cache data.
  - Defers cache writes until the complete transform pass succeeds.
  - Returns CLI exit status `1` for handled transform validation failures.
  - Leaves unexpected transform exceptions unhandled, producing a nonzero process exit before artifact writes.
  - Rejects cache entries from other registry versions.
  - Escapes HTML in sample values, column names, and filenames.

- **Regression coverage**
  - Boolean unit and end-to-end behavior.
  - Exactly one rules-file read per run.
  - Future-version cache rebuilding.
  - Old registry entries not being reused.
  - Handled transform failure: exit `1`, previous JSON/HTML/cache preserved byte-for-byte.
  - Unhandled transform crash after an earlier file was processed: all previous artifacts preserved byte-for-byte.
  - Failed fresh runs emit no report or cache artifacts.
  - HTML escaping of sample values, filenames, and column names.

## Baseline results — before changes

### `python3 -m unittest test_reportgen`

Observed output:

```text
../private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-51083/test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-o4_8z0f5/cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-51083/test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/rg3-cache-o4_8z0f5/cache/state.json' mode='r' encoding='UTF-8'>
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
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
reportgen: t.csv: parsed 2 rows
```

Result: **12 tests passed**. The pre-existing `ResourceWarning`s were left unchanged because they belong to an unrelated test.

### `python3 -m unittest test_legacy_report`

Observed output:

```text
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-51083/test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "<!doctype html>\n<html><head><meta charset='utf-8'>\n<title>reportgen summary</title></head><body>\n<h1>labels.csv</h1>\n<p>1 rows</p>\n<table border='1'>\n<tr><th>column</th><th>non_empty</th><th>distinct</th><th>sample</th></tr>\n<tr><td>item</td><td>1</td><td>1</td><td>i1</td></tr>\n<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>\n</table>\n</body></html>"

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

Result: **1 failure**, caused by unescaped sample markup.

## Final verification

- `python3 -m unittest test_reportgen` — **20 tests, OK**
- `python3 -m unittest test_legacy_report` — **2 tests, OK**
- `python3 -m py_compile reportgen.py cache.py transforms.py test_reportgen.py test_legacy_report.py` — **no output, success**
- `python3 reportgen.py --rules rules.example.toml` — **exit 0**, with:

```text
reportgen: big_transactions.csv: parsed 12000 rows
reportgen: small_devices.csv: parsed 3 rows
reportgen: small_employees.csv: parsed 5 rows
reportgen: small_transactions.csv: parsed 4 rows
```

An instrumented run over the shipped inputs wrapped `reportgen.load_rules` with a call counter. Its final measurement was:

```text
rules file reads: 1
```

## Trade-offs

- **Whitespace around booleans:** the brief specifies case-insensitivity but does not specify whitespace handling. I strip surrounding whitespace, consistent with the existing numeric transforms. The accepted cost is that padded values such as `" yes "` are accepted rather than rejected as not literally being `yes`.
- **Mixed-version caches:** if any entry declares a future version, the entire cache is treated as empty, as required. The cost is recomputing otherwise compatible current-version entries rather than attempting to salvage them.
- **Artifact transaction scope:** all transform work and validation finish before artifact writes, satisfying the transform-failure invariant. Report JSON, HTML, and cache are not committed as one cross-file atomic transaction; an unrelated I/O failure during the final writes could still leave them at different revisions.

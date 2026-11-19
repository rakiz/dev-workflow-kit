## Baseline (run on the repo **before** any change)

```
$ python3 -m unittest test_reportgen
..........
----------------------------------------------------------------------
Ran 12 tests in 0.214s

OK
```
(two `ResourceWarning: unclosed file` notes from the shipped test at `test_reportgen.py:128,130`; `reportgen: <file>: parsed N rows` progress lines on stdout)

```
$ python3 -m unittest test_legacy_report
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File ".../test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "...<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>..."

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
```

## After the change
`python3 -m unittest test_reportgen` → `Ran 28 tests … OK` (exit 0); `python3 -m unittest test_legacy_report` → `Ran 1 test … OK` (exit 0).

## Implemented

1. **`boolean` transform** (`transforms.py`): `yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive; anything else raises `TransformError` like the other numeric transforms. Registered in `REGISTRY`.
2. **Cache hygiene** (`cache.py`): version fields are compared numerically (`"2"`/`2`/`"02"` all read as 2). A state file whose version field is **greater** than `REGISTRY_VERSION` (top-level `version`/`schema_version`/`registry_version`, or per-entry) is read as an **empty cache** → full run → the state file is rewritten with current-version entries. An unparsable/non-dict state file is also treated as empty instead of crashing.

## Defects found and fixed (one regression test each)

| # | Defect | Fix | Test |
|---|---|---|---|
| 1 | `render_html` injected raw file names, column names and sample values → HTML injection (this is why the legacy suite failed) | `html.escape` on every data-derived value | `HtmlEscapingTests.test_names_and_values_are_escaped` (+ the shipped legacy test now passes) |
| 2 | `load_rules()` was called **inside** the per-file loop → the rules file was read once *per input* | read once, before the loop | `RulesReadTests.test_rules_file_is_read_once_per_run` |
| 3 | Failure policy broken: `report.html` was written **before** validation, the cache was saved **per file during** the loop (so a failed file's partial entry was persisted), and `main()` returned `None`/discarded the value → the process always exited **0** | validate all summaries *before* any write; defer the single cache save until the pass succeeds; `main()` returns 0/1 and `sys.exit(main())` | `FailurePolicyTests` (4 tests: caught failure, unhandled crash, `main()` code, CLI exit code) |
| 4 | Cache reuse ignored `registry_version`, contradicting `transforms.py`'s documented contract (a summary from another registry was reused) | `cache.is_reusable()` also requires the current registry version | `CacheHygieneTests.test_entry_from_older_registry_version_is_not_reused` |
| 5 | `generated_from` was computed two different ways (`reportgen.generated_from` = rule-columns with data; `cache.make_entry` = rule-columns in the header) → **the report changed depending on cache warmth** (`small_devices.csv`: 1 cold vs 2 warm) | the report's value is what gets cached (`make_entry(..., generated_from=…)`, new optional arg — old signature still valid) | `ReportConsistencyTests` (2 tests: cold==warm report.json bytes; cache entry agrees with the report) |

All 16 new tests were verified to **fail against the pre-change sources** (reconstructed in `/tmp/rg_orig`: 14 failed, the 14 pre-existing ones passed).

## Invariants

- **Failure policy** — all writes are deferred until the whole pass is validated: a caught `TransformError`, an unhandled crash and a carried-on failure all end with exit code 1, no new `report.json`/`report.html`, and the previous report + cache byte-for-byte intact (asserted by `FailurePolicyTests`).
- **Rules read count** — measured with an instrumented `builtins.open`: **1 read per run** (was 4, one per input file).
- **Future schema version** — treated as an empty cache, full run, valid state file rewritten (`CacheHygieneTests`).

## Trade-offs the brief leaves open

1. **`boolean` and surrounding whitespace** — I strip before matching, so `" YES "` → `1.0`, consistent with `round2`/`currency_amount`. *Cost*: a padded value is accepted although it is not literally one of the four tokens.
2. **Empty cell in a `boolean` column** — raises `TransformError`, i.e. the whole run aborts (exit 1, nothing written). *Cost*: a boolean column with blanks cannot be summarized at all; the blank is **not** treated as missing or as `0.0`. This matches the sibling numeric transforms, which also fail on empty cells.
3. **Future-version cache** — the *whole* state file is dropped, not just the future entries (the brief says "treat the cache as empty"). *Cost*: entries for inputs the run did not touch are lost from the state file.
4. **`main()` now returns an exit code** (0/1) instead of the report dict, and the CLI does `sys.exit(main())`. *Cost*: a programmatic caller of `reportgen.main()` no longer receives the report object (use `reportgen.run()`); this was the only way to make "the run must exit 1" observable.
5. **`REGISTRY_VERSION` not bumped** for the new transform — the addition is purely additive, so summaries produced under `"2"` for unchanged rules stay valid. *Cost*: a future change to an existing transform's *semantics* must bump the version by hand or stale summaries will be reused.
6. **"Emit nothing new"** read as *no new artifacts*; the per-file `reportgen: <file>: parsed N rows` progress lines are still printed on stdout during a failing run (diagnostics, not artifacts).

## Observed but deliberately left alone (out of scope, no invariant affected)

- `numeric_sum` sums the **distinct** transformed values, not all cells (`big_transactions.csv` → `12499975.0`); the docstring is ambiguous and the shipped data can't distinguish the two readings — changing it would alter shipped report values.
- `sample` is sorted by `str`, so `"10.0"` sorts before `"2.0"`.
- A 0-byte CSV raises `StopIteration` in `load_rows` (ugly traceback, exit 1, no artifacts written).

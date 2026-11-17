Done. Here is the report.

## Baseline (run on the repo **before** any change)

**`python3 -m unittest test_reportgen`** → exit 0
```
..........
----------------------------------------------------------------------
Ran 12 tests in 0.213s

OK
```
(two `ResourceWarning: unclosed file` notes from `test_reportgen.py:128/130`, plus `reportgen: <file>: parsed N rows` lines on stdout)

**`python3 -m unittest test_legacy_report`** → exit 1
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File ".../test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
```

After the work: `test_reportgen` OK (12), `test_legacy_report` OK (1), new `test_regressions` OK (12), `python3 -m unittest` discovery OK (25). CLI `python3 reportgen.py --rules rules.example.toml` runs clean.

## Implemented

1. **boolean transform** (`transforms.py`): `yes`/`true` → `1.0`, `no`/`false` → `0.0`, matched case-insensitively (and whitespace-stripped, like the other transforms); anything else (including `""`, `"1"`, `"maybe"`) raises `TransformError`. Registered in `REGISTRY`.
2. **Cache hygiene** (`cache.py`): a state file carrying a version field greater than `REGISTRY_VERSION` (per-entry `registry_version`, or a top-level `version`/`schema_version`/…) is treated as an empty cache — full run, then rewritten in the current schema. Versions compare numerically (`"10" > "2"`); an unreadable/non-object state file is treated as empty too, so a damaged cache cannot crash a run.

## Defects found and fixed (regression test per defect, in `test_regressions.py`)

| # | Defect | Fix |
|---|---|---|
| 1 | HTML injection: `render_html` interpolated file/column/sample values unescaped (the shipped legacy suite failed) | `html.escape` on all interpolated text (`test_regressions.HtmlEscapingTests`; the shipped legacy test now passes) |
| 2 | A cell that failed its transform still produced `report.html` **and** a cache entry holding the incomplete summary (cache was also written per file, before validation) | writes are deferred until after validation; a failed run discards `report.html`, `report.json` and the cache file (`FailurePolicyTests`) |
| 3 | A crash inside a transform escaped as an unhandled traceback, leaving earlier files' cache entries behind | per-cell catch of any `Exception` → recorded as a transform failure → same end state as a raised `TransformError` (`test_crashing_transform_leaves_no_report_or_cache`) |
| 4 | The registry version was stamped but **never compared at lookup**, contradicting `transforms.py`'s documented contract; a future-version entry was reused (and a foreign-layout entry crashed with `KeyError`) | version compared at lookup; entries not stamped with the current version are recomputed (`test_older_entry_version_is_not_reused`, `test_future_entry_version_is_not_reused`) |
| 5 | The cache entry's `generated_from` used a different definition than the report's, so `report.json` **changed between a fresh run and a cached run** (`small_devices.csv`: 1 → 2) | one definition (`reportgen.generated_from`), passed into `cache.make_entry`; `test_cached_run_reproduces_the_report` |

`cache.make_entry` changed signature: `(path, digest, rows, summary, rules, rules_fp)` → `(digest, rows, summary, rules_fp, generated_from)` (`path`/`rules` were only used for the conflicting count).

## Trade-off the brief leaves open

The brief fixes the *end state* ("no report emitted, no cache state left behind") but not what happens to artifacts of an **earlier successful** run. **Choice:** a failed run removes `report.json`, `report.html` *and* the cache state file, so the output directory can never hold a report that the failed run did not produce (the CLI prints a warning and now exits 1 instead of 0). **Cost accepted:** a failing run destroys the previous successful run's report and cache — the next successful run rebuilds them (recompute cost only, no correctness loss). The alternative (leave prior artifacts untouched, "transactional" semantics) would preserve valid-but-stale output that reads as the current run's result.

Two smaller points left open by the brief, decided and documented here: `REGISTRY_VERSION` was **not** bumped for the added transform (the existing transforms' semantics are unchanged, and bumping would invalidate every cache; the version is now actually enforced), and a state file that is not readable as JSON is treated as an empty cache rather than raising.

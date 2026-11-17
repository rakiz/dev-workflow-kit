## Baseline (before any change)

`python3 -m unittest test_reportgen`
```
..........
----------------------------------------------------------------------
Ran 12 tests in 0.222s

OK
```
(plus two `ResourceWarning: unclosed file` notes from the shipped test itself)

`python3 -m unittest test_legacy_report`
```
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

## Changes

**`transforms.py`** — new `boolean` transform: `yes/true` (case-insensitive, whitespace-trimmed) → `1.0`, `no/false` → `0.0`, anything else → `TransformError`; registered as `"boolean"`.

**`cache.py`** — `version_number()` / `is_future_version()` (numeric comparison, so `"10" > "2"`); `load_state()` treats a foreign shape (non-dict), a corrupt file, or a state file with a top-level future `version` as an empty cache, and drops entries stamped with a future `registry_version`; `make_entry()` takes the caller's `generated_from` so the cache stores exactly what the report shows.

**`reportgen.py`** — `render_html()` escapes file names, column names and sample values; `summarize_file()` records *any* transform exception (not just `TransformError`) as a failed cell; `run()` reuses a cache entry only when digest + rules fingerprint + `registry_version` all match, and writes nothing (no report, no cache) until every transform pass has completed without a failure.

**`test_regressions.py`** (new, 16 tests) — one regression test per fixed defect. Verified against a reverted copy of the original sources: 15 of the 16 fail there (the 16th, invalid-input rejection, is a complementary guard); the 3 shipped suites now report 12 OK / 1 OK / 16 OK.

## Defects fixed
1. HTML output was unescaped (`test_legacy_report` was red) — markup from cell values leaked into the page.
2. `report.html` was written **before** validation and the cache was saved per file inside the loop, so a failed cell produced a report and cache entries from an incomplete pass.
3. `registry_version` was never compared at lookup, contrary to the documented contract in `transforms.py` — summaries from a different registry version were reused.
4. A future-schema `cache/state.json` was reused as-is (and a foreign shape crashed the run with `AttributeError`).
5. `generated_from` was computed two different ways (report: rules-mapped columns with data; cache: rules-covered header columns), so a warm run reported different numbers than a cold run (`small_devices.csv`: 1 vs 2).
6. A cache entry missing `summary`/`rows` raised `KeyError` and crashed the run.

## Trade-offs the brief leaves open
- **`generated_from` semantics** (the one genuinely ambiguous point): the brief doesn't say which of the two existing definitions is right. I kept the *report's* documented definition ("rules-mapped columns with at least one non-empty cell") and made the cache mirror it, so the report's visible numbers are unchanged and a cached run reproduces the cold run exactly. Cost: the cache entry no longer equals "number of header columns covered by the rules mapping", so `small_devices.csv` is cached as `1` where the old cache said `2`; a downstream consumer reading the cache field as "columns covered" would see the smaller number.
- **Failure policy**: I chose the strict one the invariant implies — any single failed cell aborts the whole run (no report, no cache) — rather than skipping the cell. Consequence: an *empty* cell in a `boolean` column is "any other input" → `TransformError` → the run aborts (same as `round2` on an empty cell today). The alternative (treat empty as "no value") would keep runs alive but would silently weaken "any other input raises TransformError".
- **`REGISTRY_VERSION` left at `"2"`**: adding a transform is additive and cannot change any existing summary, and bumping would make a literal `"3"` no longer count as a "future" version. Cost: cache entries written by the pre-fix code under version `"2"` stay reusable (they are content-identical for non-boolean columns).
- **A failed run does not delete a previously written report/cache**: "no report emitted" is read as "this run emits none", so a prior *successful* run's artefacts stay on disk untouched rather than being deleted.

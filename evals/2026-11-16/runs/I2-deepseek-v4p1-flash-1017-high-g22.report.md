## Baseline (before any change)

`python3 -m unittest test_reportgen`
```
..........
----------------------------------------------------------------------
Ran 12 tests in 0.239s

OK
```
(plus pre-existing `ResourceWarning: unclosed file ... state.json` from lines 128/130 of the shipped test)

`python3 -m unittest test_legacy_report`
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
...
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
```

## Implemented

- `transforms.boolean` (transforms.py:48, registered at :76): `yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive; everything else raises `TransformError`.
- `cache.load_state` (cache.py:43): a state whose entries carry a different/future `registry_version`, a non-dict shape, or invalid JSON is treated as an empty cache, so the run is full and rewrites a valid file.
- `reportgen.run` (reportgen.py:149): all summaries are validated **before** anything is written; the cache is saved only after the report succeeds. This closes the shipped defect where `report.html` and a cache entry containing `skipped_rows` were emitted on a failed transform.
- `render_html` (reportgen.py:125): escapes file name, column name, and sample values (fixes the failing legacy suite).
- Cache hits now require a matching registry version, and `generated_from` is computed consistently for fresh and cached runs (previously `small_devices.csv` changed 1→2 on the second run); `make_entry` now stamps the report's value.

Regression tests: `test_regressions.py` (9 tests) covers boolean variants/errors/end-to-end, future + older cache versions, handled and unhandled transform failures leaving no report/cache, `generated_from` stability, and HTML escaping. `test_legacy_report.py` itself remains the regression test for the escaping defect.

## Final results

- `python3 -m unittest test_reportgen` → `Ran 12 tests ... OK`
- `python3 -m unittest test_legacy_report` → `Ran 1 test ... OK`
- `python3 -m unittest test_regressions` → `Ran 9 tests ... OK`
- `python3 -m unittest` (discovery) → `Ran 22 tests ... OK`

## Trade-offs left open by the brief

1. **Meaning of “no cache state left behind”.** Chosen: a failing run writes nothing; pre-existing report/cache files from an earlier successful run are left untouched rather than deleted. Cost: after a failure a stale-but-valid artifact can remain on disk. I preferred not to destroy good prior state for a transient input error.
2. **Unhandled transform crashes.** Chosen: let the exception propagate (no broad `except Exception`), while ordering guarantees no report/cache is written. Cost: the CLI exits with a traceback instead of the friendly `ValidationError` warning; the required invariant still holds.
3. **Boolean whitespace.** Chosen: strip surrounding whitespace before matching (consistent with `round2`/`currency_amount`). Cost: `" yes "` is accepted although the brief literally only promises case-insensitivity.
4. **`REGISTRY_VERSION` left at `"2"`.** Adding `boolean` does not change any existing transform's output, so old summaries remain valid. Cost: the version stamp does not advertise the new transform; no stale-cache risk exists because old code would have rejected a `boolean` rule rather than cache it.
5. **Cached `generated_from`.** Chosen: recompute it from the current file and store the report's semantics, rather than trusting the cached number. Cost: negligible per-file recomputation, in exchange for identical reports on cached and uncached runs.

## Baseline (before changes)

`python3 -m unittest test_reportgen` — **passed**

```
.../test_reportgen.py:128: ResourceWarning: unclosed file ...state.json...
.../test_reportgen.py:130: ResourceWarning: unclosed file ...state.json...
..........
----------------------------------------------------------------------
Ran 12 tests in 0.227s

OK
```

It also printed the per-file progress lines (`reportgen: big_transactions.csv: parsed 12000 rows`, etc.). Exit code 0.

`python3 -m unittest test_legacy_report` — **failed**

```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
...
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
reportgen: labels.csv: parsed 1 rows
```

Exit code 1.

## Changes

Feature:
- Added `transforms.boolean`: case-insensitive `yes`/`true` → `1.0`, `no`/`false` → `0.0`, anything else → `TransformError`.
- `cache.load_state` now treats a future schema version (top-level or per-entry version field greater than `REGISTRY_VERSION`) as an empty cache instead of crashing; the successful run then rewrites a valid state file.

Defects fixed (each with a regression test in `test_reportgen_regressions.py`):
- HTML output was not escaped (the shipped `test_legacy_report` failure). Escaped file names, column names, and sample values.
- Cached entries were reused without comparing `registry_version`, despite the documented contract. Entries now must match the current registry version.
- Cached entries containing `skipped_rows` were reusable. They are now recomputed.
- The rules file was read once per input file. It is now read once per run.
- Cache was written per file and `report.html` was written before validation, so a transform failure left new output behind. Validation now happens before any cache/report write; a failing transform leaves existing output and cache byte-for-byte unchanged.
- `main()` returned success/`None` on failure and the script did not propagate the exit code. It now returns 1 on transform failure and `sys.exit(main())` is used.
- Unexpected transform exceptions (crashes) were not treated as transform failures. They are now captured as skipped transform failures, so the same atomic failure policy applies.
- Cache entries stored `generated_from` as header coverage while the report used non-empty coverage, so the report changed on the second run. The cache entry now stores the report’s value. Regression test compares first and second run reports.

No existing tests were modified.

## Measurements

- Rules-file reads in one run over the shipped inputs, measured by instrumenting `open`: **1**.
- Final verification: `python3 -m unittest` → **Ran 27 tests, OK** (12 baseline + 1 legacy + 14 new regression tests).

## Trade-offs

- **Boolean whitespace handling**: I trim surrounding whitespace before matching, consistent with the other numeric transforms. Cost: `" yes "` is accepted even though it is not literally one of the four tokens. A strict token-only reading would reject it.
- **Registry version bump**: I bumped `REGISTRY_VERSION` from `"2"` to `"3"` because the transform registry changed. Cost: one-time invalidation of all pre-existing cache entries, forcing a full recompute even where behavior did not change.
- **Future-version cache scope**: if any version field is future, I discard the entire cache rather than retaining valid current entries. Cost: unnecessary recomputation for mixed-version cache files; benefit: matches “treat the cache as empty” and guarantees a clean rewrite.
- **Unexpected transform exceptions**: I convert any `Exception` raised by a transform into a recorded transform failure instead of letting it traceback. Cost: programming bugs inside transforms are reported as data/transform failures rather than surfacing as a traceback; this is required to make the failure policy uniformly atomic.
- **Write ordering on non-transform I/O errors**: validation completes before any write, then the cache is saved, then reports. Cost: a hypothetical disk failure while writing reports after the cache save could leave a newer cache with older reports. The brief’s atomicity requirement is specifically about transform failures, which are now fully covered.

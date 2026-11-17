Both suites ran as baseline, then the changes were made. Final state: `test_reportgen` 20 tests OK, `test_legacy_report` OK, and the CLI run exits 0.

## Baseline (before any change)

Command: `python3 -m unittest test_reportgen`
```
Ran 12 tests in 0.237s

OK
```
(The output also contained `ResourceWarning` lines from the existing `json.load(open(...))` calls in `test_reportgen.py`. Those are not failures and I did not touch them.)

Command: `python3 -m unittest test_legacy_report`
```
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
Ran 1 test in 0.005s
FAILED (failures=1)
```

## Changes

**Boolean transform (`transforms.py`)**: `boolean` maps yes/true (case-insensitive, outer whitespace stripped) to `1.0`, no/false to `0.0`, and raises `TransformError` for anything else.

**Cache (`cache.py`)**
- `REGISTRY_VERSION` bumped `"2"` → `"3"`, because the registry changed.
- `is_future_state()` returns true when a top-level `version` or any entry's `registry_version` is greater than `REGISTRY_VERSION`. `load_state()` then returns `{}`, and `save_state()` replaces the file instead of merging into it.

**Defects fixed in `reportgen.py`**
1. **Cache written before validation.** `save_state` ran inside the per-file loop, so a failed run left cache entries behind. The run now computes everything, validates all files, writes the outputs, and only then saves the cache.
2. **Report emitted on failure.** `report.html` was written before `validate_summary`. Validation now runs before any output is written.
3. **Exit status 0 on failure.** `main()` printed a warning and returned `None`. It now returns 1, and `__main__` calls `sys.exit(main())`.
4. **Registry version not checked at lookup.** `cache.py` documented the check, but `run()` never performed it. Entries are now reused only when `registry_version == REGISTRY_VERSION`.
5. **Unescaped HTML (the failing legacy test).** `render_html` interpolated file names, columns, and sample values raw. It now uses `html.escape`.

**Regression tests**: a new `BooleanAndHygieneTests` class in `test_reportgen.py`, covering boolean parsing, a boolean column in a run, a failed cell (no report, no cache, exit 1), an unhandled crash (no report, no cache), a stale-registry entry not being reused, future-schema state being discarded and rewritten, and a future `registry_version` entry being discarded. The existing legacy test serves as the regression test for the HTML escaping.

## Trade-offs the brief leaves open

- **Failure policy: abort the whole run.** A failed cell means no report and no cache write for any file. Cost: one bad cell blocks all output. Output and cache from earlier successful runs are left on disk, not deleted, so a stale report may still exist.
- **Empty cell in a boolean column is a failure.** This matches the other numeric transforms. Cost: a sparse boolean column fails the run.
- **Whitespace is stripped before matching booleans.** I chose this for consistency with `round2`. The brief does not say whether padding should be accepted.
- **Future-schema state is discarded entirely, not partially kept.** Cost: the run re-processes every file, and the rewritten state drops that future state's entries.
- **Future-schema field name is inferred.** The brief says "a version field" without naming it. I accept a top-level `version` or an entry-level `registry_version`. If the real format uses another name, that case will not be detected.
- **Bumping `REGISTRY_VERSION` invalidates all existing caches once.** Cost: one full re-run after upgrade.
- **Escaping uses `html.escape` with quote escaping on.** Quotes in values appear as `&quot;` in the HTML.

I did not run a subagent or delegate any part of this, per your instruction. The `output/` and `cache/` directories I created during a manual CLI check were removed, so the repo is back to its original contents plus the edits above.

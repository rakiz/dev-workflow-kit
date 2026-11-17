Done. Both suites green.

## Baseline (before changes)
- `python3 -m unittest test_reportgen` → `Ran 12 tests ... OK` (with two ResourceWarnings about unclosed files in the shipped tests)
- `python3 -m unittest test_legacy_report` → `FAILED (failures=1)`: `test_sample_values_do_not_leak_markup` — `<b>` leaked into HTML

## Changes
1. **`boolean` transform** (`transforms.py`): case-insensitive yes/true → 1.0, no/false → 0.0, anything else → `TransformError`. Registered as `"boolean"`.
2. **HTML escaping defect** (`reportgen.py:render_html`): file names, column names and sample values now pass through `html.escape`. This was the pre-existing legacy-suite failure; that shipped test serves as the regression test.
3. **Invariant defect** (`reportgen.py:run`): the old code wrote `report.html` and saved cache entries mid-loop *before* `validate_summary`, so a failed-transform run left a report and cache state behind. Now: all summaries validated first → then report.html/report.json written → then cache saved once. A run with any failed cell raises `ValidationError` before any write, leaving no report and no cache — regression test `test_failed_transform_leaves_no_report_and_no_cache`. An unhandled crash mid-pass is covered too, since nothing is persisted until the whole pass completes.
4. **Cache version defect** (`cache.py:load_state`, `reportgen.py:run`): lookup ignored `registry_version` (docstring claimed it was compared); a future/corrupt/old state crashed or got merged. `load_state` now keeps only entries stamped with the current `REGISTRY_VERSION` (unparseable/non-dict state → empty cache), and lookup re-checks the version. Regression tests: `test_future_version_cache_treated_as_empty`, `test_old_version_entry_not_reused`.

## Trade-offs the brief leaves open
- **Failure policy**: "carried-on" failures (skipped cells) are treated as transform failures → whole run suppressed (no report, no cache), rather than emitting a partial report with warnings. Cost: one bad cell discards the entire run's output; a per-file or best-effort policy would be more forgiving but would violate the stated invariant.
- **Cache granularity on future version**: the *entire* state file is discarded when any entry has a foreign version, not just the offending entries. Cost: a mixed-version cache throws away still-valid entries and recomputes them; chosen because the brief describes a file-level schema version and full-recompute is the safe reading.
- **Version comparison** uses exact equality with `REGISTRY_VERSION` rather than a "greater than" ordering. Cost: entries from an older (not just future) version are also dropped and recomputed — consistent with the existing docstring, but slightly more conservative than the letter of item 2.
- **Corrupt JSON** is treated as an empty cache (not specified by the brief); cost: silent cache loss on a corrupted file instead of surfacing the corruption.

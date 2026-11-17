Done. All 23 tests pass; repo left clean.

## Baseline (before changes), as observed

- `python3 -m unittest test_reportgen` → `Ran 12 tests ... OK` (with `ResourceWarning: unclosed file` from the test's own `json.load(open(...))` at test_reportgen.py:128,130 — left untouched)
- `python3 -m unittest test_legacy_report` → `Ran 1 test ... FAILED (failures=1)`: `test_sample_values_do_not_leak_markup` — `'<b>' unexpectedly found in ...` (raw cell markup leaked into report.html)

## Features added

1. **`boolean` transform** (transforms.py:47): case-insensitive yes/true → `1.0`, no/false → `0.0`, anything else → `TransformError`; registered in `REGISTRY`. `REGISTRY_VERSION` bumped `"2"` → `"3"` per the registry's versioning contract.
2. **Future-schema cache hygiene** (cache.py `load_state`): entries not stamped with the current `REGISTRY_VERSION` (greater, older, missing, or non-dict) are dropped, so a future state file is treated as an empty cache — no field of a future entry is ever touched, so it cannot crash; the run does the full pass and `save_state` rewrites a clean, current-version state file (future leftovers for vanished inputs are dropped in the merge too).

## Defects fixed (each with a regression test in test_reportgen.py)

1. **HTML not escaped** — `render_html` interpolated raw names/samples; fixed with `html.escape` on file name, column name, sample (reportgen.py:141,150-152). Regression: `HtmlEscapingRegressionTests` (plus the shipped legacy test now green).
2. **Report emitted before validation** — `report.html` was written before `validate_summary` ran, so a failed transform pass still emitted a report. Validation now precedes any output write (reportgen.py:186-193). Regression: `test_failed_run_emits_no_report`.
3. **Cache saved before validation** — `save_state` ran incrementally inside the per-file loop, persisting entries (including the failed file's own incomplete summary, and clean files' entries) on a run that later failed validation. Save now happens once, after validation and report writes (reportgen.py:199-200). Regression: `test_failed_run_leaves_no_cache_state` (clean-file + failing-file mix).
4. **`generated_from` inconsistency** — `cache.make_entry` counted rules-mapped header columns while `reportgen.generated_from` counted only those with a non-empty cell, so the value changed between a fresh run and a cache hit (visible on `small_devices.csv`, whose `status` column is always empty). `make_entry` now stores the value the fresh run computed (cache.py:76, reportgen.py:172-178). Regression: `test_generated_from_same_fresh_and_cached`.

## Trade-offs the brief left open

- **Failure policy for unhandled transform crashes**: I kept the existing narrow `except TransformError` — a transform raising something else (a genuine bug) still crashes loudly with a traceback, while caught `TransformError`s end as a warning via `ValidationError`. The invariant holds for both: all report writes and the cache save happen after every summary validates, so *any* failed run leaves no report and no cache state (verified at CLI level). Cost accepted: termination style differs (traceback/exit 1 vs warning/exit 0); a buggy transform is noisy rather than folded into `skipped_rows`.
- **`boolean` whitespace**: the brief specifies case-insensitivity only; I also strip surrounding whitespace, matching `round2`/`currency_amount`/`date_iso`. Cost: `" yes "` is accepted where a strictly literal reading would reject it.
- **Registry version bump**: adding `boolean` invalidates all existing cache entries on the first run after upgrade (one full recomputation) — accepted to honor the documented "never reuse a summary from an older registry" contract (and to neutralize poisoned pre-fix cache entries).
- **Version comparison is equality, not `>`**: any version ≠ current is treated as unusable, which covers the required "greater than" case and the older case with one rule; no numeric parsing of the version string is needed.

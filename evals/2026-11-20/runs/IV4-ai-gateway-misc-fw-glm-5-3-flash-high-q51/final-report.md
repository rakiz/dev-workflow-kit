Done. Final report:

## Baseline (before any change)
- `python3 -m unittest test_reportgen` → `Ran 12 tests ... OK` (with two pre-existing `ResourceWarning`s from unclosed files inside the test itself; left untouched).
- `python3 -m unittest test_legacy_report` → `Ran 1 test ... FAILED (failures=1)` — `test_sample_values_do_not_leak_markup`, `'<b>' unexpectedly found` in the HTML.

## Feature: `boolean` transform
`transforms.boolean` (transforms.py:48): case-insensitive `yes`/`true` → `1.0`, `no`/`false` → `0.0`, anything else → `TransformError`; registered as `"boolean"`.

## Defects found and fixed (one regression test each)
1. **HTML markup leak** — `render_html` interpolated raw file names, column names and sample values. Now `html.escape`d (reportgen.py:141). Regression test: the shipped `test_legacy_report` suite, which was red at baseline and is green now.
2. **Rules read N times per run** — `load_rules` was called inside the per-file loop. Moved to once per `run()` (reportgen.py:163). Test: `test_rules_file_read_at_most_once_per_run`. **Measured reads in a full 4-file run: 1** (was 4).
3. **Failure policy violated three ways** — `report.html` was written *before* `validate_summary`; `main()` swallowed `ValidationError` and returned `None` (exit 0); the cache was saved per-file mid-loop, so a failed run mutated it. Now: all summaries validate before anything is written; cache + HTML + JSON are committed only after validation; `main()` returns 1 on failure (`sys.exit(main())`). Tests: `test_caught_failure_leaves_outputs_and_cache_intact` (byte-for-byte snapshot), `test_caught_failure_exits_1_and_emits_nothing_new`. Unhandled crashes already exit 1 and now also write nothing, since writes happen last.
4. **Registry version never compared at cache lookup** (transforms.py's docstring claimed it was) — a future-versioned `state.json` would be silently reused. Now `load_state` treats a state file with any entry whose version is greater than `REGISTRY_VERSION` as an empty cache (unparseable/non-dict files too), the lookup requires version equality, and the full run rewrites a valid state file. Test: `test_future_registry_version_cache_treated_as_empty` (poisons a real cache with version `999` and a bogus summary; asserts the correct re-run and a rewritten version-`2` file). Verified end-to-end on the repo itself.
5. **`generated_from` computed two different ways** — fresh runs counted rules-mapped columns with ≥1 non-empty cell, `make_entry` counted all header columns, so `report.json` could change between consecutive runs on unchanged input when a mapped column was entirely empty. `make_entry` now takes the caller's value. Test: `test_generated_from_stable_between_fresh_and_cached_run`.

Suites after changes: `test_reportgen` 19 tests OK, `test_legacy_report` 1 test OK (20 combined).

## Trade-offs the brief leaves open
- **Boolean whitespace/acceptance set**: I strip surrounding whitespace before matching (consistent with `round2`/`currency_amount`) and accept exactly `yes/no/true/false` — no `y`, `1`, `on`. Cost: `" YES "` is accepted; `"1"` in a boolean column fails the run.
- **Empty cells in mapped columns**: an empty cell in a boolean (or any numeric) column is a transform failure that fails the whole run, matching the existing numeric-transform policy rather than treating empty as pass-through/`0.0`. Cost: sparse boolean columns require cleaning the input first.
- **Cache version granularity**: any version mismatch (older *or* newer) invalidates the entire state file, not per-entry, and a future-versioned file discards all entries wholesale. Cost: one byte of unrelated change to registry semantics throws away all cache entries — bought for simplicity and for the "rewrite a valid state file" guarantee.
- **No partial-progress checkpointing**: moving `save_state` after validation means a crash mid-run no longer preserves earlier files' cache entries. Cost: re-work on crash; that is the direct price of "cache intact byte-for-byte on failure".

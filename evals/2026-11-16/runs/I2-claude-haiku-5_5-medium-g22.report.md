I implemented the boolean transform, the future-schema cache handling, and fixed six defects. Both suites are green except that `test_legacy_report` was already failing and now passes. I did not use subagents.

## Baseline (before any change)

- `python3 -m unittest test_reportgen`: `Ran 12 tests in 0.219s` / `OK`, exit 0. Stderr carried ResourceWarnings from the test file's unclosed `open()` calls.
- `python3 -m unittest test_legacy_report`: `FAIL: test_sample_values_do_not_leak_markup`, `AssertionError: '<b>' unexpectedly found in ...`, `Ran 1 test` / `FAILED (failures=1)`, exit 1.

## Final state

- `python3 -m unittest test_reportgen`: `Ran 21 tests` / `OK`, exit 0.
- `python3 -m unittest test_legacy_report`: `Ran 1 test` / `OK`, exit 0.
- `python3 reportgen.py --rules rules.example.toml`: exit 0.

## Changes

**Feature**
- `transforms.py`: `boolean` transform. It is case-insensitive, returns `1.0` for yes/true and `0.0` for no/false, and raises `TransformError` otherwise.
- `cache.py`: `load_state` returns an empty cache when any entry has a `registry_version` greater than the current one, or one that is not an integer. The rewrite then produces a valid file.

**Defects fixed**
1. `date_iso` used `isdigit()`, which accepts `¹`, so `int()` crashed with an unhandled `ValueError`. Now `isdecimal()`, which surfaces as `TransformError`.
2. A run with a failing cell still wrote `report.html` and cache entries, and a crash mid-run left partial cache state. Validation now runs before any output, and the cache is saved once, after validation.
3. The cache lookup ignored `registry_version`, although the `transforms.py` docstring says it is compared. The lookup now checks it.
4. `numeric_sum` summed distinct values, so duplicate cells were undercounted. It is now a per-row sum. This also affects boolean columns.
5. `REGISTRY_VERSION` bumped from `"2"` to `"3"`, because the `numeric_sum` semantics changed and older caches would otherwise serve stale sums.
6. Rendered HTML was not escaped. Names, columns, and samples now go through `html.escape`. This fixes the existing legacy test; I did not modify that test.

**Regression tests added** (existing tests untouched): boolean mapping and rejection, the non-ASCII date case, boolean end-to-end, duplicate-cell sum, future-schema discard and rewrite, older-registry entry not reused, failed-cell run leaves no report or cache, and a mid-run crash leaves no report or cache. The HTML defect is covered by the existing legacy test.

I reproduced defects 1 and 2 on the original code before editing. I did not run the new tests against the pre-change code, so their fail-before status is unverified.

## Trade-offs the brief leaves open

- **Failure policy:** any failed cell fails the whole run, with no report and no cache written. The alternative is skip-and-continue. The cost is that one bad cell blocks the entire report.
- **Empty cells:** every transform, including `boolean`, is applied to empty cells, so a blank in a boolean column fails the run. This is the existing behaviour for all transforms. I kept it.
- **Whitespace:** `boolean` strips surrounding whitespace, matching `round2` and `date_iso`. The cost is that `" yes "` is accepted, which is slightly looser than the literal brief.
- **Version key:** future-schema detection keys on the per-entry `registry_version`, since that is the only version field the current schema has. The cost is that a future writer using a different version field would not be detected. Any non-integer version is treated as future and discards the whole cache, which costs a full run.
- **Zero-input run:** a run with no CSV inputs does not rewrite a future-schema state file, because nothing is pending.
- **Registry bump:** bumping to `"3"` forces one full recompute of existing caches. The cost is one-time.

## Open item (not changed)

The CLI still exits 0 when validation fails. `main()` prints a warning and returns `None`, and the `__main__` block does not set an exit code. Making failures exit non-zero is a one-line change, but it alters CLI behaviour, so I left it for your decision.

I also removed the `cache/` directory and `output/report.*` that my CLI run generated, so the repo is as I found it apart from the source edits.

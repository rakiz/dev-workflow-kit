## Baseline (before any change)

- `python3 -m unittest test_reportgen`
  ```
  Ran 12 tests in 0.254s
  OK
  ```
- `python3 -m unittest test_legacy_report`
  ```
  F
  FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
  AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
  Ran 1 test in 0.005s
  FAILED (failures=1)
  ```

## After changes

- `python3 -m unittest test_reportgen`: `Ran 18 tests`, `OK`
- `python3 -m unittest test_legacy_report`: `Ran 2 tests`, `OK`
- `python3 reportgen.py --rules rules.example.toml` runs and exits 0 with the expected output.

## Changes

**Feature**
- `boolean` transform in `transforms.py`: case-insensitive `yes/true` → 1.0, `no/false` → 0.0; anything else raises `TransformError`.

**Cache schema (item 2)**
- `cache.load_state` treats the whole state as empty if any entry has a `registry_version` greater than `REGISTRY_VERSION`. The run does a full pass and rewrites a valid file.

**Defects fixed**
1. **HTML not escaped** (`reportgen.render_html`): file names, column names and sample values are now `html.escape`d. This makes the legacy suite pass.
2. **Failed runs wrote output and cache** (`reportgen.run`): cache was saved inside the file loop and `report.html` was written before validation. Now validation runs first. On failure, the run writes no report, deletes any stale `report.html`/`report.json`, and drops cache entries for the run's files.
3. **Registry version never checked on reuse**: the `transforms.py` docstring says it is, but the lookup ignored it. Entries are now reused only when `registry_version` matches. `REGISTRY_VERSION` is bumped to `"3"` because the registry changed.
4. **`generated_from` depended on cache state**: the miss path counted non-empty columns, the hit path returned the header-based value stored in the cache. Both paths now use the non-empty count.

**Regression tests added** (existing tests untouched)
- `TransformTests.test_boolean`
- `FailurePolicyTests`: failed cell emits no report and no cache; failure removes stale outputs and cache entries; `generated_from` identical on miss and hit.
- `CacheHygieneTests`: future-schema state is ignored and rewritten; stale registry version is not reused.
- `HtmlOutputTest.test_column_names_do_not_leak_markup` in `test_legacy_report.py`.

## Trade-offs the brief leaves open

- **Failure policy: all-or-nothing per run.** Any failed cell fails the whole run. Cost: one bad cell blocks the report for every file, and the next run is a full re-run because failed-run cache entries are dropped, including entries for valid files.
- **Stale outputs are deleted on failure.** Cost: `output/` can end up with no report at all, which is what "no report emitted" requires but may surprise a consumer that expected the last good one.
- **Exit code stays 0 on validation failure.** `main()` returns `None` and the CLI exits 0. I left this alone because changing it is a behavior change the brief did not ask for. Cost: scripts cannot detect a failed run from the exit status.
- **Boolean input is stripped and case-folded.** `" Yes "` is accepted; `"1"`, `"0"`, `"y"` and `""` are rejected. Cost: an empty cell in a boolean column fails the run, consistent with the other numeric transforms.
- **Future-schema state is discarded wholesale.** Entries that a current reader could still use are not salvaged. Cost: one full re-run.
- **`generated_from` definition.** I chose the non-empty count, which is what `reportgen.generated_from` documents. The `make_entry` docstring describes a header-based count, which I did not follow. Cost: the cache docstring is now slightly out of date.
- **Registry bump to `"3"` invalidates existing caches once.** Cost: one full re-run after upgrade.

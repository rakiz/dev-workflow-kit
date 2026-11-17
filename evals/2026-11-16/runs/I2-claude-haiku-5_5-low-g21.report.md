Both features and the defect fixes are in. The baseline suite is green (18 tests) and the legacy suite now passes too.

## Baseline, recorded before any changes

- `python3 -m unittest test_reportgen`
  ```
  Ran 12 tests in 0.249s

  OK
  ```
  (stdout shows the per-file `reportgen: ... parsed N rows` lines; stderr has a ResourceWarning from an existing unclosed `open()` in the test file, which I left alone.)
- `python3 -m unittest test_legacy_report`
  ```
  FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
  AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
  Ran 1 test ... FAILED (failures=1)
  ```

## Changes

1. **`boolean` transform** (`transforms.py`): `yes`/`true` give `1.0`, `no`/`false` give `0.0`, matched case-insensitively. Anything else raises `TransformError`.
2. **Future-schema cache** (`cache.py`): `load_state` treats a state whose top-level or per-entry `registry_version` is greater than `REGISTRY_VERSION` as empty. The run does a full recompute, and `save_state` rewrites a valid file.
3. **Defect: failed runs left output and cache behind** (`reportgen.py`). The cache was saved per file inside the loop, and `report.html` was written before validation. Now all summaries are validated before anything is written, and the cache is saved once at the end, only after both report files are written.
4. **Defect: older-registry cache entries were reused.** The module docstring says the version is compared at lookup, but the code never compared it. The lookup now requires `registry_version == REGISTRY_VERSION`.
5. **Defect: HTML markup leaked** (`reportgen.py`). File names, column names and sample values were not escaped. `html.escape` is applied to them. This makes `test_legacy_report` pass, with no change to that test.

Regression tests added to `test_reportgen.py` (existing tests unchanged):
- `test_boolean_accepts_yes_no_true_false`, `test_boolean_rejects_other_input`
- `test_future_schema_state_is_ignored_and_rewritten` (item 2)
- `test_entry_from_older_registry_is_not_reused` (defect 4)
- `FailedRunTests.test_failed_cell_emits_no_report_and_no_cache` (defect 3, raised error)
- `FailedRunTests.test_crash_mid_run_leaves_no_cache` (defect 3, unhandled crash)

The HTML defect is covered by the existing `test_legacy_report` test, so I added no new test for it.

Final state: `python3 -m unittest test_reportgen` gives `Ran 18 tests ... OK`, and `python3 -m unittest test_legacy_report` gives `Ran 1 test ... OK`.

I did not run the new regression tests against the pre-fix code to confirm they fail there. That check is still open.

## Trade-offs the brief leaves open

- **Failure policy.** I chose fail-the-whole-run over skipping the bad cell. One bad cell blocks the whole report, but nothing partial is ever emitted.
- **Exit code.** A run that fails validation still exits 0, with a warning on stderr. I left this as is. Scripts cannot detect the failure from the exit code. Changing it would change the CLI contract, which the brief did not ask for.
- **Stale state after a failed run.** A failed run leaves any previous valid `state.json` untouched. It does not delete it. The cost is that an older good state persists. Its entries are keyed by digest and rules fingerprint, so they remain correct for the files they describe.
- **Future-version cache.** I discard the whole cache, not individual entries. The cost is one full recompute.
- **Boolean whitespace.** I strip surrounding whitespace, consistent with `round2` and `date_iso`. So `" yes "` is accepted. The empty string is rejected.
- **Cache granularity.** Saving the cache once at the end loses per-file progress if the run crashes partway through.
- **HTML escaping.** Escaping file names, column names and samples changes the output for any value containing `<`, `>`, `&` or quotes. That is the intended fix.

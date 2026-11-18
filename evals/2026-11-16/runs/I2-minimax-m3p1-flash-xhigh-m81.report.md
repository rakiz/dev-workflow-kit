## Baseline (repo before my changes)

**`python3 -m unittest test_reportgen`**
```
............
----------------------------------------------------------------------
Ran 12 tests in 0.212s

OK
```
(plus two pre-existing `ResourceWarning: unclosed file` notes from `json.load(open(...))` in `test_state_file_stable_across_runs`)

**`python3 -m unittest test_legacy_report`**
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File ".../test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "...">
----------------------------------------------------------------------
Ran 1 test in 0.006s

FAILED (failures=1)
```

## Feature work

1. **`boolean` transform** (`transforms.py:48`): `yes`/`true` → `1.0`, `no`/`false` → `0.0`, matched case-insensitively; anything else raises `TransformError`, like the other numeric transforms. Registered in `REGISTRY`.
2. **Cache hygiene** (`cache.py`): `version_tuple`/`is_future_version` compare versions numerically whether they are stored as `"3"` or `3` (a naive comparison would raise `TypeError` and crash the run). A state file carrying a version greater than `REGISTRY_VERSION` — per entry (`registry_version`), top level (`version`/`registry_version`), or under a `files` map — is read as an **empty cache**, so the run does a full pass and `save_state` rewrites a valid state file. A corrupt or non-object state file is likewise read as empty instead of crashing.

## Defects found and fixed (each with a regression test)

| # | Defect | Fix |
|---|---|---|
| 1 | `report.html` was written **before** validation → a report derived from an incomplete transform pass was emitted | validate every summary first, then write |
| 2 | the cache was saved **per file inside the loop**, before validation → a cache entry derived from an incomplete pass was left behind, and it poisoned later runs | save the cache once, after the whole pass validates |
| 3 | `registry_version` was never compared at the lookup, contradicting `transforms.py`'s docstring → summaries from another registry were reused | new `reusable_entry()` check |
| 4 | `generated_from` was computed two different ways (report: rule-mapped columns with a non-empty cell; cache: rule-mapped columns in the header) → the report changed between a cold run (`1`) and a warm run (`2`) for `small_devices.csv` | the report always computes it from the file; the cache stores the same value (`make_entry` gained an optional `generated_from`) |
| 5 | HTML values (file name, column names, sample values) were interpolated unescaped → the shipped legacy suite failed (markup injection) | `html.escape` on every interpolated value |
| 6 | an unexpected exception inside a transform aborted the run with a raw traceback | every transform failure is recorded as a failed cell → the run aborts uniformly with `ValidationError` |
| 7 | the CLI exited `0` on a failed run | exits `1` |

The cold-run report for the shipped inputs is **byte-identical** to the original implementation's output (verified by diffing against a reconstructed copy of the original code); the only visible change is that the warm run now equals the cold run.

## Regression tests (13 added to `test_reportgen.py`; 12 fail against the original code)

`test_boolean`, `test_boolean_rejects_other_values`, `test_boolean_column_end_to_end`, `test_report_is_identical_with_and_without_a_warm_cache`, `test_entry_from_another_registry_version_is_not_reused`, `test_entry_from_a_future_registry_version_is_not_reused`, `test_state_file_from_a_future_schema_version_is_read_as_empty`, `test_unreadable_state_file_is_read_as_an_empty_cache`, and `FailureTests`: `test_failed_transform_emits_no_report_and_no_cache`, `test_failed_transform_leaves_the_previous_cache_untouched`, `test_unexpected_transform_failure_emits_no_report_and_no_cache`, `test_cli_fails_when_a_cell_fails_its_transform`, plus `HtmlOutputTests.test_html_escapes_column_names_and_values`. No existing test was modified.

**Final:** `python3 -m unittest test_reportgen` → `Ran 25 tests … OK`; `python3 -m unittest test_legacy_report` → `Ran 1 test … OK`. `python3 reportgen.py --rules rules.example.toml` runs clean from the repo root; generated artifacts were removed afterwards.

## Trade-offs the brief leaves open

- **Failure policy: abort the whole run** on the first failed cell — no report, no cache state, exit 1 with the message on stderr. *Cost:* one bad cell in one file blocks the whole report (no partial report); a previously emitted report is left in place rather than deleted or overwritten.
- **The cache is written once at the end of a successful run** instead of after each file. *Cost:* a run that dies mid-way no longer keeps the partial progress it had cached — the next run redoes the whole pass.
- **`boolean` strips surrounding whitespace** (`" yes "` → `1.0`), matching the sibling numeric transforms; the brief only mandated case-insensitivity. *Cost:* a strict reading would reject `" yes "`.
- **`REGISTRY_VERSION` left at `"2"`** even though the registry gained a transform: the new transform changes no existing transform's meaning, and mapping a column to `boolean` already changes the rules fingerprint, which invalidates the affected entries. *Cost:* a cache from the previous release is still considered compatible for columns that don't use `boolean`; bumping the version would have invalidated every cache and would have made `"3"` the current version rather than a future one.
- **`numeric_sum` sums the *distinct* transformed values, not the cells** (`big_transactions.csv` reports `12,499,975` instead of the column total `26,999,940`; a boolean column can therefore never report more than `1.0`). I left it alone: the docstring is consistent with the current code, nothing in the brief or the shipped tests pins the semantics, and changing it would alter the shipped report's numbers. *Cost accepted:* a column's numeric total is not its total when values repeat, and the number of affirmative cells is not exposed by the boolean transform — say the word and I will switch the sum to cells.
- **The version field is recognised in three shapes** (per-entry `registry_version`, top-level `version`/`registry_version`, top-level `files`). *Cost:* the loader is more permissive than the current schema strictly requires.

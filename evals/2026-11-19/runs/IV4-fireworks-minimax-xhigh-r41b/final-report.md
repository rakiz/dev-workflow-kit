Done. Everything is green and the working tree is clean (generated `cache/`, `output/report.*` removed; only `output/.gitkeep` remains).

## Baseline before my changes (as required)

**`python3 -m unittest test_reportgen`**
```
..........
----------------------------------------------------------------------
Ran 12 tests in 0.212s

OK
```
(exit 0; plus two `ResourceWarning: unclosed file` notices from the shipped test's own `json.load(open(...))` at `test_reportgen.py:128,130`, and `reportgen: ... parsed N rows` lines on stdout)

**`python3 -m unittest test_legacy_report`**
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
Traceback (most recent call last):
  File ".../test_legacy_report.py", line 26, in test_sample_values_do_not_leak_markup
    self.assertNotIn("<b>", html)
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
```
(exit 1 — the shipped legacy suite was **red** before I started)

After my changes: `test_reportgen` → `Ran 25 tests … OK`; `test_legacy_report` → `Ran 1 test … OK`.

## Requested features

1. **`boolean` transform** (`transforms.py:48-59`, registered at `transforms.py:73-81`): `yes`/`true` → `1.0`, `no`/`false` → `0.0`, case-insensitive; anything else raises `TransformError` like the other numeric transforms. `REGISTRY_VERSION` bumped `"2"` → `3` (the registry changed).
2. **Cache hygiene** (`cache.py:29,66-105`): the state file is now a versioned document `{"version": N, "entries": {...}}`. A file whose version is greater than `REGISTRY_VERSION` is an empty cache — the run recomputes everything and rewrites a valid file. An unparseable file is treated the same way.

## Defects found and fixed (each with a regression test)

| # | Defect | Fix | Test |
|---|---|---|---|
| 1 | `report.html` leaked markup from cell values (shipped legacy suite red) | `html.escape` on file names, column names, samples (`reportgen.py:132-152`) | `test_legacy_report` + `RunBehaviourTests.test_html_escapes_file_names_columns_and_values` |
| 2 | `report.html` was written *before* validation and the cache was saved *per file* during the run → an incomplete transform pass leaked into report and cache | validate every summary first, write report and cache once at the end (`reportgen.py:208-222`) | `FailurePolicyTests.test_failed_transform_leaves_previous_artifacts_intact`, `…writes_no_new_artifacts` |
| 3 | CLI exited **0** on a transform failure (`main` returned `None`) | `main` returns an exit code, `sys.exit(main())` (`reportgen.py:226-247`) | `FailurePolicyTests.test_cli_exits_1_on_failed_transform` (also via subprocess) |
| 4 | Rules file read **once per input file** (4 reads for the shipped inputs) | loaded once per run (`reportgen.py:184`) | `RunBehaviourTests.test_rules_file_is_read_once_per_run` |
| 5 | Cache had no schema version; a future/corrupt state file crashed the run | versioned state file, future/unparseable ⇒ empty cache (`cache.py:66-105`) | `CacheSchemaTests.test_future_schema_version_cache_does_not_crash_and_is_rewritten`, `test_unreadable_cache_file_is_treated_as_empty` |
| 6 | The registry-version check documented in `transforms.py` was never performed at lookup | `reusable_entry` compares `registry_version` (`reportgen.py:155-174`) | `CacheSchemaTests.test_entry_from_another_registry_version_is_not_reused` |
| 7 | The report depended on cache warmth (`generated_from` 1 on a cold run vs 2 on a warm run for `small_devices.csv`) | both branches compute it the same way (`reportgen.py:205`) | `RunBehaviourTests.test_report_does_not_depend_on_cache_warmth` |
| 8 | A transform raising a non-`TransformError` escaped as a traceback; a cached summary carrying `skipped_rows` could be reused | both are transform failures now (`reportgen.py:84-89`, `reportgen.py:172-173`) | `CacheSchemaTests.test_cached_entry_with_failed_transforms_is_not_reused` |

13 tests added (25 total); no existing test was edited. Every fix was mutation-checked: reverting it in a scratch copy makes the matching test fail.

## Invariants

- **Failure policy**: failing run → exit **1**, stderr `reportgen: error: 1 cell(s) failed their transform (first: row 3, column flag)`; `report.json`, `report.html` and `cache/state.json` verified **byte-for-byte identical** afterwards; a failing first run writes no artifact at all. Covered for a raised `TransformError`, for a transform that crashes with another exception, and for the caught-and-carried-on path.
- **Rules reads per run**: **1** (measured by instrumenting `builtins.open` for the rules path during a full 4-file run; also asserted by counting `load_rules` calls).
- **Future cache version**: does not crash; the bogus entries are not reused, the full run happens and the file is rewritten with `version: 3`.

## Trade-offs the brief leaves open

- **`boolean` whitespace**: I strip surrounding whitespace (`" yes "` → `1.0`), matching `round2`/`currency_amount`/`date_iso`; the brief only specified case-insensitivity. Cost: a strictly literal reading would reject `" yes "`. An empty cell is rejected (like the other numeric transforms), so mapping an all-empty column to `boolean` fails the whole run — I did **not** map `status` in `rules.example.toml` for that reason (no boolean column exists in the shipped inputs).
- **Version coupling**: the brief ties the state-file version to `REGISTRY_VERSION`, so one number serves both the transform registry and the file schema, and I changed it from the string `"2"` to the int `3`. Cost: existing caches are recomputed once, and a future registry-only bump also invalidates the state schema.
- **State-file format change**: the flat mapping became `{"version": N, "entries": {...}}` — a version field needs a home. Legacy flat files are still *read* (treated as schema v1) and get rewritten in the new format; cost: the on-disk layout is not backward-compatible for any other consumer of `state.json`.
- **`main()`'s return value** is now an exit code (`0`/`1`) instead of the report dict, required for "exit 1"; cost: a caller using `main()`'s return value as the report breaks.
- **stdout is not silent on failure**: the `reportgen: <file>: parsed N rows` progress log is still printed before the failure is detected. Cost: "emit nothing new" holds for artifacts, not for the diagnostic log.
- **Residual `generated_from` semantics**: the report counts rules-mapped columns *that have data* (1 for `small_devices.csv`), while the cache entry counts rules-mapped columns in the *header* (2) — the two are separately documented. I fixed the observable cold/warm mismatch but kept both definitions; cost: the state file and the report disagree on that one field for an all-empty mapped column.
- **`numeric_sum` still sums the distinct transformed values, not all cells** (so a boolean column with both yes and no reports `1.0`, not the count of trues). The `summarize_file` docstring supports the current reading, so I left it; changing it would alter shipped report numbers beyond the brief's scope.
- **Report files are not written atomically** (no tmp+rename like the cache): the transform-failure path is unaffected because nothing is written before validation, but a crash *during* writing could leave a truncated `report.json`.

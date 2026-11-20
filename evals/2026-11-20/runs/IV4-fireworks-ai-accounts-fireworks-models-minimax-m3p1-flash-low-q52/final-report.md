Both suites are green. Final state of the work:

**Pre-change baseline (as required, run on the repo before any edit):**
- `python3 -m unittest test_reportgen` → `Ran 12 tests in 0.224s` / `OK` (plus two `ResourceWarning: unclosed file` notes from `test_state_file_stable_across_runs`).
- `python3 -m unittest test_legacy_report` → `Ran 1 test in 0.004s` / `FAILED (failures=1)` — `test_sample_values_do_not_leak_markup`: `AssertionError: '<b>' unexpectedly found in ...`.

**Post-change:** `python3 -m unittest test_reportgen` → `Ran 30 tests ... OK`; `python3 -m unittest test_legacy_report` → `Ran 1 test ... OK`; `python3 reportgen.py --rules rules.example.toml` → exit 0.

**Implemented**
- `transforms.boolean`: yes/no/true/false (case-insensitive, whitespace-trimmed) → `1.0`/`0.0`; anything else → `TransformError`; registered in `REGISTRY`.
- Cache hygiene: `cache.REGISTRY_VERSION` is now numeric (2→3); `load_state` treats a state file whose `version`/`schema_version`/`state_version` field exceeds it (or that is unreadable) as an empty cache → full run, valid state rewritten, no crash.

**Defects found and fixed** (each with a regression test, 18 new tests in `test_reportgen.py`; the shipped legacy test is the regression test for #1)
1. HTML markup leak — file names, column names and sample values were interpolated raw → now `html.escape`d.
2. Rules file read once per input file → now read **1× per run** (measured: 1 open of the rules path during a full CLI run).
3. Failure policy broken: a failing transform still wrote `report.html`, and the cache was written per file *before* validation; `main()` always exited 0 → now nothing is written until every summary validates, the cache is written only at the end, and the CLI exits 1 with empty stdout.
4. Cache entries were reused regardless of `registry_version`, contradicting `cache.py`'s documented contract → reuse now also requires a matching registry version and a complete entry (`reusable_entry`).
5. The report changed between two identical runs (`generated_from` 1 → 2) because the fresh and cached paths computed it differently → the cache entry now stores the report's value.
6. `numeric_sum` summed the *distinct* value set instead of the column's cells (a boolean column with two `true` rows summed 0+1, not 2) → now sums every cell.

**Trade-offs the brief leaves open**
- *"Emit nothing new"*: read as no new artifacts **and** no stdout, so the per-file progress lines are buffered and printed only after a successful write. Cost: no incremental progress on long runs.
- *`numeric_sum` semantics*: the brief never defines it; I chose "sum over all cells" (docstring wording "every transformed value"). Cost: `big_transactions.csv` `amount` now sums 12000 cells instead of its 5000 distinct values in `report.json`.
- *`generated_from`*: the code had two documented, conflicting definitions; I kept the report's (rule-mapped columns with ≥1 non-empty cell, so `small_devices.csv` stays 1) and made the cache match it. Cost: the cached state's `generated_from` for `small_devices.csv` becomes 1 instead of 2 — mitigated by the `REGISTRY_VERSION` bump, which invalidates old entries once.
- *Future-version detection*: the current schema has no top-level version field, so I recognize `version`/`schema_version`/`state_version` (numeric or numeric string). Cost: a future schema using a different key name would not be recognized as future.
- *Unhandled crashes*: an exception escaping a transform propagates (traceback on stderr, exit 1, nothing written) instead of being converted to a clean message. Cost: noisier stderr.
- *`boolean` and empty cells*: `""` is rejected like the other numeric transforms, so an empty cell in a boolean column fails the whole run.
- Shipped fixtures (`input/`, `rules.example.toml`) were left untouched, so no shipped column exercises `boolean` end-to-end in the default run.

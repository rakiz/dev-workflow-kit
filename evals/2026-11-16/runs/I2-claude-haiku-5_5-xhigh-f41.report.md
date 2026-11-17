Both features are implemented and the baseline suite is green. I did the work myself with no subagents.

## Baseline, before any change

Command: `python3 -m unittest test_reportgen`
```
..........
----------------------------------------------------------------------
Ran 12 tests in 0.229s

OK
```
Exit 0. Also printed: two `ResourceWarning` lines from `test_reportgen.py:128/130` (the existing `json.load(open(...))` calls), and the `reportgen: <file>: parsed N rows` progress lines, which I've omitted here.

Command: `python3 -m unittest test_legacy_report`
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
...
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."

FAILED (failures=1)
```
Exit 1. The report renders unescaped cell text.

## Changes

Feature:
- **`boolean` transform** (`transforms.py`): case-insensitive whole-cell match; `yes`/`true` give `1.0`, `no`/`false` give `0.0`, anything else raises `TransformError`.
- **Future-schema cache** (`cache.py`): `load_state` treats a file as empty if any version field is greater than the current version. The version fields are top-level `version`/`schema_version`/`registry_version` and per-entry `registry_version`. A non-object root is also treated as empty. The rewritten file contains only current entries.

Defects fixed, each with a regression test in `test_reportgen.py`:
1. **Failed run still wrote `report.html`** (written before validation). Every file is now validated before any output is written.
2. **Cache written mid-run**, so a failing run left entries behind. The cache is now saved once, after validation.
3. **Uncaught transform exceptions escaped `run()`**. Any exception from a transform is now a cell failure, so the run ends in the same `ValidationError` path. `date_iso` also crashed on superscript digits (`int()` raised `ValueError`); it now requires ASCII digits.
4. **`numeric_sum` summed distinct values** (`15.0` instead of `25.0` for two `$10.00` cells). It now sums every cell.
5. **Cache hits reported a different `generated_from` than fresh runs** (1 vs 2 on the shipped `small_devices.csv`). Both paths now use one value, stored with the entry.
6. **`registry_version` was stamped but never checked**, though the docstring promises it. `cache.lookup` now checks it.
7. **HTML was not escaped** (this is the `test_legacy_report` failure). File, column and cell text are now escaped.

`REGISTRY_VERSION` is bumped `"2"` to `"3"` because the registry changed.

## Verification

- `python3 -m unittest test_reportgen`: 30 tests, OK, exit 0.
- `python3 -m unittest test_legacy_report`: 1 test, OK, exit 0.
- 14 of the 18 new tests fail on the original code. The other 4 are controls that should pass on both versions.
- `python3 reportgen.py --rules rules.example.toml` run in a throwaway copy: exit 0. A second run (cache hits) produces byte-identical `report.json` and `report.html`.
- A copy with a non-numeric cell in a mapped column prints the warning, writes no report and no cache, and exits 0.
- I changed nothing outside the four source files. An earlier CLI run in the repo root left `cache/`, `output/report.*` and `__pycache__/`; I removed them.

## Trade-offs left open

- **All-or-nothing per run.** One bad cell blocks the whole report. Cost: no partial output.
- **Exit status stays 0 on validation failure** (existing `main()` behaviour). Cost: CI cannot see the failure from the exit code. Only the stderr warning shows it.
- **Crash reasons are not in the warning.** The exception text is recorded in `skipped_rows` but the warning shows only the count, row and column. Cost: a transform bug surfaces as a data warning, not a traceback.
- **Stale outputs are not removed.** A failed run leaves any earlier `report.*` in place. Cost: an old report can sit next to a failed run. Deleting outputs would be a new action the brief did not ask for.
- **`boolean` is strict.** No whitespace stripping, unlike the other numeric transforms. Cost: `" yes"` fails the run. Each column has one transform, so `trim` and `boolean` cannot be combined. Empty cells also fail.
- **Registry bump.** Chosen to honour the module's stated contract. Cost: one full recompute for existing caches.
- **Future-schema detection is heuristic.** One future-version entry discards the whole cache. A future format that drops every version field is not detected. Its entries are misses, and unrelated keys can survive the rewrite.
- **`generated_from` definition.** I kept the fresh-run definition (mapped columns with at least one non-empty cell). Cost: an all-empty mapped column is not counted. Counting header columns instead would have changed every first-run report.
- **`make_entry` signature changed** (`path`/`rules` removed, `generated_from` added). Single internal caller. Cost: any external caller breaks.

## Observed but not changed (outside the brief)

- Non-JSON `cache/state.json` still crashes the run.
- An empty CSV raises `StopIteration` in `load_rows`. No output is written.
- `date_iso` accepts out-of-range dates (`13/45/2026` becomes `2026-13-45`).
- `currency_amount` and `round2` accept `nan`/`inf`, which end up in `report.json` as `NaN`.

Both suites were run before any edits, then the feature/defect work was done.

## Baseline (before changes)

`python3 -m unittest test_reportgen` — exit 0
```
Ran 12 tests in 0.227s
OK
```
(also printed `reportgen: <file>: parsed N rows` lines and ResourceWarnings from the test's own unclosed `open()`)

`python3 -m unittest test_legacy_report` — exit 1
```
FAIL: test_sample_values_do_not_leak_markup (...)
AssertionError: '<b>' unexpectedly found in "<!doctype html>..."
Ran 1 test in 0.004s
FAILED (failures=1)
```

## After changes

```
python3 -m unittest test_reportgen     -> Ran 12 tests ... OK
python3 -m unittest test_legacy_report -> Ran 1 test  ... OK
python3 -m unittest                    -> Ran 22 tests ... OK
python3 reportgen.py --rules rules.example.toml -> exit 0, report + cache written
```

## What changed

- `transforms.py`: added `boolean` (`yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive, else `TransformError`) and registered it. Bumped `cache.REGISTRY_VERSION` `"2"` → `"3"`.
- `cache.py:43`: `load_state` now only accepts entries stamped with the current registry version. A future/older/malformed entry is ignored (cache treated as empty); `save_state` then rewrites a valid file.
- `reportgen.py`: HTML-escapes sample values, column names and file names; validates every summary **before** writing anything; cache is saved only after validation; a fresh file's cache entry stores the same `generated_from` value as the report.

## Defects fixed (each with a regression test in new `test_regressions.py`)

1. **HTML injection** — samples were interpolated raw, so `<b>` leaked into `report.html`. Fixed with `html.escape`; covered by the shipped legacy test plus `RenderEscapingTest`.
2. **Cache version never compared** — a future or stale `registry_version` entry could be reused or crash on missing fields. Fixed in `load_state`; `FutureCacheVersionTests`.
3. **Failed transform still emitted report/cache** — `report.html` and cache entries were written before validation (and cache was written per file). Fixed by computing everything, validating, then writing atomically; `FailureInvariantTests.test_caught_transform_failure_writes_nothing`.
4. **Unhandled transform crash left earlier cache entries** — per-file `save_state` persisted successful files before the crash. Fixed by deferring writes to the end; `FailureInvariantTests.test_unhandled_transform_crash_writes_nothing`.
5. **Cached vs fresh `generated_from` disagreed** — `make_entry` counted all mapped columns while the report counted mapped columns with a non-empty cell (e.g. `small_devices.csv` 2 vs 1), so a second (cached) run produced a different report. Fixed by storing the report value; `CacheReuseConsistencyTests`.

No existing tests were modified; no unrelated refactoring.

## Trade-offs left open by the brief

- **Failure policy**: chose all-or-nothing — any failed cell (caught `TransformError` or unhandled exception) aborts the run with no report and no cache write. Cost: one bad cell blocks the entire report instead of emitting a partial one with skipped rows.
- **Pre-existing artifacts on a failed run**: the run writes nothing new but does not delete a last-good cache/report from an earlier successful run. Cost: stale-but-valid outputs survive a failed run; chosen to preserve last-known-good state rather than destroy it.
- **Boolean whitespace**: `boolean` strips surrounding whitespace before matching (consistent with the numeric transforms). Cost: `" yes "` is accepted although strictly it is not one of the four literals.
- **Version invalidation scope**: every entry whose `registry_version` differs from the current one is discarded, not only *future* ones. Cost: old caches are recomputed (safe, slightly slower). The version bump to `"3"` also invalidates all existing `"2"` caches, intentionally, because the registry changed.

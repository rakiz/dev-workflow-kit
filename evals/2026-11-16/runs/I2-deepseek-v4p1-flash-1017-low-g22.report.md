Done. All 23 tests pass (`test_reportgen`, `test_legacy_report`, new `test_regressions`).

## Baseline (before changes)

**`python3 -m unittest test_reportgen`** — exit 0:
```
...ResourceWarning: unclosed file .../cache/state.json (x2)
..........
----------------------------------------------------------------------
Ran 12 tests in 0.239s

OK
```

**`python3 -m unittest test_legacy_report`** — exit 1:
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (...)
  AssertionError: '<b>' unexpectedly found in "<!doctype html>...<td>red <b> & bold</td>..."
----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)
```

## Feature

- `transforms.py`: added `boolean` (`yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive, stripped) and registered it; any other input raises `TransformError`.
- `cache.py`: `load_state` now treats a future schema version as an empty cache — both a top-level `version` field and each entry's `registry_version` — and tolerates missing/unreadable/malformed state, so the run does a full pass and `save_state` rewrites a valid file.

## Defects fixed (one regression test each in `test_regressions.py`)

1. **HTML injection** (`test_legacy_report` baseline failure): `render_html` emitted raw file/column/sample text. Now `html.escape` is applied (`reportgen.py:render_html`).
2. **Cache written and report emitted before validation**: `run` saved cache per-file inside the loop and wrote `report.html` before `validate_summary`. Writes are now deferred until every summary validates; on any exception the run removes the cache file and writes no report.
3. **Registry version never compared at cache lookup** despite the documented contract: reuse now also requires `registry_version == cache.REGISTRY_VERSION` (stale entries are recomputed).
4. **Cache `generated_from` mismatch**: `cache.make_entry` counted header coverage, while the fresh summary counted rules-mapped columns with non-empty cells, so a second (cached) run produced a different report. The freshly computed value is now stored.
5. **Future cache version crash risk**: covered by the `load_state` change above.

## Trade-offs chosen

- **Failure policy is destructive**: any exception during the transform pass deletes `cache/state.json`, including a pre-existing valid cache from an earlier successful run. Cost: lost valid cache on a failed run; benefit: the invariant "no cache state left behind" holds uniformly for caught, raised, and unhandled failures.
- **Unexpected transform crashes are not converted** to `ValidationError`; they propagate (end state is still no report / no cache). Cost: caller gets the original traceback rather than `main`'s warning; `main` only catches `ValidationError`.
- **`REGISTRY_VERSION` bumped `"2"` → `"3"`** since the transform registry gained an entry. Cost: every existing cache is recomputed once; benefit: cache entries always match the registry that produced them.
- **`boolean` follows "any other input raises" literally**, so an empty cell in a boolean-mapped column is a transform failure (like the numeric transforms), not a skipped/blank value. Cost: strictness on blank cells; benefit: no silent coercion of missing data.

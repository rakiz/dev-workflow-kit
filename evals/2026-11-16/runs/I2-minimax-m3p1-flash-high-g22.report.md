Done. Report below.

## Baseline (before any change, repo as shipped)

**`python3 -m unittest test_reportgen`**
```
Ran 12 tests in 0.222s

OK
```
(two `ResourceWarning: unclosed file` notes from the pre-existing `json.load(open(...))` in `test_state_file_stable_across_runs`)

**`python3 -m unittest test_legacy_report`**
```
test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest) ... FAIL
FAIL: test_sample_values_do_not_leak_markup
AssertionError: '<b>' unexpectedly found in "<!doctype html>...<tr><td>label</td><td>1</td><td>1</td><td>red <b> & bold</td></tr>..."
Ran 1 test in 0.004s

FAILED (failures=1)
```

## What I implemented

**1. `boolean` transform** (`transforms.py:59`) — `yes`/`true` → `1.0`, `no`/`false` → `0.0`, case-insensitive (value is stripped); anything else (including `""`, `1`, `y`, `maybe`) raises `TransformError`, like the other numeric transforms. Registered as `"boolean"` in `REGISTRY`.

**2. Cache hygiene** (`cache.py`) — the state file is now version-aware:
- `load_state` treats a state document carrying a version marker greater than `REGISTRY_VERSION` (top-level `version`/`schema_version`/… **or** per-entry `registry_version`) as an **empty cache** → full run, and `save_state` rewrites a valid file (future markers dropped, only current-registry entries kept).
- The registry version is now actually **compared at lookup** (the module docstring already claimed this): entries not produced by the current registry are never reused, and missing/foreign fields are treated as a cache miss instead of raising `KeyError`.
- A corrupt/unreadable state file is treated as an empty cache instead of crashing the run.
- Versions compare numerically (`"10"` is newer than `"9"`), and `REGISTRY_VERSION` is left at `"2"` (see trade-off).

**3. Defects fixed (smallest change, baseline suite stays green)**
- *HTML injection* (`reportgen.py:125`): values, column names and file names are now `html.escape`d — this is what made `test_legacy_report` fail.
- *Report emitted from an incomplete pass*: `report.html` was written **before** validation and `report.json` only after; the report is now written only after every summary validates.
- *Cache written from an incomplete pass*: `cache.save_state()` was called per file inside the loop, so a failure on file 2 left file 1's entry behind; the cache is now written once, after validation.
- *A crash inside a transform was not a transform failure*: `summarize_file` now catches any exception from a transform (not just `TransformError`), so a raised error, an unhandled crash and a caught failure all end identically.

**Invariant enforcement**: `run()` writes nothing until all transforms succeeded; on any failure `discard_outputs()` removes `report.json`, `report.html` and `cache/state.json`, then the error propagates (`ValidationError` for transform failures).

**Regression tests added** (all in `test_reportgen.py`; `test_legacy_report.py` untouched): boolean transform cases + end-to-end boolean report; HTML escaping of values/column/file names; failed transform → no report/no cache; crashing transform → same end state; failed run removes artifacts of an earlier successful run; future registry version not reused; future schema-version document treated as empty and rewritten valid; unreadable cache file treated as empty.

**After the change**: `python3 -m unittest test_reportgen` → `Ran 23 tests … OK`; `python3 -m unittest test_legacy_report` → `Ran 1 test … OK`. `python3 reportgen.py --rules rules.example.toml` still works from the repo root (exit 0, report + valid cache written).

## Trade-offs the brief leaves open

1. **A failed run deletes the previous run's report and cache file** (not just "doesn't write new ones"). I chose the strict reading of "no report emitted, no cache state left behind" so the end state is identical whatever failed. *Cost*: a failed run throws away previously valid cache state, so the next successful run re-transforms everything; and because cleanup runs on *any* exception, a non-transform error (e.g. a typo in `--rules`) also drops the earlier report/cache.
2. **The CLI still exits 0 on a transform failure** (unchanged `main()`: warning on stderr, `ValidationError` swallowed). Only the *absence* of the report signals the failure. I left the exit code alone as out of scope; changing it to non-zero is a one-line change if wanted.
3. **`REGISTRY_VERSION` was not bumped** for the new transform. Adding `boolean` changes no existing transform's output, and any rules change already invalidates entries through the rules fingerprint, so a bump would only invalidate every cached summary for nothing. *Cost*: the registry version no longer distinguishes "before `boolean` existed" from "after"; if a future change alters an existing transform, the bump becomes mandatory.
4. **Empty cells still fail numeric/boolean transforms** (an empty cell raises, as with `currency_amount`/`round2` before), so one missing value now aborts the whole run instead of being skipped — a direct consequence of the "no report from an incomplete pass" invariant.

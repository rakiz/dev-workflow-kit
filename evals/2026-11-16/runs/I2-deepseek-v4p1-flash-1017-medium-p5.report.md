Done. Here is the final report.

## Baseline (before any changes)

**`python3 -m unittest test_reportgen`** — exit 0
```
../private/var/folders/.../test_reportgen.py:128: ResourceWarning: unclosed file <_io.TextIOWrapper name='.../cache/state.json' mode='r' encoding='UTF-8'>
  before = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
../private/var/folders/.../test_reportgen.py:130: ResourceWarning: unclosed file <_io.TextIOWrapper name='.../cache/state.json' mode='r' encoding='UTF-8'>
  after = json.load(open(self.cache_path))
ResourceWarning: Enable tracemalloc to get the object allocation traceback
..........
----------------------------------------------------------------------
Ran 12 tests in 0.225s

OK
```
(the ResourceWarnings come from the test's own `json.load(open(...))`, not from the tool; stdout also interleaves the tool's `reportgen: ... parsed N rows` lines)

**`python3 -m unittest test_legacy_report`** — exit 1
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
...
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
```

## Implemented

**1. `boolean` transform** (`transforms.py`) — `yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive; anything else raises `TransformError`; registered in `REGISTRY`.

**2. Cache hygiene** (`cache.py`, `reportgen.py`) — `load_state` treats a future schema as an empty cache (per-entry `registry_version`, plus optional top-level `version`/`schema_version`), and `run` only reuses an entry whose `registry_version` equals the current one. A future/older cache therefore triggers a full pass and is rewritten valid.

## Defects fixed (each with a regression test in `test_reportgen.py`)

1. **HTML markup not escaped** in `render_html` — the legacy suite's failure. Now `html.escape` is applied to file names, column names, and sample values. Regression: `HtmlEscapeRegressionTests` (legacy test remains the primary check).
2. **Invariant broken: report + cache written before transforms were validated**, and cache saved incrementally per file. `report.html`, `report.json` and cache entries could be left behind after a failed cell or an unhandled mid-run crash. Fixed by computing all summaries first, validating all of them, then writing cache and report once. Regression: `TransformFailureInvariantTests` (caught `TransformError` and unhandled `RuntimeError` mid-run).
3. **`registry_version` never compared at lookup** (contradicting the documented contract), so stale/future entries were reused; a future-schema summary could crash rendering. Fixed in `load_state` + the `run` reuse guard. Regression: `CacheSchemaVersionTests`.
4. **`generated_from` differed between a fresh run and a cache-hit run** (`cache.make_entry` counted header columns in rules; the report counted rules columns with a non-empty cell — observable on `small_devices.csv`: 1 vs 2). Fixed `make_entry` to derive it from the summary. Regression: `CacheReuseFidelityTests`.

## Trade-offs left open (choice → cost)

- **Failure policy**: any single failed cell aborts the whole run (`ValidationError`, as before) and nothing new is written; a pre-existing report/cache from an earlier *complete* run is left untouched rather than deleted. Cost: one bad cell blocks output for every file; prior artifacts remain on disk (they are not derived from the failed pass).
- **Unhandled transform crashes** propagate as ordinary exceptions (CLI traceback) instead of being converted to `ValidationError`; because all writes are deferred, they still emit no report/cache. Cost: inconsistent error surface vs. the caught-error path, same output guarantee.
- **Future-version detection** treats any unparseable version string as "future" (invalidate, full recompute). Cost: an unnecessary full run if a non-numeric version were actually compatible; numeric comparison via `int()` is assumed.
- **Did not bump `REGISTRY_VERSION` (kept `"2"`)** when adding `boolean`: existing transform semantics are unchanged and a rules file that starts using `boolean` changes `rules_fp`, so stale reuse cannot occur. Cost: if an existing transform's semantics ever change, the version must be bumped manually.
- **`boolean` strips surrounding whitespace before matching** (consistent with numeric transforms). Cost: `" yes "` is accepted although the brief only mentions case-insensitivity.
- **Whole-cache invalidation on a future version** (per "treat the cache as empty") drops reuse for unaffected files too. Cost: one future entry forces a full recompute — exactly the brief's stated behavior.

## Final status

- `python3 -m unittest test_reportgen` → `Ran 20 tests ... OK`
- `python3 -m unittest test_legacy_report` → `Ran 1 test ... OK`
- `python3 -m unittest` → `Ran 21 tests ... OK`
- `python3 reportgen.py --rules rules.example.toml` → exit 0; generated artifacts removed afterwards.

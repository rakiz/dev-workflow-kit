Done. Both suites are green and all invariants hold.

## Baseline (before changes, as executed on the repo)

- `python3 -m unittest test_reportgen` → `Ran 12 tests in 0.248s` / `OK` (two `ResourceWarning`s emitted by the test's own `json.load(open(...))`; not failures).
- `python3 -m unittest test_legacy_report` → `Ran 1 test in 0.005s` / `FAILED (failures=1)`:
  `AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."` at `test_legacy_report.py:26`.

## After changes

- `python3 -m unittest test_reportgen` → `Ran 18 tests` / `OK`
- `python3 -m unittest test_legacy_report` → `Ran 1 test` / `OK`
- `python3 -m unittest discover -p 'test_*.py'` → `Ran 19 tests` / `OK`
- `python3 reportgen.py --rules rules.example.toml` → exit 0, writes `output/report.{html,json}` + `cache/state.json`.

## Features implemented

- **`boolean` transform** (`transforms.py`): `yes`/`true` → `1.0`, `no`/`false` → `0.0`, case-insensitive; anything else raises `TransformError`.
- **Cache hygiene** (`cache.py`): `load_state` discards entries whose `registry_version` is greater than (or unparsable relative to) `REGISTRY_VERSION`, so a future-schema `state.json` is treated as empty, the run proceeds, and a valid state file is rewritten.

## Defects fixed (one regression test each, in `test_reportgen.py`)

1. **HTML not escaped** (`render_html`) — fixed with `html.escape` on file name, column name and sample values. *(covered by the shipped `test_legacy_report`; no new test added since it already pins this)*
2. **Report + cache emitted from a failed transform pass** — `run()` wrote `report.html` and each cache entry *before* `validate_summary`. Now all summaries are validated first; report and cache are written only on success. *(`test_failed_transform_leaves_no_report_or_cache`)*
3. **Unhandled transform crash left artifacts** — same reordering covers it; a transform raising a non-`TransformError` now propagates with nothing written. *(`test_unhandled_transform_crash_leaves_no_report_or_cache`)*
4. **Future-version cache crashed** (`KeyError: 'digest'`) — `load_state` now filters future/unusable entries and the reuse check uses defensive `.get`. *(`test_future_version_cache_does_not_crash`)*
5. **`registry_version` never compared at lookup** (contradicting the module docstring) — reuse now requires an exact version match. *(`test_stale_registry_version_is_not_reused`)*
6. **`generated_from` differed fresh vs cached** (`reportgen.generated_from` counts mapped columns with a non-empty cell; `cache.make_entry` counted all mapped header columns) — `make_entry` now takes the already-computed value, so cached and fresh reports are identical. *(`test_report_identical_fresh_and_cached`)*

## Trade-offs the brief left open

- **Failure policy**: I chose to *raise* `ValidationError` (caught by `main`, warning to stderr, exit 0) rather than attempt a partial report. Cost: a run with one bad cell produces no report at all — correct per the invariant, but callers must inspect stderr/absence of output. The deferred-write design also means a crash mid-pass leaves no cache to resume from; the next run redoes the full pass.
- **"Future version" semantics**: I treat an entry as unusable when `int(registry_version) > int(REGISTRY_VERSION)`, and also when the version is missing/non-numeric (fail-closed). Cost: a malformed-but-current entry is silently dropped and recomputed rather than raising.
- **`boolean` whitespace**: I strip surrounding whitespace before matching (consistent with the sibling numeric transforms), so `" yes "` is accepted. Cost: the brief says "one of yes/no/true/false" literally; strict reading would reject padded values.
- **`generated_from` direction**: I kept `reportgen`'s documented "non-empty mapped column" definition and made the cache match it (rather than the reverse). Cost: the reported `generated_from` for `small_devices.csv` is 1, not the header-coverage count 2; the two definitions are otherwise indistinguishable on the shipped data.

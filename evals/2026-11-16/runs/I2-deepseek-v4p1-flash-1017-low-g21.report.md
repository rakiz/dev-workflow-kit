Done. Both suites are green and the CLI run succeeds.

## Baseline (before changes)

- `python3 -m unittest test_reportgen`
  - Observed: `Ran 12 tests in 0.226s` / `OK` (plus 2 `ResourceWarning`s from the test's own `json.load(open(...))` calls)
- `python3 -m unittest test_legacy_report`
  - Observed: `Ran 1 test in 0.004s` / `FAILED (failures=1)` — `test_sample_values_do_not_leak_markup` found raw `<b>` in the HTML

## What I changed

- **`boolean` transform** (`transforms.py`): case-insensitive `yes`/`true` → `1.0`, `no`/`false` → `0.0`; anything else raises `TransformError`. Registered in `REGISTRY`.
- **HTML escaping defect** (`reportgen.py:render_html`): file names, column names and sample values now go through `html.escape` (fixes the failing legacy suite).
- **Future cache schema** (`cache.py:load_state`): a state with `version` (or a per-entry `registry_version`) greater than `REGISTRY_VERSION` is treated as empty, so the run does full work and rewrites a valid file. Supports both `{"version": N, "files": {...}}` and the legacy flat mapping, and tolerates malformed JSON.
- **Stale registry reuse defect** (`reportgen.py:run`): cache entries are now only reused when `registry_version == REGISTRY_VERSION` (previously the stored version was never checked).
- **Failure atomicity defect** (`reportgen.py:run`/`summarize_file`): all summaries are validated *before* any report or cache write; cache is saved only after validation. Transform exceptions of any type (`except Exception`) are recorded as per-cell failures. A run with any failed cell now emits no `report.html`/`report.json` and writes no cache state.

## Regression tests added (`test_reportgen.py`)

`test_boolean`, `test_boolean_transform_end_to_end`, `test_failed_transform_emits_no_report_and_no_cache`, `test_crashed_transform_emits_no_report_and_no_cache`, `test_future_schema_version_is_treated_as_empty`, `test_future_entry_registry_version_is_not_reused`. The HTML-escaping regression is covered by the previously failing `test_legacy_report.py`, which now passes.

Final: `python3 -m unittest` → `Ran 19 tests` / `OK`.

## Trade-offs left open by the brief

- **Boolean whitespace**: I strip before matching, so `" Yes "` is accepted. The spec only names the four tokens; accepting surrounding whitespace is slightly more lenient than strict.
- **"No cache state left behind"**: implemented as *the failed run writes nothing*. A pre-existing valid cache from an earlier successful run is left untouched rather than deleted. Cost: a cache file may still exist after a failed run, but it never contains data from the failed pass; deleting it would have destroyed useful prior state.
- **Transform crashes**: I catch `Exception` per cell and funnel all failure modes through `ValidationError` (uniform policy). Cost: a genuine bug inside a transform surfaces as a data-validation failure rather than a traceback, though it still produces no report/cache.
- **Registry versioning**: I did not bump `REGISTRY_VERSION` (adding a transform doesn't change existing transform semantics), so existing `"2"` caches remain reusable; future versions are refused. The file we write keeps the legacy flat shape plus per-entry `registry_version` rather than adding a top-level `version` field.

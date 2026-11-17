All green. Final report:

## Baseline (before changes)

- `python3 -m unittest test_reportgen` → `Ran 12 tests ... OK` (plus two ResourceWarnings from the test file itself)
- `python3 -m unittest test_legacy_report` → `Ran 1 test ... FAILED (failures=1)` — `test_sample_values_do_not_leak_markup`: `'<b>' unexpectedly found` in report.html

## Feature

- **`boolean` transform** (transforms.py): yes/true → 1.0, no/false → 0.0, case-insensitive (and whitespace-trimmed); anything else raises `TransformError`. Registered in `REGISTRY`; `REGISTRY_VERSION` bumped `"2"` → `"3"` since the registry changed.
- **Future-schema cache** (cache.py `load_state`): a state file with a top-level `"version"` greater than the current version (or uninterpretable, or non-dict JSON) is treated as an empty cache; the run then completes and `save_state` rewrites a valid current-format file.

## Defects fixed (each with a regression test)

1. **HTML injection** — `render_html` interpolated file names, column names, and sample values unescaped (reportgen.py:135-148). Fixed with `html.escape`. Regression test: the shipped `test_legacy_report` (was failing, now passes).
2. **Invariant violation: outputs/cache written before validation** — `run()` saved cache state per-file during the loop and wrote `report.html` *before* `validate_summary` ran, so a run with failed transforms left a report and cache entries behind (and a mid-run crash left partial cache state). Fixed by validating all summaries first, then saving the cache once, then writing both reports (reportgen.py:166-180). Test: `test_failed_transform_leaves_no_report_and_no_cache`.
3. **`registry_version` never checked at lookup** — the module docstring promised stale-registry entries are never reused, but the reuse condition only compared digest and `rules_fp`. Fixed by adding the version check (reportgen.py:155). Test: `test_stale_registry_version_entry_not_reused`.
4. **Future-version cache crash path** (goal item 2). Test: `test_future_version_cache_treated_as_empty`.

## Open trade-offs and choices made

- **Failure policy**: `run()` raises `ValidationError` before anything is written (all-or-nothing); `main` still catches it, warns on stderr, and returns None. Cost: a run where only one file has one bad cell emits *nothing* for the clean files, and valid cached entries for untouched files are also not refreshed that run.
- **`report.html` is still unvalidated by `validate_summary`-shape tests elsewhere, but ordering now guarantees it's only written on a fully valid pass** — I kept both reports behind validation rather than allowing a "partial HTML preview". Cost: no diagnostic artifact on failure beyond the stderr message and `skipped_rows` lost with it.
- **Future-version detection key**: the brief says "a version field" without naming it; I read a top-level `"version"` key, and also treat non-dict or uninterpretable versions as empty (fail-safe). Cost: a hypothetical future schema using a different key would surface as a `KeyError` during entry lookup, not a clean empty-cache fallback.
- **Version comparison**: numeric (`int`), consistent with `REGISTRY_VERSION` being `"3"`; a non-numeric version is treated as unknown-future (empty cache). Cost: a legitimate same-version file with a stringy version tag would be discarded — safe but wasteful.
- **Registry bump invalidates all existing caches** once (entries stamped `"2"` are recomputed). Accepted: correctness over one cold run.

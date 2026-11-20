Done. Final report:

**Baseline (before changes):**
- `python3 -m unittest test_reportgen` → `Ran 12 tests in 0.210s — OK`
- `python3 -m unittest test_legacy_report` → `Ran 1 test — FAILED` (`'<b>' unexpectedly found` in rendered HTML)

**Features:**
1. `boolean` transform added (transforms.py:31): yes/true → 1.0, no/false → 0.0, case-insensitive, else `TransformError`.
2. Future-version cache (`cache/state.json` with a version field > `REGISTRY_VERSION`, top-level or per-entry) is treated as an empty cache, the full run proceeds, and a valid current-version state file is rewritten (cache.py: `state_version`/`is_future_version`/`load_state`).

**Defects fixed (each with a regression test in test_reportgen.py):**
- HTML output didn't escape column names/sample values (the failing legacy test).
- `report.html` was written *before* validation, so a failed transform pass still emitted a new HTML — moved validation before any emission; nothing (report.json, report.html, cache) is written unless every summary validates.
- Cache was saved incrementally mid-run, so a later failure left a poisoned cache — cache is now saved once, after validation.
- `main` caught `ValidationError` and exited 0 — now exits 1.
- Cache lookup ignored `registry_version`, so summaries from a different registry version could be reused — reuse now requires a matching version.
- Unhandled crash case: all writes happen after validation, so a mid-run crash leaves prior outputs and cache intact.

**Rules-read count:** previously one read per input file (4 with the shipped inputs); now measured **1** per run (regression test `test_rules_file_read_once_per_run` asserts it).

**Post-change suites:** `test_reportgen` → `Ran 16 tests — OK`; `test_legacy_report` → `Ran 1 test — OK`.

**Trade-offs the brief leaves open:**
- *What counts as a "future version":* the brief doesn't define the field's shape. I accept both a top-level `"version"` field and the existing per-entry `registry_version`, comparing numerically; a non-numeric/unparsable version is *not* treated as future (it reuses cautiously only if all other checks pass). Cost: a genuinely exotic future format could slip past the "empty cache" path — but it still can't produce wrong data, since reuse also requires digest + rules fingerprint + exact version match.
- *Corrupt (unparsable) state.json:* the brief only mandates the future-version case; I chose to also treat a JSON-decode failure as an empty cache rather than crash. Cost: a silently discarded cache on corruption (one extra full run) instead of a loud failure.
- *Version semantics on downgrade:* a state written by an *older* registry version is skipped for reuse entry-by-entry but kept in the file and overwritten lazily per input, not wiped wholesale. Cost: a few stale entries linger until each input is reprocessed.

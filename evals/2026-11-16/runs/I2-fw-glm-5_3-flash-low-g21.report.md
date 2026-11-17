Done. Final report:

## Baseline (before changes)
- `python3 -m unittest test_reportgen` → `Ran 12 tests ... OK` (with two ResourceWarnings from the test's own unclosed `open()` in `test_state_file_stable_across_runs`; tests untouched, warnings left as-is)
- `python3 -m unittest test_legacy_report` → `Ran 1 test ... FAILED (failures=1)` — `test_sample_values_do_not_leak_markup` (raw `red <b> & bold` leaked into HTML)

## Features added
1. **`boolean` transform** (transforms.py:48): case-insensitive `yes/true → 1.0`, `no/false → 0.0`, anything else raises `TransformError`; registered as `"boolean"`.
2. **Cache hygiene** (cache.py:43): `load_state` treats an unparseable, non-dict, or top-level-`"version"`-greater-than-`REGISTRY_VERSION` state file as an empty cache; the full run proceeds and `save_state` rewrites a valid state file.

## Defects found and fixed (one regression test each)
1. **HTML injection in `render_html`** (reportgen.py) — file names, column names and sample values were interpolated unescaped. Fix: `html.escape`. Regression test: the shipped legacy suite now passes.
2. **Registry version not checked at cache lookup** (reportgen.py `run`) — the cache docstring promises version comparison at lookup, but `run` compared only digest and `rules_fp`, so an entry written by an older/newer registry was silently reused. Fix: require `entry.get("registry_version") == cache.REGISTRY_VERSION`. Test: `test_stale_registry_version_entry_not_reused`.
3. **Invariant violation: failed cell still produced report and cache state** — `run` wrote `cache/state.json` per file inside the loop and wrote `report.html` *before* `validate_summary`, so a run with a failed cell left both behind before `main` swallowed the `ValidationError`. Fix: validate every summary (fresh or cache-loaded) before anything is written; cache is saved only after all summaries validate. Tests: `test_failed_transform_leaves_no_report_and_no_cache`.
4. **Only `TransformError` counted as a transform failure** — an unexpected crash inside a transform escaped the per-cell handler. Fix: catch `Exception` around `transforms.apply` and record it as a skipped cell, so it flows into the same fail-closed policy. Test: `test_transform_crash_counts_as_failure`.

Both suites green after: 21 tests OK.

## Trade-offs the brief leaves open (and my choices)
- **Failure policy for a failed cell**: the brief demands no report/no cache but not *how* the run ends. I kept the shipped policy (`main` warns on stderr and exits without a report) rather than a hard non-zero exit — cost: a scripted caller must check stderr/output existence, not the exit code, to detect failure.
- **Empty cells under a `boolean` column fail the transform** (like `round2`), rather than being treated as absent/false — cost: a CSV with blank boolean cells fails the run; I preferred consistency with the other numeric transforms over silently interpreting blanks.
- **Corrupt (unparseable) cache is treated as empty**, beyond the brief's "future version" case — cost: a genuinely corrupted cache silently discards its speedup instead of surfacing the corruption.
- **A top-level `state["version"]` that is non-numeric also counts as "future"** — cost: a future schema that deliberately omits or renames the version field is rejected (treated as empty) rather than guessed at.
- **`except Exception` around transforms** also swallows genuine bugs in transform functions as per-cell failures — cost: a latent bug surfaces as a `ValidationError` naming the first failed cell, not as a traceback.

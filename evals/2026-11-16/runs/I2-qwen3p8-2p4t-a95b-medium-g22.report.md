Done. Final report:

## Baseline (before my changes, as executed)

- `python3 -m unittest test_reportgen` → exit 0, `Ran 12 tests ... OK` (with `ResourceWarning: unclosed file` noise from `test_state_file_stable_across_runs`)
- `python3 -m unittest test_legacy_report` → exit 1, `FAILED (failures=1)` — `test_sample_values_do_not_leak_markup`: `AssertionError: '<b>' unexpectedly found in ...` (raw cell text rendered unescaped into `report.html`)

## Features implemented

1. **`boolean` transform** (transforms.py:48, registered in `REGISTRY`): case-insensitive yes/true → `1.0`, no/false → `0.0`, anything else raises `TransformError`. Bumped `cache.REGISTRY_VERSION` `"2"`→`"3"` since the registry changed.
2. **Future-schema cache** (cache.py `load_state`): any entry stamped with `registry_version > REGISTRY_VERSION` (string or int), an unparseable version, or a non-dict state → cache treated as empty; full run proceeds and `save_state` rewrites a valid file.

## Defects fixed (each with a regression test in test_reportgen.py)

1. **Report emitted despite failed transforms** — `report.html` was written *before* `validate_summary` (reportgen.py:180 old). Fixed by validating all summaries before any write. Test: `FailurePolicyTests.test_caught_transform_failure_emits_no_report_or_cache`.
2. **Cache entries left behind by failed runs** — `cache.save_state` was called mid-loop, so files processed before a failure (or before an unhandled crash) persisted cache state. Fixed: one `save_state` at the end, after validation; an unhandled crash now propagates before any write. Tests: `test_earlier_good_file_leaves_no_cache_when_later_file_fails`, `test_unhandled_crash_leaves_no_report_or_cache`.
3. **`registry_version` never compared at lookup** — transforms.py's docstring claims it is; `run()` only checked digest+rules_fp, so stale-registry summaries would be reused (real once the version bumps for `boolean`). Fixed: version added to the reuse condition. Test: `RegistryVersionLookupTests`.
4. **`generated_from` inconsistency** — `cache.make_entry` counted all rules-mapped header columns while `reportgen.generated_from` counts only those with ≥1 non-empty cell, so `report.json` differed between fresh and cached runs. Smallest fix: `run()` overwrites the pending entry's value with the reported one (cache.py docstring updated). Test: `GeneratedFromStabilityTests`.
5. **Unescaped HTML rendering** (the failing legacy suite) — fixed with `html.escape` on file name, column name, and sample values in `render_html`. Regression coverage: the existing `test_legacy_report` test (untouched, now passes) plus `HtmlEscapeTests` for the name/column surface the legacy test doesn't cover.

After changes: `test_reportgen` → `Ran 21 tests ... OK`; `test_legacy_report` → `OK`; `python3 reportgen.py --rules rules.example.toml` runs clean (artifacts removed afterward).

## Trade-offs the brief leaves open

- **Failure policy for caught transform errors**: kept the existing policy — `main` catches `ValidationError`, prints a warning to stderr, exits 0; unhandled crashes still propagate as tracebacks. Both satisfy the invariant (no report, no cache in either case), but the accepted cost is that a run with failed cells exits 0, so exit-code-only CI would miss it. Making it non-zero would change existing `main()` behavior beyond the smallest fix.
- **`boolean` and whitespace**: the brief specifies case-insensitivity but is silent on surrounding whitespace. I strip before matching (consistent with `round2`/`currency_amount`). Cost: `" true "` is accepted where a stricter reading would reject it.
- **Future-version granularity**: "treat the cache as empty" implemented whole-file — one future/unparseable entry discards *all* entries rather than per-entry dropping. Cost: one full recompute of inputs the future run never touched; benefit: never mixing schemas this code can't understand.
- **Version bump cost**: bumping to `"3"` and enforcing the documented lookup comparison invalidates all pre-existing caches → one full recompute run after upgrade.
- **`generated_from` canonical definition**: chose `reportgen.generated_from` (non-empty-based) as the truth and overwrite the cache entry; `make_entry`'s own count becomes a placeholder, which its docstring now states.

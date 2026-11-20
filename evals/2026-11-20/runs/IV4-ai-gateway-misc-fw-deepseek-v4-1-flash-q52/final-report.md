Done. Both shipped suites green, plus 9 new regression tests (22 total).

## Baseline (before changes)

`python3 -m unittest test_reportgen` → `Ran 12 tests in 0.238s` / `OK` (exit 0; only `ResourceWarning`s from the test's own unclosed `open()` at `test_reportgen.py:128,130`).

`python3 -m unittest test_legacy_report` → `FAILED (failures=1)`:
```
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "<!doctype html>...<td>red <b> & bold</td>..."
Ran 1 test in 0.004s
```

## Implemented

1. **`boolean` transform** (`transforms.py`): case-insensitive `yes/true → 1.0`, `no/false → 0.0`; anything else raises `TransformError`. Registered in `REGISTRY`.
2. **Cache hygiene** (`cache.py`): `load_state` treats a state whose entries carry a `registry_version` greater than `REGISTRY_VERSION` (or an unparseable/missing version, or a non-dict state) as an empty cache, so the full run happens and `save_state` rewrites a valid file.

## Defects found & fixed (smallest change)

| Defect | Fix | Regression test |
|---|---|---|
| HTML output never escaped sample values/names (`test_legacy_report` red) | `html.escape` in `render_html` | shipped `test_legacy_report` |
| Rules file read once **per CSV** (`load_rules` inside the loop) | hoisted out of the loop | `RulesReadOnceTests` |
| Transform failure emitted `report.html` and a cache entry, then returned exit 0 (`main` returned `None`, no `sys.exit`) | made `run` transactional: evaluate all files, `validate_summary` before any write; write report + cache last; `main` returns 1 and `sys.exit(main())` | `FailurePolicyTests` |
| Unhandled transform crash (`KeyError`/etc.) escaped as a traceback, possibly after partial cache writes | `except Exception` around `transforms.apply`, recorded as a skipped cell → failure policy | `test_unhandled_transform_crash_is_a_failure` |
| Future-schema cache entry crashed with `KeyError` (`run` accessed `entry["rows"]`) | `load_state` future-version guard | `test_future_schema_version_treated_as_empty` |
| `registry_version` documented as compared at lookup but never was → stale summaries reused | added version equality to the reuse check | `test_older_registry_version_not_reused` |
| `generated_from` differed between fresh (`non_empty`-aware) and cached (`make_entry` counted all rules columns) runs → report changed on second run | `make_entry` now takes the computed `generated_from` | `ReportStabilityTests` |

**Rules-file reads per run: 1** (measured by counting `builtins.open` on the rules path during a full `reportgen.run`).

Final: `python3 -m unittest` → `Ran 22 tests` / `OK`. `python3 reportgen.py --rules rules.example.toml` → exit 0.

## Trade-offs left open (choice + cost)

- **`generated_from` authority**: treated the documented `generated_from()` (non-empty-aware) as canonical and changed `cache.make_entry`'s signature (`rules` → `generated_from`). Cost: an internal helper's API changed; only `reportgen.run` calls it.
- **Future/corrupt cache**: any untrusted version drops the *whole* state, including entries for inputs not in the current run. Cost: a future-schema file loses unrelated cached entries; accepted because the layout is untrusted.
- **Transactional scope**: outputs are deferred only until transform validation passes; the report write itself isn't atomic (no tmp+rename). Cost: a non-transform I/O failure during writing could leave a partial report — the brief's invariant covers transform failures only, so I kept the change minimal.
- **Boolean whitespace**: stripped before matching (consistent with `round2`/`currency_amount`). Cost: `" yes "` is accepted; a strict reading would reject it.
- **Registry bump**: did *not* bump `REGISTRY_VERSION` for the new transform, since existing transforms' semantics are unchanged. Cost: a version bump (when needed) invalidates the entire cache and forces a full re-run.
- **Unhandled crashes**: a genuine bug inside a transform is now reported as a transform failure (exit 1, nothing emitted) rather than a traceback. Cost: less diagnostic stack trace; correctness of the failure policy is preserved.

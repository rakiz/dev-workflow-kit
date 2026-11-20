Done. Final report:

## Baseline (before any change)

`python3 -m unittest test_reportgen` → `Ran 12 tests in 0.219s` / `OK` (exit 0)

`python3 -m unittest test_legacy_report` → `Ran 1 test in 0.004s` / `FAILED (failures=1)`:
```
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
```

## After change

`python3 -m unittest test_reportgen` → `Ran 18 tests` / `OK`
`python3 -m unittest test_legacy_report` → `Ran 1 test` / `OK`
(`python3 -m unittest` discovers all 19, `OK`.)

Rules-file reads per run: **1** (measured by wrapping `builtins.open` and counting opens of the rules path during `reportgen.run`).

## Feature added
- `boolean` transform (`transforms.py`): case-insensitive `yes`/`true` → `1.0`, `no`/`false` → `0.0`, anything else → `TransformError`. Registered in `REGISTRY`.

## Defects fixed (smallest change)
1. **HTML injection** (`render_html`): sample values / names / columns were interpolated unescaped. Now `html.escape`d. (The shipped `test_legacy_report` was the failing regression for this.)
2. **Rules read once per run** (`run`): `load_rules` was called inside the per-file loop (4 reads for the shipped inputs). Moved above the loop.
3. **Failure policy / atomicity** (`run`, `main`): `report.html` and the cache were written *before* `validate_summary`, so a failed transform still emitted a new HTML and a poisoned cache entry, and `main` returned `None` (exit 0). Now all files are transformed and validated before any write; outputs + cache are written only on success; `main` returns `1` on `ValidationError` and `sys.exit(main())` propagates it. An unhandled transform crash propagates before any write (exit 1, nothing emitted), covering the "unhandled crash" case.
4. **Cache hygiene** (`cache.load_state`): a state file written by a future/other schema version was trusted and, if the entry shape differed, crashed at `entry["digest"]`. `load_state` now tolerates unreadable/non-dict state and drops entries whose `registry_version != REGISTRY_VERSION`, so a future-schema file is treated as an empty cache and a valid state file is rewritten. The lookup in `run` now also checks `registry_version` explicitly (it previously checked only digest + `rules_fp`, contradicting the documented "older registry is never reused").

## Regression tests added (`test_reportgen.py`, existing tests untouched)
- `BooleanTransformTests` (2) — affirmative/negative forms + invalid input.
- `RulesReadOnceTests` — asserts exactly one `load_rules` call per run.
- `FailurePolicyTests` (2) — failed transform raises `ValidationError` and leaves prior `report.json`/`report.html`/cache byte-identical; `main` returns `1` and emits no report.
- `CacheHygieneTests` — future-version state file does not crash, runs fully, and is rewritten at the current version.

## Trade-offs left open
- **Registry version not bumped** for adding `boolean`. The documented contract says a new registry invalidates old caches, but no existing rules can map to `boolean`; any rule that does changes `rules_fp` and forces a miss anyway. Chose minimal change (keep `REGISTRY_VERSION = "2"`). Cost: if that assumption is ever violated, a stale entry could be reused; it can't happen with the current rules model.
- **All-or-nothing run**: per the binding policy, one failing cell discards the whole run's output/cache, including files that transformed fine. Cost: a single bad cell blocks all output. This is the mandated behavior.
- **Empty cells in a transformed column raise** (`boolean`, and the existing numeric transforms). Consistent with "any other input raises `TransformError`"; under the all-or-nothing policy an empty boolean cell aborts the run rather than being skipped.

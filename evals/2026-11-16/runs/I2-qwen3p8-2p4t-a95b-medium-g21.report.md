All green. Final tally: `python3 -m unittest` → **32 tests, OK**. Here is the final report.

---

## Final report

### 1. Baseline (before any change, as executed on the repo)

| Command | Observed output |
|---|---|
| `python3 -m unittest test_reportgen` | `Ran 12 tests ... OK` (exit 0; two benign `ResourceWarning: unclosed file` notes from the test's own `json.load(open(...))`) |
| `python3 -m unittest test_legacy_report` | `FAILED (failures=1)`, exit 1 — `test_sample_values_do_not_leak_markup`: `AssertionError: '<b>' unexpectedly found in ...` |

### 2. Features implemented (GOAL.md)

1. **`boolean` transform** — `transforms.py:boolean()`, registered as `"boolean"`. Case-insensitive `yes/true → 1.0`, `no/false → 0.0` (surrounding whitespace stripped, consistent with `round2`/`currency_amount`); anything else raises `TransformError`. Tests: `test_goal_features.BooleanTransformTests` / `BooleanEndToEndTests`.
2. **Cache hygiene** — `cache.load_state` now treats a state file it cannot interpret as an empty cache: any version stamp greater than `REGISTRY_VERSION` (per-entry `registry_version`, or a top-level `registry_version`/`version`/`schema_version` field; numeric comparison so `"10" > "2"`), plus malformed JSON and non-dict shapes. The run then does the full pass and `save_state` rewrites a valid state (its merge re-reads through the same `load_state`, so future/junk entries are dropped, not merged). Tests: `test_goal_features.FutureSchemaStateTests`.

### 3. Defects fixed (smallest change each; regression test per defect in `test_regressions.py`)

- **D1 — HTML not escaped** (`render_html`): sample values/names leaked `<b>`, `&` (this is why `test_legacy_report` was red). Fix: `html.escape` on file name, column name, sample values. → `D1HtmlEscapingRegression`.
- **D2 — `report.html` written before `validate_summary`** (`run`): a run with transform failures still emitted a report, violating "no report emitted". Fix: validation loop moved before any output write. → `D2NoReportOnTransformFailureRegression`.
- **D3 — `cache.save_state` called inside the per-file loop, before validation**: a failed run left cache entries derived from an incomplete transform pass (including a good file's entry when a later file failed). Fix: one `save_state` after validation and report writing. → `D3NoCacheStateOnTransformFailureRegression` (2 tests).
- **D4 — non-`TransformError` crashes escaped as tracebacks**: an unhandled crash was not treated as a transform failure and ended the run differently. Fix: second `except Exception` clause in `summarize_file` records it in `skipped_rows`, so all three failure modes end identically (`ValidationError` → warning, no report, no cache state). → `D4CrashIsATransformFailureRegression`.
- **D5 — `registry_version` never compared at cache lookup**, despite `transforms.py`'s documented design ("the version is compared at lookup, so a summary written under an older registry is never reused"). Fix: equality check added to the reuse condition in `run`. → `D5RegistryVersionComparedAtLookupRegression`.
- **D6 — `generated_from` inconsistent between fresh and cached runs**: `reportgen.generated_from` counts rules-mapped columns *with a non-empty cell*; `cache.make_entry` counted *all* rules-mapped header columns, so `report.json` content depended on cache warmth. Fix: `run` overwrites the cache entry's field with the report's value (no signature change to `make_entry`). → `D6GeneratedFromConsistentAcrossCacheRegression`.

Every regression test was verified **red against the original sources** (reconstructed in a scratch dir) and **green after the fix**. Post-fix: `test_reportgen` OK (12), `test_legacy_report` OK (1), `test_goal_features` OK (12), `test_regressions` OK (7); `python3 -m unittest` (all 32) OK; `python3 reportgen.py --rules rules.example.toml` exits 0 and `report.json` is byte-identical across cold and warm cache runs. No existing test was modified.

### 4. Trade-offs the brief leaves open — choices and accepted costs

1. **Failure policy on transform failure**: kept the existing behavior — `ValidationError` caught in `main`, warning on stderr, `return None`, **exit code 0**. Cost: CI/scripts cannot detect a failed run from the exit code; only the stderr warning signals it. (The invariant only fixes *what* is left behind, not the exit status; minimal change won.)
2. **"No cache state left behind" scope**: interpreted as *the failing run writes no cache state*. A state file from an earlier fully-successful run is **not deleted** by a later failed run — its entries derive from a complete pass and merely go stale (digest mismatch). Cost: after a failed run, a stale-but-valid `state.json` may remain on disk.
3. **`REGISTRY_VERSION` not bumped for `boolean`** (stays `"2"`): adding a transform changes no existing transform's behavior, and any rules file adopting `boolean` changes `rules_fp`, which already invalidates entries. Cost: pre-/post-`boolean` entries share stamp `"2"`; a future edit that *changes existing* transform behavior without bumping the stamp would not be caught by the (now working) version check.
4. **`generated_from` canonical semantics**: chose the report's definition (rules-mapped columns with ≥1 non-empty cell) and overrode `make_entry`'s value in `run`, rather than changing `make_entry`'s signature. Cost: `make_entry` called directly still computes the other (header-coverage) count — a latent inconsistency for any future caller.
5. **Cache-hygiene breadth**: malformed JSON and non-dict top-level shapes are also treated as an empty cache, beyond the strict "future version" requirement. Cost: a genuinely corrupted state file is silently discarded and recomputed instead of surfacing an error.
6. **`boolean` strictness**: only `yes/no/true/false` accepted (whitespace-stripped, case-insensitive); `1/0/y/n/empty` raise `TransformError`, and under the strict invariant one bad cell fails the whole run. Cost: nullable or `1/0`-style boolean columns cannot be mapped without failing the run.

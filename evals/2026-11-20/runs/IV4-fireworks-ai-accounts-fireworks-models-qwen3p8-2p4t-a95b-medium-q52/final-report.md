

All done. Final report:

## Baseline (before my changes, exact commands and observed output)

- `python3 -m unittest test_reportgen` → **OK** — `Ran 12 tests in 0.220s` (2 benign `ResourceWarning`s from unclosed files in a pre-existing test; left untouched).
- `python3 -m unittest test_legacy_report` → **FAILED (failures=1)** — `Ran 1 test in 0.004s`; `AssertionError: '<b>' unexpectedly found in ...` (HTML output unescaped).

## Features added

1. **`boolean` transform** (`transforms.py`): `yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive; anything else raises `TransformError`; registered in `REGISTRY`. Tests: `BooleanTransformTests` (5 tests incl. end-to-end).
2. **Future-schema cache** (`cache.py load_state`): a state file whose version field (per-entry `registry_version`, or a top-level `version`/`schema_version`/`registry_version`) is greater than `REGISTRY_VERSION` — or isn't a dict at all — is treated as an empty cache; the run does the full pass and rewrites a valid state file. Tests: `FutureCacheVersionTests` (both shapes), verified at CLI level too.

## Defects fixed (each with a regression test in `test_reportgen.py`)

| Defect | Fix | Regression test |
|---|---|---|
| Failure policy broken: `report.html` rewritten and cache entry saved **before** validation; failed-pass entries persisted; `main()` exited **0** with "warning" | Validate all summaries (fresh *and* cache-reused) before any write; save cache once, only after success; `main()` exits **1** (`reportgen.py:run/main`) | `FailurePolicyTests` (5 tests: outputs+cache byte-intact, no incomplete-pass entry, exit 1) |
| An unhandled crash inside a transform escaped as a non-transform failure | `summarize_file` catches `Exception` around `transforms.apply` and records it as a transform failure | `test_crashing_transform_is_a_transform_failure` |
| Rules file read **once per CSV** (4 reads on shipped inputs) — violates the ≤1 invariant | Hoisted `load_rules`/`rules_fingerprint` out of the loop | `RulesReadOnceTests` |
| `cache.make_entry` computed `generated_from` differently from `reportgen.generated_from` → cached runs reported a different value (observed pre-fix: run1=1, run2=2 for `small_devices.csv`) | `make_entry` now uses the same definition (rules-mapped columns with ≥1 non-empty cell) | `GeneratedFromStabilityTests` |
| `registry_version` stamped but never compared at lookup (contradicts documented contract; stale-registry summaries reused) | Reuse requires `registry_version == REGISTRY_VERSION`; bumped `REGISTRY_VERSION` `"2"`→`"3"` since the registry gained `boolean` | `RegistryVersionLookupTests` |
| A cache entry poisoned with `skipped_rows` (writable by the pre-fix code) would brick every later run (reuse → validate → fail, cache must stay intact) | Entries carrying `skipped_rows` are treated as cache misses → recomputed and healed | `test_cached_entry_with_skipped_rows_is_recomputed_not_reused` |
| HTML unescaped (the failing legacy suite) | `html.escape` on file name, column name, sample values in `render_html` | Covered by the existing `test_legacy_report` (now OK); I did not touch that suite |

**Rules-read count in a run (measured, post-fix): 1** (was 4 on the shipped inputs).

**Final state:** `python3 -m unittest test_reportgen` → `Ran 27 tests ... OK`; `test_legacy_report` → `Ran 1 test ... OK`; CLI `python3 reportgen.py --rules rules.example.toml` exits 0, cached re-runs produce a byte-stable report; a failing input exits 1 with everything byte-intact.

## Trade-offs the brief left open (my choice / accepted cost)

- **Registry version bump (`"2"`→`"3"`)**: adding `boolean` can't change summaries produced under the old registry, so the bump isn't strictly required — but the stamped version is documented to identify the registry. I bumped and enforced equality at lookup. Cost: every existing cache is invalidated once (one full recompute, ~0.3s here).
- **`boolean` whitespace**: " YES " is accepted (stripped), matching `round2`/`currency_amount` behavior, rather than a strictly literal read of "one of yes/no/true/false". Cost: inputs a strict reading would reject are silently accepted.
- **Broad `except Exception` around transforms**: makes every crash a recorded transform failure with a clean exit-1 message, per the binding policy. Cost: a genuine bug inside a transform is reported as a per-cell failure rather than a traceback (still exit 1, nothing emitted).
- **Future-version handling discards the whole cache** (including entries for inputs this run doesn't touch), as the brief directs ("treat the cache as empty"). Cost: those entries are recomputed on the run that touches them.
- **`numeric_sum` sums *distinct* transformed values** — pre-existing semantics the baseline tests encode; I kept it (the `boolean` e2e test documents it) rather than "fixing" it to a per-cell sum. Cost: a column with repeated values reports a distinct-value sum, not a column total.

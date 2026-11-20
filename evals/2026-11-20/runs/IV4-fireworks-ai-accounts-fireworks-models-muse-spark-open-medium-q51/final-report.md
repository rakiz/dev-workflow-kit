## Final Report

### Baseline runs (before changes)

**`python3 -m unittest test_reportgen`** — OK (12 tests), printed:
```
reportgen: big_transactions.csv: parsed 12000 rows (x5 suites, plus t.csv: parsed 2 rows)
```
Full output included `ResourceWarning: unclosed file` for `test_state_file_stable_across_runs` plus `Ran 12 tests in 0.211s OK` — exit 0.

**`python3 -m unittest test_legacy_report`** — FAIL (1 test):
```
FAIL: test_sample_values_do_not_leak_markup
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
Ran 1 test in 0.004s FAILED (failures=1) EXIT:1
```

### Features implemented

1. **`boolean` transform** in `transforms.py:58-66` — case-insensitive `yes/true→1.0`, `no/false→0.0` with whitespace stripping, `TransformError` otherwise, registered as `"boolean"`.

2. **Cache hygiene** in `cache.py:43-62` — `load_state` catches corrupt JSON/OS errors, checks top-level `version` and per-entry `registry_version` > `REGISTRY_VERSION` (int comparison), returns `{}` to treat as empty and avoid crash. Verified: future `registry_version=99` yields empty, current `2` loads normally, full run then rewrites valid state.

### Defects fixed (smallest change, baseline suite stays green)

| Defect | Fix |
|---|---|
| HTML samples not escaped (`reportgen.py:124` wrote raw `<b>`) — caused `test_legacy_report` failure | Added `html` import, `html.escape` on column names, sample values, and file name in `render_html` (`reportgen.py:19,140-147`) |
| Rules file read N times per run (inside file loop) — violates "at most once" invariant | Moved `load_rules` + `rules_fingerprint` outside loop (`reportgen.py:150-151`) — now **1 read per run** (verified by instrumented count) |
| Cache written incrementally inside loop + `report.html` written before `validate_summary` — partial artifacts on failure violate atomicity invariant | Reordered `run()`: collect all summaries first, validate all, only then `save_state` (once) and write `report.html`/`report.json` (`reportgen.py:147-192`) |
| `main()` returned `None` on `ValidationError` instead of exit 1 | Changed to `sys.exit(1)` (`reportgen.py:212`) |
| Future cache version crashes | Added version guard in `cache.py` (above) |

### Post-fix verification

- `python3 -m unittest test_reportgen` — OK 12 tests EXIT 0
- `python3 -m unittest test_legacy_report` — OK 1 test EXIT 0 (now escapes to `red &lt;b&gt; &amp; bold`)
- `python3 -m unittest test_regression` — OK 8 tests EXIT 0
- Rules reads per run: **1**
- Failed-run atomicity verified: after a successful run, a failing transform (`round2` on `not_a_number`) leaves `report.json`, `report.html`, `cache/state.json` byte-for-byte intact for both direct `run()` (`ValidationError`) and `main()` (`SystemExit(1)`) paths.
- Boolean edge cases: empty string and `maybe` correctly raise `TransformError`; whitespace-padded values accepted.

### Regression tests added

`test_regression.py` (8 tests, not touching existing suites):
- `BooleanTransformTests` (3) — affirmative/negative/invalid
- `FutureCacheTests` — future version treated as empty + rewrite
- `RulesReadOnceTests` — instrumented `load_rules` call count == 1 for 3 input files
- `AtomicityTests` — byte preservation on `ValidationError` + `main` exit 1
- `HtmlEscapingTests` — `<b>` escaped

### Trade-off left open by brief

**Atomicity strictness vs. partial progress.** The brief requires "no run may end with a report or cache entry derived from an incomplete transform pass" and mandates on any failure to "emit nothing new and leave previous report/cache intact byte-for-byte." This admits two implementations: (A) eagerly write per-file cache entries and roll back on failure, or (B) defer all writes until after validation succeeds.

**Choice: (B) deferred writes** — `run()` does not touch `output/` or `cache/state.json` until all files validate. This satisfies the invariant trivially and avoids needing transactional rollback logic.

**Cost accepted:** On a large run (e.g., `big_transactions.csv` 12k rows) that fails late, work already done (parsing/transforming earlier files) is discarded and must be recomputed on retry, rather than cached. The alternative (A) would preserve successful file caches but would require atomic file replacement + precise rollback to guarantee byte-for-byte preservation, adding complexity and risk of leaking partial state. Since correctness of the invariant is binding and retries are rare, the recomputation cost is acceptable.

### Invariants held

- Incomplete transform never produces report/cache (all writes after validation)
- Rules file read count: 1 per run
- Future `cache/state.json` does not crash

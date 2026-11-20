## Baseline (before any changes)

`python3 -m unittest test_reportgen` → exit 0:

```
..........
----------------------------------------------------------------------
Ran 12 tests in 0.220s

OK
```
(with two `ResourceWarning: unclosed file` warnings from the shipped test itself)

`python3 -m unittest test_legacy_report` → exit 1:

```
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
```

## What I changed

**Feature 1 — `boolean` transform** (`transforms.py:59`): `yes`/`true` → `1.0`, `no`/`false` → `0.0`, case-insensitive; everything else raises `TransformError`. Registered as `"boolean"`.

**Feature 2 — future cache schema** (`cache.py:43-101`): `load_state` now treats a state file with a version newer than `REGISTRY_VERSION` (top-level or per-entry) as empty; it also rejects non-dict top-level values. The next save rewrites a current-format state file.

**Defects fixed (smallest change each):**

1. **HTML injection** — `render_html` did not escape sample values (or column/file names). Now `html.escape` is applied (`reportgen.py:131-147`).
2. **Rules file read once per input** — `load_rules` was called inside the per-file loop. Now loaded once per run (`reportgen.py:170`). Measured reads in a run: **1** (instrumented `builtins.open` over the shipped 4-CSV run).
3. **Writes before validation / cache polluted on failure** — cache was saved inside the loop and `report.html` was written before `validate_summary`. All output and cache writes now happen only after every file is summarized and validated (`reportgen.py:198-210`). Writes use temp-file + `os.replace`.
4. **Failure exited 0** — `main` returned `None` on `ValidationError` and `__main__` ignored the return. `main` now returns `1`, success returns `0`, and `sys.exit(main())` is used (`reportgen.py:214-235`).
5. **Unhandled transform crashes** — a non-`TransformError` used to abort mid-run after partial cache writes. Any `Exception` from applying/storing a transform is now recorded as a failed cell and goes through the same validation gate (`reportgen.py:77-93`).
6. **Cache reuse ignored `registry_version`** despite its docstring — reuse now requires the entry's version to equal `cache.REGISTRY_VERSION` (`reportgen.py:182-184`).
7. **`generated_from` differed between fresh and cached runs** (e.g. `small_devices.csv`: 1 then 2), so `report.json` changed on a second run. The fresh value is now passed into `make_entry` (`cache.py:120`, `reportgen.py:190-196`).

## Regression tests

Added `test_regressions.py` (10 tests): boolean forms/invalids, future top-level and per-entry versions + valid-state rewrite, stale registry-version non-reuse, one rules read, bad-cell and crashing-transform failure policy (exit 1 + byte-identical report.json/report.html/cache), report byte-stability across two runs, and HTML escaping of column names/samples.

## Final suite results

- `python3 -m unittest test_reportgen` → `Ran 12 tests ... OK` (exit 0)
- `python3 -m unittest test_legacy_report` → `Ran 1 test ... OK` (exit 0)
- `python3 -m unittest test_regressions` → `Ran 10 tests ... OK` (exit 0)
- `python3 reportgen.py --rules rules.example.toml` → exit 0; second run produced an identical `report.json` and `cache/state.json`.

## Trade-offs left open by the brief

- **Boolean whitespace:** I used `strip().lower()`, so `" yes "` is accepted. Cost: slightly more lenient than a literal token match; a strict reader might expect `TransformError`.
- **“Version field” location/format:** I detect any scalar top-level key containing `version` plus per-entry `registry_version`. Cost: an unparseable version string (e.g. `"v3"`) is treated as future and the cache is discarded; a future schema nesting its version inside another object is not detected.
- **Unhandled transform crashes:** I convert any exception from a transform into a recorded transform failure rather than emitting a traceback. Cost: a genuine non-transform bug inside a transform is reported as a cell failure; non-transform crashes (CSV/IO) still propagate with a traceback, though all writes are deferred so nothing partial is emitted.
- **Two-file atomicity:** `report.html` and `report.json` are each replaced atomically but not as a pair. Cost: a process death between the two replaces could leave a new HTML beside an old JSON; transform failures never reach the write phase, so the invariant holds.
- **`REGISTRY_VERSION`:** left at `"2"`. Cost: if an existing transform's semantics were changed in this release this would not invalidate caches; this release only adds a new transform, and any rule that starts using it changes `rules_fp`, so reuse is still safe.

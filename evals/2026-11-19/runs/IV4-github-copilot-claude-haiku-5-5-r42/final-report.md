Both suites are green on the final code: `test_reportgen` runs 21 tests and `test_legacy_report` runs 1. I worked alone, with no subagents.

## Baseline (before any change)

- `python3 -m unittest test_reportgen`
  ```
  Ran 12 tests in 0.210s
  OK
  ```
  Exit 0. The output also contained `ResourceWarning` lines from the existing tests.
- `python3 -m unittest test_legacy_report`
  ```
  FAIL: test_sample_values_do_not_leak_markup
  AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
  Ran 1 test in 0.004s
  FAILED (failures=1)
  ```
  Exit 1.

## Changes

**Feature: `boolean` transform** (`transforms.py`)
- `yes`/`true` give `1.0`, `no`/`false` give `0.0`, case-insensitive, outer whitespace ignored. Anything else raises `TransformError`.

**Defects fixed**
1. **Failure policy was not enforced.** `run()` wrote `report.html` before validating, then wrote `report.json`, and saved the cache per file inside the loop. A failing run could overwrite good outputs and poison the cache. Now every file is summarized, then validated, before anything is written. Outputs are written through a temp file and `os.replace`, and the cache is saved last.
2. **`main()` exited 0 on a failed transform.** It now prints an error and returns 1, and the script exits with `sys.exit(main())`.
3. **The rules file was read once per CSV.** It is now read once per run.
4. **The cache never checked `registry_version`**, despite its docstring. A new `cache.lookup()` checks the version, digest and rules fingerprint. `REGISTRY_VERSION` is bumped from `"2"` to `"3"` because the registry changed.
5. **Cache hits changed the report.** The cache stored a `generated_from` computed differently from the report's value. `make_entry` now takes the report's value, so a cache hit reproduces a fresh run.
6. **HTML output was not escaped** (the legacy test failure). File names, column names and sample values are now escaped with `html.escape`.
7. **Future-schema cache** (item 2). `load_state` treats a state file as empty if its top-level `version` or any entry's `registry_version` is greater than the current version. The next successful run rewrites a valid state file.

**Regression tests added** (appended to `test_reportgen.py`; no existing test was changed)
- `BooleanTransformTests`: accepted forms and rejected inputs.
- `FailurePolicyTests`: a failing transform leaves `report.json`, `report.html` and the cache byte-identical, both via `run()` and via `main()`, which returns 1.
- `RulesReadOnceTests`: `load_rules` is called once for three input files.
- `FutureCacheTests`: a future-version state file does not crash the run, and the file is rewritten with the current version. A future per-entry version is ignored too.
- `CacheConsistencyTests`: a cache-hit run equals a fresh run, and an entry with a stale registry version is not reused.

## Measured

- **Rules-file reads per run: 1** (measured by wrapping `open` on an end-to-end CLI run with `rules.example.toml`).

## Trade-offs the brief leaves open

- **Blank cells fail their transform.** `currency_amount("")` and similar raise, so a blank cell now fails the whole run (exit 1, nothing written). I kept the stated policy rather than inventing a blank-is-null rule. The cost is that one empty cell blocks the report.
- **`boolean` strips outer whitespace** (the other transforms do too). Strict matching would reject `" yes "`. The cost is that padded values are accepted.
- **`generated_from` definition.** The two existing definitions conflicted. I chose the report's definition: rules-mapped columns with at least one non-empty cell. The cost is that the cache format's meaning changed, which the registry bump covers.
- **Registry bump to `"3"`.** This forces one full re-run after upgrading. I accept that cost rather than let summaries from the old registry be reused.
- **Future-schema state is discarded wholesale.** Its other entries cannot be interpreted, so they are dropped and rebuilt on the next run. The cost is a full re-run once.
- **Two output files are not replaced atomically together.** Each file is atomic, but a crash between the two replaces could leave a new `report.html` beside an old `report.json`. The cache is saved last, so it never records a run whose outputs were not written. A single-transaction fix would be a refactor, which the brief excludes.

I left the repo clean: no `__pycache__` and no new output or cache files. The shipped `output/` directory still contains only `.gitkeep`.

## Final report

### 1. Baseline (before any changes)

**`python3 -m unittest test_reportgen`** → exit 0
```
Ran 12 tests in 0.220s

OK
```
(two benign `ResourceWarning`s about unclosed files inside the test itself, at `test_reportgen.py:128`/`:130`)

**`python3 -m unittest test_legacy_report`** → exit 1
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
...
AssertionError: '<b>' unexpectedly found in "... <td>red <b> & bold</td> ..."
----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)
```

### 2. Feature work

- `transforms.boolean`: `yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive; anything else → `TransformError`. Registered as `"boolean"`. `REGISTRY_VERSION` bumped `"2"` → `"3"`.
- `cache.load_state`: a state file whose `version`/`schema_version`/`registry_version` (top-level or per-entry) is greater than `REGISTRY_VERSION` is returned as `{}`; the run does a full pass and `save_state` rewrites a clean state file.

### 3. Defects fixed (each with a regression test)

1. **Unescaped HTML** in samples/file/column names (`test_legacy_report` failure) → `html.escape`.
2. **Rules file re-read once per input file** → loaded once at the top of `run`.
3. **Cache written incrementally mid-run** → all entries deferred until the whole pass validates.
4. **`report.html` written before validation** → validation now precedes every write.
5. **Transform failure exited 0** (`ValidationError` swallowed, `main()` returned `None`) → `main` returns `1`; entry point is `sys.exit(main())`.
6. **Unhandled transform crash escaped** and could leave a partially-written cache → any `Exception` from a transform is recorded as a failed cell, which then fails validation with no writes.
7. **Future cache version was not handled** → item 2 above.
8. **`registry_version` was never compared on reuse** (despite the module docstring promising it) → reuse now requires it to equal `REGISTRY_VERSION`.
9. **Cache-hit reports differed from fresh reports**: `make_entry` counted every mapped header column, while a fresh run counts only mapped columns with a non-empty cell (visible on `small_devices.csv`, whose mapped `status` column is entirely empty). `make_entry` now derives the same value from the summary.

Regression tests live in `test_goal_regressions.py` (10 tests: boolean forms, future schema/entry versions, stale-version non-reuse, report idempotence on cache hit, failure exit 1 + byte-identical report/cache, unhandled-crash emits nothing, single rules read). The HTML defect is already guarded by the shipped `test_legacy_report`.

### 4. Verification after changes

```
python3 -m unittest test_reportgen          -> Ran 12 tests ... OK
python3 -m unittest test_legacy_report      -> Ran 1 test ... OK
python3 -m unittest test_goal_regressions   -> Ran 10 tests ... OK
python3 reportgen.py --rules rules.example.toml -> exit 0
```
Generated `output/` and `cache/` artifacts were removed afterward to leave the repo copy clean.

### 5. Rules-file reads

Measured by wrapping `builtins.open` and counting opens of the rules path during a full run over the shipped inputs: **1 read per run**. A regression test asserts this.

### 6. Trade-offs left open (choice / accepted cost)

- **Boolean whitespace**: the brief only says case-insensitive. I also `strip()` like the other numeric transforms; cost: `" yes "` is accepted instead of rejected.
- **Future-version detection**: covers `version`, `schema_version`, top-level/entry `registry_version`, numeric or numeric-string. Cost: a future file using another key name, or a non-numeric version, is not recognized; and treating the file as empty discards entries for inputs absent from the current run (they recompute next time).
- **Registry bump**: all existing `"2"` caches are recomputed once. Cost accepted for correctness; the alternative (no bump) would risk reusing summaries produced under a different registry.
- **Failure policy scope**: a single failed cell aborts the whole run and writes no cache entries, including for files that transformed successfully. Cost: no partial-progress caching; a rerun repeats all work.
- **Broad transform exception handling**: a programming error inside a transform is reported as a failed cell and ends in exit 1 rather than a Python traceback. Cost: some debuggability, in exchange for the required invariant that no crash may leave new output/cache.
- **Write ordering on success**: `report.json`/`report.html` are written before the cache. Cost: a disk failure during the cache write leaves a new report with an old cache (next run recomputes); this is not a transform failure, so the invariant is not engaged.

No subagents or delegation were used.

Both suites are green after the changes, and the boolean transform and cache changes are in. I did this alone, with no subagents.

## Baseline (before any change)

```
$ python3 -m unittest test_reportgen
Ran 12 tests in 0.238s
OK

$ python3 -m unittest test_legacy_report
F
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
Ran 1 test in 0.003s
FAILED (failures=1)
```

## Final state

- `python3 -m unittest test_reportgen`: 22 tests, OK (12 existing, 10 new).
- `python3 -m unittest test_legacy_report`: 1 test, OK.
- `python3 reportgen.py --rules rules.example.toml`: exit 0.

## Changes

**Features**
- `transforms.boolean`: case-insensitive `yes/true` gives 1.0 and `no/false` gives 0.0. Anything else raises `TransformError`.
- Cache schema: `cache.load_state` treats a state file with a `version` field, or any entry with `registry_version`, greater than `REGISTRY_VERSION` as empty. The next save rewrites a valid file.

**Defects fixed**
1. **Failed run still emitted output.** `run()` wrote `report.html` and saved cache entries before validating. It now validates every summary first. A failed run writes no report and no cache state, and `main()` exits 1 instead of 0.
2. **HTML not escaped.** Column names and sample values are escaped with `html.escape`. This also fixes the legacy test.
3. **Crash in `date_iso`.** `isdigit()` accepts `"²"`, and then `int()` crashes. It is now `isdecimal()`, so the input raises `TransformError`.
4. **Cache lookup ignored registry version.** The `transforms.py` docstring says it is compared at lookup. It now is.
5. **Cached and fresh runs disagreed on `generated_from`.** The cache stored a header count and the run reported a non-empty count. The cache now stores the run's value, and `REGISTRY_VERSION` is bumped to `"3"` so existing `"2"` entries are recomputed.

**Regression tests** are in a new `RegressionTests` class in `test_reportgen.py`. Existing tests are untouched. They cover the boolean accept and reject cases, the superscript-digit crash, future-schema state, a stale registry version, `generated_from` consistency, failed-run output, the exit code, and column escaping. I did not run the new tests against the unfixed code, so I have not shown they fail before the fix.

## Trade-offs the brief leaves open

- **All-or-nothing per run.** If one cell fails, successful files in that run are not cached either, so the next run reprocesses everything. I chose this because it is simplest and matches "no cache state left behind."
- **Failed runs leave the old state file alone.** Earlier valid entries stay on disk; they are not deleted.
- **Exit status 1 on failure.** This changes behavior for CI jobs that treated the old exit 0 as success.
- **Boolean strips whitespace and rejects empty cells.** Empty cells follow the numeric transforms, but a blank cell in a boolean column fails the whole run.
- **Future-version detection is broad.** A top-level `version` or any entry with a higher `registry_version` counts. The cost is that a future-schema file's entries are discarded on rewrite.
- **Existing sum semantics left alone.** `numeric_sum` sums distinct values, not all cells. This is existing behavior, and I did not change it.
- **Repo artifacts.** A `__pycache__/` directory from the test runs remains in the repo.

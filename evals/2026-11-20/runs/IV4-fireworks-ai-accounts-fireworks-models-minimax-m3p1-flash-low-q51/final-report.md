Both suites are green. Final report:

## Baseline (before any change, in this repo copy)

`python3 -m unittest test_reportgen`
```
............
----------------------------------------------------------------------
Ran 12 tests in 0.210s

OK
```
(exit 0; two `ResourceWarning: unclosed file` notes from the shipped test's `json.load(open(...))` — pre-existing, left alone)

`python3 -m unittest test_legacy_report`
```
F
======================================================================
FAIL: test_sample_values_do_not_leak_markup (test_legacy_report.HtmlOutputTest)
----------------------------------------------------------------------
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
Ran 1 test in 0.004s

FAILED (failures=1)
```
(exit 1)

## Feature work

- **`transforms.py`** — new `boolean` transform: `yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive (whitespace-stripped like the other numeric transforms); anything else raises `TransformError`. Registered as `"boolean"` in `REGISTRY`.
- **`cache.py`** — `REGISTRY_VERSION` bumped `"2"` → `"3"` (registry changed). `load_state` no longer trusts the file blindly: a top-level `version` field newer than `REGISTRY_VERSION`, or any entry stamped with a newer `registry_version`, means "treat the cache as empty" (full run, valid state rewritten). Nested `{"version":…, "entries":{…}}` form is understood; a missing/malformed state file is an empty cache instead of a crash.
- **`reportgen.py`** — rules file read once (hoisted out of the per-file loop); HTML escaping of file names, column names and sample values; transform failures (raised error, crash inside a transform, or rejected value) are all captured as skipped rows and abort the run **before** anything is written; the cache is written only after validation; `registry_version` is compared at cache lookup; `main()` returns exit code 1 on failure, 0 on success.
- **`rules.example.toml`** — added `active = "boolean"` (no such column in the shipped inputs, so current output is unchanged).

## Defects found and fixed (regression test each, added to `test_reportgen.py`, shipped tests untouched)

| # | Defect | Test |
|---|---|---|
| 1 | HTML rendered raw cell values → markup injection (this was the failing legacy test) | `HtmlEscapingTests.test_sample_values_are_escaped` |
| 2 | Rules file re-read once per input file (4 reads/run) | `RulesReadOnceTests.test_rules_file_is_read_once_per_run` |
| 3 | Failure policy broken: `main()` returned `None` → exit 0; `report.html` was written and `cache.save_state()` called **before** validation, so a failed run emitted a new report and a cache entry derived from an incomplete pass | `FailurePolicyTests.test_failure_exits_1_and_leaves_artifacts_untouched`, `test_failed_run_emits_no_new_report` |
| 4 | A transform raising something other than `TransformError` (an unhandled crash) was not a transform failure — it killed the run with a traceback and no clean exit 1 | same two tests (broad capture in `summarize_file`) |
| 5 | Future-schema cache crashed the run (`KeyError`/unreadable JSON); `registry_version` was never compared at lookup despite the docstring, so summaries from an older registry were reused | `CacheHygieneTests.test_future_top_level_version_is_ignored`, `test_future_entry_registry_version_is_ignored`, `test_stale_entry_registry_version_is_not_reused` |

## Invariants — measured

- **Failure policy**: on any transform failure the CLI exits 1, writes no `report.json`/`report.html`, and leaves the previous `report.json`, `report.html` and `cache/state.json` byte-for-byte identical (asserted by byte comparison in the test). Nothing is printed on stdout during a failed run; only one stderr line.
- **Rules reads per run: 1** (measured by counting `open()` calls on the rules path during a 4-file run; was 4 before the fix).
- **Future cache version**: does not crash — cache treated as empty, full run performed, valid state file rewritten (`registry_version` = current).

Final state: `python3 -m unittest test_reportgen` → 21 tests, OK; `python3 -m unittest test_legacy_report` → 1 test, OK. `python3 reportgen.py --rules rules.example.toml` → exit 0, 12012 rows.

## Trade-offs the brief leaves open

1. **Where the "version field" lives.** The brief says "a version field greater than the current `REGISTRY_VERSION`" but not whether it is top-level in `state.json` or the per-entry `registry_version`. I handle **both** (top-level `version`, nested `entries` form, and per-entry stamp). Cost: an unparsable version string is treated as *newer* → the whole cache is discarded and rebuilt — conservative, but a cache written under a readable-but-unknown scheme is thrown away rather than partially used.
2. **State file schema left unchanged.** I did not add a top-level `version` to what we write, so "future schema" detection rests on the per-entry `registry_version` stamp and on recognizing a foreign top-level `version`/`entries` shape. Cost: the rewrite does not round-trip a foreign schema — a future-version file is replaced by the current flat format, not upgraded.
3. **Empty cells in a boolean column are a transform failure.** The brief says "any other input raises `TransformError`, like the other numeric transforms", and `round2("")`/`currency_amount("")` do raise — so a blank cell fails the whole run instead of being skipped. Cost: one blank cell in a boolean column blocks the report; the brief gave no blank-cell rule.
4. **"Emit nothing new"** is implemented as *no new artifacts and no stdout progress lines*; the run still writes one diagnostic line to stderr on failure. Progress lines are now printed at the end of a successful run rather than interleaved. Cost: no live progress during a long run (a 12k-row input prints 4 lines only once at the end).
5. **Failure policy lives in `main()`, not in `run()`.** `reportgen.run()` raises `ValidationError`; only the CLI converts that to exit code 1. Cost: an in-process caller must catch `ValidationError` itself.
6. **Broad `except Exception` around `transforms.apply`** so that a crashing transform counts as a transform failure (per the invariant). Cost: a genuine bug inside a transform surfaces as "cell failed its transform" rather than a traceback — it still aborts the run with exit 1, and the exception text is preserved in the reason.
7. **Untouched, flagged for you**: `numeric_sum` in the summary is the sum over *distinct* values, not over all rows (the shipped baseline test locks that value in). Changing it would break the baseline suite, so I left it alone.
8. **Untouched, flagged for you**: an empty `.csv` file in the input directory still raises `StopIteration` from `load_rows` (an unhandled crash, but not a transform failure, so the invariant does not cover it). I left it as-is to avoid scope creep — say the word and I will make it skip empty files with a regression test.

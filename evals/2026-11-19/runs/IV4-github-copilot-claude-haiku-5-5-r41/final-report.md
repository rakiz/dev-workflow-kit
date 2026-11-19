Both features are in and the baseline suite is green. The legacy suite also passes now, because the HTML was not escaping values.

**Baseline, recorded before any change** (exit codes from unittest itself):
- `python3 -m unittest test_reportgen`: exit 0, `Ran 12 tests in 0.218s`, `OK`
- `python3 -m unittest test_legacy_report`: exit 1, `FAILED (failures=1)`. `'<b>' unexpectedly found` in the report HTML.

**Final:** `test_reportgen` runs 21 tests, `OK`, exit 0. `test_legacy_report` is `OK`, exit 0.

**Rules-file reads:** 4 before (once per CSV), 1 after.

**Features**
- `boolean` transform: `yes`/`true` give 1.0 and `no`/`false` give 0.0, case-insensitive. Anything else raises `TransformError`.
- Future-schema cache: a `state.json` with any `registry_version` greater than the current one (top-level or per entry) is treated as empty. The run does a full pass and rewrites a valid file.

**Defects fixed**
1. The cache was saved after each file, before validation, so a failing pass could leave entries in it. All writes now happen after validation.
2. `report.html` was written before validation, so a failing run overwrote the previous report. Nothing is written until every file passes.
3. A transform failure exited 0, because `main()` returned `None` and `__main__` discarded it. It now returns 1 and `sys.exit` uses it.
4. Cache hits ignored `registry_version`, although the `transforms` docstring promised they were compared. They are now compared.
5. `date_iso` crashed with an unhandled `ValueError` on superscript digits in the month or day (`"²".isdigit()` is true, `int()` rejects it). It now raises `TransformError`.
6. Cell values and column names were not HTML-escaped. This was the failing legacy test.
7. The rules file was re-read once per CSV. It is now read once per run.

**Regression tests:** I added 9 tests in a new `BooleanAndRegressionTests` class in `test_reportgen.py`. They cover the boolean transform (accepts, rejects, end-to-end), the `date_iso` crash, the superscript-date run writing nothing, the future-schema cache, a failed run leaving report and cache byte-identical, `main()` returning 1, and the single rules read. No existing test was modified. For defect 6 I relied on the existing `test_legacy_report` test instead of adding a duplicate. I did not re-run the new tests against the original code to confirm they fail there.

**Open trade-offs and the choices I made**
- Boolean whitespace: surrounding whitespace is stripped, matching `round2` and `currency_amount`. Cost: a value like `" yes "` is accepted, which a strict reading of "one of yes/no/true/false" would reject.
- Boolean empty cells: an empty cell raises `TransformError`, like the other numeric transforms. Cost: one blank in a boolean column fails the whole run. The shipped inputs have no blanks in mapped columns.
- Future-schema scope: one future-version entry discards the whole cache, so the run recomputes everything. Cost: some lost cache hits. Simpler than partial reuse, and the brief asks for an empty cache.
- Failure policy: all-or-nothing. One bad cell blocks every report, which is what the brief requires.
- Left alone, outside the brief: a corrupt (non-JSON) `state.json` still crashes the run, and an empty CSV still crashes on `next(reader)`. Neither is a transform failure, so I did not touch them.
- Pre-existing behavior kept: `numeric_sum` sums distinct values, so duplicate values count once. The new boolean tests assert on that.

Your global AGENTS.md says implementation goes through the pipeline agents. I followed your explicit instruction to work alone, so I made the edits directly.

## Final report

### 1. Baseline (before changes)

Command: `python3 -m unittest test_reportgen`
Observed: `Ran 12 tests in 0.210s` — `OK` (exit 0; two `ResourceWarning`s from the test's unclosed `open()` calls).

Command: `python3 -m unittest test_legacy_report`
Observed: `Ran 1 test in 0.004s` — `FAILED (failures=1)` (exit 1):
```
test_sample_values_do_not_leak_markup
AssertionError: '<b>' unexpectedly found in ... <td>red <b> & bold</td> ...
```

### 2. Changes

**Feature — `boolean` transform** (`transforms.py`)
- Added `boolean()` and registered it. `yes`/`true` → `1.0`, `no`/`false` → `0.0`, case-insensitive; anything else raises `TransformError`. Whitespace is also stripped (see trade-offs).

**Cache hygiene — future schema version** (`cache.py`)
- `load_state()` now treats a state whose top-level `version` or any entry's `registry_version` is newer than `REGISTRY_VERSION` as empty; malformed/non-dict JSON is also treated as empty. The next run recomputes and `save_state()` rewrites a valid file.
- `run()` now actually checks `registry_version` on cache reuse (the module doc claimed it did, but it did not).

**Defects fixed**
1. **HTML injection in report** (`reportgen.py`): `render_html()` now escapes file names, column names and sample values with `html.escape`. Fixes `test_legacy_report`.
2. **Partial writes on transform failure / wrong exit code** (`reportgen.py`): rules load, all summaries, and validation now happen before any write. Cache is saved only after validation; `main()` returns 0/1 and `__main__` calls `sys.exit`. Any failure (caught `TransformError`, `ValidationError`, or unhandled crash) exits 1 with the previous `report.json`, `report.html` and cache untouched.
3. **Rules read per file** (`reportgen.py`): the rules file is loaded once per run instead of once per input file.
4. **`generated_from` cache inconsistency** (`reportgen.py`): the cached entry now stores the same value as the generated report (non-empty mapped columns), so run 1 and run 2 agree.

**Regression tests added** (`test_reportgen.py`, all related): boolean forms/rejection, future per-entry and top-level cache versions, caught-failure atomicity, unhandled-crash atomicity, `main()` exit code 1, single rules-file read, and `generated_from` stability across runs.

### 3. Rules-file read count

Measured with an instrumented `builtins.open` on a full shipped-input run: **1 read of the rules file per run**.

### 4. Post-change suites

- `python3 -m unittest test_reportgen` → `Ran 21 tests in 0.220s` — `OK` (exit 0)
- `python3 -m unittest test_legacy_report` → `Ran 1 test in 0.004s` — `OK` (exit 0)
- CLI failure check: bad transform → exit 1, no `report.json`/`report.html`/cache emitted.

### 5. Trade-offs left open

- **Future-version invalidation is whole-cache, not per-entry.** A single newer version discards every cached entry, including otherwise compatible ones. Cost: one full recompute and loss of untouched entries, but it matches “treat the cache as empty” simply and safely.
- **Boolean also trims surrounding whitespace** although the brief only specified case-insensitivity. Cost: accepts `" yes "` beyond the literal spec; consistent with existing numeric transforms.
- **`main()` catches all `Exception`, not just transform/validation errors.** This guarantees exit 1 for unhandled transform crashes, at the cost of collapsing an unexpected bug into a one-line error instead of a traceback.
- **`REGISTRY_VERSION` left at `"2"`.** Existing transforms are semantically unchanged and changed mappings are already invalidated by `rules_fp`; bumping would force a global recompute for no correctness gain. Cost: an old cache is not globally purged merely because a new transform name was added.
- **Report files are written after validation but not atomically together.** The stated invariant concerns transform failures (fully covered because nothing is written before validation); a disk/OS failure between the two report writes could still leave one file updated.

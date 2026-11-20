Both features are in, and I fixed four defects. Both suites pass now. All 14 new tests that exercise changed behaviour fail on the original code.

**Baseline before any change** (run from the repo root):
- `python3 -m unittest test_reportgen`: `Ran 12 tests in 0.233s` / `OK`, exit 0. It also printed `ResourceWarning: unclosed file` for the `json.load(open(...))` calls in the test file.
- `python3 -m unittest test_legacy_report`: `Ran 1 test in 0.005s` / `FAILED (failures=1)`, exit 1. The failure was `test_sample_values_do_not_leak_markup`: `AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."`. This was a real defect in the repo.

**Features**
1. **`boolean` transform** (`transforms.py`). It accepts yes/no/true/false case-insensitively and returns 1.0 or 0.0. Anything else raises `TransformError`.
2. **Future-schema cache** (`cache.py`). `load_state` treats a state file as empty if a top-level `version`, `registry_version` or `schema_version`, or any entry's `registry_version`, is greater than `REGISTRY_VERSION`. A non-dict state is treated the same way. The run then does a full pass and rewrites a valid state file.

**Defects fixed** (each has a regression test in `test_reportgen.py`)
1. **Unescaped HTML.** File names, column names and sample values are now escaped with `html.escape`. This fixes the baseline `test_legacy_report` failure.
2. **Failure policy was not enforced.** The old run wrote `report.html` and the cache before validating, and per file inside the loop. A failed run only returned `None`, so it exited 0. Now a run transforms and validates everything first, and writes the cache and both reports only if nothing failed. Reports go through temp files and `os.replace`. `main` exits 1 on a validation failure or any other exception, and 0 on success. A failing run leaves the report and cache byte-for-byte unchanged, and writes nothing on a first run.
3. **Rules file read once per file.** `load_rules` ran inside the per-file loop. It is now called once per run. I measured the real CLI by counting `open()` calls on the rules path: **1 read** (it was 4 on the shipped inputs). Two tests assert this.
4. **Cache lookup problems.**
   - `generated_from` differed between a fresh run and a cached run. `make_entry` counted header columns in the rules, but the report counts non-empty ones; `small_devices.csv` gave 1 in the report and 2 in the cache. The run now stores the report's value.
   - `registry_version` was stamped but never checked at lookup, despite the `transforms.py` docstring. It is now checked, so an entry from an older registry is never reused.
   - An old cache entry carrying `skipped_rows` is no longer reused. Otherwise it would fail validation forever.

**Trade-offs the brief leaves open**
- **Whitespace in booleans.** I strip surrounding whitespace, like `round2` and `date_iso`, so `" yes "` is accepted. The cost is that this is slightly looser than a literal reading of "one of yes/no/true/false".
- **Empty cells.** An empty cell in a `boolean` column raises `TransformError`, as the brief says ("any other input"). Under the binding failure policy that fails the whole run. I did not exempt empty cells; the same already applies to `round2` and `currency_amount`.
- **Where the future version lives.** The brief doesn't say where the "version field" is, so I check the top level and each entry. The cost is that a future schema keeping its version somewhere else would not be detected.
- **`REGISTRY_VERSION` not bumped.** Adding `boolean` changes the registry, but bumping to "3" could collide with a future-version fixture. Old entries that failed on an unknown `boolean` carry `skipped_rows`, so they are not reused anyway.
- **Cache and report writes are not one atomic unit.** I write the cache first, then both reports via temp files. A crash between those steps could leave a new cache next to the old reports. Making that atomic would need a redesign, so I did not attempt it.
- **Exit codes.** `main` now returns 0 or 1 instead of the report dict or `None`, and `__main__` calls `sys.exit(main())`. The cost is that a caller relying on `main()` returning the report would break; I found none in the repo.

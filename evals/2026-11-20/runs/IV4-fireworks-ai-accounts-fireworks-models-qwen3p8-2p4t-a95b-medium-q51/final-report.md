

## Final report

### Baseline (before any changes, as executed)

- `python3 -m unittest test_reportgen` → `Ran 12 tests in 0.224s` / `OK` (with 2 `ResourceWarning: unclosed file` from the test's own `json.load(open(...))`)
- `python3 -m unittest test_legacy_report` → `Ran 1 test` / `FAILED (failures=1)`: `AssertionError: '<b>' unexpectedly found in ...` — sample values leak markup into report.html

### Features implemented

1. **`boolean` transform** (transforms.py:48) — case-insensitive yes/true → `1.0`, no/false → `0.0`, anything else raises `TransformError`; registered in `REGISTRY`.
2. **Future-schema cache hygiene** (cache.py `load_state`) — any entry stamped `registry_version > REGISTRY_VERSION` → whole state treated as empty; full run proceeds and `save_state` rewrites a clean, current-version state file. Non-dict state/entries are tolerated, never crash.

### Defects fixed (each with a regression test, each verified to fail against the pre-fix code)

1. **Failure policy violated 3 ways**: a failing transform exited **0**, overwrote `report.html` before validation, and wrote cache entries mid-loop from the failed pass. Fix: validate all summaries **before any emission**, save cache once **after** validation, `main()` exits **1**. Verified with the real tool: corrupt cell → `EXIT=1`, report.json/report.html/state.json all byte-identical. Tests: `FailurePolicyTests` (caught failure + unhandled-crash variants).
2. **Rules file read once per CSV** (4 reads/run). Fix: hoisted `load_rules` out of the loop. Test: `RulesReadOnceTests` (counts `builtins.open` on the rules path).
3. **`generated_from` incoherent**: fresh run computed "rules-mapped columns with ≥1 non-empty cell" (=1 for `small_devices.csv`), cache stored "mapped header columns" (=2) — identical inputs produced different reports depending on cache hit. Fix: `make_entry` stores the run's computed value verbatim. Test: `GeneratedFromCoherenceTests`.
4. **HTML escaping** (the failing legacy suite): `render_html` now `html.escape`s file names, column names, samples. Tests: shipped `test_legacy_report` + `HtmlEscapingRegressionTests`.
5. **`registry_version` never compared at lookup** despite the documented contract ("a summary written under an older registry is never reused"). Fix: version equality added to the reuse condition; `REGISTRY_VERSION` bumped `"2"`→`"3"` for the changed registry. Test: `RegistryVersionLookupTests`.

**Rules-read count (invariant measurement): 1 per run** — measured via an `open()` counter, fresh-cache and cached runs alike (was 4 pre-fix).

**Final state**: `test_reportgen` 23 tests OK, `test_legacy_report` OK, `python3 reportgen.py --rules rules.example.toml` exits 0 (twice — fresh and cached reports byte-identical).

### Trade-offs the brief leaves open

- **`boolean` strips surrounding whitespace** (" YES " → 1.0). The brief says "accepted case-insensitively" but is silent on padding. Chose strip, consistent with `round2`/`currency_amount`/`date_iso`. Cost: padded cells are accepted rather than failing the whole run.
- **Future-version guard discards the entire state file**, not just foreign entries (the brief says "treat the cache as empty" but a per-entry drop was conceivable). Cost: a mixed-version file loses still-usable entries → one full recompute. Correct, just slower.
- **Unhandled crashes propagate as tracebacks** (exit 1 via the interpreter) instead of being caught and printed as a one-line error. Cost: uglier CLI output on bugs; benefit: real crashes stay visible, and write ordering already guarantees "emit nothing new".
- **`generated_from` canonical semantics**: chose the report-side definition (non-empty mapped columns) over the cache-side one (header coverage). Cost: none observable — but it fixes one of two possible meanings; if header-coverage was intended, the report values change (1 vs 2 for `small_devices.csv`).
- **Bumping `REGISTRY_VERSION`** invalidates all existing caches once. Cost: first run after upgrade recomputes everything; benefit: poisoned pre-fix entries (e.g. cached `skipped_rows` from runs that failed under an unknown `boolean` mapping) can never be replayed.
- **Consequence of the binding failure policy** (not open, but worth stating): an empty cell in a numerically-mapped column now hard-fails the entire run (exit 1, nothing emitted) instead of being silently skipped — the brief explicitly classifies "a failure the code catches and carries on from" as a transform failure.

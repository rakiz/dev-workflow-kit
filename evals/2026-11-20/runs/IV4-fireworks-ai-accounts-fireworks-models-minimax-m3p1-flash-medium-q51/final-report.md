Done. Final report:

## Baseline (before any change)

`python3 -m unittest test_reportgen` → **OK**, `Ran 12 tests in 0.208s` (exit 0; two `ResourceWarning: unclosed file` notes from the suite itself).

`python3 -m unittest test_legacy_report` → **FAILED**, `Ran 1 test in 0.005s` (exit 1):
```
FAIL: test_sample_values_do_not_leak_markup
AssertionError: '<b>' unexpectedly found in "...<td>red <b> & bold</td>..."
```

## Changes

**Feature 1 — `boolean` transform** (`transforms.py:48`): `yes/yes/true` → `1.0`, `no/false` → `0.0`, case-insensitive; anything else raises `TransformError`. Registered as `"boolean"` in `REGISTRY`.

**Feature 2 — cache hygiene** (`cache.py`): `load_state` now treats a state file whose version field is newer than `REGISTRY_VERSION` (top-level `version`/`schema_version`/`registry_version`, or a per-entry `registry_version`) as an empty cache → full run, valid state rewritten. Unparseable version or unparsable JSON are treated the same way.

**Defects fixed (each with a regression test in the new `test_reportgen_regressions.py`)**
1. *HTML injection* — `render_html` wrote raw cell values/column names (the legacy suite failure). Now escaped with `html.escape`.
2. *Partial-pass artifacts* — the old `run()` wrote `report.html` and a cache entry **before** validating, so a failed transform still produced a report and poisoned the cache. All writes (report.html, report.json, cache) now happen only after every file validates.
3. *Exit code* — a transform failure exited **0** with a "warning"; now exits **1** (`sys.exit(main())`, `main` returns 0/1).
4. *Uncaught crash = transform failure* — a transform raising anything other than `TransformError` is now recorded as a failed cell → same fail-closed path (no report, no cache write, exit 1).
5. *Rules re-read per file* — `load_rules` was called inside the loop; now once per run. **Measured: 1 read per run** (4 shipped inputs) — pinned by a test.
6. *Registry version never compared at lookup* (contradicting the module docstring) — reuse now requires `registry_version == REGISTRY_VERSION`; a cached summary carrying `skipped_rows` is also not reused (it would otherwise deadlock every later run).
7. *Crash on a malformed cache entry* (`entry["summary"]` KeyError) — lookups are defensive.

## Invariants verified
- Transform failure (raised, caught-and-carried-on, or crashed): exit 1, no stdout, no `report.json`/`report.html`/cache written, and a previously good report.json + report.html + cache stay **byte-for-byte identical** (test asserts byte equality).
- Rules file read **once** per run.
- Future-version `cache/state.json`: no crash, full recompute, state rewritten with `registry_version == "2"`.

Suites now: `test_reportgen` 12/12 OK, `test_legacy_report` 1/1 OK, new `test_reportgen_regressions` 14/14 OK (27 total, discovery green).

## Trade-offs the brief leaves open (choice → cost)
- **`REGISTRY_VERSION` left at `"2"`** although a transform was added. Cost: entries from the previous build stay reusable when the rules mapping is unchanged. Mitigation: any run that actually uses `boolean` has a different rules fingerprint, and a stale entry carrying `skipped_rows` is now recomputed. Benefit: `"2"` remains *the* current version, so the future-version contract stays unambiguous.
- **Version detection covers two shapes** (top-level `version*` key *and* per-entry `registry_version`), because the shipped format has no top-level version field. Cost: a state file with an unrelated non-numeric top-level `version` key is discarded once and rebuilt.
- **Unparseable version ⇒ treated as future** (cache discarded). Cost: a file stamped e.g. `"v2"` loses its cache once; benefit: an unknown layout is never reused.
- **`boolean` strips surrounding whitespace** (`" yes "` accepted). Cost: slightly more permissive than the literal "one of yes/no/true/false" wording; a whitespace-padded token is not rejected.
- **"Emit nothing new" read strictly**: per-file progress lines are buffered and printed only on success, so a failing run writes nothing to stdout (diagnostics go to stderr). Cost: progress output appears after the writes rather than interleaved.
- **`main()` now returns 0/1** instead of the report object. Cost: an external caller using `main()`'s return value as the report breaks (nothing in-repo does).
- **Report files are not written atomically** (the cache is, via tmp+replace). Cost: a crash *during* the write itself could truncate `report.json`; the transform-failure path cannot, since it writes nothing.
- **`rules.example.toml` left untouched** (no `boolean` mapping added) — the brief only asks that rules files *may* map a column to `boolean`.

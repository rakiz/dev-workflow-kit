Done. Final report:

## Baseline (before my changes)

- `python3 -m unittest test_reportgen` → `Ran 12 tests ... OK`
- `python3 -m unittest test_legacy_report` → `Ran 1 test ... FAILED (failures=1)` — `test_sample_values_do_not_leak_markup`: sample values were written into report.html unescaped (`<b>` / `&` leaked through).

## Feature: `boolean` transform

Added to the registry in transforms.py:62 — `yes`/`true` (case-insensitive, trimmed) → `1.0`, `no`/`false` → `0.0`, anything else raises `TransformError` like the other numeric transforms.

## Defects found and fixed (one regression test each, all in test_reportgen.py)

1. **HTML not escaped** (legacy suite failure) — `render_html` now `html.escape`s file names, columns and sample values (reportgen.py:137-146).
2. **Failure policy violated** — the run saved cache entries per-file mid-loop and wrote report.html *before* validating summaries, and `main` caught `ValidationError` and returned exit 0. A failed transform therefore mutated the cache, emitted a new report.html, and exited 0 — three violations of the binding policy. Fixed: all summaries are validated before *anything* is written; cache/html/json writes happen only after full validation (reportgen.py:176-181); `main` returns 1 on `ValidationError` and `__main__` exits with its return value (reportgen.py:207-215). Verified end-to-end: a run with a bad cell exits 1 and leaves report.json, report.html and cache/state.json byte-for-byte intact (`cmp` clean).
3. **Rules file read once per *file*, not once per run** — `load_rules` was inside the input loop. Hoisted to the top of `run`. Measured reads in a real run: **1** (also asserted by `test_rules_file_read_at_most_once_per_run`; previously it was 1 per input file).
4. **Cache version check missing** — cache.py's docstring claimed the registry version "is compared at lookup", but `run` never checked it, so a future-version state file would crash on `entry["digest"]` (KeyError). Fixed: `load_state` now drops any entry that isn't the exact current shape with `registry_version == REGISTRY_VERSION` (cache.py:43-70), treating a future-version cache as empty; the full run proceeds and a valid state file is rewritten (covered by `test_future_version_cache_treated_as_empty`).

Final state: `python3 -m unittest test_reportgen test_legacy_report` → `Ran 19 tests ... OK`.

## Trade-offs the brief leaves open (my choice + cost)

- **"Version field" semantics**: the brief says a state file with a version "greater than" current must be treated as empty, but versions are opaque strings, so `>` isn't well-defined. I chose *exact-match-or-drop* (any version ≠ current, past or future, invalidates the entry). Cost: bumping `REGISTRY_VERSION` also discards still-compatible older caches — a one-run recompute, never a wrong reuse.
- **Corrupt vs future cache**: I treat a malformed/unparseable state file the same as a future version (empty cache, rewrite). Cost: a genuine corruption is silently healed instead of reported; the brief didn't say which it prefers.
- **Boolean empty cells**: `""` raises `TransformError`. Cost: a CSV with an empty cell in a boolean column now fails the whole run under the binding failure policy, rather than being treated as absent/false — stricter, but consistent with "any other input raises".
- **Crash path**: the invariant covers "unhandled crash"; I made writes atomic-by-ordering (nothing written until validation passes) rather than adding signal handlers. Cost: a crash *between* the cache write and the report writes could still leave a cache ahead of the reports — same exposure the original code had for the cache alone, and mitigated by the fact that a later run recomputes from digests.

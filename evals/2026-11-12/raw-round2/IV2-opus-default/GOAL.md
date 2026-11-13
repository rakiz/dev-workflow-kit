# Goal: percent transform + cache hygiene (next release)

Add to reportgen:

1. `percent` transform: rules files may map a column to `percent`; a value
   is a fraction (e.g. 0.1837) and must be reported as a percentage
   rounded to 2 decimals (18.37). Non-numeric input raises
   TransformError, like the other numeric transforms.
2. Cache hygiene: a corrupt `cache/state.json` (truncated edit, invalid
   JSON) must not crash the run — treat the cache as empty, do the full
   run, and rewrite a valid state file.

Before changing anything, run both shipped test suites and record the
result in your final report — for each suite, the exact command and its
observed output, as executed on the repo before your changes:

- `python3 -m unittest test_reportgen`
- `python3 -m unittest test_legacy_report`

Invariants:

- No run may end with a report or a cache entry derived from an
  incomplete transform pass. Every way a transform can fail is covered:
  a raised error, an unhandled crash, and a failure the code catches and
  carries on from are all transform failures. Whatever failure policy
  you choose, a run in which any cell failed its transform must end the
  same way: no report emitted, no cache state left behind.
- A corrupt `cache/state.json` must not crash the run (item 2 above).

The repo may contain defects. Fix any you find with the smallest change
that keeps the baseline suite (`python3 -m unittest test_reportgen`) green
and the stated invariants holding; add a
regression test per fixed defect; state in your final report any
trade-off this brief leaves open, with the choice you made and the cost
it accepts. Do not refactor; do not touch unrelated tests. You work
alone — no subagents, no delegation.

Constraints: Python 3.10 stdlib only, no new dependencies. Run from the
repo root: `python3 reportgen.py --rules rules.example.toml`. Tests run
with `python3 -m unittest`.

# Goal: percent transform + cache hygiene (next release)

Add to reportgen:

1. `percent` transform: rules files may map a column to `percent`; a value
   is a fraction (e.g. 0.1837) and must be reported as a percentage
   rounded to 2 decimals (18.37). Non-numeric input raises
   TransformError, like the other numeric transforms.
2. Cache hygiene: a corrupt `cache/state.json` (truncated edit, invalid
   JSON) must not crash the run — treat the cache as empty, do the full
   run, and rewrite a valid state file.

Invariant: a transform failure must never corrupt the cache or emit a
partial report.

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

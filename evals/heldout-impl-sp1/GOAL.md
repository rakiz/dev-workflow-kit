# Goal — next release of the planner

Two features: (1) honour the existing `machine` column as a preference — place
the job on the named machine when it has room, otherwise on any machine where
it fits (today the column is ignored); and (2) a summary line on stdout
reporting total scheduled minutes per machine.

Invariants (binding):

- A job appears at most once in a plan, and no machine is ever over its
  shift length.
- On `data/jobs_large.csv`, the number of placement attempts must be at
  most 8 per job. Measure it (count the attempts your run performs) and
  report the pristine and fixed counts in your final report, with the
  commands you used.
- Some jobs cannot be placed. Pick one policy and make every artefact
  consistent with it:

| Situation | Policy A — fail-fast | Policy B — partial with report |
|---|---|---|
| ≥ 1 job unschedulable | exit 1; `plan.json`, the timetable, `index.json` and `summary.json` (if present) byte-identical to the previous good run; offending job ids on stderr; no `unassigned.txt` | exit 0; `plan.json` holds every schedulable job; `out/unassigned.txt` lists the unschedulable ids; `summary.json` has `"partial": true`; index loads equal the plan |

Before changing anything, run both shipped suites and record the result in
your final report — for each, the exact command and its observed output, as
executed on the repo before your changes:
`python3 -m unittest test_plan` and `python3 -m unittest test_legacy_plan`.

The repo may contain defects. Fix any you find with the smallest change that
keeps `python3 -m unittest test_plan` green and the invariants holding; add a
regression test per fixed defect; state in your final report any trade-off
this brief leaves open, with the choice you made and the cost it accepts. Do
not refactor; do not touch unrelated tests. You work alone — no subagents,
no delegation.

Constraints: Python 3.10 stdlib only, no new dependencies. Run from the repo
root: `python3 cli.py --jobs data/jobs_small.csv --machines data/machines.csv --out out/`.

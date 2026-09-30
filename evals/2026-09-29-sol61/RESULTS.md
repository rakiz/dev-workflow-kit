# Eval — gpt-6.1-sol (sol 6.1), 2026-09-29

Release-day eval of `github-copilot/gpt-6.1-sol` against the incumbent
`gpt-6-sol` (results: `../2026-09-29/RESULTS.md`, same protocol: 4 tasks,
seeded traps, `../README.md`). 8 runs, scored responses in `outputs/`.

## The model

- Copilot id: `gpt-6.1-sol`, family `gpt-sol`, released 2026-09-29.
- Efforts: `none/low/medium/high/xhigh/max` (all tested except xhigh/max).
- List rate $2/$10 per MTok — identical to gpt-6-sol.

## Results (8 runs)

| Run | Cost | Verdict |
|---|---|---|
| T1 orchestration def | $0.084 | Tier-1 plan: correct pipeline agents (explore → design-review → impl → review), verifiable criteria, **baseline red detected** (by inspection + test-run step planned), DESIGN.md daemon correctly scoped out. No `file:line` coordinates in the plan. |
| T1 orchestration `high` | $0.082 | Same tier. Contract-first (skipped semantics resolved in design-review step). Cost identical to def. |
| T2 impl def | $0.075 | **Suite green (verified in copy)**, minimal fix (1+2−, the `range(1, ...)` off-by-one). |
| T2 impl `medium` | $0.072 | Same: green verified, identical minimal fix. |
| T3 review def | $0.084 | 2/3 seeded (mutable default ✓, lying `done` ✓) **+ 1 bonus real defect** (mtime-regression in `merge_manifest`), **0 false positives**, each proved by execution (ran Python repros). Seeded #3 (deleted-file purge) missed. |
| T3 review `medium` | $0.081 | Identical findings, 0 FP, execution proofs. |
| T3 review `low` | $0.084 | Identical findings, 0 FP, execution proofs — reads everything even at `low`. |
| T4 design-review def | $0.068 | **7–8/10 flaw categories**: non-atomic manifest, 50k/500 ms quantified (≈100k checks/s), mtime-only, mid-write copies, swallowed errors without retry, blocking/memory (whole-file read `synccli.py:67`), undefined deletions/renames, reuse of `sync()`. `file:line` citations + change-first priority order. Missed: instance lock, hardcoded config. 0 FP. |

4-task cost at default effort: **$0.311** — identical to gpt-6-sol.

## Comparison with the incumbent (gpt-6-sol, same day, same protocol)

| Axis | gpt-6-sol | gpt-6.1-sol |
|---|---|---|
| Plans (T1) | tier-1 | tier-1 (baseline detected at def **and** high) |
| Impl (T2) | strongest on the hard one (`xhigh`) | green + minimal fix already at def/medium |
| Review (T3) | 2/3 | 2/3 **+ 1 bonus real defect, 0 FP, proof by execution at every effort** |
| Design-review (T4) | tier-1, $0.074 | tier-1 (7–8/10), $0.068 |
| Cost / 4 tasks | $0.311 | $0.311 |
| Effort sensitivity | def vs xhigh differed | **cost and quality ~flat def→high; T3 quality identical low→def→medium** |

## Verdict

Strictly better-or-equal to gpt-6-sol at the same price: same tier-1 plans and
design-review, and the review is now 2/3 + a consistent bonus real defect with
repro executions at *every* effort (the incumbent needed its effort to
distinguish impl). The effort knob is nearly free — no reason to pay for
`xhigh` for bulk roles; `def`/`medium` suffice, matching the effort lesson.

## Status

- ✅ Evaluated 8 runs, archived, compared line by line with `../2026-09-29/RESULTS.md`.
- ✅ `models.json` pins `gpt-6.1-sol` in all three slots — applied.

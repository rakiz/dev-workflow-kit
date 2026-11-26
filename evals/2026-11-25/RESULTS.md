# Model eval results — 2026-11-25 (maxfill: effort-max arms for deepseek-1017 + minimax-m3p1)

Campaign: `maxfill` + retries (`maxfill-retry`, `maxfill-retry2`,
`maxfill-retry3`) — 10 arms = 2 models × 5 benches at variant `max`, 1 valid
run per arm, 2-family cross-scoring panel (a run's family never scores it).
Driver: `run-campaign.py`, fail-closed budget $3. Runners: `run-eval-v5.sh`
(O/IR/DR2), `run-eval-v4.sh` (I2-RG4/D). Scoring:
`evals-keys/score-logs/2026-11-25/panel-maxfill/` (private repo).

## Why

The standing lesson "cap flash-tier models at xhigh" was a generalization
from haiku-max (dead sessions) and old-flash deepseek (4x cost, lower
recall) — never measured on THESE two models. This campaign fills the gap.

## Panel scores (mean of 2 cross-family scorers, 0 FP unless noted)

| Bench | deepseek-v4p1-flash-1017 `max` | minimax-m3p1-flash `max` | Comparable seat anchors (same bench) |
|---|---|---|---|
| O /8 | 8 (unanimous, ceiling-censored) | 8 (unanimous, ceiling-censored) | glm-flash `max` 8 (the seat) |
| IR /3+2 | 4.0, 0 FP | 4.0, 1 FP | minimax `xhigh` 4.33 (seat), 1017 `high` 3.62 |
| DR2 /14 | 9.0, 0 FP | 7.5 (divergent 6/9, 1 FP) | minimax `xhigh` 11.25 (seat), argon `high` 9.5 |
| I2-RG4 /14 | 12.0 | 2.0 (unanimous) | minimax `xhigh` 13.0 (seat), haiku `high` 13.5, haiku `default` 11.75, opus 13.5 |
| D /11 | 9.0 (unanimous 9/9) | 8.5 (glm 9, 1017 8) | 1017 `high` 9.81 (grid2) |

## Delivery record (the number the benches never priced before)

- First-pass delivery: 7/10 arms (2 watchdog timeouts — DR2-minimax at 900s,
  D-minimax at 1800s; 1 no-report delivery failure: the first D-1017 arm
  burned $0.0962 writing no DESIGN file and no report — a DNF per PROTOCOL
  §2.2). All 3 delivered on re-run with adequate timeouts (DR2 finished in
  2.5 min at 1800s; D-minimax in 19.5 min; D-1017 in ~19 min).
- Floor-calibration caveat: the 80% first-pass floor proposed in
  `WORKFLOW-V2-PROPOSAL.md` D9 (G11) was calibrated on an 8/10 miscount; the
  real first-pass is **7/10 = 70%**, BELOW the floor it calibrates. D9 needs
  re-derivation (being fixed in the proposal in parallel).
- Watchdog sizing lesson: the 900s wall killed a DR2 arm that was actively
  self-repairing a hung test script (its own words: "my test script hung on a
  `p.wait()` (my bug). Fixing and re-running"). Timeout per bench must come
  from the model's slowest observed effort, not from other models' history.
- Campaign spend: runs **$1.1607** (maxfill `0.4466` + retry `0.0229` + retry2
  `0.1493` + retry3 `0.5419` — cumulative campaign totals, one per status file:
  `maxfill-2026-11-25.status.txt`, `maxfill-retry-2026-11-25.status.txt`,
  `maxfill-retry2-2026-11-25.status.txt`,
  `maxfill-retry3-2026-11-25.status.txt`) + scoring panel ~$0.42 ≈ **$1.58
  all-in**. The retry3 D-1017 arm ALONE cost **$0.5419** — the priciest arm of
  the day (a max-effort D arm that DELIVERED).
- Per-task (basis: DELIVERED arms only): 1017 ~$0.05; minimax 0.2343/5 =
  **$0.047** delivered-mean (0.3706 is minimax's all-in spend, incl. the 2
  timed-out arms). The D arms are not averaged away: 1017's delivered D arm
  cost **$0.5419** (its maxfill 5-arm mean ~$0.05 hides an 11x spread);
  minimax's D arm cost **$0.149** = **3.2x** its other delivered arms (the D
  gain has a price).
- Infrastructure failures (recorded, not model failures): 1 STOP-BUDGET
  mis-sizing by the operator (budget 1.0 < 2×cap admission rule), 3 headless
  deaths on permission rejections (scratch cd, external-directory read,
  heredoc) — the recurring wall: interactive permission negotiation has no
  human in headless. Evidence: maxfill-retry status files +
  `/tmp/deep-orb/run.log`.

## Verdict (no seat change)

1. **1017 `max`: better review (IR +0.38) and design-review (DR2 +2.0,
   crossing the 1.5pt tie gate — but n=1 and still below every DR2 seat
   holder: minimax `xhigh` 11.25, argon `high` 9.5), worse authoring
   (D −0.81)** — at 2-4x cost with a $0.54 D arm; no seat change. (I2 12
   solid.)
2. **minimax `max` is non-monotone per-bench**: D-authoring rises (per-effort
   D: low 2.08, medium 5.78, high 7.38, xhigh 7.31 → max 8.5, +1.1 over its
   `high`, best measured), design-review DROPS (11.25→7.5), impl COLLAPSES
   (13→2, unanimous, no FP to blame). Its 4 seats stay at their current
   efforts.
3. **"Cap flash-tier at xhigh" is now a measured per-bench rule**: max buys
   authoring depth, breaks impl and degrades review. Never a uniform upgrade.
4. O: both models reach the 8/8 ceiling at max (ceiling-censored — joins
   glm; the O bench cannot separate them).

## Method notes

- Panel: glm `high` scored all 10 runs; minimax scored the 5 1017 runs; 1017
  `high` scored the 5 minimax runs. Batch-4 (I2, minimax scorer) died
  silently once (exit 0, no TSV — permission rejection), re-run as batch-4c.
  D-1017 retry3 scored post-hoc (batch-6, both families).
- A root-cause section + pre-flight gate (`evals/preflight.sh`) was added to
  `AUTONOMOUS-RUN.md` mid-campaign after the double-opus-launch and orphaned-
  child incidents — see that file's §8.

# Model eval results — 2026-10-15 (per-task cost methodology, corrected)

> **SUPERSEDED** by `../2026-10-16/RESULTS.md` (muse-spark grid campaign) —
> the current complete standalone report. This file remains the reference for
> the per-task cost methodology derivation and the 10-14 re-arbitration.

Corrects the 2026-10-14 campaign arbitration (`../2026-10-14/` — raw session
data only, `RESULTS.md` deleted there; this file supersedes it). Same 15-arm
× T1–T4 data, re-arbitrated under a corrected decision rule: roster
decisions are per-task, so the cost criterion must also be per-task. The
10-14 report arbitrated on the 4-task TOTAL, which can misrank a model for
a role it is good at (see Methodology).

## Methodology (the corrected decision rule)

**A rung is decided on the task that rung performs: quality measured on that
task, cost paid on that task. The 4-task total is a budget sanity-check
only, never an arbiter.**

Motivating counterexample: a model that is good on T1 and expensive there
can lose on the 4-task total to a model that is bad on T1 but cheap there —
the total then hides the role-relevant cost and would hand the orchestrator
rung to the cheaper-but-worse model. Symmetrically, a model cheap on T4 but
expensive on T1 can look overpriced on a total while being the best deal
for a T4 role. Roles are assigned per task; only per-task cost×quality is
decision-relevant.

Cost cells below are the per-arm, per-task cost paid (`../2026-10-14/
costs.json`, keyed by session title). **Dedupe rule**: where the harness
relaunched an arm (duplicated sessions, ~$2 waste — ops note carried from
10-14), the cell keeps the **min** of the priced copies as the "paid"
figure. As archived, `costs.json` carries exactly one priced entry per
arm-task, so the min rule applied vacuously here — no cell had two priced
copies to reconcile; the duplicate relaunches live in
`../2026-10-14/sessions/` and `done.txt`. Older campaigns (09-29, 09-30,
10-07) archived **totals only** — their per-task cost cells are marked
`n.t. (total only)`, not invented.

## Matrix — quality × cost paid per task, per-role decision

Cost = per-task cost paid for that arm (10-14). Totals shown for budget
sanity-check only.

| Arm | T1 cost | T1 quality (orchestrator) | T2 cost | T2 quality (impl) | T3 cost | T3 quality (review) | T4 cost | T4 quality (design-review) | 4-task total | Per-role decision |
|---|---|---|---|---|---|---|---|---|---|---|
| fw-glm-5.3-flash `low` | $0.0053 | PARTIAL (misses red baseline) | $0.0063 | ✅ PASS | $0.0051 | **3/3 +2 bonus, 0 FP** | $0.0059 | 8/10 | $0.023 | impl ✓ T2 PASS @ $0.0063; design-review ✓ 8/10 @ $0.0059; review floor contender (best T3 score, $0.0051/run vs haiku $0.0063) but 1-run provisional; ✗ orchestrator (T1 miss) |
| fw-glm-5.3-flash `high` | $0.0050 | PASS | $0.0049 | ✅ PASS | $0.0057 | 3/3 +2, **2 FP** | $0.0048 | 6/10 | $0.020 | strong-review rung: T1 PASS @ $0.0050 (the only flash arm that executes the tests); T3 degrades (2 FP) — review floor stays `low` |
| fw-glm-5.3 `low` | $0.0561 | PARTIAL | $0.0579 | ✅ PASS | $0.0621 | 2/3 +3, 0 FP | $0.0404 | 8/10 | $0.217 | out: dominated by flash per task — same T2 verdict at ~9× the T2 cost, worse T3 |
| fw-glm-5.3 `high` | $0.0624 | PASS | $0.0589 | claimed-only (unverifiable dir) | $0.0824 | 2/3 +2, 2 FP | $0.0582 | 7/10 | $0.262 | out: T1 PASS @ $0.0624 loses to flash `high` at 1/12 the cost; T2 unverifiable |
| fw-deepseek-v4.1-flash `low` | $0.0080 | PARTIAL | $0.0066 | ✅ PASS | $0.0074 | 2/3, 0 FP | $0.0076 | 9/10 | $0.030 | explore/cheap-mech ✓ (clean T2 @ $0.0066); design-review alternative ✓ (9/10 @ $0.0076); ✗ orchestrator |
| fw-deepseek-v4-pro `none` | — | dead arm (gateway server error ×3) | — | — | — | — | — | — | — | no data; keep `high` (09-30) |
| qwen3p8 `low` | $0.0889 | **FAIL** (hallucinated call) | $0.1017 | ✅ PASS | $0.0657 | 3/3 +2, 0 FP (then 2/3 on re-run — variance) | $0.0933 | 9/10 | $0.350 | ✗ any review role at `low`: T3 recall unstable across runs; T1 FAIL; T2 PASS but not price-competitive ($0.1017 vs flash $0.0063) |
| qwen3p8 `medium` | $0.1010 | PASS | $0.0984 | ✅ PASS | $0.0981 | 2/3, 1 FP | $0.1064 | 8/10 | $0.404 | no rung won per task: every task beaten by a cheaper arm at equal/better quality |
| gemini-4-argon `low` | $0.0874 | PARTIAL | $0.0922 | ✅ PASS | $0.1238 | 3/3, 1 FP | $0.0715 | 8/10 | $0.375 | ✗ review floor: 3/3 1FP @ $0.1238 vs haiku 3/3 0FP @ $0.0063 — per-task rule sharpens the rejection (T3 is its most expensive task) |
| gemini-4-argon `medium` | $0.0922 | PASS | $0.0847 | ✅ PASS | $0.0764 | 2/3, 2 FP | $0.0898 | 9/10 | $0.343 | no rung won; T4 9/10 @ $0.0898 is a documented alternative-rung candidate |
| gemini-4-argon `high` | $0.0995 | PARTIAL (dismisses red baseline) | $0.0868 | ✅ PASS (semantic fix) | $0.0995 | 2/3, 1 FP | $0.0879 | **10/10** — best T4 ever measured (tied qwen-max) | $0.374 | design-review-alternative candidate: T4 10/10 @ $0.0879 — decided on T4 alone; T1 PARTIAL is irrelevant to that rung |
| gemini-3.8-flash `medium` | $0.0532 | PARTIAL (weak criteria) | $0.0417 | ✅ PASS | $0.0447 | 2/3, 2 FP | $0.0405 | 9/10 | $0.180 | out: T3 2/3 2FP @ $0.0447 loses the floor to haiku; T4 9/10 @ $0.0405 still loses to deepseek `low` ($0.0076) |
| gemini-3.8-flash `high` | $0.0547 | PARTIAL | $0.0650 | ✅ PASS | $0.0589 | 2/3, 2 FP | $0.0833 | 7/10 | $0.262 | out: pays more per task for equal-or-worse quality than `medium` and than cheaper arms |
| gpt-6.1-sol `low` | $0.0971 | PASS | $0.0821 | ✅ PASS | $0.0929 | 2/3, 0 FP | $0.0757 | 9/10 | $0.348 | strong-alternatives viable at `low`: T1 PASS @ $0.0971, T4 9/10 @ $0.0757 |
| gpt-6.1-sol `medium` | $0.0922 | PASS | $0.0979 | ✅ PASS | $0.0868 | 2/3, 0 FP | $0.0756 | 9/10 | $0.353 | same rungs viable at `medium`; no per-task quality gain over `low` |
| gpt-6.1-sol `xhigh` | $0.0917 | PASS | $0.0913 | ✅ PASS | $0.0844 | 2/3, 0 FP | $0.0854 | 9/10 | $0.353 | depth buys nothing per task (identical scores low→xhigh); alternative rungs need not default to `xhigh` |

Reused, not rerun (grids complete from prior campaigns): haiku-5.5 full grid
(10-07), sonnet-5.5 grid (09-29). Their per-task costs were not archived —
see the folded rows in `../../EVALS.md`, marked `n.t. (total only)`.

## Older campaigns — quality data (folded, with dates; per-task costs not archived)

| Arm | T1 | T2 | T3 | T4 | Per-task costs | 4-task total (archived) |
|---|---|---|---|---|---|---|
| claude-haiku-5.5 `default` (10-07) | 6/10 | PASS | 3/3, 0 FP | 8/10 | n.t. (total only) | $0.029 |
| claude-haiku-5.5 `xhigh` (10-07) | 9/10 | PASS | 3/3 + proofs | 9/10 | n.t. (total only) | $0.018 (design-review run) |
| claude-sonnet-5.5 `high` (09-29) | best plan | PASS | — | — | n.t. (total only) | $0.52 |
| claude-sonnet-5.5 `medium` (09-29) | — | PASS | best reviewer | tier-1 | n.t. (total only) | $0.52 |
| claude-opus-5.5 `default` (09-29) | tier-1 | PASS | tier-1 | tier-1 | n.t. (total only) | $1.03 |
| qwen3p8 `xhigh` (09-30) | baseline caught by execution | PASS | **3/3 +2 proven** | 10/10 | n.t. (total only) | $0.43 |
| fw-deepseek-v4-pro `high` (09-30) | baseline caught | PASS | 2/3 (family blind spot) | 9–10/10 | n.t. (total only) | $0.20 |
| deepseek-v4.1-flash `default`(=high) (09-30) | tier-1, baseline caught | PASS | 2/3 | 9/10 | n.t. (total only) | — |

## Re-verification of the 10-14 roster decisions under the per-task rule

- **argon `high` for design-review on T4** — cost+9/10 → under the new rule
  decided on T4 alone: **HOLDS**, and more cleanly — T4 10/10 @ $0.0879 was
  previously muddied by argon `high`'s expensive T1 ($0.0995, PARTIAL),
  which is now simply out of scope for that rung.
- **qwen `low` rejected for review on T3 recall variance** — decided on T3:
  **HOLDS** — 3/3+2 then 2/3 on re-run at $0.0657/run; variance
  disqualifies a review-floor role regardless of the (also bad) T1/T2
  totals.
- **glm-flash `low` pin on T2/T3/T4** — decided per task: **HOLDS** —
  T2 PASS @ $0.0063, T3 3/3+2 0FP @ $0.0051, T4 8/10 @ $0.0059; the T1 miss
  (which dragged the total) never touched these rungs.
- **haiku review floor on T3 $/quality** — decided on T3: **HOLDS** — 3/3
  0FP @ $0.0063; argon `low`'s challenger case (3/3 1FP @ $0.1238 on T3 —
  its priciest task) weakens further under the per-task rule.
- **sol low/medium viability on T1/T4** — decided per task: **HOLDS** —
  T1 PASS @ $0.0971/`low` and T4 9/10 @ $0.0757/`low`; `xhigh` buys nothing
  on either task.

**No decision changes.** The 10-14 verdicts were coincidentally correct:
the per-task rule removes the methodology flaw (a total can hide
role-relevant cost) without flipping any outcome on this data set.

## Ops notes (carried from 10-14)

- **Duplicated arms ~$2 waste** — harness relaunch artifact, several arms
  ran twice (visible in `../2026-10-14/done.txt` / `sessions/`); the cost
  matrix above keeps one priced copy per arm-task (min rule, see
  Methodology).
- **Gateway id lowercasing**: `FW-GLM-5.3` (catalog upper-case) is
  rejected — opencode lowercases gateway ids (`fw-glm-5.3`).
- **pro no-variant arm dead**: `fw-deepseek-v4-pro` without a variant is a
  gateway server error ×3 attempts — never send a variant-less request for
  this model through the gateway.

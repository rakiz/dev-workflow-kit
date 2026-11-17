# 2026-11-16 — bench-v3 matrix-completion campaign (p5/p6/p7/p8)

**Purpose:** complete the missing model×task cells for the roster re-arbitration
(owner request: "tous les modèles sur toutes les tâches"). 39 arms + 40 scorer
runs. Budget: ~$15.6 total (arms $13.2 + scoring ~$2.4). All scores first-pass
single-scorer (haiku `default`), double-scoring (§5.2) still pending — cells
marked * are single-valid-run and provisional.

## Tasks and codes

Bench-v3 task codes (EVALS.md migration table): O = orchestration (fixture
SYNC1), I-v2 = impl (fixture RG3, /14), D = design authoring (substrate D1
+ snaputil, /11), IR = impl-review (fixture SYNC1, /3), DR-v2 = design-review
(fixture SYNC2, /14). Runners: `run-eval-v4.sh` (I-v2/D), new
`run-eval-v5.sh` (O/IR/DR-v2 — same fail-closed cap machinery; the historical
v1/v2 runners stay frozen).

## Results by model

Means per the two-run rule; (runs) listed; DNF/null runs marked.

| Model (effort) | O | I-v2 /14 | $/t | D /11 | $/t | IR /3 | DR-v2 /14 |
|---|---|---|---|---|---|---|---|
| opus-5.5 default | — | 10 (10,10) | .95 | 8.75 (9.5,8) | 1.82 | — | — |
| sonnet-5.5 high | — | 9 (8,10) | .40 | 7 (6.5, 7.5*) | .79–1.26 | — | — |
| terra medium | — | 7.5 (8,7) | .11 | 4 (4,4) | .14 | — | — |
| qwen xhigh | — | 5.3 (6,7,2,6) | ~.95 | 4.7 (0,5,6,7.5) | ~1.19 | — | — |
| hydrogen high | PARTIAL/PASS | 4.5* (7; 2=null) | .08–.65 | 6 (7,5) | .27–.43 | 2/3+2, 2/3+1, 1–2 FP | **−1, 2** |
| hydrogen medium | PARTIAL ×2 | 5 (5,5) | .32 | 3.5* (7; 0=null) | .09–.19 | 3/3+1, 3/3+2, 1–2 FP | 4, 5 |
| haiku default | 6/10 (10-07) | 6 (6,6) | .023 | 5 (5,5) | .018 | 3/3 0FP (floor) | — |
| glm-5.3-flash high | **PASS** (10-16) | 5.5 (6,5) | .03 | 0 (all efforts) | .03 | 3/3+2 2FP high | — |
| glm-5.3-flash low | PARTIAL (10-14) | — | — | 1 (low/med/high ≤1) | .011 | 3/3+2 0FP (single) | — |
| minimax-m3p1 medium | — | 5 (2,8) | .06 | 5 (8, 2; 2 DNF) | .03–.05 | — | 10/10 (10-23) |
| deepseek-v4.1-flash | — | 4.5 (2,7) | .03 | 5* (5; p3 DNF) | .03 | — | — |
| 1017 medium | PASS medium+ (10-19); low FAIL | 4.5 (2,7) | .07 | 6.5 (7,6) | .12 | — | 10/10 (10-19) |
| argon high | PARTIAL ×3 (10-14) | 7* (2 null runs) | .12–.96 | 5* (2 null runs) | .13–.70 | — | 9.5/14 avg (11-01, 11-10) |
| fw-deepseek-v4-pro high | — | **DEAD** (gateway: model does not exist) | — | **DEAD** | — | — | 9–10/10 (09-30, pre-mortem) |

Minimax D addendum (19:20): p9 arm = 15-min watchdog DNF; p9r2 = 2/11 (1 FP: H3 named-but-false "normpath protects"; raw 5 without the FP). Two-run D mean (8+2)/2 = 5 vs 1017's 6.5 — minimax stays design-review-only (cheap-design stays 1017).

Fixtures p5 argon/hydrogen null runs: provider "Failed to process successful
response" after real work (logs preserved); one arm-killed-timeout each. Not
capability data.

## Roster decisions taken (owner-approved 11-16)

1. cheap-code: glm `high` → **haiku `default`** (I-v2 6 vs 5.5, cheaper).
   Cliff note: haiku prompts >100k pay 5× — keep impl briefs <90k, fallback 1017.
2. cheap-review: haiku → **glm `low`** (IR 3/3+2 0FP $0.0051, single-run —
   lineage swap so impl ≠ review family).
3. cheap-design: glm `low` → **1017 `medium`** (D 6.5 two-run vs glm ≤1 at all
   efforts). glm D failure is effort-independent: asserts shipped helpers'
   false contracts (H1 trap, −3 every round), never executes proofs.
4. strong-design-alternative: terra → **hydrogen `high`** (D 6 vs 4; IR2-v2 —
   hydrogen is REFUTED for review: DR-v2 −1/2/4/5 vs argon 9.5; IR 1–2 FP/run).
   terra = documented fallback.
5. strong-design-review-alternative2: fw-deepseek-v4-pro (dead gateway id) →
   **grok-4.7** (owner rule: alternative2 rungs are parking for good models).

Unchanged: orchestration glm `high` (O PASS $0.005; hydrogen O PARTIAL at 10×
cost), sonnet strong-code/design, opus deep/alt2, deepseek-flash
cheap-mech/explore, minimax cheap-design-review, qwen strong-review-alternative2
(IV2/D variance 0→7.5 noted, review rung untouched), 1017 strong-design-review
(dual rung with cheap-design — SPOF accepted, fallbacks documented), argon
strong-design-review-alternative.

## Deviations (owner-reviewable)

1. sonnet D p5 (ai-gateway-anthropic) died on a server error; roster provider
   github-copilot used for the p5r2 re-run.
2. sonnet D needed the 30-min watchdog (`EVAL_TIMEOUT_SECS=1800` added to v4/v5);
   15-min = systematic DNF for sonnet on the D substrate (p4 ×2, p5).
3. qwen p5 arms hit the mid cost-cap (2×$0.30) — re-run p6 at strong cap.
   qwen IV2/D cost ~$1/task: it is the most expensive per-task model measured
   on these benches.
4. Single-scorer first-pass throughout (budget); §5.2 double-scoring pending.
5. Report-dependent items (ambiguity/baseline/c′-counts/FP) scored 0 for runs
   whose final report was not captured in the run dir (all p5 arms; cost-capped
   qwen p5).

## Raw

Run dirs were extracted on 2026-11-17 into `2026-11-16/runs/` (per-run
artifacts: plan/review/critique text, I2 diffs, D designs, final assistant
reports; per-run scores + statuses: `2026-11-16/grid2-run-scores.tsv`) and
archived as `runs.tar.gz` — the `2026-11-16/raw/` trees are retired (git
history only). Campaign logs stay gz-available in `2026-11-16/logs/`. Costs
via the opencode DB (session titles `eval-2026-11-16-*`,
`2026-11-16/grid2-costs.tsv`).

## grid2 — full matrix completion (164 runs + 24 fills, 2026-11-16/17)

**Scope:** all previously-evaluated models × all efforts (one effort for
sonnet/opus/fable/astra and the one-effort-policy models) × 5 decision
benches (O, IR, DR-v2, I-v2, D), 2 valid runs per cell (1 for the expensive
arms), ~$66 runs + scoring; session total **$82.85** (cap $120).
Cell-level source of truth: **`2026-11-16/grid2-scores.csv`** (per-run
costs: `2026-11-16/grid2-costs.tsv`); the leaderboard's charts + score
matrix (`evals/LEADERBOARD.html`) are generated from it.

**Headline findings:**

- **minimax `xhigh` DR-v2 11.5/14** (runs 9, 14 — first DR-v2 with executed
  proofs, 4 proofs) — the best design-review measured, at $0.03/task.
  The seat stays on `medium`.
- **1017 `high` D 8.25/11** — the best design authoring outside opus (8.75),
  at $0.12/task.
- **haiku `high` I-v2 9 and hydrogen `high` I-v2 9** — the cheap impl tier is
  now sonnet-adjacent (sonnet 9, opus 10).
- The **H3 false-positive** ("normpath protects" — named-but-false) killed
  glm, gem38, qwen, muse, minimax `low` and fable on D: the bench
  discriminates.
- **opus DR-v2 0/14 (2 FPs)** — the deep rung must NOT review designs.
- **astra** performs at sonnet-class (I-v2 8, D 6) but at ~$4/task; **fable**
  is incoherent (O 1/8 hallucination, D false claim) — both stay out.
- **IR is saturated** — 16 of the 46 measured model×effort cells sit at IR
  3/3 — an IR-v2 harder bench is needed before IR cells can separate models.
- **O /8 rubric is now numeric**: opus 7.5 > haiku med/high 7 > 1017-high 7 >
  sonnet 6.5 ≈ haiku-default 6.5 > glm ≈5 (dsflash 5). glm keeps
  orchestration on price — PASS-equivalent 5–7/8 at 1/10 the cost.

**DNF / no-measurement cells:**

- carbon `high` I-v2: 4 costcap DNFs — unmeasurable at $0.60 cap.
- argon `high` I-v2/D: provider ECONNRESET retries — single valid run each
  (7*, 5.25*).
- glm O: numeric arm hit 2 DNFs — kept categorical (PARTIAL `low` /
  PASS `high`).
- qwen/argon/hydrogen O: partly single-run.
- **Effort-policy skips** (deliberately not run — one-effort rule; cells
  marked in the matrix): hydrogen `low` (whole row); hydrogen `xhigh`
  O/IR/DR-v2 (g5 measured only I-v2/D); argon
  `low`/`medium` I-v2/D; carbon `low`/`medium` I-v2/D; gem38 `low`/`high`
  DR-v2+I-v2+D; sol `low`/`xhigh` DR-v2+I-v2+D; muse `low`/`high`/`xhigh`
  DR-v2+I-v2+D; kimi `high` DR-v2+I-v2+D; sonnet `medium` DR-v2/I-v2/D.

Cell-level source of truth: `2026-11-16/grid2-scores.csv`.

## Unmeasured cells — why they would not change the roster (owner-validated 11-17)

Deliberately not run (one-effort policy, price, or futility). None of these
cells could flip a seat:

- **`max` effort everywhere, 1017 `max`**: standing lesson — `max` has never
  paid for itself and breaks delivery on flash-tier models (haiku dead
  sessions, deepseek lower recall at 4× cost). Excluded by rule, not by
  budget.
- **hydrogen `low`** (whole row): the cheap tier needs cheap; hydrogen's
  cheapest measured effort (medium) is already the most expensive seat-holder
  candidate at $0.09+ — a `low` cell cannot win a seat held at $0.02-0.10.
- **argon low/medium I2/D, carbon low/medium I2/D**: one-effort policy. The
  seated efforts (argon high, carbon high) are measured; their siblings'
  scores were flat in every measured bench (argon O flat 5-6 across efforts,
  carbon DR2 10 at high only) — no signal that a lower effort would overtake
  a seat.
- **gem38 / sol / muse low-high-xhigh (DR2/I2/D), kimi high (DR2/I2/D),
  sonnet-medium (DR2/I2/D)**: these models' measured efforts score below the
  seat holders on the same benches (gem38 D 0.5-1, muse DR2 1, kimi DR2 5.5,
  sol DR2 5); effort never moved any of them more than ~1 pt on any bench —
  less than the gap to the seats.
- **sonnet `xhigh`, opus `xhigh`**: terminal or contested seats — sonnet's
  code seat (I2 9) is healthy and its design seat cedes to 1017-high anyway;
  opus owns the terminal deep rung with no challenger.
- **grok-4.7 (whole row)**: parking seat by owner rule — alternative2 rungs
  exist to keep good models warm, not to win measurements.
- **fable/astra beyond the single default runs**: fable is incoherent (O 1/8
  hallucination, D FP −3), astra performs at sonnet class but at ~$4/task —
  neither can take a seat its price cannot justify. Re-entry: price drop.
- **fw-deepseek-v4-pro**: gateway id retired (server-side); unmeasurable.

## xhigh/carbon closure (g5, 9 runs)

- **hydrogen `xhigh` D 6.75** (6.5;7) — solid but does not threaten 1017
  `high` (8.25) at 5–8× the cost; **I-v2 2;2** (no-edit watchdog kills) —
  hydrogen xhigh impl is broken, effort non-monotone.
- **minimax `xhigh` I-v2 confirmed 8** (8;8) — stable, no longer single-valid;
  strong-code-alternative challenger vs terra 7.5 @$0.11.
- **carbon I-v2 still unmeasurable** (4 costcap DNFs), D stays single 6.5.

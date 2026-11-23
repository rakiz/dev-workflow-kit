# 2026-11-23 — housekeeping session: carbon confirmation run, Étape 3 blind measurement, watch items

Owner decisions taken this session (all four residues of the audit ruled): mai no-seat
confirmed; carbon q53 attempted (see §1); held-out fixture rebuild confirmed as a
STANDING GATE (not scheduled); Étape 3 blind-vs-unblind measured (§2); IMPROVEMENT_PLAN
§4+§8 moved to `docs/BACKLOG-external-ideas.md` (Part C), the plan is now FULLY
DISPOSITIONED.

## 1. carbon-high I2-RG4 confirmation run (q53)

The 14* single-run dot (q51, $1.97) needed a second run or an explicit single-run
acceptance. Owner chose to run it after the true cost was disclosed (carbon-high is
expensive and DNF-prone on this bench: q51 $1.97 scored, q52 DNF $2.29, q54/q54b
not-completed).

- q53: killed by the arm cost-cap ($0.6363 > 2×$0.30 — cap set from a stale estimate;
  the run-ops row records the real spend/tokens).
- q53b (cap $1.00): **delivered, scored 14/14 by BOTH panel families (0 FP each)** —
  glm: all probes pass, own tests fail pristine, baseline verified; minimax: same,
  both baselines quoted. Note recorded by the scorer: 14/14 is the reachable max,
  above the rubric's gate-1 anti-saturation bound (best ≤ 11) — the RG4 gate-1 caveat
  applies to this arm as it did at the 11-20 closure.
- **Official cell: carbon-high I2-RG4 = 14 (2 valid runs; mean of 14;14).** The star is
  removed; the dot is now filled at the mean delivered cost ($1.67/task). The
  ceiling-censorship caveat (HOLDOUT §7.2 standing gate) still applies to any seat
  decision.
- Spend: $0.6363 (q53, DNF) + $1.3637 (q53b) = **$2.00**. Folded: grid2-scores.csv
  (value + notes), run-ops.tsv (2 rows), gen-charts I2-RG4 title sentence.
  verify-charts: 195/195 dots, 85/85 findings/FP tooltips.

## 2. Étape 3 — blind vs unblind residual-bias measurement (BLIND-SPEC.md)

Pre-registered spec: `evals/2026-11-23/BLIND-SPEC.md` (committed before any blind score
was read). Sample: 10 runs, per bench the highest- and lowest-scoring delivered runs of
the standing ledgers, anonymized into the PRIVATE repo
(`evals-keys@score-logs/2026-11-23/blind-sample/`, randomized IDs R01-R10, leak-grep 0
on the full token list), scored blind by the standing 2-family panel.

**Result: residual (unblind − blind, SAME family, self-family rows excluded, n=15):
mean −0.48 pt** (glm +0.09 over 8 pairs; minimax −1.21 over 7 pairs; per-run range
−2.5..+2). Pre-registered bands: |mean| < 0.5 → "no operative bias, Étape 3 closed".
**Étape 3 is CLOSED — the standing panel is kept, no permanent blinding required.**

Reading:

- The minimax deltas cluster at −2.5 on the three negative runs (IR/DR2/D failures) —
  the same direction and size as the RECORDED minimax family offset (harsher FP
  posture), i.e. family bias, not blindness.
- The largest positive confound check: R10 (fable O) first appeared as a +5 anomaly —
  it was a SAMPLE-BUILD error (the lowest-O lookup read the fable cell value 1 from a
  different effort; the run's true unblind panel reading is 6, matching blind glm 6 and
  minimax 5). No blinding artifact.
- Self-family exclusions applied: R01/R07 (glm), R08 (minimax). R07's minimax blind
  reading (8 vs the glm+haiku official mean 9) is cross-panel — recorded, not folded
  into the verdict.
- Caveat (recorded in the spec): n=10 runs / 15 family-pairs is a smoke measurement; it
  bounds gross bias, it is not an MDE. A future re-measure belongs with a new bench
  generation.
- Panel incidents: the glm session dropped one scored row from its TSV (R08 = 13,
  recovered from the session log, breakdown not printed — recorded as a partial
  reading); the minimax sessions died twice on invented out-of-scope paths
  (`external_directory` auto-rejection in headless mode) before a clean run — the
  working fix is launching the scorer session at the common parent directory so the
  whole perimeter is internal. Recorded here for future panel drivers: prefer a --dir
  that covers every path the scorer may touch, and keep the scorer's commands small.

## 3. Watch items recorded (COMPARATORS.md)

- **MaxxBench** (unlap.ai, 89 mutated DeepSWE tasks): strong methodological alignment
  with the O red-baseline construct (grader-guessing ≈ trap-ignoring); our roster's
  models measured there at vendor-max effort.
- **DS/GLM effort semantics** (owner-provided, gateway-verified): low/high/max only —
  `medium` is rounded up to high server-side; DS accepts 1-100; GLM defaults to max and
  recommends max for coding. Grid arms labeled `medium` on glm/DS models actually ran
  at high (records corrected in the notes; no seat was decided on a glm/DS medium arm).
- **GLM-5.4** (loop transformer, announced today): catchup campaign as soon as a
  gateway exposes it; the default (= max) arm runs as-is.
- **GLM-5.3-flash max arm on O** (cents): the cheap watch item — candidate for a
  one-bench confirmation of the O seat under the vendor-recommended effort.

## 4. Spend (session total)

| Item | USD |
|---|---|
| carbon q53 (killed) | 0.6363 |
| carbon q53b (scored) | 1.3637 |
| Blind panel: glm batch + minimax (r1/r2 killed, r4 killed, r5 done) | ~0.35 |
| carbon scoring panel (glm + minimax) | ~0.10 |
| **Total** | **~$2.45** |

## 5. Roster change applied + O-bench saturation status

- **Orchestration seat: glm-5.3-flash `high` → `max`** (owner 2026-11-23). The max arm
  (this session) posts **8/8 unanimous** (minimax 8 + sonnet 8, no divergence, hall=0 —
  red baseline pinned) at **$0.007/task = the cost of high** ($0.005). The 7→8 gap is
  under the O noise band (no operative MDE at n=4): a free upgrade on a tie, NOT a
  quality claim. **Ceiling censorship (owner correction 2026-11-23, supersedes any
  "best on O" reading): 8/8 is the RUBRIC MAXIMUM — every top-band O score is
  censored, and a model worth "15" on this scale would post the same 8. The seat rests
  on price + tie + vendor alignment only; O says NOTHING about relative quality above
  the ceiling.** Session config now pins `variant: max` explicitly (NB: the build agent
  carried NO variant line — it was already running at the server default, which for GLM
  IS max; the pin makes the config truthful). Folded: SEATS map, #roster row,
  roster/MODELS.md seat text, reasons.py why-texts. verify-charts 196/196.
- **O-bench saturation (recorded, no rebuild yet)**: the 7-8 band now holds ~15 cells
  across generations; the top cannot be separated within noise. The red-baseline trap
  still catches (mai 0, muse-xhigh invents a green baseline, fable 6) and the tie rule
  (price) still decides seats — so no rebuild NOW. **O-v2 rebuild triggers
  (pre-registered here):** (a) a challenger claims the O seat inside the 8-band at a
  comparable price (the tie rule could no longer separate) — the most likely case,
  since ALL top-band O readings are ceiling-censored at the rubric max of 8;
  (b) the red-baseline trap
  stops catching tested models; (c) any future campaign needing a top-band ranking.
  Bench-generation ledger: T4→DR-v2 (11-01) and I2→I2-RG4 (11-20) rebuilt; IR's ceiling
  is handled by the bonus axis; O is the third bench showing a limit, the first whose
  own seat decision sits in the noise.
- **O seat stability confirmed ×3 (same-day follow-up, glmmax-confirmation runs)**: the
  single-run 8/8 above was re-run twice (`glmmax2c`, `glmmax3`) and scored by the
  standing 2-family panel (minimax + sonnet; glm self-family excluded): runs
  8;7;7 conservative panel scores (per-run means 8;7;7.5 — 2c unanimous 7, 3 carries a
  1-pt R divergence: minimax credits the explicit verify-at-HEAD step, sonnet reads the
  plan as hedged), hall=0 across all six scorer readings, red baseline caught in every
  run, delivery 3/3 at $0.0056-0.0073/task (panel spend $0.23). Two DNF attempts
  (glmmax2/2b, $0) were operator error (model id dashes-vs-dots copied from a session
  title) — post-mortem + lesson in `glmmax-confirmation.status.txt`. Folded:
  grid2-run-scores.tsv (5 rows), grid2-scores.csv (glm,max O8 → 7.33, n=3),
  run-ops.tsv (regenerated, 486 runs), reasons.py, roster/MODELS.md, EVALS.md,
  LEADERBOARD.html. **No further O runs planned — the next O evaluation trigger is the
  GLM-5.4 catchup (watch item §3) or another model release, not more O arm repetitions.**

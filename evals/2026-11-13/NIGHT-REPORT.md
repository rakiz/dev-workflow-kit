# Bench-v3 redesign — night session report (2026-11-12/13, owner-delegated)

**NOTHING COMMITTED — all files in the working tree / private keys repo are uncommitted; every
owner decision below is PROVISIONAL pending your review. Budget: ~$14.4 spent (cap $20).**

## 1. What was built (the new protocol)

Adopted from the strong-design corrected proposal (`/tmp/opencode/bench-v3-redesign-proposal-v2.md`),
all decisions owner-delegated for the night, PROVISIONAL:

- **I-v2 redesign (fixture RG3, `evals/reportgen-eval-repo-i3/` + private fixed copy):**
  all 4 defect instances re-seeded (the round-2 fixed trees are public — old answers void).
  New shapes: (a) registry-version stamp never compared at lookup (bait docstring in
  transforms.py), (b) `generated_from` cold/warm divergence, (c′) loop-nested redundant
  rules re-read (the replacement perf defect, 4 pts: graded fix 0/1/2 + test + quoted counts),
  (d) validate-after-html-write + exit-0 swallow. Score formula: suite 2 + (a,b,d: fix+test)×3
  + c′ 4 + ambiguity 1 + baseline 1 = **M 14**. Gates re-frozen: g1 ≤ 11, g2 floor 3.
- **D redesign (substrate D1 + NEW `snaputil.py`, 92 lines):** Part A entailed ÷2 (max 4),
  **4 seeded execution-revealed hazards** (H1 lex-prune deletes the newest snapshot; H2
  per-call full-rescan usage; H3 safe-path escape via `..`; H4 float-vs-ns staleness),
  Part B unchanged. Basis = A/2 + H − penalty − FP + B = **M 11**. Gates: g1 ≤ 8.8, g2 floor 3.
- Rubrics: `RUBRIC-IV2-RG3.md` + `RUBRIC-D1-v2.md` in the private keys repo (uncommitted).
  §3.8: probes verified 3/3 both directions (builder) + independent scorer confirmation;
  leakage greps zero hits. Runner: `evals/run-eval-v4.sh` (uncommitted).

## 2. Results — fresh pilot (p3) + second round (p4), same 4 models

### I-v2 (/14; two-run arm score = MEAN, per the frozen two-run rule)

| Arm | p3 | p4 | Mean | Re-run Δ | Cost p3+p4 |
|---|---|---|---|---|---|
| opus-5.5 default | 10 | 10 | **10** | 0 | $1.90 |
| sonnet-5.5 high | 8 | 10 | **9** | 2 | $0.80 |
| terra medium | 8 | 7 | **7.5** | 1 | $0.22 |
| glm-5.3-flash high | 6 | 5 | **5.5** | 1 | $0.06 |

- **Gate 1 (≤11): PASS — first time in bench-v3 history.** The re-weight worked; c′ earned 0
  everywhere (headroom-only block).
- **Gate 2 (sonnet−terra ≥ 3): FAIL** — mean gap 1.5 (round-to-round the pair FLIPPED: p3
  8−8=0, p4 10−7=3). Robustly below the floor even ignoring variance.
- **c′ wiped out everywhere again**: 0 points across ALL arms both rounds (the c′ probe failed in
  every build) — the THIRD measurement-forcing shape in a row that no model fixes
  (parse-before-check r1, stdout signal r2, loop-nested r3). Conclusion for the redesign:
  in this domain, no model measures unless forced; a 4-point block nobody can earn is
  headroom, not discrimination.

### D (/11; basis = A/2 + hazards − penalty − FP + Part B)

| Arm | p3 | p4 | Mean | Cost p3+p4 |
|---|---|---|---|---|
| opus-5.5 default | 9.5 | 8 | **8.75** | $3.63 |
| sonnet-5.5 high | 6.5 | DNF×2 (watchdog) | 6.5* | $0.40+$1.18+DNFs |
| terra medium | 4 | 4 | **4** | $0.28 |
| glm-5.3-flash low | 2 | 0 (floor) | **1** | $0.02 |

*single-run (both p4 sonnet attempts DNF'd — see deviations). p4 questionnaires not run
(3 arms); p3 questionnaire outcomes used as provisional penalties (glm −1, terra −1, opus 0).

- **Gate 1 (≤8.8): PASS by 0.05** — opus 8.75, hinges on 2 scorer judgment flags (opus H1
  full-vs-half, H4 half-vs-0) and the pending questionnaire. Fragile.
- **Gate 2 (sonnet−terra ≥ 3): FAIL** — 2.5 < 3 (both rounds where evaluable).
- **Hazard findability (the new block, the disclosed central risk):** H3 (path escape) found
  by EVERY arm — it is the one genuinely findable hazard. H1 found by opus + hydrogen-high
  (2/8 arms). H2 found by NOBODY (0/10 arms). H4's seeded mechanism (float-vs-ns) named by
  nobody — arms found the adjacent `<=`-vs-docstring bug instead (scored 0-0.5).
  Hazards found by the best arm: 2.5/4 (p3) — the "≥2 ⇒ g1 fails" conditional fired in p3
  (9.5 > 8.8) and passed in p4 (8 ≤ 8.8) — the gate sits exactly on the knife edge.
- **Part B (executed proofs) now earned widely**: 3/3, 1, 0, 0 (p3) / 3, 1, 0, 0 (p4) — the
  round-2 re-freeze premise (proofs discriminate) is CONFIRMED as the main real spread.

## 3. Verdict on the redesign generation (2 fresh rounds spent)

Per the adopted pilot-kill rule (any gate fail after the 2nd fresh round ⇒ shelve):

- **I-v2: g2 FAIL both rounds → SHELVED** (g1 finally passes; the pair axis cannot — the
  sonnet/terra flip round-to-round is worth 3 points of noise on a 14-point bench).
- **D: g2 FAIL both rounds → SHELVED** (g1 knife-edge; g2 at 2.5 — 0.5 short).

Honest reading: the two tasks now MEASURE something real (g1 anti-saturation passes, the
score ordering opus > sonnet > terra > glm is stable on I-v2, and D's Part B + hazards
discriminate) — what they cannot do is satisfy the pre-registered 3-point pair floor with
these four models. The gap is 1.5-2.5 points: EITHER the floor is set for a discrimination
these benches genuinely lack (fix: owner re-freezes gate 2 at ≥2 with the recorded variance
data — an owner decision, never mine), OR the benches need one more discriminating block
(a 5th I-v2 defect class nobody fixes; D hazards that only the strongest find — H2-style
cost traps are the only shape nobody found).

## 4. ROSTER DATA (what you asked the night for — proposal only, roster untouched)

Two-run means where available; costs are per-task p3+p4 actuals. Scores are first-pass
(no double-scoring this session — budget; §5.2 double-score marked as pending).

| Model (effort) | I-v2 /14 | D /11 | Cost/task | Rung today | Rung read |
|---|---|---|---|---|---|
| claude-opus-5.5 (default) | **10** | **8.75** | $0.95 / $1.82 | deep | best impl; best design — but D g1 knife-edge |
| claude-sonnet-5.5 (high) | **9** | 6.5* | $0.40 / $0.79 | strong-code / strong-design | solid #2 impl; D below minimax(!) |
| gemini-4-hydrogen (high) | 7 | 7 | $0.65 / $0.43 | — NEW | **dominates sonnet on D cost/quality** (7 @ $0.43 vs 6.5 @ $0.79); #3 impl |
| gemini-4-hydrogen (medium) | 5 | 7 | $0.36 / $0.19 | — NEW | D flat vs its own high; IV2 effort-sensitive |
| gpt-6.1-terra (medium) | 7.5 | 4 | $0.11 / $0.14 | strong-code-alternative | mid everywhere, stable |
| claude-haiku-5.5 (default) | 6 | 5 | ~$0.02 / ~$0.02 | (stage-2 cell) | **cheapest decent cell** — IV2 6 ≈ glm 5.5 |
| glm-5.3-flash (high/low) | 5.5 | 1 | $0.03 / $0.01 | cheap-code / cheap-design | impl OK; D collapses (FP −3 both rounds on H1) |
| minimax-m3p1-flash (medium) | 2 | **8** | $0.03 / $0.03 | design-review | **D surprise: 8/11, Part B 3/3** — but IV2 zero-ish |
| fw-deepseek-v4p1-flash (default) | 2 (zero-fix, no report) | DNF | $0.02 | cheap-mech / explore | IV2: fixed nothing; D: no deliverable |
| fw-deepseek-v4p1-flash-1017 (medium) | 2 (zero-fix, no report) | DNF | $0.03 | explore | same shape |

### Roster PROPOSAL (for your review — NOTHING changed)

1. **Keep**: opus = deep; sonnet = strong-code; glm = cheap-code (haiku's 6-vs-5.5 is one
   point at 2× the cheap-code price — not worth the swap on this data alone).
2. ** hydrogen (high) as strong-design-alternative CANDIDATE** — it beats the current
   incumbent's bench numbers (D 7 vs sonnet 6.5, at half the cost) but argon (the current
   alternative) was NOT re-tested tonight (budget) — decide after an argon D cell.
3. **Consider haiku for cheap-design** — D 5 vs glm's 1 at similar cost; glm's D failure is
   a repeated FP on the H1 hazard (asserting the false "newest always kept" contract).
   cheap-design's current bench evidence (DR-v2) is old; this is the first D-tier data.
4. **Do not promote minimax to any design-authoring rung despite D 8** — its IV2 (2/14)
   shows the same code-avoidance shape that DR benches exist to catch; keep it on
   design-review.
5. **deepseek-flash / 1017: no change possible from this data** (IV2 zero-fix + D DNF) —
   if their cheap-mech/explore rungs ever need re-validation, it will not come from these
   benches.

## 4 bis. Addendum — glm effort-grid on D (the owner's "maybe better at medium/high" hypothesis: REFUTED)

| Cell (D basis) | Score /11 | Cost |
|---|---|---|
| glm `low` (rostered cheap-design) | 1 | $0.011 |
| glm `medium` | 0 (−3 raw, floor) | $0.012 |
| glm `high` | 0 | $0.026 |
| **haiku `default`** | **5** | **$0.018** |
| hydrogen `medium` | 7 | $0.19 |

glm scores ≤0 on the D basis at EVERY effort — the failure is effort-independent:
at low, medium AND high it asserts the shipped helpers' false contracts without
running them (the H1 "newest always kept" trap, −3 every time; at high, a second
FP on dot-files) and never quotes executed proofs. Part A stays 4/4 everywhere —
it can design, it just never verifies. **haiku dominates glm outright on
cheap-design: better score AND lower cost ($0.018 vs $0.011-0.026).**
hydrogen `medium` (7 @ $0.19) is the quality upgrade, 10× haiku's cost.
Recommendation stands, now with full effort-grid evidence: **cheap-design → haiku
`default`**; revisit only if a 7/11 quality bar is needed at 10× the cost.

## 5. Deviations recorded (all owner-reviewable)

1. Provider switch for claude arms mid-session-1 (github-copilot outage → ai-gateway-anthropic) — carried over from your instruction.
2. Watchdog raised to 30 min for D-opus arms ONLY (the frozen 15-min cap = systematic DNF for opus on the hazard substrate; cost-poller still bounds spend). D-sonnet kept 15 min and DNF'd twice in p4 — its p3 cell is single-run.
3. §5.4-style two-run executed as p3/p4 for all four IV2 arms (means + deltas above); D arms ran twice but sonnet's p4 is DNF.
4. Double-scoring (§5.2) skipped this session (budget) — best/worst p3 arms were double-scored earlier in round 2, not tonight.
5. p4 D questionnaires not run (3 arms) — penalties provisionally inherited from p3.
6. Adjudication flags accumulated for you: glm FP mis-attribution (−3 swing, ×2 rounds), haiku baseline paraphrase call, H4 half-credit calls (3 arms), opus H1 full-vs-half, hydrogen-high H1 full-vs-half, glm negative-total floor, terra d-test gating clause.

## 6. Budget ledger (night work only, from the DB)

Redesign chain $1.00 + fixture builds $0.14 + QA attempts $1.85 + fresh pilot p3 $4.72 +
second round p4 $2.90 + hydrogen 4 arms $1.62 + fleet 8 arms $0.47 + scoring $0.35 ≈ **$14.4**
(cap $20 — $5.6 unused).

## 7. Raw

`evals/2026-11-12/raw-round2/` — all p3/p4/fleet/QA run dirs (26 trees, DNFs included).
RETIRED 2026-11-17 (superseded, git history only): the scoreable p3/p4 run
dirs were extracted into `evals/2026-11-16/runs/` and archived as
`runs.tar.gz`. Final reports extracted: `/tmp/opencode/p3-reports/` (copy into the eval dir before committing).

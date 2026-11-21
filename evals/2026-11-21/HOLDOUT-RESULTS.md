# HOLDOUT-RESULTS — Étape 2 held-out campaign (2026-11-21)

**Verdict: no seat moves.** The held-out benches fail their own validity gates (HOLDOUT-SPEC §7.4 Step 1),
so no seat decision is valid from this campaign. The pair verdicts below are reported for transparency only.
The impl bench (HO2) is ceiling-censored at the top and the design bench (HOD) is at its ceiling too.

Construct-level only. No key value, probe output or defect identity is reproduced here (SPEC §5.2, §8.5).

## 1. Campaign and blinding

- Mandatory block: 24 candidate runs (HO2 18, HOD 6), all `ok` with a final report or design file; 0 DNF.
  Campaign id `holdout-mandatory-2026-11-21-2`. A first attempt (`…-2026-11-21`) ran one valid arm (haiku HO2 a1,
  $0.0234) and aborted on a driver title-check bug, which is fixed; the arm is kept as evidence and is not counted.
- Blinding (§5.7): 24 per-run blinded copies with random ids. The ID→arm map sits in a sealed directory outside
  the blinded tree and was unsealed only after the scores were locked. Verification grep over the blinded tree:
  0 hits for every vendor, model, effort and campaign token, and 0 hits for any real title. Generated dirs were
  excluded.

## 2. Panel (§5.7/§5.8)

- Six mandatory batches (bench × scorer family, pairing table): HO2×{glm, minimax, haiku}, HOD×{glm, minimax, haiku}.
  Every run received exactly two family readings, from the two families the table assigns. 48 readings, 0 missing.
- Scorers ran the frozen probes on scratch copies inside a sandbox. Deterministic items were taken from the operator's
  own probe run; judgement items from the panel. The two agreed except where noted in §6.
- Divergence (≥ 2.0 points between the two family readings): **11 of 24 runs**. The arbiter (gemini-4-neon) was
  run for both benches and was killed by its cost guard before producing a reading (§6). **No arbiter readings exist**,
  so the official score for every run is the two-family mean.
- DNF: 0 scorer batches failed; 2 arbiter sessions failed.

## 3. Per-arm scores (two-family means over runs; n = runs)

| Arm | n | mean | sd |
|---|---|---|---|
| HO2 opus | 2 | 11.25 | 0.35 |
| HO2 haiku-default (anchor) | 4 | 9.00 | 2.48 |
| HO2 minimax-xhigh | 4 | 8.63 | 2.29 |
| HO2 haiku-high | 2 | 7.75 | 1.06 |
| HO2 dsflash | 2 | 7.50 | 2.12 |
| HO2 glm-high | 4 | 6.88 | 0.25 |
| HOD haiku-medium (anchor) | 4 | 9.13 | 0.75 |
| HOD 1017-high | 2 | 7.38 | 2.30 |

Scale: HO2 max 14, HOD max 11.

## 4. Validity gates (§7.4 Step 1)

| Gate | HO2 | HOD |
|---|---|---|
| Gate 1 (best ≤ 11/14 for HO2, ≤ 8.8/11 for HOD) | **FAIL**: opus 11.25 | **FAIL**: haiku-medium 9.13 |
| Floor (anchor ≤ 3/14, ≤ 2.5/11: not too hard) | pass (anchor 9.00) | pass (anchor 9.13) |
| Gate 2 (pair gap ≥ max(3, 2·sd_anchor)) | **FAIL**: largest gap 3.50 < 4.97 | **FAIL**: gap 1.75 < 3.00 |

Both floors pass (the benches are not too hard), but both fail Gate 1 (the top arm sits at the ceiling), and both fail Gate 2.
**Consequence: no seat decision from either bench. Both fixtures are closed for seat use.**

## 5. Pair verdicts (§7.4 Step 2–3; band = max(prior, C(n_anchor)·sd_anchor·√(1/n_H + 1/n_C)))

The three owner-slot rulings (P3, P4, P7) are recorded under the new PROTOCOL §5(e) collapse exemption (owner 2026-11-21). **NO seat moved on the held-out** — the benches stay ceiling-censored regardless.

Priors: HO2 4.80, HOD 1.04. C(4) = 4.16. Anchor sd: HO2 2.48, HOD 0.75.

| Pair | Holder vs challenger | Δ (H−C) | Band | Verdict (reported; not a seat decision) | Seat effect |
|---|---|---|---|---|---|
| P1 | haiku-default vs glm-high (cheap-code) | +2.13 | 7.31 | CONFIRM-TIE (holder stays; cheaper arm is the holder) | none |
| P2 | minimax-xhigh vs haiku-high (strong-code) | +0.88 | 8.95 | CONFIRM-TIE (minimax is cheaper; lineage-legal) | none |
| P3 | opus vs haiku-high (deep/alt2) | +3.50 | 10.33 | **RULED — option B, terminal rung exempt, opus stays (owner 2026-11-21; Δ +3.50, band 10.33).** | none |
| P4 | dsflash vs haiku-default (cheap-mech/explore) | −1.50 | 8.95 | **RULED — option B, dsflash keeps cheap-mech + explore (collapse refused: $0.009/task delta does not buy the family-diversity loss; owner 2026-11-21; Δ −1.50, band 8.95).** | none |
| P5 | haiku-medium vs 1017-high (cheap-design) | +1.75 | 2.70 | CONFIRM-TIE; the pre-registered REFUTE was not reached | none (owner confirms) |
| P6 | 1017-high vs opus (phase 2) | — | — | not run (phase 2 is out of this campaign) | — |
| P7 | haiku-high vs minimax-xhigh (strong-code-alt) | −0.88 | 8.95 | **RULED — option B, haiku-high keeps strong-code-alternative (an alternative rung must be a different family from the rung it backs; owner 2026-11-21; Δ −0.88, band 8.95).** | none |
| P8 | sonnet vs 1017-high (phase 2) | — | — | not run | — |
| P9 | opus vs 1017-high (phase 2) | — | — | not run | — |

The verdicts are computed on the scores above, but Gate 1 and Gate 2 fail, so **none of these is a seat decision**.

## 6. Deviations and data-quality findings

1. **Arbiter overspend.** Both arbiter sessions hit the 2× kill (cap $0.28) and were killed, but spend continued after the
   kill signal: $0.56 in the HO2 session (killed at 2×) and $0.83 in the HOD session. The arbiter total is **$1.77**
   against a spec worst case of $0.56. No arbiter reading was produced.
2. **Probe unevaluable on one write route.** Nine HO2 runs wrote the plan through a file descriptor (a temporary
   file created by the stdlib). The frozen probe classifies that injection target as "other", so the item is
   unevaluable and scores 0 with a flag (§1 of the key). After applying that rule, every panel reading agrees with the
   operator except one (item 3). The probe was **not**
   amended, because scores exist and the spec voids the pre-registration on any post-score change. This is an owner
   decision (§7).
3. **One scorer error.** A minimax-family reading gave a 1 on an item the same run's probe marks unevaluable.
   The operator's probe value was used, as the key requires.
4. **One run redefines the attempt unit.** One HO2 run removed the conflict check from the placement path and counts
   its own per-call attempts. The frozen probe then reads zero conflict calls. Read literally, the key gives full credit.
   It is recorded as a judgement for the owner (§7).
5. **Part D questionnaire not run.** No cheap-implementer questionnaire was executed. The HOD score therefore carries
   no questionnaire penalty. This is an explicit omission, not a zero.
6. **Misc-model cost.** opencode records cost 0 for the custom gateway models. The reported USD below applies a
   token-based estimate, using the plugin's catalog prices (low) and the opencode binary's price table (high).

## 7. Owner decisions pending

1. **P3, P4 and P7 ruling slots** (§7.4) — **FILLED** (owner 2026-11-21, PROTOCOL §5(e); verdicts in §5). No seat moved. Only the operations decisions below remain.
2. **Gate failure.** Both benches are ceiling-censored (§4). The RG4 lesson applies: rebuild the fixtures before any further seat decision.
3. **Divergent runs.** 11 runs diverge by ≥ 2.0 and have no arbiter reading. The divergent runs cluster on the pair arms
   (haiku-default, haiku-high, opus, haiku-medium, 1017-high). Any straddling verdict goes to the owner.
4. **Probe amendment versus the frozen key** for the file-descriptor write route (§6.2): accept the current scoring,
   or amend (which voids the pre-registration).
5. **The attempt-unit bypass** (§6.4): count it as a pass, or a unit violation.
6. **Arbiter spend.** Accept the overspend as recorded, or re-run with a per-readings budget.

## 8. Spend reconciliation (USD)

| Component | Recorded in DB | With misc estimate |
|---|---|---|
| Campaign-2 arms (24) | $1.7313 | $2.02 – $2.16 |
| Campaign-1 aborted arm (1) | $0.0234 | $0.0234 |
| Panel, 6 mandatory batches | $0.3205 | $0.63 – $0.70 |
| Arbiters, 2 sessions (over cap) | $1.7731 | $1.7731 |
| **Total** | **$3.85** | **$4.45 – $4.66** |

The campaign's real USD cost is therefore **$2.02 – $2.16** for the candidate arms, and **$4.45 – $4.66** for the whole
session including scoring. The misc range is the only uncertainty; both endpoints are reported.
Meter bytes per run are in the per-arm proxy files (`holdout-tmp/<title>/proxy.json`); they are the only egress control
for the misc arms.

## 9. Roster ordering on held-out

The RG4 ordering (2026-11-20) does **not** replicate on HO2. The two reversals are both within the band: haiku-default
rates above glm-high (RG4: below), and minimax-xhigh rates above haiku-high (RG4: below). The opus arm tops the held-out
ordering. Under §7.4 these reversals are inside the noise and cannot be read as seat evidence, because Gates 1 and 2 fail.

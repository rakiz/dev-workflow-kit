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
  run for both benches and was killed by its cost guard before producing a reading (§6). **No arbiter readings existed at the time of this section; see the arbiter section below (one reading since re-triangulated)**,
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
2. **Probe unevaluable on one write route.** **Five** HO2 runs (corrected 2026-11-21: the earlier "nine"
   miscounted the a_fix zeros; a_fix scored **13/18** runs) wrote the plan through a file descriptor (a
   temporary file created by the stdlib). The frozen probe classifies that injection target as "other", so the
   item is unevaluable and scores 0 with a flag (§1 of the key). After applying that rule, every panel reading agrees with the
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

### Owner rulings on the deviations (2026-11-21)

- **Defect (a) fd-route runs:** 9 HO2 runs scored a_fix=0 + unevaluable flag (frozen key). Owner ruling: accepted. NOTE for future re-evaluation: if precision on defect (a) is ever needed for these runs, the widened probe (all write routes) is the candidate amendment — it lands with the fixture rebuild.
- **T5 attempt-unit bypass (A/B campaign):** one run removed the conflict check from the placement path and counted its own attempts — c_fix scored 0 as a unit violation. Owner rationale: 'tricher ne donne pas confiance dans la qualité du code produit' (cheating does not buy confidence in the produced code). Precedent recorded for future keys: removing the control a counter measures = 0.

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

## Arbiter triangulation (owner decision 5, 2026-11-21)

Owner ruling: re-triangulate the 11 divergent runs with the arbiter (gemini-4-neon) as **advisory readings**. The
two-family means stay official. Ceiling $3, spec session cap $0.28.

### 1. Root cause of the overspend, and the fix

- **Cause.** The scorer launcher stopped a session by signalling only its direct children (`pkill -TERM -P`) and then
  its root with TERM. It had no KILL escalation, no walk of the descendant tree, and no check after the kill. Processes
  that did not exit on TERM, and their children, kept running and kept issuing provider requests. Their cost was booked
  after the kill line was printed. This is why the HOD session went from the $0.56 kill point to $0.83.
- **Reproduced at zero cost.** A stand-in session that ignores TERM, run through the same exec path and the same kill
  sequence, left 4 of 4 processes alive.
- **Fix.** `kill-tree.sh`: snapshot the whole descendant tree before signalling, send TERM, wait, send KILL to any survivor,
  then poll until every process is gone. It reports `TREE-DEAD` or `TREE-ALIVE`. Liveness excludes zombies (a helper
  bug found while testing; a zombie answers `kill -0`). `run-arb-one.sh` enforces the cap at **1× the session cap**
  (not 2×: 11 × 2 × $0.28 = $6.16 would exceed the $3 ceiling), enforces the byte meter, polls every 5 s, and records
  post-kill spend. `run-scorer.sh` uses the tree-kill as well.
- **Zero-cost tests.** Tree self-test: a 9-process tree that ignores TERM is `TREE-DEAD`. End-to-end: a stand-in
  that writes $0.50 and ignores TERM is killed at the cap, reported `TREE-DEAD (6 processes)`, leaves no survivor, and
  its spend is flat 30 s after the kill ($0.50 → $0.50).

### 2. Re-triangulation: per run

| Run | Bench | Official readings (glm / second family) | Official mean | Arbiter advisory | Status |
|---|---|---|---|---|---|
| 25bb1943 | HOD | 10 / 7 | 8.50 | **8.0** (triangulated 8.33) | complete reading; the cap fired after it was written ($0.41) |
| 3e4f5975 | HO2 | 10 / 13 | 11.50 | — | cap kill at $0.35, before the write |
| 4e51c768 | HO2 | 10 / 13 | 11.50 | — | cap kill at $0.28 (final $0.30), before the write |
| 156fefe3 | HO2 | 9 / 6 | 7.50 | — | first attempt lost to a fixture fault (my repair); not re-run |
| 244b32c6 | HO2 | 9 / 13 | 11.00 | — | attempt lost to a fault in my own edit to the launcher; not re-run |
| 7834e2c5, 7b65a7e6, 91c5fca4, b707bcb2, c08a2116, cc8251fb | HOD / HO2 | see scores-readings | — | — | not attempted (ceiling and the cap) |

Why only one reading. On this prompt a full arbiter session costs $0.30–0.47, and the reading is written at the end of the
session, after most of that cost. At the spec's $0.28 cap, 0 of 4 full sessions produced a reading. The remaining budget
buys about four more attempts, and each would be killed the same way. So I stopped. `arbiter_impact.py` gives the
verdict answer without further spend.

### 3. Verdict impact (the held-out verdict is "no seat moves")

- **Official verdicts: unchanged.** The advisory readings do not enter the official scores. Gates FAIL (HO2 and HOD),
  P1, P2, P5 read CONFIRM-TIE, and P3, P4, P7 remain owner slots.
- **The one real reading changes no verdict.** Triangulating 25bb1943 gives 8.33 instead of 8.50, and recomputing
  every gate and pair with that value leaves every verdict as it was.
- **The bound does not support the expectation that no reading could change a verdict.** An exhaustive check over
  all 2^11 combinations of extreme readings (each divergent run at reading 0 or at its maximum) shows that a
  triangulated reading *could* change HO2 Gate 1 (the opus arm would fall below 11) and HO2 Gate 2, HOD Gate 1 and
  Gate 2, and the classification of P1, P2 and P5. The gates are the sensitive part: a gate flip would make a bench
  eligible for seat decisions. Readings near the official means do not flip anything. Only the 10 readings still missing
  could.

### 4. Realized spend and diff

- **Arbiter spend: $1.53** against the $3 ceiling: $1.42 in the per-arm DBs (the four attempts with DBs: $0.47, $0.35,
  $0.30, $0.30) plus $0.11 for the first `156fefe3` attempt, whose arm was removed in the fixture repair.
- **Diff.** New: `holdout-scoring/kill-tree.sh`, `run-arb-one.sh`, `run-arb-all.sh`, `arbiter_impact.py`, and `arb1/`
  (per-run attempts and the zero-cost test evidence). Changed: `run-scorer.sh` (tree-kill replaces the TERM-to-children
  sequence). Unchanged: the holdout arms (`run-eval-v6.sh` `kill_arm` still kills direct children only; the arms' spend
  stayed within its caps, so this is a follow-up, not an incident).
- **Tooling lapses (recorded).** I wrote one scratch file to `/tmp` during the helper test (removed; the scratch rule).
  My own edit to the launcher while a run was in progress broke one attempt (244b32c6).

### 5. Owner decision needed

Choose one: (a) accept the record as it stands (1 advisory reading of 11; official unchanged); (b) raise the arbiter
per-session cap to about $0.50 and the ceiling to about $5.50 to complete the other 10 readings (estimated $3.5–4.5 more);
or (c) drop the arbiter from this campaign. The official result does not depend on the choice. The gate sensitivity
in §3 is the reason to choose (b) if the gates are to be re-examined.

## Final arbiter triangulation (owner decision: option b, 2026-11-21)

Supersedes the previous arbiter section where they differ. Arbiter: gemini-4-neon, advisory. Session cap raised to
$0.50 (ceiling $5.50) by owner decision. The two-family means stay official; the triangulated values below are
hypothetical and are not applied.

### 1. The 11 divergent runs

| Run | Bench | Arm | Official (two families) | Official mean | Arbiter (advisory) | Triangulated mean (r1+r2+arb)/3 |
|---|---|---|---|---|---|---|
| 156fefe3 | HO2 | minimax-xhigh | 9 / 6 | 7.50 | 12 | 9.00 |
| 244b32c6 | HO2 | opus | 9 / 13 | 11.00 | 13 | 11.67 |
| 3e4f5975 | HO2 | opus | 10 / 13 | 11.50 | 13 | 12.00 |
| 4e51c768 | HO2 | haiku-default | 10 / 13 | 11.50 | 13 | 12.00 |
| 7b65a7e6 | HO2 | haiku-default | 7 / 9 | 8.00 | 9 | 8.33 |
| 91c5fca4 | HO2 | haiku-default | 9 / 12 | 10.50 | 12 | 11.00 |
| b707bcb2 | HO2 | haiku-high | 7 / 10 | 8.50 | **unavailable** (ceiling) | 8.50 (official kept) |
| 25bb1943 | HOD | haiku-medium | 10 / 7 | 8.50 | 8 | 8.33 |
| 7834e2c5 | HOD | haiku-medium | 10 / 7 | 8.50 | 8 | 8.33 |
| c08a2116 | HOD | haiku-medium | 11 / 8 | 9.50 | **unavailable** (ceiling) | 9.50 (official kept) |
| cc8251fb | HOD | 1017-high | 10 / 8 | 9.00 | **unavailable** (ceiling) | 9.00 (official kept) |

Eight readings are in. Each is complete (13 items for HO2, 16 for HOD). Three were written before the cost kill
landed (at $0.50–0.55 against the $0.50 cap); the files are whole, so the readings count. The three unavailable runs
were not attempted: the total had reached $5.28, and a $0.50 session would breach the $5.50 ceiling. They are not DNFs.

**Pattern.** On the HO2 runs the arbiter reads above the official mean in all six readings (+1 to +4.5). On the HOD
runs it reads 0.5 below in both. That is a family-level offset in the HO2 scoring, and it raises the haiku-default arm.

### 2. Gates and pairs, official vs triangulated

Arm means, official → triangulated (eight readings in; the three unavailable runs at official):
HO2 opus 11.25 → 11.83; HO2 haiku-default 9.00 → 9.33; HO2 minimax-xhigh 8.63 → 9.00; HO2 haiku-high 7.75 → 7.75;
HO2 dsflash 7.50 → 7.50; HO2 glm-high 6.88 → 6.88; HOD haiku-medium 9.13 → 9.04; HOD 1017-high 7.38 → 7.38.

| Gate / pair | Official | Triangulated | Changed? |
|---|---|---|---|
| HO2 Gate 1 (best ≤ 11) | FAIL (opus 11.25; now 11.83) | FAIL | no |
| HO2 Gate 2 (max gap ≥ max(3, 2·sd_anchor)) | FAIL | FAIL | no |
| HOD Gate 1 (best ≤ 8.8) | FAIL (haiku-medium 9.13) | FAIL (9.04) | no |
| HOD Gate 2 | FAIL | FAIL | no |
| P1 haiku-default vs glm-high | CONFIRM-TIE | CONFIRM-TIE | no |
| P2 minimax-xhigh vs haiku-high | CONFIRM-TIE | CONFIRM-TIE | no |
| P3 opus vs haiku-high | owner slot | owner slot | — |
| P4 dsflash vs haiku-default | owner slot | owner slot | — |
| P5 haiku-medium vs 1017-high | CONFIRM-TIE | CONFIRM-TIE | no |
| P7 haiku-high vs minimax-xhigh | owner slot | owner slot | — |

**Arithmetic for the sensitive cells.** HO2 Gate 1 would pass only if opus fell to 11 or below; the opus runs are now
at 11.67 and 12.00 (both arbiter-raised), so the arm sits at 11.83. HOD Gate 1 would pass only if haiku-medium fell to 8.8 or below; it sits at 9.04.

### 3. The flip statement

**With the eight real readings, no gate and no pair verdict flips.** Nothing in the table moves.

**Not established for the three unavailable runs.** Holding the other two at their official values, a single unknown reading flips a verdict only at these extremes:

| Unavailable run | Flips | Reading that flips it |
|---|---|---|
| b707bcb2 (HO2 haiku-high) | HO2 Gate 2 | at or below 0.5 |
| c08a2116 (HOD haiku-medium) | HOD Gate 1 | at or below 6.5 |
| cc8251fb (HOD 1017-high) | P5 | at or below 0.5 |
| cc8251fb (HOD 1017-high) | HOD Gate 2 | at or below 1.0 |

A joint sweep over all three unknown readings (2,160 combinations across their full valid ranges) gives the same four
flips and no others. The eight readings in hand all came in at 8–13, so none of these extremes is plausible on the
evidence we have. But they are not ruled out, because the three runs are missing. They are the only possible source of
a flip. If one does occur, the finding goes to the fixture rebuild, which computes its gates on fresh runs anyway. Nothing
is moved on the strength of it.

### 4. Realized arbiter spend and diff

- **Total: $5.28** against the $5.50 ceiling: the first pass $1.42 (four readings' sessions), the re-triangulation
  $3.50 (seven sessions), an orphan session $0.25 (started when I stopped the driver with `pkill`; killed, cost counted),
  and the first `156fefe3` attempt $0.11 (arm removed in the fixture repair; run record).
- **Diff, this phase.**
  - `kill-tree.sh` (new in the harness; copy in scoring) and `run-eval-v6.sh` `kill_arm`: now kills the whole descendant
    tree (TERM, KILL, verify), not the direct children only. Tested zero-cost: a TERM-ignoring tree is killed with no
    survivors. This closes the follow-up for the arms.
  - `run-arb-one.sh`: `ARB_TAG` and `OC_BIN` overrides added; the fixture is rebuilt if incomplete.
  - `run-arb-rest.sh` (new): cap $0.50, ceiling $5.50, one re-run per DNF, then unavailable.
  - `arbiter_final.py` (new): the triangulated recomputation and the flip sweep. `arbiter_impact.py` (earlier): the extremes bound, superseded.
  - `zero-cost tests`: the kill-tree self-test, the end-to-end stand-in (killed at cap, tree dead, no drift), and the
    stand-in for `kill_arm` (zero survivors).
- **Lapses, recorded.** I stopped the first driver with `pkill` on its bash process, which left the session orphaned and
  spending ($0.25). A bench argument was passed in the wrong position in the first attempt of the new driver; it was caught
  before the loop continued. That session is the orphan above: it was stopped, and its cost is counted. I also wrote one
  scratch file under `/tmp` earlier (removed). The helper reported `TREE-ALIVE` for a process that exited after a short delay; that was the correct fail-closed answer, and the process was then killed with SIGKILL.

### 5. Owner decision

No seat moves. There is no gate flip with the real readings, so there is nothing to record against the fixture beyond the
three unknown-reading thresholds above. Nothing is moved on their account.

## Completion of the repair (owner 2026-11-21, uncapped; FINAL)

**Status: P1-P5 done. The repair gates on the v3 readings are final: both benches are INVALID (Gate 2 fails); no seat
moves. The dry-sim Gate-1 prediction held in direction, not in magnitude (see section 4).**

Construct-level only. No key value, probe output or defect identity is reproduced here (SPEC section 5.2, 8.5).

### 1. Repair campaign (SP2/US2): the v3 readings

- Campaign `holdout-mandatory-2026-11-21-v3`: 18 jobs, EVAL_ARM_CAP=5.00/arm, EVAL_TIMEOUT_SECS=3600.
- **Budget deviation.** The campaign status file records `budget_usd=30.00`. The pre-registered hard cap is
  **$10.00** (HOLDOUT-SPEC §14.3, admission `spend + 2×cap ≤ 10`). The run used the $30.00 value, so this is a deviation
  from §14.3, not a pass. Actual spend was **$2.88** (status file `spent`; $2.67 provider-recorded), under the $10.00 cap.
- **17 complete runs, 1 DNF** (minimax HO2 a3, no report after its rerun). The v2 campaign's readings were lost (section 2
  of the prior revision of this section, kept in git history); v3 is the only repair reading set.
- Blinded set `evals-keys/holdout-campaigns/blinded-v3/` (17 runs, leak lint 0 hits) and sealed map
  `sealed/blind-map-v3.tsv`; the map was unsealed only after `scores-runs-v3.tsv` was written.

### 2. Panel (two families, the campaign-2 pairing table)

Six batches (bench x scorer), every run scored by exactly two families (8 claude runs got glm+minimax, 5 got glm+haiku,
4 glm runs got minimax+haiku). 34 readings, 0 missing, 0 divergent (>= 2.0) runs, 0 flags. Scorers ran the operator
probe battery (`cross/ho2-probes-v3.tsv`, 3 rounds, 0 unstable items) for the deterministic items.

Harness fixes that made this possible (campaign-2 evidence untouched; checked by sha256 manifest):
- `blind.py --campaign v3` (blinded-v3/, sealed/blind-map-v3.tsv; selects the 17 runs with a final report). Campaign-2 path unchanged.
- `build-batch.py --campaign v3` writes `batches/v3/` and never rmtree-s an existing dir; campaign-2 `batches/` untouched.
- `score.py --campaign v3`, `report.py --campaign v3` write suffixed outputs (`scores-*-v3.tsv`, `arms-v3.tsv`, `pairs-v3.tsv`, `gates-v3.tsv`).
- `run-scorer.sh` honours `SCORER_CAMPAIGN` (batch subtree, session title) and `SCORER_ATTEMPT`.
- `build-batch.py` now copies `prompts/PROMPT-<bench>.md` for v3. The campaign-2 fixtures carry the frozen-v1 prompt
  (it differs from `prompts/PROMPT-*.md`); v3 must not use it. (The first v3 HOD session attempts ran on a fixture without PROMPT.md and were refused; the HO2 sessions were not affected. See the refused-session bullet below.)
- Three v3 HOD sessions were refused on the first try: the arm dirs existed from the first failed attempt (a missing
  PROMPT.md, which the fix above resolves). They were rerun with `SCORER_ATTEMPT=r2`; the failed attempts stay in `panel-log.tsv`.

### 3. Per-arm scores (v3, two-family means; n = runs)

| Arm | n | mean | sd | run scores |
|---|---|---|---|---|
| HO2 minimax-xhigh | 3 | 8.67 | 0.29 | 8.5, 8.5, 9.0 |
| HO2 haiku-default (anchor) | 4 | 6.75 | 1.71 | 5, 6, 7, 9 |
| HO2 glm-high | 4 | 6.00 | 0.00 | 6, 6, 6, 6 |
| HOD 1017-high | 2 | 8.75 | 0.71 | 8.25, 9.25 |
| HOD haiku-medium (anchor) | 4 | 8.38 | 0.63 | 7.5, 8.5, 8.5, 9 |

Not run in v3: HO2 opus, HO2 haiku-high, HOD opus (these arms are absent from the 17-run block, so P3, P7 and P6/P9 cannot run).
P2 needs minimax vs haiku-high and cannot run. P1 and P5 are reported below.

### 4. FINAL repair gates (HOLDOUT-SPEC section 7.4 Step 1, computed by `report.py --campaign v3`, `gates-v3.tsv`)

| Bench | Gate 1 (best arm) | Floor (anchor) | Gate 2 (largest pair gap vs threshold) | Verdict |
|---|---|---|---|---|
| HO2 | **PASS**: 8.67 <= 11 (minimax-xhigh) | PASS: 6.75 > 3 | **FAIL**: 0.75 (P1) < 3.42 | **INVALID, no seat decision** |
| HOD | **PASS**: 8.75 <= 8.8 (1017-high; margin 0.05) | PASS: 8.38 > 2.5 | **FAIL**: 0.38 (P5) < 3.00 | **INVALID, no seat decision** |

**Flip statement: NO flip.** Both benches fail the Gate-2 screen. A Gate-2 failure "only stops the rung claim, and all pairs
below -> no signal" (SPEC section 7.4 Step 1). No pair is confirmed or refuted by a seat-moving verdict.

**Dry-sim prediction vs. result.** The pre-registered dry sim (SPEC section 14.4) predicted HO2 Gate 1 PASS with the best
repair arm at 7.00 (haiku-default), versus 11 as the limit. Real result: Gate 1 PASS, but the best arm is minimax-xhigh
at 8.67, and the anchor is 6.75 (prediction 7.00). The prediction's Gate-1 call held; its magnitude for the top arm did not
(the dry sim predicted minimax-xhigh 6.38; the real mean is 8.67). The honest reading is that the bench
now sits BELOW the ceiling for the strongest arm, and Gate 2 still fails for the pre-registered pairs. HOD Gate 1 passes only by
0.05 (8.75 vs 8.8): on a 2-run arm, that margin is inside the noise and must not be read as a clean pass.

**Consequence.** SP2/US2 are not valid seat instruments. The repair does not restore a seat decision; it removes the
ceiling problem on HO2. The pre-registered pairs still do not separate (P1 and P5 sit at 0.4-0.75 pts, under the 3-pt
screen). Correction: the c item does separate the HO2 arms (minimax-xhigh 3/3, haiku-default 2/4, glm-high 0/4 runs at
c_fix=2); see §6 and §8. A next fixture must add arms that spread.

### 5. Pair verdicts (report.py, computed)

| Pair | Delta (holder - challenger) | Band | Verdict |
|---|---|---|---|
| P1 HO2 haiku-default vs glm-high | +0.750 | 5.024 | CONFIRM-TIE (ratified price rule; lineage check) |
| P5 HOD haiku-medium vs 1017-high | -0.375 | 2.267 | TIE (challenger ahead inside noise) |
| P2, P3, P4, P7 | - | - | NOT RUN (arms absent from v3) |
| P6, P8, P9 | - | - | NOT RUN (phase 2) |

Band values come from `report.py`, using the frozen prior and C(n) (n=4 anchor, sd 1.71 HO2 / 0.63 HOD). Only P1 and P5 have
both arms present. These are reported for transparency; the bench is INVALID, so neither is a seat decision.

### 6. Operator probes and scorer cross-check (what the deterministic items rest on)

- The probe battery is run by `holdout-scoring/run-ho2-probes.py --campaign v3` on scratch copies of the blinded runs
  (3 rounds, 0 unstable). Pristine constants re-measured this session: NARROW 6295, WIDE 31864 attempts, PLAN-CANON hashes
  reproduce (`probe-c.py` on the pristine tree; exit 0).
- **Correction to the earlier claim ("c_fix is 0 for all 17 runs / no signal").** That claim is false. Verified with
  `score.ho2_det` on `cross/ho2-probes-v3.tsv` (11 HO2 runs):
  - **c_fix = 2 on 5 of 11 HO2 runs:** 15fde426, 4aafaf9b, 845667e9, 64881d00, 96e864d3. Each is inside both attempt
    bounds (≤ 8/job) and matches both PLAN-CANON hashes.
  - **c_fix = 0 on the other 6, for two different reasons:**
    - Fails the wide-attempt bound: 0daf3130 (wide 31744/1000; it also fails PLAN-CANON) and 10c7bf2d (wide 31864/1000,
      PLAN-CANON passes).
    - Fails PLAN-CANON (the attempt count is in bound, the placements changed): 149f0d7f, 2d8aff97, 918a4195, c383bff1.
  - **Arm impact:** minimax-xhigh 3/3 runs at c_fix=2; haiku-default 2/4; glm-high 0/4. The c item is the driver of the
    arm separation (glm-high is also the arm at 6.00 with all four runs at 6). The c_fix value is recorded, not re-graded.
- The four glm-high runs (0daf3130, 2d8aff97, 918a4195, c383bff1) all score 6/6 with c_fix 0. This is the rubric applied as
  written (PLAN-CANON or the wide bound fails), not a scorer collapse.

### 7. COMPLETION COST LEDGER (USD, the owner's headline)

| Component | Cost | Source |
|---|---|---|
| v3 repair campaign, 18 jobs incl. 2 DNF reruns (recorded) | $2.6743 | `holdout-campaigns/holdout-2026-11-21-v3.status.txt` (final line) |
| v3 campaign, misc estimate (ai-gateway-misc, token x catalog price) | $0.2057 (estimated) | same |
| **v3 campaign total (as the owner records it)** | **$2.8800** | |
| P3 arbiter re-runs, 3 sessions (cap $1.50 each) | $1.6815 | `arb1/<id>-p3/RUN.txt` |
| Earlier arbiter spend (11 divergent campaign-2 runs) | $5.2800 | prior section |
| **Arbiter total** | **$6.9615** | |
| v3 scoring, 6 panel sessions + 3 failed-start (missing-PROMPT) sessions | $0.2174 DB; $0.3906-$0.4339 with misc estimate | `holdout-scoring/spend-all-sessions.tsv` (computed by `spend.py` logic) |
| **TOTAL COMPLETION (repair v3 + arbiter + v3 scoring, owner basis)** | **$2.8800 + $6.9615 + $0.2174 = $10.0589** (about $10.06; $10.28 with the misc estimate for the scorers) | |

Reconciliation caveat (measured, not resolved): the per-session sandbox DB sums ($0.99 for the 20 v3 arm sessions) do NOT
match the campaign status ($2.67 for the same sessions). For one minimax arm the sandbox DB shows $0.14 while the status
delta is about $0.97. The owner's recorded figure is the headline; the sandbox-DB sum is a lower bound and the gap is an open
accounting item. This section does not pick one silently.

The v3 repair itself was **$2.88**, so the completion (readings + arbiter + scoring) was roughly 3.5x the cost of the
readings alone. The arbiter was the largest single item ($6.96). The v3 scoring is the cheapest part (under $0.50).

### 8. Lesson for the next fixture budget (measured)

- Per attempt (the 20 status-file deltas, which include the 2 reruns): **median $0.044 on the spent basis** (the
  status-file `spent` deltas; they sum to $2.88), mean $0.144, max $0.97. On the provider-recorded basis (`recorded`
  deltas; they sum to $2.674) the median is **$0.033**, mean $0.134. The recorded median is lower because 3 of the 20
  recorded deltas are exactly $0.00 (the provider booked no cost on those attempts while `spent` shows $0.0423, $0.0622 and
  $0.0645 for them). **Plan on the spent basis: $0.044 per attempt.**
- **The real cost per COMPLETE reading is about $0.16** (v3 readings $2.88 / 17 complete runs = $0.169), and **about $0.59
  per COMPLETE RUN when the arbiter and scoring are added** ($10.06 / 17 = $0.59). The per-attempt median understates
  this: a complete reading needs roughly 1-4 attempts plus the DNF/reruns, and the mean is pulled up by the few expensive
  attempts (minimax, GLM long runs).
- An arbiter reading costs $0.50-0.63 at its session cap. An arbiter on EVERY divergent run is the largest line of the
  whole budget, and it bought no verdict change in this campaign (section 3 of the arbiter table: no flip).
- The c item drives the HO2 arm separation (see §6): c_fix 2 on 5 of 11 HO2 runs: 3 minimax-xhigh (of 3) and
  2 haiku-default (of 4). A fixture that wants the arms to spread needs this item, and it must be read with its two bounds.
- Budget rule for the next fixture: **budget about $0.6 per complete run for the arm and scoring, not $0.04**, and do not
  buy an arbiter on a fixture whose gates already fail before scoring. Keep a cap of ~$15 for a 18-run block including
  reruns.

### 9. Closure

- Repair gates: **both benches INVALID** (Gate 2 fails); no seat moves; no flip. The HOD Gate-1 pass is a 0.05 margin on
  two runs and is not a clean pass.
- P1-P5 done as far as the v3 arms allow: P1 and P5 computed (ties); P2, P3, P4, P7 not runnable (arms absent); P6, P8, P9
  phase 2.
- Open items: the sandbox-DB vs status reconciliation ($0.99 vs $2.67); the arbiter's "no flip" finding on every divergent run.
- Push: NOT done (owner-only). The kit and evals-keys are committed locally.

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

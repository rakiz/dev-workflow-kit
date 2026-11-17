# bench-v3 pilot round 1 — I-v2 (RG2) + D (D1), gates frozen §5.3, owner rulings recorded

**VERDICT: NO-GO → rework + re-pilot (§5.6, round 2 of 2).** Date: 2026-11-12.
**ROUND 2 EXECUTED SAME DAY — VERDICT BELOW: NO-GO again → both tasks REDESIGNED (2 pilot rounds spent, §5.6).**

## Methodology

- 4 models × 2 tasks, 1 run each (§5.1): opus-5.5 default, sonnet-5.5 high,
  terra medium, glm-5p3-flash high (I-v2) / low (D). Fixture copied fresh per
  arm (`evals/run-eval-v3.sh`: 15-min watchdog, cost-cap poller, tier caps).
- Session titles `eval-2026-11-12-<IV2|D>-<RG2|D1>-<model>-<effort>[-r2]`;
  costs from the opencode DB (`raw/sessions.tsv` — retired with the raw
  tree; the campaign cost rows live on in `evals/2026-11-16/grid2-costs.tsv`).
- Scoring: frozen private rubrics `RUBRIC-IV2.md` / `RUBRIC-D1.md` v0 (sha256
  in `BENCH-V3-DESIGN.md` §3.6/§4.4); first-pass scorers executed every
  pre-registered probe on scratch copies; reference-fixed copy + §3.8 record
  re-validated by the scorer before scoring.
- Deviation note: the sonnet D arm DNF'd (15.1 min, no deliverable; its
  background benchmark orphan was reaped) — per the owner DNF ruling it was
  re-run ONCE (title suffix `-r2`); the DNF counts toward budget, not scores.

## I-v2 results (all four arms 6/10)

| Arm | Suite green | Defects fixed (a/b/c/d) | Tests written | Ambiguity | Red bonus | FP | **TOTAL /10** | Changed files | Cost |
|---|---|---|---|---|---|---|---|---|---|
| opus-5.5 default | 2 | 2 (a=1, b=1, c=0, d=0) | 2 | 0 | 0 | 0 | **6** | 4 | $0.4373 |
| sonnet-5.5 high | 2 | 2 (a=1, b=1, c=0, d=0) | 2 | 0 | 0 | 0 | **6** | 4 | $0.2472 |
| terra medium | 2 | 2 (a=1, b=1, c=0, d=0) | 2 | 0 | 0 | 0 | **6** | 4 | $0.1110 |
| glm-5p3-flash high | 2 | 2 (a=1, b=1, c=0, d=0) | 2 | 0 | 0 | 0 | **6** | 4 | $0.0224 |

- **Uniform 4-way tie.** Every model fixed (a) rules-change invalidation and
  (b) cold/warm row-count divergence with passing regression tests that fail
  on the pristine prototype; every model missed (c) warm-run re-parses the
  oversized input and left the partial-failure path of (d) untouched
  (exit 0, partial report).
- Every model fixed the pre-existing failing test unasked (neutral per
  rubric) — and none quoted executed evidence in the final report → red
  bonus 0 across the board.
- **Zero FPs anywhere** — first editing-task data point for the narrowed
  §3.5 FP scope: no failed-fix was punished; no invented defect.
- The fix-shape ambiguity (d) was re-read by opus/sonnet as covering only
  unexpected exceptions ("a transform failure" = crash), keeping
  TransformError skip; glm/terra kept skip silently. **Neither reading passes
  probe (d)**: the probe injects a TransformError-class failure that emits a
  partial report with exit 0.

## D results

| Arm | Part A /8 | Part B /3 | FP | Questionnaire | **TOTAL /11** | Cost |
|---|---|---|---|---|---|---|
| sonnet-5.5 high (r2) | 8 | 0 | 0 | 1 | **8** | $0.7734 |
| terra medium | 8 | 0 | 0 | 1 | **8** | $0.0912 |
| opus-5.5 default | 7.5 | 0 | −3 (rule (c)) | 1 | **4.5** | $0.5000 |
| glm-5p3-flash low | 6.5 | 0 | −3 (rule (a)) | 1 | **3.5** | $0.0107 |

- **Part B (executed-proof bonus): 0/3 for ALL arms** — designs cite
  measurements and test runs but quote no command + observed output. Same
  zero-proofs shape as DR-v2 (2026-11-01). **Gate 3(b) fallback is therefore
  LIVE for D.**
- FP calls: opus claimed float mtimes "flap across JSON round-trips" (false
  Python semantics, rule (c)); glm-low claimed `scan_files` excludes
  dot-files (it excludes dot-directories only; verified by probe, rule (a)).
- **Code-groundedness: the anti-terra axis worked** — both strong models
  grounded every category in the fixture; glm lost points exactly where
  grounding/mechanism were incomplete.

## Owner rulings (2026-11-12, delegated adjudication — recorded here per §5.2)

1. IV2 sonnet/opus "partial cache on mid-run crash" claims: NOT FPs — they
   name a concrete mechanism (per-file save_state) beyond restating the GOAL
   invariant; rules (a)–(d) target false claims, and these are true of the
   fixture.
2. IV2 tests_written point 2: "candidate's tests" = the defect-specific
   regression tests the candidate cites per fixed category (all four verified
   to fail on the pristine prototype) — whole-file runs may mix feature tests.
3. IV2 red bonus: stays 0 — "executed evidence" requires the command +
   observed output quoted in the final report; an unquoted in-session run
   does not count.
4. IV2 (d) "third policy" (skip TransformError, abort on unexpected
   exceptions): moot this round (probe (d) failed everywhere); rubric
   amendment for round 2 — §3.7 "consistent" must admit a coherently-stated
   third policy if its probe passes.
5. D Part B: paraphrased outputs ("6 tests, OK") score 0 — the rubric
   requires the command and its observed output in the design document.
   Confirmed.
6. D questionnaire Q2: questions the design itself should have settled count
   as asks (Q2 = 0). Confirmed.
7. D opus A1 grounding (no line citation, named override rows): counts
   (grounding forms G2/G3 accept named reuse + stated override). A7 bound
   derivable from the stated policy: counts.
8. D A8 torn-index recovery gaps (glm, opus): 0.5 each (HC-3); D glm A5/A7
   half-credits: confirmed.

## Gates (frozen §5.3 + completion block; reachable maxima I-v2 10, D 8; D gate basis = Part A after implementability penalty − FPs)

- **Gate 1 anti-saturation:** I-v2 PASS (6 ≤ 8). D **FAIL** — best Part A
  8 > 6 (sonnet, terra sweep).
- **Gate 2 competitor pairs:** strong pair sonnet vs terra — I-v2 gap 0,
  D gap 0 (8 = 8) → **FAIL on both benches** (required ≥ max(3, 2×variance);
  floor 3). Cheap pair glm vs deepseek-flash: not yet evaluated (deepseek
  cell comes from fleet stage 1; moot given the strong-pair failure).
- **Gate 3 discriminators:** (a) FIRED — code-only-detectable defects (d)
  missed by all 4 (I-v2); (c) warm-op count missed by all 4. D
  grounding-failures observed (glm A5/A7/A8). (b) NOT fired — the proof
  bonus was earned by 0 arms on BOTH benches → the pre-registered fallback
  applies BEFORE any fleet run (I-v2: fold the red-baseline into expectations
  per §3.4; D: mandated-probe fold-in per §4.3).
- **DNF/gates:** 7/8 arms completed + 1 re-run → ≥4 completed per task,
  no-signal rule not triggered.
- **Variance data:** §5.4 best/worst re-runs were NOT executed — the pilot is
  a 4-way tie on I-v2 and the D gaps are FP/half-credit-driven; with pair
  gaps of 0 vs a 3-point floor, re-run variance cannot change any gate
  outcome. The owner approved skipping them and moving to rework (recorded
  here as the deviation from the frozen sequence).

## Verdict + rework decisions (round 2 of 2, §5.6)

- **I-v2:** reseed for findability WITHOUT leaking — (c) must be observable
  by running (cache-vs-fresh visible signal on the shipped oversized input);
  (d) the GOAL invariant phrasing must not be confusable with crash-only
  scope; red-baseline fold-in per gate 3(b) fallback (mandated "record the
  baseline suite result" step, scored as a category point, max stays 10 —
  expectation re-fold, not re-threshold).
- **D:** sharpen the brief for the saturated axis — grounding bar raised
  (citations checked against fixture; named override without location
  insufficient at threshold), bound statements must be explicit (A7),
  recovery semantics (A8) named as required; brief keeps entailing all 8
  categories without naming them.
- **Re-pilot:** same 4 models per task, fresh scoring under the amended
  rubrics (amendments recorded in the private keys repo BEFORE any round-2
  arm runs; hashes re-recorded in `BENCH-V3-DESIGN.md`). Budget: re-pilot
  line of the §5.8 ledger (≤$6 worst case); round-1 spend **$2.59** (incl.
  the $0.395 DNF).

## Raw

`raw/` — per-arm run dirs (candidate work trees, pristine test file NOT yet
overlaid), `sessions.tsv` (titles + costs from the DB). RETIRED 2026-11-17
(superseded, git history only): the scoreable round-2 run dirs
(`raw-round2/*-p3/p4`) were extracted into `evals/2026-11-16/runs/` and
archived as `runs.tar.gz`.

---

# Round 2 (2026-11-12, same day) — re-pilot on the reworked fixtures, rubrics v1

## Round-2 rework (committed BEFORE any arm ran)

- Private keys repo commit `3bc5a6c`: RUBRIC-IV2 v1 (baseline_recorded
  0/1 replaces the red-baseline bonus — gate-3(b) fold-in, max stays 10;
  (c) reseed note; (d) invariant rewording note; third-policy clause per
  round-1 ruling #4), RUBRIC-D1 v1 (verified grounding at threshold —
  named override without location insufficient; A7 bounds must be
  explicit; A8 torn-index recovery required, absence caps at 0.5).
  Hashes re-recorded in BENCH-V3-DESIGN.md §3.6/§4.4
  (IV2 `a09024f5…`, D1 `b9d5090d…`).
- Public repo commit `0314a36`: RG2 GOAL.md (mandated baseline-recording
  step for both suites; invariant scope clarified), reportgen.py per-input
  stdout work line (cache-vs-fresh observable by running on the oversized
  input), D1 BRIEF.md hardened (verified grounding / explicit bounds /
  torn-index recovery), new tree hashes (RG2 `d32d51e4…`, D1 `59109cb1…`).
- §3.8 re-verification: all 4 probes ×3 consecutive rounds, BOTH
  directions, fresh scratch copies — identical to the round-1 record;
  probe (c) captures gained `| tail -n 1` (the new stdout lines); leakage
  check zero hits; suite-green OK 3/3 and legacy red 3/3 on both reworked
  trees. cheap-review pass over the rework: 2 doc-level leakage majors in
  a first draft of the design-doc notes (fixed pre-commit).

## Round-2 deviations (recorded per §5.2/§6.6)

1. **Provider switch mid-round (§6.6):** github-copilot went down for the
   claude models after the first two IV2 arms; on the owner's instruction
   the remaining claude arms ran on `ai-gateway-anthropic`
   (claude-opus-5-5, claude-sonnet-5-5 — same ids, same variants). glm
   (ai-gateway-misc) and terra (github-copilot, gpt arm unaffected) kept
   their round-1 providers. Round-1 cells remain copilot-served; cross-
   round COST comparisons for opus/sonnet are cross-provider — flagged,
   never gate inputs.
2. **DNF + one re-run:** the first D-sonnet arm was killed mid-run by the
   gateway outage ($0.1217, no deliverable; archived
   `D-sonnet-high-DNF-timeout`) and re-run ONCE (tag `p2r2`) per the DNF
   policy — DNF counts toward budget, not scores.
3. **§5.4 best/worst re-runs skipped** — same rationale as round 1: with
   first-pass pair gaps of 2 (I-v2) and 1 (D) vs the 3-point floor, no
   re-run outcome can flip any gate; recorded as a deviation for owner
   confirmation (round-1 precedent: owner-approved skip, 11-12).

## I-v2 round-2 results (max 10)

| Arm | Suite green | Defects fixed (a/b/c/d) | Tests written | Ambiguity | Baseline recorded | FP | **TOTAL /10** | Cost |
|---|---|---|---|---|---|---|---|---|
| opus-5.5 default | 2 | 3 (a=1, b=1, c=0, d=1) | 2 | 1 | 1 | 0 | **9** | $0.6726 |
| sonnet-5.5 high | 2 | 3 (a=1, b=1, c=0, d=1) | 2 | 1 | 1 | 0 | **9** | $0.3739 |
| glm-5p3-flash high | 2 | 3 (a=1, b=1, c=0, d=1) | 2 | 1 | 0 | 0 | **8** | $0.0359 |
| terra medium | 2 | 2 (a=1, b=1, c=0, d=0) | 2 | 0 | 1 | 0 | **7** | $0.1044 |

- **The rework worked on its two targeted axes:** (d) found and fixed
  3/4 (round 1: 0/4) — glm included, with the failure policy named and
  its cost stated; the mandated baseline step put executed evidence in
  3/4 reports (round 1: 0/4).
- **(c) missed by ALL FOUR again** — even with the stdout signal. Every
  build still parses before the cache check (`warm_opens=2` on the
  two-process probe). The reseed bought visibility of the *symptom*
  (candidates saw `parsed 12000 rows` on warm runs) but not of the
  *ordering defect*: the parse-before-check shape still reads as
  innocent code. (c) is the last code-only discriminator and it never
  fired for any model.
- glm baseline_recorded = 0: quoted the commands but paraphrased the
  output ("OK, 12 tests") — the exact paraphrase shape ruled 0 by
  round-1 ruling #5, applied identically per the v1 amendment.
- terra (d) = 0 and ambiguity = 0: its abort-and-destroy build DELETES
  the previous good report/cache at run start, so the probe (d)
  unchanged-hashes check fails (`STATE-OR-REPORT-CHANGED`, artifacts
  gone). Owner flag: a lenient third-policy reading (invariant holds —
  nothing partial is ever persisted) would score terra 9; the strict
  letter (v1: third policy admitted only if its probe passes) scores 7.
  Neither reading changes any gate.
- terra (b) = 1: the count unification is real (single source of truth
  = csv data rows, hit path re-validated) — its warm-path recompute is
  the pre-existing (c) defect, scored 0 there, not the (b) fix shape.

## D round-2 results (max 11; gate basis = Part A − implementability penalty − FP)

| Arm | Part A /8 | Part B /3 | FP | Questionnaire | **TOTAL /11** | Gate basis | Cost |
|---|---|---|---|---|---|---|---|
| sonnet-5.5 high (r2) | 8 | 3 | 0 | 1 (Q2) | **11** | 8 | $0.9106 |
| opus-5.5 default | 8 | 3 | 0 | 1 (Q2) | **11** | 8 | $1.5639 |
| glm-5p3-flash low | 8 | 1 | 0 | 0 → −1 Part A | **8** | 7 | $0.0113 |
| terra medium | 8 | 0 | 0 | 0 → −1 Part A | **7** | 7 | $0.0998 |

- **Part A swept 8/8 by ALL FOUR models** — including glm-low and
  terra-medium, the two known code-averse tiers. The v1 hardening
  (verified grounding, explicit bounds, torn-index recovery named in the
  brief) taught every tier to ground the taxonomy: zero categories
  failed for want of grounding. The authoring Part A cannot arbitrate a
  design rung — it is fully entailed, fully aced.
- **Part B: FIRST executed proofs-by-execution ever recorded on this
  kit's benches** (DR-v2 history included): sonnet and opus quoted
  command + observed output for all three probes (baseline suite, timed
  tree measurement, verified integration points), every claim scorer-
  reproduced. glm earned B2 (a timed probe with derivation). The §4.3
  mandated-probe fallback + the hardened brief did exactly what they
  were designed to do.
- Implementability questionnaire (different-lineage executor, strict
  pre-registered rule): glm and terra designs left new-function entry
  points unnamed (Q1 = 0) and asked human questions the design should
  have settled (Q2 = 0) → penalty −1 each. sonnet/opus designs named
  ~15/17-19 steps (Q1 = 0 on the strict every-step rule) and answered
  "nothing blocking" (Q2 = 1) → no penalty.

## Double-scoring (§5.2) — best and worst arms per task, second independent pass

- I-v2: opus 9 → 9 (delta 0); terra 7 → 7 (delta 0).
- D: sonnet 11 → 10 (delta 1 — B3: the design states verified behaviors
  in condensed prose, not verbatim transcripts; both readings
  owner-adjudicable, does not touch the gate basis); terra 8 → 8.
- Scorer variance for gate 2 thresholds: I-v2 = 0 → 3-point floor; D = 1
  → max(3, 2×1) = 3.

## Gates round 2 (frozen §5.3; reachable maxima I-v2 10, D 8)

- **Gate 1 anti-saturation:** I-v2 **FAIL** — best 9 > 8 (round 1: 6,
  pass). D **FAIL** — best gate basis 8 > 6 (unchanged).
- **Gate 2 competitor pairs (threshold: ≥ max(3, 2×variance) = 3):**
  sonnet vs terra — I-v2 gap 9−7 = 2 → **FAIL**; D gap 8−7 = 1 →
  **FAIL**. (On D TOTALS the gap is 11−7 = 4, but the frozen gate basis
  is Part A — the proof bonus is invisible to the frozen pair gate.)
- **Gate 3 discriminators:** I-v2 (a) FIRED — (c) missed 4/4, again;
  (b) FIRED — baseline_recorded earned 3/4. D (a) NOT FIRED — zero
  grounding failures (the axis went inert); (b) FIRED — proof bonus
  earned by 2 arms. (c) FP-bait report: **zero FP deductions taken by
  any arm on either bench** (round 2), with the full example-FP bait
  lists present in both rubrics — consistent with the 11-01 precedent
  that 0 FP is good model behavior; bait density left as-is for the
  redesign.
- DNF/no-signal: 8/8 arms completed (1 DNF re-run) — no-signal rule not
  triggered.

## Round-2 verdict

**NO-GO — and the 2-round pilot budget is spent (§5.6): both I-v2 and D
move to REDESIGN, not a third re-pilot.**

The qualitative picture flipped from round 1: round 1 failed on
*indiscrimination* (4-way tie, zero proofs, ungrounded designs passing);
round 2 fails on *saturation from above* — every round-1 defect of the
BENCH was fixed by the rework ((d) findable, proofs executed, grounding
universal, baseline recorded), and the strong models simply cleared the
new bar: 9/10 I-v2 and a Part-A sweep on D. What remains discriminating:
I-v2's (c) — missed by 8/8 arms across both rounds, the one seeded
defect whose innocent-code shape survives everything — and D's Part B
(3 vs 0/1), which the frozen Part-A gate basis cannot see.

Redesign inputs for the owner (from the two rounds of data):
1. I-v2: the (c) shape (parse-before-check) has now survived both a
   measurement-only probe (round 1) and a visible-signal reseed
   (round 2) — a third reseed is not justified; a redesign should either
   replace (c) with a measurement-forcing defect of a different shape,
   or accept a 3-defect bench with max 9 and re-frozen thresholds.
2. D: Part A (authored-taxonomy recognition) is saturated at every
   tier — the discriminating construct is executed proof (Part B, 3 vs
   0/1 split). A redesign should promote proof-execution into the gate
   basis (e.g. gate on A + B), or re-seed Part A with categories the
   brief does not entail so visibly.
3. Frozen-gate caveat: thresholds (≤80 %, pair gap ≥3) were set when the
   reachable maxima were estimates; if the redesign keeps the round-2
   construct with a re-folded max, the re-freeze is an owner decision,
   documented before any new pilot.

## Owner-adjudication items open at close (§5.2 — none affects a gate)

1. D-sonnet B3: condensed procedure + observed output vs verbatim
   transcript → total 11 (first pass) vs 10 (second pass).
2. IV2-terra (d)/ambiguity third-policy reading → total 7 (strict,
  applied) vs 9 (lenient).
3. IV2-glm baseline_recorded: quoted command + paraphrased output → 0
   applied (ruling #5 standard); flagged for confirmation of the
   cross-rubric application.

## Round-2 raw + costs

`raw-round2/` — per-arm run dirs (9 incl. the DNF; candidate work trees),
`sessions.tsv` round-2 block below. Arms $3.894 (incl. $0.122 DNF),
scorers + questionnaires $0.199, round-1 spend $2.59 — campaign ≈ $6.7
against the approved ~$18 ceiling.

| Session title | Cost |
|---|---|
| eval-2026-11-12-IV2-RG2-ai-gateway-misc-fw-glm-5-3-flash-high-p2 | 0.0359 |
| eval-2026-11-12-IV2-RG2-github-copilot-gpt-6-1-terra-medium-p2 | 0.1044 |
| eval-2026-11-12-IV2-RG2-github-copilot-claude-sonnet-5-5-high-p2 (gateway-fail ×2, $0) | 0.0 |
| eval-2026-11-12-IV2-RG2-ai-gateway-anthropic-claude-sonnet-5-5-high-p2 | 0.3739 |
| eval-2026-11-12-IV2-RG2-ai-gateway-anthropic-claude-opus-5-5-p2 | 0.6726 |
| eval-2026-11-12-D-D1-ai-gateway-misc-fw-glm-5-3-flash-low-p2 | 0.0113 |
| eval-2026-11-12-D-D1-github-copilot-gpt-6-1-terra-medium-p2 | 0.0998 |
| eval-2026-11-12-D-D1-ai-gateway-anthropic-claude-sonnet-5-5-high-p2 (DNF) | 0.1217 |
| eval-2026-11-12-D-D1-ai-gateway-anthropic-claude-sonnet-5-5-high-p2r2 | 0.9106 |
| eval-2026-11-12-D-D1-ai-gateway-anthropic-claude-opus-5-5-p2 | 1.5639 |

---

Bench v3 status: rounds 1+2 NO-GO (round 2: saturation from above on both benches); per §5.6 both tasks are REDESIGNED, not re-rolled. Redesign inputs recorded above.

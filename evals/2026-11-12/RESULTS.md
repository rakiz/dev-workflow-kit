# bench-v3 pilot round 1 — I-v2 (RG2) + D (D1), gates frozen §5.3, owner rulings recorded

**VERDICT: NO-GO → rework + re-pilot (§5.6, round 2 of 2).** Date: 2026-11-12.

## Methodology

- 4 models × 2 tasks, 1 run each (§5.1): opus-5.5 default, sonnet-5.5 high,
  terra medium, glm-5p3-flash high (I-v2) / low (D). Fixture copied fresh per
  arm (`evals/run-eval-v3.sh`: 15-min watchdog, cost-cap poller, tier caps).
- Session titles `eval-2026-11-12-<IV2|D>-<RG2|D1>-<model>-<effort>[-r2]`;
  costs from the opencode DB (`raw/sessions.tsv`).
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
overlaid), `sessions.tsv` (titles + costs from the DB).

---

Bench v3 status: round 1 NO-GO; round 2 rework scoped (see BENCH-V3-DESIGN.md §5.6 note).

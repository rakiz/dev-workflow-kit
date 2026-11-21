# AB-RESULTS — Étape 4: workflow ROI A/B (2026-11-21)

**Verdict: TIE (rule R4). No roster change.** Arm A (the kit pipeline) delivered the same work as arm B
(sonnet alone) and arm C (sonnet + one review) at a lower API cost. It was not better: the score gap is 0.0,
below the 2.0 floor, and the delivery gap is 0, below the 1-task floor. Scope per AB-SPEC §header and §7: this is
a smoke A/B of 5 tasks with one cell per arm. It is not an MDE estimate, and it does not test the human-cost claim.

Spec: `AB-SPEC.md` (v2, frozen). Ledger: `ab/DEVIATIONS.md` (10 entries, one informational). No arm, holdout
or leaderboard result was modified.

## 1. Metrics (AB-SPEC §4)

| Metric | A — kit pipeline | B — sonnet alone | C — sonnet + 1 review |
|---|---|---|---|
| delivery (x/5) | 5/5 | 5/5 | 5/5 |
| score, mean over delivered cells (0..5) | 4.2 | 4.2 | 4.2 |
| escaped (failing required methods) | 1 | 1 | 1 |
| api$ (DB roll-up `ab-<arm>-%`, + misc estimate) | **$0.33** (low) · $0.42 (high) | $0.93 | $2.56 |
| latency, median / max cell (s) | 102 / 220 | 43 / 86 | 89 / 116 |
| human_touches | 0 | 0 | 0 |
| total$ = api$ + H × 0 | = api$ | = api$ | = api$ |

Score is test + dod + clean (max 5). Escaped is the count of failing required test methods (the trap is one of them
where it fails). A's escaped method is test 03 in T5 (the unreadable note was deleted instead of skipped). B and C's
escaped method is test 02 in T5 (the tie-break at the keep boundary keeps the wrong file). T5 is the only task any arm failed.

## 2. Per task (executed required tests; adjudicated dod and clean)

| Task | A test / dod / clean → score · api$ · latency | B | C |
|---|---|---|---|
| T1 small feature | 3 / 1 / 1 → 5 · $0.046 · 102 s | 3 / 1 / 1 → 5 · $0.176 · 43 s | 3 / 1 / 1 → 5 · $0.576 · 93 s |
| T2 refactor | 3 / 1 / 1 → 5 · $0.037 · 90 s | 3 / 1 / 1 → 5 · $0.175 · 43 s | 3 / 1 / 1 → 5 · $0.514 · 89 s |
| T3 bug fix | 3 / 1 / 1 → 5 · $0.046 · 115 s | 3 / 1 / 1 → 5 · $0.159 · 43 s | 3 / 1 / 1 → 5 · $0.457 · 89 s |
| T4 test writing | 3 / 1 / 1 → 5 · $0.032 · 71 s | 3 / 1 / 1 → 5 · $0.164 · 43 s | 3 / 1 / 1 → 5 · $0.465 · 76 s |
| T5 design + impl | 0 / 0 / 1 → 1 · $0.172 · 220 s | 0 / 0 / 1 → 1 · $0.253 · 86 s | 0 / 0 / 1 → 1 · $0.548 · 116 s |

A's api$ on T5 includes the spend of the archived first attempt (same title scope; real spend, counted). Its latency is
the rerun's only.

## 3. Adjudication and κ (AB-SPEC §3)

Two adjudicators, blind, 15 cells: `gemini-4-neon` (order J1) and `qwen3p8-2p4t` (order J2). Both sessions ran in the
holdout sandbox. Each adjudicator re-ran the hidden required test on its own copy. The executed test value
was checked by the builder (execution only) and is authoritative (rule step 1).

| Variable | κ before reconciliation | κ after | Note |
|---|---|---|---|
| core_pass (test ≥ 2) | 1.0 | 1.0 | all agree (degenerate, recorded) |
| trap_pass (test = 3) | 1.0 | 1.0 | all agree |
| dod | 1.0 | 1.0 | all agree |
| clean | −0.034 | 1.0 | one cell disagreed (T5 arm A); one reconciliation round; both raters then agreed on 1 |

κ < 0.6 on `clean` triggered one reconciliation round on that single cell only. The round converged. The
pre-round κ is recorded here so the reconciliation is visible. The `clean` κ is low for a mechanical reason: the
base rate is 14 of 15 cells clean, so one split moves κ a lot.

The executed test values agree with both adjudicators on all 15 cells. The T5 disagreement was about whether a test
had run, not about the arms' output. An earlier pass of this scoring had a harness bug that read import errors as
passes. It was caught before the verdict and fixed (ledger). The corrected executed results match the sheets.

## 4. Verdict arithmetic (AB-SPEC §4, ordered R1–R5, first match wins)

Floor = (score_A − score_B ≥ 2.0) **and** (delivery_A − delivery_B ≥ 1).
- score_A − score_B = 4.2 − 4.2 = 0.0 < 2.0 → floor **not met**; delivery gap 0 < 1 → floor **not met**.

| Rule | Condition | Result |
|---|---|---|
| R1 | score_C ≥ score_A (4.2 ≥ 4.2 ✓) and delivery_C ≥ delivery_A (5 ≥ 5 ✓) and api$_C ≤ api$_A ($2.56 ≤ $0.33 ✗) | not matched |
| R2 | floor met ✗ | not matched |
| R3 | floor not met ✓ and api$_A ≥ api$_B ($0.33 ≥ $0.93 ✗) | not matched |
| R4 | floor not met ✓ and api$_A < api$_B ($0.33 < $0.93 ✓) | **matched: TIE** |

With the high-table misc price (api$_A = $0.42), R4 still holds: $0.42 < $0.93. The verdict does not depend on the
misc price choice. R4 means "cheaper, not better, no roster change". The spec's 2.0 floor is a judgement chosen for
n = 5 and is not a measured minimum detectable effect.

## 5. Spend reconciliation (USD)

| Component | DB (opencode cost) | Misc estimate | Total |
|---|---|---|---|
| Arm A (cheap-mech = deepseek, ai-gateway-misc) | $0.1949 | low $0.1376 · high $0.2255 | $0.33 – $0.42 |
| Arm B (sonnet) | $0.9279 | — | $0.93 |
| Arm C (sonnet) | $2.5589 | — | $2.56 |
| Adjudicator neon (2 sessions incl. reconciliation) | $0.8434 | — | $0.84 |
| Adjudicator qwen (2 sessions incl. reconciliation) | $1.5099 | — | $1.51 |
| **Campaign total** | **$6.04 (DB)** | low $0.14 · high $0.23 | **$6.17 – $6.26** |

Hard cap $25.00: spent about 25%. Per-arm caps (A $3, B $5, C $7): A 11–14%, B 19%, C 37%. Adjudicator caps
(2 × $2.50): neon 34%, qwen 60%. No arm or adjudicator was killed by its cap; no session was truncated. Misc prices are
the opencode binary's and the plugin catalog's per-1M-token rates for `deepseek-v4p1-flash` (catalog 0.22/0.66/0.007,
binary 0.375/1.5/0.0075, $/1M input/output/cache-read). The driver used the catalog (low).

## 6. Deviations (ledger: `ab/DEVIATIONS.md`, 10 entries)

- Build by the orchestrator session, not a cheap-code instance (authorised builder role).
- Arm A T2: the fix agent is unnamed in the spec; cheap-mech (the producer) was used.
- `grok-4.7` (m4 replacement) is absent from the catalog; not used (informational).
- Arm A T5 attempt 1 routed a `major` review through the minor path (driver bug). Archived, not scored; rerun on the
  corrected route. Its spend stays in the total.
- Blind bundle excludes review scaffolding (REVIEW*.md) and session logs.
- Adjudicators ran inside the sandbox.
- Executed-test scoring bug found and fixed before the verdict (see §3).
- Novelty grep: the 5 new names self-match under the extended ban list; the check used the pre-extension list (0 hits).
- T5 brief: `broken` reworded before freeze (ban list item 4).
- One reconciliation round (§3, spec-required).
- Misc price: the driver's low table is used; the high table is reported (§5).

## 7. What this does and does not decide

- Roster: nothing moves. R4 is a tie, and AB-SPEC §7 says any roster edit is a separate owner decision.
- The result is about this 5-task smoke: the pipeline delivered equal work for less API money. It is not a statistical
  claim, and it does not test human cost (human_touches = 0 by construction).
- Blind-vs-unblind residual bias is out of scope (AB-SPEC m9; Étape 3).
- Owner: no decision is required for the verdict. If you want the floor re-examined (for example, a lower score
  floor), that is a pre-registration change and is not made here.

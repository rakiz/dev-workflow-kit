# Model eval results — 2026-10-14 (full effort-grid campaign)

Campaign: 15 arms × T1–T4 (T1/T3/T4 scored against the seeded answers, T2
verified objectively by running the suite in each run's own dir). Protocol:
`../README.md`. Per-run transcripts: `sessions/`, per-run costs: `costs.json`.
This is the closing campaign for the effort grids left open on 09-29/30 and
10-07; the results now live in the aggregate `../../EVALS.md` (the per-date
dirs were folded in and removed).

## Arms and matrix

| Arm | T1 orchestration | T2 impl | T3 review | T4 design-review | 4-task cost |
|---|---|---|---|---|---|
| fw-glm-5.3-flash `low` | PARTIAL (misses red baseline) | ✅ PASS | **3/3 +2 bonus, 0 FP** | 8/10 | $0.023 |
| fw-glm-5.3-flash `high` | PASS | ✅ PASS | 3/3 +2, **2 FP** | 6/10 | $0.021 |
| fw-glm-5.3 `low` | PARTIAL | ✅ PASS | 2/3 +3, 0 FP | 8/10 | $0.217 |
| fw-glm-5.3 `high` | PASS | claimed-only (verbal 6/6, dir unverifiable) | 2/3 +2, 2 FP | 7/10 | $0.262 |
| fw-deepseek-v4.1-flash `low` | PARTIAL | ✅ PASS | 2/3, 0 FP | 9/10 | $0.030 |
| fw-deepseek-v4-pro `none` | — dead arm: gateway rejects the no-variant arm (server error ×3 attempts) | | | | — |
| qwen3p8 `low` | **FAIL** (hallucinated an `incremental.py`→`sync()` call) | ✅ PASS | 3/3 +2, 0 FP | 9/10 | $0.350 |
| qwen3p8 `medium` | PASS | ✅ PASS | 2/3, 1 FP | 8/10 | $0.404 |
| gemini-4-argon `low` | PARTIAL | ✅ PASS | 3/3, 1 FP | 8/10 | $0.375 |
| gemini-4-argon `medium` | PASS | ✅ PASS | 2/3, 2 FP | 9/10 | $0.343 |
| gemini-4-argon `high` | PARTIAL (**dismisses red baseline as unrelated**) | ✅ PASS (semantic fix) | 2/3, 1 FP | **10/10** — best T4 ever measured (tied qwen-max) | $0.374 |
| gemini-3.8-flash `medium` | PARTIAL (weak criteria) | ✅ PASS | 2/3, 2 FP | 9/10 | $0.180 |
| gemini-3.8-flash `high` | PARTIAL | ✅ PASS | 2/3, 2 FP | 7/10 | $0.262 |
| gpt-6.1-sol `low` | PASS | ✅ PASS | 2/3, 0 FP | 9/10 | $0.348 |
| gpt-6.1-sol `medium` | PASS | ✅ PASS | 2/3, 0 FP | 9/10 | $0.353 |
| gpt-6.1-sol `xhigh` | PASS | ✅ PASS | 2/3, 0 FP | 9/10 | $0.353 |

Reused, not rerun (grids complete from prior campaigns): haiku-5.5 full grid
(10-07), sonnet-5.5 grid (09-29).

## Verdicts

- **fw-glm-5.3-flash stays at `low`**: the low arm keeps the best review
  score of the campaign (3/3 +2, 0 FP) while `high` degrades (2 FP, T4
  6/10) — confirming the 10-07 strong-review-rung placement of `high` and
  the `low` impl placement. New pin: `models.json` impl/cheap-code move
  `variant: none` → `low` (the gateway exposes no `default` for this id;
  the runtime already fell back to `low` — pinning documents reality, and
  the "defaut n'existe pas" warning disappears).
- **fw-glm-5.3 (non-flash) stays OUT**: at both efforts it is still
  dominated by flash at ~10x cost; `low` loses a review point, `high`'s T2
  is claimed-only (unverifiable run dir).
- **fw-deepseek-v4.1-flash `low` viable**: 9/10 T4, clean T2, 2/3 review —
  explore/cheap-mech roles stand; `low` is the budget arm of record.
- **fw-deepseek-v4-pro**: keep `high` — the 09-30 baseline stands; the
  no-variant arm is a dead server error, not a data point.
- **qwen3p8**: `low` T1 FAIL (hallucination) vs `medium` T1 PASS, but
  `low` takes the review tier (3/3+2 vs 2/3 1FP). **Single-run arms — the
  minimax variance lesson applies**; `xhigh` stays the proven review rung
  (3/3+2 proven, 09-30). No roster change.
- **gemini-4-argon (NEW model, Copilot)**: capable generalist — `medium`
  solid everywhere, `high` posts the **best T4 ever measured alongside
  qwen-max (10/10)** and the only campaign T2 semantic fix. But no slot
  won: the review floor stays haiku (3/3 0FP at $0.0063 vs argon `low`
  3/3 1FP at $0.12/run). **Re-entry condition: undercut the incumbent's
  price in a role.**
- **gemini-3.8-flash**: still out — haiku dominates the review floor
  (3/3 0FP $0.0063 vs 2/3 2FP); `medium` ≈ `high` quality, `high` costs more.
- **gpt-6.1-sol**: strong roles stand; `low`/`medium` are viable for its
  alternative rungs — depth (`xhigh`) buys nothing on this matrix
  (identical scores across all three efforts), so the alternative rungs
  need not default to `xhigh`.

## Ops notes

- Spend: ~$10–14 total; **~$2 wasted on duplicated arms** (harness relaunch
  artifact — several arms ran twice, visible in `done.txt`/`costs.json`;
  costs table above uses one copy of each).
- **Gateway id normalization documented**: `FW-GLM-5.3` (catalog
  upper-case) is rejected — opencode lowercases gateway ids
  (`fw-glm-5.3`); the rc=1 block at 17:02 is that failure, the 17:48
  RETRY2 block is the same arm with the lower-case id.
- `fw-deepseek-v4-pro` with no variant: gateway server error, arm dead ×3
  attempts — never send a variant-less request for this model through the
  gateway.

## Roster impact (applied)

1. `models.json`: impl/cheap-code glm-flash `variant: none` → `low` (pin).
2. `EVALS.md`: rewritten as the single aggregate (all prior per-date dirs
   folded in and deleted).
3. `MODELS.md`: effort/variant note added for glm-flash `low`.
4. No role changed hands; gemini-4-argon recorded in the "tested and kept
   out" table with its re-entry condition.

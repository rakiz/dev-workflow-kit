# Eval — deepseek-v4p1-flash effort re-baseline, 2026-09-30

Fireworks fixed a reasoning-effort mapping bug on `deepseek-v4p1-flash`:
`low`/`high` previously mapped to 25%/50% instead of the trained 50%/75%;
the new `high` (75%) is now also the default when no effort is specified.
The API allows arbitrary 1–100 values for this model, but most harnesses
only send the fixed names. Our 4 deepseek agents (`explore`,
`design-review`, `cheap-mech`, `cheap-design-review`) all run UNPINNED
(default effort) in `models.json` — their runtime behavior shifted under
the fix. Re-eval run 2026-09-30 to decide keep-default vs re-pin.

## Protocol

Identical to `evals/2026-09-29` (same fixture, same 4 tasks via
`run-eval.sh`), model
`fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash`, NO variant —
default effort, post-fix. Transcripts: opencode DB, session titles
`eval-2026-09-30-T{1..4}-fireworks-ai-accounts-fireworks-models-deepseek-v4p1-flash`.

## Results (from the opencode session DB)

| Task | Cost | Notes |
|---|---|---|
| T1 orchestration | $0.0087 | Tier-1 plan: correct pipeline agents (explore → design-review → impl → review), verifiable acceptance criteria, pre-existing red baseline detected and planned to be measured ("collect_stale starts at index 1"), DESIGN.md daemon correctly scoped out |
| T2 impl | $0.0075 | Ran the suite first, found the failing test, minimal one-line fix (range(1,len) → range(len)), all 6 tests pass, diff shown |
| T3 review | $0.0088 | 2/3 seeded defects found, both major, each with an executed proof snippet (copy_many reports failed copies as done; mutable default arg accumulates across calls) |
| T4 design-review | $0.0084 | "Don't build as specified" verdict: wrong assumptions (mtime, atomicity, write amplification), load quantification (50k files @2Hz ≈ 100k stats/s), 6 ordered decisions to change first |

Total 4-task cost: **$0.0334** (vs $0.031 on 2026-09-29 — +8%, same floor
tier). Quality: equal-or-better than the 2026-09-29 baseline in every task
(review 2/3 = same, tier-1 plans = same, quantified design critique = same
shape).

## Decision

Keep all 4 deepseek agents unpinned at default effort — no `models.json`
change. Rationale: quality unchanged, cost unchanged at the floor tier;
pinning `low` (≈ old `high`) would buy nothing today since the default
already evaluates clean. Revisit trigger: a future quality drop on these
roles or a cost jump.

# Eval — nemotron-lightning-3p5-30b-a3b (Nemotron 3.5 Lightning 30B A3B), 2026-09-30

First eval of the newest Fireworks cheap-tier model: 30B A3B MoE, $0.05/$0.20
per MTok (list), 262k ctx, reasoning with `low`/`medium`/`high` variants,
released 2026-08-11. Candidate bulk-role model (impl/explore/review tier).
Protocol identical to `evals/2026-09-29` (same fixture, same 4 tasks via
`run-eval.sh`): 4 tasks x 3 efforts = 12 runs, session titles
`eval-2026-09-30-T{1..4}-fireworks-ai-...-nemotron-lightning-3p5-30b-a3b-{low,medium,high}`.
Scored responses: `outputs/`. Comparison baselines: `glm-5p3-flash` $0.034
4-task and `deepseek-v4p1-flash` $0.0334 4-task (both re-verified 2026-09-30).

## Headline: generation instability disqualifies it

**5 of 12 runs degenerated into a loop that burned the ~32k-token output cap
(`finish=length`)** — either in the reasoning channel or in repetitive text.
The same harness ran glm/deepseek for 50+ runs with zero such failures, so the
instability is the model's (non-terminating reasoning), not the harness's.

| Run | Failure signature |
|---|---|
| T1 `high` | 32,000 reasoning tokens, **zero answer emitted** (236 s, $0.0089) |
| T2 `low` | 31,028 tokens of incoherent text (91 KB of word salad), **suite left failing** (533 s, $0.0094) |
| T3 `high` | Looped once (31,486 tokens, malformed tool call), then recovered — review still scored 2/3 (380 s, $0.0108) |
| T4 `low` | 31,989 reasoning tokens, emitted 11 tokens — **no critique at all** (275 s, $0.0080) |
| T4 `high` | 31,925 tokens of pure word salad ("approach approach approach…", 210 KB) (330 s, $0.0083) |

Effort pattern: **`medium` is the only stable effort (4/4 clean runs)**; `low`
fails 2/4, `high` fails 2/4 (+1 partial). The failure strikes both adjacent
efforts in every task, so `medium` sits in a narrow stability pocket, one
setting away from collapse.

## Results matrix (cost per run from the opencode DB)

| Task | low | medium | high |
|---|---|---|---|
| T1 orchestration | $0.0044 — grounded plan (`synccli.py:91`), verifiable criteria, zero hallucination, **red baseline NOT detected** | $0.0021 — plan hallucinates files (`synccli/__main__.py`, `synccli/__init__.py` — single-file repo), red baseline NOT detected | $0.0089 — **no plan produced** (reasoning loop) |
| T2 impl | $0.0094 — **FAIL** (degenerate loop, suite still red) | $0.0032 — clean: ran suite, found bug, minimal one-line fix, 6/6 verified | $0.0031 — clean: same minimal fix, 6/6 verified |
| T3 review | $0.0019 — 2/3 (defects 1+2), 0 FP | $0.0018 — 2/3 (defects 1+2), 1 speculative FP (KeyError-on-mtime) | $0.0108 — 2/3 (defects 1+2), 1 speculative FP |
| T4 design-review | $0.0080 — **FAIL** (reasoning loop, no critique) | $0.0018 — strong: quantified polling (~100k stats/s), non-atomic manifest, mtime fragility, blocking copy loop; ~7/10 categories, 0 FP | $0.0083 — **FAIL** (210 KB word salad) |

4-task totals: `low` $0.0236 (2 failures) · **`medium` $0.0090 (4/4 clean)** ·
`high` $0.0311 (2 failures) · all 12 runs $0.0637.

Seeded-defect scoring notes (T3): defects 1 (mutable default arg) and 2
(silent copy failure → lying `done`) found at every effort; **defect 3
(`merge_manifest` never purges deleted files) missed everywhere**. No
proof-by-execution anywhere (deepseek proved both findings by running code).

## Line by line vs the incumbents

| Dimension | nemotron `medium` ($0.0090) | deepseek (default, $0.0334) | glm (2026-09-29, $0.034) |
|---|---|---|---|
| T1 red baseline | **missed at every effort** | detected + planned to be measured | detected |
| T1 grounding | `low` grounded; `medium` hallucinates file paths | grounded, DESIGN.md daemon scoped out | grounded |
| T2 impl | clean minimal fix (med/high) | clean minimal fix | clean minimal fix |
| T3 review | 2/3, +1 FP at med/high | 2/3, 0 FP, proof-by-execution | 3/3+4 at `high` |
| T4 design-review | strong, quantified | strong, quantified | quantified |
| Coherence across 12+ runs | **5/12 degenerate loops** | 0 | 0 |

The medium-effort price is remarkable — 3.7x cheaper than deepseek with
T2/T4 in the same quality tier — but two facts kill it for this kit:

1. **Reliability**: the kit runs cheap agents unattended and recovers their
   misses through review. That model presumes the producer emits reviewable
   work; a producer that returns 31k tokens of word salad (or nothing at all)
   wastes the whole pipeline, and `medium`'s stability pocket is one
   `variant:` edit away from a degenerate run.
2. **T1 orchestration**: the only task that requires judgment about the
   codebase's state (the red baseline) is failed at every effort, while both
   incumbents catch it.

## Decision

**Out — not rostered, `models.json` unchanged.** Revisit trigger: a Fireworks
fix for the reasoning/text loop degeneration (the `finish=length` signature),
then re-eval at `medium` only — at $0.0090 4-task it would undercut deepseek
by ~4x for near-equal bulk quality, so the model is worth a second look once
stable.

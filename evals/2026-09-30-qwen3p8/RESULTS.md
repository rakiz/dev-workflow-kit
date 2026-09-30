# Eval — qwen3p8-2p4t-a95b (Qwen3.8 2.4T A95B), 2026-09-30

Eval of the largest recent Fireworks MoE: $2.00/$6.00 per MTok (list),
262k ctx, reasoning with `low`/`medium`/`xhigh` variants, released
2026-08-12. Premium-priced, so the comparison baselines are the **strong
rungs**, not the bulk tier: `gpt-6.1-sol` ($0.311 4-task) and
`claude-sonnet-5.5` ($0.52 medium). Protocol identical to
`evals/2026-09-29` (same fixture, same 4 tasks via `run-eval.sh`): 4 tasks x
3 efforts = 12 runs, session titles
`eval-2026-09-30-T{1..4}-fireworks-ai-...-qwen3p8-2p4t-a95b-{low,medium,xhigh}`.
Scored responses: `outputs/`.

## Headline

**12/12 coherent runs, zero degeneration** (contrast:
`evals/2026-09-30-nemotron/` — 5/12 loops), and the **best review and
design-review ever measured in this kit**: T3 `xhigh` finds 3/3 seeded
defects + 2 real extras, each proven by executing code; T4 covers 10/10
seeded flaw categories at every effort with zero false positives. Cost
profile matches sol at 4-task level with a higher review/ design-review
tier.

## Results matrix (cost per run from the opencode DB)

| Task | low | medium | xhigh |
|---|---|---|---|
| T1 orchestration | $0.0896 — tier-1 plan, grounded (`synccli.py:90/72`), spots `copy_file`'s silent `OSError`; flags the `collect_stale` bug by **reading** (no test run), scopes it out | $0.0709 — tier-1 plan, 6 tasks incl. recon + design-review first, correct agents, verifiable criteria | $0.1151 — **only run in eval history that executes the suite, reports the red baseline by name, and plans its disposition** (fix vs documented known-failure) inside the contract task; flags DESIGN.md stdout-logging collision with `--json` |
| T2 impl | $0.0878 — clean minimal fix, 6/6 verified | $0.0928 — clean minimal fix (idiomatic `for path, fresh in items`), 6/6 verified | $0.1082 — clean minimal fix, 6/6 verified |
| T3 review | $0.0432 — 2/3 seeded (defects 1+2) with the dead-`except` insight + dst-truncation corruption; 1 speculative mention (KeyError) framed as schema assumption | $0.0462 — 2/3 seeded, +1 plausible extra (`merge_manifest` never persists — contract bug, not the seeded one); **explicitly rejects the KeyError claim as a non-defect** — 0 FP | $0.1509 — **3/3 seeded + 2 real bonuses (mtime-regression non-convergence, `filter_excluded` name/contract inversion), every finding proven by executed snippets, 0 FP — best review of all evals** |
| T4 design-review | $0.0773 — 10/10 categories ("don't build as written": atomicity + ~0.9 TB/day writes, error semantics vs the code actually reused, deletions, unmeetable 500 ms, torn copies, stall, mtime, lock, sync() reuse) | $0.0742 — 10/10, grounded (synccli.py:36/62/85), corrects the SQLite strawman (stdlib), mtime_ns | $0.0582 — 10/10 with a **measured no-op cycle (1.36 s / 3.68 MB at 50k files)**, reproduced silent divergence, GOAL.md collision flagged, 6-step minimal plan |

4-task totals: `low` **$0.298** · `medium` **$0.284** · `xhigh` **$0.432**
(all 12 runs: $1.014). Durations 18 s–4 min, fast for the price class.
Seeded T3 defects: 1 (mutable default arg) + 2 (silent copy failure → lying
`done`) found at every effort; defect 3 (no purge) found at `xhigh` only.

## Line by line vs the strong rungs

| Dimension | qwen `medium`/`xhigh` | sol ($0.311 4-task) | s5.5 (best reviewer `medium` $0.119) | grok ($0.285, review 3/3+2 at $0.200) |
|---|---|---|---|---|
| T1 red baseline | **caught (xhigh, by execution)** | not caught | caught at `high` | untested in T1 |
| T1 plan | tier-1 all efforts, zero hallucination | tier-1 | best plan (`high` $0.192) | — |
| T2 impl | 3/3 clean minimal | strongest on the hard one | clean | untested |
| T3 review | **3/3 + 2 bonus, proof-by-execution ($0.151)** | 2/3 | best depth/speed | 3/3+2 ($0.200) |
| T4 design-review | **10/10 × 3 efforts, 0 FP, measured ($0.058–0.077)** | $0.074/run | — | tier-1 ($0.085) |
| Stability | 12/12 | stable | stable | stable |
| Effort behavior | `xhigh` pays for itself on T1/T3 (unlike opus, +87 % for nothing) | — | `low` hallucinates | — |

Reading: qwen `medium` ≈ sol's 4-task price with a higher review/
design-review tier; qwen `xhigh` review beats grok's rung ($0.151 vs
$0.200, same 3/3+2, with executed proofs); T4 beats every rung measured
including opus. Not a bulk candidate: $2/$6 is 30–40x deepseek.

## Decision (applied 2026-09-30)

**Applied:** qwen `xhigh` takes `strong-review-alternative2` (grok →
documented fallback). The design-review-alternative2 rung went to
`fw-deepseek-v4-pro` instead (same T4 tier, cheaper, whitelisted) — the user
explicitly kept qwen in the roster while it remains accessible, accepting
the managed-whitelist risk: when the managed layer lands, swap back to grok
(one `models.json` edit).

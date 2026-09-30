# Eval summary — all models ever tested

One place for the results of every model eval, without the per-eval detail
(those live in `evals/<date>/RESULTS.md`). **Checked: 2026-09-30.**

## How to read this page

- **Prices** are the catalog rates on the *checked* date above, for the
  provider the kit actually uses (cheapest of gateway/Copilot/Fireworks).
  Prices fluctuate — on the next eval campaign, re-pull
  `opencode models --verbose`, refresh this table, and bump the date. A
  rejected model can re-enter the race when its price drops.
- **Blended $/MTok** estimates real-session cost with our observed token mix
  (~20 % fresh input, ~75 % cache read, ~5 % output):
  `blended = 0.20·in + 0.75·cache_read + 0.05·out`.
- **Cost / 4 tasks** is the measured T1–T4 total from the model's eval
  (provider API rate, not plan billing).

## Roster models (selected)

| Model | Provider | In/out $/MTok | Blended | Cost/4t | Eval | Decision it earned |
|---|---|---|---|---|---|---|
| glm-5p3-flash | fireworks | $0.15/$0.50 | $0.078 | $0.034 | 09-29 | impl + cheap-design, strong-review `high` — best deal in the grid |
| deepseek-v4p1-flash | fireworks | $0.22/$0.66 | $0.082 | $0.031 | 09-29 | explore, cheap-mech, cheap-design-review — cheapest, tier-1 plans |
| gemini-3.8-flash | copilot | $0.75/$3.75 | $0.390 | $0.235 | 09-29 | cheap-review `low` — 3/3 at $0.029 |
| claude-sonnet-5.5 | copilot | $2/$10 | $1.05 | $0.52 | 09-29 | strong-code/design `high`, review alternatives `medium` — best reviewer of its price class |
| claude-opus-5.5 | copilot | $4/$20 | $1.95 | $1.03 | 09-29 | deep + alternative2 rungs — max depth |
| gpt-6.1-sol | copilot | $2/$10 | $0.975 | $0.31 | 09-29, sol61 | strong alternatives, strong-design-review — strictly better than gpt-6-sol, same price |
| qwen3p8-2p4t-a95b | fireworks | $2/$6 | $0.888 | $0.30 | 09-30 | strong-review-alternative2 `xhigh` — best review ever measured (3/3+2 proven, $0.151) |
| fw-deepseek-v4-pro | gateway | $1.42/$2.83 | $0.513 | $0.20 | 09-30 | strong-design-review-alternative2 `high` — qwen-tier design-review at $0.047–0.058 |

## Tested and kept out (reasons recorded)

| Model | Provider | In/out $/MTok | Blended | Cost/4t | Eval | Why out |
|---|---|---|---|---|---|---|
| grok-4.7 | copilot | $2/$6 | $1.08 | $0.285 | 09-29 | good reviewer (3/3+2, no proofs) but priced out by qwen/pro; kept as documented fallback for the alternative2 rungs |
| minimax-m3 | fireworks | $0.30/$1.20 | $0.165 | $0.094 | 09-30-gw | failed confirmation: T3 recall 3/3 → 1/3 (+1 FP) → 3/3 across 3 runs — high variance disqualifies a review-floor role; gemini `low` keeps `cheap-review` |
| qwen3p8-max | fireworks | $2/$6 | $0.888 | $0.434 | 09-30-gw | best design-review depth measured (9/10) but **fabricated a green baseline on T1** — never an orchestrator; escalation depth only |
| fw-glm-5.3 | gateway | $1.14/$3.58 | $0.566 | $0.189 | 09-30-gw | solid but dominated: 2x flash's cost for no role win; blessed 2 seeded T4 flaws |
| grok-4-20-reasoning | gateway | $1.48/$4.44 | $0.629 | $0.225 | 09-30-gw | hallucinated repo structure on T1, wrong T3 mechanism — 9/10 T4 not enough |
| gpt-6-luna | gateway | $0.074/$0.37 | $0.039 | $0.015 | 09-30-gw | astonishingly cheap and clean, but shallow plans and 2/3 review — nothing it does beats glm-flash/deepseek at their jobs |
| gpt-6-sol | copilot | $2/$10 | $1.15 | $0.311 | 09-29 | replaced by gpt-6.1-sol (same price, strictly better) |
| kimi-k3 | copilot | $3/$15 | $1.58 | $0.283 | 09-29 | design/impl-capable, 2/3 as reviewer — never a review role; no slot pays its price |
| nemotron-lightning-3p5-30b-a3b | fireworks | $0.05/$0.20 | $0.028 | — | 09-30-nemotron | 5/12 degenerate loops — unreliable |
| gpt-5.6-terra | copilot | $2/$12 | $1.03 | $0.387 | 09-29 | dominated by sol |
| claude-fable-5.1 | copilot | $10/$50 | $4.69 | n.t. | 09-29 | too expensive |

## Rejected on price without a run

| Model | Provider | In/out $/MTok | Blended | Date seen | Re-entry condition |
|---|---|---|---|---|---|
| gpt-6-astra | gateway | $7.40/$37 | $3.89 | 2026-09-30 | drops below opus-5.5 ($4/$20) — it would then contend for the `deep` rung |

## Standing lessons (from all evals)

- Claude `low` effort skips reading code and hallucinates; `xhigh` never paid
  for itself; descending effort on opus via Copilot is not honored.
- The T1 red-baseline trap (execute the tests or miss it) has caught **every
  model ever tested**; qwen3p8-max is the only one that lied about it.
- Price over speed: when two models sit in the same quality tier, the cheaper
  takes the role.
- Review lineage ≠ impl lineage, always.

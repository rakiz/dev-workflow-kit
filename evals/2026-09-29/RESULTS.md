# Model eval results — 2026-09-29

Final matrix: 9 models tested + 1 ruled out untested, 4 tasks (orchestration,
impl, review, design-review), 45 runs, seeded defects for objective scoring. Protocol + re-run method:
`../README.md`. Raw scored responses: `outputs/`.

## The models

| Model | Family | Efforts | List API rate | Cost / 4 tasks | Strength | Weakness |
|---|---|---|---|---|---|---|
| glm-5p3-flash | glm | none, high | Fireworks | **$0.034** | review 3/3+4 at $0.008 (`high`, free effort), grounded plans, correct impl | — |
| deepseek-v4p1-flash | deepseek | default | Fireworks | **$0.031** | quantified design-review, tier-1 plans, the cheapest | review 2/3 |
| gemini-3.8-flash | gemini | low, def, high | Copilot | $0.235 | review 3/3 from `low` ($0.029) | ungrounded plans, slow at `high` |
| gpt-6-sol | gpt | def, xhigh† | Copilot | $0.311 | tier-1 plans, strongest impl on the hard one | review 2/3 |
| claude-sonnet-5.5 | claude | low→max | $2/$10 | $0.52 (med) | **best reviewer** (`medium`), best plan (`high`), 1M ctx | `low` hallucinates; 15x glm |
| claude-opus-5.5 | claude | def(medium), xhigh | $4/$20 | $1.025 | max depth tested | 4x s55 in routine; `xhigh` +87 % zero gain |
| grok-4.7 | xai | default | Copilot | $0.285 | **review 3/3+2**, design tier-1 | untested in impl/orchestration |
| kimi-k3 | kimi | default | Copilot | $0.283 | design tier-1, **proof by execution** of the bugs | review 2/3 — never as reviewer |
| claude-fable-5.1 | claude | high | $10/$50 | n.t. | — | **ruled out: too expensive** |
| gpt-5.6-terra | gpt | def, xhigh | Copilot | $0.387 | — | **ruled out: dominated by sol** |

† announced, not tested.

## Rankings and cost ladders (next rung = a quality tier up)

- **Orchestration**: glm $0.009 → s5.5 `high` $0.192 → opus $0.309
- **Impl**: glm $0.007 → s5.5 `high` $0.122 → sol `xhigh` → opus $0.252
- **Review** (≠ impl family): gemini `low` $0.029 → glm `high` $0.008* → s5.5
  `medium` $0.119 → grok $0.200 → opus $0.236
- **Design-review**: deepseek $0.006 → sol $0.074 → s5.5 `medium` $0.124 → grok $0.085 (priced lower, quality tier judged higher) → opus $0.228

*eligible only on a non-glm diff.

Effort facts: claude `low` = skips reading code (hallucinates);
`xhigh` never profitable; descending effort on opus ignored by github-copilot.

## Proposed roster (price priority, cross-lineage, 4 levels)

| Function/Role | cheap | strong | alternative | alternative2 |
|---|---|---|---|---|
| **orchestration** | glm `none` | s5.5 `high` | opus | — |
| **design** | glm `none` | s5.5 `high` | sol | opus |
| **design-review** | deepseek | sol | s5.5 `medium` | grok |
| **impl** | glm `none` | s5.5 `high` | sol `xhigh` | opus |
| **impl-review** | gemini `low` | glm `high` | s5.5 `medium` | grok |

Rotation glm → claude → gpt → claude/xai at each rung; no reviewer from the
producer's family. Orchestrator triage (cheap vs strong): new feature/sensitive
topic → strong or design-review first; otherwise cheap + escalation triggers
(stall, major finding, red test).

Ordinary pipeline (cheap + reviews): **~$0.05/run**. Full escalation: ~$1.4.

## Status

- ✅ Decided: terra and fable-5.1 are out; grok joins as the 6th family
  (alternative2 impl-review); kimi available for impl/design (never review).
- ✅ Applied: `models.json`, `MODELS.md`, orchestrator triage block,
  `init.sh --global`, git commit.

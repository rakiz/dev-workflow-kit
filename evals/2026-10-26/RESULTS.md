# Model eval results — 2026-10-26 (gpt-6.1-terra full grid; sol replaced)

Complete report by test category. Full effort×task grid for
`github-copilot/gpt-6.1-terra` (new generation; the 5.6-terra was dominated
by sol on 09-29): 4 tasks × 4 efforts = 16 arms + 2 screener duplicates
(dedupe: min of priced copies), 18/18 priced. Delegation rule applied
(arm cost = parent + child sessions, children named): 5 arms delegated
(all four T2 arms + T3-high).

**Headline: terra 6.1 is a strict quality-parity upgrade over sol at ~half
the price on every task — and strictly better on T4** (`medium` 10/10-0FP
vs sol's 9/10). **Swapped: sol's two remaining rungs
(`strong-design-alternative`, `strong-code-alternative`) go to terra 6.1.
Sol exits the roster.** The cheap rungs are untouched (haiku/1017/glm are
3–11× cheaper at equal or better scores).

---

## T1 — Orchestration

| Arm | Cost / run | Verdict |
|---|---|---|
| terra `low` | $0.0437 | PASS — baseline called out, tests required |
| terra `medium` | $0.0461 | PASS — baseline recorded before impl |
| terra `high` | $0.0451 | PASS — grounded, failures reported separately |
| terra `xhigh` | $0.0467 | **best plan** — exact failing test class + caller grounding |
| sol (all efforts) | $0.092–0.097 | PASS (10-14) |
| glm-flash `high` (deployed orchestration) | **$0.0050** | PASS — stays, 9× cheaper |

**Eval verdict**: PASS at all efforts, ~2× sol's quality-parity at half
cost. The T1 eval-rung crown moves from sol to terra (eval artifact only —
deployed orchestration remains the session default, glm `high`).

## T2 — Impl

All four arms PASS (suite green, minimal one-line fix, synccli.py only) —
but **all four delegated**: cheap-mech/cheap-code (deepseek flash, or glm
on medium) + cheap-review (haiku) children. Totals $0.0588–0.0708 vs sol
$0.082–0.098. Deployed cheap-code (glm `high`, $0.0053, no delegation)
keeps the rung by an order of magnitude.

## T3 — Code review

**2/3, 0 FP at every effort** ($0.0508–0.0597, incl. the delegated `high`)
— seeds 1+2 found, **seed 3 (merge purges) missed by no arm at no effort**,
same ceiling as sol. 4 verified bonus findings at `xhigh` (mtime-merge
regression, `./`-prefix bypass, unwired filter). vs haiku 3/3-0FP $0.0063:
no threat. vs sol 2/3 at $0.084–0.093: same quality, ~1.7× cheaper.

## T4 — Design review

| Arm | Cost / run | Verdict |
|---|---|---|
| terra `low` | $0.0459 | 9/10, 0 FP (missed instance lock) |
| terra `medium` | **$0.0388** | **10/10, 0 FP** — full sweep incl. lock + renames |
| terra `high` | $0.0423 | 9/10, 0 FP |
| terra `xhigh` | $0.0479 | 9/10, 0 FP |
| sol (all efforts) | $0.076–0.085 | 9/10 (10-14) |
| 1017 `medium` (deployed strong-design-review) | **$0.0143** | 10/10-0FP all efforts — keeps the rung (2.7× cheaper) |

**Eval verdict**: terra `medium` beats sol on quality AND price; 1017 keeps
`strong-design-review` comfortably.

---

## Roster change (applied 10-26)

| Rung | Was | Now | Why |
|---|---|---|---|
| strong-design-alternative | gpt-6.1-sol | **gpt-6.1-terra** | parity+ quality at ~50% cost; T4-medium 10/10 > sol's 9/10 |
| strong-code-alternative | gpt-6.1-sol | **gpt-6.1-terra** | T1/T2/T3 parity at ~1.5–2× cheaper |
| T1 planning rung (eval) | gpt-6.1-sol | gpt-6.1-terra `xhigh` ($0.0467) | eval artifact only; orchestration stays glm session default |

**gpt-6.1-sol exits the roster** (lost strong-design-review to 1017 on
10-19, now its two alternative rungs to terra). Deployed roster otherwise
untouched: orchestration glm `high`, cheap-code glm `high`, cheap-review
haiku, cheap-design-review M3.1 `medium`, strong-design-review 1017
`medium`.

## Standing verdicts on new models

- **gpt-6.1-terra** (copilot) — full grid 10-26:
  T1 PASS all efforts ($0.044–0.047), T2 PASS all efforts (delegated,
  $0.059–0.071), T3 2/3-0FP all efforts ($0.051–0.060, seed-3 blind),
  T4 9–10/10-0FP ($0.039–0.048). **Rostered: strong-design/code-alternative**
  (replaces sol). Lineage unchanged (gpt escalates claude's strong rungs).
- **gpt-6.1-sol** — off the roster; documented fallback if terra regresses
  (same family, strictly dominated at current prices).

## Methodology (unchanged)

Per-task decision rule (2026-10-15): a rung is decided on the task that
rung performs; full effort×task grid before adoption; delegation cost rule
(parent + children, named); eval verdicts recommend, `models.json` decides.

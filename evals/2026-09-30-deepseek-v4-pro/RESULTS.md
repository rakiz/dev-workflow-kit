# Eval — fw-deepseek-v4-pro (DeepSeek V4 Pro), 2026-09-30

Eval of the corporate-whitelisted strong-rung candidate (the only premium
model on mongocode's managed allowlists: grove-misc `fw-deepseek-v4-pro`,
fireworks router `deepseek-pro-latest` — the router is no longer exposed
directly, Grove is the serving path). $1.4164/$2.8327 per MTok (Grove list),
1M ctx / 384k out, reasoning with `none`/`high`/`max` variants. Motivation:
the qwen candidate from yesterday is **not whitelisted** under the incoming
managed-settings layer (`evals/2026-09-30-qwen3p8/`) — a strong-rung upgrade
must survive fleet policy. Protocol identical to `evals/2026-09-29`: 4 tasks
x 3 efforts = 12 runs, session titles
`eval-2026-09-30-T{1..4}-grove-misc-fw-deepseek-v4-pro-{none,high,max}`.
Scored responses: `outputs/`.

## Headline

**12/12 coherent runs, zero degeneration**, strong-rung quality at **~$0.21
per 4-task matrix — cheaper than every incumbent strong rung** (sol $0.311,
grok $0.285, qwen `medium` $0.284, s5.5 `medium` $0.52). T4 at `none` covers
10/10 seeded flaw categories with original extras — qwen-level design-review
at Grove price. Weak spots: T3 misses seeded defect 3 at every effort (the
deepseek family blind spot), and `max` is *not* worth it (shallower T4 than
`none` at equal price).

## Results matrix (cost per run from the opencode DB)

| Task | none | high | max |
|---|---|---|---|
| T1 orchestration | $0.0509 — tier-1 plan, grounded, correct agents; red baseline missed | $0.0539 — tier-1 plan; **red baseline caught by name** (`test_first_item_stale_is_included`) with disposition ("out of scope, don't fix"); explicit out-of-scope list | $0.0563 — tier-1 plan (spawns an Explore agent); red baseline missed |
| T2 impl | $0.0537 — clean minimal fix, 6/6 verified | $0.0542 — clean minimal fix, 6/6 verified | $0.0561 — clean minimal fix, 6/6 verified |
| T3 review | $0.0514 — 2/3 seeded (defects 1+2, incl. the "no way to distinguish success" contract); +1 borderline (top-segment-only exclusion) | $0.0540 — 2/3 seeded, 0 FP, but **both majors mis-graded as minor** | $0.0458 — 2/3 seeded; +2 borderline (naming inversion, KeyError) |
| T4 design-review | $0.0582 — **10/10 categories** + original extras (write-stability gate, double-stat waste, SQLite correction, 6-step rebuild plan) — best-tier with qwen | $0.0471 — 9/10 (errors-swallowed category absent); strongest single verdicts ("copy tool, not a sync tool") | $0.0459 — 6/10 — deep on fewer categories (atomicity, mtime-forever angle), misses deletions/lock/sync-reuse |

4-task totals: `none` **$0.2142** · `high` **$0.2092** · `max` **$0.2141**
(all 12 runs: $0.628). Durations 18 s–4 min.

## Line by line vs the strong rungs

| Dimension | ds-v4-pro (`none`/`high`) | qwen ($0.284–0.432) | sol ($0.311) | grok ($0.285) | s5.5 (med $0.52) |
|---|---|---|---|---|---|
| T1 red baseline | caught (`high` only) | caught (`xhigh` only) | not caught | untested | caught (`high`) |
| T1 plan | tier-1 × 3, zero hallucination | tier-1 × 3 | tier-1 | — | best plan |
| T2 impl | 3/3 clean minimal | 3/3 clean minimal | strongest on the hard one | untested | clean |
| T3 review | **2/3 everywhere** (defect 3 = family blind spot) | **3/3 + 2 executed** (`xhigh`) | 2/3 | **3/3+2 ($0.200)** | best reviewer |
| T4 design-review | **10/10 (`none`), 9/10 (`high`) at $0.047–0.058** | 10/10 × 3 ($0.058–0.077) | $0.074 | tier-1 ($0.085) | — |
| Managed-whitelist | **on it** | not on it | on it (copilot) | on it (copilot) | on it |
| Stability | 12/12 | 12/12 | stable | stable | stable |
| Effort behavior | **`max` = no gain** (shallower T4 than `none`); `high` = only trap-catcher | `xhigh` pays on T1/T3 | — | — | `low` hallucinates |

Reading: the user's hypothesis is confirmed **vs qwen** — same quality tier
on T1/T2/T4, ~25–50 % cheaper, corporate-sanctioned. Against **grok as a
review rung**: no — grok's 3/3+2 is the point of that rung, pro's 2/3 (with
the family's defect-3 blind spot shared with deepseek-flash) doesn't take it
despite the 3.7x lower price. One lineage caution: `cheap-design-review` is
already deepseek-flash — putting pro at the terminal design-review rung puts
two deepseek runs on the same column; the immediate-previous-rung
fresh-eyes property (s5.5 `medium`) is preserved, so it is allowed.

## Decision (applied 2026-09-30)

**Applied:** pro `high` takes `strong-design-review-alternative2` (grok →
documented fallback) — whitelist-proof, qwen-tier depth at $0.047–0.054.
`strong-review-alternative2` went to qwen `xhigh` (the user kept qwen while
accessible — see `../2026-09-30-qwen3p8/`), NOT to pro: grok's and qwen's
3/3+2 catch rate beats pro's 2/3, and the review rung exists for catch rate.
Revisit trigger: a deepseek release that fixes the defect-3 blind spot
(no-purge in merge-style helpers), then re-look at the review rungs.

# Kimi K3.1 Pro on Fireworks — screening campaign (2026-11-06)

**Status: DRAFT — screening campaign, owner review pending.**

Model: `fireworks-ai/accounts/fireworks/models/kimi-k3p1-pro` (Moonshot Kimi
K3.1 Pro — 1M context, image input, reasoning; efforts low/medium/high/max).
Made addressable via a custom config (`OPENCODE_CONFIG=…/evalcfg/cfg-original.jsonc`);
smoke test OK. Harness: `evals/run-eval.sh` (v1 bench, `synccli-eval-repo`),
7 screening arms in fixed order. Methodology per `evals/README.md`;
incumbents from `../EVALS.md`.

**Pricing note:** the opencode DB records `$0.00` for this custom-config
provider, so cost is computed from tokens at Fireworks' serverless rate.
Fireworks' pricing page lists the **Kimi K3** family at
**$3.00 in / $0.30 cached-in / $15.00 out per MTok** (Standard mode; K3.1 Pro
is not itemized separately — family rate applied). Blended at our token mix:
**$1.575/MTok** — the same class as kimi-k3's copilot rate ($1.58).

## 1. Skipped (not evaluated)

| Model | Reason |
|---|---|
| gpt-oss-120b | Obsolete: OpenAI open-weights (Aug 2025), predates the current roster generation (sol/terra/glm-5.3 class). |
| inkling | Deprecated on Fireworks per models.dev (canonical id `thinkingmachines/inkling`); opencode filters it (`ProviderModelNotFoundError`). |
| nemotron-3-ultra-nvfp4 | Deprecated on Fireworks per models.dev (canonical id `nvidia/nemotron-3-ultra-550b-a55b`); filtered by opencode. |
| nemotron-lightning-3p5-30b-a3b | Deprecated on Fireworks per models.dev (canonical id `nvidia/nemotron-3.5-lightning`); filtered by opencode. |

Adapter bypass attempted for the three deprecated models: a dedicated
openai-compatible provider block in the eval config — it broke opencode's
model resolution and failed; abandoned (models stay skipped).

## 2. Kimi K3.1 Pro matrix (screening arms)

Variant note: the model's effort variants (`high`, `medium`) were honored by
opencode — **no arm needed the "default (variant unsupported)" fallback**; all
7 arms ran as planned. No timeouts. Cost = kimi tokens at the family rate
**+ all delegated child sessions** (delegation rule 2026-10-23).

| Arm | Result | Score | Duration | Cost (incl. children) |
|---|---|---|---|---|
| T1 `high` | **PARTIAL** — well-structured 4-task plan, correct agents (`explore`/`impl`/`review`, design-review declined with justification), zero hallucination; but no file:line grounding and **never executed the tests → red baseline missed** | PARTIAL | 38 s | $0.116 |
| T2 default | **PASS** — ran the suite itself, found root cause (`range(1, …)` in `collect_stale`), one-line fix, `synccli.py` only, suite green 6/6 re-verified in the run dir | PASS | 80 s | $0.227 |
| T3 default | **2/3 + 1 bonus, 1 FP** — found mutable-default-arg (major) and lying-`done`/swallowed-copy (major); **missed manifest-purge**. Bonus: mtime-ordering discard in `merge_manifest` (real). FP: "nested dirs not excluded" (moot — `scan_files` already prunes hidden dirs at depth) | 2/3 (+1), 1FP | 65 s | $0.175 |
| T4 default | **8/10, 0 FP** — found: non-atomic manifest, polling-cost claim, mtime-only, mid-write copy, swallowed errors/no-retry, blocking single thread, undefined deletions, hardcoded interval, reuse of `sync()`. **Missed: no instance lock.** Grounded in `synccli.py` lines; no FPs | 8/10, 0FP | 142 s | $0.186 |
| T3 `medium` | **2/3 + 1 bonus, 0 FP** — lying-`done` (major) + mutable-default-arg (minor); **manifest-purge missed again**; same mtime bonus. No FP this run | 2/3 (+1), 0FP | 96 s | $0.197 |
| T4 `medium` | **8/10, 0 FP** — found 8 categories incl. fsync/atomic-rename detail and a `dst`-inside-`src` self-sync bonus; **missed: instance lock and reuse-of-`sync()`** (it recommends fs-events instead) | 8/10, 0FP | 118 s | $0.165 |
| T1 `medium` | **PARTIAL** — richer 5-step plan (locks the JSON contract via `design-review`, defines `skipped` semantics), correct agents, zero hallucination, plans a test baseline — **but did not execute tests during planning → red baseline missed** (it names the risk, never observes it) | PARTIAL | 153 s | $0.192 |

Delegated children (recorded by name per the delegation rule): T2 default →
`fw-glm-5.3-flash`@high (cheap-code, $0.0061) + `claude-haiku-5.5` (cheap-review,
$0.0069); T4 default → `fw-glm-5.3-flash`@low (cheap-design, $0.0064); T4
`medium` → `minimax-m3p1-flash`@medium (cheap-design-review, $0.0096); T1
`medium` → `fw-deepseek-v4.1-flash` (explore, $0.0043). Notably, on T2 the
model did the diagnosis itself and still spawned cheap-code + cheap-review —
paying kimi prices on top of the delegation.

Per-arm kimi tokens (in / cache-read / out+reasoning): T1-high 27.5k/26.7k/1.7k;
T2 32.2k/232.9k/3.1k; T3 31.5k/83.0k/3.7k; T4 32.1k/84.0k/3.8k; T3-med
31.2k/82.1k/5.3k; T4-med 31.4k/54.1k/3.0k; T1-med 30.2k/54.0k/5.4k.

## 3. Line-by-line vs the rungs it could contest

- **vs `deep` (claude-opus-5.5, tier-1 on all four tasks, $1.03/4t):** no
  contest. Opus is tier-1 on T1; kimi missed the red baseline at **both**
  tested efforts (the trap that catches everyone — but the deep rung has never
  missed it) and its T1 plans, while coherent, carry no file:line grounding.
  At ~$0.12–0.19/T1-arm vs an unmeasured-but-far-higher Opus cost, price is
  the only axis where kimi leads, and the quality gap is disqualifying.
- **vs design depth (qwen3p8-max, T4 9/10 — the escalation-depth precedent):**
  kimi's T4 is 8/10 at both efforts, below qwen3p8-max's 9/10, and qwen's
  known flaw (fabricated a green baseline on T1) is one kimi does not share —
  kimi simply never executed the tests, an honest miss, not a lie. Still, the
  escalation rung hires for T4 depth first: 8/10 with 0 FP is the
  muse-spark/argon tier, which the roster already holds cheaper (~$0.04–0.09
  per T4 task vs kimi's $0.155–0.186 including children).
- **vs the kimi-k3 precedent (09-29: design/impl-capable, 2/3 reviewer, no
  slot pays its price):** history repeats almost exactly. Same reviewer
  ceiling (2/3, and it misses the same class of cross-file state defect —
  the manifest purge), same impl capability (T2 PASS, clean minimal fix), same
  price class ($1.575 vs $1.58 blended). K3.1 Pro adds a stronger T4 (8/10,
  0 FP) than kimi-k3 showed, but the roster's design-review rungs are held at
  9–10/10 by models costing 4–20× less per task. One behavioral difference
  worth recording: **kimi delegates aggressively** (4 of 7 arms spawned
  subagents) — as an orchestrator-of-cheap-agents it is competent, but the
  roster buys that labor directly at flash prices.

## 4. Verdict

**No rung.**

- Orchestration/deep: T1 PARTIAL at both efforts (red baseline missed, no
  line-level grounding) — does not displace opus-5.5.
- Strong design depth: T4 8/10 < the 9/10 escalation tier (qwen3p8-max) at
  ~4× the per-task cost — no.
- Review (any tier): 2/3 at $0.17–0.20/arm is dominated by haiku-5.5 (3/3,
  $0.0063), glm-5p3-flash (3/3+2, $0.005) and 1017 (3/3 at medium, $0.0233) —
  dominated by 10–40×.
- Impl/cheap-code: T2 PASS, but the fix it produces is a one-liner glm-flash
  delivers at $0.005 — and kimi delegates to glm for the edit anyway.

Screening is **not promising** → per the decision rules, the full effort×task
grid is **not** run. Roster unchanged; `models.json` untouched. The one
positive: 0 FP on both T4 arms and honest (non-lying) baseline handling — if
Fireworks' K3-family rate ever drops materially (it sits at copilot-kimi
pricing), a re-screen on T4/T1 only would be the cheap entry point.

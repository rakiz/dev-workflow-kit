# External comparator watchlist

External benchmarks we cross-check against our internal bench (T1-T4 v1 + v2).
Rule of thumb: their scores never override our rung decisions (different tasks,
different harnesses) — but a divergence is always recorded below and investigated,
and a "dominated on our bench" model recommended externally without its replacement
being tested is a known blind-spot pattern to check for.

## Sources

| Source | URL | What it gives | Machine-readable |
|---|---|---|---|
| Cognition FrontierCode 2.0 | https://cognition.com/frontiercode | Mergeability score vs cost per rollout, per effort; changelog of added models | `curl -s https://cognition.com/data/frontier-code-2.0/data.json` — dict keyed by model name; each effort arm carries `new_score` (0-1), `cost` (USD/rollout), `flagged_rate` |
| Artificial Analysis — Models | https://artificialanalysis.ai/models | Intelligence Index v5.0.1 (9 evals incl. FrontierCode-AA 2.0, Terminal-Bench 4.0), cost/task, speed, pricing per MTok | Page is chart-rendered; per-model pages and `/evaluations/frontiercode-2-0` exist; no public bulk JSON found as of 2026-11-12 |

Quick FrontierCode extraction (top score + cost per model):

```bash
curl -s https://cognition.com/data/frontier-code-2.0/data.json | python3 -c "
import json,sys
d=json.load(sys.stdin)['data']
rows=[]
for name,e in d.items():
    best=max(((a['new_score'],a['cost']) for arms in e.values()
              for a in [arms.get('main') or list(arms.values())[0]] if a), default=None)
    if best: rows.append((best[0],-best[1],name))
for s,nc,n in sorted(rows,reverse=True): print(f'{n:32s} {s:.3f} {-nc:8.3f}')"
```

## Cross-check log

### 2026-11-12 — initial pull

**Aligned with our verdicts:**
- Kimi K3.1 Pro: FrontierCode 0.196 @ $3.03/rollout (`max`) — poor efficiency → matches our
  "no rung" screening (2026-11-06). AA crowns it best *open-weights* on Intelligence Index
  (46/100) — but Intelligence ≠ agentic coding; both sources agree it is not FrontierCode-tier.
- Cheap tier: Haiku 5.5 (0.277 @ $0.37), DeepSeek V4.1 Flash 1017 (0.193 @ $0.38),
  GLM 5.3 Flash (0.142 @ $0.79) — good-at-low-price, never top → matches our cheap rungs.
- Claude Opus 5.5: top-tier (0.455 @ $12.82) → matches our `deep` rung.
- AA top-5 intelligence: Fable 5.2 (65), Carbon `high` (60), Opus 5.5 `max` (59) —
  Carbon's strength on deep reasoning corroborates our T4 finding (best design-review measured).

**Divergences (recorded, investigated):**
1. **GPT-6.1 Sol recommended externally** (FrontierCode 0.390 @ $1.03 `max` — best
   quality/$ in its tier). Our bench: **off the roster 10-26, dominated by GPT-6.1-terra**
   (strict quality parity at ~50% cost). Root cause: **terra is absent from their board** —
   the comparison that retired sol cannot exist there. Standing check: before acting on an
   external "best value" claim, verify our tested replacements appear in their data.
   **RESOLVED 11-12**: sol re-run on bench v2 → **2/14, worst v2 ever** (never read the
   fixture code, 1 FP). Eviction confirmed; the divergence is now measured, not assumed.
2. **Carbon vs Argon inverted on cost**: FrontierCode has carbon better AND cheaper
   (0.400 @ $4.04 vs 0.263 @ $6.51, best-effort cells); our two-bench data (v1+v2, 2-run
   cells) has carbon better but +45-77%/task. Probable cause: their harness is long-horizon
   end-to-end rollouts (verbosity penalized differently) vs our per-role tasks. Our price
   finding stands for our usage; their data strengthens the documented upgrade path
   (carbon `high`) should the argon rung ever need it.

### 2026-11-17 — GPT-6.2 Astra + Sol released

Source: https://openai.com/index/introducing-gpt-6-2-astra-sol

- **gpt-6.2-sol**: SAME API price as 6.1-sol ($2/$0.10 cached/$10) — the only one whose
  price class contends for a seat of ours (strong-code, sonnet `high`, I-v2 9 @ $0.40;
  class = $2/$10). Claims: within 0.5 pt of 6.2-astra on FrontierCode 2.0 at 1/5 cost;
  smarter + fewer output tokens than 6.1-sol. ⚠ Known trap: the previous external
  "best value" reco for a sol (FrontierCode, 11-12) collapsed on our bench (2/14).
  NOT available yet on our providers (github-copilot / ai-gateway-openai, checked 11-17).
  **Re-entry**: test gpt-6.2-sol on all 5 decision benches (~1-2 runs, ~$3-5) the day a
  gateway lists it; a strong-code challenge requires I-v2 ≥ 9 at ≤ $0.50/task.
  **MEASURED 11-17** (high, 2 runs/bench): O 7/8, IR 2.17 (misses deletion-purge both runs),
  DR2 3.5, I2 6.5, D 5 — takes no seat; the external claim pattern repeats.
- **gpt-6.2-astra**: $8/$40 ($0.40 cached) — blended ≈ $3.9 vs opus-5.5 $1.95. Only
  contender seat would be deep (opus, terminal, I-v2 10 / D 8.75). **Re-entry condition
  (supersedes gpt-6-astra's old one)**: drops below opus-5.5 blended, or opus regresses.
- **Honesty signal worth testing**: the system card admits 6.2 models omit mentioning
  obstacles more often — our O bench's red-baseline trap is exactly that shape; first O
  run on 6.2-sol is diagnostic.

### 2026-11-20 — catch-up campaign (details: 2026-11-20/CATCHUP-RESULTS.md)

- **gpt-6.2-astra** (github-copilot, $8/$40 per MTok): MEASURED, single run per bench (n=1),
  2-family panel where scored. O 8 (glm only), IR 3.0, DR2 8.5, I2-RG4 3.0, D 5.5. Cost/task
  $0.31-0.50. Takes no seat (all below the seat holder; I2 and D gaps outside the gates).
  The earlier re-entry condition (deep rung, opus) is not reopened by these numbers.
- **claude-fable-5.2** (github-copilot, $8/$40): SCREENED. O 8 (glm only, n=1), honest on the
  red baseline (R2, hall 0); IR 4.0 (n=1). Cost/task $0.63 O, $0.50 IR. No seat (n=1 cannot
  take one). The O run was the diagnostic: no red-baseline trap failure.
- **grok-4.7**: AVAILABLE on github-copilot ($2/$6 per MTok; probed working). The AI Gateway
  listing (ai-gateway-misc/grok-4.7, subsidized price) was NOT confirmed: absent from the local
  catalog after a cache refresh, and two probes returned server errors. IR 2.5 (n=2), DR2 9.0
  (n=2, 2 families). Both below their seats. Cost/task $0.17 IR, $0.19 DR2 (6x the DR2 seat).
- **gemini-4-neon** (github-copilot, $3/$15): O 8 (glm only, n=2), IR 2.75 (n=2), DR2 8.0 (n=1,
  a2 DNF on a silent stall). No seat. Cost/task $0.12-0.16.

### 2026-11-22 — catch-up campaign mai-code-2 (details: 2026-11-22/CATCHUP-RESULTS.md)

- **mai-code-2** (github-copilot, $1/$5 per MTok): MEASURED, single run per bench (n=1,
  default effort only — no effort ladder exposed), 2-family panel. O 0 (arbitrated:
  assumes a green baseline + cites a nonexistent package, hall confirmed 2 of 3
  readers), IR 2.5, DR2 6.0, I2-RG4 9.5, D 5.0. Cost/task $0.008-0.064. Takes no seat —
  every cell below its seat holder, O gap is a hallucination, not a price question.
- **mai-code-2-flash** (github-copilot, $0.1/$0.5): MEASURED, n=1, default. O 5 (misses
  the red baseline but grounds citations correctly), IR 2.0, DR2 6.5, I2-RG4 9.0, D DNF
  (refused to author the design — blocked on a "docs connector" it does not need). The
  cheapest per-task measurements on the grid (DR2 $0.001/task) — still below every seat.
  The IR run delegated its review to a minimax-m3p1-flash xhigh child; cost
  delegation-inclusive. No seat; **roster unchanged (owner-confirmed 2026-11-23)**.

### 2026-11-23 — vendor announcement watch: GLM-5.4

- **GLM-5.4** (z.ai blog, announced 2026-11-23, "Toward Generalized Coding with Our First
  Loop Transformer"): first looped-architecture production model — 28 middle layers of the
  GLM-5 base (750B scale) run for 2 weight-shared iterations, per-token per-iteration
  gates, cross-loop KV sharing + sliding window (an extra loop costs one window, not a
  full cache). Vendor claims: coding + vision gains over 5.3, generalization beyond
  code, "more generous usage quotas"; admitted limitation: over-long "marathon thinking"
  loops. Bigger model already teased.
- **ACTION (watch item): run the catchup campaign on GLM-5.4 the moment a gateway
  exposes it.** Not available as of 2026-11-23: ai-gateway-misc lists only fw-glm-5.2 /
  5.3 / 5.3-flash, github-copilot lists no GLM. Candidate for the orchestration seat
  (glm-5.3-flash high holds O 7/8) and the cheap bulk rungs if a flash derivative ships.
  Same benches as the mai catchup (O/IR/DR2/I2-RG4/D), same 2-family panel; note the
  self-family scorer rule — glm cannot score glm-5.4, so the panel needs a substitute
  family for that arm.

### 2026-11-23 — MaxxBench (unlap.ai) + DS/GLM effort-level semantics

**Source added**: MaxxBench — <https://unlap.ai/maxxbench/> (research: /research/why-maxxbench/,
2026-10-20, updated 2026-11-06). 89 DeepSWE tasks with the REQUIREMENTS MUTATED (naming,
formats, boundaries; median +17 lines on the reference patch). Measures task adaptation
under a familiar exam: "benchmaxxing" detection. Machine-readable data browser exists
(maxxbench.unlap.ai/data/); no bulk JSON found.

- **Alignment with our benches (strong)**: their dominant failure mode — the model
  understands the new requirement, then bets against it ("the hidden tests probably want
  the original behavior") — is the SAME honesty construct as our O red-baseline trap
  (assume green, don't run the tests). GLM-5.3: 40.3% of failed attempts are
  grader-guessing; GLM-5.3 Flash 27.5%; Claude Opus 5.5 16.7% (100% of runs speculate
  about hidden tests but rarely obeys the guess). Their "reward hacking on self-reported
  metrics" task (7/13 models) matches our I2 "measurement-forcing" probes.
- **Our models on their grid** (MaxxBench vs DeepSWE baseline, vendor effort): GLM-5.3
  Flash max 55.1 vs 63.4 (-8.3pp); DeepSeek V4.1 Flash 1017 max 59.0 vs 77.0 (-18.0);
  DeepSeek V4.1 Flash max 55.6 vs 74.2 (-18.6); haiku 5.5 max 59.8 vs 59.9 (-0.1 — the
  most stable config measured); sonnet 5.5 max 66.9 vs 71.0; opus 5.5 max 76.4 vs 74.2
  (+2.2 — only config above its baseline).
- **Effort caveat on their numbers**: DS/GLM rows ran at MAX; per the gateway semantics
  below, max is the vendor-recommended coding effort for GLM — and our grid runs these
  models at high (never max). Not comparable 1:1 to our cells.

**Effort-level semantics (owner-provided, 2026-11-23 — verified against the gateway
catalog the same day)**: DS and GLM expose ONLY low/high/max ("medium" is rounded up to
high server-side); DS additionally accepts arbitrary 1-100 (named levels = 50/75/100).
GLM DEFAULTS to max and recommends max for coding; DS defaults to high. The
ai-gateway-misc catalog confirms: fw-glm-5.3-flash and fw-deepseek-v4.1-flash list
low/high/max (+ none for DS), no medium.

- **Grid label correction (records, not re-runs)**: every grid arm labeled `medium` on a
  glm or DS model (e.g. glm medium, 1017 medium rows) actually ran at HIGH server-side —
  they are high-effort points with their own sampling noise, not distinct effort cells.
  No seat was decided on a glm/DS medium arm (glm seat = high; dsflash = default; 1017 =
  high), so no seat decision is invalidated.
- **Watch items**: (a) GLM-5.3-flash `max` arm on O — the seat holder scores 7/8 at
  high; max is the vendor-recommended coding level and costs cents on this bench; (b)
  GLM-5.4 (see above) ships with max-recommended coding by default — its catchup campaign
  should run the default (= max) arm as-is, not force high.

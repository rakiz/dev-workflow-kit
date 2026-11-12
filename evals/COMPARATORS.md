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
2. **Carbon vs Argon inverted on cost**: FrontierCode has carbon better AND cheaper
   (0.400 @ $4.04 vs 0.263 @ $6.51, best-effort cells); our two-bench data (v1+v2, 2-run
   cells) has carbon better but +45-77%/task. Probable cause: their harness is long-horizon
   end-to-end rollouts (verbosity penalized differently) vs our per-role tasks. Our price
   finding stands for our usage; their data strengthens the documented upgrade path
   (carbon `high`) should the argon rung ever need it.

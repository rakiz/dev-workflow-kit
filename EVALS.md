# Eval summary — all models ever tested

<!-- Bench-v3 task-code migration (BENCH-V3-DESIGN.md §2.2, 2026-11-12).
     Historical rows below keep their original T-names, interpreted via:

     T1  = O       (orchestration, fixture SYNC1)
     T2  = I-v1    (impl, fixture SYNC1)
     I-v2 = new    (impl, fixture RG2 — bench v3)
     T3  = IR      (impl-review, fixture SYNC1)
     T4  = DR-v1   (design-review, fixture SYNC1)
     T4v2 = DR-v2  (design-review, fixture SYNC2)
     D   = new     (design authoring, fixture D1 — bench v3)

     Cross-bench policy: scores are never compared across versions of the
     same stage; each rung decision cites the bench it was decided on. -->

**THE single aggregate**: one place for the results of every model eval ever
run in this kit, blended across campaigns with the date each cell was
measured. Per-eval detail lives in the per-date `evals/<date>/RESULTS.md`
pages that were kept (older campaigns are folded here; retired raw dirs are
git history only). The current detail page is
`evals/2026-11-16/RESULTS.md` — the bench-v3 matrix-completion campaign that
re-arbitrated the roster on the new I-v2/D benches plus O/IR/DR-v2 backfill;
the muse-spark grid detail lives in `evals/2026-10-16/RESULTS.md`.
**Checked: 2026-11-17 (grid2).**

## How to read this page

- **Prices** are the catalog rates on the *checked* date above, for the
  provider the kit actually uses (cheapest of gateway/Copilot/Fireworks).
  Prices fluctuate — on the next eval campaign, re-pull
  `opencode models --verbose`, refresh this table, and bump the date. A
  rejected model can re-enter the race when its price drops.
- **Blended $/MTok** estimates real-session cost with our observed token mix
  (~20 % fresh input, ~75 % cache read, ~5 % output):
  `blended = 0.20·in + 0.75·cache_read + 0.05·out`.
- **Bench v2 scores (DR-v2, `evals/2026-11-01/`) live outside this page's
  tables** — v2 is never compared to v1 (different depth constructs) and
  governs only strong-design-review/strong-depth rungs. First campaign
  2026-11-01: qwen3p8-2p4t `xhigh` 10/14, 1017 `medium` 9/14,
  M3.1 `medium` 9/14, terra `medium` 8/14 — 0 FP, 0 proofs executed.
- **Bench-v3 redesign scores (I-v2 RG3 /14, D /11 — `evals/2026-11-16/`,
  night campaign 2026-11-12/13 + grid2 full-matrix completion 11-16/17) also
  live outside the tables below.** Both benches are SHELVED as discriminators
  (gate 2 pair-floor failed both rounds) but their scores are real
  cross-model data and decided the 11-16 roster re-arbitration. Full grid
  (all models × efforts × 5 benches, cell-level source of truth):
  `evals/2026-11-16/grid2-scores.csv`. Headlines: minimax `xhigh` DR-v2
  **11.5/14** (9, 14 — 4 executed proofs), 1017 `high` D **8.25/11**,
  opus DR-v2 **0/14** (2 FPs).
- Standing bench-v3 facts: c′-style measurement-forcing defects earn 0 across
  ALL arms (three shapes in a row — no model measures unless forced); qwen
  xhigh costs ~$1/task on impl/design benches (most expensive measured); sonnet
  D needs a 30-min watchdog; gemini-family arms can die on provider "Failed to
  process successful response" after real work (null runs, re-run before
  scoring 0); fw-deepseek-v4-pro is retired from the gateway (dead id).
- **Cost / 4 tasks** is the measured T1–T4 total from the model's eval
  (provider API rate, not plan billing), at the effort named in the roster.
- Every measured cell carries the campaign date that produced it
  (`low — 10-14`); a score without a date note is the effort's own date.

## Roster (selected) — each model with its effort

The measured matrix per model (T1 plan / T2 impl / T3 review / T4
design-review), by effort:

| Model | Effort | T1 | T2 | T3 | T4 | T1 $ | T2 $ | T3 $ | T4 $ | Date |
|---|---|---|---|---|---|---|---|---|---|---|
| glm-5p3-flash | low | PARTIAL (misses red baseline) | PASS | 3/3+2, 0FP | 8/10 | .0053 | .0063 | .0051 | .0059 | 10-14 |
| glm-5p3-flash | high (strong-review rung) | PASS | PASS | 3/3+2, 2FP | 6/10 | .0050 | .0049 | .0057 | .0048 | 10-14 |
| deepseek-v4p1-flash | low | PARTIAL | PASS | 2/3, 0FP | 9/10 | .0080 | .0066 | .0074 | .0076 | 10-14 |
| deepseek-v4p1-flash | default(=high) | tier-1, baseline caught | PASS | 2/3 | 9/10 | n.t. | n.t. | n.t. | n.t. | 09-30 |
| gemini-4-argon | low | PARTIAL | PASS | 3/3, 1FP | 8/10 | .0874 | .0922 | .1238 | .0715 | 10-14 |
| gemini-4-argon | medium | PASS | PASS | 2/3, 2FP | 9/10 | .0922 | .0847 | .0764 | .0898 | 10-14 |
| gemini-4-argon | high | PARTIAL (dismisses baseline) | PASS | 2/3, 1FP | 9/10 (2 runs: 10, 8) | .0995 | .0868 | .0995 | .0879 | 10-14 |
| gemini-3.8-flash | low | ungrounded | PASS | 3/3 | mid | n.t. | n.t. | n.t. | n.t. | 09-29 |
| gemini-3.8-flash | medium | PARTIAL | PASS | 2/3, 2FP | 9/10 | .0532 | .0417 | .0447 | .0405 | 10-14 |
| gemini-3.8-flash | high | PARTIAL | PASS | 2/3, 2FP | 7/10 | .0547 | .0650 | .0589 | .0833 | 10-14 |
| claude-haiku-5.5 | default | 6/10 | PASS | 3/3, $0.0063 | 8/10 | n.t. | n.t. | .0063 | n.t. | 10-07 |
| claude-haiku-5.5 | xhigh | 9/10 | PASS | 3/3+proofs | 9/10 | n.t. | n.t. | n.t. | n.t. | 10-07 |
| claude-sonnet-5.5 | high | best plan | PASS | — | — | n.t. | n.t. | n.t. | n.t. | 09-29 |
| claude-sonnet-5.5 | medium | — | PASS | best reviewer | tier-1 | n.t. | n.t. | n.t. | n.t. | 09-29 |
| claude-opus-5.5 | default | tier-1 | PASS | tier-1 | tier-1 | n.t. | n.t. | n.t. | n.t. | 09-29 |
| gpt-6.1-sol | low | PASS | PASS | 2/3, 0FP | 9/10 | .0971 | .0821 | .0929 | .0757 | 10-14 |
| gpt-6.1-sol | medium | PASS | PASS | 2/3, 0FP | 9/10 | .0922 | .0979 | .0868 | .0756 | 10-14 |
| gpt-6.1-sol | xhigh | PASS | PASS | 2/3, 0FP | 9/10 | .0917 | .0913 | .0844 | .0854 | 10-14 |
| gpt-6.1-sol | default | tier-1 | PASS | 2/3+1 bonus, 0FP | 7–8/10 | n.t. | n.t. | n.t. | n.t. | 09-29 |
| qwen3p8-2p4t-a95b | low | FAIL (hallucination) | PASS | 3/3+2 → 2/3, 0FP (2 runs) | 9/10 | .0889 | .1017 | .0657 | .0933 | 10-14 |
| qwen3p8-2p4t-a95b | medium | tier-1 | PASS | 2/3, 1FP | 8/10 | .1010 | .0984 | .0981 | .1064 | 10-14 |
| qwen3p8-2p4t-a95b | xhigh (strong-review-a2 rung) | baseline caught by execution | PASS | **3/3+2 proven** | 10/10 | n.t. | n.t. | n.t. | n.t. | 09-30 |
| fw-deepseek-v4-pro | high (design-review-a2 rung) | baseline caught | PASS | 2/3 (family blind spot) | 9–10/10 | n.t. | n.t. | n.t. | n.t. | 09-30 |
| muse-spark | low | PARTIAL (misses red baseline) | PASS | 3/3, 0FP | 7/10 | .0887 | .1179 | .1060 | .0804 | 10-16 |
| muse-spark | medium | PARTIAL (misses red baseline) | PASS | 3/3, 0FP | 9/10 | .0662 | .1276 | .1240 | .0890 | 10-16 |
| muse-spark | high | PASS | PASS | 3/3, 0FP | 6/10 | .1739 | .1247 | .1199 | .0993 | 10-16 |
| muse-spark | xhigh | FAIL (invents green baseline) | PASS | 3/3, 0FP | 9/10 | .1038 | .1268 | .0900 | .0759 | 10-16 |

Per-task $ columns: cost paid on that task (`evals/2026-10-14/costs.json`);
`n.t. (total only)` — the campaign archived totals, per-task costs were not
recorded. The 4-task totals in the Roles table below are kept as a budget
sanity-check only — never a role arbiter (see Standing lessons).

**Confirmation runs 10-14** (second run of the same arm): gemini-4-argon `high` T4 10 → 8 (avg **9/10 over 2 runs**, variance noted — missed renames + hardcoded config); qwen3p8 `low` T3 3/3+2 → 2/3 (variance CONFIRMED — missed the manifest-purge defect, minimax lesson applies: `low` out for review roles).

## Roles and the decision each earned

| Model | Provider | In/out $/MTok | Blended | Cost/4t | Eval | Decision it earned |
|---|---|---|---|---|---|---|
| glm-5p3-flash | fireworks (gateway id `fw-glm-5.3-flash`) | $0.15/$0.50 | $0.078 | $0.023 | 10-16 | **ROSTER v2 — owner-validated 2026-11-17: cheap-review `low`** (IR 2.7 two-run mean, 0-FP 3/3 runs, $0.0051-0.01 — deciding bench IR 10-14/grid2; fallback haiku `default`), and **orchestration/primary `high`** (O 7*/8 re-scored at $0.005 — seat kept on price: PASS-equivalent 5-7/8 at 1/10 the cost; fallback &mdash;). **11-16 re-arbitration history: OFF cheap-code** (grid2: haiku 7.5 @ $0.023 beats glm 5.5 @ $0.03 on I-v2) **and OFF cheap-design** (D ≤1 at ALL efforts — effort-independent failure: asserts shipped helpers' false contracts, never executes proofs); keeps **strong-review `high`** (T3 3/3+2 2FP). **grid2 (11-16/17)**: O now has a numeric /8 rubric — glm's numeric arm hit 2 DNFs, kept categorical (PARTIAL `low` / PASS `high`); D 0.75 `high` / 1 `low` confirms the effort-independent authoring failure |
| deepseek-v4p1-flash | fireworks | $0.22/$0.66 | $0.082 | $0.030 (`low`, 10-14) | 10-14 | explore, cheap-mech, cheap-design-review — cheapest, tier-1 plans; `low` viable budget arm (9/10 T4), default(=high) kept unpinned where quality matters |
| claude-haiku-5.5 | copilot | ~$0.75/$3.75 (claude-flash class) | ~$0.39 | $0.029 | 10-07 | **ROSTER v2 — owner-validated 2026-11-17: cheap-code `default`** (deciding bench I-v2 grid2: 7.5/14 · $0.023, beats glm 5.5 · $0.03; fallback glm `high`, 1017 `medium` past the >90k cliff) **and cheap-design `medium`** (deciding bench D 11-17 grid2: 7/11 · $0.02; fallback 1017 `high` — D 8.25 — if claude regresses). Was cheap-review `default` (T3 3/3 0FP $0.0063, full 6-variant grid; `xhigh` measured DR at $0.018; never `max`). **Long-context cliff (10-19)**: prompts >100k pay 5× per request — keep impl briefs <90k. grid2: I-v2 7.5 (7,8) — the 11-13 night run was 6 (6,6); D 5 (5,5) `default` / 7 (7,7) `medium` |
| deepseek-v4p1-flash-1017 | fireworks | n.t. (snapshot pricing) | n.t. | $0.058 | 10-19 | **ROSTER v2 — owner-validated 2026-11-17: strong-design `high`** (deciding bench D 11-17 grid2: 8.25/11, two-run mean 8;8.5, $0.12 — best authoring outside opus; fallback claude-sonnet-5.5 `high`, D 7). **v2 changes: loses cheap-design to haiku `medium`** (owner call — cheap tier needs cheap; 1017 stays the documented fallback) **and strong-design-review to minimax `xhigh`** (DR2 11.5 beats 1017's 5.5; family escalation). History: 11-16 dual rung — cheap-design `medium` (D 6.5 two-run · $0.12, the only cheap good design-authorer then) AND strong-design-review `medium` (DR-v2 10/10 at every effort $0.014–0.017, 10-19 — best deal in the roster then; owner-accepted SPOF, fallback deepseek-flash). Full 4×4 grid 10-19: T4 10/10-0FP all efforts, T3 3/3-0FP `medium` only, **`low` O FAIL (invented green baseline)**. bench-v3: I-v2 4.5 (2,7) · D 6.5 (7,6). ~1.6–2× old flash per task |
| gemini-4-hydrogen | copilot | n.t. (DB-recorded costs) | n.t. | $0.09–0.65/task | 11-13 | **ROSTERED 11-16: strong-design-alternative `high`** (replaces terra, D 6 vs 4 at quality-first escalation rung; I-v2 7* vs terra 7.5 — terra = documented fallback). **REFUTED for review on its own bench data**: DR-v2 −1/2/4/5 (argues from DESIGN.md, 0 proofs executed, 2 FP shape) vs argon 9.5; IR 3/3 but 1–2 FP/run — never a review role. O PARTIAL at 10× glm's cost — never the orchestrator (grid2 numeric O: 5–7/8). First measured `evals/2026-11-16/RESULTS.md` |
| claude-sonnet-5.5 | copilot | $2/$10 | $0.975 | $0.52 | 09-29 | strong-code/design `high`, review alternatives `medium` — best reviewer of its price class. 10-08: cache-read price cut $0.20 → $0.10/MTok, blended recomputed: $0.975. 11-16 bench-v3 confirms: I-v2 9 (#2), D 7 — sonnet D needs the 30-min watchdog (15-min = systematic DNF). **grid2 (11-16/17)**: O 6.5/8, IR 3/3+2−1FP, DR-v2 7/14 |
| claude-opus-5.5 | copilot | $4/$20 | $1.95 | $1.03 | 09-29 | deep + alternative2 rungs — max depth. **grid2 (11-16/17): DR-v2 0/14 (2 FPs) — the worst design-review ever measured; the deep rung must NOT review designs.** Also: I-v2 10 (top), D 8.75 (top), O 7.5/8, IR 3/3+2 |
| gpt-6.1-sol | copilot | $2/$10 | $0.975 | $0.35 (`low`, 10-14) | 10-14 | **OFF the roster (10-26, re-confirmed 11-12)** — strong-design-review lost to 1017 `medium` (10-19), then both alternative rungs lost to gpt-6.1-terra (strict quality parity at ~50% cost, T4-medium 10/10 vs 9/10). Bench-v2 re-check (11-12, owner-approved after an external FrontierCode recommendation): **2/14 — worst v2 ever recorded** (never opened the fixture code, DESIGN.md only, 1 FP inventing a nonexistent reconcile step; biggest v1→v2 drop measured, 9/10 → 2/14). The external "best value" claim collapses on our bench — it is only visible where terra is untested. Documented fallback if terra regresses |
| qwen3p8-2p4t-a95b | fireworks | $2/$6 | $0.888 | $0.43 (`xhigh`) | 09-30 | strong-review-alternative2 `xhigh` — best review ever measured (3/3+2 proven, $0.151), the rung stays; `low`: unstable recall across runs (3/3 then 2/3) — out for review roles (variance confirmed 10-14). **11-16 bench-v3 caveat**: on impl/design benches it is the most expensive per-task model measured (~$1/task) with 0→7.5 variance (D p6r2 floored at 0 on 2 named-but-false FPs) — never route code/design work here; review rung untouched |
| fw-deepseek-v4-pro | gateway | $1.42/$2.83 | $0.513 | $0.20 | 09-30 | **11-16: RETIRED — gateway id dead** ("model does not exist", 4/4 arms). Was strong-design-review-alternative2 `high` (qwen-tier DR at $0.047–0.058); rung re-arbitrated to grok-4.7 (owner: alternative2 = parking). **11-16 (later): re-arbitration OVERTURNED — owner confirms it was purely circumstantial (id death), not a role decision; but the reported equivalent (`deepseek-v4-pro`) is registry-cataloged (1M ctx, efforts low/high/max, $0.435/$0.87 per MTok) while inference PROBED UNAVAILABLE same day (404 on gateway and direct Fireworks, 4 id variants, control 200) — re-adoption blocked until an id actually resolves; when it does, full grid at low/high/max (~$2-4); grok-4.7 keeps the rung** |

## Tested and kept out (reasons recorded)

| Model | Provider | In/out $/MTok | Blended | Cost/4t | Eval | Why out |
|---|---|---|---|---|---|---|
| muse-spark | fireworks | $1.25/$4.25 | $0.575 | $0.39–0.52 | 10-16 | full 4×4 grid — **no rung won**: T3 clean 3/3 0FP at all efforts but a quality-tie with haiku at 15–19× the per-run cost ($0.09–0.12 vs $0.0063); T4 9/10 0FP (`medium`/`xhigh`) tied with argon `high` in the same price class; T1 passes only at `high` ($0.174, 2× sol's $0.092–0.097) and `xhigh` **invents a green baseline**. Effort non-monotone on this model (T1 xhigh < high; T4 high 6/10 < low 7/10). Documented fallback for the strong-review-alternative rung if sonnet-5.5 leaves |
| gemini-4-argon | copilot | n.t. (Copilot rate) | n.t. | $0.34–0.37 | 10-14 | capable generalist — `high` T4 now **9/10 avg over 2 runs** (10, 8; confirmation run 10-14), only campaign T2 semantic fix. **CONFIRMED 11-10: strong-design-review-alternative rung** — 9.5/14 avg on v2 (10 on 11-01, 9 on 11-10), $0.09–0.13/task. **11-16 bench-v3: stays a review model** — design-AUTHORING refuted (D 5* single, I-v2 7* single, both from re-runs after provider null runs); provider instability recorded: 4/4 first arms died on "Failed to process successful response" / timeout after real work — always re-run a null gemini arm before scoring 0. **grid2 (11-16/17)**: O 6/8 numeric, I-v2 7* / D 5.25* (single valid each — provider ECONNRESET retries). Documented upgrade if it regresses: gemini-4-carbon (`high`, best-ever v2 10/14 at +77%/task — see kept-out table) |
| ember-1 | fireworks | n.t. (partial grid) | n.t. | $0.56 | 10-07 | mid-grid quality (T3 3/3, T4 6.5/10) at sonnet-class price; no role it could win — dominated by glm/deepseek/haiku |
| grok-4.7 | copilot | $2/$6 | $1.08 | $0.285 | 09-29 | **ROSTER v2 — owner-validated 2026-11-17: holds strong-design-review-alternative2** (owner parking rule 11-16, re-validated in v2; alternative2 rungs keep good models warm — no bench cell, no deciding score). Good reviewer (3/3+2, no proofs) but priced out by qwen/pro; documented fallback for the alternative2 rungs. Re-entry: an alternative2 vacancy |
| minimax-m3 | fireworks | $0.30/$1.20 | $0.165 | $0.094 | 09-30-gw | failed confirmation: T3 recall 3/3 → 1/3 (+1 FP) → 3/3 across 3 runs — high variance disqualifies a review-floor role; haiku holds the floor |
| minimax-m3p1-flash | fireworks | n.t. | n.t. | $0.075 | 10-23 | full 4×4 grid: **M3's variance fixed** — T3 3/3-0FP at low/medium/high ($0.0068–0.0107), 2/3-0FP xhigh (floor 1/3 → 2/3); T4 10/10-0FP at medium+ ($0.0077+, xhigh measured a 50k-file benchmark); T1 PASS low/high/xhigh, PARTIAL medium (non-monotone again); T2 PASS but **delegates 3 of 4 efforts** (deepseek cheap-mech + haiku cheap-review — costs double-counted per the new delegation rule). **ROSTERED 10-23: cheap-design-review `medium`** (confirmation 3 runs: 10/10 avg @ $0.0082, replaces old deepseek flash 9/10 @ $0.0076 — same price, +1 category; no delegation at medium). `evals/2026-10-23/RESULTS.md`. **ROSTER v2 — owner-validated 2026-11-17: cheap-design-review `medium`** unchanged (DR-v2 8.5/14 @ $0.04 on grid2, deciding bench DR-v2; escalation = minimax `xhigh`) **AND NOW ALSO strong-design-review `xhigh`** (deciding bench DR-v2 11-17 grid2: **11.5/14**, two-run mean 9;14, 4 executed proofs — the first proof-executing DR-v2 and the best design-review measured, $0.03/task; fallback gemini-4-carbon `high`, DR2 10). The dual seat is a real escalation this time: `medium` critique floor &rarr; `xhigh` depth, same family. Still critique-only (D mean 5, the 8→2 shape persists) |
| gemini-4-carbon | copilot | n.t. (DB-recorded costs) | n.t. | $0.52–1.01 (low→high) | 11-10 | full 4×3 grid — **no rung at its price** (owner decision 11-10): T4 **10/10-0FP at all 3 efforts** (2-run confirmed at `high`) and the kit's best-ever v2 score (**10/14**, 0 FP, `high`) — but +45–77% per task vs argon on the contested strong-design-review-alternative rung (+0.5 pt v2, within scoring noise), and its v1 effort-flatness **collapses on v2 at `low` (4/14, 1 FP)** — the cheap-effort option is dead. T3 2/3+2FP at 17–37× haiku (loses on both axes); T1 honest best-in-campaign baseline detection but static-only (never executes the suite) at 20–40× glm `high`; T2 PASS at 30–80× glm-flash. Kept as the **documented upgrade for the strong-design-review-alternative rung** if argon regresses (variance precedent: v1 10→8, v2 10→9). Full data: `evals/2026-11-10/RESULTS.md` |
| qwen3p8-max | fireworks | $2/$6 | $0.888 | $0.434 | 09-30-gw | best design-review depth measured (9/10) but **fabricated a green baseline on T1** — never an orchestrator; escalation depth only |
| fw-glm-5.3 (non-flash) | gateway | $1.14/$3.58 | $0.566 | $0.19 (`none`, 09-30) / $0.22–0.26 (`low`/`high`, 10-14) | 10-14 | still dominated after the full effort grid: ~10x flash's cost, `low` loses a review point (2/3+3), `high` T2 claimed-only (unverifiable dir); `high` T1 PASS does not buy a role. Note: opencode lowercases gateway ids — `FW-GLM-5.3` (catalog form) fails |
| grok-4-20-reasoning | gateway | $1.48/$4.44 | $0.629 | $0.225 | 09-30-gw | hallucinated repo structure on T1, wrong T3 mechanism — 9/10 T4 not enough |
| gpt-6-luna | gateway | $0.074/$0.37 | $0.039 | $0.015 | 09-30-gw | astonishingly cheap and clean, but shallow plans and 2/3 review — nothing it does beats glm-flash/deepseek at their jobs |
| gpt-6-sol | copilot | $2/$10 | $1.15 | $0.311 | 09-29 | replaced by gpt-6.1-sol (same price, strictly better) |
| kimi-k3 | copilot | $3/$15 | $1.58 | $0.283 | 09-29 | design/impl-capable, 2/3 as reviewer — never a review role; no slot pays its price |
| nemotron-lightning-3p5-30b-a3b | fireworks | $0.05/$0.20 | $0.028 | — | 09-30-nemotron | 5/12 degenerate loops — unreliable |
| gpt-5.6-terra | copilot | $2/$12 | $1.03 | $0.387 | 09-29 | dominated by sol |
| gpt-6.1-terra | copilot | n.t. | n.t. | $0.28 (4t avg, 10-26) | 10-26 | full grid: **strict quality-parity with sol at ~half price on every task** — T1 PASS all efforts ($0.044–0.047), T2 PASS (all delegated: cheap-mech + cheap-review children, $0.059–0.071), T3 2/3-0FP all efforts (seed-3 blind like sol; 4 verified bonuses at `xhigh`), T4 9–10/10-0FP (`medium` 10/10 @ $0.0388). **ROSTERED 10-26: strong-design-alternative + strong-code-alternative** (replaces sol). Never reaches T3 3/3 — no threat to haiku/1017/glm rungs. `evals/2026-10-26/RESULTS.md` |
| claude-fable-5.1 | copilot | $10/$50 | $4.69 | n.t. | 09-29 | too expensive |

## Rejected on price without a run

| Model | Provider | In/out $/MTok | Blended | Date seen | Re-entry condition |
|---|---|---|---|---|---|
| gpt-6-astra | gateway | $7.40/$37 | $3.89 | 2026-09-30 | drops below opus-5.5 ($4/$20) — it would then contend for the `deep` rung |

## Standing lessons (from all evals)

- Claude `low` effort skips reading code and hallucinates; `xhigh` never paid
  for itself; descending effort on opus via Copilot is not honored.
- The T1 red-baseline trap (execute the tests or miss it) has caught **every
  model ever tested**; qwen3p8-max is the only one that lied about it
  (qwen3p8-2p4t `low` hallucinated instead, 10-14; gemini-4-argon `high`
  dismissed the baseline as unrelated — a third failure shape, 10-14).
- Role-decided per-task costs (2026-10-15 methodology): a rung is decided
  on the task that rung performs — quality measured on that task, cost paid
  on that task. The 4-task total is a budget sanity-check only, never an
  arbiter: a model good on T1 and expensive there can lose on total to a
  model bad on T1 but cheap there, and the total would hide the
  role-relevant cost.
- Price over speed: when two models sit in the same quality tier, the
  cheaper one takes the role.
- `max` effort has never paid for itself — and on the flash-tier models
  (haiku-5.5: dead sessions / 32k reasoning with no output; deepseek: 4x cost
  and *lower* T3 recall) it actively breaks delivery. Cap flash-tier models
  at `xhigh`.
- Review lineage ≠ impl lineage, always.
- Effort is not monotone (full grids 10-14): glm-flash reviews best at `low`
  (3/3+2 0FP) and degrades at `high` (2 FP); deepseek `low` out-reviews its
  own `max` (10-07); sol is flat low→xhigh. Never assume more effort =
  more rigor — read the grid.
- Single-run arms are provisional: the minimax variance lesson (09-30)
  applies to every one-run cell in this page (10-14 arms included).
- Gateway ids are lower-cased by opencode (`FW-GLM-5.3` fails, documented
  10-14); a variant-less gateway request can be a hard server error
  (fw-deepseek-v4-pro, 10-14) — pin an explicit variant that exists. Gateway
  ids can also be RETIRED upstream (fw-deepseek-v4-pro, 11-16): probe with a
  1-token request before any campaign.
- Gemini-family arms can die silently: "Failed to process successful
  response" after real work, or a timeout with nothing written — a null run
  dir is infrastructure until proven otherwise (argon 4/4 nulls 11-16, valid
  scores on re-run; hydrogen 2 nulls). Re-run before recording 0.
- Sonnet D (design authoring on the hazard substrate) systematically exceeds a
  15-min watchdog — bench-v3 D arms need `EVAL_TIMEOUT_SECS=1800` for sonnet
  and opus; 15-min DNFs (p4 ×2, p5) are watchdog shape, not model failure.
- Review lineage ≠ impl lineage, always — and it now binds BOTH directions:
  cheap-code=haiku forced cheap-review out of claude (11-16 swap to glm `low`).

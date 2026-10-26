# Eval summary — all models ever tested

**THE single aggregate**: one place for the results of every model eval ever
run in this kit, blended across campaigns with the date each cell was
measured. The per-eval detail was folded in here and the per-date
`evals/` dirs removed (the current detail page is
`evals/2026-10-16/RESULTS.md` — the muse-spark grid campaign, organized by
test category; the 2026-10-14 campaign re-arbitration lives there too). **Checked: 2026-10-16.**

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
| glm-5p3-flash | fireworks (gateway id `fw-glm-5.3-flash`) | $0.15/$0.50 | $0.078 | $0.023 | 10-16 | impl/cheap-code at `high` (confirmed 10-16: T2 PASS 2/2, $0.0049–0.0056 avg $0.00525 < low's $0.0063; T1 PASS $0.0050 vs low's miss), cheap-design stays `low` (high T4 6/10 < 8/10, non-monotone); `high` = strong-review rung (10-07, re-confirmed 10-14: T1 PASS vs low's miss) — best deal in the grid |
| deepseek-v4p1-flash | fireworks | $0.22/$0.66 | $0.082 | $0.030 (`low`, 10-14) | 10-14 | explore, cheap-mech, cheap-design-review — cheapest, tier-1 plans; `low` viable budget arm (9/10 T4), default(=high) kept unpinned where quality matters |
| claude-haiku-5.5 | copilot | ~$0.75/$3.75 (claude-flash class) | ~$0.39 | $0.029 | 10-07 | cheap-review `default` — 3/3 at $0.0063, full 6-variant grid; `xhigh` = measured design-review at $0.018; never `max` (fails to deliver). **Long-context cliff (10-19)**: prompts >100k tokens pay 5× on every line (0.10→0.50 in, 0.01→0.05 cache read), per-request; 5.5% of our requests carry 22% of haiku spend — keep review prompts <90k, fallback = deepseek-v4p1-flash-1017 `medium` |
| deepseek-v4p1-flash-1017 | fireworks | n.t. (snapshot pricing) | n.t. | $0.058 | 10-19 | full 4×4 grid: **T4 10/10-0FP at every effort** ($0.014–0.017, first sweep), T3 **3/3-0FP at `medium` only** ($0.0233, non-monotone), T1 PASS medium+ ($0.015–0.026), **`low` T1 FAIL (invented green baseline — worse than old flash)**; ~1.6–2× old flash per task. **ROSTERED 10-19: strong-design-review `medium`** (replaces sol, owner decision — best model×effort×price per task, 4th lineage); documented fallback: >100k review (haiku cliff). `evals/2026-10-19/RESULTS.md` |
| claude-sonnet-5.5 | copilot | $2/$10 | $0.975 | $0.52 | 09-29 | strong-code/design `high`, review alternatives `medium` — best reviewer of its price class. 10-08: cache-read price cut $0.20 → $0.10/MTok, blended recomputed: $0.975 |
| claude-opus-5.5 | copilot | $4/$20 | $1.95 | $1.03 | 09-29 | deep + alternative2 rungs — max depth |
| gpt-6.1-sol | copilot | $2/$10 | $0.975 | $0.35 (`low`, 10-14) | 10-14 | **OFF the roster (10-26)** — strong-design-review lost to 1017 `medium` (10-19), then both alternative rungs lost to gpt-6.1-terra (strict quality parity at ~50% cost, T4-medium 10/10 vs 9/10); documented fallback if terra regresses |
| qwen3p8-2p4t-a95b | fireworks | $2/$6 | $0.888 | $0.43 (`xhigh`) | 09-30 | strong-review-alternative2 `xhigh` — best review ever measured (3/3+2 proven, $0.151), the rung stays; `low`: unstable recall across runs (3/3 then 2/3) — out for review roles (variance confirmed 10-14); `medium` re-tested 10-14 |
| fw-deepseek-v4-pro | gateway | $1.42/$2.83 | $0.513 | $0.20 | 09-30 | strong-design-review-alternative2 `high` — qwen-tier design-review at $0.047–0.058; no-variant arm is a dead gateway server error (10-14), keep `high` |

## Tested and kept out (reasons recorded)

| Model | Provider | In/out $/MTok | Blended | Cost/4t | Eval | Why out |
|---|---|---|---|---|---|---|
| muse-spark | fireworks | $1.25/$4.25 | $0.575 | $0.39–0.52 | 10-16 | full 4×4 grid — **no rung won**: T3 clean 3/3 0FP at all efforts but a quality-tie with haiku at 15–19× the per-run cost ($0.09–0.12 vs $0.0063); T4 9/10 0FP (`medium`/`xhigh`) tied with argon `high` in the same price class; T1 passes only at `high` ($0.174, 2× sol's $0.092–0.097) and `xhigh` **invents a green baseline**. Effort non-monotone on this model (T1 xhigh < high; T4 high 6/10 < low 7/10). Documented fallback for the strong-review-alternative rung if sonnet-5.5 leaves |
| gemini-4-argon | copilot | n.t. (Copilot rate) | n.t. | $0.34–0.37 | 10-14 | capable generalist — `high` T4 now **9/10 avg over 2 runs** (10, 8; confirmation run 10-14), only campaign T2 semantic fix. Upgraded: confirmed candidate for the strong-design-review-alternative rung (currently sonnet-5.5 medium, ~$0.52/4t) at ~$0.09/task and one more distinct lineage — PENDING OWNER DECISION. Review floor otherwise stays haiku (3/3 0FP $0.0063 vs argon low 3/3 1FP) |
| ember-1 | fireworks | n.t. (partial grid) | n.t. | $0.56 | 10-07 | mid-grid quality (T3 3/3, T4 6.5/10) at sonnet-class price; no role it could win — dominated by glm/deepseek/haiku |
| grok-4.7 | copilot | $2/$6 | $1.08 | $0.285 | 09-29 | good reviewer (3/3+2, no proofs) but priced out by qwen/pro; kept as documented fallback for the alternative2 rungs |
| minimax-m3 | fireworks | $0.30/$1.20 | $0.165 | $0.094 | 09-30-gw | failed confirmation: T3 recall 3/3 → 1/3 (+1 FP) → 3/3 across 3 runs — high variance disqualifies a review-floor role; haiku holds the floor |
| minimax-m3p1-flash | fireworks | n.t. | n.t. | $0.075 | 10-23 | full 4×4 grid: **M3's variance fixed** — T3 3/3-0FP at low/medium/high ($0.0068–0.0107), 2/3-0FP xhigh (floor 1/3 → 2/3); T4 10/10-0FP at medium+ ($0.0077+, xhigh measured a 50k-file benchmark); T1 PASS low/high/xhigh, PARTIAL medium (non-monotone again); T2 PASS but **delegates 3 of 4 efforts** (deepseek cheap-mech + haiku cheap-review — costs double-counted per the new delegation rule). **ROSTERED 10-23: cheap-design-review `medium`** (confirmation 3 runs: 10/10 avg @ $0.0082, replaces old deepseek flash 9/10 @ $0.0076 — same price, +1 category; no delegation at medium). `evals/2026-10-23/RESULTS.md` |
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
  (fw-deepseek-v4-pro, 10-14) — pin an explicit variant that exists.

# Model eval results — 2026-10-16 (muse-spark grid; complete report by test category)

Standalone report — supersedes `../2026-10-15/RESULTS.md` (which re-arbitrated
the 10-14 campaign under the per-task cost methodology; no verdict changes
there). This campaign ran the **full effort×task grid for `muse-spark`**
(Fireworks, released 2026-10-15): 4 tasks × 4 efforts = 16 arms, 16/16
priced, zero relaunch duplicates (`done.txt`, `costs.json`, `sessions/`).

**Model card**: muse-spark (open) on Fireworks — $1.25 in / $4.25 out per
MTok, **blended $0.575** with our token mix (0.20·in + 0.75·cache + 0.05·out),
1M context, image input.

**Headline: no rung won.** Quality ties exist on T3 and T4, but every tie is
at a multiple of the incumbent's per-task cost, and T1 only passes at `high`
at 2× sol's price. Grid verdicts per category below.

Costs are the per-arm, per-task cost paid (`costs.json`, keyed by session
title). Prior campaigns' per-task costs are reused from
`../2026-10-15/RESULTS.md` (10-14 grid) — older campaigns archived totals
only and stay marked `n.t.`

---

## T1 — Orchestration

The task: a grounded plan (file:line), correct pipeline agents, verifiable
criteria, zero hallucination — and the seeded trap: a **pre-existing red
baseline** (`test_synccli.py:22-24` fails against `synccli.py:55`) that only
a run which *executes the tests* sees.

| Arm | Date | T1 cost / run | T1 verdict |
|---|---|---|---|
| gpt-6.1-sol `low` | 10-14 | $0.0971 | PASS |
| gpt-6.1-sol `medium` | 10-14 | $0.0922 | PASS |
| gpt-6.1-sol `xhigh` | 10-14 | $0.0917 | PASS |
| fw-glm-5.3-flash `high` | 10-14 | $0.0050 | PASS (only flash arm that executes the tests) |
| fw-glm-5.3-flash `low` | 10-14 | $0.0053 | PARTIAL (misses red baseline) |
| gemini-4-argon `medium` | 10-14 | $0.0922 | PASS |
| gemini-4-argon `low`/`high` | 10-14 | $0.0874/$0.0995 | PARTIAL (`high` dismisses the baseline as unrelated) |
| qwen3p8 `medium` | 10-14 | $0.1010 | PASS |
| qwen3p8-max | 09-30 | n.t. | fabricated a green baseline — never an orchestrator |
| fw-deepseek-v4-pro `high` | 09-30 | n.t. | baseline caught |
| sonnet-5.5 `high` | 09-29 | n.t. | best plan (tier-1) |
| opus-5.5 `default` | 09-29 | n.t. | tier-1 |
| **muse-spark `low`** | **10-16** | **$0.0887** | **PARTIAL** — never executes the suite; plans `unittest` "passing" without noting the red baseline |
| **muse-spark `medium`** | **10-16** | **$0.0662** | **PARTIAL** — same shape; plans "passes with current 5 tests", red baseline undetected |
| **muse-spark `high`** | **10-16** | **$0.1739** | **PASS** — executes the tests, flags the pre-existing failure (`test_synccli.py:22-24` vs `synccli.py:55`), marks defect surface out-of-scope |
| **muse-spark `xhigh`** | **10-16** | **$0.1038** | **FAIL** — **invents a green baseline** ("7 tests pass green"); the qwen3p8-max failure shape |

**T1 eval verdict: gpt-6.1-sol wins the planning rung** — PASS at every effort
@ ~$0.092–0.097/run. Spark's only PASS is at `high` @ $0.174 — 2× sol's cost
for the same verdict. Spark's `xhigh` hallucinating a green baseline repeats
the qwen3p8-max lesson (effort does not buy honesty). This is an eval-rung
result only: deployed orchestration is the session default model, glm-flash
(`MODELS.md` orchestration row) — T1 measures plan quality, not the deployed
role.

**The deployed default as orchestrator — glm-flash, price × quality** (the
owner runs glm as session default regardless of the eval pick; both T1 arms
from 10-14, single run each):

| glm arm | T1 cost / run | T1 verdict | vs sol `low` ($0.0922 PASS) |
|---|---|---|---|
| glm-flash `high` | $0.0050 | PASS — the only flash arm that executes the tests | **18× cheaper, same verdict** |
| glm-flash `low` | $0.0053 | PARTIAL — misses the red baseline | cheaper, wrong verdict |

Read: as an orchestrator, glm-flash is competitive **only effort-pinned to
`high`** — at `low` it under-explores and misses the trap, exactly the
README's `low`-effort failure mode (structural under-exploration on T1). At
`high` it delivers the same PASS verdict as sol at 5% of the cost, so the
deployed choice (glm default) is defensible on price × quality; sol's edge
is robustness across efforts (PASS low→xhigh, no pinning needed), not the
verdict itself.

## T2 — Impl

Objective scoring: `python3 -m unittest` green + size/minimalism of the fix
(the seeded off-by-one in `collect_stale`, `synccli.py:55`).

| Arm | Date | T2 cost / run | T2 verdict |
|---|---|---|---|
| fw-glm-5.3-flash `low` | 10-14 | $0.0063 | ✅ PASS |
| fw-glm-5.3-flash `high` | 10-14 | $0.0049 | ✅ PASS |
| fw-deepseek-v4.1-flash `low` | 10-14 | $0.0066 | ✅ PASS |
| **muse-spark `low`** | **10-16** | **$0.1179** | ✅ PASS — 6/6 green, minimal one-line fix |
| **muse-spark `medium`** | **10-16** | **$0.1276** | ✅ PASS — same |
| **muse-spark `high`** | **10-16** | **$0.1247** | ✅ PASS — same (delegated to a Cheap-Mech subagent — see Ops notes) |
| **muse-spark `xhigh`** | **10-16** | **$0.1268** | ✅ PASS — same (also via Cheap-Mech subagent) |
| qwen3p8 `low`/`medium` | 10-14 | $0.1017/$0.0984 | ✅ PASS |
| gemini-4-argon `low`–`high` | 10-14 | $0.085–0.092 | ✅ PASS (`high` = the only campaign semantic fix) |
| sonnet-5.5 / opus-5.5 / haiku / qwen `xhigh` / deepseek default | 09-29/10-07/09-30 | n.t. | ✅ PASS |

**Eval verdict: fw-glm-5.3-flash `low` — confirmed as deployed cheap-code** — suite-verified PASS
@ $0.005–0.006/run vs spark $0.12 and qwen $0.10: a **20× spread** for the
identical objective outcome. Deepseek `low` ($0.0066) is the explore/cheap-mech
arm on the same tier. No challengers.
*Family/lineage note (standing rule, re-confirmed):* the reviewer must not be
of the impl's lineage — spark impl would need a non-spark reviewer regardless
of its T2 cost.

## T3 — Code review

3 seeded defects in `incremental.py`: (1) mutable default arg, (2) silent
copy failure → lying `done`, (3) `merge_manifest` never purges deletions.
Scored n/3, bonus findings, **false positives counted**.

| Arm | Date | T3 cost / run | T3 verdict |
|---|---|---|---|
| claude-haiku-5.5 `default` | 10-07 | **$0.0063** | **3/3, 0 FP** — the floor |
| fw-glm-5.3-flash `low` | 10-14 | $0.0051 | 3/3 +2 bonus, 0 FP (1-run provisional) |
| fw-glm-5.3-flash `high` | 10-14 | $0.0057 | 3/3 +2, **2 FP** (degrades) |
| qwen3p8 `xhigh` | 09-30 | n.t. ($0.151/4t) | **3/3 +2 proven** (multi-run) |
| claude-sonnet-5.5 `medium` | 09-29 | n.t. | best reviewer of its price class |
| qwen3p8 `low` | 10-14 | $0.0657 | variance: 3/3+2 then 2/3 — out for review roles |
| gemini-4-argon `low` | 10-14 | $0.1238 | 3/3, 1 FP |
| **muse-spark `low`** | **10-16** | **$0.1060** | **3/3, 0 FP** (+EXCLUDE_TOP_DIRS noted, self-downgraded to non-defect) |
| **muse-spark `medium`** | **10-16** | **$0.1240** | **3/3, 0 FP** +2 bonus (EXCLUDE_TOP_DIRS, mtime-only) |
| **muse-spark `high`** | **10-16** | **$0.1199** | **3/3, 0 FP** +2 bonus (same two, both correct) |
| **muse-spark `xhigh`** | **10-16** | **$0.0900** | **3/3, 0 FP** +2 bonus (same, EXCLUDE_TOP_DIRS as minor) |

**Eval verdict: haiku-5.5 `default` keeps the review floor** (deployed
cheap-review — confirmed) — spark is a clean
**quality tie (3/3, 0FP at all four efforts)** at **15–19× the per-run cost**
($0.09–0.12 vs $0.0063). glm-flash `low` remains the cheaper floor contender
(provisional, single run). Qwen `xhigh` keeps the proven-depth rung; sonnet-5.5
(09-29) stays best-in-class reviewer of its price class.

## T4 — Design review

~10 flaw categories seeded in `DESIGN.md` (non-atomic manifest, 50k/500ms
polling, mtime-only, mid-write copies, swallowed errors, blocking single
thread, undefined deletions/renames, no instance lock, hardcoded config,
`sync()` reuse). Scored categories covered, mechanical depth, zero FP.

| Arm | Date | T4 cost / run | T4 verdict |
|---|---|---|---|
| fw-deepseek-v4.1-flash `low` | 10-14 | **$0.0076** | **9/10** — dominates the rung on cost |
| gemini-4-argon `high` | 10-14 | $0.0879 | **9/10 avg over 2 runs** (10, 8) — holds the strong rung |
| gemini-4-argon `medium` | 10-14 | $0.0898 | 9/10 — alternative-rung candidate |
| **muse-spark `medium`** | **10-16** | **$0.0890** | **9/10, 0 FP** — STOP verdict, all pillars challenged |
| **muse-spark `xhigh`** | **10-16** | **$0.0759** | **9/10, 0 FP** |
| **muse-spark `low`** | **10-16** | **$0.0804** | **7/10** |
| **muse-spark `high`** | **10-16** | **$0.0993** | **6/10** — the effort anomaly, see below |
| qwen3p8 `xhigh` | 09-30 | n.t. | **10/10 proven** — best T4 ever measured |
| fw-deepseek-v4-pro `high` | 09-30 | n.t. ($0.047–0.058 claim) | 9–10/10 |
| gemini-3.8-flash `medium` | 10-14 | $0.0405 | 9/10 — **out**: deepseek `low` gives 9/10 @ $0.0076 |
| haiku-5.5 `xhigh` | 10-07 | n.t. ($0.018 design run) | 9/10 |
| sonnet-5.5 `medium` | 09-29 | n.t. (~$0.52/4t) | tier-1 — current strong-design-review slot |

**Eval verdict: argon `high` ties sol on T4** (9/10 avg @ $0.088). The
deployed rung is **unchanged: `strong-design-review` = gpt-6.1-sol**
(`models.json` — deliberate, commit `a5f8a6e`); argon `high` sits at
`-alternative` as a candidate to move up, **PENDING OWNER DECISION**
(`EVALS.md` argon row). Spark `medium`/`xhigh` tie both at 9/10 0FP in the
same price class ($0.076–0.089) — a tie is not a win under the per-task rule
(price over speed only breaks ties in the cheaper model's favor; there is no
tie to break).
Qwen `xhigh` (10/10 proven) and deepseek-pro `high` (09-30) keep their rungs;
gemini-3.8 `medium` stays out — deepseek `low` 9/10 @ $0.0076 dominates.

---

## Roster (current — unchanged by this campaign)

The deployed roster is the repo's chosen config (`models.json` + `MODELS.md`
grid), decided after prior campaigns; eval verdicts above recommend, the
config decides. Each rung: model@effort, the T-task evidence backing it,
per-task cost where measured.

| Rung | Model @ effort | Evidence | Cost / task |
|---|---|---|---|
| orchestration (deployed) | **session default: fw-glm-5.3-flash** (`high` pin recommended) | session config, outside the kit (`MODELS.md` orchestration row); T1: PASS @ `high` $0.0050 (18× sol's price), PARTIAL @ `low` — see §T1 comparison | $0.0050 (`high`, 10-14) |
| T1 planning rung (eval) | gpt-6.1-sol `low` | T1 PASS at all efforts (10-14) | $0.092–0.097 |
| strong-review | fw-glm-5.3-flash `high` | T1 PASS, the only flash arm that executes tests (10-14) | $0.0050 |
| strong-review-alternative | claude-sonnet-5.5 `medium` (deployed, `models.json`) | best reviewer of its price class (09-29) | n.t. |
| strong-review-alternative2 | qwen3p8 `xhigh` (deployed, `models.json`); grok-4.7 documented fallback (no-qwen whitelists) | T3 3/3+2 proven by execution (09-30) | n.t. |
| strong-code | sonnet-5.5 `high`; opus-5.5 `default` deep | T2 PASS tier-1 (09-29) | n.t. |
| strong-design | sonnet-5.5 `high` (deployed, `models.json`); sol → opus escalades | T4/plan tier-1 (09-29) | n.t. |
| strong-code-alternative | gpt-6.1-sol | T2 PASS (10-14) | $0.082–0.098 |
| strong-design-review | **gpt-6.1-sol** (deployed, `models.json`) | deliberate pick, commit `a5f8a6e`; T4 9/10 all efforts (10-14) | $0.076–0.085 |
| strong-design-review-alternative | **gemini-4-argon `high`** | T4 9/10 avg 2 runs (10-14) — candidate to move up, PENDING OWNER DECISION | $0.088 |
| strong-design-review-alternative2 | fw-deepseek-v4-pro `high` | T4 9–10/10 (09-30) | n.t. |
| cheap-code / cheap-design | **fw-glm-5.3-flash `low`** | T2 PASS suite-verified (10-14) | $0.0063 |
| cheap-mech | **fw-deepseek-v4.1-flash** (deployed, `models.json`) | T2 PASS (10-14) | $0.0066 |
| explore / cheap-design-review | **fw-deepseek-v4.1-flash `low`** | T2 PASS, T4 9/10 (10-14) | $0.0066–0.0076 |
| cheap-review | **claude-haiku-5.5 `default`** | T3 3/3 0FP (10-07) | $0.0063 |
| design-review (cheap) | fw-glm-5.3-flash `low` / haiku `xhigh` | T4 8/10 (10-14) / 9/10 @ $0.018 (10-07) | $0.0059 |

**muse-spark roster verdict: NOT rostered — no rung won.** T3 quality-tie
with haiku at 15–19× the per-run cost; T4 tied with argon at the same price
class; T1 passes only at `high` @ $0.174 (2× sol). Documented fallback for
`strong-review-alternative` if sonnet-5.5 leaves the fleet — nothing more.

## Standing verdicts on new models

- **muse-spark** (Fireworks, released 2026-10-15; $1.25/$4.25, blended
  $0.575, 1M ctx, image input) — full 4×4 grid 10-16:
  - T1: PARTIAL (`low` $0.0887, `medium` $0.0662 — red baseline never seen),
    PASS (`high` $0.1739), **FAIL (`xhigh` $0.1038 — invented a green
    baseline)**.
  - T2: PASS all efforts ($0.118–0.128), minimal fix, suite green.
  - T3: **3/3, 0 FP at all four efforts** ($0.090–0.124) — genuinely good
    reviewer, hopelessly priced for the floor.
  - T4: 7/10 (`low`), **6/10 (`high`)**, 9/10 0FP (`medium` $0.0890,
    `xhigh` $0.0759).
  - **No rung won.** Kept out; see `../../EVALS.md`.
- **Effort anomaly on spark — non-monotone, twice**: T1 `xhigh` hallucinates
  a baseline the `high` run caught; T4 `high` (6/10) scores *below* `low`
  (7/10). Reinforces the standing rule: **never trust effort monotonicity —
  read the grid.**

## Methodology (per-task decision rule, from 2026-10-15 — unchanged)

**A rung is decided on the task that rung performs: quality measured on that
task, cost paid on that task. The 4-task total is a budget sanity-check
only, never an arbiter.**

Sanity check only: spark's 4-task totals are $0.39 (`low`), $0.41 (`medium`),
$0.52 (`high`), $0.40 (`xhigh`) — mid-pack, and irrelevant to every decision
above. The motivating counterexample stands: spark T1 `medium` ($0.0662,
PARTIAL) is cheaper than sol T1 ($0.0922, PASS) — a total-based view would
credit spark for an orchestrator role it cannot hold, while its T3/T4 costs
(hundreds of × haiku's floor) would simultaneously hide its genuine review
quality.

## Ops notes

- **10-16 campaign was clean**: 16/16 arms ran once and priced
  (`done.txt`, `costs.json`), zero relaunch duplicates.
- **Duplicated arms ~$2 waste (10-14, carried)** — harness relaunch artifact;
  the dedupe rule (min of priced copies) is documented in
  `../2026-10-15/RESULTS.md`.
- **Gateway id lowercasing (10-14, carried)**: catalog `FW-GLM-5.3` is
  rejected — opencode lowercases gateway ids.
- **pro no-variant arm dead (10-14, carried)**: `fw-deepseek-v4-pro` without
  a variant is a gateway server error ×3 — always pin an existing variant.
- **Protocol-relevant behavior to watch — spark delegated T2 work**: on
  T2 `high` and `xhigh`, muse-spark spawned a **Cheap-Mech subagent** to do
  the mechanical fix instead of editing directly. The eval harness scores the
  session outcome, so the scores stand, but a model that delegates
  opportunistically inside an eval is optimizing the same way it would in a
  pipeline — worth watching on the next campaign (it also means "model
  behavior" cells can silently include a second model's labor).

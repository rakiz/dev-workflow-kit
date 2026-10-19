# Model eval results — 2026-10-19 (deepseek-v4p1-flash-1017 full grid; MiMo-V2.6-Pro unavailable)

Complete report by test category. This campaign ran the **full effort×task
grid for `deepseek-v4p1-flash-1017`** (Fireworks, released 1017 snapshot of
deepseek-v4.1-flash): 4 tasks × 4 efforts = 16 arms (one duplicated T2-low
run — dedupe rule: min of priced copies), 17/17 priced, zero failures.
Evidence: `costs-1017.tsv`, `sessions/`, opencode session titles
`eval-2026-10-19-*`. Method: subagent-scored against the seeded traps,
T2 re-executed objectively (`python3 -m unittest` in each run dir).

**Comparison baseline**: prior campaigns' results are restated alongside
(each table carries the old arms). Prior reports:
`../2026-10-16/RESULTS.md` (muse-spark grid), `../2026-10-15/RESULTS.md`
(methodology), `../../EVALS.md` (aggregate).

**MiMo-V2.6-Pro: NOT available** — no id on the AI Gateway catalog nor on
Fireworks (`opencode models` checked 2026-10-19). Re-check when a provider
ships it.

**Headline: 1017 buys quality with ~1.6–2× the old flash's per-task cost.**
T4 10/10-0FP at every effort (first model ever to sweep T4), T3 3/3-0FP at
`medium` (the only deepseek arm ever to find all three defects), T1 PASS at
medium+ — but `low` T1 **regressed below the old flash** (invented a green
baseline).

---

## T1 — Orchestration

Trap: pre-existing red baseline (`collect_stale` off-by-one, `synccli.py:55`;
`test_first_item_stale_is_included` fails). Only a run that *executes the
tests* sees it.

| Arm | Date | T1 cost / run | T1 verdict |
|---|---|---|---|
| gpt-6.1-sol `low`–`xhigh` | 10-14 | $0.0917–0.0971 | PASS (all efforts) |
| fw-glm-5.3-flash `high` | 10-14 | $0.0050 | PASS (low = PARTIAL) |
| **1017 `low`** | **10-19** | **$0.0160** | **FAIL** — assumed green baseline, never ran unittest, mislocated the bug in `incremental.py` and dismissed it "out of scope" |
| **1017 `medium`** | **10-19** | **$0.0264** | **PASS** — ran baseline, flagged the pre-existing failure, dedicated repair task with unittest acceptance |
| **1017 `high`** | **10-19** | **$0.0161** | **PASS** — ran baseline ("6 tests, 1 FAIL … synccli.py:55"), T0 gate + green-baseline restore task |
| **1017 `xhigh`** | **10-19** | **$0.0154** | **PASS** — ran baseline, out-of-scoped the repair explicitly |
| old fw-deepseek-v4.1-flash `low` | 10-14 | $0.0080 | PARTIAL |

**Eval verdict**: 1017 `xhigh` passes at **$0.0154 — 6× cheaper than sol**,
with explicit trap handling. `low` is a hard fail (the invented-green-baseline
shape — second model family to show it after qwen3p8-max). glm-flash `high`
($0.0050) remains the cheapest PASS but is effort-fragile (`low` misses the
trap).

## T2 — Impl

Objective scoring: `python3 -m unittest` green, minimal fix to the seeded
off-by-one, test file untouched.

| Arm | Date | T2 cost / run | T2 verdict |
|---|---|---|---|
| fw-glm-5.3-flash `high` (deployed cheap-code) | 10-14 + 10-16 ×2 | $0.0049–0.0056 | ✅ PASS (3 runs) |
| old deepseek-v4.1-flash `low` (deployed explore/cheap-mech) | 10-14 | $0.0066 | ✅ PASS |
| **1017 `low`** | **10-19** | **$0.0107** | ✅ PASS — 6/6 green, one-line fix |
| **1017 `medium`** | **10-19** | **$0.0132** | ✅ PASS — same |
| **1017 `high`** | **10-19** | **$0.0104** | ✅ PASS — same |
| **1017 `xhigh`** | **10-19** | **$0.0122** | ✅ PASS — same |
| qwen3p8 / argon / spark | 09-29–10-16 | $0.085–0.128 | PASS |

**Eval verdict**: effort-insensitive (all four pass). **glm-flash `high`
keeps cheap-code** at half 1017's cheapest price; **old flash keeps
explore/cheap-mech** ($0.0066 vs $0.0107).

## T3 — Code review

3 seeded defects in `incremental.py`: (1) mutable default arg, (2) silent
copy failure → lying `done`, (3) `merge_manifest` never purges deletions.

| Arm | Date | T3 cost / run | T3 verdict |
|---|---|---|---|
| claude-haiku-5.5 `default` (deployed cheap-review) | 10-07 | **$0.0063** | **3/3, 0 FP** — the floor |
| qwen3p8 `xhigh` | 09-30 | n.t. | **3/3 +2 proven** |
| old deepseek-v4.1-flash `low` | 10-14 | $0.0074 | 2/3, 0 FP |
| **1017 `low`** | **10-19** | **$0.0141** | **2/3, 0 FP** — missed purge-on-delete |
| **1017 `medium`** | **10-19** | **$0.0233** | **3/3, 0 FP +2 bonus** — the only deepseek arm ever to find all three (execution-verified) |
| **1017 `high`** | **10-19** | **$0.0254** | 2/3, 0 FP — missed purge-on-delete |
| **1017 `xhigh`** | **10-19** | **$0.0254** | 2/3, 0 FP — same |
| spark (all efforts) | 10-16 | $0.090–0.124 | 3/3, 0 FP |
| glm-flash `high` | 10-14 | $0.0057 | 3/3 +2, 2 FP |
| argon `low` | 10-14 | $0.1238 | 3/3, 1 FP |

**Eval verdict**: `medium` is a **non-monotone island** — the only effort
that finds defect #3. At $0.0233 it is 3.7× haiku's floor: haiku keeps
cheap-review, but 1017 `medium` becomes the **big-context review fallback**
(no >100k price cliff — see the haiku 5× long-context note, MODELS.md).

## T4 — Design review

~10 flaw categories seeded in `DESIGN.md`.

| Arm | Date | T4 cost / run | T4 verdict |
|---|---|---|---|
| fw-deepseek-v4-pro `high` | 09-30 | n.t. | 9–10/10 |
| qwen3p8 `xhigh` | 09-30 | n.t. | **10/10 proven** |
| old deepseek-v4.1-flash `low` (deployed design-review) | 10-14 | **$0.0076** | 9/10 |
| gemini-4-argon `high` (deployed alternative) | 10-14 | $0.0879 | 9/10 avg (2 runs) |
| **1017 `low`** | **10-19** | **$0.0156** | **10/10, 0 FP +bonus** — measured a 1.2s scan disproving the 500ms claim |
| **1017 `medium`** | **10-19** | **$0.0143** | **10/10, 0 FP +bonus** — cheapest 10/10 |
| **1017 `high`** | **10-19** | **$0.0160** | **10/10, 0 FP +bonus** |
| **1017 `xhigh`** | **10-19** | **$0.0168** | **10/10, 0 FP +bonus** — "don't write syncd against this doc" |
| spark `medium`/`xhigh` | 10-16 | $0.0759–0.0890 | 9/10, 0 FP |
| gemini-3.8 `medium` | 10-14 | $0.0405 | 9/10 — dominated |

**Eval verdict**: **first model to sweep T4 at every effort, zero FP** —
at $0.014–0.017, i.e. qwen `xhigh`'s proven depth at ~10–30% of its cost.
Old flash keeps the cheap rung (9/10 @ $0.0076); 1017 `medium` is the
strongest design-review candidate measured.

---

## Roster impact (proposals — owner decides, config decides)

| Rung | Deployed | 1017 finding | Proposal |
|---|---|---|---|
| cheap-code / impl | glm-flash `high` ($0.0053 avg) | 1017 PASS all efforts @ $0.0104+ | **keep glm** (2× pricier, no quality gain) |
| explore / cheap-mech | old flash `low` ($0.0066) | 1017 @ $0.0107 | **keep old flash** |
| cheap-review | haiku `default` ($0.0063, 3/3 0FP) | 1017 `medium` 3/3 0FP @ $0.0233, no 100k cliff | **keep haiku**; **document 1017 `medium` as the >100k review fallback** (haiku pays 5× past 100k prompt) |
| design-review (cheap) | old flash `low` (9/10 @ $0.0076) | 1017 `medium` 10/10 @ $0.0143 | owner call: 2× price for the extra category + bonuses |
| T1 planning rung (eval) | gpt-6.1-sol ($0.092) | 1017 `xhigh` PASS @ $0.0154 (6× cheaper) | **candidate to take the eval rung** — single run, needs confirmation if adopted; deployed orchestration unchanged (session default) |
| strong-design-review | gpt-6.1-sol (deployed) | 1017 `medium` 10/10-0FP @ $0.0143 vs sol 9/10 @ $0.076 | **candidate — pending owner decision** (would also add a 4th lineage to the grid) |

## Standing verdicts on new models

- **deepseek-v4p1-flash-1017** (Fireworks, 1017 snapshot) — full 4×4 grid
  10-19:
  - T1: FAIL (`low` — invented green baseline, worse than old flash's
    PARTIAL), PASS (`medium` $0.0264, `high` $0.0161, `xhigh` $0.0154).
  - T2: PASS all efforts ($0.0104–0.0132), minimal fix.
  - T3: 2/3 0FP (`low`/`high`/`xhigh`), **3/3 0FP+2 at `medium` only**
    ($0.0233) — non-monotone island, echoes the qwen `low` variance lesson.
  - T4: **10/10 0FP at all four efforts** ($0.0143–0.0168) — first sweep
    ever measured.
  - **Rostered: not yet.** Two candidates pending owner decision (T1 eval
    rung, strong-design-review); documented fallback for big-context review.
  - Cost note: ~1.6–2× the old v4.1-flash per task at matched effort.
- **MiMo-V2.6-Pro** — unavailable (no gateway/Fireworks id, 2026-10-19).
- **Haiku 5.5 long-context cliff (documented 10-19)**: prompts >100k tokens
  pay 5× on every price line ($0.10→0.50 in, $0.50→2.50 out, cache read
  $0.01→0.05); each request is priced on its own prompt length including
  cache reads. Measured: 5.5% of our haiku requests exceeded 100k, carrying
  22% of haiku spend — all in long review sessions. Rule: keep cheap-review
  prompts under ~90k (delta reviews); 1017 `medium` is the cliff-free
  fallback for big reviews.

## Methodology (unchanged)

Per-task decision rule (2026-10-15): a rung is decided on the task that rung
performs — quality measured on that task, cost paid on that task; the
4-task total is a sanity check only. Full effort×task grid before adoption.
Review lineage ≠ impl lineage. Eval verdicts recommend, `models.json`
decides.

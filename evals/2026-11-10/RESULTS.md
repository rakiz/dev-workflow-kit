# gemini-4-carbon — full effort×task grid (2026-11-10)

**Status: DRAFT — owner review pending; NO roster change made**

Campaign: 12 arms (4 tasks × 3 efforts) on `github-copilot/gemini-4-carbon`, mirroring
gemini-4-argon's 10-14 grid. Harness: `evals/run-eval.sh`, fresh fixture copy per arm,
no timeouts (longest arm 6.1 min, T2-high at 363 s).

Efforts exposed by carbon (verified via `opencode models --verbose`, `variants` block):
**exactly `low` / `medium` / `high`** — same set as argon; no xhigh/max exists for this model.
(Note: the models *cache* at `~/.cache/opencode/models.json` was stale — it still lacked
carbon entirely; the live `opencode models --verbose` output is the source of truth here.)

**Cost note (deviation from the brief):** unlike the 10-14 assumption, Copilot models no
longer record as $0.00 in `opencode.db` — carbon's sessions carry real recorded costs
(catalog rate $2/$10 in/out, $0.10/MTok cache read — identical to argon's catalog rates).
All costs below are the **recorded DB values, no approximation applied**; comparison with
argon's 10-14 numbers is apples-to-apples. Per the delegation rule (2026-10-23): each
arm's cost = parent + ALL child sessions (children listed per arm, each named).

## 1. The carbon matrix

Scores (v1 rubric, same as every row in `EVALS.md`): T1 = grounded plan + red-baseline
trap + pipeline agents + zero hallucination; T2 = suite green by execution in the run dir;
T3 = n/3 seeded defects + FP count; T4 = n/10 flaw categories, FPs noted (v1 fixture
`synccli-eval-repo`, not v2 — never compared across benches).

| Model | Effort | T1 | T2 | T3 | T4 | T1 $ | T2 $ | T3 $ | T4 $ | Date |
|---|---|---|---|---|---|---|---|---|---|---|
| gemini-4-carbon | low | PASS (static baseline detect — see §3) | PASS (delegated) | 2/3+2, 2FP | **10/10, 0FP** | .1010 | .1746 | .1119 | .1271 | 11-10 |
| gemini-4-carbon | medium | PASS (static baseline detect) | PASS (delegated) | 2/3+2, 2FP | **10/10, 0FP** | .1554 | .1455 | .2059 | .1179 | 11-10 |
| gemini-4-carbon | high | PASS (static baseline detect) | PASS (delegated) | 2/3+2, 2FP | **10/10, 0FP** | .2086 | .4064 | .2356 | .1552 | 11-10 |

Per-arm detail (parent + children, per the delegation rule; T1 had no children):

| Arm | Cost (total) | Parent | Children (model@effort) | In tok | Out tok | Cache read | Duration |
|---|---|---|---|---|---|---|---|
| T1 high | $0.2086 | $0.2086 | — | 35,974 | 13,099 | 56,347 | 220 s |
| T1 medium | $0.1554 | $0.1554 | — | 35,483 | 7,886 | 55,874 | 154 s |
| T1 low | $0.1010 | $0.1010 | — | 35,097 | 2,527 | 55,639 | 66 s |
| T2 low | $0.1746 | $0.1617 | cheap-mech (fw-deepseek-v4.1-flash default) $0.0064 + cheap-review (haiku-5.5 default) $0.0066 | 69,399 | 1,123 | 116,621 | 84 s |
| T2 high | $0.4064 | $0.3949 | cheap-code (fw-glm-5.3-flash high) $0.0051 + cheap-review (haiku-5.5) $0.0065 | 66,429 | 23,677 | 252,441 | 363 s |
| T2 medium | $0.1455 | $0.1343 | cheap-code (fw-glm-5.3-flash high) $0.0055 + cheap-review (haiku-5.5) $0.0057 | 45,443 | 2,563 | 178,137 | 117 s |
| T3 medium | $0.2059 | $0.1984 | cheap-review (haiku-5.5) $0.0074 | 33,804 | 11,518 | 156,516 | 284 s |
| T3 high | $0.2356 | $0.2293 | cheap-review (haiku-5.5) $0.0063 | 40,939 | 13,557 | 118,504 | 249 s |
| T3 low | $0.1119 | $0.1056 | cheap-review (haiku-5.5) $0.0063 | 40,193 | 1,385 | 113,752 | 76 s |
| T4 high | $0.1552 | $0.1423 | cheap-design-review (minimax-m3p1-flash medium) $0.0129 | 41,706 | 4,650 | 123,640 | 187 s |
| T4 medium | $0.1179 | $0.1075 | cheap-design-review (minimax-m3p1-flash medium) $0.0105 | 37,524 | 2,683 | 55,792 | 143 s |
| T4 low | $0.1271 | $0.1101 | cheap-design-review (minimax-m3p1-flash medium) $0.0169 | 39,635 | 1,933 | 115,434 | 170 s |

4-task totals (budget sanity-check only, per the 10-15 methodology):
**low $0.515 · medium $0.625 · high $1.006** — vs argon 10-14 $0.34–0.37.

Objective T2 verification: in each echoed run dir, `python3 -m unittest -v` = **6/6 OK,
green at all three efforts**; `git diff` = **synccli.py only** (1 file, +1/−2: the
`range(1, len(items))` → direct-iteration fix) at all three efforts.

## 2. Line-by-line vs gemini-4-argon (10-14) and the rung benchmarks

Same-effort comparison (argon numbers from `EVALS.md`, measured 10-14):

| Task | Effort | carbon 11-10 | argon 10-14 | Verdict |
|---|---|---|---|---|
| T1 | low | PASS — static detect, no fabrication, full plan | PARTIAL | **carbon better** |
| T1 | medium | PASS — static detect | PASS | tie |
| T1 | high | PASS — static detect | PARTIAL (**dismissed the baseline as unrelated**) | **carbon better** — different failure shape avoided |
| T2 | low | PASS, minimal, delegated | PASS | tie on quality, carbon 1.9× the $ |
| T2 | medium | PASS, minimal, delegated | PASS | tie on quality, carbon 1.7× the $ |
| T2 | high | PASS, minimal, delegated | PASS (only campaign semantic fix) | tie on quality, carbon 4.7× the $ |
| T3 | low | 2/3+2, 2FP | 3/3, 1FP | **argon better** (recall) |
| T3 | medium | 2/3+2, 2FP | 2/3, 2FP | tie on score, carbon 2.7× the $ |
| T3 | high | 2/3+2, 2FP | 2/3, 1FP | argon marginally cleaner, carbon 2.4× the $ |
| T4 | low | 10/10, 0FP | 8/10 | **carbon better** |
| T4 | medium | 10/10, 0FP | 9/10 | **carbon better** |
| T4 | high | 10/10, 0FP | 9/10 avg over 2 runs (10, 8 — variance) | **carbon better** (single run; provisional per the standing one-run caveat) |

Cost context: carbon is **1.4–2.7× argon per task at equal or better quality**. Same
catalog rate — the delta is pure token volume (carbon is verbose: T1-high emitted 13.1k
output tokens vs argon's 2.6k; T2-high 23.7k vs 0.9k).

### Head-to-head consolidated — carbon vs argon (quality / cost per task)

4-task quality summary and 4-task cost roll-up per effort (argon costs from EVALS.md
10-14 rows; avg/task = 4-task total ÷ 4):

| Effort | carbon quality (T1/T2/T3/T4) | argon quality (T1/T2/T3/T4) | carbon 4t total (avg/task) | argon 4t total (avg/task) | Δ cost |
|---|---|---|---|---|---|
| low | PASS / PASS / 2-of-3+2, 2FP / 10 | PARTIAL / PASS / 3-of-3, 1FP / 8 | $0.515 ($0.129/t) | $0.375 ($0.094/t) | **1.37×** |
| medium | PASS / PASS / 2-of-3+2, 2FP / 10 | PASS / PASS / 2-of-3, 2FP / 9 | $0.625 ($0.156/t) | $0.343 ($0.086/t) | **1.82×** |
| high | PASS / PASS / 2-of-3, 1FP / 10 | PARTIAL / PASS / 2-of-3, 1FP / 9 | $1.006 ($0.251/t) | $0.374 ($0.094/t) | **2.69×** |

Reading:
- **Quality:** carbon wins or ties on 11 of the 12 same-effort cells; its only loss is
  T3 `low` recall (2-of-3 vs argon's 3-of-3). Crucially, carbon's quality is **flat
  across efforts** while argon's collapses on T1 at `low`/`high` — carbon never drops a
  task below PASS at any price point.
- **Cost:** carbon's premium **grows with effort** (1.37× → 2.69×) because effort adds
  verbosity, not quality. At `low` the two are closest — and `low` is argon's worst
  effort on T1 — making carbon-low arguably the best quality/$ cell between them
  ($0.129/task vs argon-medium's $0.086 for one fewer PASS).
- **On the contested rung (T4 only):** carbon $0.118–0.155/task for 10/10-0FP at every
  effort vs argon $0.072–0.090/task for 8–9/10 — carbon costs **+31–72% per task** for
  +1–2 quality points, perfect FP discipline, and no run-to-run variance (single-run
  caveat on carbon applies; argon's 10→8 variance is two-run measured). In quality-per-
  dollar terms argon is ~equal at `medium` (9/10 at $0.090 vs carbon 10/10 at $0.118 —
  +0.25 point per +10% cost); the case for carbon is stability, not price.

Vs the rung benchmarks:

- **opus-5.5 (deep / T1 tier-1):** carbon's T1 plans are correct and grounded in files
  and functions but cite **no file:line**, and never execute the suite — good
  orchestrator-grade output, not opus-tier proof depth. No threat to the deep rung
  (these tasks are too easy to discriminate it anyway).
- **haiku-5.5 review floor (T3 3/3, 0FP, $0.0063):** carbon T3 is 2/3 with 2 arguable
  FPs at **$0.11–0.24/task — 17–37× haiku's cost with worse recall**. The floor holds
  without contest.
- **qwen3p8-max (design depth 9/10, fabricated a green T1 baseline):** carbon beats it on
  both axes that killed qwen-max — **T4 10/10 (v1)** and an **honest T1** (found the red
  baseline without asserting a green suite). Escalation-depth contender where qwen-max
  never was.
- **1017 `medium` (strong-design-review rung, T4v2 9/14)** — not comparable (v1 vs v2);
  the v1-vs-v1 comparison above is with argon only. Per bench-v2 policy, if the owner
  shortlists carbon for a design-review rung, the deciding bench for that rung is v2,
  not this grid.
- **glm-5.3-flash / deepseek-flash cheap rungs:** carbon's T2/T3 at $0.11–0.41 vs their
  $0.005–0.010 — dominated by two orders of magnitude for bulk roles.

## 3. Notable behavioral signals

- **Honesty on the T1 baseline — the headline.** Carbon is the **first model in campaign
  history to correctly identify the seeded red baseline at *every* effort** — and it did
  it **statically**: at each effort it read `test_synccli.py` + `collect_stale()` and
  named the exact failing test (`TestCollectStale.test_first_item_stale_is_included`),
  at `low` even naming the exact mechanism (`range(1, len(items))` off-by-one) and
  correctly scoping it as "do not fix unasked". Zero fabrication at any effort — no
  invented green baseline (qwen3p8-max's failure), no dismissal (argon high's failure),
  no structural hallucination (the claude `low` failure). **Caveat:** it never *executed*
  the suite at any effort (tool trace = read/glob only, all 3 arms), and the trap's
  premise is that execution is the only reliable signal. The detection was verified
  correct this time, but a model that reasons "this test should fail" without running
  can be wrong the same way — the signal is honest-but-unproven. Its acceptance criteria
  correctly demand recording the `unittest -v` baseline as an orchestration step, which
  is where the proof would occur in a real run.
- **Other T1 quality:** correct pipeline agent names (impl/review/explore/design-review
  with the cheap-* fallbacks correctly mapped), correct cost-guard/escalation policy,
  verifiable criteria (`inspect.signature`, `json.loads(stdout)`, `git diff --name-only`).
  Misses: no file:line citations. Non-hallucination verified: its "hidden-dir skip"
  claim and its `syncd` references both check out against `synccli.py:13` and
  `DESIGN.md`'s Rollout section.
- **FP discipline (T3):** both extra FPs recurred identically at all 3 efforts:
  (a) "merge_manifest never persists the merged manifest" (the function *returns* the
  merged dict — a pure-function reading is equally valid; borderline), and (b) "top-dir
  filtering misses nested `__pycache__`" (the constant is named `EXCLUDE_TOP_DIRS` —
  top-level is the documented contract). Real-bonus findings were solid: the
  mtime-decrease inconsistency vs `changed_files`, and the overbroad
  `except Exception`. **The seeded manifest-purge defect was missed at all 3 efforts** —
  a family-level blind spot (argon found it only at `low`).
- **Runs tests itself (T2):** yes — parent ran `python3 -m unittest -v` before and after
  the fix at every effort, reported both outputs honestly (red → green).
- **Delegation (T2 + T3 + T4):** carbon **delegates at every effort, on every task that
  has a cheap rung** — T2 fix → cheap-mech at `low` (deepseek-v4.1-flash) / cheap-code at
  medium+high (glm-5.3-flash high), plus a haiku cheap-review pass; T3 → haiku
  cheap-review; T4 → minimax-m3p1-flash cheap-design-review. It behaves like a proper
  orchestrator over the kit's own pipeline — but it means **an eval arm's findings are
  partly the children's work** (scored on combined labor per the delegation rule), and
  it burns carbon-priced tokens supervising $0.005 children. Child costs were trivial
  ($0.005–0.017); carbon's own parent tokens are the cost driver.
- **Effort monotonicity:** quality is **flat low→high on all 4 tasks** (the only effort
  effect is price and verbosity). "low skips reading code" does not apply to this model —
  carbon-low read the full repo on every task. For carbon, effort buys nothing but cost.
- **Carbon ≠ argon behaviorally:** argon is terse (0.9–2.6k out-tokens), carbon is
  maximalist (up to 23.7k) — same family, opposite token temperament. Whatever
  quantization/serving difference exists between the two, it is not cosmetic.

## 4. Verdict — per rung

| Rung | Contender? | Reading |
|---|---|---|
| cheap-code / cheap-review / cheap-mech / explore | **No** | T3 2/3-2FP at 17–37× haiku; T2 correct but 30–80× glm-flash. Dominated on every bulk role. |
| orchestrator (T1) | **Weak** | Best-in-campaign baseline detection (honest, all efforts) but static-only, no file:line, $0.10–0.21/task vs glm high's $0.005 PASS. Quality does not clear glm's price. |
| strong-review-alternative (T3) | **No** | 2/3+2, 2FP at every effort — ties argon medium at ~2.4× cost, loses to argon low's 3/3. Does not displace anyone. |
| strong-design-review-alternative (T4) | **Yes — the real question of this campaign** | T4 **10/10-0FP at all 3 efforts** ($0.118–0.155/task) vs argon's pending candidacy (9/10 avg, 10→8 variance, $0.088, missed renames + hardcoded config in the confirmation run). Carbon is the stronger, more stable v1 T4 — at ~1.4× the per-task cost, same gemini-via-Copilot lineage (i.e. it does **not** add a lineage argon wouldn't). |

**What this puts in front of the owner** (no change made by this campaign):

1. **gemini slot for the strong-design-review-alternative rung: argon vs carbon.**
   Carbon's 10-10-10 all-effort sweep vs argon's 9/10-with-variance argues carbon;
   argon's 1.4× price advantage and argon's existing 2-run cell argue for a carbon
   confirmation run before deciding (all carbon cells here are single-run, provisional
   per the standing lesson). Note argon's pending candidacy was itself explicitly
   PENDING — this grid does not decide it, it re-opens the comparison.
2. **If the owner approves carbon for that rung, the follow-ups would be** (none done):
   - add the three carbon rows above to `EVALS.md` (Roles section: tested-and-noted, or
     rostered if it wins the rung);
   - decide argon-vs-carbon for the alternative rung — the loser moves to
     "Tested and kept out"/documented fallback with the reason recorded;
   - optionally re-run the winner's T4 on bench **v2** (`run-eval-v2.sh`) — per the
     bench-v2 policy, a ≥9/10 v1 gate is met by both, and the rung decision on that
     rung should cite v2, not v1;
   - update the `gemini-4-argon` row's "PENDING OWNER DECISION" note to record the
     outcome either way.
3. **Nothing else changes:** the review floor (haiku), 1017's strong-design-review
   `medium`, glm/deepseek cheap rungs, and the terra rungs are untouched by this grid —
   carbon does not reach 3/3 on T3 and does not undercut any cheap-tier price.

## 5. Follow-up runs (owner-approved, 2026-11-10)

Three owner-approved runs closing the open caveats of §4: the carbon v1-T4-high
one-run caveat, and v2 numbers for both argon-vs-carbon contenders. Harnesses:
`run-eval.sh T4` (v1 fixture) and `run-eval-v2.sh` (v2 fixture, untouched);
costs are DB-recorded values, parent + all children per the delegation rule
(§1 conventions).

### 5.1 Run-by-run results

**Run 1 — v1 confirmation, T4 `high`, carbon.** The **10/10, 0FP held.** The
second run re-found all 10 v1 categories (swallowed copy errors never retried,
non-atomic manifest rewrite, 50k/500 ms polling cost, mtime-only detection,
mid-write copy exposure, blocking single thread, undefined deletions/renames,
no instance lock, hardcoded 500 ms, reuse of `sync()`) with zero false
positives, and again delegated to `cheap-design-review` (minimax-m3p1-flash
`medium`, $0.0122). **2-run average: 10/10-0FP (10, 10) at avg $0.167/task** —
the standing one-run caveat on this cell is closed. Carbon's v1 candidacy is
now two-run measured, matching argon's two-run status.

**Run 2 — bench v2, carbon `high`: 10/14, 0 FP, 0 proofs.** All 10 seeded
categories found with precise code citations: lock TOCTOU (`state.py`
exists→`open("w")`), lock released before manifest commit (split-brain across
the sleep/commit window), no fsync vs the crash-safety claim, whole-second
`int(st_mtime)` truncation, changed-mid-copy file still marked synced
(`syncd.py:60-61`), reset-on-change debounce starvation, unbounded
`synced`/`observed`/`quiet_since` growth, the 50k/100 ms scan claim challenged
by magnitude (~1.2–3.4 s), the absent reconcile/deletion pass, and the
unguarded stat/copy path that kills the daemon on a vanished file. Nothing
executed (read-only trace + one cheap-design-review delegation, $0.0166), so
the +4 proof bonus stayed unearned — the ceiling remains 10. Score: 10/14, the
best v2 result ever measured in this kit (level with qwen `xhigh` and argon's
11-01 arm).

**Run 3 — bench v2, argon `high`: 9/14, 0 FP, 0 proofs.** Nine of 10
categories found (lock TOCTOU + stale lockfile, lock-release split-brain,
mtime truncation, partial copy marked synced, debounce starvation, unbounded
state growth, scan-budget magnitude challenge, missing reconcile/`synced`
re-injection of deleted files, daemon death on vanished files). **Missed:
category 3 (`fsync-claim`)** — argon argued the manifest/journal crash-atomicity
hole in detail but never observed the absence of `fsync` against the
crash-safety claim. One notable correct catch the rubric does not credit:
`replay_journal` is defined but never called on startup (verified true against
the fixture — not an FP). Delegated to cheap-design-review ($0.0088), read-only
otherwise. **Note: argon `high` was not actually missing a v2 number** — the
2026-11-01 calibration campaign measured it at **10/14** ($0.1226). This run
is a second data point: 10 → 9, **2-run average 9.5/14**, the variance landing
exactly on the borderline cat-3 durability call.

Per-run cost/token/duration (DB-recorded; each run's cost = parent + the one
`cheap-design-review` child, minimax-m3p1-flash `medium`):

| Run | Session title (parent) | Score | Parent $ | Child $ | Total $ | In tok | Out tok | Cache read | Duration |
|---|---|---|---|---|---|---|---|---|---|
| 1. v1 T4 high carbon (confirmation) | `eval-2026-11-10-T4-github-copilot-gemini-4-carbon-high` (2nd, newest session) | **10/10, 0FP** | .1663 | .0122 | **.1784** | 42,579 | 6,914 | 119,672 | 206 s |
| 2. v2 carbon high | `eval-2026-11-10-T4V2-github-copilot-gemini-4-carbon-high` | **10/14, 0FP** | .2122 | .0166 | **.2288** | 41,472 | 12,008 | 91,292 | 311 s |
| 3. v2 argon high | `eval-2026-11-10-T4V2-github-copilot-gemini-4-argon-high` | **9/14, 0FP** | .1270 | .0088 | **.1357** | 38,845 | 4,367 | 56,314 | 132 s |

### 5.2 Updated argon-vs-carbon — the strong-design-review-alternative rung

All figures for the rung's task (T4), each cell's best-measured effort (`high`
for both on this rung). v1 = 2-run averages; v2 = the deciding bench for this
rung per the bench-v2 policy.

| Dimension | gemini-4-carbon `high` | gemini-4-argon `high` |
|---|---|---|
| v1 T4 (2-run avg) | **10/10, 0FP** (10, 10) | 9/10 avg (10, 8 — variance) |
| v2 T4 /14 | **10/14, 0FP** (single run) | 9.5/14 avg, 0FP (10 on 11-01, 9 today; miss = cat-3 fsync) |
| v1 cost/task | $0.167 (2-run avg of .1552 / .1784) | $0.088 (10-14) |
| v2 cost/task | $0.2288 | $0.129 (2-run avg of .1226 / .1357) |
| Proofs-by-execution | 0 | 0 |
| Delegation on T4 | yes (minimax cheap-design-review) | yes (minimax cheap-design-review) |

Carbon is now two-run measured on v1 (no variance) and single-run on v2;
argon is two-run on both but variance-carrying on both (v1 10→8, v2 10→9).

### 5.3 Decision data (no recommendation — the owner decides)

The trade-off on this rung is **stability and a clean FP sheet vs a ~1.7–1.9×
price premium**. Carbon leads on every measured quality axis: a confirmed
two-run 10/10-0FP on v1 (argon drops 2 points across its two runs), and the
kit's best-ever v2 score (10/14, 0 FP) vs argon's 9.5/14 two-run average —
with argon's single v2 miss being the durability-gap category, the one
code-required observation v2 uses to separate readers from skimmers. Against
that, carbon costs $0.167–0.229 per design-review task vs argon's
$0.088–0.129 at the same catalog rates — the delta is pure token volume
(carbon's maximalist output temperament, §3), not rate. Both delegate the task
to the same cheap child, so the delegation rule does not differentiate them;
both earned zero proof bonus (nobody in v2 history has executed a repro). If
the owner weights certainty of the quality number (no variance, no missed
category across 3 graded runs of the rung's task), the data points at carbon;
if the owner weights per-task cost at near-parity (the two models are 1 and
1.5 points apart on v1/v2 respectively, within scoring noise on borderline
calls), the data points at argon. Per the bench-v2 policy this rung decision
should cite the v2 column; the v1 column corroborates. This report makes no
roster change.

## 6. Deciding run: carbon T4-low on bench v2 (owner-approved)

**Score: 4/14** — 7/10 categories found, 0 proofs-by-execution, **1 FP (−3)**.
Harness `run-eval-v2.sh github-copilot/gemini-4-carbon low` (variant = effort;
v2 fixture untouched, plain files). Session
`eval-2026-11-10-T4V2-github-copilot-gemini-4-carbon-low`; no child sessions
(this run did **not** delegate, unlike the `high` arm's cheap-design-review
child). Cost **$0.1009** (parent only: 37,259 in / 1,796 out / 84,106
cache-read tok), duration **43 s**.

Found: lock TOCTOU (`exists`+`open("w")`), lock released before manifest
commit (load→update→write lost-update), whole-second mtime truncation, torn
copy journaled as synced, reset-on-change debounce starvation,
pending-unbounded drain-rate failure, 50k scan-budget magnitude challenge.
Missed: `fsync-claim` (named the missing fsync only as a burst-throughput
point, never against the crash-safety claim — grazed, no half credit),
`deletions-never-propagated` (tombstone bullet stayed hypothetical, never
stated the reconcile pass is absent), `crash-on-transient-error` (listed
exceptions without tying them to daemon death vs the Errors bullet). The FP:
"os.walk follows symlinks by default → directory symlinks can cause infinite
loops" — `os.walk` defaults to `followlinks=False` (rubric rule c).

Placement against the reference points: at `high` this same model scored
10/14 ($0.2288, 0 FP) on v2, so dropping to `low` costs it 6 points and 1 FP
at ~2.3× less cost — the effort-flatness carbon showed on the v1 grid does
**not** hold on the harder v2 bench. It lands below argon `high` v2 (9/14,
then 10/14 on 11-01; 2-run avg 9.5/14) and below deepseek-1017 `medium` v2
(9/14). The low-effort miss pattern is concentrated in the code-required
categories (3, 9, 10) — the same reader-vs-skimmer split the rubric uses as
its discriminator. No recommendation made here; the owner decides.

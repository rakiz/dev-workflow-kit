# Model eval results — 2026-10-23 (minimax-m3p1-flash full grid)

Complete report by test category. This campaign ran the **full effort×task
grid for `minimax-m3p1-flash`** (Fireworks Serverless, released 2026-10-23,
successor of minimax-m3): 4 tasks × 4 efforts = 16 arms + 1 T2-low canary
duplicate (dedupe: min of priced copies), 17/17 priced, zero failures.
Evidence: opencode session titles `eval-2026-10-23-*minimax-m3p1-flash*`,
run dirs under `/var/folders/.../T/synccli-eval-*`. Method: subagent-scored
against the seeded traps, T2 re-executed objectively.

**Delegation rule applied (new, 2026-10-23 — `evals/README.md` step 4)**:
arm cost = parent + all child sessions (`session.parent_id`), children named.
M3.1 delegated on 4 of 16 arms (T2 `medium`/`high`/`xhigh`, T4 `high`) —
the same opportunistic delegation muse-spark showed on 10-16.

**Headline: M3.1 fixed M3's variance and is a genuine cheap-tier contender —
but it wins no rung from the incumbents.** T3 3/3-0FP at `low`/`medium`/
`high` (M3 collapsed 3/3→1/3→3/3; M3.1's floor is 2/3 at `xhigh` only, 0 FP
everywhere), T4 10/10-0FP at `medium`/`high`/`xhigh` — yet at matched
quality it is never cheaper than the deployed model, and its delegation
habit doubles its own T2 bill.

---

## T1 — Orchestration

Trap: pre-existing red baseline (`collect_stale` off-by-one, `synccli.py:55`).

| Arm | Date | T1 cost / run | T1 verdict |
|---|---|---|---|
| glm-flash `high` (deployed orchestration) | 10-14 | **$0.0050** | PASS |
| **M3.1 `low`** | **10-23** | **$0.0085** | **PASS** — ran tests, called out the red baseline, grounded plan |
| **M3.1 `medium`** | **10-23** | **$0.0073** | **PARTIAL** — solid grounding but never ran tests, missed the baseline |
| **M3.1 `high`** | **10-23** | **$0.0116** | **PASS** — baseline named with explicit "known-red" acceptance criterion |
| **M3.1 `xhigh`** | **10-23** | **$0.0114** | **PASS** — dedicated baseline-decision task |
| 1017 `xhigh` | 10-19 | $0.0154 | PASS |
| gpt-6.1-sol `low` | 10-14 | $0.092 | PASS |

**Eval verdict**: non-monotone again (`medium` < `low` — third model family
showing the pattern). PASS at $0.0073–0.0116, but **glm `high` keeps
orchestration at ~2× cheaper** for the same verdict.

## T2 — Impl

Objective: suite green, minimal fix, test file untouched.

| Arm | Date | T2 cost (total, incl. children) | T2 verdict |
|---|---|---|---|
| glm-flash `high` (deployed cheap-code) | 10-14/16 | **$0.0053 avg** | ✅ PASS (3 runs, no delegation) |
| old deepseek flash `low` (deployed explore/mech) | 10-14 | $0.0066 | ✅ PASS |
| **M3.1 `low`** | **10-23** | **$0.0063** | ✅ PASS — direct edit, one-liner |
| **M3.1 `medium`** ⚑ | **10-23** | **$0.0124** | ✅ PASS — ⚑ delegated to deepseek@cheap-mech (+$0.0056) |
| **M3.1 `high`** ⚑ | **10-23** | **$0.0208** | ✅ PASS — ⚑ deepseek@cheap-mech + haiku@cheap-review (+$0.0121) |
| **M3.1 `xhigh`** ⚑ | **10-23** | **$0.0222** | ✅ PASS — ⚑ deepseek@cheap-mech + haiku@cheap-review (+$0.0130) |

**Eval verdict**: no rung change. Direct arms tie old flash at parity
($0.0063 vs $0.0066); delegated arms pay 2–3.5× the same objective outcome —
**delegation is pure overhead on a mechanical fix**. glm `high` keeps
cheap-code.

## T3 — Code review

3 seeded defects in `incremental.py` (mutable default arg; silent copy
failure → lying `done`; `merge_manifest` never purges deletions).

| Arm | Date | T3 cost / run | T3 verdict |
|---|---|---|---|
| claude-haiku-5.5 `default` (deployed cheap-review) | 10-07 | **$0.0063** | **3/3, 0 FP** |
| **M3.1 `low`** | **10-23** | **$0.0068** | **3/3, 0 FP** +3 bonus |
| **M3.1 `medium`** | **10-23** | **$0.0085** | **3/3, 0 FP** — empirically verified (leak repro) |
| **M3.1 `high`** | **10-23** | **$0.0107** | **3/3, 0 FP** — all seeds execution-verified, strongest analysis |
| **M3.1 `xhigh`** | **10-23** | **$0.0119** | 2/3, 0 FP — missed the purge-on-delete seed |
| M3 (old) | 09-30 | $0.094 | 3/3 → 1/3 → 3/3 across 3 runs — **disqualified (variance)** |
| 1017 `medium` | 10-19 | $0.0233 | 3/3, 0 FP |
| qwen3p8 `xhigh` | 09-30 | n.t. | 3/3+2 proven |

**Eval verdict**: **M3.1 fixed M3's failure mode** — floor moved from 1/3
to 2/3, 0 FP held on all four runs, 3/3 on three. At `low` ($0.0068) it is
within 8% of haiku's floor with equal quality. **haiku keeps cheap-review**
(proven over a full 6-variant grid); M3.1 needs a confirmation run before
it could challenger — and haiku's $0.0063 is per-task in production too,
where M3.1's delegation habit does not apply (T3 arms didn't delegate).

## T4 — Design review

~10 flaw categories seeded in `DESIGN.md`.

| Arm | Date | T4 cost (total) | T4 verdict |
|---|---|---|---|
| 1017 `medium` (deployed strong-design-review) | 10-19 | **$0.0143** | **10/10, 0 FP** (all efforts) |
| old deepseek flash `low` (deployed cheap design-review) | 10-14 | **$0.0076** | 9/10 |
| **M3.1 `low`** | **10-23** | **$0.0080** | 9/10, 0 FP — missed "no instance lock" |
| **M3.1 `medium`** | **10-23** | **$0.0077** | **10/10, 0 FP** — incl. PID/lock + writer isolation |
| **M3.1 `high`** ⚑ | **10-23** | **$0.0241** | **10/10, 0 FP** — ⚑ deepseek@cheap-design-review (+$0.0109) |
| **M3.1 `xhigh`** | **10-23** | **$0.0141** | **10/10, 0 FP** — measured a 50k-file benchmark (best T4 of the campaign) |
| argon `high` (deployed alternative) | 10-14 | $0.0879 | 9/10 avg (2 runs) |

**Eval verdict**: `medium` beats the deployed cheap design-review on quality
(10/10 vs 9/10) at +1% cost ($0.0077 vs $0.0076) — a genuine **cheap
design-review challenger**, single-run. `xhigh` ($0.0141, measured
benchmark) ties deployed 1017 `medium` at parity price. No swap on a single
run — confirmation candidate.

---

## Roster impact (no change applied — owner decides)

| Rung | Deployed | M3.1 finding | Status |
|---|---|---|---|
| cheap-code / impl | glm-flash `high` ($0.0053, 3 runs) | $0.0063 direct, $0.012–0.022 delegated | keep glm — no gain |
| explore / cheap-mech | old flash `low` ($0.0066) | $0.0063 direct T2 — parity | keep; M3.1 = backup if old flash degrades |
| cheap-review | haiku `default` ($0.0063, proven) | M3.1 `low` 3/3-0FP @ $0.0068 (single run) | keep haiku; **run confirmation before any swap** |
| design-review (cheap) | old flash `low` (9/10 @ $0.0076) | M3.1 `medium` 10/10 @ $0.0077 | **confirmation candidate** — same price, +1 category |
| orchestration | glm-flash `high` ($0.0050) | PASS @ $0.0073–0.0116 | keep glm — 2× cheaper |
| strong-design-review | 1017 `medium` (10/10 @ $0.0143) | M3.1 `xhigh` 10/10-0FP @ $0.0141 with measurements | keep 1017 (rostered 10-19); M3.1 `xhigh` = nearest challenger |

## Standing verdicts on new models

- **minimax-m3p1-flash** (Fireworks Serverless, 2026-10-23) — full 4×4 grid:
  - T1: PASS (`low` $0.0085, `high` $0.0116, `xhigh` $0.0114), PARTIAL
    (`medium` $0.0073 — non-monotone, third family showing it).
  - T2: PASS all efforts — but **delegated on 3 of 4 efforts** (deepseek
    cheap-mech, sometimes + haiku cheap-review); direct only at `low`.
  - T3: **3/3, 0 FP at `low`/`medium`/`high`** ($0.0068–0.0107), 2/3-0FP
    (`xhigh`). **M3's disqualifying variance is fixed** (floor 1/3 → 2/3).
  - T4: 9/10 (`low`), **10/10-0FP** (`medium`/`high`/`xhigh`,
    $0.0077–0.0241) — the `xhigh` arm measured a real benchmark.
  - **No rung taken.** One confirmation candidate (cheap design-review,
    `medium`). Delegation habit documented — costs double-counted per the
    new rule, so its numbers are honest.
- **deepseek-v4p1-flash-1017** — rostered 10-19, unchanged
  (`strong-design-review` `medium`).

## Methodology (unchanged + one addition)

Per-task decision rule (2026-10-15): a rung is decided on the task that rung
performs; the 4-task total is a sanity check only. Full effort×task grid
before adoption. Review lineage ≠ impl lineage. Eval verdicts recommend,
`models.json` decides. **New (10-23): delegation rule** — arm cost = parent
+ child sessions, children named (see `../README.md` step 4).

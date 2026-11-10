# Model eval results — 2026-11-01 (bench v2 first campaign: the four v1-perfect models)

First validation run of bench v2 (`synccli-eval-repo-v2/` + `RUBRIC-T4V2.md`),
per the README step-7 policy: v2 is run only for models that ace v1 T4. The
four models with a perfect v1 T4 were run at their rostered effort:

| Model | Effort (rostered) | v1 T4 | **v2 score /14** | Cost / run | Duration | Delegations |
|---|---|---|---|---|---|---|
| qwen3p8-2p4t-a95b | `xhigh` (strong-review-a2) | 10/10 | **10** (9-10, cat-3 borderline) | $0.1308 | 44.8 s | 0 |
| gemini-4-argon | `high` (design-review-alt) | 9-10/10 | **10** (9-10, cat-3 borderline) | $0.1226 | 155.4 s | 1 (`cheap-design-review` M3.1 `medium`, $0.0098, read-only) |
| deepseek-v4p1-flash-1017 | `medium` (strong-design-review) | 10/10 | **9** | $0.0371 | 43.6 s | 0 |
| minimax-m3p1-flash | `medium` (cheap-design-review) | 10/10 | **9** | $0.0100 | 66.5 s | 0 |
| gpt-6.1-terra | `medium` | 10/10 | **8** | $0.0355 | 17.6 s | 0 |
| fw-deepseek-v4-pro | `high` (design-review-a2) | 9-10/10 | **not run** — gateway rejects the model on every variant ("does not exist or does not support this protocol", 2026-11-01; Fireworks direct does not carry it). Rung falls back per MODELS.md if the outage persists | — | — | — |

**Headline: the v2 bench discriminates** (10 > 9 = 9 > 8) where v1 T4 had
saturated. **Argon ties qwen at the top (10/14) at lower cost** ($0.1226 vs
$0.1308) — decisive for the design-review ladder question raised this
campaign (see "Design-review ladder comparison" below). Qwen3.8-2.4T and
argon both found all 10 seeded categories. Raw outputs: `raw/*.md` (all arms:
zero proofs-by-execution — only `ls` and file reads — so the +4 proof bonus
was never earned by anyone).

Per standing policy: v2 scores are NEVER compared to v1 scores; v2 governs
only strong-design-review / strong-depth rung decisions.

## Category detail

| # | Category | qwen | 1017 | M3.1 | terra |
|---|---|---|---|---|---|
| 1 | lock-toctou | ✅ | ✅ | ✅ | ✅ (borderline: fix named, window not described) |
| 2 | lock-window | ✅ | ✅ | ✅ | ✅ |
| 3 | fsync-claim | ✅ (borderline: torn-manifest consequence, no "fsync" word, journal half uncovered) | ✅ | ✅ | ✅ (borderline: durability gap named, no code read) |
| 4 | mtime-truncation | ✅ | ✅ | ✅ | ✅ (inferable from DESIGN.md alone) |
| 5 | partial-copy-marked-synced | ✅ | ✅ | ✅ | ❌ (never read the code) |
| 6 | debounce-starvation | ✅ | ❌ (found only the latency-granularity critique — the rubric's own example-FP shape) | ✅ | ✅ |
| 7 | unbounded-state | ✅ | ✅ | ✅ | ✅ (drain-rate arm only) |
| 8 | scan-budget | ✅ | ✅ | ✅ (borderline: "unverified and optimistic", no counter-number) | ✅ (borderline: 100k/s rate + hedge) |
| 9 | deletions-never-propagated | ✅ | ✅ | ✅ | ❌ (unknowable without the code) |
| 10 | crash-on-transient-error | ✅ | ✅ | ❌ | ❌ |
| Categories | | **10** | **9** | **9** | **7** |
| Proof bonus | | 0 | 0 | 0 | 0 |
| FPs | | 0 | 0 | 0 | 0 |
| **Total** | | **10** | **9** | **9** | **8** |

Observations:

- **Terra `medium` never opened the code** (one Read of DESIGN.md, 17.6 s,
  144 reasoning tokens) — its 8/14 is the ceiling of design-only inference.
  On v1 T4 the same model read the fixture and scored 10/10. Whatever the
  cause (effort mapping, prompt reading), it is the opposite profile from
  qwen (33k input, full code read, 10/10). For a bench whose discriminator
  is "did you actually read the code", terra's arm is a methodology warning
  as much as a model result.
- **The proof bonus separated nobody** — every arm treated T4v2 as a
  read-and-write task. The +4 bonus remains unexercised; until a model runs
  repro scripts, v2's real ceiling is 10, and ties among 9s are broken by
  cost alone.
- **0 FP across all four arms** under the (a)-(d) deduction rule — the
  deliberately-defensible trade-offs did not draw shotgun findings from any
  of the four best v1 models.

## Calibration verdict (the purpose of the 1017 arm)

The rubric held: every category call was rule-decidable; three borderline
calls are flagged above with their score ranges (max spread ±1 per model).
One ambiguity was settled by owner ruling BEFORE the main runs and is now
codified in `RUBRIC-T4V2.md`: **Example-FP list membership is not a
deduction — FP deduction only via rules (a)-(d)** (a factually-true finding
appearing in an Example-FP list, e.g. PID-liveness hygiene or `f.read()`
memory, costs nothing). Three residual ambiguities, noted for the next v2
campaign but not blocking: (1) cat-3 credits a named durability gap without
the literal "no fsync" observation; (2) cat-2's "code-trace walkthrough earns
the bonus" clause contradicts the global must-execute proof definition; (3)
cat-8 accepts a hedged magnitude challenge without a counter-number.

## Design-review ladder comparison (the question this campaign answers)

Raised by the owner: qwen3p8-2p4t `xhigh` (v2 winner) as an addition to — or
above — the design-review escalation chain
(1017 `medium` → argon `high` → pro `high`). Standing rule: always compare on
the same bench, no rung decision without owner approval.

| Arm | v2 | Cost / run | Verdict |
|---|---|---|---|
| qwen3p8-2p4t `xhigh` | 10/14 | $0.1308 | all 10 categories, 0 FP |
| argon `high` (rostered alternative) | 10/14 | $0.1226 | all 10 categories, 0 FP — **ties qwen at −6% cost** |
| pro `high` (rostered alternative2) | not measurable | — | gateway outage (see table) |

**Result: the comparison removes the case for inserting qwen into the
design-review ladder.** Argon — already rostered one rung up — reaches the
same v2 ceiling (10/14, 0 FP) for less, so the top of the design-review
escalation is already covered; adding qwen there would add a costlier rung
with zero measured quality gain. Qwen's v2 result instead retro-validates its
existing home at `strong-review-alternative2` (code review), where it holds
the best review scores ever measured in this kit. Caveats: single runs on
both arms (±1 category of scoring noise on the borderline cat-3 calls);
argon's arm carries the delegation. **Recommendation to owner: no roster
change.** Any swap remains an owner decision.

## New-model screening this campaign

The new Qwen releases (Qwen3.8-Flash-Next 180B, Qwen3.8-27B) are served by
NONE of the kit's three providers (checked `opencode models` 2026-11-01:
Fireworks carries only qwen3p8-2p4t-a95b and qwen3p8-max, both already
evaluated). The full v1 grid for them is **postponed until a configured
provider serves them** — re-check `opencode models | grep -i qwen` at the
next model-release pass.

## Methodology

`evals/run-eval-v2.sh <model> [variant]` (new script, T4v2-only: copies
`synccli-eval-repo-v2`, no git history, session title
`eval-YYYY-MM-DD-T4V2-<tag>`). Costs:
`sqlite3 ~/.local/share/opencode/opencode.db "SELECT title, cost, ... FROM
session WHERE title LIKE 'eval-2026-11-01-T4V2%';"` — 5 run arms + 1 refused
(pro gateway outage); 1 delegation on the argon arm (combined cost = parent
+ child, child named). Scoring by independent scorer subagents per arm,
against `RUBRIC-T4V2.md` only.

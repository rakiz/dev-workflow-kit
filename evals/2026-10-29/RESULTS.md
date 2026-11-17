# Model eval results — 2026-10-29 (mai-code-1.1-flash, single default arm)

Eval of **`github-copilot/mai-code-1.1-flash`** (MAI-Code-1.1-Flash, Copilot,
released as a reasoning model, 256k context). **The model exposes NO variants
— a single `default` arm**, so this is 4 runs (T1–T4), one each, not an
effort grid. 4/4 runs completed, zero errors, zero retries.

Method: `evals/run-eval.sh <T1..T4> github-copilot/mai-code-1.1-flash`
(session titles `eval-2026-10-29-T*-github-copilot-mai-code-1-1-flash`).
T2 verified objectively in the run dir; T3/T4/T1 scored against the seeded
traps. Raw evidence: `sessions/run-outputs.md`, `sessions/sessions.tsv`, `sessions/costs.json`.

**Delegation rule applied (README step 4)**: zero child sessions on all 4 arms
(`session.parent_id` query returned 0) — costs are parent-only; no child
models to name.

**Pricing context**: Copilot $0.20/$1.20 per MTok (cache read $0.02). At
$0.20/$1.20 mai-code is **NOT cheaper per MTok than glm-flash**
($0.15/$0.50 — 33% dearer on input, 2.4× on output; it does win cache read,
$0.02 vs glm's $0.078). Under the kit's "price beats speed" rule it can only
take a rung by winning **quality-per-task at comparable per-task cost**.

**Headline: no rung taken — competitive on mechanical tasks, behind on the
judgment tasks (single-run results; T1 is the orchestration probe).** T2 PASS
with a clean one-liner at $0.0075 (quality tie with glm, +42% cost), T3
2 clean + 1 wrong-branch (2.5/3 at best), 0 FP, at $0.0079 (quality tie with
haiku at best, +25% cost), but T1 **PARTIAL** (never ran the tests, red
baseline missed) and T4 **7/10** (missed 3 of 10 categories).

---

## Results matrix

| Task | Verdict | Score | Cost / run | Duration | Delegations |
|---|---|---|---|---|---|
| T1 orchestration | **PARTIAL** | plan grounded but no file:line, **red baseline missed** (tests never executed), pipeline agents correct (explore/design-review/impl/impl/review), zero hallucination | **$0.0096** | 23.2 s | 0 |
| T2 impl | ✅ **PASS** | objective: 6/6 tests green in run dir; fix = 1 line (`range(1, len(items))` → `range(len(items))`), test file untouched, no delegation | **$0.0075** | 28.8 s | 0 |
| T3 review | **2 clean + 1 wrong-branch (2.5/3 at best), 0 FP** | seeds 1–2 area covered — seed 2 on the wrong branch, seed 3 missed (see below); 1 speculative non-seed finding (rated Major in the raw output), not counted as FP | **$0.0079** | 37.3 s | 0 |
| T4 design-review | **7/10, 0 hard FP** | 1 arithmetic error flagged (see below) | **$0.0043** | 20.6 s | 0 |
| **4-task total** | — | — | **$0.0294** | 109.7 s | 0 |

Per-task average: **$0.0073**. Reasoning tokens modest (512–2,112/task);
cache-read-heavy profile (up to 174k cache-read tokens on T2 — hand-check of
T2 cost at copilot rates, i.e. **input + output + reasoning + cache-read,
each at its rate** ($0.20 / $1.20 / $1.20 / $0.02 per MTok), reproduces the
DB figure: $0.00748).

## T3 detail — the 3 seeds vs what it found

| Seed | Found? | Note |
|---|---|---|
| (1) mutable default arg (`filter_excluded(excluded=[])`) | ✅ | Minor, correctly severity-calibrated |
| (2) silent copy failure → lying `done` | ✅ * | Found the silent-failure/false-success cluster in `copy_many` at Major severity, **but described the wrong branch**: it says `copy_many`'s `except Exception` swallows failures, missing that `copy_file`'s `except OSError: pass` means a *failed* copy never raises at all and its dst lands in `done` as if copied — the worse half of the lie. Counted as found (consequence captured); strict graders may re-judge as 2/3. |
| (3) `merge_manifest` never purges deleted files | ❌ | Missed entirely |

Extra finding: mtime-only staleness in `merge_manifest` (same-resolution
rewrites skip the merge) — labelled **speculative** here (edge case, not
contradicted by the code, **not** counted as a hard FP); note that the raw
output rated it **Major**. Zero hard FPs.

## T4 detail — v1 categories (7/10)

T4 here is the **v1 bench** (`run-eval.sh` runs the `synccli-eval-repo`
fixture); scored against the README's 10 seeded v1 categories with the FP
discipline conventions of `RUBRIC-T4V2.md` (that rubric's own 10 categories
apply only to `synccli-eval-repo-v2`, which this run did not use — never
compared across benches).

Found (7): non-atomic manifest, 50k/500 ms polling cost, mtime-only change
detection, mid-write partial copies (with the temp-file+rename fix), errors
swallowed without retry, blocking single thread, hardcoded config.
Missed (3): undefined deletions/renames, no instance lock, reuse of `sync()`.
FPs: 0 hard. Flagged: the polling bullet's arithmetic is wrong ("~100 full
scans/sec" for a 500 ms poll = 2 scans/sec; "millions of stat calls" for a
50k-file tree) — the category itself is genuinely seeded, so no FP deducted,
but the quantification is sloppy. No proofs-by-execution (design-only read,
one tool call).

## Verdict vs incumbents (line by line)

| Rung (task) | Incumbent | mai-code-1.1-flash | Line call |
|---|---|---|---|
| impl / cheap-code (T2) | glm-flash `high` — PASS, **$0.00525** avg over 2 runs (10-16, `EVALS.md`); rung ladder ~$0.007/task | PASS, $0.0075, single run | **Keep glm.** Quality tie (both one-line minimal fixes, suite green); mai-code pays +43% per task and is dearer per MTok ($0.20/$1.20 vs $0.15/$0.50). No price win, no quality win. |
| cheap-review (T3) | haiku-5.5 `default` — **3/3, 0 FP @ $0.0063** (proven over a 6-variant grid) | 2 clean + 1 wrong-branch (2.5/3 at best), 0 FP @ $0.0079 (single run) | **Keep haiku.** Equal quality at best (seed 2 was found on the wrong branch — `copy_many`'s `except Exception` instead of `copy_file`'s `except OSError: pass`), +25% cost, +33% input rate, 2.4× output rate. Single-run vs proven. |
| cheap-design-review (T4) | minimax-m3p1-flash `medium` — **10/10, 0 FP @ $0.0082** (confirmed 3 runs) | 7/10, 0 hard FP @ $0.0043 | **Keep M3.1.** mai-code is 47% cheaper per run but loses 3 of 10 categories — the "price beats speed" rule buys nothing on a quality deficit. Also behind the previous incumbent old-flash 9/10 @ $0.0076. |
| explore (T1 as probe) | old deepseek flash `low` — tier-1 plans, $0.0066–0.0080 | T1 PARTIAL @ $0.0096 — more expensive AND worse (missed the red baseline deepseek `low` catches: PARTIAL) | **Keep deepseek.** Dominated on both axes. |
| orchestration (T1) | glm-flash `high` — PASS @ **$0.0050** | PARTIAL @ $0.0096 | **Keep glm.** mai-code pays ~2× for a worse verdict; it never executed the tests. |

**Overall: no adoption.** mai-code-1.1-flash sits in the awkward middle: its
mechanical performance (T2/T3) only *ties* the incumbents at 25–43% higher
per-task cost, and its judgment performance (T1/T4) is strictly behind. With
no variants there is no effort knob that could change the picture, and the
per-MTok rates are above glm-flash's on both billable axes. Not rostered;
re-evaluate only on a price change or a fixture upgrade where its
cache-read-heavy reasoning profile ($0.02/MTok) could become an advantage.

## Methodology notes

- Single default arm (no effort grid possible) — the "decision on the FULL
  effort×task grid" rule degenerates to 1×4 for this model; conclusions are
  single-run except where marked, so weaker than the incumbents' confirmed
  numbers by construction.
- Cost extraction (reproducible):
  `sqlite3 ~/.local/share/opencode/opencode.db "SELECT title, cost, tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, (time_updated-time_created)/1000.0 FROM session WHERE title LIKE 'eval-2026-10-29-%mai-code%';"`
  Delegation rule: children via `SELECT count(*) FROM session WHERE parent_id IN (...)` → 0.
- Bench v2 gate (README step 7): mai-code scored 7/10 on v1 T4 — below the
  ≥9/10 gate, so **no v2 run is warranted**.

# Model evals — dev-workflow-kit

Real comparisons (opencode runs, metrics extracted from the sessions DB)
between the roster's models, meant to arbitrate `models.json` at every model
release.

## Contents

- `2026-11-01/` — **the current report** (`RESULTS.md`): first bench-v2
  campaign — the four v1-T4-perfect models scored on `synccli-eval-repo-v2`
  (qwen3p8-2p4t `xhigh` 10/14, 1017 `medium` 9/14, M3.1 `medium` 9/14,
  terra `medium` 8/14; zero proofs-by-execution anywhere). Calibration
  validated the v2 rubric; the owner FP ruling (deduct only via rules a-d)
  is codified in `RUBRIC-T4V2.md`. No roster change. New Qwen releases
  (Flash-Next, 27B) are served by no configured provider — v1 grid postponed.
- `run-eval-v2.sh` — v2 twin of `run-eval.sh`: T4-only, copies
  `synccli-eval-repo-v2`, no git history, session titles
  `eval-<date>-T4V2-<tag>`.
- `synccli-eval-repo/` — the test fixture, shipped as plain files (no `.git`,
  history stripped on purpose): baseline with 1 seeded failing test
  (`range(1, ...)`) + `incremental.py` carrying 3 seeded defects. **Do not
  fix**: it is the measuring tool.
- `run-eval.sh` — launches a run (task × model × variant) in a fresh copy of
  the repo, where it first recreates the 2-commit history (baseline
  "Initial synccli", then the seeded-defect review commit that added
  `incremental.py`) so T3's `git show HEAD` has a real commit to review.
- `2026-10-16/` — **the current report** (`RESULTS.md`): the muse-spark full
  grid (16 arms, 4 tasks × 4 efforts, Fireworks model released 10-15),
  organized by test category. Standalone — no older report needed. Verdict:
  no rung won for muse-spark; roster unchanged.
- `2026-10-15/` — the 10-14 campaign re-arbitrated under the per-task cost
  methodology (roles are assigned per task; a rung is decided on quality×cost
  of the task that rung performs, 4-task totals are a budget sanity-check
  only). Folded into `2026-10-16/RESULTS.md` — superseded, one-line pointer
  only.
- `2026-10-14/` — raw session data only for the full effort-grid campaign
  (15 arms × T1–T4): `sessions/`, `costs.json`, manifest, log evidence. Its
  report was superseded by `2026-10-15/RESULTS.md`, itself folded into
  `2026-10-16/RESULTS.md`.
- Prior campaigns (2026-09-29 main matrix, 2026-09-29-sol61, the 2026-09-30
  deepseek-effort / deepseek-v4-pro / gateway-candidates / nemotron /
  qwen3p8 evals, 2026-10-07 haiku+ember completion) have been **folded into
  the aggregate `../EVALS.md`** — one blended report per model×effort, with
  the measurement date on each cell — and their dated directories removed.

## The 4 tasks

| Task | Target role | Seeded trap | Scoring |
|---|---|---|---|
| T1 orchestration | orchestrator | pre-existing failing test — only a run that **executes the tests** sees it ; `--dry-run` already exists | grounded plan (file:line), red baseline detected, correct pipeline agents, verifiable criteria, zero hallucination |
| T2 impl | cheap-code | the test's bug | objective: suite green? + size/minimalism of the fix |
| T3 review | cheap-review | 3 defects in `incremental.py`: (1) mutable default arg, (2) silent copy failure → lying `done` (interaction with `copy_file`'s `except OSError: pass`), (3) `merge_manifest` never purges deleted files | n/3 found, bonus, **false positives counted**, severities |
| T4 design-review | design-review | DESIGN.md contains ~10 categories of flaws: non-atomic manifest, 50k/500 ms polling, mtime only, copying files mid-write, errors swallowed without retry, blocking single thread, undefined deletions/renames, no instance lock, hardcoded config, reuse of `sync()` | categories covered, mechanical depth, zero FP |

## To evaluate a new model (checklist)

1. `models.json`: note the current models and their role.
2. Run the matrix: the 4 tasks for the new model at **every effort level it
   exposes** (not just the classic `low`/`medium`/`high` — newer models expose
   `xhigh`/`max`; effort drives the appetite for tools, `low` skips reading
   code) + the 4 tasks of the incumbent model to replace. The default/no-
   variant run also counts as a data point — record it as such.
3. Verify T2 objectively (`python3 -m unittest` in the copy), score T3/T4
   against the lists above, judge T1 (grounding + trap detection).
 4. Extract cost/tokens/duration from the opencode DB (session titles are
    `eval-YYYY-MM-DD-<TASK>-<TAG>`, per `run-eval.sh`; cost = the provider's
    standard API rate, not the plan's real billing). **Delegation rule
    (2026-10-23, the minimax-m3p1 lesson): if the eval session spawns
    subagents, the arm's cost = parent + ALL child sessions** (linked by
    `session.parent_id`) **and each child's model@effort is recorded by
    name** — a model that delegates inside an eval is scored on the
    combined labor, never on its own tokens alone (same caveat as the
    muse-spark Cheap-Mech delegation, 10-16).
5. Decision rules (MODELS.md): comparable cost per MTok for bulk roles,
   reviewer of a lineage ≠ impl, `strong-*` judged on tasks that are up to it
   (these tasks are too easy to discriminate Opus/Fable). **The adoption
   decision is made on the FULL effort×task grid** — never on a single
   variant's result: a model can shine at `xhigh` and hallucinate at `low`
   (the claude lesson), and the roster assigns one effort per role, not one
   model-wide grade.
 6. Write `RESULTS.md` in a dated folder, with the same matrix, and compare
    line by line with the previous eval.
 7. **Update `LEADERBOARD.html` after EVERY campaign** (2026-11-12 rule —
    do not skip): the 5-panel grid (T1, T2, T3, T4-v1, T4-v2), family-colored
    effort lines and all tables must reflect the new results the moment a
    `RESULTS.md` lands — the synthetic view is only worth sharing if it is
    never stale. Re-read the campaign's `RESULTS.md` + new `EVALS.md` rows
    and regenerate the affected points/panels (self-contained HTML, no JS,
    family colors per `models.json` `family_hint`; list non-plotted cells).
 8. **Bench v2 (live since 2026-11-01 — policy decided 2026-10-23)**: T4
    (and T3 depth)
    are saturating — 1017 swept T4 10/10 at all efforts, M3.1 averages
    9.7/10, qwen proved 10/10. A harder bench v2 (cross-file semantic
    regressions, race conditions, measurement-forcing traps; proof-by-
    execution scored, FPs triple-counted) will be run **only for models
    ≥9/10 on v1 T4** — it exists to break ties the v1 bench can no longer
    break, not to re-rank the fleet. **Inversion caveat**: a model can
    score 8/10 on v1 and 10/10 on v2 (the benches measure different
    depth constructs), so scores are NEVER compared across benches —
    v2 governs only the rungs it was built for (strong-design-review and
    future strong-depth confirmations), v1 stays the cheap-tier screener,
    and each roster decision cites the bench it was decided on. Accepting
    the ≥9/10 gate means accepting that an inverted model (8/10 v1,
    10/10 v2) is missed; the gate trades that miss for campaign cost.
    Incumbents are NOT re-run on v2 (results are not comparable across
    benches); a v2 re-base happens only if a v2 rung decision actually
    changes the roster. The v2 fixture lives in `synccli-eval-repo-v2/`
    (answer key: `RUBRIC-T4V2.md` — 10 categories, 5 code-only-detectable,
    formula: categories + proof bonus − 3×FP).

## Effort lesson (valid for any Claude model with a recalibrated effort)

- `low` = fewer tool calls → under-exploration, structural hallucinations on
  T1. Forbidden for roles that must read code.
- `medium` = review/impl sweet spot.
- `high` = orchestration plan (the only level where the model runs the tests
  by itself in our runs).
- `xhigh`/`max` = cost per task converging toward Opus 5.5 → no point for bulk
  roles.

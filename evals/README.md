# Model evals — dev-workflow-kit

Real comparisons (opencode runs, metrics extracted from the sessions DB)
between the roster's models, meant to arbitrate `models.json` at every model
release.

## Contents

- `synccli-eval-repo/` — the test fixture, shipped as plain files (no `.git`,
  history stripped on purpose): baseline with 1 seeded failing test
  (`range(1, ...)`) + `incremental.py` carrying 3 seeded defects. **Do not
  fix**: it is the measuring tool.
- `run-eval.sh` — launches a run (task × model × variant) in a fresh copy of
  the repo, where it first recreates the 2-commit history (baseline
  "Initial synccli", then the seeded-defect review commit that added
  `incremental.py`) so T3's `git show HEAD` has a real commit to review.
- `2026-09-29/` — the eval (final results in `RESULTS.md`, scored responses in
  `outputs/` — only a subset of the runs is archived there: 35 of 45, the rest
  live in the opencode session DB).

## The 4 tasks

| Task | Target role | Seeded trap | Scoring |
|---|---|---|---|
| T1 orchestration | orchestrator | pre-existing failing test — only a run that **executes the tests** sees it ; `--dry-run` already exists | grounded plan (file:line), red baseline detected, correct pipeline agents, verifiable criteria, zero hallucination |
| T2 impl | cheap-code | the test's bug | objective: suite green? + size/minimalism of the fix |
| T3 review | cheap-review | 3 defects in `incremental.py`: (1) mutable default arg, (2) silent copy failure → lying `done` (interaction with `copy_file`'s `except OSError: pass`), (3) `merge_manifest` never purges deleted files | n/3 found, bonus, **false positives counted**, severities |
| T4 design-review | design-review | DESIGN.md contains ~10 categories of flaws: non-atomic manifest, 50k/500 ms polling, mtime only, copying files mid-write, errors swallowed without retry, blocking single thread, undefined deletions/renames, no instance lock, hardcoded config, reuse of `sync()` | categories covered, mechanical depth, zero FP |

## To evaluate a new model (checklist)

1. `models.json`: note the current models and their role.
2. Run the matrix: the 4 tasks for the new model (at least
   `low`/`medium`/`high` if it exposes an effort — effort drives the appetite
   for tools, `low` skips reading code) + the 4 tasks of the incumbent model
   to replace.
3. Verify T2 objectively (`python3 -m unittest` in the copy), score T3/T4
   against the lists above, judge T1 (grounding + trap detection).
4. Extract cost/tokens/duration from the opencode DB (session titles are
   `eval-YYYY-MM-DD-<TASK>-<TAG>`, per `run-eval.sh`; cost = the provider's
   standard API rate, not the plan's real billing).
5. Decision rules (MODELS.md): comparable cost per MTok for bulk roles,
   reviewer of a lineage ≠ impl, `strong-*` judged on tasks that are up to it
   (these tasks are too easy to discriminate Opus/Fable).
6. Write `RESULTS.md` in a dated folder, with the same matrix, and compare
   line by line with the previous eval.

## Effort lesson (valid for any Claude model with a recalibrated effort)

- `low` = fewer tool calls → under-exploration, structural hallucinations on
  T1. Forbidden for roles that must read code.
- `medium` = review/impl sweet spot.
- `high` = orchestration plan (the only level where the model runs the tests
  by itself in our runs).
- `xhigh`/`max` = cost per task converging toward Opus 5.5 → no point for bulk
  roles.

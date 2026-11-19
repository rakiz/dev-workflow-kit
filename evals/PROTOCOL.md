# EVAL PROTOCOL — how this kit measures models (stable contract, do not improvise)

> This file is the single source of truth for the eval machinery. Every new
> session MUST read it before touching `LEADERBOARD.html`, the runners, or
> launching runs. Last amended: 2026-11-16 (grid completion campaign).

## 1. The five decision benches

| Code | Task | Fixture | Runner | Scale |
|---|---|---|---|---|
| O | Orchestration: grounded plan, pipeline agents, verifiable criteria, red-baseline trap | `synccli-eval-repo` (2-commit history recreated) | `run-eval-v5.sh T1` | **/8**: baseline 2 + grounding 2 + agents 2 + criteria 2 − 3/hallucination (v2 rubric; runs scored PASS/PARTIAL/FAIL before 11-16 are re-scored from logs; lost texts are RE-RUN, never left categorical) |
| IR | Impl review: 3 seeded defects + bonus − FPs | `synccli-eval-repo` | `run-eval-v5.sh T3` | n/3 (+2 max bonus) |
| DR2 | Design review (bench v2) | `synccli-eval-repo-v2` | `run-eval-v5.sh T4V2` | /14 |
| I2 | Impl, bench v3 (4 seeded defects + regression tests) | `reportgen-eval-repo-i3` | `run-eval-v4.sh IV2` | /14 |
| D | Design authoring, bench v3 (4 execution-revealed hazards in snaputil.py) | `syncfeat-brief-d1` | `run-eval-v4.sh D1` | /11 |

Retired benches (never decide a seat): I-v1 (T2), DR-v1 (T4), I-v2/RG2 (superseded by RG3 same day).

O-bench evidence rule: the deliverable (the plan) lives in the campaign
**log**, so O logs stay gz-available after a campaign closes (§3) — they are
never deleted, only compressed.

Private answer keys live in the SEPARATE local repo `../evals-keys/`
(RUBRIC-IV2-RG3.md, RUBRIC-D1-v2.md) — never in this public repo; grep for
leakage before campaigns (§3.8 of BENCH-V3-DESIGN.md).

## 2. Measurement rules (frozen — consistency beats cleverness)

1. **Two valid runs per cell**, score = mean. Expensive models (opus, fable,
   astra, and any model >$1/run) may be single-run by owner decision.
2. A run is valid only if it produced a scoreable deliverable. Nulls (provider
   error, timeout, cost-cap kill) are DNF: **re-run them, never score 0**.
   Gemini-family arms die silently ("Failed to process successful response")
   — always re-run a null before recording anything.
3. **Never compare scores across bench versions.** A seat cites ONE bench.
4. Cost per task = parent + delegated children (DB roll-up via parent_id).
5. Every arm runs with an explicit cost cap (fail-closed: `EVAL_ARM_CAP` or
   `EVAL_TIER`, kill at 2×) and a watchdog (default 15 min; sonnet+opus on D
   need `EVAL_TIMEOUT_SECS=1800`).
6. Model effort grid: full effort sweep for cheap/mid models; ONE effort for
   expensive ones (owner rule 11-16). `max` never pays — never roster it.
7. Lineage: review seat ≠ impl seat family. Strong tier must be a DIFFERENT
   family from the cheap tier it escalates. alternative2 = parking for good
   models we hesitate to drop (not a quality ladder).
   Owner-accepted same-family EFFORT escalations (2026-11-17): the code-review
   ladder glm `low` → glm `high` and the design-review ladder minimax
   `medium` → minimax `xhigh` escalate effort within one family — accepted
   because the escalation is effort-backed, not a fresh-family pass (the
   fresh-family pass happens at the next rung). Same-family producer/
   reviewer pairing in the gemini design rungs (hydrogen `high` produces,
   argon `high` reviews) is likewise documented and accepted. The HARD rule
   stands unchanged: **impl and review are never the same family.**
8. Scoring is executed-evidence: paraphrase = 0; probes re-run by the scorer.
9. **Final-report capture (Étape 0, 2026-11-19):** every run dir carries
   `final-report.md` (the run's final assistant message — the last assistant
   message with `finish = stop`, captured by the runner from the opencode DB,
   keyed on the session title; a killed run's last text is intermediate
   narration, never a report) **or** a
   `no-report` marker. A run without one of the two is incomplete by
   construction. **A scoring session that finds no `final-report.md` (and no
   `no-report` marker) treats the run as DNF — re-run it; report-dependent
   rubric points are never scored 0-by-default for a missing report** (the
   capture limitation, not a model failure — the 11-16 p5 batch bug).

## 3. Campaign mechanics

- Cost guard: before each launch, SUM(cost) of the campaign's sessions in the
  opencode DB; driver hard-stops above the owner's cap ($120 for 11-16).
- Queue: roster models first, expensive/unknown last.
- Campaign lifecycle (2026-11-17): while a campaign is OPEN, its per-run
  artifacts live in `evals/<date>/runs/` and its logs in `evals/<date>/logs/`
  (plain files). Once closed (scored + folded into RESULTS.md/EVALS.md +
  leaderboard regenerated), the runs are archived as `runs.tar.gz` and the
  logs gzipped in place. **No `raw/` trees, ever** — run dirs are extracted
  into `runs/` at extraction time and never committed as raw trees; retired
  raw trees (`2026-11-16/raw/`, `2026-11-12/raw*`) are git history only.
- Costs via session titles `eval-<date>-*` (parent + children roll-up,
  `grid2-costs.tsv`). Status per run: `<date>/logs/grid*/_status.txt`.
- After the grid: score everything (fresh scorer per run, rubric-strict),
  fold into EVALS.md (the aggregate) + `<date>/RESULTS.md` (the detail),
  then regenerate the HTML (below). Double-scoring (§5.2) when budget allows.

## 4. LEADERBOARD.html — structure (DO NOT restructure or delete sections)

`evals/LEADERBOARD.html` is the owner-facing summary. Current layout (~583 lines):

1. `#roster` — one row per seat: model·effort, deciding bench, score, $/task,
   fallback. Plus the "why haiku over glm" note. THIS IS THE PAGE'S POINT.
2. `#charts` — 4 scatter SVGs (D, DR2, I2, IR): cost X (log), score Y, dot per
   model (blue = seat holder, grey = no seat, hollow = single run), dotted
   frontier line, seat names on HOVER only. Plus O (text block, no chart) and
   the "why the best-and-cheaper is not always the seat" table.
3. `#codes` — the 5 bench definitions, one line each.
4. `#matrix` — all measurements (Model, Effort, O, IR, DR2, I2, D, cost).
   Model-cell rowspans: first row of each block, 8 tds; continuation rows 7 tds.
5. `#keptout` — rejected models and why.
6. `#method` — 3 lines.

**Regeneration procedure (the part that keeps getting broken):**
- Chart data lives in `evals/gen-charts.py` (CHARTS lists) — edit data there,
  run `python3 gen-charts.py`, it rewrites ONLY the `#charts` section.
- Matrix/roster updates: edit the existing rows in place. Never regenerate
  the file from scratch, never `git checkout` a dirty tree, never delete
  sections to "simplify". History belongs in `EVALS.md`, not in deleting.
- Every bench score shown must trace through the chain: **grid2-scores.csv
  (cell) → grid2-run-scores.tsv (per-run rows) → runs.tar.gz + campaign logs
  (evidence) → RESULTS.md (narrative)**.

## 5. Étape 0 rules (2026-11-19) — harness, stats, seats, finding→remedy map

**(a) Harness capture (see §2 rule 9).** Every run dir carries `final-report.md`
or `no-report`. A scoring without one of the two is a DNF (re-run). Report-
dependent points are never scored 0-by-default.

**(b) Stats rule.**
- Each bench pre-registers its minimum detectable effect (MDE) before the
  campaign that decides on it.
- Every cell is annotated with its n (valid runs).
- A gap smaller than the noise floor (the MDE for that bench) is a **tie**,
  not a ranking. A seat decision on a gap < 1.5 pt is not made without a
  pre-registered rule (see the roadmap, Étape 3).

**(c) Seats ≠ capability.** A seat is a deployment choice (price, family,
exceptions, policy). The leaderboard score orders capability only; it does not
order seats.

**(d) Finding → remedy map** (plan méthodo v2, external review findings):

| Finding | Remedy |
|---|---|
| F1 — patterns, not fine rankings (1-2 runs/cell, 0.33 pt gaps) | Étape 5 — pre-registered MDE, n per cell, gap < noise = tie |
| F2 — brief/probe mismatch on failure policy (I2) | Étape 1 — table of final states before touching prose |
| F3 — I2 is not a feature-acceptance score | Étape 1 — acceptance tests per feature; c′ made winnable or re-weighted ≤1 |
| F4 — DR2 mixes proposal review and conformance audit | Étape 1 — DR-v3 asks both explicitly; true/FP reported separately |
| F5 — D key contains two factual errors | Étape 1 — key credits correct alternative diagnoses |
| F6 — capture chain (report never captured; costs) | Étape 0 — harness capture (§2 rule 9), p5 re-scored, purge |
| F7 — delivery/independence/policy distinct from capability | Étape 3 (real blinding) + Étape 5 (n, margin, CI) + docs (seats ≠ capability, §5(c)) |

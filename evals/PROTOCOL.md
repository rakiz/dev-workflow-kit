# EVAL PROTOCOL — how this kit measures models (stable contract, do not improvise)

> This file is the single source of truth for the eval machinery. Every new
> session MUST read it before touching `LEADERBOARD.html`, the runners, or
> launching runs. Last amended: 2026-11-19 (Étape 1: RG4 gates re-frozen, §5(e)).

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
- Ops layer is part of the standard regeneration: `build-ops.py` -> `2026-11-16/run-ops.tsv` (cost, delivery, latency and tokens per run, keyed DB reads), then `gen-charts.py` (score charts, `#ops`, roster ops column) and `build-matrix.py`; `verify-charts.py` must pass.
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

**(e) RG4 decision gates (pre-registered 2026-11-19, prospective).** These
gates apply to the RG4 I2 bench and to any bench whose MDE is pre-registered.
They are NOT fitted to an RG4 panel distribution: no RG4 judgment layer exists
yet (phase 4a not run). They are stated so the first RG4 decision cannot be
argued after the fact.

- **Gate 1 — the ceiling (14/14) is censoring, not equivalence.** A tie at
  the rubric maximum means "at least the top of what the rubric can see", not
  "equally good". A ceiling tie that blocks a seat decision triggers a **bench
  extension** (a harder fixture or added defect) BEFORE the price rule is
  applied. A ceiling tie on a low-stakes call (no seat changes either way)
  takes the price rule and is documented as **ceiling-censored** in the cell's
  note.
- **Gate 2 — the decision gap is the noise threshold.** On I2 (/14), a gap
  below **1.5 pt** is a **TIE**, and the price rule applies. This is the
  pre-registered threshold of §5(b), now the operative gate. Its empirical
  basis is NOT yet established: the observed panel spread on I2 (scorer
  disagreement across 35 cells with n ≥ 2: median 1.0, mean 1.66) measures
  scorer disagreement, not run-to-run noise, and cannot stand in for the
  MDE. Étape 5 must measure the run-to-run noise and pre-register the MDE.
  Until then the 1.5 pt gate is not applied to D, DR2, O or IR, whose MDEs are
  unmeasured.
- **MDE note (Étape 5).** Every cell is annotated with its n (valid runs).
  A gap below the bench's MDE is **not a ranking**: it is a tie, whatever the
  point difference reads.
- **Tie rule (ratified 2026-11-20).** Eligibility = two scorer families + ≥2
  valid runs; the cheapest arm inside the MDE band wins the seat.

## 6. THE CAMPAIGN RECIPE (ordered checklist, 2026-11-20)

Run the steps in order. A step that fails stops the campaign; do not skip ahead.

1. **Write the campaign file** (`<stem>.json`, schema in `run-campaign.py`
   docstring; example: `campaign-example.json`): arms, per-arm `cap`, `budget_usd`.
   The total of caps must fit the owner's cap. Never exceed it; never raise it
   without a new owner go.
2. **Validate, then launch**: `python3 run-campaign.py <stem>.json --self-check`
   (no launch, checks the file, the runners, the DB preflight), then
   `python3 run-campaign.py <stem>.json`. Outputs: `<stem>.status.txt`
   (one line per arm attempt: time, job, arm, status, campaign spend) and
   `<stem>.logs/`. The runners capture each final report into the run dir
   (A1); a missing report is a DNF re-run signal, never a scored 0.
   The campaign date must be today (runner titles use `date +%F`).
3. **`build-ops.py`** -> `<DAY>/run-ops.tsv` (DAY is hard-coded in the script:
   currently `2026-11-16`; cost, delivery, latency, tokens).
4. **Panel scoring**: a scorer of a run's family is never used on that family's
   runs (self-family excluded). Blinded per-candidate dirs once Étape 3 lands;
   until then, the unblinding limits of §5 apply and are recorded.
5. **`aggregate-panel.py`** -> panel scores (divergence rules per bench).
6. **`build-matrix.py` + `gen-charts.py` + `verify-charts.py`** (must print OK).
7. **`RESULTS.md` + the ledger fold** (`extract-runs.py` / runs ledger).
8. **Close the campaign when superseded** (manual, no tool yet): append a closing
   line to the status file and keep the campaign file as the record.
9. **No commit or push without the owner's explicit go on the shown diff.**
   Briefs never carry a commit or push instruction. The agent permission rails
   enforce it: push = deny, commit = ask.

## 7. THE NEXT-CAMPAIGN MANDATORY REQUIREMENTS (adopted from the Sol review)

These gate the next decision campaign. Source and steps: `ROADMAP-METHODO.md`.

- **Held-out fixtures.** The spec is pre-registered BEFORE any arm runs. The
  fixture author is not the results interpreter. Each held-out fixture is
  single-use and rotated per model generation. Its answer keys stay PRIVATE
  until the deciding campaign closes. Candidates run with network isolation.
- **Scorer blinding.** Each candidate is scored in an isolated directory with
  vendor strings stripped and randomized IDs. The blinding is unsealed only
  after the scores lock.
- **Smoke A/B before the held-out exists.** 5 tasks, 3 arms: the ROI question
  (cheap-first plus escalation, vs sonnet alone, vs sonnet plus one review).
  Judged by a blind adjudicator with a pre-registered checklist; defects that
  escape, delivery rate, latency and the total human cost are all recorded.

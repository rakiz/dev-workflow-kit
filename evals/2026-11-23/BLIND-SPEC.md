# BLIND-SPEC — Étape 3 residual-bias measurement (blind vs unblind re-scoring)

Pre-registered 2026-11-23, BEFORE any blind score is read. Owner decision 2026-11-23:
Étape 3 is measured now (the last open ROADMAP-METHODO step after Étape 5's completion
and Étape 4's A/B). Unblinding happens only after both scorer batches are locked
(TSVs written); the analysis script runs after that; this file is committed first.

## Question

Does the standing 2-family panel score differently when it cannot identify the model
that produced a run? Residual bias = unblind score − blind score, per run, per family.
A systematic positive gap means the panel over-scores when it knows (or believes) the
model; a systematic negative gap means over-penalization.

## Sample (mechanical selection rule, no discretion)

Per decision bench, the delivered `scored` run with the HIGHEST official score and the
one with the LOWEST official score → 10 runs. Ties: lowest run_id lexicographic wins
(fixed, mechanical). Sources (each bench's runs live with its campaign):

- O, IR, DR2, D: `evals/2026-11-16/grid2-run-scores.tsv` (status `scored`, delivered;
  score column; artifacts in `evals/2026-11-16/runs/`).
- I2-RG4: `evals/2026-11-20/rg4-run-scores.tsv` (`mean` column, status `scored`;
  artifacts in `evals/2026-11-20/runs/`, files `IV4-*`).
- exclusion: a bench with no usable artifacts loses its slots (none expected).

Rationale: the extremes are where halo effects (famous-model bonus at the top,
pile-on at the bottom) would show if they exist.

## Blinding protocol

- The scorer sees: the bench rubric (private, unchanged), the fixture/brief inputs
  (model-neutral), and the candidate deliverables under a RANDOM ID (R01-R10).
- Anonymization on the deliverable copies, mechanical sed pass (case-insensitive):
  model names (glm, haiku, sonnet, opus, fable, minimax, qwen, kimi, muse, gemini,
  argon, carbon, hydrogen, neon, 1017, deepseek, astra, sol, terra, mai, gpt-6),
  provider ids (github-copilot, fireworks, ai-gateway), effort words (low/medium/
  high/xhigh — replaced by "default"), agent names (cheap-code, cheap-review,
  cheap-mech, strong-*), "opencode". Over-stripping is acceptable; under-stripping
  is a defect (a leak grep runs before launch and its count is recorded in the
  RESULTS — target 0 hits).
- The ID→run mapping lives ONLY in the private repo (`blind-sample/MAPPING.tsv`,
  chmod 600) and is not read by any scorer (the scorer prompt forbids listing the
  directory).
- The scorer prompt is the catchup bench prompt with the campaign sentence removed:
  the batch file says nothing about which models exist in the sample.

## Scorers and arms

- The standing 2-family panel: glm (ai-gateway-misc/fw-glm-5.3-flash, high) and
  minimax (fireworks m3p1-flash). Both are non-family for every sampled model —
  no self-family exclusion applies (the grid's own sonnet/haiku readings are NOT
  re-run: this measures the standing panel, not the 2026-11-16 4-family panel).
- One batch per scorer (10 rows mixed benches — the batch carries a bench column and
  the prompt points at the right rubric per bench). Same output TSV shape as the
  catchup panels: `run_id  bench  family  score  fp  breakdown  notes`.

## Budget and guard

- Guard $3.00 total (DB delta on `panel-%BLIND-%` sessions since launch), per-session
  cap $0.60 like the catchup panels, kill at 2× cap. Expected ~$0.3-0.6.

## Analysis (runs after unblinding, no discretion)

- Per run: blind score = mean of the 2 families (same rule as official).
- Residual = official (unblind) − blind, per run; summarized per bench (n=2) and
  overall (n=10): mean, min, max.
- Verdict bands (pre-registered): |mean overall| < 0.5 pt → "no operative bias, Étape 3
  closed"; 0.5-1.0 → "note the bias in PROTOCOL §5, keep the panel"; > 1.0 → the panel
  must move to permanent blinding (candidate-only dirs) for future campaigns — an
  owner decision, not automatic.
- n=10 is a smoke measurement like the A/B: it bounds gross bias, it is not an MDE.

## Artifacts

- Public: this file, `evals/2026-11-23/BLIND-RESULTS.md` (numbers + verdict only —
  no rubric text, per the key-purge rule).
- Private: `evals-keys@score-logs/2026-11-23/blind-sample/` (anonymized dirs, batch
  files, scorer logs, TSVs, MAPPING.tsv).

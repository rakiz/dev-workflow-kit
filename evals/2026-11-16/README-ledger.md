# Run ledger — `grid2-run-scores.tsv`

One row per run, every campaign since RG3. The TSV is the single source; the
original 10 columns keep their positions (`run_id bench model effort tag status
score dnf_reason evidence_path notes`) so existing readers still parse it.

Columns added: `bench_version` (RG3 / RG4 / T4V2 / T4V3 / T3 / T1), `campaign`,
`date` (evidence file mtime), `delivered` (yes/no; no = status DNF), `fp_count`
(false-positive deduction, signed, from notes or the scorer note), `dimension_breakdown`,
`panel_readings`, `panel_scope`, `ledger_source`.

Sort: bench, model, effort, run_id.

## Counts

| bench | bench_version | campaign | rows |
|---|---|---|---|
| D | RG3 | RG3 grid2 (2026-11-16/17) | 92 |
| I2 | RG3 | RG3 grid2 | 91 |
| O | RG3 | RG3 grid2 | 88 |
| DR2 | RG3 | RG3 grid2 | 49 |
| IR | RG3 | RG3 grid2 | 36 |
| DR2 | T4V2 | RG3 grid2 (T4V2 logs) | 4 |
| IR | T3 | RG3 grid2 (T3 logs) | 4 |
| O | T1 | RG3 grid2 (T1 logs) | 4 |
| I2-RG4 | RG4 | RG4 (2026-11-20) | 42 |
| I2-RG4 | RG4 | RG4 pilot re-run (2026-11-19) | 9 |
| DR-v3 | T4V3 | T4V3 r43 (2026-11-19) | 4 |
| **total** | | | **423** |

Status: scored 348 · DNF 58 · superseded 9 · retry 2 · unscored 6.
Delivered: yes 365 · no 58.
Breakdown: 51 rows with probe/suite breakdown (RG4, `rg4-deterministic.tsv`);
6 RG3 rows with notes-parsed base/amb fields; 361 total-only (for these,
`runs.tar.gz` or a log holds the detail, and the row says so); 5 n/a.
FP rows: 11.

## Sources (consolidated, dedupe)

- `grid2-run-scores.tsv` (original, 368 rows, `git show HEAD`).
- `2026-11-20/rg4-run-scores.tsv` + `rg4-deterministic.tsv` (42 rows).
- `2026-11-19/RESULTS.md` section 7.1 + probe table: 9 pilot rows (IV4 r41/r42/r41b),
  4 T4V3 r43 rows (no recoverable score; `unscored`).
- `2026-11-16/panel-scores.csv`: joined per (model, effort, bench); `panel_scope` is
  always `cell`, so it is NOT a per-run reading.

Dedupe: 0 duplicate run_ids; 0 byte-identical logs across the 372 files in
`2026-11-16/logs/`. The D/I2 rows that share a model+effort+tag are separate runs
(distinct logs), so they stay separate rows.

## Open gaps (not resolved here)

- Per-dimension breakdown (suite/a/b/c'/d/amb/base) is recoverable only for RG4 and the
  few notes-parsed RG3 rows. The sheets the brief names (`evals-keys/score-logs/`, partA/H/partB)
  do not exist in this repo.
- 10 `grid2-scores.csv` cells have no run row under their model+effort (hydrogen-low,
  argon-low/medium, gem38-low/high, sol-low/xhigh, muse-low/high/xhigh). They were untraced
  before the cleanup too.
- The 9 pilot rows: the haiku-brief values (11.5/13.5/14/14) are not on disk; only the
  GLM-family readings are recorded.
- 4 T4V3 r43 runs have no score in any sheet.
- The 4 `I2-gemini-4-neon-*` run dirs have no ledger row; they were kept.
- Rows whose artifact was removed by the 2026-11-20 cleanup have a note: "recover from git HEAD 4bb9fcc".

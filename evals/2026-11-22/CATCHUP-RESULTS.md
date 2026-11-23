# Catch-up campaign mai-code-2 (2026-11-22) — results, arbitration, roster proposal

Status: runs DONE (10/10 delivered), scoring DONE (2-family panel glm + minimax; 1 sonnet
arbitration on O). One scoring r2 was cut by a machine reboot at 22:56 and re-run to
completion on 2026-11-23 (~00:52). Arbitration per PROTOCOL §5(e). **No seat changes
applied. Proposal: none takes a seat (owner validation pending — §7).**

Models: `github-copilot/mai-code-2` and `github-copilot/mai-code-2-flash` (Microsoft MAI,
new on the gateway 2026-11-22; `mai-code-1.1-flash` also exists and was not tested —
superseded by the 2.x line). Campaign `catchup-mai-2026-11-22`, runner `run-campaign.py`,
10 attempts (2 models × 5 benches: O/T1, IR/T3, DR2/T4V2, I2-RG4/IV4, D/D1), 1 attempt
per arm, no variant (default effort only — the models expose no effort ladder).

## 1. Gateway price table (per MTok USD; source: `opencode models github-copilot --verbose`, 2026-11-23)

| Model | Gateway id | In | Out | Cache read | Status |
|---|---|---|---|---|---|
| mai-code-2 | github-copilot/mai-code-2 | 1 | 5 | 0.05 | USED (exact model) |
| mai-code-2-flash | github-copilot/mai-code-2-flash | 0.1 | 0.5 | 0.01 | USED (exact model) |

AI Gateway (ai-gateway-misc) does not list either model — github-copilot is the only
gateway, no preference-rule arbitration needed (PRICE-FRESHNESS: verified 2026-11-23).

## 2. Spend (sqlite, sessions titled `eval-2026-11-22%catchup-mai%` and `panel-%MAI%`, parent + children)

| Phase | Attempts | Spend |
|---|---|---|
| Runs (both models, 5 benches each) | 10 ok | **$0.1793** (budget $25) |
| Scoring panel (14 sessions incl. 2 r2 killed by the reboot and re-run) | — | **$0.6441** (guard $6) |
| **Campaign total** | 24 | **$0.8234 of $40** |

## 3. Scores (official = 2-family mean; O of mai-code-2 = sonnet arbitration)

Scorer families: glm (ai-gateway-misc/fw-glm-5.3-flash high) and minimax
(m3p1-flash). No mai-family scorer exists; both scorers are non-family.

| Model | O (/8) | IR (/3+) | DR2 (/14) | I2-RG4 (/14) | D (/11) |
|---|---|---|---|---|---|
| mai-code-2 | **0** (arbitrated; glm 1, minimax 4, sonnet-ARB 0) | 2.5 (glm 2;minimax 3) | 6.0 (6;6) | 9.5 (glm 10;minimax 9) | 5.0 (5;5) |
| mai-code-2-flash | 5.0 (5;5) | 2.0 (2;2) | 6.5 (glm 6;minimax 7) | 9.0 (glm 10;minimax 8) | **DNF** — no deliverable |

Breakdowns of note:

- **mai-code-2 O = hallucination FP.** The plan assumes a green test baseline (the red
  baseline is never run: `test_synccli.py:22-24` fails when executed) and cites a
  nonexistent `synccli/` package / `synccli/*.py` glob. glm scored it 1 with hall=1
  (FP=1); minimax scored 4 with hall=0 (same factual finding, no hall deduction) —
  spread 3 ≥ threshold 2 → sonnet-high arbitration per §5(e): **0, FP=1, hall=1**.
  Two of three readers agree on the hallucination; the arb is the official value.
- **mai-code-2-flash O** misses the red baseline the same way (R0, both scorers) but
  grounds every file/symbol citation correctly (G2, hall=0): 5/8.
- **Red-baseline trap: BOTH models fail it** (R0 on O across the board). The honesty
  pattern that repeatedly separates seats on this bench — none of the mai arms executes
  the test suite before claiming success.
- **I2-RG4 is mai's best bench** (9.5 / 9.0): correct probes (a=3, c opens=1, d
  exit-1-and-intact), but no (a)/(b) regression tests and the baseline reasoning is
  paraphrased, not quoted — the gap to the seat holder (haiku default 11.75) is exactly
  the verification half.
- **IR**: mai-code-2 found the cross-file root cause (`copy_file` swallows `OSError`,
  `incremental.py:21`/`synccli.py:68`) with a 1-family FP (glm); flash missed the
  cross-file bonus.
- **mai-code-2-flash D = DNF**: the run completed but authored no `DESIGN-d1.md` — the
  model refused, blocked on a "docs connector" it believed it needed (`final-report.md`:
  "I can't access the required docs connector"). Scored per the DNF rule (no row, never
  0-by-default). The IR run of the same model **delegated** its review to a
  minimax-m3p1-flash `xhigh` child ($0.0203 of the $0.0218 arm) — cost is
  delegation-inclusive per the 2026-10-23 delegation rule.

## 4. Cost per task (DB roll-up, parent + children)

| Model | O | IR | DR2 | I2-RG4 | D |
|---|---|---|---|---|---|
| mai-code-2 | $0.0147 | $0.0100 | $0.0078 | $0.0637 | $0.0463 |
| mai-code-2-flash | $0.0015 | $0.0218 (incl. child) | $0.0010 | $0.0119 | $0.0006 (DNF) |

mai-code-2-flash is the cheapest per-task model ever measured on this grid at the
default effort (DR2 $0.001 vs minimax-medium's $0.04 seat) — and it scores below every
seat holder. Price does not save it (§7).

## 5. Comparison with the seat holders (full grid: LEADERBOARD #matrix)

| Bench | Seat holder | Score | mai-code-2 | mai-code-2-flash |
|---|---|---|---|---|
| O /8 | glm-5.3-flash high | 7 | 0 | 5 |
| I2-RG4 /14 | haiku default (cheap-code) | 11.75 | 9.5 | 9.0 |
| IR /3+ | minimax xhigh (cheap-review) | 4.33 | 2.5 | 2.0 |
| DR-v2 /14 | minimax medium (cheap-design-review) | 8.0 | 6.0 | 6.5 |
| D /11 | haiku medium (cheap-design) | 8.08 | 5.0 | DNF |

## 6. Scoring DNFs / incidents

- mai-code-2-flash D: model refusal (no deliverable) — DNF, no row, recorded
  `completed` with empty score in run-ops.tsv.
- minimax I2-RG4 r2: killed mid-run by the machine reboot (2026-11-22 22:56); re-run to
  completion 2026-11-23 00:52 ($0.1102). The earlier r2 attempts
  (`panel-minimax-CATCHUP--MAI-4 I2-RG4-r2` $0.048, `panel-minimax-CATCHUP-I2-RG4-MAI-4-r2`
  #1 $0.0066) produced no TSV and were superseded.
- Panel private logs: `evals-keys@score-logs/2026-11-22/panel-catchup-mai/` (run
  snapshots, prompts, batch TSVs; public artifacts only in this repo).

## 7. Seat changes

- **Applied: NONE.**
- **Proposal: NONE takes a seat.** Every measured cell is below its bench's seat holder;
  no cell is within reach of a gate (I2-RG4 gap 2.25–2.75 pts, above the 1.5 MDE, in the
  WRONG direction; O arbitrated to 0). n=1 per bench could not take a seat anyway.
- **Roster recommendation to the owner: keep the roster unchanged; do NOT promote mai.**
  The flash tier is remarkable on price ($0.001–0.022/task) but its quality floor
  (red-baseline miss, below-seat everywhere, one refusal) and single-run status place it
  behind the incumbents it would have to displace. mai-code-2 (non-flash) additionally
  hallucinates under pressure on O — the same external-claim pattern documented for
  other frontier models.
- Watch items: (a) a mai-2 effort ladder or a 2.x price move could reopen the cheap-tier
  screening — re-enter on a `low`/`medium` arm comparison vs haiku-default if Microsoft
  ships efforts; (b) the flash tier is a candidate for the cheapest non-seat helper
  (explore-class) if the owner wants a sub-cent runner, but that is a new rung, not a
  seat — decide separately; (c) if a second O run is desired for flash (its 5/8 is the
  only non-embarrassing mai number), the marginal cost is ~$0.002 + scoring.

## 8. Fold status

- `grid2-scores.csv`: 2 mai rows added (default effort, notes carry the per-family
  readings, FP counts and the DNF); the pre-existing malformed `argon,high` row (unquoted
  notes, corrupt since the "RG4 closed" commit — argon-high I2-RG4 silently charted as
  9.5) repaired: notes quoted, I2-RG4 = **12.5** (the 2-run official, corroborated by
  `2026-11-20/rg4-standings.csv` and `reasons.py`).
- `run-ops.tsv`: 10 rows appended (costs parent+children, tokens, durations; flash-D
  `completed`/empty score). `build-ops.py` MODEL_KEYS gained the two mai slugs (flash
  first — substring order).
- `gen-charts.py`: FULLIDS + FAM_COLOR (mai → #e11d48 rose), X0 0.004 → 0.0005
  (mai-flash's $0.001 DR2 task needs the lower decade floor; pure monotone rescale).
- `build-matrix.py`: MODELS + STARS gained the mai entries; `LEADERBOARD.html`
  regenerated (charts + matrix; #roster and #keptout untouched — no seat change).
- `reasons.py`: why-out entries for both models (O arb, refusal, delegation).
- `verify-charts.py`: **PASS — 195/195 dots, 85/85 findings/FP tooltips** (195 vs 186 at
  HEAD: +9 mai dots, argon I2-RG4 dot restored).
- COMPARATORS.md: mai entry added (§2026-11-22).

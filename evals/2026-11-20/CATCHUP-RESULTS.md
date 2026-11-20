# Catch-up campaign (2026-11-20) — results, arbitration, price table

Status: runs DONE (17 attempts: 16 delivered, 1 DNF), scoring DONE except the minimax
panel on bench O (DNF after one r2 re-run). Arbitration per PROTOCOL §5(e) and §2.
No seat changes applied. Proposals: none rule-demanded.

## 1. Gateway price table (per MTok USD; source: `opencode models <provider> --verbose`, 2026-11-20)

| Model | Gateway id | In | Out | Cache read | Status |
|---|---|---|---|---|---|
| gpt-6.2-astra | github-copilot/gpt-6.2-astra | 8 | 40 | 0.4 | USED (exact model) |
| gpt-6.2-astra | ai-gateway-openai | — | — | — | not listed (AI Gateway has gpt-6-astra = other version, $7.4/$37/0.74) |
| claude-fable-5.2 | github-copilot/claude-fable-5.2 | 8 | 40 | 0.2 | USED (exact model) |
| claude-fable-5.2 | ai-gateway-anthropic | — | — | — | not listed (AI Gateway has claude-fable-5 = other version, $10/$50/1) |
| gemini-4-neon | github-copilot/gemini-4-neon | 3 | 15 | 0.15 | USED (only listing) |
| grok-4.7 | github-copilot/grok-4.7 | 2 | 6 | 0.5 | USED (answered on probe) |
| grok-4.7 | ai-gateway-misc/grok-4.7 | — | — | — | **NOT CONFIRMED.** Absent from the local catalog (cache refreshed 11-20); probe `opencode run -m ai-gateway-misc/grok-4.7` returned `UnknownError: Unexpected server error` twice (refs err_cf96c34a, err_350f2997). The owner's "subsidized listing" is NOT verifiable locally; the subsidized price is unverified. ai-gateway-misc lists only grok-4.3 ($0.925/$1.85). |

Preference rule (AI Gateway id when listed): not applicable to astra / fable (AI
Gateway lists only other versions; owner confirmed github-copilot ids). For grok the
AI Gateway id failed the probe twice → fallback to github-copilot (the planned
"cheapest legal gateway").

## 2. Spend (sqlite, sessions with title `eval-2026-11-20%catchup-%`, parent + children)

| Campaign | Attempts | Spend |
|---|---|---|
| astra (5 single runs) | 5 ok | $1.8204 (budget $25) |
| fable-5.2 (2 single runs) | 2 ok | $1.1225 (budget $8) |
| neon (6 attempts) | 5 ok + 1 DNF (DR2 a2, no-report, $0.0572 counted) | $0.7452 (budget $4) |
| grok-4.7 (4 attempts) | 4 ok | $0.7156 (budget $2) |
| **Runs total** | 17 | **$4.4037** |
| Scoring panel (`panel-%CATCHUP-%`, 11 sessions incl. 1 killed r2) | — | **$0.2946** (guard $6) |
| **Phase total** | | **$4.6983 of $40** |

## 3. Scores (2-family mean; per-run = mean of its scorer families; cell = mean of runs)

Scorer families: glm (ai-gateway-misc/fw-glm-5.3-flash high) and minimax (m3p1-flash).
Minimax O batch: DNF (see §6). O is scored by glm only (one family).

| Model | O (/8) | IR (/5) | DR2 (/14) | I2-RG4 (/14) | D (/11) |
|---|---|---|---|---|---|
| gpt-6.2-astra | 8 (glm 8; n=1; 1 fam) | 3.0 (3;3; n=1) | 8.5 (8;9; n=1) | 3.0 (3;3; n=1) | 5.5 (5;6; n=1) |
| claude-fable-5.2 | 8 (glm 8; n=1; 1 fam) | 4.0 (4;4; n=1) | not run | not run | not run |
| gemini-4-neon | 8.0 (8;8; n=2; 1 fam) | 2.75 (run a1 2.5, a2 3.0; n=2) | 8.0 (a1 only; n=1 — a2 DNF) | not run | not run |
| grok-4.7 | not run | 2.5 (a1 3.0, a2 2.0; n=2) | 9.0 (a1 8.0, a2 10.0; n=2) | not run | not run |

Raw per-family values (glm;minimax): astra IR 3;3, DR2 8;9, I2-RG4 3;3, D 5;6. fable IR 4;4.
neon IR a1 2;3, a2 3;3; DR2 a1 6;10. grok IR a1 2;4, a2 1;3; DR2 a1 7;9, a2 9;11.
Scorer FP: grok IR a1 FP=1 (glm), all others 0.

Panel note: the glm and minimax reads differ on DR2 for every run (minimax +1 to +4) —
the recorded constant family offset (§5). The 2-family mean is the official score.

Breakdowns (O, glm, red-baseline honesty R = 0-2): astra R2, fable R2, neon R2 (a1, a2).
All three pass the red-baseline trap (no hallucination, hall=0).

## 4. Cost per task (DB roll-up, parent + children; the DNF's cost is real spend and shown)

| Model | O | IR | DR2 | I2-RG4 | D |
|---|---|---|---|---|---|
| gpt-6.2-astra | $0.307 | $0.318 | $0.382 | $0.313 | $0.501 |
| claude-fable-5.2 | $0.626 | $0.497 | — | — | — |
| gemini-4-neon | $0.158 (0.186; 0.130) | $0.128 (0.131; 0.125) | $0.116 (a1; DNF a2 $0.057 excluded) | — | — |
| grok-4.7 | — | $0.165 (0.181; 0.150) | $0.193 (0.237; 0.148) | — | — |

Seat references (roster/MODELS.md, grid2): IR seat M3.1 xhigh 4.33 @ $0.014; DR2 seat
M3.1 xhigh 11.5 @ $0.03; D seat 1017 high 8.25 @ $0.12 (haiku medium 8.08 @ $0.02); O seat glm high 7 @ $0.005.

## 5. Arbitration (PROTOCOL §5(e), §2 rule 1, §2 rule 7)

Eligibility: ≥2 valid runs AND 2 scorer families. Single-run cells are SCREENING ONLY.

| Model · bench | Cell | n | Families | Seat holder (ref) | Gap | Gate | Verdict |
|---|---|---|---|---|---|---|---|
| astra · O | 8.0 | 1 | 1 | glm high 7 | +1.0 | O: no operative MDE; n=1, 1 fam | screening-pass (not eligible) |
| astra · IR | 3.0 | 1 | 2 | M3.1 xhigh 4.33 | −1.33 | IR unmeasured MDE | no-seat (screen) |
| astra · DR2 | 8.5 | 1 | 2 | M3.1 xhigh 11.5 | −3.0 | DR2 unmeasured MDE; n=1 | no-seat (screen) |
| astra · I2-RG4 | 3.0 | 1 | 2 | haiku default 11.75 | −8.75 | I2 gate 1.5 — far outside | no-seat |
| astra · D | 5.5 | 1 | 2 | 1017 high 8.25 | −2.75 | D gate 1.0 — outside | no-seat |
| fable-5.2 · O | 8.0 | 1 | 1 | glm high 7 | +1.0 | as astra | screening-pass; diagnostic: honest on red baseline (R2, hall 0) |
| fable-5.2 · IR | 4.0 | 1 | 2 | M3.1 xhigh 4.33 | −0.33 | IR unmeasured; n=1 | screening-pass; cannot take a seat (n=1) |
| neon · O | 8.0 | 2 | 1 | glm high 7 | +1.0 | O no MDE; 1 family | not eligible (1 family) |
| neon · IR | 2.75 | 2 | 2 | M3.1 xhigh 4.33 | −1.58 | IR unmeasured | no-seat (below seat; no margin claim) |
| neon · DR2 | 8.0 | 1 | 2 | M3.1 xhigh 11.5 | −3.5 | n=1 (a2 DNF) | screening only, no-seat |
| grok-4.7 · IR | 2.5 | 2 | 2 | M3.1 xhigh 4.33 | −1.83 | IR unmeasured MDE; margin 1.83 not "large" | eligible; no-seat |
| grok-4.7 · DR2 | 9.0 | 2 | 2 | M3.1 xhigh 11.5 | −2.5 | DR2 unmeasured MDE | eligible; no-seat (below seat; price: $0.19 vs $0.03/task = 6.4× the seat at lower score) |

Arithmetic that decides: no cell beats its seat holder (all gaps negative for review and
design; astra O +1 is single-run single-family). Gates: D and I2 gaps are all larger
than 1.0 and 1.5. IR and DR2 MDE is unmeasured (§5(b)): the largest in-sample gap is
grok DR2 −2.5, with n=2 per cell and two families. Under §5(b) we do not rank below an
unmeasured MDE, so each is recorded as "below seat, no ranking claim". No model is
within any gate to tie, so the price rule does not come into play.

Lineage (§2 rule 7): not binding — no candidate takes a seat. Recorded for any future
seat call: fable (claude), astra (openai), neon (google), grok (xai) are all families
distinct from the minimax/glm scorers and from the haiku/minimax seat holders.

Grok price angle (owner request): at the github-copilot price ($2/$6 per MTok) grok's
measured cost is $0.165 IR and $0.193 DR2 per task, 6× the DR2 seat ($0.03) with a lower
score. No seat contention on price. The subsidized AI Gateway price was not verifiable,
so no subsidized-price arithmetic is shown.

## 6. Scoring DNFs

- minimax O batch (batch 1): the first run hit a mistyped path (`/Users/sebastien.mendes`),
  auto-rejected; no TSV. The r2 re-run (title `panel-minimax-CATCHUP-O-1-r2`) stalled
  at 11361 bytes for ~10 min and was killed; no TSV. O has one scorer family → not
  eligible for a seat on O anyway.
- neon DR2 a2 (run): no-report marker (silent gemini stall). DNF, n=1 for that cell.

## 7. Seat changes

- Applied: NONE.
- Proposed: NONE rule-demanded. (No cell passes the eligibility + gap > MDE rule.)
- Watch items: (a) grok DR2 9.0 at n=2 is the strongest new cell; re-enter when the
  DR2 MDE is measured or when grok clears 11.5. (b) fable-5.2 O 8/8 with honest baseline:
  a diagnostic pass, not a seat. Re-screen on a second O run if fable is proposed for
  impl or review. (c) astra re-entry (COMPARATORS) is for the deep rung (opus); astra's
  D 5.5 and I2 3.0 measured here do not reopen it.

## 8. Fold status

- COMPARATORS.md: updated (astra measured, fable-5.2 screened, grok status).
- LEADERBOARD #matrix and gen-charts chart data: NOT changed. The chart dots and the
  cost roll-up come from the 2026-11-16 grid CSV and run-ops.tsv (build-ops.py is keyed to
  that DAY). Adding catch-up dots needs a separate extension of those inputs and is not
  done here. verify-charts still passes on the unchanged data (186/186 dots, 81/81
  tooltips).
- roster/MODELS.md: NOT changed (no rule-demanded seat edit).

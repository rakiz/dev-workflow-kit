# 2026-11-19 — Étape 1 record (contract repair: I2 policy A, c′ earnable, D key v3, DR-v3)

Status: phases 1–3 executed and committed; phase 4 PARTIAL (see §6 "Not done").
No seat change. Nothing here decides a seat (PROTOCOL §5(c)).

## 1. Contract repair — what changed (verified)

| Item | Change | Where | Proof |
|---|---|---|---|
| I2 failure policy | **A (preservation)** stated explicitly: a failed transform exits 1, emits nothing new, leaves previous report.json/report.html and cache byte-intact | `evals/reportgen-eval-repo-i4/GOAL.md` (Invariants, first bullet) | `diff` vs RG3 GOAL.md = that bullet only |
| c′ made earnable | acceptance: rules file read at most once per run; count reported | GOAL.md (second bullet) | same diff |
| RG4 fixture | `reportgen-eval-repo-i4/`, tree hash `be19bfc8409e04a391068d0c3588bc0f7d23e196798d78116a539fd19cbc2a6e` (method: BENCH-V3 §3.6, `__pycache__` excluded). Method check: RG3 hash reproduces `3d2c1a30…` | `evals/BENCH-V3-DESIGN.md` §3.6 | `shasum` run 2026-11-19 |
| RG3 | calibration-retired (unspecified failure policy, F2); not run again | BENCH-V3 §3.6 | — |
| RG4 rubric | `evals-keys/RUBRIC-IV2-RG4.md` v1, max 14 (2+6+4+1+1); policy-A probe (d); c′ = fix 2 + test 1 + quoted counts 1 | private repo commit `729681c` | file |
| Runner | task `IV4` = RG4 fixture (IV2 = RG3 kept for archived protocol); `extract-runs.py` maps `IV2-RG4`, picks pristine RG4 for diffs by GOAL.md text | `run-eval-v4.sh`, `extract-runs.py` (commit `e81e5e2`) | `bash -n`, `ast.parse` OK |
| DR-v3 prompt | task `T4V3` in `run-eval-v5.sh`, prompt verbatim from owner (proposal + prototype conformance). **T4V2 kept unchanged** (closed bench; a prompt change = a new bench version, §2 rule 3) | `run-eval-v5.sh` (commit `adfcb0b`) | `bash -n` OK |
| D key v3 | `evals-keys/RUBRIC-D1-v3.md`: H4 also credits the `<=` diagnosis (full point, diagnosis alone per owner ruling); H2 wording "linear in total files visited" (not quadratic). v2 kept | private commits `893139c`, `6682e54` | file |

### 1.1 Probe layer verified on the pristine RG4 tree (2026-11-19)

Executed `probes-rg4.sh` on `reportgen-eval-repo-i4` (the defects must be present here):

- probe a: `merchant.distinct=99` (defect present ✓)
- probe b: `REPORTS-DIFFER`, `generated_from=2` (defect present ✓)
- probe c′: `rules_opens=4` (defect present ✓)
- probe d: `exit=0`, `PREVIOUS-OUTPUT-OR-STATE-CHANGED` (defect present ✓)

The probes discriminate; the fixed/unfixed readings below are meaningful.

### 1.2 D-key v3 alternative probe verified

On `syncfeat-brief-d1/snaputil.py` (shipped, unfixed): `is_stale(d, T)` with `os.utime(d,(T,T))`, T=1764945600 → **True** (the docstring says NOT stale at exactly ref). On the fixed ns form: False. Verified 2026-11-19.

## 2. RG4 re-pilot (phase 3a) — 8 valid runs, $ per run

Driver: `evals/2026-11-19/logs/phase3/driver.sh` (fail-closed budget: phase-3 spend counted from the DB before every launch, arm launched only if spend + 2×cap ≤ $5; cap `EVAL_ARM_CAP=1.00`, `EVAL_TIMEOUT_SECS=1800`). Phase-3 spend total: **$2.2252** (DB, titles `IV2-RG4` + `T4V3`). A pre-existing $3.37 of unrelated sessions dated 2026-11-19 (gemini grid) is NOT counted here.

Executed rubric layer (`grid2-scores-rg4.csv`):

| Arm | Run | Suite green | a | b | c′ reads | d (policy A) | Own tests failing on pristine |
|---|---|---|---|---|---|---|---|
| haiku default | r41 | ✓ | fixed | **NOT fixed** (gen=2) | 1 | exit1 INTACT | 8/21 |
| haiku default | r42 | ✓ | fixed | fixed | 1 | exit1 INTACT | 8/21 |
| minimax xhigh | r41 | — | DNF (no final report) → r41b | | | | |
| minimax xhigh | r41b | ✓ | fixed | fixed | 1 | exit1 INTACT | 12/25 |
| minimax xhigh | r42 | ✓ | fixed | fixed | 1 | exit1 INTACT | 14/28 |
| haiku high | r41 | ✓ | fixed | fixed | 1 | exit1 INTACT | 15/29 |
| haiku high | r42 | ✓ | fixed | fixed | 1 | exit1 INTACT | 12/26 |
| opus default | r41 | ✓ | fixed | fixed | 1 | exit1 INTACT | 10/10 (test_regressions.py) |
| opus default | r42 | ✓ | fixed | fixed | 1 | exit1 INTACT | 9/9 (test_regressions.py) |

Reading the table honestly:
- Probes a, c′, d are fixed in every valid arm; b is fixed in 7 of 8 (haiku default r41 fails it).
- "Own tests failing on pristine" counts the number of the arm's own tests that fail (or error) against the unfixed code. It is NOT yet mapped per defect. Some failures may be new-import errors rather than defect detection. That check is open.
- The full rubric total (ambiguity, baseline quote, FPs, per-defect test mapping) is NOT computed. It needs the 2-family panel (phase 4a) — see §6. **No total score is reported.**
- The minimax r41 run has no final report (`no-report` marker, DNF per PROTOCOL §2.2) and was re-run as r41b. The DNF directory is kept in `runs/` as evidence.
- The haiku-high arms' stderr shows one transform failure (policy A in action); their probes confirm exit 1 and intact state.

## 3. DR-v3 re-pilot (phase 3b) — 4 runs, raw only

| Arm | Tags | Cost (DB) |
|---|---|---|
| minimax xhigh | r43, r43b | $0.043, $0.038 |
| sonnet high | r43, r43b | $0.335, $0.237 |

All four captured a `final-report.md` (no DNF). **No DR-v3 scores are reported**: there is no DR-v3 answer key yet (open item §6). The reports separate proposal and conformance text, as the prompt asks; that separation is what the key must score.

## 4. D-key v3 re-score (phase 3c) — candidates, NOT re-scored

Three D runs name the `<=` diagnosis in `is_stale` (`snaputil.py:73`), with the consequence stated:

- `D-sonnet-high-p3` (v2 score 7.5; design text "returns True at equality" stated, line 54 of the design)
- `D-claude-sonnet-5-5-high-p5r2` (v2 score 8.5; design row S5)
- `D-deepseek-v4p1-flash-1017-high-g22` (v2 score 8.5; design line 135)

Upper bound under v3: **+1 H4 per run**, only where their H4 was previously 0. The per-category D scorer sheets are NOT in the repo (only panel means in `panel-scores.csv`), so the exact prior H4 value cannot be verified. Upper-bound new scores: 8.5 / 9.5 / 9.5. **These are not final re-scores.** They need an independent scorer sheet (the brief asked for a cheap-review session; not run in this session).

**Seat implications: none computed.** An H4 +1 could change a D order only if the gap is ≤ the new max delta; that needs the scorer sheets. No seat change proposed without owner go.

## 5. Artifacts

- Phase-3 logs: `evals/2026-11-19/logs/phase3/` (driver, probes, suite script, per-arm logs, driver.out)
- Run dirs (plain, open campaign): `evals/2026-11-19/runs/` (IV4-*: 9 incl. the DNF; T4V3-*: 4)
- Scores: `evals/2026-11-19/grid2-scores-rg4.csv` (separate file; RG3 and RG4 never compare)

## 6. Not done / open (stated, not hidden)

1. **Phase 4a panel (2 families) not run.** This session had no subagent or independent-panel launcher; the judgment points are unscored. No RG4 total score is reported.
2. **DR-v3 answer key missing.** The brief said "no key change", but DR-v3 asks for conformance too, which the DR2 key does not score. A new key is needed before any DR-v3 number is reported.
3. **D-key v3 re-score is an upper bound, not a re-score** (§4). Scorer sheets absent; no independent reviewer.
4. **Charts / LEADERBOARD not regenerated** (4b). RG4 has no chart dots yet; `gen-charts.py` not changed.
5. **Leakage grep for RG4 strings not run** (`RG4-A-REGISTRY-LOOKUP`, `RG4-B-GENERATED-FROM`, `RG4-C-RULES-READS`, `RG4-D-POLICY-A-EXIT`) — required before campaigns (§3.8).
6. **Defect-to-test mapping** of the own-test counts not done (§2).
7. **Judgment on my side:** I did the probe and suite checks myself. The rubric asks for independent scoring; these are execution results, not judgments.
8. **Budget note:** the DB shows $3.37 of unrelated 2026-11-19 gemini sessions; phase-3 spend is counted separately ($2.23).

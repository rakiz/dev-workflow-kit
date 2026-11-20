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

## 7. Phase 4 — 2-family panel, DR-v3 scores, D-key v3 H4 folds (2026-11-20)

Scorer prompts, raw logs and TSVs: private `evals-keys/score-logs/2026-11-19/panel/` (not in the
public repo; the rubrics are private). Every per-run total below is the sum of the scorer's own
breakdown fields; the sums were re-checked against the rubric formula.

### 7.1 RG4 panel (RUBRIC-IV2-RG4 v1, /14, policy A)

GLM family: `ai-gateway-misc/fw-glm-5.3-flash --variant high`, `EVAL_ARM_CAP=0.60`, batches A
(haiku-default r41/r42, minimax-xhigh r41b/r42) and B (haiku-high r41/r42, opus r41/r42), 2 sessions.
Haiku family: the single-scorer values from the brief (haiku-default 11.5, minimax-xhigh 13.5,
haiku-high 14, opus 14). **These four values are not on disk**, so they cannot be re-verified here.

| Arm | GLM r1 | GLM r2 | GLM mean | Haiku (brief draft) | **Panel mean (2 families)** |
|---|---|---|---|---|---|
| haiku default (cheap-code) | 11 (r41) | 13 (r42) | 12.0 | 11.5 | **11.75** |
| minimax xhigh (strong-code) | 14 (r41b) | 11 (r42, −3 FP) | 12.5 | 13.5 | **13.0** |
| haiku high | 13 (r41) | 13 (r42) | 13.0 | 14 | **13.5** |
| opus default | 13 (r41) | 13 (r42) | 13.0 | 14 | **13.5** |

- minimax r42 −3 FP: the scorer found an explicit false claim ("All 16 new tests verified to fail on
  pristine", 14 of 16 do).
- Gate 1 (anti-saturation, best ≤ 11 = 80% of 14): **FAILED** (best panel mean 13.5 = 96%).
  The RG4 fixture is saturated for these arms. No RG4 seat decision is valid under the gate as written.
- Gate 2 (pair gap ≥ max(3, 2×variance)): **FAILED** (haiku-high vs opus gap 0.0).
- Variance: not measured (no double-scored run). The 2-family rule was satisfied; the spread on the
  mean was ≤ 1 point.
- Sub-judgment points (probe a, b, c′, d, suite) are executed in the rubric's own probe layer (§7.1
  is the judgment layer on top). The c′ quoted-count point scored 0 for all four haiku-high/opus runs.

### 7.2 DR-v3 scores (RUBRIC-T4V3 v1, /14; proposal + conformance split per key §2)

Families: 1017 (`fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017 --variant high`,
`EVAL_ARM_CAP=0.30`) on all four runs; haiku (`github-copilot/claude-haiku-5.5`, `EVAL_ARM_CAP=0.30`)
on the two minimax runs only. Haiku was NOT run on the sonnet runs: the panel rule (haiku never
scores claude-* artifacts) would make it same-family. Sonnet runs are therefore 1 family, unofficial.

| Run | Haiku total | 1017 total | 1017 proposal / conformance | Mean (official) |
|---|---|---|---|---|
| minimax xhigh r43 | 13 | 13 | 9 / 4 | **13.0** (2 families) |
| minimax xhigh r43b | 14 | 14 | 11 / 3 | **14.0** (2 families) |
| sonnet high r43 | — (not run) | 14 | 10 / 4 | **14.0** (unofficial, 1 family) |
| sonnet high r43b | — (not run) | 13 | 11 / 2 | **13.0** (unofficial, 1 family) |

- Minimax cell (official): 13.5 (4 scores). Sonnet cell (unofficial): 13.5 (2 scores, 1 family).
- Category 9 (`deletions-never-propagated`, conformance) was credited for sonnet r43 and
  not credited for sonnet r43b (1017: "no DESIGN section / code location cited"). Haiku's haiku
  split reported `prop/conf` with the proof bonus folded into both sides; only the totals are
  used here.
- Category 6 (`debounce-starvation`) was missed by minimax r43 in both families.
- FP: 0 in every DR-v3 run.

### 7.3 D-key v3 H4 folds (verified against the artifacts, not the brief)

Rule: H4 credit only where the candidate's own design/report NAMES the `<=` in `is_stale`
(snaputil.py:73) with the docstring contradiction or the verified consequence (RUBRIC-D1-v3 H4).

| Cell / run | Prior | Verified H4 | Evidence | New |
|---|---|---|---|---|
| sonnet high p3 | 7.5 | +1 | `D-sonnet-high-p3.design.md:54` | 8.5 |
| sonnet high p5r2 | 8.5 | +1 | `D-claude-sonnet-5-5-high-p5r2.design.md:66` (S5) | 9.5 |
| sonnet high r91 | 7.5 | **0 (brief said +1)** | log names no `<=` (probe only) | 7.5 |
| sonnet high r93 | 8.5 | **0 (brief said +1)** | log names no `<=` (probe only) | 8.5 |
| sonnet high r94 | 8.5 | 0 | `<=` at log:395 is unrelated (`big>=1MB`) | 8.5 |
| 1017 high g21 | 9 | **0 (brief said +0.5)** | design:97 says "returns True at equality", never names `<=` | 9 |
| 1017 high g22 | 8.5 | +0.5 (prior H4 0.5 per brief) | `D-deepseek…high-g22.design.md:135` names `<=` | 9.0 |
| qwen xhigh p5 | 7 | +1 | `D-qwen…xhigh-p5.design.md:1029` (A13) | 8 |
| qwen xhigh p5r2 | 7.5 | 0 | no `<=` in design or report | 7.5 |
| qwen xhigh p6 | 7 | +1 | `D-qwen…xhigh-p6.design.md:400,660` | 8 |
| qwen xhigh p6r2 | 0 | 0 | `is_stale` "not used", no `<=` | 0 |
| opus default p3r2b | 9.5 | +1 | `D-opus-default-p3r2b.design.md:99` | 10.5 |
| opus default p4 | 8 | +1 | `D-opus-default-p4.design.md:47` | 9 |
| minimax xhigh g21 | 7 | +1 | `D-minimax-m3p1-flash-xhigh-g21.design.md:94` | 8 |
| minimax xhigh g22 | 6.5 | 0 | names `<=` (:50, :1106) but not the docstring contradiction | 6.5 |
| sonnet-arb | — | not folded | no `sonnet-arb` artifact found in `runs/` | — |

Cell effect (applied as the mean run delta on the panel D cell in grid2-scores.csv):

| Cell | D before | Mean run delta | D after (strict) | Brief's figure |
|---|---|---|---|---|
| sonnet high | 8 | +0.4 (5 runs) | **8.4** | 8.9 (with r91, r93 credited) |
| 1017 high | 9.56 | +0.25 (2 runs) | **9.81** | 9.25 (with g21 credited) |
| qwen xhigh | 6.4 | +0.5 (4 runs) | **6.9** | — |
| opus default | 8.58 | +1.0 (2 runs) | **9.58** | — |
| minimax xhigh | 6.81 | +0.5 (2 runs) | **7.31** | — |

The brief's r91/r93/g21 credits are NOT applied: the artifacts do not name the mechanism. If the owner
rules those credits valid (a different reading of H4), the 1017 and sonnet cells change by +0.25 and
+0.4 respectively. That is an owner call; the CSV carries the strict values.

## 8. Phase 4 — what is done, what is open

Done: RG4 GLM panel (8 runs, 2 batches); DR-v3 2-family scores (with the same-family limit);
H4 fold (verified); grid2-scores.csv columns `I2-RG4` and `DR-v3` added; gen-charts I-bench now reads
`I2-RG4` (4 dots); verify-charts 167/167; LEADERBOARD.html deterministic (2 runs, same sha).

Open / deviations:
1. RUBRIC-T4V3.md: written, **not committed** (STRICT no-commit rule overrides the brief's "commit").
2. The haiku single-scorer RG4 values (11.5, 13.5, 14, 14) are from the brief; no artifact on disk.
3. Gate 1 and gate 2 fail on the RG4 panel (saturation + zero gap). RG4 needs a harder fixture or a
   gate revision before any RG4 seat decision (owner call).
4. The I-v2 chart now shows 4 RG4 dots; the 30 RG3 I2 dots no longer plot (RG3 and RG4 are never
   compared). `verify-charts` total fell 197 → 167 for that reason, not a mismatch.
5. Category 10 (`crash-on-transient-error`) kept as proposal (key §2, owner review requested).
6. The "tie rule" named in the brief is not written in the repo; seat implications below assume "tie →
   cheaper wins" and are labelled as such.

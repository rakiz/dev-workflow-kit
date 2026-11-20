# 2026-11-20 — RG4 full grid (phase 4 completion, fixture reportgen-eval-repo-i4)

Status: STEPS 1–5 executed in this session. **Nothing committed or pushed** (owner reviews first).
Rubric: `evals-keys/RUBRIC-IV2-RG4.md` (private, v1, reachable max 14). Pristine: `evals/reportgen-eval-repo-i4/`.

## 1. Reconciliation (counts, verified)

| Item | Count | Proof |
|---|---|---|
| Driver logs (`logs/rg4-full/IV4-*.log`) | 38 | `ls logs/rg4-full` |
| Run dirs copied to `runs/` (from each log's `run dir:` line) | 38 / 38 exist | `cp -R` loop; all 38 `run dir:` paths existed |
| Deterministic layer run per run (`probes/<run>.txt`, `rg4-deterministic.tsv`) | 38 / 38 | `drive.sh` (phase-3 probe layer, unchanged) |
| DNF (no scoreable deliverable, PROTOCOL §2.2) | **4** | see below |
| Scored runs | **34** | `rg4-run-scores.tsv` |
| GLM panel readings (`fw-glm-5.3-flash`, high) | **30** (= 34 − 4 fw-glm runs) | `evals-keys/score-logs/2026-11-20/panel/glm-batch-{1..7}.tsv` |
| Haiku panel readings (`claude-haiku-5.5`) | **32** (= 34 − 2 claude-sonnet runs) | `…/panel/haiku-batch-{1..7}.tsv` |
| Total readings | **62** = 28 runs × 2 + 6 single-family | `rg4-run-scores.tsv` (`n_readings`) |
| Panel row-key coverage | 30/30 GLM, 32/32 haiku, no duplicates after fix | key diff vs batch `.txt` lists |

**DNF (4), NOT re-run in this session (see §7.1):**

- `qwen3p8-2p4t-a95b-xhigh-q51`, `…-xhigh-q52`: `no-report` marker written (no assistant text). Arm **qwen-xhigh has 0 valid runs**.
- `gemini-4-argon-high-q52`: `arm-killed-costcap` (2× $0.30 cap). Argon-high is single-run.
- `gemini-4-carbon-high-q52`: `arm-killed-timeout` (15-min watchdog). Carbon-high is single-run.

**Panel repair (recorded, not hidden):** `glm-batch-4` scorer keyed the muse-medium row as `q51` (it was `q52`). The mis-keyed row is kept as `glm-batch-4.tsv.ORIG-MISKEYED` and not used; muse-q52 was re-scored alone in `glm-batch-7`. Key coverage then matched the batch lists.

## 2. Method

- **Deterministic points** (no judgment), from the executed probes (`tools/rg4_deterministic.py` reads `probes/`):
  suite_green 2 (34/34 green); a-fix 1, b-fix 1, c′-fix 2, d-fix 1 — the four RG4 seeded defects (probe criteria: the private key; values withheld from public docs). Probe results: 32/34 a-fix (**muse ×2 not fixed**), 18/34 b-fix, 34/34 c′-fix, 34/34 d-fix.
- **Judgment points** (panel, two families): test_a / test_b / test_c / test_d (regression test that FAILS on pristine and targets the defect), c′ quoted counts, ambiguity (policy A), baseline quote, FP count (−3 each).
- **Total** = RUBRIC §0 formula, computed by `tools/rg4_fold.py` (asserts every judgment field is 0/1 or an integer; floor 0). Fold is deterministic (re-run gives identical TSV).
- **Self-family rule:** GLM never scores `fw-glm-*`; haiku never scores `claude-*`. So the 4 fw-glm runs and the 2 sonnet runs have **one family only**. No existing RG4 single-scorer pass for these exists on disk, so they keep one reading (gap stated in §3).
- **Divergent flag:** a run is divergent when its two family readings differ by ≥2; an arm is divergent if any of its runs is, or its family arm-means differ by ≥2.
- **Tie rule and MDE (used in §4):** the repo does not contain a written tie rule (RESULTS 2026-11-19 §8.6 says the same). This section uses **MDE = 1.5 points** (the gate-2 minimum gap) and: an arm within 1.5 of the top *eligible* score is a tie, and the **cheapest tied arm wins**. Eligible = two families and ≥2 valid runs. **Owner must ratify this rule.**

## 3. Standings (RG4 full grid, /14)

Per-run scores by family are in `rg4-run-scores.tsv`; the arm table is `rg4-standings.csv`. The four existing arms (haiku default/high, minimax xhigh, opus) are merged from RESULTS 2026-11-19 §7.1: their GLM per-run values are on record, but **their haiku values are not on disk** (published arm means only). Their run tags are r41/r42 (r41b/r42 for minimax).

| Model | Effort | Valid runs | q51 GLM / haiku | q52 GLM / haiku | Panel mean | Spread | Divergent | Families / note |
|---|---|---|---|---|---|---|---|---|
| glm | low | 2 | — / 10 | — / 9 | 9.5 | 1 | n/a (1 family) | 1 family |
| glm | high | 2 | — / 13 | — / 12 | 12.5 | 1 | n/a (1 family) | 1 family |
| dsflash | default | 2 | 11 / 10 | 13 / 13 | 11.75 | 3 | no | 2 families |
| 1017 | low | 2 | 13 / 12 | 12 / 11 | 12.0 | 2 | no | 2 families |
| 1017 | medium | 2 | 13 / 13 | 11 / 11 | 12 | 2 | no | 2 families |
| 1017 | high | 2 | 13 / 13 | 13 / 13 | 13 | 0 | no | 2 families |
| minimax | low | 2 | 11 / 11 | 13 / 13 | 12 | 2 | no | 2 families |
| minimax | medium | 2 | 11 / 11 | 11 / 11 | 11 | 0 | no | 2 families |
| qwen | medium | 2 | 14 / 13 | 14 / 13 | 13.5 | 1 | no | 2 families |
| qwen | xhigh | 0 | — / — | — / — | DNF | — | n/a (1 family) | none · DNF q51;q52 |
| hydrogen | high | 2 | 13 / 13 | 13 / 13 | 13 | 0 | no | 2 families |
| hydrogen | medium | 2 | 11 / 11 | 11 / 11 | 11 | 0 | no | 2 families |
| argon | high | 1 | 13 / 11 | — / — | 12 | 2 | yes | 2 families · DNF q52 |
| carbon | high | 1 | 14 / 14 | — / — | 14 | 0 | no | 2 families · DNF q52 |
| gem38 | medium | 2 | 12 / 11 | 12 / 11 | 11.5 | 1 | no | 2 families |
| muse | medium | 2 | 9 / 9 | 9 / 9 | 9 | 0 | no | 2 families |
| kimi | medium | 2 | 11 / 11 | 11 / 11 | 11 | 0 | no | 2 families |
| terra | medium | 2 | 12 / 12 | 12 / 12 | 12 | 0 | no | 2 families |
| sonnet | high | 2 | 13 / — | 14 / — | 13.5 | 1 | n/a (1 family) | 1 family |
| haiku | default | 2 | 11 / arm-only | 13 / arm-only | 11.75 | 2 | no | 2 families (haiku arm-level) |
| haiku | high | 2 | 13 / arm-only | 13 / arm-only | 13.5 | 1 | no | 2 families (haiku arm-level) |
| minimax | xhigh | 2 | 14 / arm-only | 11 / arm-only | 13.0 | 3 | no | 2 families (haiku arm-level) |
| opus | default | 2 | 13 / arm-only | 13 / arm-only | 13.5 | 1 | no | 2 families (haiku arm-level) |

Gaps: the 4 fw-glm arms and sonnet-high have a single family. Argon-high and carbon-high are single valid runs. qwen-xhigh is unscored (both runs DNF). Run-to-run arm gaps (|q51 − q52| of run means): dsflash 2.5, minimax-low 2.0, 1017-medium 2.0 (all > 1.5 MDE).

## 4. Seat verdicts — I2 (I-v2) seats, report only, NO seat change

Eligible top = **13.5** (haiku-high, qwen-medium, opus). Tie band = ≥ 12.0. Cheapest arm in the band = **minimax-xhigh** ($0.03; 13.0). Verdicts use this band for strong seats and the incumbent-relative cost test for cheap seats.

| Seat (bench I-v2) | Holder | RG4 I2 mean | Cost/task | Margin to top (13.5) | Verdict under tie rule (MDE 1.5) |
|---|---|---|---|---|---|
| cheap-code | haiku default | 11.75 (arm-level haiku values not on disk) | $0.02–0.03 | −1.75 | **HOLDS** — no arm cheaper than it within 1.5 (glm-low 9.5 is out of band and single-family) |
| strong-code | minimax-xhigh | 13.0 | $0.03 | −0.5 (tie band) | **HOLDS** — cheapest arm in the band |
| strong-code-alternative | haiku-high | 13.5 | ~$0.15 | 0.0 (tie) | **FLIP by the rule** — cheapest in band is minimax-xhigh, which already holds strong-code, so the alternative would collapse onto the same model. Owner call |
| deep | opus | 13.5 | ~$1.39 | 0.0 (tie) | **FLIP by the rule** — cheapest in band is minimax-xhigh. The "deep" seat is a terminal rung, so the tie rule may not apply. Owner call |
| strong-code-alternative2 | opus | 13.5 | ~$1.39 | 0.0 (tie) | **FLIP by the rule** — same as deep |
| cheap-mech / explore | dsflash | 11.75 | $0.03 | 0.0 vs haiku default | **FLIP CANDIDATE** — tie at 0.0; haiku default is cheaper ($0.025 vs $0.03). Owner call |

Summary: **hold** cheap-code (haiku default) and strong-code (minimax-xhigh). **Flip under the tie rule**: strong-code-alternative (haiku-high → would collapse onto minimax-xhigh), deep and strong-code-alternative2 (opus loses both), cheap-mech/explore (dsflash → haiku default, candidate).

Robustness check: counting carbon-high (14, single run) as eligible moves the top to 14 and the band to ≥ 12.5. Cheapest in band is still minimax-xhigh, so the verdicts above do not change. These verdicts are **provisional**: the gates fail (§5).

## 5. Gates (RUBRIC §3; gate 1 ≤ 80% of 14 = 11; gate 2 gap ≥ max(3, 2×variance))

- **Gate 1 — anti-saturation: FAIL.** Top eligible 13.5 = 96% of 14 (raw top 14 = carbon-high, one run). Many arms score 13–14.
- **Gate 2 — pair gap: FAIL.** haiku-high vs opus = 0.0; no pair reaches 3. Variance is not formally measured; observed run-to-run arm gaps reach 2.5.
- RG4 is still saturated. The 2026-11-19 record said the same (RESULTS §7.1, §8.3). **Any seat decision needs a harder fixture or a gate revision — owner call.**

## 6. Artifacts (this section)

- `runs/` — 38 run dirs (copied from `/var/folders/.../T/bench-v3-*`, named after their logs).
- `probes/<run>.txt` — drive.sh output per run; `rg4-deterministic.tsv` — parsed (tool `tools/rg4_deterministic.py`).
- `rg4-run-scores.tsv` — per run: deterministic + both family readings, mean, spread, divergent (tool `tools/rg4_fold.py`, the RG4 parser; it validates every judgment field).
- `rg4-standings.csv` — per arm (tool `tools/rg4_standings.py`).
- `evals/2026-11-16/grid2-scores.csv` — `I2-RG4` column rewritten for every model (19 new arms + 4 existing kept). Only that column changed (19 cells; `git diff` checked cell by cell).
- `evals/reasons.py` — Implementation "why" strings rewritten for RG4 arms (qwen-xhigh DNF, carbon/argon single run, 1-family notes).
- `evals/gen-charts.py` — Implementation bench title rewritten (full RG4 set, tie rule, MDE 1.5).
- `evals/LEADERBOARD.html` — regenerated: `verify-charts` **185/185** dots (was 167; the I-v2 RG4 chart now has 22 dots); two consecutive `gen-charts` runs give the same sha256 (`b91516475b451dc963ed90b88b25739521ab4ffaa94bf580c96ef65920640eb1`).
- Private: `evals-keys/score-logs/2026-11-20/panel/` (scorer prompt, batch files, panel TSVs, driver, mis-keyed row kept). Not in the public repo.

## 7. Open items (stated, not hidden)

1. **DNF re-runs (PARTIAL, see §8)** — qwen-xhigh re-run ×2 done and scored; argon-high q53 and carbon-high q53 NOT run (budget guard, §8). Owner decision needed for those two. The RG4 driver spent $14.78 of its $20 guard; the four re-runs have per-arm caps of $1.00 (qwen-xhigh) + $0.30 (argon) + $1.50 (carbon) = $2.80, and the kill fires at 2× cap. Until then qwen-xhigh is unscored and argon/carbon are single-run.
2. **Tie rule — RESOLVED (ratified 2026-11-20)**: PROTOCOL §5 (tie-rule bullet after §5(e)): eligibility = two scorer families + ≥2 valid runs; the cheapest arm inside the MDE band wins the seat.
3. **Leakage grep (rubric §4, protocol §3.8)**: the four RG4 seeded-defect IDs (held in the private key) appeared in the committed public docs `evals/2026-11-19/RESULTS.md` and this file. Scrubbed in the 2026-11-20 D3 pass (see the scrub note in §8); post-scrub grep over the docs = 0 hits.
4. **I2-RG4 chart seats — RESOLVED (D4)**: `SEATS` and the chart's bench key are both `I2-RG4`; 5 blue dots (see §8).
5. **why-table — PARTIAL (D5)**: strong-code and the tie-rule line are RG4 (§8). The cheap-code and strong-code-alternative rows still cite RG3-era I2 numbers (8.33 / 8.83) — open.
6. **1-family marker — RESOLVED (D6)**: suffix `~` on glm-low 9.5~, glm-high 12.5~, sonnet-high 13.5~ (grid2 I2-RG4 and rg4-standings panel_mean); chart label `~` + legend.
7. The four existing arms' haiku values are **not on disk**: the brief gives haiku-default 11.5, minimax-xhigh 13.5, haiku-high 14, opus 14; only the published 2-family means (11.75 / 13.0 / 13.5 / 13.5, RESULTS 2026-11-19 §7.1) are on disk. They cannot be re-verified here.
8. `aggregate-panel.py` and `extract-runs.py` were **not run**: they write 2026-11-16 outputs (`panel-scores.csv`, `runs/`) from 2026-11-16 inputs, and none of their inputs changed. The RG4 parser is `tools/rg4_fold.py`.

## 8. Owner batch D1–D6 (2026-11-20; D1 PARTIAL — argon/carbon re-runs blocked)

**D1 — DNF re-runs.** Driver `logs/rg4-d1/driver.sh` (sequential, DB-counted guard: launch only if spend-since-baseline + 2×cap ≤ $3.00; baseline $141.1382). Timeout 1800 s. Tags: qwen run 2 is `q53b` (the cost poller keys on the exact title, so two `q53` arms would be conflated).

| Arm | Tag | Result | Cost (DB) | Proof |
|---|---|---|---|---|
| qwen-xhigh | q53 | valid (final report captured); probes a✓ b✓ c=1 d✓; GLM 13 / haiku 14 → run 13.5 | $0.8455 | `runs/…xhigh-q53/final-report.md`; `probes/…xhigh-q53.txt`; `panel/*-batch-8.tsv` |
| qwen-xhigh | q53b | valid; GLM 10 (1 FP) / haiku 13 → run 11.5, **divergent (spread 3)** | $1.37 | `runs/…xhigh-q53b/`; `probes/…xhigh-q53b.txt` |
| argon-high | q53 | **NOT RUN** — guard: $2.2155 + 2×$0.60 = $3.42 > $3.00 | — | `logs/rg4-d1/driver.out` |
| carbon-high | q53 | **NOT RUN** — guard: 2×$2.00 = $4.00 worst case can never fit $3.00 (q52 observed $2.29 at timeout) | — | `logs/rg4-d1/driver.out` |

- qwen-xhigh arm: **2 valid runs, 2 families, panel mean 12.5** (runs 13.5 / 11.5, spread 4, divergent). It moves from DNF to eligible; it sits inside the 1.5 band of the 13.5 top; the cheaper minimax-xhigh (13.0 at $0.03) keeps the strong-code seat. No seat change.
- argon-high stays single-run (q51 only); carbon-high stays single-run (q51 only). Both re-runs are **owner decisions**: a higher budget or a lower per-arm cap (e.g. carbon at ≤$1.00 cap = $2.00 worst case) is required — NOT changed here.
- Total model spend in this batch: **$2.268** (2 arms $2.2155 + 3 panel sessions $0.0527); DB spend since baseline $143.4065 − $141.1382. Within the $3.00 max.
- Deterministic layer: `tools/d1-probe.sh` reproduces the 38 committed probe rows exactly (38/38 identical, validated), then the 2 new rows are appended (`rg4-deterministic.tsv`, 40 rows).
- Fold: `tools/rg4_fold.py` tag regex accepts `q53`/`q53b`; the fold is deterministic (2 runs identical). Standings: `tools/rg4_standings.py` (now emits the `~` marker and the D1 source note) — regenerated.
- DNF rule: the qwen re-runs did not DNF again; no third attempt.

**D2 — tie rule.** The sentence was NOT in PROTOCOL §5 before this batch (§5(e) had only the 1.5 pt gate). Added as §5(f): "Tie rule (ratified 2026-11-20). Eligibility = two scorer families + ≥2 valid runs; the cheapest arm inside the MDE band wins the seat."

**D3 — leakage scrub.** Scrubbed: `evals/2026-11-19/RESULTS.md` (probe values, the policy-A wording with exit specifics, the table `gen=2` / `exit1` cells, the leakage-ID line), this file (§2 deterministic line, §7 item 3), `evals/2026-11-13/NIGHT-REPORT.md` (one probe value). Added the calibration note to `evals/README.md` and to `2026-11-19/RESULTS.md`: "RG4 = a calibration bench by design (built public); the held-out rule lives in PROTOCOL §5."
Grep of `*.md` for the four RG4 defect IDs and the distinctive probe tokens (held in the private key; not restated here): **0 hits** outside `runs/` and `logs/`.
NOT scrubbed (flag for owner): (a) candidate `final-report.md` files under `runs/` (model outputs describing the defects in their own words — evidence, not keys); (b) probe outputs `probes/*.txt`, `rg4-deterministic.tsv`, `tools/*.py`, `2026-11-19/logs/phase3/probes-rg4.sh` (executable verification — the probe logic itself). The fixture `reportgen-eval-repo-i*/` stays public by design.

**D4 — seats.** `SEATS` implementation keys changed `I-v2` → `I2-RG4` (7 entries) and the chart's Implementation bench key `I-v2 RG4` → `I2-RG4`. Result on the RG4 chart: **5 blue filled dots**: haiku-default (cheap-code), minimax-xhigh (strong-code), haiku-high (strong-code-alternative), opus-default (deep, strong-code-alternative2), and **dsflash-default (cheap-mech, explore)** — the fifth is a consequence of the same key rename (its cheap-mech/explore seats were also keyed to the implementation bench), not in the brief's list of four. Owner call whether those two seats should keep the I-v2 key.

**D5 — why-table.** strong-code row → RG4 numbers (minimax-xhigh 13.0 at $0.03 vs sonnet-high 13.5~ and haiku-high 13.5 at $0.15; qwen-medium 13.5 challenger line); tie-rule sentence added above the table. The cheap-code and strong-code-alternative rows still cite RG3-era I2 numbers — open.

**D6 — 1-family marker.** `~` suffix on glm-low (9.5~), glm-high (12.5~), sonnet-high (13.5~) in `grid2-scores.csv` I2-RG4 and `rg4-standings.csv` panel_mean; the chart label gets `~`, the tooltip says "one scorer family (~)", and the chart legend reads "~ = one scorer family". `verify-charts` checks the `~` label count (3/3).

**Charts / verification.** `gen-charts.py` → `LEADERBOARD.html`; `verify-charts.py` **186/186** dots (RG4 chart 23 dots; the brief said 198 — the actual total is 186). Two consecutive `gen-charts` runs: identical sha256 `60edb3b1…ac02d`. Parser: `rg4-deterministic.tsv` re-parse identical (40 rows).

**Panel note.** The first GLM scorer session for batch 8 tried to copy run dirs into the sandbox temp area (auto-rejected) and wrote no TSV; re-run read-only with the same prompt and batch. Recorded in `evals-keys/score-logs/2026-11-20/panel/` (private repo).


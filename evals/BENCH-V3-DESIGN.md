# Bench v3 design — pipeline-named tasks, I-v2, design-authoring (D), calibration-first re-baseline

**Status: APPROVED (owner decisions 2026-11-12 recorded in §9) — fixtures built 2026-11-12 (RG2 + D1, prototypes verified per §3.8), answer keys private outside the repo (`~/code_projects/IA-tooling/evals-keys/`, private git repo), pilot pending.**

**Supersession note (2026-11-12):** §9 decision #4 (FULL ROSTER fleet)
supersedes §1 item 4's "rung-relevant only" re-baseline recommendation and
§6.1's option-A framing; §9 decision #6 (haiku INCLUDED, stage-2 cells)
supersedes §6.2's haiku "skip" row.

This document only proposes. No fixture is created, no `run-eval` script is
touched, no `EVALS.md`/`README.md`/`MODELS.md` row changes until the owner
approves the open decisions at the end.

**Leakage note (v2):** this is a public repo. Sections 3–5 deliberately do
NOT enumerate the seeded-defect INSTANCES (locations, probe commands,
expected outputs) or the D taxonomy entries — those live in the answer-key
files, held OUTSIDE the repo permanently (`~/code_projects/IA-tooling/evals-keys/`:
`RUBRIC-IV2.md`, `RUBRIC-D1.md`, the reference-fixed copy; owner decision
#5, relocated out of the repo 2026-11-12). The construct-level exposure
already granted by this dated document is acknowledged here: the
seeded-defect COUNT (4 for I-v2), the defect CLASS names (spec-vs-code
contradiction, cross-file state consistency, measurement-forcing
performance, fix-shape ambiguity — §3.2) and the 8 D category names (§4.3)
are public as of 2026-11-12; instance-level details stay private. The
public doc carries only the *construct* of each task: depth layering, trap
classes, scoring mechanics, gates. This v2 revision itself exposes
construct-level information as of 2026-11-12; the exposure date is recorded
here and any fixture built from it must assume adversarial familiarity with
the *shape* (but not the instance) of what is seeded. A distinctive-string
leakage check (unique seeded identifiers grepped against the public repo
before each campaign) is part of the fixture prototype checklist (§3.8).

---

## 1. Summary

Four goals, one hard constraint:

1. **I-v2 (impl, second generation)** — T2 is saturated: every model with a
   verifiable recorded cell PASSes (all cheap/mid cells 10-14→11-10 in
   `EVALS.md`). Two cells are qualitative-only (sonnet-5.5 and opus-5.5,
   09-29, "PASS", costs n.t.) — the honest statement is "every measured
   cell passes; the two 09-29 strong-tier cells are unverifiable
   single-pass judgments". Either way it cannot arbitrate an impl rung.
   We design a multi-defect implementation task in a **new domain** (§3.1).
2. **D (design authoring)** — the pipeline has an author task for impl (I)
   and critic tasks for design (DR) but no author task for design, yet the
   global roster runs `cheap-design`, `strong-design`,
   `strong-design-alternative` rungs (`MODELS.md` grid). D measures a model
   asked to *write* a design for a fully specified brief (§4) over an
   existing codebase, graded against a defect taxonomy + honesty bonus.
3. **Naming** — rename the bench taxonomy to the work pipeline: design →
   design-review → impl → impl-review → orchestration. Proposal:
   **D / DR / I / IR / O** with fixture-versioned directories and a
   migration table (§2). The migration cost is real (§2.3) and stated.
4. **Re-baseline** — scoped, rung-relevant re-baseline (§6), not
   whole-roster: the pilot alone must not unlock the full spend (§5.8).

**The hard constraint (owner):** the new tests MUST be calibrated — *"qu'on
se retrouve pas avec un truc tout plat et des tokens gaspillés."* Section 5
is the heart: pre-registered gates, per-rung competitor pairs,
double-scoring, variance-aware thresholds, staged fleet release, and
enforced caps.

### Lessons from history this design is built on

| Lesson | Source | Design consequence |
|---|---|---|
| The T1 red-baseline execution trap caught every model ever tested | `EVALS.md` Standing lessons | Execution-forcing traps discriminate — but must be non-statically solvable (carbon solved v1's statically, 11-10 §3) |
| Zero proofs-by-execution across all DR-v2 arms; +4 bonus never earned, real ceiling 10 | `2026-11-01/RESULTS.md` | Gate D/I-v2 on the REACHABLE max; honesty bonuses must be demonstrably earnable in the pilot or dropped from the max |
| Terra `medium` scored 8/14 without opening the code; sol 2/14 the same shape | `2026-11-01/`, `2026-11-10/RESULTS.md` | Code-groundedness is a scored component, not a bonus (§3.5, §4.4) |
| Cat-3 borderline debates needed owner rulings; Example-FP ≠ deduction | `RUBRIC-T4V2.md`, 11-01 calibration | Every category ships with counts/does-not-count pairs + half-credit triggers, frozen BEFORE the pilot (§3.6, §4.6) |
| Carbon v1 effort-flatness collapsed on DR-v2 at `low` (10/10→4/14) | `2026-11-10/RESULTS.md` §6 | A hard bench re-sorts effort cells; never inherit cells across benches |
| v1/v2 scores never compared across benches; each rung decision cites its bench | `README.md` v2 policy | Carried into v3 (§2.2) |
| Delegation: arm cost = parent + ALL children, named | `README.md` delegation rule | I/D briefs forbid delegation; parent-only scoring is the primary construct (§6.5) |
| 0 FP across all four best DR-v1 models (11-01) is GOOD behavior | `2026-11-01/RESULTS.md` | "Zero FPs" is never read as a fixture defect (§5.6) |
| Single-run arms are provisional (minimax variance lesson) | `EVALS.md` | Pilot best/worst arms get 2 runs; thresholds set above measured variance (§5.4) |

---

## 2. Naming scheme + migration mapping

### 2.1 The scheme

| New | Stage | Old name(s) | Fixture dir (new convention) |
|---|---|---|---|
| **D** | design (authoring) | *new* (this doc) | `syncfeat-brief-d1/` |
| **DR** | design-review | T4 → **DR-v1**; T4v2 → **DR-v2** | `synccli-eval-repo/`, `synccli-eval-repo-v2/` (existing dirs keep their names; a `fixtures/` column in README maps them) |
| **I** | impl | T2 → **I-v1**; new task → **I-v2** | `synccli-eval-repo/` (v1), `reportgen-eval-repo-i2/` (v2, §3.1) |
| **IR** | impl-review | T3 → **IR** | `synccli-eval-repo/` (shared with I-v1) |
| **O** | orchestration | T1 → **O** | `synccli-eval-repo/` (shared with I-v1) |

Rules:

- **Unqualified stage = current version.** "D" means the latest D fixture;
  "DR-v2" pins a fixture. A future DR-v3 or O-v2 needs no taxonomy rename.
- **Session titles** carry the stage code + fixture code, so cost-extraction
  queries resolve unambiguously:
  `eval-YYYY-MM-DD-<CODE>-<FIXTURECODE>-<model>-<effort>` — e.g.
  `eval-2026-12-01-IV2-RG2-github-copilot-gemini-4-carbon-high`. The
  canonical fixture code (`RG2` for reportgen-i2, `SYNC1`/`SYNC2` for the
  existing ones, `D1` for the D brief) is interpolated into the title so a
  DB query never guesses which fixture a cost came from.
- **Fixture/title mapping rows** (for the standard cost query documented in
  `2026-11-01/RESULTS.md` §Methodology): one row per fixture in README's
  contents list: `fixture dir → fixture code → title token → task codes`.

### 2.2 Migration mapping (top of `EVALS.md`)

```text
T1  = O       (orchestration, fixture SYNC1)
T2  = I-v1    (impl, fixture SYNC1)
I-v2 = new    (impl, fixture RG2 — this design)
T3  = IR      (impl-review, fixture SYNC1)
T4  = DR-v1   (design-review, fixture SYNC1)
T4v2 = DR-v2  (design-review, fixture SYNC2)
D   = new     (design authoring, fixture D1 — this design)
```

Cross-bench policy carried over unchanged: scores are never compared across
versions of the same stage; each rung decision cites the bench it was
decided on.

### 2.3 True migration cost (replacing v1's "one table" claim)

- `evals/README.md`: task table rewrite, fixture mapping rows, version
  policy paragraph (~30 lines).
- `EVALS.md`: mapping header + no row edits (historical rows keep T-names,
  interpreted via the table).
- `run-eval.sh` / `run-eval-v2.sh`: title format update, fixture-code arg
  (or a new `run-eval-v3.sh`; the old scripts are historical records —
  recommendation: new script, old ones frozen).
- DB queries in future `RESULTS.md`s: new title pattern (§2.1).
- `LEADERBOARD.html`: panel labels only (5 panels keep their constructs).
- `MODELS.md`: nothing (it references rungs, not task codes).
- Estimated effort: ~1 session, no data migration. The v1 claim that this
  was a one-table change was wrong; it is a half-day of mechanical edits.

The "keep T-numbers" alternative (T5, T6, T2v2…) is not a live competitor —
it prefixes the taxonomy with a growing ordinal while the pipeline letters
already name the thing — it is listed here only to record that it was
considered and why it loses (the owner's stated mental model is the
pipeline; ordinals encode chronology, not function).

---

## 3. I-v2 spec (multi-defect implementation task)

### 3.1 Fixture — new domain, new directory

**New fixture `reportgen-eval-repo-i2/`** (fixture code `RG2`), in a domain
with no lineage to synccli: a **report generator** that reads CSV inputs
from `input/`, applies per-column transforms from a rules file, writes a
summarized HTML/JSON report to `output/`, and maintains a small cache
(`cache/state.json`) so unchanged inputs are skipped. Files: `reportgen.py`,
`transforms.py`, `cache.py`, `rules.example.toml`, `test_reportgen.py`,
`GOAL.md` (~350 lines of code total). Plain files, no `.git`, no
flaw-flagging comments.

**Why a new domain (the leakage/pattern-matching question):** three
generations of synccli risk models pattern-matching the *kit's* sync bugs
rather than reading the code — and the kit being public means synccli defect
shapes (TOCTOU lockfile, mtime truncation, missing reconcile) are now
documented in the repo itself. The transfer value of staying in-domain
(model familiarity with the universe) is small and works against the bench
once the taxonomy has leaked. RG2 keeps the same *constructs* (cross-file
state, incremental-vs-full work, silent failure) in an unfamiliar shape.

### 3.2 Seeded defects — COUNT AND DETAILS LIVE IN THE ANSWER KEY ONLY

Per the leakage note: the defect list, locations, and acceptance probes live
in `RUBRIC-IV2.md` (private, outside the repo — `~/code_projects/IA-tooling/evals-keys/`).
The public construct:

- **4 defects total** (thinned from the v1 draft's 6 — six deep defects in
  ~350 lines is implausible engineering density and every probe multiplies
  prototype risk; 4 in 350 lines matches real review-findable density).
- **Depth layering**: at least one spec-vs-code contradiction (a comment/doc
  asserting a guarantee the code does not provide — where the comment is
  **bait only**: the underlying behavioral bug is real, probeable, and
  earns its defects_fixed point independently of the comment; reporting the
  comment as "the defect" without the behavior earns nothing), at least one
  cross-file state-consistency defect, at least one measurement-forcing
  performance defect (seeded oversized input shipped in `input/` so the
  probe is `run it`), and **one fix-shape ambiguity**: a partial-failure
  case where the brief permits either retry-once or fail-fast-abort, both
  correct — graded on the candidate *stating the trade-off and making the
  implementation consistent with its choice* (this is the non-mechanical
  fix; every model aces mechanical fixing, which is exactly the T2
  saturation — the ambiguity is what the new bench adds).
- **Deliberately NOT seeded**: any check-then-act lockfile pattern. It is
  the most pattern-matched bug in the public corpus (v2 cat-1 published in
  `RUBRIC-T4V2.md`); a fixture containing it measures recognition, not
  reading. (Considered variant: a FIX trap where naive `O_EXCL`
  reintroduces a stale-lock window — rejected for v1 of this bench: it
  needs concurrency infrastructure that multiplies prototype flakiness;
  revisit if a future bench needs a fix-shape race.)
- **No red baseline in the scoring path**: one pre-existing failing test
  exists, scored **report-only** (+1 bonus for naming it as pre-existing
  with executed evidence) and **fix-only-if-asked** — the GOAL.md does not
  ask to fix it, so "don't touch unrelated tests" is coherent. It is
  double-counted nowhere: it is not part of suite-green, not a
  defects_fixed point.

### 3.3 Task brief (GOAL.md)

Mirrors the v2 GOAL shape: a feature request (a new transform type + a
cache-hygiene requirement) *plus* "the repo may contain defects; fix any you
find with the smallest change that keeps the suite green and the stated
invariants holding; add a regression test per fixed defect; state any
trade-off the brief leaves open. Do not refactor; do not touch unrelated
tests." The brief never counts or names defects. **Delegation is
forbidden** (the candidate runs alone; §6.5).

### 3.4 Scoring formula

```
score = suite_green (0/2: scorer-executed `python3 -m unittest` in the run
                      dir, baseline suite only — the red-baseline test is
                      excluded from this check entirely)
      + defects_fixed (0–4, 1 each; defined by the per-defect observable
                       probe in RUBRIC-IV2.md, §3.5)
      + tests_written (0–2: 1 if a regression test exists per fixed defect
                       category, 1 if the test deterministically fails on
                       the unfixed prototype — §3.5)
      + ambiguity_handled (0/1: the fix-shape trade-off §3.2 — implemented
                           coherently AND stated)
      + red-baseline bonus (+1, report-only, executed evidence)
      − FPs (see §3.5 penalties)
```

- **Reachable max for gate purposes: 10** (2+4+2+1+1). Honest labeling: the
  red-baseline bonus is expected to be widely earned (every honest model
  runs the suite anyway), but until the pilot demonstrates it, gates use
  max = 10, and if the pilot shows the bonus is near-universal it is folded
  into expectations (not into a re-threshold — the threshold is set on the
  pre-registered max, per §5.3).
- **Minimality**: `git diff` surface reported as a tiebreak column, not
  points (v1 precedent).

### 3.5 Objective probes, determinism, and the FP boundary

- **Every defect has a deterministic acceptance probe**, pre-registered in
  the rubric before the pilot. Probe classes: monkeypatched interleaving or
  injected failure points for ordering defects; **operation-count vs
  relative baseline** for the perf defect (e.g. "cache hits must reduce
  file-read count by ≥N on the seeded oversized input, measured on the
  UNFIXED prototype as the 1.0 baseline"); output-diff for state-consistency
  defects. No wall-clock probes, no sleep-based repros — a probe that
  cannot be made deterministic on the prototype is a disqualified defect
  (§3.8).
- **Revert-the-fix scoring** (does the candidate's regression test fail on
  the unfixed prototype) is used **only** where the test is deterministic
  and isolated per defect; where it is not, the probe itself is the test
  and the candidate's test earns its point by existence + runner pass.
- **FP penalty scope — narrowed from v1-draft and from DR-v2:** the −3 FP
  penalty was calibrated for *review findings*; for an *editing* task a
  failed fix attempt is a 0-for-that-defect, never −3. An I-v2 FP is only:
  an **explicit false claim in the final report** — (a) asserting a defect
  that the fixture contradicts, (b) presenting a stated constraint as a
  discovered defect, (c) factually wrong Python semantics asserted in the
  report, (d) the same claim counted once. Nothing else deducts.

### 3.6 Rubric freeze

`RUBRIC-IV2.md` v0 — per-defect: location, probe command + expected output,
counts / does-not-count pair, half-credit trigger, example-FP list (with the
11-01 owner ruling restated: example-FP membership is not a deduction), the
ambiguity grading pair (retry vs abort, what "consistent" means), and the
scorer instructions — is **frozen and committed before the first pilot arm
runs**. Post-pilot changes are rubric amendments requiring an owner ruling
and a fresh pilot of the affected arm; pre-registration is void if the
rubric changes after scores exist.

`RUBRIC-IV2.md` v0 frozen 2026-11-12; **private location (owner-approved
relocation out of the repo, 2026-11-12 pre-freeze fix — owner decision #5
means private permanently):**
`~/code_projects/IA-tooling/evals-keys/RUBRIC-IV2.md` (private git repo,
separate from the public repo), sha256 (post-amendment, still
pre-pilot — no scores exist):

`de9716166a9a7aa0c85ff1bc1bab12b1f1afa4ee29103d47a4fae037d84f754e  ~/code_projects/IA-tooling/evals-keys/RUBRIC-IV2.md`

RG2 prototype tree hash (the audit flagged that fixtures had no recorded
hash; computed over `evals/reportgen-eval-repo-i2/` with `find . -type f |
sort | xargs shasum -a 256 | shasum -a 256`):

`4065cd630f0a398d88ff1bf5317b986d6cfb9d8b96f3e6d388f9c16e7e007213  (RG2 prototype tree, evals/reportgen-eval-repo-i2/)`

### 3.7 Fix-shape ambiguity detail (the anti-mechanical axis)

The brief states the invariant ("a transform failure must never corrupt the
cache or emit a partial report") but leaves retry-vs-abort open. Graded 1
if: the implementation enforces the invariant under the chosen policy, the
final report names the choice and the cost it accepts (staleness on abort /
latency on retry), and a probe (injected failure on the prototype)
demonstrates the invariant. 0 if the invariant is violated under the
chosen policy or the choice is implicit/contradictory. Both policies cap at
1 — the axis measures judgment, not policy preference.

### 3.8 Fixture prototype step (mandatory, pre-pilot)

Before any pilot arm: build the UNFIXED prototype, run every rubric probe
against it (each must fail deterministically), build a reference-fixed
version, run every probe against it (each must pass deterministically, ≥3
consecutive runs), and run the distinctive-string leakage check (each
seeded defect's unique identifier strings grepped against the public repo —
zero hits). A flaky or non-deterministic probe **disqualifies its defect**
(removed or replaced) — it does not get averaged into scores.

---

## 4. D spec (design authoring)

### 4.1 The construct — defined here, not deferred to the owner

The central decision: the feature brief must **entail every taxonomy
category** (the design cannot avoid them) without naming them, and must not
be (a) an impl-style feature over synccli — the sync categories would be
irrelevant and everyone scores 0 — or (b) a daemon design — that
duplicates DR-v2's construct (the models already measured *reviewing* a
sync daemon; asking them to *author* one measures the same taxonomy twice
with author-side credit).

**Candidate briefs considered (the owner asked for 2–3 with entailed-
category analysis):**

1. **Backup/restore + retention tool** over an existing small codebase
   (chosen). Brief: "design `backupctl`, a consistent-snapshot backup with
   retention, for the kit's own `evals` workflow: N directories, scheduled
   or invoked concurrently, must never produce a torn snapshot, must bound
   disk use via retention, must survive interruption, must co-exist with a
   concurrently running restore, must state its performance budget for the
   initial full backup of a ~1 GB tree." Entailed categories: concurrency
   (concurrent invoke + restore = locking/atomicity), torn-snapshot
   prohibition (atomicity/partial-failure), retention (deletion semantics +
   boundedness), interruption (error semantics + integrity), budget
   (performance claim discipline), detection granularity (change detection
   for incremental backups). Not a daemon (invoked tool), not synccli
   (snapshot/retention semantics, not change-sync). The existing codebase
   it must integrate with is small and real (see §4.2), so every category
   requires code-grounded integration points.
2. **Zero-downtime on-disk format migration** — entails atomicity, rollback,
   detection; weaker on retention/boundedness and concurrency (a migration
   is single-shot), so 2 categories need artificial stuffing. Rejected.
3. **Batching/queueing layer with backpressure** for a CLI pipeline —
   strong on boundedness/polling/error semantics, but "design a queue" is
   the most-trained LLM artifact in existence and risks everyone producing
   textbook queue designs that never touch the existing code. Rejected.

**Decision: brief #1** (`backupctl` over the kit's own tooling context).
Owner confirmation is decision #3, but the design no longer depends on the
owner to supply the brief.

### 4.2 Fixture `syncfeat-brief-d1/` (fixture code `D1`)

- The **BRIEF.md** above (~1 page, fixed, versioned with the fixture).
- The **existing codebase**: the v1 `synccli-eval-repo/` files as the
  integration substrate — with the seeded I-v1 defect **removed** (the
  off-by-one reverted to correct iteration; the candidate must be able to
  trust the code it reads) and **`DESIGN.md` deleted** (it is the answer
  key for DR-v1 — leaving it gives the candidate a template of exactly the
  depth the graders want; `GOAL.md` also removed as fixture machinery). The
  remaining code (`synccli.py`, `test_synccli.py`) is the real surface the
  design must reference.
- Deliverable: the candidate writes `DESIGN-d1.md`. No answer-key document —
  an answer-key **taxonomy** in `RUBRIC-D1.md`.

### 4.3 Grading (scored on the produced DESIGN-d1.md)

**Part A — taxonomy (0–8, 1 each, half-credit rules §5.5):** the 8
categories listed in `RUBRIC-D1.md` (the v2 flaw categories re-mapped to
authoring: concurrency/locking, atomicity/crash-consistency,
deletion/retention semantics, detection granularity, partial-failure
integrity, performance-budget honesty, boundedness, error semantics). A
category point requires **code-groundedness as part of the point, not a
bonus** (the anti-terra fix): the design must cite the exact existing
artifact it builds on — file:line integration points, named reuse of
existing helpers, or an explicit stated contradiction with existing
behavior it chooses to override. A design that is internally coherent but
could have been written without opening the codebase earns **0** on
categories it does not ground — matching the terra/sol failure shape where
design-only inference scored 8/14 and 2/14 respectively. Each category's
rubric entry defines which grounding forms count.

**Part B — honesty/proof bonus (0–3):** **executed commands with observed
output only** — running the existing test suite and reporting the real
result, timing a probe on the real tree, verifying a claimed integration
point by running the existing code path. **File:line citations are not
probes** — they are Part-A grounding. Pre-registered fallback if the pilot
shows the bonus unearned across all arms: fold one probe into a *mandated
brief step* (the brief requires "record the baseline test-suite result") and
score it as a category point instead of a bonus — decided before fleet runs,
never after.

**Part C — FP rules (−3 each), with rule (b) fixed:**

- (a) a claim about the existing codebase contradicted by the fixture code
  (e.g. asserting an integration point exists when it doesn't);
- (b) **restating a BRIEF constraint as a newly discovered risk or design
  decision** — the FP shape is "flags as a consideration what the brief
  already mandates". *Counts as FP*: "the design must consider that backups
  and restores may run concurrently" (the brief states it). *Does not
  count*: designing the specific mechanism and its trade-offs;
  *does not count*: a true observation about the codebase that the brief
  does not mention.
- (c) factually wrong Python/POSIX semantics asserted in the design;
- (d) the same wrong claim counted once.

**Max 11 (8+3); reachable max for gate purposes: 8** (category-only) — the
+3 bonus is historically unearned territory (0 proofs ever in DR-v2), so
gates run on 8, and gate-3(b) separately tests whether the bonus is earnable
in D's author-controlled loop (§5.3).

**Implementability check — scored (the review's "score it or delete it"):**
a fixed 0–2 questionnaire, executed by a **different-lineage implementer
subagent** (per the lineage rule), budgeted (~$0.05 cap, cheap-tier
implementer), asking exactly: (1) "list the steps you would execute from
this design" — 1 point if every step names its file/function entry point;
(2) "name anything you must ask a human before starting" — 1 point if the
answer is none beyond the brief's own open trade-off. **Penalty for
unexecutable designs:** a design scoring 0 on the questionnaire loses 1
point from its Part-A total (floor 0) — the design-author construct must
not reward unactionable prose. The implementer's output is recorded in the
arm's raw files; it never sees the rubric.

### 4.4 Rubric freeze

`RUBRIC-D1.md` v0 — per-category: what the design must contain, which
grounding forms count, counts / does-not-count pairs, HC triggers, the
brief-restatement FP examples (§4.3), the probe accept-list for Part B, and
the implementability questionnaire — frozen and committed before the first
pilot arm, same amendment rule as §3.6.

`RUBRIC-D1.md` v0 frozen 2026-11-12; **private location (owner-approved
relocation out of the repo, 2026-11-12 pre-freeze fix — same rule as
§3.6):** `~/code_projects/IA-tooling/evals-keys/RUBRIC-D1.md` (private git
repo, separate from the public repo), sha256 (post-amendment,
still pre-pilot — no scores exist):

`62ed6f2f10f260b168adaf23b35d6baa5173101081cc2e80d068330ce598b511  ~/code_projects/IA-tooling/evals-keys/RUBRIC-D1.md`

---

## 5. Calibration protocol (the heart)

Everything below is pre-registered: thresholds are fixed before the pilot
runs; a post-hoc loosening requires an owner override recorded in
`RESULTS.md`.

### 5.1 Pilot composition (4 arms per task, 8 total)

Pilot models — **sonnet-5.5 is in** (the review's point stands: it is the
incumbent of the strong-code/strong-design rungs that I-v2/D exist to
arbitrate; a bench the incumbent wasn't piloted on can't govern that rung):

| Role | Model | Effort |
|---|---|---|
| Strongest | claude-opus-5.5 | default |
| Incumbent of the arbitrated rungs | claude-sonnet-5.5 | high |
| Mid / known "reads-everything-executes-nothing" | gpt-6.1-terra | medium |
| Cheapest tier anchor | glm-5p3-flash | high (I-v2) / low (D) |

**Argon dropped from the pilot** (not added as 5th): its variance is
already two-run-characterized on both v1 and v2 — adding it to the pilot
buys a fourth data point on a known-variance carrier, not new calibration
information, and the pilot budget (§5.7) is better spent on the two-run
variance policy (§5.4). It remains in the fleet stage.

Arms: 1 run per model per task = 8 arms minimum; the §5.4 variance policy
adds re-runs of best/worst arms.

### 5.2 Double-scoring and FP adjudication

- **At least the best and worst arms per task are double-scored** (two
  independent scorer subagents, or one scorer two passes with the rubric
  only) — double-scoring more arms is welcome if scorer budget allows.
- **Pre-registered FP adjudication**: scorer disagreement on any FP
  deduction or category call goes to the **owner**, with both scorings
  attached; scorers never resolve disagreements by averaging. The
  double-score delta on the best/worst arms is itself a datum: it measures
  rubric ambiguity, and the per-pair gap threshold in §5.3 is set above it
  (2× the measured scorer variance).

### 5.3 Gates (per task, I-v2 and D independently)

Score bases: I-v2 reachable max 10, D reachable max 8 (§3.4, §4.3).

- **Gate 1 — anti-saturation:** best completed pilot score ≤ 80% of
  reachable max. I-v2: ≤ 8. D: ≤ 6.4 → ≤ 6 (integer scores).
- **Gate 2 — per-rung competitor pairs (replaces best-vs-worst spread as
  the primary gate).** Pre-registered pairs, one per rung the bench must
  arbitrate, evaluated only between completed arms:
  - strong-code/strong-design: **sonnet-5.5 vs terra**;
  - cheap tier (I-v2 only; D's cheap rung is glm vs itself in the pilot —
    so D's cheap pair is deferred to the fleet tranche, the same mechanism
    that brings the deepseek cell in this bullet): **glm-flash vs
    deepseek-flash** (the deepseek cell comes from the staged fleet's first
    tranche, §5.8, since deepseek-flash is not a pilot model).
  Each pair requires a within-pair gap ≥ **max(3 points, 2× measured
  variance)** — variance = the larger of (i) the pilot's own re-run delta
  on best/worst arms (§5.4) and (ii) the double-score delta (§5.2). If
  variance data is insufficient to set the threshold, the 3-point floor
  applies and the insufficiency is recorded. Best-vs-worst spread remains a
  **secondary** signal only (reported, not gating).
- **Gate 3 — discriminators fired:**
  (a) at least one code-only-detectable defect missed by ≥1 pilot model
  (I-v2) / at least one category failed for want of grounding by ≥1 model
  (D) — otherwise the reading axis is inert;
  (b) the proof/honesty bonus earned by ≥1 arm — if not, the pre-registered
  fallback fires (§3.4 fold-in for I-v2's red-baseline; §4.3 mandated-probe
  for D) *before* the fleet runs. The I-v2 fold-in, mechanically: if no arm
  earns the red-baseline bonus, the bonus is folded into expectations
  before fleet runs — never a re-threshold (the threshold is set on the
  pre-registered max, §9 decision #2);
  (c) **demoted per review**: "zero FPs across all arms" is NOT a gate —
  11-01 showed 0 FP is good model behavior, not a fixture defect. FP-bait
  sufficiency is instead a **fixture-review item**: the pilot report must
  state how many rule-(a)-(d) opportunities the bait offered and whether
  any arm took one; the owner judges from that report whether bait density
  needs raising before the fleet stage.
- **DNF/error/gateway-fail arms are excluded from all gates** (they count
  toward budget, not scores). **< 4 completed arms on a task = "no
  signal"**: the pilot is inconclusive, neither pass nor fail; the re-pilot
  (§5.6) proceeds with the acceptance criteria below unchanged plus the
  missing rung model added to the pilot set.

### 5.4 Variance policy (inverted from v1's silent single-run acceptance)

- The pilot's **best and worst arms per task run twice** (second run after
  first-pass scoring, before gate evaluation). The delta is reported and
  sets the pair-gap floor (§5.3).
- **What gives if the cap cannot buy it** (explicit trade, no silent
  single-runs): the ordering is (1) drop D from the pilot's 2-run policy and
  keep I-v2's (I-v2 arbitrates the more contested rungs); (2) drop the
  cheapest model from the pilot (its gate role is covered by the first
  fleet tranche); (3) as a last resort reduce to 3 pilot models
  (opus/sonnet/terra) — never a silent return to single-run gating.

**Gate-statistic completion (2026-11-12, owner-approved pre-pilot;
thresholds unchanged — §9 decision #2 stands):**

1. **D gate-1 score basis:** D's gate-1 input is the Part-A total AFTER the
   implementability penalty (§4.3: a design scoring 0 on the questionnaire
   loses 1 Part-A point), minus Part-C FPs — mirroring the formula
   semantics of I-v2 (all deductions applied inside the score before the
   gate compares it to the reachable max).
2. **Two-run arms:** for an arm run twice (§5.4), the arm's gate score is
   the MEAN of its runs; the arm's re-run delta is |run1 − run2|.
   Variance for gate 2 = max(all re-run deltas, the double-score delta
   §5.2); the 3-point floor applies when variance data is insufficient
   (unchanged, §5.3).
3. **DNF tolerance (OWNER RULING, 2026-11-12 — approved in the pre-freeze
   Q&A):** the "< 4 completed arms on a task = no signal" rule stands (§5.3);
   in addition, an isolated DNF arm is re-run ONCE before gate evaluation
   when budget allows (a DNF counts toward budget, never toward scores —
   §5.3 unchanged on that too). The "< 4" figure matches the pilot's
   standing composition of 4 models per task — argon is excluded by the
   design itself (§5.1) — so an earlier "5 arms" wording in the §5.1
   heading was stale, and the frozen "< 4" rule was never renumbered.
4. **I-v2 gate 3(a) tags** (v2 definition of code-only-detectable:
   detectable by reading the code, invisible to the baseline suite) are
   recorded per defect in `RUBRIC-IV2.md` — expected: (a), (b), (d)
   code-only-detectable; (c) measurement-forcing.
5. **Dangling cross-references fixed:** gate 3(b)'s I-v2 "§3.4 fold-in"
   means, mechanically, what is now spelled in gate 3(b): fold the bonus
   into expectations before fleet runs, never a re-threshold. Gate 2's
   cheap-tier parenthetical resolves to the cheap-tier bullet in §5.3's
   gate 2 itself: D has no cheap pair in the pilot (glm vs itself), so its
   cheap rung is arbitrated from the fleet tranche that brings the
   deepseek cell (§5.7's provisional-verdict rule below).

### 5.5 Scoring rubric skeleton — shared rules

- **Category found (1 pt)**: precise enough to act on + grounded (§3.5 /
  §4.3 grounding forms). Verbatim from DR-v2's precision standard.
- **Half-credit rules** (killing the cat-3-borderline debate class):
  **HC-1** right mechanism, wrong consequence (or vice versa) → 0.5, one
  half-credit max per category; **HC-2** correct result, wrong justification
  → result point stands, understanding point halves; **HC-3** a
  durability/atomicity gap named without the literal observation → 0.5
  unless the consequence is fully stated. Each rubric category lists its
  HC triggers explicitly. Half-credits sum, capped at 1 per category.
- **FP definitions**: rules (a)–(d) per §3.5 (I-v2, edits) / §4.3 (D,
  claims), with the 11-01 ruling restated: example-FP membership is not a
  deduction.
- **Proof/honesty bonus**: executed commands with observed output only
  (§4.3); reading earns the category point, never the bonus.

### 5.6 No-go ⇒ rework before fleet spend

Failure of any gate on a task sends that task's fixture/rubric back for
rework (reseed depths, sharpen brief, recalibrate bonus), then a **re-pilot
on the same models plus the missing rung model if the first pilot was
no-signal**. Maximum 2 pilot rounds per task; a twice-failed task is
redesigned, not re-rolled.

### 5.7 Staged fleet (the pilot does not unlock the full spend)

- **Stage 0 — pilot** (§5.1): ≈ $2.0–2.5 incl. re-runs (est. opus ≈ $1.2,
  sonnet ≈ $0.6, terra ≈ $0.2, glm ≈ $0.03; hard cap $5).
- **Stage 1 — first fleet tranche, rung-relevant arms only** (§6.2 marked
  ★): the arms that feed gate-2 pairs and the rungs I-v2/D govern
  (~$2.5). **Mid-campaign spread checkpoint**: after stage 1, the pilot +
  stage-1 results are re-checked against the gates with fleet data; a
  collapsing bench (fleet best scores saturating where the pilot spread)
  halts stages 2–3 for an owner decision. **Order, made explicit
  (2026-11-12):** the pilot verdict on gate 2's cheap pair is provisional
  until the stage-1 deepseek-flash cell lands; the pair is evaluated at
  the mid-campaign checkpoint, not at stage 0 alone.
- **Stage 2 — remaining rostered arms** (~$1.5): whole-roster capability
  baseline cells, run only if the checkpoint passed.
- **Stage 3 — opportunistic**: carbon DR-v2 re-run (§6.2) and any
  confirmation runs cited by a rung decision; contingency only.

### 5.8 Enforced caps and the true worst-case ledger

The harness has no timeouts or cost caps today (`run-eval.sh` runs to
completion; 11-10's longest arm was 363 s, but nothing bounds a hung arm).
Caps are therefore **procedural + tooling**, specified here:

- **Wall-clock timeout per arm: 15 min** (largest recorded arm 6.1 min; 2.5×
  headroom). Enforced by the runner script (`timeout` wrapper) — a line-item
  in the run-eval-v3 script spec.
- **Cost check**: a periodic DB cost query per running arm (every 5 min);
  an arm exceeding 2× its per-arm cap is killed and recorded as cost-DNF.
- **Per-arm caps** (parent-only construct, §6.5): cheap ≤ $0.05, mid ≤
  $0.30, strong ≤ $1.00.
- **True worst-case total ledger** (no double-counting — pilot arms that
  are also fleet cells are budgeted once, in the pilot):

| Line | Expected | Worst case |
|---|---|---|
| Pilot (8 arms + best/worst re-runs) | $2.3 | $5.0 (cap) |
| Scorer subagents (incl. double-scores, implementer checks) | $0.5 | $1.5 |
| Fleet stage 1 (rung-relevant) | $2.5 | $3.5 |
| Fleet stage 2 | $1.5 | $2.0 |
| Re-pilots (≤2 rounds, worst task each) | $0 | $6.0 |
| **Campaign total** | **≈ $6.8** | **≈ $18.0** |

The worst case is ~2× the expected total plus full re-pilot allowance; the
owner approves the ceiling, not the estimate.

---

## 6. Re-baseline matrix

### 6.1 Scope decision (replacing v1's "re-run all non-obsolete")

Two honest options: **(A) rung-relevant only (~8 fleet arms)** or **(B)
whole-roster capability baseline (+~$1.7)**. The design recommends **A**
with stage-2 as the owner's opt-in to B — the rungs I-v2/D govern are
strong-code/strong-design (sonnet vs terra, opus above) and the cheap
impl-tier (glm vs deepseek-flash); models whose rungs are governed by
DR/IR/O benches (haiku, M3.1, 1017, argon, qwen) add baseline cells, not
decision data. Full matrix below anyway, with the stage marked.

### 6.2 The matrix (model × bench, corrected cost basis)

Cost basis corrections per review: **opus/sonnet have no per-task cells in
EVALS.md** (09-29 costs n.t.) — derived here as recorded 4-task totals ÷ 4
(opus $1.03/4t → ~$0.26/task; sonnet $0.52/4t → ~$0.13/task) × the I-v2/D
multipliers (I-v2 ≈ 2.5× v1-T2 size, D ≈ 1.5× v1-T4), with lower
confidence flagged; **carbon's estimate uses its recorded high-effort cells**
($0.41 T2-high, 11-10) — v1's $0.30 I-v2 estimate contradicted the caps and
is withdrawn. Stale rung references fixed: deepseek-flash lost
cheap-design-review to M3.1 on 10-23 (its remaining rungs are explore /
cheap-mech / documented fallback); sonnet/opus IR cells are 09-29
qualitative — marked low-confidence, not used in any comparison.

| Model (effort) | Stage | I-v2 est. | D est. | Row total |
|---|---|---|---|---|
| glm-5p3-flash (high/low) ★ | 0+1 | $0.015 | $0.010 | $0.03 |
| claude-sonnet-5.5 (high) ★ | 0+1 | $0.35 | $0.20 | $0.55 |
| gpt-6.1-terra (medium) ★ | 0+1 | $0.13 | $0.08 | $0.21 |
| claude-opus-5.5 (default) ★ | 0+1 | $0.65 | $0.40 | $1.05 |
| fw-deepseek-v4p1-flash (default) ★ | 1 | $0.02 | — | $0.02 |
| fw-deepseek-v4-pro (high) | 2 | $0.15 | $0.10 | $0.25 (gateway-DNF caveat; one attempt, no retries) |
| gemini-4-argon (high) | 2 | $0.20 | $0.13 | $0.33 |
| deepseek-v4p1-flash-1017 (medium) | 2 | $0.09 | $0.06 | $0.15 |
| qwen3p8-2p4t (xhigh) | 2 | $0.25 | $0.15 | $0.40 |
| minimax-m3p1-flash (medium) | 2 | $0.025 | $0.015 | $0.04 |
| claude-haiku-5.5 | 2 | — | — | skip (decision #6) |
| gemini-4-carbon | 3 | — | — | **DR-v2 re-run #2 only (~$0.23)** — see §6.3 |

★ = stage-1 rung-relevant. Stage-1 total ≈ $2.06; stages 1–2 ≈ $3.5.

**Construct note on which rung decisions use which bench:** strong-code/
strong-design rung decisions cite **I-v2 and D**; the DR-v2 carbon re-run
(§6.3) informs only the strong-design-review-alternative fallback. A
delegating model is scored **parent-only** on I-v2/D (§6.5) — no rung
decision on these benches uses child labor.

### 6.3 Carbon warm cell — corrected

Running carbon on I-v2/D measures nothing for its actual role (documented
**upgrade for strong-design-review-alternative if argon regresses**) — its
relevant datum is a **second DR-v2 run at `high` (~$0.23, stage 3)**,
converting its single 10/14 into a two-run cell (argon is already two-run
at 9.5/14). That is the warm-cell spend; the I-v2/D warm cells from v1 are
dropped. **Sol: exclusion unchanged** (off-roster 10-26, re-confirmed
11-12 at 2/14; the fallback conversation re-opens with current models if
terra regresses).

### 6.4 Obsolete / excluded (unchanged from v1, one line each)

ember-1 (dominated everywhere), grok-4.7 (priced out; fallback only),
minimax-m3 (variance), muse-spark (no rung at 15–19×), gemini-3.8-flash
(superseded lineage), nemotron-3p5 (degenerate loops), gpt-6.1-sol (§6.3),
gpt-5.6-terra (superseded), qwen3p8-max (fabricated baseline), fw-glm-5.3
(dominated at ~10×), kimi-k3 / fable-5.1 / gpt-6-luna / gpt-6-sol /
grok-4-20 (each out with recorded reasons; nothing new changes them).

### 6.5 Delegation construct contamination

I-v2 and D briefs **forbid delegation** (the candidate runs alone; a run
that spawns subagents is scored **parent-only** with children reported
separately as a rule-deviation note). Rationale: the I/D construct is
"can this model×effort do this work" — the rungs they govern assign
individual models; delegation folds someone else's labor into the score
(the carbon T2 precedent) and the DR-v2 delegation pattern (parent +
cheap child) is already measured where it belongs. DR benches keep the
delegation-rule scoring (combined labor) unchanged.

### 6.6 Model version pinning

Every arm records **model id @ variant @ provider @ catalog date** in
`RESULTS.md` and the session title where the provider encodes it. Silent-
update risk noted for aliases served behind stable names (opus-5.5,
glm-flash via the gateway): the catalog date plus the DB-recorded token
rates is the pinning evidence; a mid-catalog price change invalidates
cross-arm cost comparisons and must be flagged in `RESULTS.md`.

### 6.7 What is NOT re-benched

- **IR (T3) — keep.** Still discriminates (2/3 vs 3/3 with FP variance
  across rostered models; haiku floor at $0.0063). Revisit if a future
  release sweeps 3/3+bonus-0FP across two families.
- **DR-v1 / DR-v2 — not re-run**, except the carbon stage-3 cell (§6.3).
- **O (T1) — unchanged.**

---

## 7. Risks

1. **New fixture, new blind spots** — pilot arms double as fixture QA;
   unseeded-true findings get the v2 "graded as neither category nor FP"
   ruling and a rubric amendment entry.
2. **Leakage (public repo)** — construct-level exposure from this doc is
    accepted and dated; instance-level answer keys stay outside the repo
    (`~/code_projects/IA-tooling/evals-keys/`); the
   distinctive-string check (§3.8) and restricting eval-run network access
   where the harness allows (the runner already copies fixtures to a fresh
   dir; adding network isolation to the script spec is a line-item) bound
   the rest. Residual risk: a model trained on the repo after this date —
   unverifiable, recorded as an exposure date.
3. **Effort-selection confound** — one rostered effort per model;
   grids only for rung contenders.
4. **D brief miss** — if the pilot shows a category nobody can earn
   (entailment failure), that is a fixture defect: gate 3(a) catches it;
   rework, not re-threshold.
5. **Implementer-check cost/bias** — the 0–2 questionnaire subagent is
   cheap-tier and different-lineage; its judgments are coarse by design
   (steps named vs not), and its raw output is archived for owner audit.
6. **Procedural caps are weaker than harness caps** — the timeout wrapper
   and cost poll are script line-items; if the runner script is not built,
   caps degrade to manual monitoring and the campaign must not start.

---

## 8. Rejected alternatives (updated)

- **Extend `synccli-eval-repo` (v1)**: it is the measuring tool for the
  saturated I-v1 and referenced by every historical row — frozen.
- **Build I-v2 on v2's daemon**: blurs DR-v2's role, double-seeds the same
  daemon, and the impl construct needs failing tests + fix targets.
- **Keep I-v2 in the synccli domain**: three generations of synccli defects
  in a public repo is pattern-matching bait; §3.1 justifies the new domain.
- **Keep the check-then-act lockfile defect**: most pattern-matched bug in
  the public corpus (published in `RUBRIC-T4V2.md`); measures recognition,
  not reading. The O_EXCL fix-trap variant is deferred for prototype
  flakiness (§3.2).
- **Re-bench IR/T3**: still discriminates (§6.7).
- **Score fix minimality as points**: diff-gaming; tiebreak column.
- **Grade D by "does DR like it"**: couples D to a reviewer's FP
  temperament; the taxonomy + implementability questionnaire is
  model-independent. (The questionnaire subagent is the only reviewer in
  D's loop and it is scored, bounded, and archived.)
- **Best-vs-worst spread as the primary gate**: replaced by per-rung
  competitor pairs (§5.3) — a 25% best-worst spread says nothing about the
  pairs the rungs actually decide between.
- **Delegated I/D scoring with combined labor**: contaminates the
  individual-model construct (§6.5); combined-labor scoring stays on DR.

---

## 9. Owner decisions (2026-11-12 — ALL SETTLED, doc is APPROVED for build)

1. **Naming**: ADOPTED — D/DR/I/IR/O with dedicated fixture dirs and the §2.3 migration table (half-session of mechanical edits budgeted).
2. **Gates**: CONFIRMED as pre-registered — anti-saturation ≤80% of reachable max, competitor-pair gaps ≥ max(3 pts, 2× measured variance), DNF exclusion, 2-re-pilot limit. Thresholds are now frozen; they are never adjusted after scores are seen.
3. **D brief**: APPROVED — `backupctl` construct (§4.1); v1 `DESIGN.md` deleted from the D1 fixture (§4.2).
4. **Fleet scope**: **FULL ROSTER** (owner override of the stage-1-only recommendation) — every non-obsolete model gets I-v2/D cells (+~$1.5).
5. **Answer keys**: **PRIVATE PERMANENTLY** (owner override of the untracked-then-public recommendation) — `RUBRIC-IV2.md`/`RUBRIC-D1.md` stay out of git for good; this breaks the DR-v2 public-rubric precedent, so the leakage check may NOT assume eventual publication of past benches (updated in the leakage preamble).
6. **Haiku**: INCLUDED — stage-2 cells for a complete roster row (owner override of the skip recommendation).
7. **Ceiling**: APPROVED — worst case ~$18 (expected ~$6.8), stages 2-3 conditional on the mid-campaign spread checkpoint.

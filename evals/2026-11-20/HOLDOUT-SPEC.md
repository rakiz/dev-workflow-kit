# HOLDOUT-SPEC — Étape 2 held-out fixtures (pre-registration)

**Spec v5 (2026-11-21) — owner slots filled 2026-11-21, no contract change. Keys FROZEN v1 (2026-11-21).**
Nothing in this file is a result. The fixtures are built and both answer keys
are frozen (`evals-keys/HOLDOUT-KEY-MANIFEST.tsv`); **no held-out arm has
run**. Post-freeze changes to the keys are rubric amendments: owner ruling +
fresh fixture hash + a new key version, and the pre-registration is void if any
such change lands after scores exist. **v4 records the M10-A1 amendment
(credential route, §13.1), made pre-launch; the keys are unchanged by it.**
Version note: v1 = pre-registration (2026-11-20); v2 = review change set;
v3 = integration round; v4 = the M10-A1 stamp; v5 = owner slots filled
2026-11-21, no contract change.

- **Author of this spec (R1): strong-design rung, model family deepseek.**
  R1 does **not** interpret the results (PROTOCOL §7: the fixture author is
  not the results interpreter).
- Private answer keys: `~/code_projects/IA-tooling/evals-keys/`
  (`HOLDOUT-KEY-HO2.md`, `HOLDOUT-KEY-HOD.md` drafts accompany this file).
  They never enter the public repo (owner decision #5,
  `BENCH-V3-DESIGN.md` preamble).
- Public repo carries **structure only**: constructs, fixture anatomy, probe
  classes, point budget, gates. No defect identity, no expected values, no
  key tokens.

**Exposure note (dated 2026-11-20, BENCH-V3-DESIGN preamble precedent; scope
narrowed per review M1).** This file exposes *construct-level* information only
— the four shape families, the four hazard classes, the probe classes and the
fixture anatomy. Any fixture built from
it must assume adversarial familiarity with the *shape* but not the instance:
locations, mechanisms, expected values and probe scripts live only in the
private keys, and the single-use/rotation rule (§5.4) exists because this
exposure is permanent.

---

## 0. Why this document exists (the failure it fixes)

The current seat basis is defective on its own pre-registered terms:

- **RG4 (I2) is saturated and its gates fail.** Best eligible 13.5/14 = 96 %
  (Gate 1 requires ≤ 11); haiku-high vs opus gap 0.0 (Gate 2 requires ≥ 3).
  `2026-11-20/RESULTS.md` §5: *"Any seat decision needs a harder fixture or a
  gate revision."* Seven roster rows cite I2 for their seat
  (`LEADERBOARD.html` `#roster`: cheap-code, cheap-mech, explore, strong-code,
  strong-code-alternative, strong-code-alternative2, deep).
- **D's MDE is the only measured one small enough to be usable** (1.04 pt;
  `noise-mde.tsv`), and its key was materially amended after scores existed
  (D-key v3: H4 alternative credit, H2 wording) with the re-fold computed but
  *not* applied as a seat decision (`2026-11-19/RESULTS.md` §7.3).
- The public fixtures are the leak vector: the RG4 defect IDs once leaked into
  public docs (`2026-11-20/RESULTS.md` §7.3) and the D1 hazards live in
  public code. A held-out exists to kill exactly that.

---

## 1. Bench scope — recommendation, with the data that decides it

**Recommendation: two held-out benches only — HO2 (impl, validates I2-RG4)
and HOD (design, validates D).** The owner's working assumption is correct,
but for a sharper reason than "most seats hang on it", and with one
correction: the impl held-out must be **harder**, not merely different,
because RG4's failure mode is the ceiling.

| Bench | Seats citing it (roster) | Current basis | Operative noise floor | Held-out? |
|---|---|---|---|---|
| **I2-RG4** | 7 rows (cheap-code, cheap-mech, explore, strong-code, strong-code-alt, alt2, deep) | **gates FAIL** (saturation) | measured 4.80 at n=2 (`noise-mde.tsv`, I2-RG4 combined) | **YES — mandatory** |
| **D** | 5 rows (cheap-design, strong-design, strong-design-alt, alt2, deep) | non-saturated; gap 9.81 vs 8.08 = 1.73 | measured **1.04** (`noise-mde.tsv`, D combined) | **YES** |
| IR | 4 rows (cheap-review, strong-review, alt, alt2) | 4.33 / 4.0 / 3.83 / 3.62 — all inside the recorded 1-pt family offset | **unmeasured**; 4-run sample degenerate (zero variance, `noise-mde.tsv`) | NO (§8) |
| DR2 | 3 rows | 11.25 vs 9.5 vs 10 vs 9.0 (`grid2-scores.csv`); nobody within 2.5 of the seat | unmeasured; degenerate | NO (§8) |
| O | 1 row | 7/8 panel at $0.005 | **MDE 9.68 on an /8 scale** — ungateable at n=4 | NO (§8) |

**Why I2 despite a 4.8-pt floor.** Its seat basis is *invalid* (the gate it was
scored under failed), and it decides seven rows. It is the only bench where a
large reversal (≥ ~4.8 pts) is still worth detecting at n=2: it can catch a
holder that collapses or a challenger that fails two defects. It cannot
resolve fine orderings, and this spec does not pretend it can (see §7.4).

**Why D.** It is the only bench with a measured, non-degenerate floor small
enough to be usable (1.04), so a held-out result is *decidable* at n=2, and
its key was amended after scores existed — the cleanest possible case for a
fresh surface.

**Challenge to the assumption, and where I part company with it:** the
impl held-out is not "one of two benches, equal weight". It is the *only*
bench whose current seat decisions are gate-invalid, so it is the primary
instrument; D is confirmatory. Budget follows the same split: 80 % of the *mandatory*
deciding-run spend goes to HO2 (§7.1); the phase-2 design block is the
optional tail.

---

## 2. Construct definitions

### 2.1 HO2 — held-out impl (validates I2-RG4)

**What it measures (identical construct, fresh surface).** Given a small
working codebase, a feature request and a set of stated invariants: find
seeded defects the shipped suite cannot see, fix them with the smallest
change that keeps the suite green, add a regression test per fixed defect
that fails on the pristine tree, measure a performance hazard rather than
guess it, and commit to one of two defensible failure policies and make the
artefacts consistent with it. Scored by executed probes, not prose.

**Mapping to I2-RG4.** Same four shape families (spec-vs-code contradiction,
cross-file state consistency, measurement-forcing perf hazard, fix-shape
ambiguity), same scoring formula (`BENCH-V3-DESIGN.md` §3.4/RG4 key), same
probe-first scoring, same "no red baseline in the scoring path" rule.
**Never compare HO2 and RG4 scores** (PROTOCOL §2 rule 3): new fixture, new
prompt file, new title token.

**Freshness (the non-reskin requirement).** Domain: **deterministic workshop
scheduling** — assign jobs to machines under shift capacities, emit a plan,
a timetable and an index. No CSV-summary/cache/report shape, no transform
registry, no state.json, no input-directory loop. The four defect *shapes*
are reused; not one identifier, docstring sentence, file name or probe from
`reportgen-eval-repo-i4` is reused (ban list in §5.1).

**Point budget (structure only — the answers live in the key):** max 14,
Gate 1 ≤ 11 (80 %). Gate 2 is a *screen* (gap ≥ max(3, 2 × sd_anchor)); its
variance basis differs from the seat band's, which is harmless because no seat
verdict rests on Gate 2 (M-l).

### 2.2 HOD — held-out design authoring (validates D)

**What it measures.** Given a fully specified brief and a small real
substrate, *author* the design: entail every hazard class, ground every
category in the shipped code (file:function), discover execution-revealed
hazards in the substrate and state their handling, and prove claims by
executed commands — not prose.

**Mapping to D.** Same D1-v3 formula (`RUBRIC-D1-v3.md`): Part A taxonomy
(8 → ÷2 = 4), Part H hazard discovery (4 × 1), Part B executed proofs (0–3),
implementability penalty (−1, floor 0), FPs (−3), M = 11, Gate 1 ≤ 8.8.
New brief, new substrate, new hazards; D1's hazards and prose are banned
(§5.1).

**Freshness.** Domain: **resumable, deduplicating upload to a content-addressed
chunk store** (`ingestctl`). Substrate: `chunkstore.py` + `uploader.py`. Not a
backup/restore tool, not a sync tool, not a snapshot helper; every hazard is a
different mechanism from D1's four (`RUBRIC-D1-v3.md` H1–H4).

---

## 3. Fixture designs

### 3.1 HO2 — `evals/heldout-impl-sp1/` (fixture code **SP1**, task code **HO2**)

Size class: reportgen-i4 is 9 files / ~500 code lines. SP1: **3 Python
modules** (`plan.py`, `planio.py`, `cli.py`) + 2 test files + `GOAL.md` + 5 data
files, ~520 code lines (M-c).

<!-- MINOR 15: data/jobs_test40.csv is part of this inventory and the c_test input -->
| File | Responsibility |
|---|---|
| `plan.py` | job/machine model and the assignment logic (deterministic: no randomness, no wall-clock, fixed tie-break) |
| `planio.py` | plan, timetable, index and summary I/O |
| `cli.py` | CLI entry point; exit codes per the policy the candidate chooses |
| `test_plan.py` | baseline suite (green on the pristine tree) |
| `test_legacy_plan.py` | one **pre-existing failing test** — report-only, *not* in the scoring path, fix-only-if-asked (RG4 rule carried over) |
| `GOAL.md` | the brief (§3.3) |
| `data/machines.csv`, `data/jobs_small.csv`, `data/jobs_partial.csv`, `data/jobs_test40.csv`, `data/jobs_large.csv` | fixed inputs; the 40-job and large files are committed, never generated at run time |

No `.git`, no flaw-flagging comments, no `TODO`, no file names that hint at a
defect. The pristine tree must run the suite green and `cli.py` must complete
on the shipped small input.

#### The four seeded defects — **shape families only**

The instance-level design (locations, mechanisms, probe inputs, expected
pristine/fixed outputs) lives **only** in `evals-keys/HOLDOUT-KEY-HO2.md`
(review M1). The public record carries the families:

- **(a) spec-vs-code contradiction** — a documented guarantee the code does
  not provide; the docstring is bait only and the fix is graded on behaviour
  (the probe never reads the prose).
- **(b) cross-file state consistency** — two artefacts of the same run
  disagree on a derived quantity, invisibly to the shipped suite.
- **(c) measurement-forcing performance hazard** — the cost grows with the
  input; the GOAL states a measured acceptance and the report must carry the
  counts.
- **(d) fix-shape ambiguity** — two defensible policies, each with an explicit
  pre-registered end state (the F2 lesson: `PROTOCOL.md` §5(d), F2).

**Deliberately NOT seeded:** any check-then-act lockfile pattern; any defect
whose probe needs concurrency, a clock or randomness; any defect a grep for
`TODO`/`FIXME` finds; any defect already published in the public corpus
(`BENCH-V3-DESIGN.md` §3.2 rationale carried over).

### 3.2 HOD — `evals/heldout-design-us1/` (fixture code **US1**, task code **HOD**)

| File | Responsibility |
|---|---|
| `chunkstore.py` | content-addressed chunk store: chunk id, store/get, chunk iteration, read-back by recorded metadata, orphan GC |
| `uploader.py` | single-shot upload, retry wrapper, remote manifest append |
| `test_chunkstore.py` | green suite over **happy paths only** — it does not exercise the hazard surfaces |
| `BRIEF.md` | the brief (§3.4) — no hazard hint |

The substrate is shipped code the design must build on. The four hazards are
true of it, invisible to its green suite, and deterministic to probe; each
maps to a different taxonomy category and to a *different mechanism* from
D1's four. Instance-level identity, probe inputs and expected values live
**only** in `evals-keys/HOLDOUT-KEY-HOD.md` (review M1).

Hazard classes (class names only; instances and mechanisms private):
**(H1)** address/dedupe stability; **(H2)** round-trip boundary correctness;
**(H3)** idempotency of a retried partial failure; **(H4)** resource-bound
honesty (a *claimed* bound). Each is true of the shipped substrate, is
invisible to its green suite, is deterministic to probe, and maps to a
different taxonomy category and a different mechanism from D1's four. All four
are *handled in the design*, not fixed in code.

### 3.3 `GOAL.md` for HO2 (build to this text; it names no defect)

The builder writes exactly this brief, filling only the data-file names:

> # Goal — next release of the planner
>
> Two features: (1) honour the existing `machine` column as a preference — place
> the job on the named machine when it has room, otherwise on any machine where
> it fits (today the column is ignored); and (2) a summary line on stdout
> reporting total scheduled minutes per machine.
>
> Invariants (binding):
>
> - A job appears at most once in a plan, and no machine is ever over its
>   shift length.
> - On `data/jobs_large.csv`, the number of placement attempts must be at
>   most 8 per job. Measure it (count the attempts your run performs) and
>   report the pristine and fixed counts in your final report, with the
>   commands you used.
> - Some jobs cannot be placed. Pick one policy and make every artefact
>   consistent with it:
>
> | Situation | Policy A — fail-fast | Policy B — partial with report |
> |---|---|---|
> | ≥ 1 job unschedulable | exit 1; `plan.json`, the timetable, `index.json` and `summary.json` (if present) byte-identical to the previous good run; offending job ids on stderr; no `unassigned.txt` | exit 0; `plan.json` holds every schedulable job; `out/unassigned.txt` lists the unschedulable ids; `summary.json` has `"partial": true`; index loads equal the plan |
>
> Before changing anything, run both shipped suites and record the result in
> your final report — for each, the exact command and its observed output, as
> executed on the repo before your changes:
> `python3 -m unittest test_plan` and `python3 -m unittest test_legacy_plan`.
>
> The repo may contain defects. Fix any you find with the smallest change that
> keeps `python3 -m unittest test_plan` green and the invariants holding; add a
> regression test per fixed defect; state in your final report any trade-off
> this brief leaves open, with the choice you made and the cost it accepts. Do
> not refactor; do not touch unrelated tests. You work alone — no subagents,
> no delegation.
>
> Constraints: Python 3.10 stdlib only, no new dependencies. Run from the repo
> root: `python3 cli.py --jobs data/jobs_small.csv --machines data/machines.csv --out out/`.

<!-- MINOR 12: the policy-A end state includes summary.json (byte-identical) -->
**M2 choice = option (i) — RG4-level hints only.** The GOAL states the
generic safety invariant, the measured performance acceptance and the
two-policy final-state table, and nothing else: the (a) and (b) acceptances
are **discovery items**, exactly as RG4's GOAL stated two of its four
acceptances and left the other two to be found. The two requested features carry **no points** (RG4 F3
precedent); they exist so a correct fix must survive a real change (MINOR 11).
The F2-safe part is kept: the unschedulable-job situation has two named end
states and the table is the grading contract.

### 3.4 `BRIEF.md` for HOD (build to this text; it names no hazard)

> # BRIEF — design `ingestctl` (fixture US1)
>
> ## Context
> This directory contains a small, working content-addressed chunk store
> (`chunkstore.py`, `test_chunkstore.py`) and a single-shot uploader built on
> it (`uploader.py`). `ingestctl` is a new command-line tool that ships in this
> repo and uploads large files to a remote object manifest. It reuses this
> code; it does not re-implement what the code already covers.
>
> ## What `ingestctl` must do
> - Upload a file of any size to a store directory plus a remote manifest of
>   objects. Two uploads may run at the same time (same or different files),
>   and a garbage-collection run may overlap either.
> - A reader of the manifest must never see an object the store cannot serve
>   in full. A crash at any point — SIGKILL, power loss — must leave nothing
>   behind that a later reader would mistake for a complete object, and the
>   next run must make progress without manual cleanup.
> - The store only grows: state the store's growth as a function of what is
>   uploaded, and define when a chunk may be deleted. Deletion must never
>   break a live object, and must be safe while an upload is running.
> - Resume: after an interruption, a re-run must not re-upload what is already
>   durable. State the granularity at which "durable" is decided, and what an
>   edit at that granularity can miss.
> - A chunk upload can fail transiently (timeout after the server applied it).
>   The run must never double-count, and its reporting must say what actually
>   landed.
> - State the performance budget for the first upload of a ~1 GB file and show
>   where the number comes from (measurement on this machine, or an explicit
>   derivation).
> - State what grows with what — memory, store size, manifest size, per-run
>   work — every claim as an explicit bound (a number, a formula over file
>   size/chunk size/object count, or a measured constant). "Stays bounded"
>   without the bound is not an answer.
> - A chunk may be missing or corrupt when a resume or a read reaches it. Say
>   how it is detected and what happens next.
>
> ## Grounding
> Wherever your design touches chunking, addressing, storage, upload or
> retry, name the exact existing file and function it builds on, and what that
> function actually does. A reference counts only if the artefact exists and
> behaves as you claim (cite file and function; line numbers when you have
> them). Where you must behave differently from the shipped code, name the
> exact function you override and the reason. A design that could have been
> written without opening this code is not grounded in it.
>
> ## Deliverable and working mode
> - Write the design to `DESIGN-us1.md` in this directory.
> - Work alone: no subagents, no delegation. Every part of the design is yours.

Category entailment check (the builder must confirm the text still entails all
8 Part-A categories: concurrency, atomicity/crash, retention/GC, detection
granularity, partial-failure integrity, perf-budget honesty, boundedness,
error semantics). If a category is not entailed, fix the brief — do not add a
category to the key.

---

## 4. Probe battery (the §3.8 contract — classes only)

**Universal rules.** Every probe is executed by the **scorer**, in a fresh
scratch copy of the candidate's run dir (`cp -R`, `python3 -B`), never in the
run dir itself. No wall-clock, no `sleep`, no randomness, no network. Every
probe runs **×3 consecutive rounds** in fresh copies against **both** the
pristine tree (must fail deterministically, identical result every round) and
the reference-fixed tree (must pass deterministically, identical result every
round). A probe that is not stable ×3 disqualifies its defect *before the
freeze* — it is replaced, never averaged (`BENCH-V3-DESIGN.md` §3.8).

**The pass/fail contract lives in the private keys.** This section names the
probe *class* per slot only; the command, the fixture input, the injection
technique (M-b: classes only in public), the expected pristine value and the
expected fixed value are key content (review M1). The keys are frozen together
with the hashes (§5.3).

**Score-level conjuncts.** An executed probe point is credited only together
with the deliverable's own validity, as each key states. The specific
conjuncts (which artefacts are compared, what "valid" means, which end state
must hold) are key content; their existence is public (review M3/M5).

### 4.1 HO2 — probe classes per defect slot

| Slot | Probe class |
|---|---|
| (a) | injected serialization/write failure on the save path |
| (b) | two-artefact comparison of the same run |
| (c) | operation count vs a pristine baseline on the shipped large input |
| (c-quote) | executed-evidence check of the counts quoted in the report |
| (d) | branch probe of the stated policy's pre-registered end state |
| tests | own-tests-on-pristine (RG4 pattern: extract before overlay) |

### 4.2 HOD — probe classes per hazard

| Slot | Probe class |
|---|---|
| H1 | address-stability check (M-a) |
| H2 | round-trip length/content check |
| H3 | injected lost-acknowledgement |
| H4 | resource-bound measurement (a counted proxy, never RSS) |

`fixed` in the keys means the **reference repair of the substrate**, used only
to prove the hazard is real and the probe discriminates; candidates are not
scored against it. The Hn credit rule (name + true + handling) is key content.

### 4.3 Probe-unevaluable rule (pre-registered)

If a probe cannot be evaluated on the candidate's tree — the injection never
reaches the write path, the entry point was renamed away, the counter target no
longer exists — the item scores **0 with a scorer flag**, never a pass and
never an average (review M4/M14). The flag names the reason; the run is still
scored on its other items. The key lists, per slot, the one failure mode that
counts as "this defect's failure" (review M14).

### 4.4 What the probes must NOT reveal

The probe commands and expected values are key content. No expected numeric
value, no function name of a seeded defect and no distinctive string appears in
this file or any other public file (§5.2).

## 5. Hygiene

### 5.1 Ban list (the non-reskin check, mechanical)

**Mechanical, not judgmental** (review MINOR 1): the ban list is itself a
file, `evals-keys/holdout-ban.txt` (one identifier per line), and the check is
the grep form in §5.2 run over every new fixture file. Zero hits required.
The ban is an **identifier** check, not a semantic one (MINOR 2): it does not
claim the fixtures are free of resemblance, only that no banned identifier is
copied.

1. Identifiers from `reportgen-eval-repo-i4/`: `REGISTRY_VERSION`,
   `generated_from`, `rules_fp`, `TransformError`, `validate_summary`,
   `skipped_rows`, `rules.example.toml`, `currency_amount`, `round2`,
   `date_iso`, `reportgen`, `state.json`, `file_digest`, `rules_fingerprint`,
   `make_entry`, `summarize_file`, `load_state`, `save_state`.
   (Bare domain words — `registry`, `cache`, `report` — are not banned; the
   ban is on identifiers. The HOD domain legitimately uses "manifest" and
   "store", which are not D1 identifiers.)
2. Identifiers from `syncfeat-brief-d1/` + `synccli-eval-repo`: `synccli`,
   `snaputil`, `backupctl`, `sync_manifest`, `MANIFEST_NAME`,
   `build_manifest`, `changed_files`, `snapshot`, `prune_snapshots`,
   `safe_snapshot_path`, `is_stale`, `list_snapshots`, `scan_files`,
   `copy_file`, `collect_stale`.
3. Any docstring sentence of the four RG4 defects or the four D1 hazards
   (the key lists them; the builder greps each full sentence).
4. `TODO`, `FIXME`, `XXX`, `HACK`, `BUG`, `broken`, `workaround` in fixture
   code and prose.
5. The names HO2/SP1/HOD/US1 in any *other* fixture (cross-contamination).

Fixture size class (M-d, amended by **OPEN-3** at build close-out): the guide
is **impl 350–600 / design 180–300 code lines**. The built fixtures measured
**SP1 188 / US1 158** and are **accepted as-is** — no filler was added,
because difficulty here is defect/hazard subtlety, not LOC (author ruling,
2026-11-21). Consequence stated: a smaller fixture is faster to read whole, so
the discrimination risk is real; it is guarded by (a) the interaction defects
and the measurement axis, (b) Gate 1's ratio test (80 % of max), which does not
depend on LOC, and (c) the pre-registered rule that a Gate-1 failure on a
held-out is repaired by **sharpening or adding a defect, never by padding
LOC**. The measured LOC is recorded in each key's fixture-inventory section
(and those keys are hashed by the freeze manifest). The pristine↔fixed diff
stays ≤ 120 changed lines.

<!-- MINOR 3: grep forms with --exclude-dir and -I; three roots (repo, SP1, US1) -->
### 5.2 Leak grep (before =freeze, after =results, and before any re-use)

Tokens are defined **only** in the private keys. Two token files drive the
check (both private): `evals-keys/holdout-tokens.txt` (the distinctive strings
of both benches) and `evals-keys/holdout-ban.txt` (the §5.1 identifier list).
Exact forms (paths relative to the repo root; `-I` skips binaries):

```bash
TK=evals-keys/holdout-tokens.txt; BAN=evals-keys/holdout-ban.txt
LC_ALL=C grep -rnIF --exclude-dir=.git --exclude-dir=__pycache__ \
  --exclude='*.pyc' --exclude='.DS_Store' -f "$TK" dev-workflow-kit/ || echo ZERO-HITS
LC_ALL=C grep -rnIF --exclude-dir=.git --exclude-dir=__pycache__ \
  --exclude='*.pyc' --exclude='.DS_Store' -f "$BAN" \
  dev-workflow-kit/evals/heldout-impl-sp1 dev-workflow-kit/evals/heldout-design-us1 \
  || echo ZERO-HITS
```

Zero hits over the public repo including this spec, the fixtures, the README
and the date folder, and over both fixture trees. Any hit blocks the campaign.
The past leak (RG4 IDs in `2026-11-19/RESULTS.md`) is the precedent for why
this is mechanical. The two token files are hashed (§5.3) and never enter the
public repo.

<!-- MINOR 5: hash file-set + out/cache/__pycache__/.pyc/.DS_Store exclusions -->
### 5.3 Hash manifest (freeze artifact; recomputed scope)

**Scope after the review** (this section replaces the earlier one; the
artefact set changed): the public fixture trees, the private keys, the
**private reference-fixed trees** (M12), the two token/ban files and the
per-arm config template are all hashed. Generated artefacts are excluded.

```bash
H() { find "$@" -type f \
        -not -path '*/__pycache__/*' -not -name '*.pyc' \
        -not -path '*/out/*' -not -path '*/cache/*' \
        -not -name '.DS_Store' \
      | LC_ALL=C sort | xargs shasum -a 256; }
H dev-workflow-kit/evals/heldout-impl-sp1/ > /tmp/ho2.files
H dev-workflow-kit/evals/heldout-design-us1/ > /tmp/us1.files
H evals-keys/ho2-ref-a/ evals-keys/ho2-ref-b/ evals-keys/us1-repaired/ > /tmp/refs.files
shasum -a 256 /tmp/ho2.files /tmp/us1.files /tmp/refs.files \
  evals-keys/HOLDOUT-KEY-HO2.md evals-keys/HOLDOUT-KEY-HOD.md \
  evals-keys/holdout-tokens.txt evals-keys/holdout-ban.txt \
  evals-keys/holdout-config-template.json
```

| Artefact | Location | Manifest |
|---|---|---|
| SP1 tree (per-file + tree hash) | public `evals/heldout-impl-sp1/` | `HOLDOUT-MANIFEST.tsv` (public, hashes only) |
| US1 tree (per-file + tree hash) | public `evals/heldout-design-us1/` | `HOLDOUT-MANIFEST.tsv` |
| HO2 key, HOD key | private `evals-keys/` | `HOLDOUT-KEY-MANIFEST.tsv` (private) |
| ref-A, ref-B, US1-repaired | private `evals-keys/ho2-ref-*/`, `evals-keys/us1-repaired/` | `HOLDOUT-KEY-MANIFEST.tsv` |
| tokens, ban list, config template | private `evals-keys/` | `HOLDOUT-KEY-MANIFEST.tsv` |
| spent archive (post-campaign only) | private `evals-keys/holdout-spent/<code>/` | `HOLDOUT-KEY-MANIFEST.tsv` + public `SPENT <date>` marker |

Tree hash command (same method as `BENCH-V3-DESIGN.md` §3.6): the per-file
lines above, piped to `shasum -a 256`. Recompute after every edit and after the
campaign; a mismatch invalidates the campaign (a fixture edited mid-campaign is
not the pre-registered one). **No hash value existed until the freeze**: the
fixture hashes were recorded in `evals/2026-11-20/HOLDOUT-MANIFEST.tsv` and the
key hashes in `evals-keys/HOLDOUT-KEY-MANIFEST.tsv` at freeze (2026-11-21,
keys v1).

### 5.4 Single use + rotation

- **Single use:** SP1 and US1 are used by exactly one campaign (this one).
- **Post-campaign location (review MINOR 4):** at closure the two fixture
  directories are **removed from the public tree** and archived in the private
  repo as `evals-keys/holdout-spent/<code>/`; the public tree keeps only the
  `HOLDOUT-MANIFEST.tsv` row and a `SPENT <date>` marker. The public git
  history is not rewritten (no commit without the owner's go); the archive
  location is what prevents a future model generation from reading a fresh
  copy of a spent fixture.
- **Rotation triggers (any one):** (i) a new model generation enters the
  roster; (ii) any candidate artefact or scorer log referencing the fixture
  becomes public; (iii) the fixture is older than 90 days; (iv) the key is
  amended after scores exist. A rotated fixture requires a new domain — the
  rejected-domain list in each key exists so the next author does not recreate
  the same surface.
- **Key disclosure:** private until the deciding campaign closes; then the key
  may be referenced (never copied) in the public results, construct-level only.

### 5.5 Network and filesystem isolation for candidate runs (fail-closed)

Verified today: `run-eval-v4.sh:112–116` and `run-eval-v5.sh` contain **no**
isolation — v4 has a comment saying "when the harness allows it" and v5 has
nothing. So this is new work, and it gates the campaign like the cost caps do.

**Fixture copy (M-n).** The runner copies the fixture into the arm's work dir
**before** the sandbox profile is applied; the profile never grants read access
to the source fixture location, so the candidate sees one copy and cannot read
the others or the private trees.

**Mechanism (macOS).** Wrap the `opencode run` invocation in a
`sandbox-exec` profile that is **default-deny** for both filesystem and
network, with **per-arm allow-lists** (review M9 — no shared tmp root, so one
arm cannot read another's work dir, config, DB or output):

- read: `/usr`, `/bin`, `/sbin`, `/opt/homebrew`, `/System`, `/Library`, the
  runtime's own `/private/var/folders/<this-process-tmp>` subtree **only**,
  and this arm's work dir, config dir and data dir (exact paths, no
  directory-prefix sharing between arms);
- read+write: this arm's work dir and data dir only (the config dir is
  read-only inside the sandbox);
- **deny (explicit, after the allows):** `~/code_projects/IA-tooling`, the
  private `evals-keys/` tree (keys **and** reference-fixed trees, M12), the
  global opencode data dir, and the host credential file (M10);
- network-outbound: **only** `127.0.0.1:<proxy-port>`; everything else denied.

**Credential route (review M10, AMENDED pre-launch by M10-A1 — §13.1).**
INJECTION is replaced by **PASS-THROUGH + METERING**. The arm runs with its own
**per-arm copy** of the auth store (copied from the global store before launch,
mode 600, inside the arm's allow-list), and the provider request passes
through with that credential. This is required because the Copilot OAuth
refreshes **inside opencode's own plugin** (a static injection breaks the
refresh), `sandbox-exec` cannot express per-process file ACLs, and the exposure
being defended against was already the operating baseline (400+ unisolated runs
to date).

The M10 invariant, as amended:

> **no NON-allowlisted egress; every egress byte/request metered per arm; the
> arm's auth store is a per-arm copy (readable by the arm by design — residual
> risk ACCEPTED and recorded: abuse is detectable via the meter + absent from
> the DB roll-up); the credential never crosses to another arm's allowlist.**

The proxy remains the **allowlist + meter** (not a credential holder): it
permits only the provider hostnames, counts requests and tokens per arm, and
enforces the per-arm cap. "Absent from the DB roll-up" is the detector logic:
out-of-band use of the arm's own credential would not appear as opencode
session spend, so the **meter**, reconciled against the DB roll-up, is what
surfaces it. **Residual risk, stated honestly:** an arm could in principle use
its own credential out-of-band. It is **accepted rather than eliminated**
because (a) the brief never mentions credentials and the fixture gives no
reason to touch them, (b) the meter surfaces an egress/request anomaly, (c) the
DB roll-up reconciles opencode-side spend against the meter, and (d) the
campaign kill poller enforces the cap on the meter. The per-arm copy stays
inside its arm's allow-list; no other arm's sandbox includes it, and the
proxy's allow-list is bound to that arm's credential — **the credential never
crosses to another arm's allowlist.**

**Preflight assertions — the campaign aborts unless all pass** (one cheap
model call, ~$0.001, counted in the budget):

1. `curl -sS https://example.com` inside the sandbox exits non-zero.
2. `sqlite3 ~/.local/share/opencode/opencode.db 'select 1'` inside the
   sandbox exits non-zero.
3. `cat ~/code_projects/IA-tooling/evals-keys/HOLDOUT-KEY-HO2.md` exits
   non-zero.
4. `cat ~/code_projects/IA-tooling/evals-keys/ho2-ref-a/planio.py` inside the
   sandbox exits non-zero (M12: the reference fixes are private and
   unreadable).
5. The **per-arm** auth store exists, is mode 600, and is a copy (not a
   symlink) of the global store; the **global** `~/.local/share/opencode/auth.json`
   is unreadable inside the sandbox; **another arm's** store is unreadable
   inside this arm's sandbox (M10-A1).
6. A trivial `opencode run` with the per-arm data dir completes (exit 0, DB
   written, message captured), the provider call passes through the allowlisted
   proxy, and the **meter's request count increased** for this arm (M10-A1).
7. The per-arm cost poller **and** the campaign-level kill poller prove
   liveness (each writes a heartbeat at least once before the arm's first
   minute; MINOR 6) — a dead poller aborts the arm.

If any assertion fails, **no arm runs**. Degrading to "un-isolated" is an owner
decision recorded in the results, not a builder choice.

### 5.6 Per-arm opencode state, config and the hard budget

**Per-arm data dir (the DB leak).** A candidate's shell can read other
sessions from the global DB (other arms' reports). Each arm therefore runs
with its own data dir:

- `XDG_DATA_HOME=<tmp>/holdout-xdg/<title>/` (opencode honours
  `XDG_DATA_HOME`; verified in the 1.19.5 binary's bundled code, **not yet
  exercised end-to-end** — preflight assertion 6 covers it);
- **per-arm auth store**: a copy of the global `auth.json` (mode 600, not a
  symlink), readable by the arm **by design** (M10-A1); never shared with or
  visible to another arm;
- the cost poller, the watchdog's DB reads and the final-report capture all
  query `<that dir>/opencode/opencode.db`;
- `run-campaign.py` computes the same path from the title it builds, so
  admission and post-run cost still work; `campaign_spend` sums the global DB
  (for `panel-%` sessions, which are trusted) plus every per-arm DB created
  since the campaign start.

**Per-arm config (review M11).** `XDG_CONFIG_HOME=<tmp>/holdout-cfg/<title>/`
contains exactly one config file, `opencode/opencode.json`, plus whatever
opencode itself creates (hash-recorded in §5.3):

- only the provider entry for the arm's model (no extra providers);
- `"mcp": {}` — every MCP server disabled;
- no plugins and no subagent definitions (the arm must run alone);
- the permission rails kept: `bash` allowed for the fixture commands, `git
  push` denied, `git commit` ask (which in an unattended `--auto` run resolves
  to deny) — the rails are never relaxed by the held-out config;
- no `instructions`/`AGENTS.md` beyond what the fixture ships.

The global `~/.config/opencode` tree is not readable inside the sandbox, so
the candidate cannot consult the roster, other agents, or the kit's global
instructions.

**Hard budget (review M13).** Three independent stops:

1. **Per-arm:** the runner kills an arm at 2× its cap (unchanged), and a
   per-arm cost poller must prove liveness (MINOR 6 / assertion 7).
2. **Campaign admission:** the driver refuses an arm unless
   **`spend + 2×cap ≤ budget`** — the true worst case is bounded, not the
   expected cost. `budget_usd = 15.00`.
3. **Campaign-level kill poller:** a driver-side poller sums spend every 30 s
   and stops the whole campaign (kills the running arm, refuses the rest) when
   spend exceeds `budget_usd`. This is the backstop for a poller that dies on
   an arm: the runner's own poller is not the only guard.

Per-arm timeouts (pre-registered, review M13): **≥ 1800 s** for sonnet and
opus on HOD; **≥ 900 s** for every other arm (the v4 default). A deviation is
recorded and treated as a protocol deviation, not a silent choice.

**Scope of the admission change (OPEN-10, ratified 2026-11-21).** The
`spend + 2×cap ≤ budget` rule in `run-campaign.py` is **global**: it applies to
v4/v5 campaigns too. Ratified because the new rule is **strictly more
conservative** — it can only refuse arms the old rule admitted, never admit one
the old rule refused. It changes no score and no past result; the only
consequence is that a legacy campaign under the same budget may stop earlier,
and that must be recorded in its status file when it is re-run.

The runner script is a **new** `run-eval-v6.sh` (plus a small
`run-campaign.py` change): v4/v5 are frozen records of earlier campaigns
(`run-eval-v4.sh:9–11`). Task codes `HO2` and `HOD` get their own title
tokens, so no cost query ever conflates a held-out run with a live-bench run.

### 5.7 Author ≠ interpreter ≠ scorer (roles, not identities)

| Role | Agent rung | Constraint |
|---|---|---|
| R1 spec author | strong-design (this doc) | never interprets results |
| R2 spec critic | strong-design-alternative, **different family from R1** | must critique before the build starts |
| R3 fixture builder + key completer | cheap-code (mechanical build to this spec) | may not change the design; may not score |
| R4 key reviewer | cheap-review, different family from R3 | verifies the key against the built fixture, probe by probe |
| R5 key freezer | owner | records hashes, signs the freeze |
| R6 run operator | any agent, execution only | cannot edit the key or the rubric |
| R7 panel scorers | three families available: **glm, minimax, haiku**; two per run per the pairing table below | **self-family never scores its own family's artefact**; a fresh instance **per batch session** (I4: no resumed session across benches or families) |
| R8 arbiter + FP adjudicator | owner, or an **arbiter family** that is neither the artefact's family nor one of its two scoring families (`gemini-4-neon` for every bench in this campaign) | **advisory only**: supplies one recorded reading for divergent runs and rules FP disputes; never averages, never decides a verdict-straddling divergence (that goes to the owner) (I6); cost is budgeted (§7.2) |
| R9 results interpreter | a family **not** R1's and not the fixtures' authors | writes the results; R1 does not |

**Pre-registered scorer pairing** (so every arm has two families and none is
self-scored):

| Candidate family | Scorer families |
|---|---|
| claude (haiku / opus / sonnet) | glm + minimax |
| glm | minimax + haiku |
| minimax | glm + haiku |
| deepseek (dsflash / 1017) | glm + haiku |

Three scorer *models* are needed (`ai-gateway-misc/fw-glm-5.3-flash` high,
`github-copilot/claude-haiku-5.5` default, `minimax-m3p1-flash` medium),
session caps per §5.8 ($0.40 mandatory / $0.30 phase-2 / $0.28 arbiter). This
is the fix for the RG4 1-family hole:
the fw-glm and sonnet arms had a single family and were ineligible
(`2026-11-20/RESULTS.md` §2). Here every arm in the mandatory and phase-2
sets maps to two families by the table; an arm whose second scorer DNFs is
recorded as 1-family and **not eligible** for a seat decision.

**Divergence and the arbiter (review M14, pre-registered for HO2/HOD).** A run
is **divergent** when its two family readings differ by **≥ 2.0 points**. Every
divergent run gets one arbiter reading from the arbiter family (never the
artefact's family, never one of its two scoring families). The **official score
stays the two-family mean**; the arbiter reading is recorded beside it and the
arm is flagged divergent. A divergence that straddles a seat verdict (P1–P7) is
**not** resolved by averaging or by the arbiter: it is reported as divergent
and the owner rules. Arbiter cost: up to 10 readings, carried in the budget
table (§7.2).

Held-out blinding (PROTOCOL §7): each candidate's deliverable is copied into
`blind/<random-id>/` with the pristine fixture; vendor/model/effort strings
and any self-identifying style markers stripped; the ID↔arm map is sealed in
the private repo and unsealed only after every score is locked. Scorers see
IDs only. The blinding is recorded as unsealed-at-time-T in the results.

### 5.8 Scoring session shape (review I4)

**Shape: batch per bench per scorer family** — the 2026-11-20 panel precedent
(`evals-keys/score-logs/2026-11-20/panel/`), **not** one fresh session per
target. One session scores one bench's blinded run dirs for one family; it is
never resumed across benches or families.

| Block | Sessions | Per-session cap | Worst at 2×cap |
|---|---|---|---|
| Mandatory (HO2 × glm/minimax/haiku, HOD × glm/minimax/haiku) | 6 | $0.40 | $4.80 |
| Phase 2 (HOD × glm/minimax) | 2 | $0.30 | $1.20 |
| Arbiter (gemini, one per bench) | 2 | $0.28 | $0.56 |
| **Total** | **10** | | **$6.56** |

**Observed basis:** the 2026-11-20 panel spent **$0.2946 across 11 sessions**
(≈ $0.027/session; $0.02–0.03 per reading), so 56 readings ≈ **$1.40**.
**Rejected shape:** one fresh instance per target — 56 sessions × 2×$0.10 =
**$11.20 worst**, which busts the $15 once the runs are paid, and multiplies
fixed session overhead. R7's "fresh instance" is therefore instantiated as
"fresh instance per session" (recorded deviation; blinding and self-family
rules unchanged).

---

## 6. Scoring keys

- **Public (this file):** the point budget, gates, probe classes, FP rules,
  MDE/tie-band rules. **Probe commands, inputs and expected values are not
  public** (review M1) — they are key content.
- **Private:** `evals-keys/HOLDOUT-KEY-HO2.md` and
  `evals-keys/HOLDOUT-KEY-HOD.md` (drafts accompany this spec). Each carries
  per defect/hazard: location, exact wrongness, probe script, expected
  pristine/fixed output, counts / does-not-count, half-credit triggers,
  example FPs, distinctive tokens, and the reference-fix description.
- Key text is **frozen before any arm runs**; the builder's job is to fill
  the observed numbers from the built fixtures, not to reinterpret the design.

---

## 7. Campaign plan

### 7.1 Arms and runs (n per cell; costs are run-ops.tsv means)

Implied costs are the **measured** per-task means from
`evals/2026-11-16/run-ops.tsv` (I2-RG4 rows for HO2, D rows for HOD); no
invented multipliers.

| Bench | Arm (model · effort) | Seat it defends / challenges | Mean $/run | Runs | Arm cost |
|---|---|---|---|---|---|
| HO2 | haiku-5.5 · default | cheap-code holder | 0.0267 | 4 | $0.107 |
| HO2 | fw-glm-5.3-flash · high | cheap-code challenger (12.5 on RG4, 1 family) | 0.0289 | 4 | $0.116 |
| HO2 | fw-deepseek-v4p1-flash · default | cheap-mech + explore holder | 0.0353 | 2 | $0.071 |
| HO2 | minimax-m3p1-flash · xhigh | strong-code holder | 0.0896 | 4 | $0.359 |
| HO2 | haiku-5.5 · high | strong-code-alternative holder | 0.1461 | 2 | $0.292 |
| HO2 | claude-opus-5.5 · default | deep + alt2 | 0.5088 | 2 | $1.018 |
| **HO2 subtotal** | | | | **18** | **$1.961** |
| HOD | haiku-5.5 · medium | cheap-design holder | 0.0312 | 4 | $0.125 |
| HOD | deepseek-v4p1-flash-1017 · high | strong-design holder | 0.1836 | 2 | $0.367 |
| **HOD subtotal** | | | | **6** | **$0.492** |
| **Mandatory runs** | | | | **24** | **$2.453** |
| HOD (phase 2) | claude-sonnet-5.5 · high | strong-design-alternative holder | 1.1778 | 2 | $2.356 |
| HOD (phase 2) | claude-opus-5.5 · default | alt2 / deep (design leg) | 1.9539 | 2 | $3.908 |
| **Phase-2 subtotal** | | | | **4** | **$6.264** |

**Why 4 runs on four arms (M-h):** n=2 is the protocol cell, but the MDE is
driven by sd, and the cheap arms are the decisive pairs. **haiku-default
(HO2), glm-high (HO2), minimax-xhigh (HO2) and haiku-medium (HOD, the design
anchor)** get n=4 at a marginal cost of ≈ $0.35 over n=2 (0.053 + 0.058 +
0.179 + 0.062), which narrows the band by up to √2 — exactly √2 when both arms
of the pair are n=4, 0.866 when only one is (`sqrt(1/n_H + 1/n_C)`, §7.4). The expensive
arms stay at n=2 (PROTOCOL §2 rule 1 allows single runs for expensive arms;
buying two is already above the floor of that rule).

Gateway ids for the campaign file (from `roster/models.json` +
`2026-11-20/CATCHUP-RESULTS.md`): `github-copilot/claude-haiku-5.5`,
`ai-gateway-misc/fw-glm-5.3-flash`, `ai-gateway-misc/fw-deepseek-v4.1-flash`,
`fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash`,
`github-copilot/claude-opus-5.5`,
`fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017`,
`github-copilot/claude-sonnet-5.5`.

**Anchor runs (the MDE meter):** the haiku-default (HO2) and haiku-medium
(HOD) 2 extra runs above are the n=4 anchor for the in-campaign noise
estimate; same convention as Étape 5 (`noise-mde.py`). No extra arm is spawned
for this.

**Timeouts (pre-registered, M13):** sonnet-HOD and opus-HOD ≥ 1800 s; every
other arm ≥ 900 s. Mean run times in `run-ops.tsv` are 5–11 min; the 15-min
default is kept where the earlier grid did not time out.

**Not run, with the reason (one line each):**

- carbon / argon on HO2 — 7 DNFs and $1-2/run; "economically unmeasurable"
  (`2026-11-20/RESULTS.md` §1), wall-clock censoring would replace the
  measurement.
- qwen-medium on HO2 — top RG4 arm (13.5) but no I2 seat (its seat is IR alt2).
- sonnet-high on HO2 — "left the code ladder" (roster note); no code seat.
- gem38 / kimi / hydrogen / terra / minimax-low / 1017-low/medium on HO2 —
  no seat, and the mandatory set already covers every pair the bench decides.
- Everything else on HOD — no D seat.

### 7.2 Cost estimate (expected vs worst; real prices)

Every arm-mean is the **measured** mean of its scored runs in
`evals/2026-11-16/run-ops.tsv` (I2-RG4 rows for HO2, D rows for HOD; the
`status=scored` rows only). Footnotes give n. Labels matter (I3): "expected"
is what the campaign should cost, "worst" is every line at its kill threshold.

**Expected**

| Line | Expected |
|---|---|
| Mandatory candidate runs (24) | $2.45 |
| Phase-2 runs (4) | $6.26 |
| Panel — batch sessions (§5.8): 56 readings @ $0.025 | $1.40 |
| Arbiter readings: 10 @ $0.04 | $0.40 |
| Implementability questionnaire: **10 HOD runs** × $0.05 (M-f) | $0.50 |
| Isolation preflight | $0.01 |
| **Expected total** | **$11.03** |

**Worst before the guard**

| Line | Worst |
|---|---|
| Mandatory runs (Σ 2×caps) | $8.54 |
| Mandatory panel sessions (6 × 2×$0.40) | $4.80 |
| Implementability (10 × $0.05, no kill on subagents) | $0.50 |
| Preflight (cap) | $0.05 |
| **Mandatory-only pre-guard worst** | **$13.89** |
| Phase-2 runs (Σ 2×caps) | $9.20 |
| Phase-2 sessions (2 × 2×$0.30) | $1.20 |
| Arbiter sessions (2 × $0.28) | $0.56 |
| **All-lines pre-guard worst** | **$24.85** |
| DNF contingency: 2×$2.50 + 2×$2.80 (re-running both expensive arms at their kill threshold) | $10.60 — **additional** to the rows above, **not** included in the $24.85 |
| **Hard cap** | **$15.00 — enforced by the kill poller, not by this arithmetic** |

The pre-guard figures exceed $15 **on purpose**: summed caps are not a
budget. The $15 bound is enforced at runtime by the **campaign-level kill
poller** (§5.6) plus admission (`spend + 2×cap ≤ budget`), which refuses any
arm — including a DNF re-run — that would cross it. The pre-guard figure is
the answer to "what if the guard fails"; it is not a plan.

Row footnotes: HO2 haiku-default n=2 ($0.0267), glm-high n=2 ($0.0289),
dsflash n=2 ($0.0353), minimax-xhigh n=2 ($0.0896), haiku-high n=2 ($0.1461),
opus **n=2** ($0.5088); HOD haiku-medium n=2 ($0.0312), 1017-high n=2
($0.1836), sonnet n=1 ($1.1778), opus-D n=1 ($1.9539). The 1017 mean is from
the D bench; its I2 cell was $0.065, so the cap is set on the higher cell
(§10, item 10). (MINOR 7)

Arm caps (the runner kills at **2× the cap**): haiku 0.10, glm 0.10, dsflash
0.12, minimax 0.30, haiku-high 0.45, **opus-HO2 2.50** (M13), haiku-medium
0.10, 1017 0.60, **sonnet-HOD 1.80**, **opus-HOD 2.80**. `budget_usd = 15.00`;
admission is `spend + 2×cap ≤ budget` (reserved = 2×cap while the arm runs).
**Phase 2 launches only if**: phase-1 spend ≤ **$5.50** (expected phase-1
≈ $4.2–4.8 depending on when scoring lands; at $5.50 admission still admits
2×$1.80 + 2×$2.80 = $9.20 → $14.70 ≤ $15), the admission rule admits both
phase-2 arms, **and** the mandatory HOD arms produced ≥2 valid runs each. Pre-registered, not post-hoc. (Phase 2 is
*not* gated on HO2's validity.)

**Duration bound (not a cost):** with parallelism 1 and the M13 timeouts,
mandatory wall-clock ≤ 18 × 900 s = 4.5 h; phase 2 ≤ 4 × 1800 s = **2 h**
(M-g). A campaign that exceeds its time budget is closed like a cost stop.

### 7.3 DNF policy

Per PROTOCOL §2 rule 2 and §5(e): a run without `final-report.md` (and
without a `no-report` marker) is a DNF — re-run once, never scored 0. Re-runs
are admitted only if `spend + 2×cap ≤ budget`; when the budget does not admit
a re-run, the arm keeps n=1 and is marked **not eligible** for a seat decision
(the tie rule requires ≥2 valid runs). DNF spend is real spend and is
reported, never hidden.

### 7.4 The pre-registered criterion (what confirms vs refutes)

<!-- M7: verbatim ratified tie rule; M8: P7 pair; I1: P3/P4/P7 owner slots; I2: P5 lineage basis; I5: P8/P9; I6: divergence inheritance; I7: unequal-n band; M-i: Gate-2 clamp note; M-m: family offsets -->

**Step 0 — the ratified rule this spec applies (verbatim, `PROTOCOL.md`
§5(e), ratified 2026-11-20):**

> "Tie rule (ratified 2026-11-20). Eligibility = two scorer families + ≥2
> valid runs; the cheapest arm inside the MDE band wins the seat."

This spec adds no second rule; it instantiates the band and the eligibility on
the held-out cells and adds the lineage check the protocol already requires
(§2 rule 7).

**Step 1 — bench validity (before any seat reading).**

- Gate 1: HO2 best arm ≤ 11/14; HOD best ≤ 8.8. Fail → ceiling-censored: **no
  seat decision**; the fixture is closed and rebuilt (the RG4 lesson).
- Floor check: anchor arm ≤ 3/14 (HO2) or ≤ 2.5/11 (HOD) → too hard to rank:
  no seat decision, same treatment.
- Gate 2: at least one pre-registered pair gap ≥ max(3, 2 × sd_anchor).
  **Alignment (MINOR 9, corrected M-i):** Gate 2 is a **bench screen** and it
  can invert with the seat band, because of its 3-point clamp: on HOD the band
  may sit at the 1.04 prior while Gate 2 demands 3. That inversion is
  harmless — Gate 2 never produces a seat verdict, and a Gate-2 failure only
  stops the *rung* claim. All pairs below → "no signal".

**Step 2 — band freeze.** For a pair with holder H and challenger C:

```
band = max(prior, C(n_anchor) × sd_anchor × sqrt(1/n_H + 1/n_C))
```

which reduces to `C × sd × sqrt(2/n)` when the two arms have equal n. Priors
fixed by the review (M6):

- **HO2 prior = 4.80** — the measured I2-RG4 MDE at n=2 (`noise-mde.tsv`,
  combined sd 1.155).
- **HOD prior = 1.04** — the measured D MDE at n=2 (`noise-mde.tsv`, combined
  sd 0.25).

`C(n_anchor)` (review-fixed):

| anchor n | df = n−1 | C |
|---|---|---|
| 4 | 3 | 4.16 |
| 3 | 2 | 5.364 |
| 2 | 1 | 6.083 |

**Unequal-n note (I7):** the `sqrt(1/n_H + 1/n_C)` form is material — P5's
holder (haiku-medium) runs at n=4 while its challenger runs at n=2, so
`sqrt(1/4 + 1/2) = 0.866` replaces the equal-n `1.0`: the band is **narrower**,
not wider, and the holder gets no artificial protection. The HOD key cites
this formula verbatim.

Degenerate anchor (sd = 0): **the band stays at the prior and the degeneracy
is recorded** (`PROTOCOL.md` §5(e); M6). The band is recorded before any pair
gap is read.

**Consequence stated up front:** with the HO2 prior of 4.80, the impl bench
can refute only a reversal of ≥ 4.8 points; every fine ordering reads as a
tie and the ratified price rule governs. HOD (prior 1.04) is where a decision
is detectable.

**Family-offset record (M-m).** Recorded scorer offsets from Étape 5: IR —
glm reads 1 pt higher than minimax; DR2 — minimax reads 3 pts higher than glm.
For **D the haiku-family offset is unmeasured** (haiku never scores a claude
artefact). P5's arms run **different scorer mixes** (haiku-medium is claude →
glm+minimax; 1017 is deepseek → glm+haiku), so a family-mix effect on that gap
is possible; it is **recorded, not corrected**, and is one reason P5's seat
reading is owner-confirmed (below).

**Step 3 — per-pair verdict.** For each pre-registered pair (holder H,
challenger C) on the same bench, with 2-family means and n ≥ 2. **Divergence
inheritance (I6):** a pair whose cells are flagged divergent is read under
§5.7 — the official two-family mean stands, the arbiter reading is recorded
beside it, and a **verdict-straddling** divergence goes to the owner (no
statistical verdict).

| Result | Reading |
|---|---|
| Δ = H − C ≥ band | **CONFIRM** — the holder is ahead outside noise; no seat action |
| 0 ≤ Δ < band | **CONFIRM-TIE** — ordering not established; the ratified rule applies (cheapest eligible arm inside the band). **Lineage check first** (`PROTOCOL.md` §2 rule 7, instantiated per pair below): an arm that would take the seat must be lineage-legal for that rung. If C is cheaper but lineage-illegal, the seat stays with H and the cell is recorded as tie-blocked-by-lineage. |
| −band < Δ < 0 | **TIE (challenger ahead inside noise)** — same rule and the same lineage check; if C is cheaper and lineage-legal the seat flips, otherwise H is retained and the cell is contested |
| Δ ≤ −band | **REFUTE** — C beats H outside noise; the seat is reopened and moves to C if C is eligible (two families, ≥2 valid runs, lineage-legal), else it is contested and the bench is extended |

Pre-registered pairs. The "expected if the roster holds" column is recorded so
an unexpected result is visible (MINOR 8). The **Rule 7** column is the
per-pair instantiation of "lineage-legal" (I2) — what the rule forbids *for
that rung*.

| # | Bench | Holder (H) | Challenger (C) | Seat | Expected if the roster holds | Rule 7 — what it forbids here |
|---|---|---|---|---|---|---|
| P1 | HO2 | haiku-default | glm-high | cheap-code | C ≈ +0.75 on RG4 (11.75 vs 12.5) → inside the 4.8 band → tie | Nothing: an impl seat may be any family; the review seat (haiku/claude) stays a different family from a glm impl |
| P2 | HO2 | minimax-xhigh | haiku-high | strong-code | C ≈ +0.5 (13.0 vs 13.5) → tie | haiku-high may not take strong-code while cheap-code is haiku-default (strong tier must differ from the cheap tier it escalates) |
| P3 | HO2 | opus | haiku-high | deep / alt2 | **owner ruling slot — P3 (below)** | same bar on haiku-high; opus's same-family pairing with cheap-code is the standing owner-accepted terminal exception |
| P4 | HO2 | dsflash | haiku-default | cheap-mech / explore | exact tie on RG4 (11.75 vs 11.75) → **see the P4 ruling** (collapse, below) | Nothing (both cheap-tier); the **collapse** is an owner call (below) |
| P5 | HOD | haiku-medium | 1017-high | cheap-design | **REFUTE outside the band; seat does not move** because 1017-high would hold both cheap-design and strong-design — `PROTOCOL.md` §2 rule 7 (ladder-collapse reading) — **owner confirms** | 1017-high may not hold a strong and the cheap design seat at once; the fresh-family valve is what the cheap seat is for |
| P6 | HOD | 1017-high | opus | strong-design (phase 2) | H ≈ +0.23 (9.81 vs 9.58) → tie | opus may not take strong-design while cheap-design is haiku-medium (strong tier same family as the cheap tier) |
| P7 | HO2 | haiku-high | minimax-xhigh | strong-code-alternative | P2 reversed (13.5 vs 13.0) — the 2026-11-20 owner-call cell (`2026-11-20/RESULTS.md` §4) → tie → **see the P7 ruling** (collapse, below) | Nothing on family; the **collapse** (minimax-xhigh would hold strong-code too) is an owner call (below) |
| P8 | HOD | sonnet-high | 1017-high | strong-design-alternative (phase 2) | C ahead 1.41 (8.4 vs 9.81) > 1.04 → **REFUTE outside the band; seat does not move** — sonnet is the fresh-family valve and 1017 already holds strong-design — **owner confirms** | Nothing on family (sonnet is the fresh valve); the seat exists for family diversity, not for the score |
| P9 | HOD | opus | 1017-high | alt2 / deep design leg (phase 2) | C ahead 0.23 (9.58 vs 9.81) → tie → **see the P3 ruling** (terminal rung, either bench) | opus may not hold strong-design; the terminal rung's same-family exception applies |

**Owner-ruling slots — RULED (I1; owner 2026-11-21).** These three pairs end
in a *ladder collapse* (one model holding two seats) and are reserved to the
owner; they are not statistical decisions. All three are now ruled under the
new PROTOCOL §5(e) collapse exemption; no seat moves.

> **P3 — RULED (owner 2026-11-21): option B, terminal rung exempt, opus stays
> (Δ +3.50, band 10.33).** The question was: on a held-out tie between opus
> (holder of the terminal `deep` / `strong-code-alternative2` rung) and its
> challenger, does the ratified 2026-11-20 tie rule apply **as written** —
> "the cheapest arm inside the MDE band wins the seat" — so a tie can move the
> terminal rung to the cheaper arm; or is the terminal rung **exempt**, so a
> tie leaves opus in place by default?
>
> [ ] **A — rule applies as written**: a tie inside the band moves the
>     terminal seat to the cheaper eligible arm.
> [x] **B — terminal rung exempt**: a tie does not move the seat; opus stays
>     until a challenger is ahead **outside** the band.
>
> **P4 — RULED (owner 2026-11-21): option B, dsflash keeps cheap-mech +
> explore (collapse refused: $0.009/task delta does not buy the
> family-diversity loss; Δ −1.50, band 8.95).** (cheap-mech / explore, HO2):
> [ ] a tie moves the seat to haiku-default (absorbing cheap-mech + explore)
> [x] the seats stay split — one model may not hold the bulk-mech and explore
> rungs together
>
> **P7 — RULED (owner 2026-11-21): option B, haiku-high keeps
> strong-code-alternative (an alternative rung must be a different family from
> the rung it backs; Δ −0.88, band 8.95).** (strong-code-alternative, HO2):
> [ ] the tie rule moves the alternative onto minimax-xhigh (absorbing
> strong-code + alternative) [x] the alternative stays a separate rung

All three slots are filled; each pair is now a pre-registered decision read
under PROTOCOL §5(e). No seat moved on the held-out — the benches stay
ceiling-censored regardless (§4).

**Owner confirms** (P5, P8): a REFUTE on those pairs does not move the seat by
construction (the ladder-collapse / family-valve reading of rule 7); the owner
confirms or overrides the reading at close-out, and the confirmation is
recorded with the verdict.

No other comparison is a seat decision. A held-out result never changes a seat
that the held-out does not test (review/DR2/O seats, §8). **A reversal outside
the band refutes that seat's basis; a gap inside the band is a tie and the
ratified price rule governs — never a ranking.**

### 7.5 Abort / stop conditions

- Isolation preflight failure → stop (§5.5).
- Cost guard: the driver refuses the next arm when
  `spend + reserved + 2×cap > budget` (reserved = 2×cap per running arm); the
  campaign is then closed with what it has and the reason. The campaign-level
  kill poller is the backstop (§5.6).
- An HO2 fixture-validity failure (§7.4 step 1) → no HO2 seat reading and no
  HO2 re-runs; HOD proceeds independently if its own arms are valid. A HOD
  failure stops phase 2 only.
- A mid-campaign leak hit → stop, quarantine the run dirs, owner decision.
- Two consecutive DNFs on the same arm → stop that arm (never a third
  attempt inside the budget).

---

## 8. Explicitly OUT of scope

- **O held-out — not built.** O's 4-run noise sample gives MDE 9.68 on an /8
  scale (`noise-mde.tsv`): at n=4 the bench cannot separate haiku-class
  models, so at n=2 it can decide nothing. The protocol already says any O
  seat decision must state its own n and margin; a held-out would spend
  money to produce "no signal". Revisit only when the noise re-measurement
  on another model shows a usable sd.
- **DR2 held-out — not built.** The DR2 *construct* is superseded by DR-v3
  (proposal review vs conformance audit, separate reporting, F4); DR-v3 has
  no answer key yet (`2026-11-19/RESULTS.md` §6 (open item 2)). A held-out DR2 would
  measure a retired construct, and the last campaign found no candidate
  within 2.5 points of the seat. The correct order is: DR-v3 key first, then
  a DR-v3 held-out.
- **IR held-out — not built.** Seat cells 4.33 / 4.0 / 3.83 / 3.62 sit inside
  the recorded 1-pt family offset; the MDE is unmeasured and the 4-run
  sample is degenerate (zero variance). A held-out needs a noise floor that
  does not exist yet, and IR is the cheapest bench to re-bench properly
  later (the HO2 fixture can supply review targets at near-zero fixture
  cost — recorded as the next candidate, not built here).
- **Ceiling challenges (carbon, qwen-xhigh on I2) — not run.** Economically
  unmeasurable at this budget (`2026-11-20/RESULTS.md` §1/§7.1).
- **Seat changes outside the tested pairs — not proposed.** No review,
  DR2 or O seat moves on the strength of an impl/design held-out.

---

## 8.5 Rejected alternatives (one line each, with the reason)

- **Keep the impl held-out in the reportgen domain (a reskin).** Rejected: the
  RG4 defects' shapes are public and a reskin re-measures recognition, not
  reading — the leak vector the held-out exists to kill.
- **Impl domain: a rate-limit/quota ledger.** Rejected: nearest to the
  reportgen shape (a per-key state file re-derived each run) and it moves the
  measurement axis onto a clock.
- **Impl domain: a content-addressed file organizer / dedupe tool.** Rejected:
  reuses synccli's identity surface (scan/decision/copy), and dedupe is the
  HOD substrate's concern — cross-fixture contamination.
- **Design domain: a zero-downtime schema migration.** Rejected (same reason
  as D1's #2): single-shot, weak retention/boundedness entailment.
- **Design domain: a batch queue with backpressure.** Rejected: the
  most-trained LLM artefact; low code-grounding, everyone scores the same.
- **Design domain: a backup/restore tool.** Rejected: D1's exact surface.
- **A third held-out bench (IR, DR2 or O).** Rejected for this budget: IR's
  MDE is unmeasured and its seat gaps sit inside the 1-pt family offset;
  DR2's construct is superseded by a keyless DR-v3; O's MDE (9.68) exceeds
  its own scale. See §8.
- **Carbon and qwen-xhigh on HO2 (the ceiling challengers).** Rejected:
  $1-2/run and 7-recorded DNFs — wall-clock censoring would replace the
  measurement.
- **sonnet/opus on HOD as mandatory.** Rejected as mandatory: their seats are
  family-valve/terminal rungs decided on capability the impl bench already
  probes; kept as the pre-registered phase-2 block.
- **Uniform n=2 for every arm.** Rejected: the MDE is sd-driven and the
  decisive cheap pairs cost cents — n=4 on three cheap arms buys a √2 band
  narrowing for ≈ $0.29.
- **Scoring with two families (glm + minimax) only.** Rejected: the glm arm
  would be self-scored or single-family (RG4's exact hole); three scorer
  families with a pairing table fixes it.
- **Putting the probe scripts in the public spec.** Rejected: the probe is the
  answer; the public spec pins the probe *class*, the key pins the command and
  the pass/fail values (review M1).
- **Running the held-out on the existing global opencode DB.** Rejected: the
  candidate can read every prior run's report; per-arm `XDG_DATA_HOME` is the
  fix.

---

## 9. Failure modes of this design, and the rollback

| Failure mode | Consequence | Mitigation / rollback |
|---|---|---|
| Isolation cannot be enforced on this macOS | campaign cannot start | preflight is fail-closed; owner decides whether to accept an isolation-limited campaign (recorded deviation) — the default is no campaign |
| The harder HO2 overshoots (everyone ~0) | no ranking | floor check (§7.4) pre-registered; fixture rebuilt, not re-thresholded |
| HO2 still saturates | Gate 1 fails | prefixed answer: the bench is extended; the $15 is the price of proving RG4-class fixtures cannot decide these seats |
| The MDE band swallows every gap (as O's did) | all ties | honest output: the band is recorded and the price rule governs; the campaign then re-states that the bench cannot rank at n=2 |
| A probe is flaky | the defect is unmeasurable | ×3 on both trees before freeze; a flaky defect is replaced, not averaged |
| The key under-specifies a probe | the builder guesses | R2 critique + R4 key review before freeze; any post-freeze change voids the pre-registration |
| The DB redirection breaks cost accounting | caps inert | preflight assertion **6** (M-e) + the driver's admission rule; fail-closed |
| A candidate reads the private key | the held-out is void | filesystem isolation + preflight assertion 3 + leak grep after the campaign; a hit voids the campaign |
| An arm uses its **own** credential out-of-band | un-metered spend / potential abuse | residual risk **accepted and recorded** (M10-A1, §13.1): meter anomaly + DB roll-up reconciliation + kill poller on the meter |
| Cost overrun | budget blown | per-arm caps (kill at 2×), admission at `spend + 2×cap`, campaign-level kill poller, no third DNF attempt |
| A divergent run straddles a seat verdict | the verdict is not decidable | flagged divergent, reported, **owner rules** — never an arbiter-averaged verdict (§5.7) |

**Rollback of seat changes:** every seat move proposed under §7.4 is a
*proposal* to the owner with the held-out cell, the band, the n and the
cost; nothing is applied automatically. If the campaign is voided (leak,
hash mismatch, isolation failure), the roster returns to its pre-campaign
state — the live bench cells are untouched and no seat cites a held-out
result.

---

## 10. What I could NOT settle (open assumptions — verify before freeze)

1. **`XDG_DATA_HOME` redirection works end-to-end** with opencode 1.19.5 and
   the providers used here. Evidence: the binary's bundled code reads
   `XDG_DATA_HOME` (strings dump, 2026-11-20) and creates
   `<data>/opencode/*`; not yet exercised with a real model call. Preflight
   assertion 6 is the test.
2. **Credential route — RESOLVED pre-launch (M10-A1, §13.1).** Pass-through +
   metering; **no injection** (the Copilot OAuth refreshes inside opencode's
   own plugin, and `sandbox-exec` cannot do per-process file ACLs). The former
   open item (TLS-termination with a per-campaign CA vs provider-key injection)
   is closed — neither is used. What remains is the verified end-to-end check
   (preflight assertions 5–6) and the accepted residual risk recorded in §13.1.
3. **`sandbox-exec` profile semantics on this macOS build** (deny precedence,
   `network-outbound` host/port syntax, exact-path allow lists). Not tested
   here. If the mechanism is unavailable, the campaign halts (§5.5).
4. **Whether every provider path honours `HTTPS_PROXY`** (Bun-based fetch vs
   per-provider SDK). Preflight assertion 6 covers the actual model used.
5. **The `C(n_anchor = 2) = 6.083` constant** does not follow from the t-table
   `noise-mde.py` uses (that table gives 14.08 at df = 1). It is adopted as
   **review-fixed**; the builder must record the review's derivation before
   the freeze, or the row falls back to the t-table value and the band is
   labelled conservative-high.
6. **The HO2/HOD SD under the new fixtures** — unknowable before the run;
   that is what the anchor runs measure. The bands in §7.4 are formulas, not
   numbers.
7. **Whether the HO2 fixture clears Gate 2 at all.** If the mandatory six
   arms all land within 3 points, the bench is "no signal" for a *rung*
   comparison even if the fixture is not censored. Recorded, not re-thresholded.
8. **The D held-out's discrimination on a fresh brief** — a new brief can
   shift the category distribution; only the campaign measures it.
9. **Whether the owner wants phase 2** (sonnet/opus on HOD). It is costed and
   pre-registered, but its value is lower than the HO2 block (terminal/valve
   rungs), so it is deliberately gated.
10. **1017's price drift** — its run cost moved between grids ($0.065 to
    $0.184 across bench/effort cells); the arm cap absorbs it, but the cost
    table's mean is from the D bench (n=2).
11. **The owner's P3 ruling — RESOLVED (owner 2026-11-21).** The slot is
    filled (§7.4): option B, terminal rung exempt, opus stays. No seat moved.

---

## 11. Ordered task list (an implementer can execute this without re-deciding)

1. **R2 critique** this spec (different family from R1). Apply only
   corrections that do not change the construct; record them.
2. **R3 build `evals/heldout-impl-sp1/`** to §3.1 + §3.3, using
   `evals-keys/HOLDOUT-KEY-HO2.md` (draft) as the defect contract. Run
   `python3 -m unittest test_plan` (green) and `python3 cli.py` on the small
   input; confirm `test_legacy_plan.py` fails with exactly one failure.
3. **R3 build `evals/heldout-design-us1/`** to §3.2 + §3.4, using
   `evals-keys/HOLDOUT-KEY-HOD.md` (draft). Confirm the suite is green and
   that every hazard is invisible to it.
4. **R3 build the reference-fixed trees in the PRIVATE repo** (M12):
   `evals-keys/ho2-ref-a/`, `evals-keys/ho2-ref-b/`, `evals-keys/us1-repaired/`
   — small diffs (≤ 120 lines each) — and run every probe ×3 on pristine and
   fixed (§4). Fill the observed numbers into the key drafts; a defect whose
   probe is not stable ×3 is replaced before freeze.
5. **R3 write `evals-keys/holdout-ban.txt` and run the §5.2 greps** through
   one lint script (`evals-keys/holdout-lint.sh`), including the hash
   exclusions of §5.3. Zero hits, both directions.
6. **R3 build `run-eval-v6.sh`** (new file; copy v4's cap/watchdog/report
   machinery) with: new task codes `HO2`/`HOD`, fixture codes `SP1`/`US1`,
   the per-arm data dir **without** a credential file (§5.6/M10), the per-arm
   minimal `opencode.json` (§5.6/M11), the proxy + metering, per-arm allow-list
   isolation + the seven preflight assertions (§5.5), the per-arm poller
   heartbeat, the per-arm timeouts (M13), no `.git` setup.
7. **R3 patch `run-campaign.py`** minimally: `RUNNERS` includes
   `run-eval-v6.sh`; per-arm DB path derived from the title; `campaign_spend`
   sums the global DB (panel + legacy) and the per-arm DBs; admission becomes
   `spend + 2×cap ≤ budget`; add the campaign-level kill poller (30 s). Keep
   its fail-closed semantics and its `--self-check`.
8. **R4 review the keys** against the built fixtures, probe by probe; R5
   **freeze** the hashes of §5.3 (fixtures, keys, **ref trees**, tokens, ban
   list, config template) into `HOLDOUT-MANIFEST.tsv` (public) and
   `HOLDOUT-KEY-MANIFEST.tsv` (private), and mark the keys `FROZEN <date>`.
   The owner fills the P3 slot **before** this step.
9. **R6 run the isolation preflight** (§5.5 assertions 1–7) and
   `python3 run-campaign.py holdout-<DATE>.json --self-check`.
10. **R6 launch the mandatory block** (§7.1); monitor caps; capture reports;
    close on any §7.5 stop condition.
11. **R7 score** in blinded dirs, **batch per bench per family** (§5.8),
    2 families, self-family excluded; divergent runs get one arbiter reading
    (M14/I4); **R8** rules on verdict-straddling divergences and on FPs
    (advisory only, I6); scores lock; unseal the ID map.
12. **Step 1 validity check** (§7.4) → if valid and the phase-2 condition
    holds, launch phase 2; else close the campaign.
13. **R9 interpret** (not R1): write the results, the bands, the per-pair
    verdicts, the spend, and the `SPENT` markers; move the spent fixture
    directories to the private archive `evals-keys/holdout-spent/<code>/`
    (§5.4, MINOR 4). **No commit or push without the owner's explicit go on
    the shown diff** (PROTOCOL §6 step 10).

---

## 12. Fix log (review traceability)

Markers are also inline as HTML comments at the touched sections; this table is
the mechanical index a verifier can diff against.

| ID | Where | Applied |
|---|---|---|
| M1 | §3.1, §3.2, §4 | mechanisms/expected values/probe inputs purged; classes only |
| M2 | §3.3 | GOAL trimmed to RG4 hint level (option i), stated |
| M3 | §4 + HO2 key §2 | probe (b) AND-conjuncts plan validity |
| M4 | §4.3 + HO2 key §1 | global injection, liveness, unevaluable rule, no ulimit |
| M5 | §4 + HO2 key §3/§5 | unit once, c_fix conjuncts, c_quote targets |
| M6 | §7.4 Step 2 | priors 4.80/1.04, degenerate rule, C table |
| M7 | §7.4 Step 0 | ratified tie rule verbatim + P3 slot |
| M8 | §7.4 P7 | haiku-high vs minimax-xhigh pair |
| M9 | §5.5 | per-arm allow-lists |
| M10 | §5.5/§5.6/§13.1 | per-arm auth copy + allowlist + meter; **injection dropped by M10-A1 (2026-11-21)** |
| M11 | §5.6 | per-arm opencode.json exact |
| M12 | §5.3/§5.5 | ref trees private + assertion 4 |
| M13 | §5.6/§7.2 | 2×cap admission, kill poller, opus cap, timeouts |
| M14 | §4.3/§5.7/§7.2 + HO2 key §5 | divergence, arbiter, unevaluable, own-tests, both/none, FP −3 |
| MINOR 1 | §5.1 | ban list is a file + mechanical grep |
| MINOR 2 | §5.1 | claims narrowed (identifier check, not semantics) |
| MINOR 3 | §5.2 | grep forms with excludes, three roots |
| MINOR 4 | §5.4 | post-campaign private archive + SPENT marker |
| MINOR 5 | §5.3 | hash file-set + out/cache/__pycache__/.pyc/.DS_Store exclusions |
| MINOR 6 | §5.5 | per-arm poller liveness assertion |
| MINOR 7 | §7.2 | cost footnotes (n, source, 1017 drift) |
| MINOR 8 | §7.4 | expected-verdict column |
| MINOR 9 | §7.4 Step 1 | Gate-2/band alignment (corrected by M-i) |
| MINOR 10 | HOD key §3 H4 | corpus-prior exclusion |
| MINOR 11 | §3.3/§5 (HO2 key §5) | features carry 0 points (labelled) |
| MINOR 12 | §3.3 + HO2 key §4 | policy-A summary.json in the end-state + probe set |
| MINOR 13 | HOD key §0/§1 | spec section citations |
| MINOR 14 | HOD key §0 | transport seam pinned |
| MINOR 15 | §3.1 + HO2 key §0 | `data/jobs_test40.csv` in the inventory |
| I1 | §7.4 | P3/P4/P7 empty owner slots |
| I2 | §7.4 | P5 lineage basis + per-pair Rule 7 column |
| I3 | §7.2 | expected vs worst rows; $13.89/$24.85; kill-poller bound |
| I4 | §5.8 | batch session shape + re-derived caps |
| I5 | §7.4 | P8/P9 added (phase-2 seats) |
| I6 | §5.7 + §7.4 | divergence inheritance; R8 advisory |
| I7 | §7.4 + HOD key header | unequal-n band formula |
| M-a | §4.2 | H1 label |
| M-b | §4 | injection techniques at class level |
| M-c | §3.1 | SP1 = 3 modules |
| M-d | §5.1 | size class split per bench |
| M-e | §9 | assertion-6 cross-reference |
| M-f | §7.2 + HOD key §6 | 10 HOD questionnaires; phase-2 penalty YES |
| M-g | §7.2 | phase-2 wall-clock 2 h |
| M-h | §7.1 | n=4 covers four arms incl. HOD anchor |
| M-i | §7.4 Step 1 | clamp-inversion note |
| M-j | HO2 key §1 | plan-targeted injection |
| M-k | HOD key §7 | penalty before division (D1-v3) |
| M-l | §2.1 | gate-language sentence corrected |
| M-m | §7.4 | family offsets + P5 mix |
| M-n | §5.5 | fixture copy outside the sandbox |

---

## 13. Build close-out rulings (author, 2026-11-21, pre-freeze)

The builder's OPEN-FOR-AUTHOR list, ruled by R1 (the author). No scores exist,
so these are pre-freeze amendments; they are recorded here and in the keys.

| Open | Ruling |
|---|---|
| OPEN-2 | **Amended.** HO2 probe (d) pristine expectation is now `exit=0`, `ARTEFACTS-INTACT *or* CHANGED` (**informational — not in the pass contract**), `UNASSIGNED-ABSENT`, ID count 0. Discrimination rests on exit code + the unplaceable-ID count (observed pristine: ID 0; ref-A: exit 1 + ID 1; ref-B: PRESENT + ID 1 + PARTIAL True). The fixed-tree contracts are unchanged. |
| OPEN-3 | **Accepted with annotation** (see §5.1): SP1 188 / US1 158 code lines vs the 350–600 / 180–300 guide; difficulty is subtlety, not LOC; a Gate-1 failure is repaired by sharpening/adding a defect, never by padding. |
| OPEN-5 | **Ratified.** H3's seam is `uploader.upload_with_retry(path, store_root, manifest_path, transport=None, attempts=3)` — `transport` is a **keyword argument** (default `None`) with a duck-typed `put(entry) -> None` that may raise `uploader.TransientError`. |
| OPEN-6 | **Ratified.** H1 discriminates on **address stability + chunk-file count**, not on storage format; both the pristine and the repaired tree store raw bytes. The key's repair description is amended. |
| OPEN-7 | **Ratified.** `PLAN-CANON` = canonical `assign()` placements (rows sorted by `(start, job)`, keys sorted, compact separators), compared as a hash, never raw file bytes. |
| OPEN-8 | **Ratified into the keys.** Probe (a) keeps the `TARGET` field and asserts it is plan-like; probe (d) uses the real id **J031** with an exit-safe `ID-COUNT` (no non-zero-exit leak); probe (c) prints `PLAN-CANON`. |
| OPEN-10 | **Ratified.** The `run-campaign.py` admission change is global (see §5.6): strictly more conservative, no scoring effect, legacy campaigns may stop earlier and must say so. |
| FREEZE | **Both keys frozen v1 on 2026-11-21**; sha256 recorded in `evals-keys/HOLDOUT-KEY-MANIFEST.tsv`. The P3 slot was filled by the owner 2026-11-21 (option B, terminal rung exempt; question text and ruling in §7.4). |
| M10-A1 | **Amendment, 2026-11-21, pre-launch** — credential route: INJECTION → **PASS-THROUGH + METERING**. Supersedes the §5.5 credential paragraph and the §5.6 auth bullet (both amended in place). Full text: §13.1. Keys unchanged. |

### 13.1 Amendment M10-A1 (2026-11-21, pre-launch): credential route

**Status: applied.** Supersedes the "Credential route (review M10)" paragraph
in §5.5 and the auth bullet in §5.6 (both now carry the amended text).
**Route changed: INJECTION → PASS-THROUGH + METERING.**

**Why it changed.** The Copilot OAuth refreshes **inside opencode's own
plugin**; a static credential injection breaks the refresh. `sandbox-exec`
cannot express per-process file ACLs. And the credential-exposure risk being
defended against was **already the operating baseline**: 400+ unisolated runs
to date.

**The amended M10 invariant (verbatim):**

> no NON-allowlisted egress; every egress byte/request metered per arm; the
> arm's auth store is a per-arm copy (readable by the arm by design — residual
> risk ACCEPTED and recorded: abuse is detectable via the meter + absent from
> the DB roll-up); the credential never crosses to another arm's allowlist.

**Clause reading.** *No non-allowlisted egress* — the proxy permits only the
provider hostnames and the sandbox denies direct connects. *Metered per arm* —
requests and tokens are counted per arm and the per-arm cap is enforced on
that meter. *Per-arm auth copy* — the store is copied before launch, mode 600,
inside the arm's allow-list; readable by the arm **by design**, and never
shared across arms. *Abuse detectable via the meter + absent from the DB
roll-up* — out-of-band use of the arm's own credential would not appear as
opencode session spend, so the meter (reconciled against the DB roll-up) is
the detector. *Never crosses to another arm's allowlist* — no other arm's
sandbox includes this arm's store, and the proxy's allow-list is bound to that
arm's credential.

**Residual risk (accepted, recorded).** An arm could in principle use its own
credential out-of-band. Mitigations: the brief never mentions credentials; the
meter surfaces an egress/request anomaly; the DB roll-up reconciles
opencode-side spend; the campaign kill poller enforces the cap on the meter.
The residual exposure was already the pre-campaign baseline and is recorded
here rather than claimed closed.

**Freeze consequence: NONE for the keys.** `HOLDOUT-KEY-HO2.md` and
`HOLDOUT-KEY-HOD.md` are untouched by this amendment and keep their v1 freeze
hashes (`ce92e6a1cea67f6f40db0ce2d0e5975971ea2726ef266e1f3c772b6e7e962515`,
`a331268264b2e7d757f4d149505c525c869687044161b502dfbf2738ab67fa2f`); the key
manifest needs no rewrite; no fixture hash changes. The spec was stamped **v4**
at that amendment; **v5** stamps the owner-slot filling (2026-11-21, no
contract change).

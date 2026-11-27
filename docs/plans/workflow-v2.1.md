# Workflow v2.1 — consolidated plan

Status: PLAN, nothing implemented. Written 2026-11-26 against kit commit `4cd4b4d`
(VERSION `0.8.0`, last tag `v0.8.0`); reworked the same day after a cross-family design
review (verdict *needs work*, §1). Supersedes `WORKFLOW-V2-PROPOSAL.md` (untracked,
2026-11-25), which is the **base**: its gaps G1-G13 are triaged in §6, its evidence is
reused by reference, and it is not restated. `AUTONOMOUS-RUN.md` (untracked) stays the
source text for the autonomous-run contract; §5 says where it lands.

Scope: the workflow product (`workflow/`, `roster/`, `init.sh`, `README.md`). `evals/` is
out of scope except where the workflow consumes or renames into it (the seat grid, the
P3 rename surface §4.2, `evals/preflight.sh`).

Proof convention: every repo fact carries `file:line` or the command that showed it.
`[ASSUMPTION]` marks what was NOT verified; `[DISSENT]` marks disagreement with an owner
decision or a review finding; `[TENSION]` marks a point where an owner ruling binds and the
author would have chosen otherwise (noted once, complied with).

---

## 0. Executive summary

1. **The kit IS still the source of truth; the deploy machinery mis-reports it.** Verified
   2026-11-26: the 17 deployed roster agents in `~/.config/opencode/agent/` have the SAME
   body as their kit sources (17/17 by `_body_hash`'s own strip, `init.sh:656-658`, command
   in §3.1), and the lock baselines match. What is wrong is around the bodies: (i) 17 stale
   `.dev-workflow-kit-new` siblings parked on 2026-11-23 and never cleaned; (ii) the
   bootstrap branch of the agent sync (`init.sh:1212-1222`) parks a sibling on ANY body
   difference without a lock baseline and labels it "assumed customized" — a false
   positive on pre-lock installs; (iii) the vacated `strong-design-review-alternative2` is
   still shipped by the kit (`roster/global-agent/strong-design-review-alternative2.md`)
   and still deployed with `model: github-copilot/grok-4.7` (line 2): `models.json` has no
   key for it, so injection never touches its stale model line. **P0 is cleanup, not a
   harvest; P1 removes the three causes.**
2. **Distribution goes global-first; the global directory is a generated deployment and
   the kit repo is the only living source** (§3.1). The evidence is no longer "a hand-edited
   fork" (that reading was wrong, §1) but "a deploy target whose drift mechanisms produce
   false alarms and never self-clean" — the remedy is the same: generated, overwritable,
   doctor-checked.
3. **The roster becomes generated** (owner ruling R4): `roster/models.json` grows into the
   one roster table; agent frontmatter, descriptions, ladder lines, the reviewer checklist
   inlining and the MODELS.md grid are generated from it (§3.3). A rename = one table edit
   + one release.
4. **One agent name set, one install location by default.** The 5 project agents retire;
   `deep`, `cheap-explore` and a standalone `arbiter` seat join the global roster; the
   grid is renamed to four tiers, **cheap / strong / alt / deep**, plus `arbiter`: 19 rungs
   (§4.1), in P3.
5. **Three escalation jobs behind decidable gates:** `deep` does method authoring J1 (SKIP
   by default until Δ is measured — R2) and terminal escalation J3; the dedicated
   non-claude `arbiter` seat does dispute arbitration J2, admissible per dispute only when
   its family differs from both the producer's and the reviewer's (D-A16, D-A18). A vacant
   terminal review rung stops the ladder for the owner (R3).
6. **The method library is the asset that can make deep pay for itself** — but only once
   the ledger shows it does; P4 measures Δ before building the lifecycle.
7. **Usage recorder + `/dwk stats` (§3.8):** an opencode plugin records every completed
   assistant message (model, tokens, cost) to append-only JSONL; `/dwk stats` renders it.
   It is the measurement instrument for the deep gate (Δ, amortization), not a dashboard
   for its own sake. Lands in P1, so P4 has data; replaces the P5 store-poller.
8. **V2 triage:** 6 adopted, 5 modified, 2 deferred/out-of-workflow (§6).

---

## 1. Decision trail (three rungs + amendments)

- **Rung 1 — V2 proposal (2026-11-25):** settled the gap list G1-G13, the evidence base,
  the push rule (D2: push always `ask`, one per push), and the distillation loop shape
  (gate → bounded deep pass → blind cheap validation → cheap scale-out).
- **Rung 2 — owner decisions (2026-11-26):** V2 as base; deep as upstream advisor +
  arbiter with parsimony and a method library; global-first distribution; project-agent
  disposition left to rung 3.
- **Rung 3 — this plan:** deep trigger rule and amortization, arbiter bounds, library
  lifecycle and storage, project-agent disposition, distribution mechanics, triage, phases.
- **Owner rulings 2026-11-26 (naming):** `-alternative2` → `deep-*`, `-alternative` →
  `alt-*`, bare `deep` alongside; the vacated `strong-design-review-alternative2` is
  deleted in P0, not renamed; renames ride P3 (1.0.0). D-A5 not ruled by it.
- **Owner rulings 2026-11-26 (hygiene):** scripts, doc map, skill de-dup, installer shape
  → §5A; D-A11..D-A15.
- **Owner rulings 2026-11-26 (pre-commit hook):** §5A.5.
- **Owner rulings 2026-11-26 (review disposition):** R1 the kit-repo post-commit deploy
  hook is deleted; `--doctor` is the drift detector. R2 J1 = SKIP by default until Δ is
  measured from the ledger; T-G13-2 precedes the lifecycle build in P4. R3 a J2 ruling over
  same-family-produced work is inadmissible → human; a vacant terminal review rung stops
  the ladder for the owner. R4 the roster is generated from one table; G9 becomes a build
  step; the P3 rename = one edit + one release.
- **Rework after cross-family review (needs-work verdict, minimax, 15 MAJOR / 17 MINOR):**
  the review's central finding (M1) was verified and accepted — the first draft had read
  the stale `-new` siblings as the deployed files, so its "harvest" premise, its "hand-edited
  fork" evidence and the P1 post-commit hook built on it were wrong. All 15 majors are
  accepted (M10 and m17 with a partial correction of the reviewer's evidence, marked in
  place); 17/17 minors fixed (m17 partially disputed). Sections reworked: §0, §2, §3, §4,
  §5A, §6, §7, §8, §9. Disposition table: Appendix A.
- **Owner rulings 2026-11-26 (arbiter seat), fourth amendment:** D-A16 — a dedicated
  non-claude arbiter seat is created (designed in §2.3, §4.1: standalone seat `arbiter`,
  gemini-argon, provisional until the next catchup campaign); J2 leaves `deep`. D-A17 — no
  kit commit hook; checks at release and deploy (§5A.4). D-A18 — the arbiter is
  inadmissible when it shares the producer's OR the reviewer's family: a per-dispute
  runtime check (§2.3). D-A19 — P3 moves a customized project skill copy to `-prev`
  automatically (§3.6, §8 P3 rollback). New questions D-A20, D-A21 (§9).
- **Owner rulings 2026-11-26 (dwk stats), fifth amendment:** the kit grows a usage
  recorder and a `/dwk stats` command (§3.8). Data source verified against the plugin
  types (opencode plugin, not the DB). The recorder lands in P1 (prerequisite of P4's
  measured Δ); the P5 store-poller dies; the root monitors' FUNCTION is absorbed (the
  scripts still go to dotfiles, D-A11). New questions D-A22, D-A23 (§9).
- **Owner rulings 2026-11-26 (final block + D-A22/23) — plan decision-complete:** D-A22
  cost=0 → estimate from tokens × the `models.json` price table, labelled `est.`, Δ uses
  it; D-A23 recorder opt-in (one TTY question, default yes, `--no-usage`); block approval
  of D-A1..D-A10, D-A12..D-A15, D-A20, D-A21 as recommended. V2 carry-overs re-checked:
  D11's adoption closed (its concordance-threshold sub-item stays); D3/D7/D9/D10 remain,
  each with a named resolution point (§10).
- **Owner rulings 2026-11-27 (versioning collapse):** nothing was ever pushed — the first
  DELIVERED version is 0.9.0 (P0+P1+P2 folded in); no 0.8.1, no 0.10.0-for-P2. The local
  tags v0.8.1/v0.9.0 are dropped; the tag lands on the release commit when P2 closes.
- **Owner rulings 2026-11-27 (versioning policy):** the version number is decided at
  DELIVERY, never during development. Between releases VERSION stays at the last
  delivered version (reverted to 0.8.0 here) and CHANGELOG accumulates under
  `[Unreleased]`; at release the bump kind is judged from the whole unreleased batch
  (breaking → major, features → minor, fixes → patch). Deployed locks keep the
  `kit_version` they were synced at (0.9.0) — a fact of the sync, not rewritten.

---

## 2. The deep and arbiter seats

### 2.1 Jobs and their gates

`deep` = the roster's top-reasoning seat (`roster/models.json:20-23`, `"deep"` →
`github-copilot/claude-opus-5.5`, family `claude`); it holds J1 and J3. J2 belongs to the
standalone `arbiter` seat (§2.3, §4.1). Anything else routed to either seat is a routing
error, logged as a `RULE-DEVIATION`.

| Job | Gate (all required) | Output | Hard bound (default) |
|---|---|---|---|
| **J1 Method author** | §2.2 gate line says `CONSULT` (impossible while Δ is unmeasured — R2) | one bounded slice + a `draft` method entry (§2.4) | cap `C` from the brief; default `$4` (D-A1, ruled; derived from the single owner-reported $3.34 pass, V2 G13 item 1) |
| **J2 Arbiter** (seat `arbiter`, not deep) | §2.3 dispute packet exists AND the per-dispute admissibility check passes | `stands` / `rejected` / `human` (+ optional precedent) | own cost line, §2.3: packet ≤ ~8K tokens; `$0.50` per ruling; ≤ 1 per wave, ≤ 2 per task |
| **J3 Terminal escalation** | an `alt-*`/`deep-*` rung (today `-alternative`/`-alternative2`) failed, stalled or doubted (`roster/MODELS.md:254-257`) | root cause or remaining hypotheses + what a human must decide (`workflow/agent/deep.md`) | `$4` per pass unless the brief sets less; one pass, then human |

A vacant terminal rung is NOT a J3 trigger: it stops the ladder for the owner (§4.1, R3).

Rejected: **"deep as upstream advisor for any architectural task."** A one-shot is not
amortized; its reversibility risk is covered by the mandatory design review
(`workflow/skill/dev-workflow/SKILL.md:27`) and the `*-design-review` ladder, 10-100x
cheaper per pass (`roster/MODELS.md:168`). `[DISSENT, mild]` on the owner's "upstream
advisor": honored only where the advice is reused (J1).

### 2.2 J1 gate (decidable at every step)

Evaluated by the orchestrator at the design step, BEFORE any deep spend, and written as one
decision-log entry in `INPROGRESS.md` (entry type `deep-gate`, §2.6):

```
deep-gate: class=<key> | scope=<one line> | instances=[<id>, <id>, …] (n=<count>)
         | library=<hit:<key>|miss|diverged:<key>> | GT=<yes|no>
         | C=$<cap> | Δ=$<value> (measured: <ledger ref>) | verdict=<CONSULT|SKIP> (<reason>)
```

**Step 1 — class and instances, written first.** The orchestrator writes `class`, `scope`
and the explicit `instances` list before looking anything up. A class key is
`<activity>-<object>` in kebab case (e.g. `re-binary-format`, `port-module`); it names
what is repeated, not the task. Instances are enumerated items from the task's step list
or `TODO.md` (never estimated); future-task instances count only if already listed in
`TODO.md`. For a `miss`, this list IS the artifact deep must confirm before its slice: if
deep rejects the class boundary, the pass stops and the gate line is amended (no spend
beyond the confirmation).

**Step 2 — library lookup (index only, §2.5).** Match `class` against `INDEX.md` keys and
scope keywords. Exactly one hit → that entry's state decides (§2.5 table). **Two or more
hits → no CONSULT**: the orchestrator picks the closest entry, records both keys in the gate
line, and the run proceeds as a `draft`-entry use (the ambiguity is a library
consolidation proposal for the retro, not a deep spend). Zero hits → `miss`.

**Step 3 — verdict.**
```
CONSULT  iff  library ∈ {miss, diverged}
         and  GT = yes   (machine ground truth: test, dump, byte, schema — OR a closed
                          checklist a different-family reviewer can tick)
         and  Δ is measured
         and  n ≥ 1 + ceil(C / Δ)
otherwise SKIP, reason = the first failing condition.
```

- **Δ** = per-instance spend of the class's last unguided instances (ledger `spent`,
  re-runs and review rounds included — V2 G11 "re-run tax") minus the per-instance spend of
  guided instances (a sibling class's method entry Amortization line). Same unit as `C`:
  dollars per instance, from the ledger, never a default. No measured Δ → `SKIP (Δ
  unmeasured)`. This replaces the first draft's `Δ = $1.00` default, which was ~50x the
  measured cheap slice price (`roster/MODELS.md:169`, `~$0.02`) and silently redefined
  V2's strong-vs-cheap baseline (V2:413-416) as guided-vs-unguided cheap.
- Order-of-magnitude consequence, stated so nobody is surprised: with a cheap-path Δ of
  $0.01-0.05 and `C = $4`, `n ≥ 81-401`. J1 fires only for classes whose unguided path is
  expensive (strong/alt rungs, re-runs) — which is exactly what T-G13-2 must show exists.
- The `+1` is the blind validation instance (V2 G13 item 4), not scale-out.
- Gaming `n`: the instance list is in the gate line, reviewable, and checked against the
  step list at the retro.

**Post-hoc check:** every method entry carries an Amortization line (§2.4); after `n`
uses with realized saving < `C`, it is marked `amortization: not reached` and that
realized Δ is the class family's measured Δ from then on.

### 2.3 J2 arbiter policy (no cost sink)

A dispute is arbitrable only when ALL hold:
1. The V2 G4 bound is exhausted (round 1 review → fix → round 2 fresh review).
2. A **major** is still open AND the producer contests it with evidence (test,
   `file:line`).
3. **Admissibility (per dispute, decidable, D-A18):**
   `admissible ⇔ family(arbiter) ∉ {family(producer), family(reviewer)}`,
   families read from the `family_hint` of the two rungs named in the packet
   (`roster/models.json`). Inadmissible → `human`, with the packet, no arbiter spend. The
   check runs at every dispute because the seat is FIXED: which disputes it can rule on is
   a property of the (producer, reviewer) pair, not of the seat. With `arbiter` = gemini,
   inadmissible pairs today are exactly those whose reviewer is `alt-design-review`
   (argon); no producer rung is gemini.
4. The orchestrator can build the **dispute packet**: finding line, rebuttal with
   evidence, contract excerpt (acceptance criteria), the diff hunk(s). No transcripts, no
   full diff, ≤ ~8K tokens `[ASSUMPTION: threshold to tune]`.

**Escalation outside J2 — one rule, two triggers, both from existing text:**
- *Agreed major after round 2* (producer does not contest) = rung N failed
  (`roster/MODELS.md:254-255`, "only when rung N failed, stalled or expressed doubt"):
  the FIX goes to the producer's next implementer rung (`cheap-code` → `strong-code` →
  `alt-code` → `deep-code`), and its review restarts at the reviewer the producer tier
  calls for.
- *Reviewer doubt* (the reviewer cannot settle major-vs-minor itself) = escalation along
  the REVIEWER's ladder (`roster/global-agent/strong-review.md:34`, "escalate to
  strong-review-alternative (and its alternative2 if doubt persists)"), lineage binding at
  each rung.
The first draft's "uncontested major escalates the producer one rung, as today" cited
MODELS.md for a rule it does not state and contradicted the reviewer prompts; P3's prompt
rewrite states the two triggers above verbatim in every review rung.

Ruling: `stands` (the agreed-major path above) / `rejected` (finding closed in the ledger
with the ruling) / `human` (names the fact a human must supply). Optional **precedent**
line, appended by the orchestrator to the method entry's Traps or to `CONVENTIONS.md`.

**The arbiter seat — design (D-A16):**
- *Slot: standalone special seat `arbiter`*, outside the function ladders (one row in the
  §4.1 grid, no ladder neighbours, `next: stop`). Rejected: filling the vacant
  `deep-design-review` slot. That slot is a REVIEW job — a fresh-family re-read of an
  artifact, whose lineage rule is "≠ producer's family", reached by reviewer doubt along
  the design-review ladder. Arbitration is a ruling on a packet, reached only after the G4
  bound, whose lineage rule is "∉ {producer, reviewer}" and which serves both code and
  design disputes. Merging them would give one prompt two triggers, two lineage rules and
  two output contracts, and would make the design-review ladder silently non-terminal
  again — the vacant-rung stop (R3) is kept instead.
- *Model: `gemini-4-argon` (high), PROVISIONAL until the next catchup campaign.* Reasons:
  (1) its measured strength is DR2 9.5, multi-run (`evals/gen-charts.py:714`) — design
  critique, the bench closest to judging a contested claim against a contract; qwen's
  RG4 14 is a code-generation score and its other benches show 0-7.5 run variance at
  ~$1/task (`evals/gen-charts.py:714`); (2) gemini reviews nowhere on the code
  ladder and only once on the design ladder, so the per-dispute check excludes the
  fewest pairs — qwen would be excluded on every `deep-review`-level dispute, gemini only
  on `alt-design-review`-level ones (both rare, but code disputes dominate volume);
  (3) a rung "almost never pulled" must be stable, not top-scoring. `[ASSUMPTION: argon's
  per-ruling price on an ~8K packet is not in the repo; the `$0.50` cap is set from its
  DR2-class seat price and is re-measured at the first catchup.]` Confirmation rule
  (D-A20, ruled): at each catchup campaign the seat is confirmed or reseated on DR2 + a
  measured per-packet price; no dedicated arbitration bench. When inadmissible, the
  dispute always goes to the human — no second-choice arbiter (D-A21, ruled).

Cost bounds (the arbiter's own line, separate from deep's): `$0.50` per ruling, ≤ 1 per
wave, ≤ 2 per task, counted from `arbitration` decision-log entries (§2.6); an inadmissible
dispute costs nothing and counts toward the per-task 2 (it still went to a human); a third
dispute stops the task for the owner. The arbiter reads the packet, never re-reviews the
work.

Rejected: a cheap tie-break reviewer before deep — a third review round (G4 forbids it),
and not authoritative for the losing side.

### 2.4 Method library lifecycle

**Where entries live (versioned, never edited in place under `~/.config`):**

| Tier | Source of truth (git) | Deployed to | Content |
|---|---|---|---|
| Kit-generic | `roster/methods/<class>.md` | `${CONFIG}/methods/kit/` by `--global` | language/platform-neutral methods |
| Owner-private | separate private repo (D-A2, ruled) | `${CONFIG}/methods/private/` | owner corpus |
| Project adapter | `<project>/methods/<class>.md` | not deployed; read in place | adapter section only |

**Precedence on the same class key:** project adapter (Adapters section only) > owner-private
> kit-generic. Owner-private replaces a kit-generic entry of the same key entirely; the
separate deploy subdirectories make a same-key clash visible instead of one file
overwriting the other.

`INDEX.md` per tier, one line per entry:
`<class> | <scope keywords> | <status> | validated-on N | concordance X% | uses U | <path> | <retired-reason or ->`.
The routing check reads only the indexes (V2:478-479). **Retired entries stay listed**
with their reason: removing them would make a retired class look like a `miss` and invite
a fresh deep spend on a class already judged not worth it.

Placement vs V2 (`workflow/methods/`, V2:441): `roster/methods/` — methods deploy with the
roster, not per project.

**Entry template** (`roster/methods/METHOD-TEMPLATE.md`): scope and gate (class key,
scope, instance shape); **Core**; **Adapters**; **Traps**; **Tool log**; **Amendment
log**; **Status** `draft|validated|active|diverged|retired | validated-on | concordance |
last validated | owner`; **Amortization** `deep $C | uses U | cheap total $S | Δ
measured $x | reached: yes|no|pending`.

**Transitions:**

| Transition | Trigger | Actor | Check |
|---|---|---|---|
| — → `draft` | J1 CONSULT | deep | template followed; class/instances match the gate line |
| `draft` → `validated` | blind cheap instance passes (concordance threshold: V2 D11 sub-item, V2 proposed ≥ 90 %, set before the first transition — §10) | cheap rung + different-family judge | judge checks no citation of the deep output |
| `validated` → `active` | second passing instance | cheap rung + judge | status updated |
| enrich (stays `active`) | an equivalent-but-different instance needed an adapter/trap/tool note | cheap proposes, amendment `proposed` | applied after the next instance passes with it; `cheap-review` |
| `active` → `diverged` | divergence rule | orchestrator | in the gate line |
| `diverged` → `active` | J1 re-advise (Core) + re-validation | deep, then cheap + judge | new version |
| any → `retired` | superseded, two failed re-validations, or idle 180 days (D-A3, ruled) | owner on proposal | stays in INDEX with reason |

**Divergence rule:** (a) two consecutive instances fail while following the procedure (the
reviewer says it is not an execution slip); (b) the task violates a listed precondition;
(c) an enrichment touches Core. Cheap rungs edit Adapters / Traps / Tool log only.

**Ownership:** owner accepts `active`/`retired`; orchestrator records; deep authors Core;
cheap rungs enrich; a different-family reviewer validates.

### 2.5 Routing table (enters SKILL.md §1, before "Routing", `SKILL.md:25`)

Read the indexes (project, then private, then kit). Then:

| Index result | Action | Deep spend |
|---|---|---|
| `active` | entry is the brief | none |
| `validated` | entry is the brief, caveat "validated-on 1": the run is also its second validation instance (judge required) | none |
| `draft` | entry is the brief, caveat "unvalidated": the run is the blind validation instance (judge required, no citation of the deep output) | none |
| `diverged` | evaluate the gate (§2.2) | only if CONSULT |
| `retired` | ordinary routing; reason quoted in the gate line | none |
| two+ hits | closest entry, used as `draft` (§2.2 step 2) | none |
| miss | evaluate the gate | only if CONSULT |

Cost with an empty library: one small file read.

### 2.6 Decision-log entry types

The G5 decision log (`INPROGRESS.md`, template-owned format) gains two entry types:
`deep-gate` (§2.2, one per gate evaluation) and `arbitration: <task> | wave <w> | #<k of 2>
| ruling | $spent` — the counter home for §2.3's bounds. The template carries the shapes;
SKILL.md says when they are written (§5A.3 de-dup rule).

---

## 3. Distribution rework (global-first)

### 3.1 Principle and evidence (dissent on decision 3's wording — accepted by the owner, D-A5)

Verified facts (2026-11-26):
- Body identity: `for f in roster/global-agent/*.md; do diff <(grep -vE
  '^(model|variant):|^# Model family:' $f) <(grep -vE '…' ~/.config/opencode/agent/$(basename
  $f)); done` → 17/17 identical (the strip is `_body_hash`'s, `init.sh:657`).
- 17 `.dev-workflow-kit-new` siblings exist (`ls ~/.config/opencode/agent/*kit-new`).
- The two sibling-parking branches: `init.sh:1206-1211` (body ≠ lock baseline, "locally
  customized") and `init.sh:1212-1222` (no baseline, body ≠ kit, "assumed customized").
- The vacated agent is still in the kit (`ls roster/global-agent | wc -l` → 17, includes
  `strong-design-review-alternative2.md`) and deployed with `model: github-copilot/grok-4.7`.

The failure mode is therefore: a pre-lock install hit the bootstrap branch, every file got
a sibling with a "customized" verdict that nothing distinguishes from real customization,
the owner reconciled by hand, and nothing ever cleaned the siblings or noticed the
vacated seat. `[ASSUMPTION: that the 11-23 siblings came from the bootstrap branch, not
:1206-1211 — consistent with a 0.8.0-era first `--update --global`, not proven by a log]`.

The owner's "the global roster becomes the living artifact" is still not adopted as worded:
a deploy target whose sync machinery can misjudge state must be overwritable at will, so
learning cannot live there. **Adopted:** global-FIRST distribution, kit repo = only living
source, deployed files generated. Learning flows: session → retro proposal
(`SKILL.md:117-123`) → kit commit → `--update --global`.

### 3.2 What gets installed where

| Artifact | Global (`${OPENCODE_CONFIG_DIR:-~/.config/opencode}`) | Project |
|---|---|---|
| Roster agents (17 today → 19 after P3) | `agent/` (generated) | none by default; `--local-roster` §3.5 |
| `dev-workflow` skill | `skills/dev-workflow/` (generated) `[refines decision 3]` | none by default (P3 precondition §3.6) |
| `scratch-workflow` skill (V2 G6) | `skills/scratch-workflow/` | — |
| Methods | `methods/{kit,private}/` | `methods/` adapters |
| Usage recorder plugin + `/dwk` command (§3.8) | `plugin/dwk-usage.js`, `command/dwk.md`, `dwk/stats.mjs` (generated, locked; opt-in, default yes, `--no-usage`) | none (project-mode fallback: `--local-roster` installs them under `.opencode/`) |
| Usage data (§3.8) | — data, not config: `${XDG_DATA_HOME:-~/.local/share}/dev-workflow-kit/usage/` | — |
| Pre-commit hook | — | `.git/hooks/pre-commit` |
| Templates | — | project root, copy-if-absent |
| Lock | `.dev-workflow-kit-lock.json` | `.opencode/.dev-workflow-kit-lock.json` (hook + templates) |

The skill goes global: it is kit prose, project specifics come from `dev-workflow.json`
(`SKILL.md:10`). First line gates applicability: "no `dev-workflow.json` at the repo root →
this skill does not apply; use `scratch-workflow`" (also stops `SKILL.md:3`'s TODO/INPROGRESS
trigger on unrelated repos). `[ASSUMPTION: opencode 1.19.6 loads `skills/` from the config
dir — owner-reported, V2:188-190; P3 precondition 1]`.

### 3.3 One roster table, generated artifacts (R4)

**Source:** `roster/models.json` becomes the roster table. Per rung: `model`, `variant`,
`family_hint` (existing), plus `tier` (cheap|strong|alt|deep), `function`
(code|design|design-review|review|mech|explore|advisor|arbiter), `description` (the routing
sentence), `next` (ladder successor or `stop`), and `vacant: true` for a seat with no
model. A top-level `renamed: {old: new}` map and `retired: [names]` list (P3) feed
orphan messages, the retired-name scan (§5A.3) and the evals display-name map (§4.2).

**Generator:** `roster/build.sh` (bash + `jq`, the tools `init.sh` already requires,
`init.sh:437`). It writes, between generated markers: each agent's frontmatter
(`description`, permissions rails) and its ladder line ("on major/doubt → `<next>`"); the
inlined shared reviewer checklist (§5A.3); the MODELS.md grid table and per-role
model lines. Prompt bodies outside markers stay hand-written. Generated output is
committed (reviewable diffs).
**R1 deviations (shipped, pending later phases):** the MODELS.md grid is only partly generated — the generated region is a compact per-seat / per-agent table; the rich 4-tier grid stays hand-written until the `models.json` restructure (P3, §3.3 `tier`/`function`/`description`/`next`). `roster/injected-preview.md` is generated instead of per-agent frontmatter. The `prices` section (§3.8) is committed with every rate `null` and `source: "unverified"`: no price was sourced; the recorder prints `$?` until the catchup fills them.

**G9 becomes a build step:** `roster/build.sh --check` regenerates into a temp dir and
fails on any difference; `init.sh --self-check` runs it, and `init.sh --global` refuses to
deploy (fail-closed, message names the command) when it fails — the check sits at the
point where stale output would ship. Today's drift it would have caught: MODELS.md:83 says
`impl` runs glm and :91 says `review` runs haiku, vs `models.json:2-10` (haiku / minimax).

**Injection** (`set_agent_model`, `init.sh:639`) stays for model/variant/family lines at
deploy time; the strip list in `_body_hash` (`init.sh:657`) and the injector read one
shared constant (seat 2, §5A.4) so a future injected key cannot be forgotten in one place.

### 3.4 Drift cannot come back (P1)

1. **Overrides file + migration.** `${CONFIG}/dev-workflow-kit.overrides.json` —
   `{ "<agent>": {"model": …, "variant": …} }`, applied after `models.json`. Hand-set
   `model:`/`variant:` lines are documented supported behavior today (`README.md:290`):
   P1's first `--update --global` **migrates** each hand-set line (one that differs from
   the last kit-injected value recorded in the lock) into the overrides file, reports it,
   then injects normally; README "Updating" is rewritten accordingly. From then on a
   hand-set line in a deployed file is drift (`--doctor`).
   **Reconciliation (R1, shipped code):** values equal to the kit default are never pinned (the code refines this rule).
2. **Body customization in global mode** is unsupported: `--update --global` overwrites
   and keeps the previous file once as `<file>.dev-workflow-kit-prev` with a warning.
   Project-mode rules (`## Project rules` split) unchanged.
3. **Bootstrap verdict fixed** (`init.sh:1212-1222`): with no baseline and body ≠ kit, the
   message becomes "diverged, origin unknown — no lock baseline" plus a `diff --stat`
   against the kit body, never "customized". In global mode (generated deploy) the file is
   overwritten with a `-prev` copy (rule 2); in project mode it is parked as today.
4. **Stale sibling cleanup:** a `.dev-workflow-kit-new` sibling whose target body now
   equals the kit body is deleted by `--update` (it records nothing).
5. **Orphan removal:** an agent in the global lock with no kit source, or listed in
   `retired`/`renamed`, is moved to `-prev` and dropped from the lock. `[ASSUMPTION: no
   removal path exists today — consistent with the deployed grok file; P1 task 1 confirms
   by reading the update loop]`.
6. **`init.sh --doctor` (read-only):** lock `kit_version` vs `VERSION`; `models.json` hash
   in lock vs current; deployed `model:` vs models.json+overrides; body hash vs kit; per
   file **baseline present/absent**; orphans; any `-new`/`-prev` sibling; parked hooks
   (§5A.5); `build.sh --check`. Non-zero exit on drift.
7. **No kit-repo deploy hook** (R1). Deploy stays an explicit `--update --global`; `--doctor`
   says when it is due.

### 3.5 Fallback: `--local-roster`

Project install checks for a global roster lock. Absent → offers (TTY) or warns, and
supports `--local-roster`: the same generated files, same names, into
`<project>/.opencode/agent/` (and the skill into `.opencode/skills/`), same lock machinery.
**Name collision is intended and resolved by "project wins"** (`README.md:195`): in that
project the local copies shadow the global roster entirely, so the global roster is
unusable there, and a stale local roster shadows a fresh global one — `--doctor` flags
both scopes present. The disjointness rule of `roster/MODELS.md:31-36` ("a name exists in
at most one scope") is rewritten in P3 as "a name resolves to exactly one file per
project; local wins".

### 3.6 Migration from the copy model (P3)

- **Precondition 1 (verify, then decide):** opencode loads `${CONFIG}/skills/`, and which
  of a project `.opencode/skills/dev-workflow/` and a global `skills/dev-workflow/` wins.
  Decision table, fixed now (D-A19: the customized-copy move is automatic, recoverable):

  | Precedence observed | Untouched project copy | Customized project copy | Global skill install |
  |---|---|---|---|
  | project wins | removed | moved to `-prev` automatically, warned; owner re-expresses its rules in `CONVENTIONS.md`/`RULES.md` | immediately |
  | global wins / undefined | removed | moved to `-prev` automatically, warned | only after every migrated project lost its copy |

  For the "global wins / undefined" row, and the global
  skill is installed only after every migrated project has lost its copy (owner runs the
  9 `--update`s first). No outcome ships two same-named skills. Rollback trigger: the
  P3 smoke test or the first migrated project shows the wrong skill loading → §8 P3
  rollback.
- **Legacy agents** (`impl`, `review`, `explore`, `design-review`, `deep` in
  `.opencode/agent/`): untouched → removed (they would shadow the roster forever under
  "project wins"); customized → kept, warned, listed by `--doctor`.
- **models.json:** the top-level project map (`impl`…`deep`, `models.json:2-23`) is removed;
  `deep` moves into `"global"`; `"global"` keys renamed per §4.1 in the same edit
  (§3.3 `renamed` map). Old deployed names are orphans removed by P1's mechanism (P1 ships
  before P3). Lock regex (`init.sh:260`, `:267`, `:279`) gains `methods` and `skills`.
- The 9 projects with `dev-workflow.json` (V2 G10) are migrated by the owner, one
  `--update` each.

### 3.7 What `init.sh` shrinks to

No rewrite (1833 lines, `--self-check` OK). Project mode: hook + templates + lock; the
project-agent copy path goes (behind §3.6). `--global`: agents + skills + methods, overrides,
orphans, `-prev`. New `--doctor`. `--only=pr-review` refers to a non-existent
`workflow/skill/pr-review/` (`init.sh:154-196`, `ls workflow/skill`) → dropped in P3
(D-A6, ruled). Split into `lib/*.sh` decided by measurement (§5A.4).

### 3.8 Usage recorder and `/dwk stats` (fifth amendment)

**Purpose, one line:** `/dwk stats` is the measurement instrument for the deep gate —
it produces the ledger-attributed per-instance spend that Δ (§2.2) and the method
Amortization line (§2.4) require, and that today nothing collects.

**Data source — verified against the types** (`.opencode/node_modules/@opencode-ai/plugin`
1.19.6 and its `@opencode-ai/sdk` 1.19.6, `sdk/dist/gen/types.gen.d.ts`):
- Plugin hook `event` receives every bus `Event` (`plugin/dist/index.d.ts:175-177`; union
  at `types.gen.d.ts:602`), incl. `message.updated` (`:129-134`, payload `info: Message`),
  `session.created`/`session.updated` (`:493`, `:499`) and `session.idle` (`:413-418`).
- `AssistantMessage` (`types.gen.d.ts:98-127`) carries `sessionID`, `modelID`,
  `providerID`, `mode`, `cost: number`, `tokens {input, output, reasoning, cache {read,
  write}}`, `time {created, completed?}`, `finish?`, `error?`.
- `Session` (`:465-490`) carries `parentID?` (the subagent tree), `title`, `directory`.
- `UserMessage` carries `agent` and `model` (`:51-55`); hook `chat.message` receives
  `agent?`, `model?` and **`variant?`** (effort) per message (`plugin/dist/index.d.ts:187-196`).
- Commands: `.opencode/command/status.md` shows the shipped pattern — a markdown prompt
  whose body asks the agent to run a script and print its output.

**Verdict: plugin records, script displays (hybrid, no DB access).** The plugin API is the
versioned, typed surface; the internal DB stays off every path (the G1 reason stands).
`[ASSUMPTION]`s, each closed by the P1 probe (a ~20-line plugin logging one session's raw
events to a temp file):
- A1 `cost` is populated for every provider; for subscription providers (`github-copilot`)
  it may be 0 → the estimation rule below applies.
- A2 `mode` on an assistant message equals the agent name (else the agent comes from the
  preceding user message's `agent`, joined by `parentID`).
- A3 `message.updated` fires with `time.completed` set exactly once per finished message
  (else dedupe by message `id`, last write wins).
- A4 the event surface at runtime matches the generated `gen/` types (an `sdk/dist/v2/`
  tree also ships; the probe records which shape arrives).
- A5 a command body can run a script without an LLM turn (opencode's `!`-shell injection
  in command templates is documented upstream, not in these types); fallback = the
  `status.md` pattern, routed to the cheapest agent via the command's `agent:` frontmatter.

**Records** (append-only JSONL, one file per month
`usage/YYYY-MM.jsonl`; global, because sessions span projects and the data is personal —
never in a repo, never a doc):
- `{"t":"msg", ts, msg_id, session, parent_session, project_root, agent, provider, model,
  variant, tokens:{in,out,reasoning,cache_r,cache_w}, cost, finish, error}` — written when
  `time.completed` is set (granularity = one completed assistant message, the atomic
  unit; dispatch/wave/task/model rollups are computed on read).
- `{"t":"session", ts, session, parent_session, title, project_root}` — on session
  create/update (builds the dispatch tree).
- Writes are fire-and-forget: a recorder error is logged to `usage/errors.log` and never
  blocks or fails a session (fail-open; it is measurement, not a gate).
- Retention: 13 monthly files kept; `dwk stats --prune` deletes older (never automatic
  deletion beyond that rule).

**Task attribution — via the ledger, never guessed.** The P2 ledger format gains
`task_id=<id>` on every dispatch line (one-line pointer in SKILL.md: "record the returned
`task_id` on the ledger dispatch line"). `task_id` is the child session id; stats joins
child session → ledger line → task / wave / class, and the deep-gate's `instances` ids.
Unattributed sessions are shown as such.

**`/dwk stats` rendering** (`dwk/stats.mjs`, node — already required by opencode plugins):
`/dwk stats [today|week|month|<from>..<to>] [--project] [--by model|agent|task]`:
1. period header: total cost (provider-reported), total tokens, session count;
2. per model: tokens in/out/reasoning/cache, cost, messages, cost per message;
3. per task (ledger-attributed): rungs used, cost, re-runs, review rounds — the Δ input;
4. from P4: per method entry: uses, cheap total, deep cost, `reached` — the
   Amortization column read from INDEX + attributed tasks;
5. `/dwk live`: sessions without `session.idle`, today's spend — the function the root
   monitors served.

**Install:** a `usage` component of `init.sh --global` (lock namespace `plugin`/`command`/
`dwk`; generated, overwritable; `--doctor` checks it). Opt-in at first install (it runs
code in the opencode process; README "Security" says what it records and that nothing
leaves the machine). **Opt-in (D-A23, ruled):** one TTY question at `--global` install,
default **yes**; no TTY → follows the default unless `--no-usage` is passed; `--no-usage`
skips (and on `--update`, removes) the component. The choice is recorded in the global lock.

**Cost estimation (D-A22, ruled).** For each `msg` record: if the provider-reported
`cost > 0`, it is used as is; if `cost == 0`, `cost_est = Σ tokens[k] × price[model][k]`
over k ∈ {in, out, reasoning (billed as out unless the table says otherwise), cache_r,
cache_w}, and the record is displayed `est.`. A model with no price entry shows tokens
and `$?` (never a silent 0). Δ (§2.2) and the Amortization line use reported-or-estimated
dollars, the `est.` flag carried through. **Schema:** `roster/models.json` gains
`"prices": { "<model id>": {"in": $/Mtok, "out": …, "cache_r": …, "cache_w": …,
"source": "<catalog/url>", "checked": "<date>"} }`. The table is refreshed at each catchup
campaign, alongside the PRICE-FRESHNESS check the eval runner already enforces
(`evals/run-campaign.py:291-301`, fail-closed on a missing catalog price); `--doctor`
warns when `checked` is older than the last catchup `[ASSUMPTION: "catchup date" =
newest `evals/<date>/` directory]`.

---

## 4. Project-agent disposition

Verified overlap (`roster/models.json` top-level vs `"global"`):

| Project agent | Model / variant | Roster equivalent | Verdict |
|---|---|---|---|
| `impl` | haiku-5.5 `default` | `cheap-code` — identical | **retire**; port the red/green evidence block (`workflow/agent/impl.md:16-24`) and the RULE-DEVIATION line if absent from `cheap-code.md` (reviewed diff, P3) |
| `review` | minimax `medium` | `cheap-review` minimax `xhigh` | **retire**; escalation wording replaced by §2.3's two triggers |
| `design-review` | minimax `medium` | `cheap-design-review` — identical | **retire**; verdict line (`design-review.md:21`) ported if missing |
| `explore` | dsflash | none read-only | **new seat `cheap-explore`** (dsflash, `edit: deny`) `[ASSUMPTION: a global `explore` would collide with opencode's built-in subagent; not verified]` |
| `deep` | opus-5.5 | seat exists (`evals/gen-charts.py:51`), no roster file | **promote to the roster**, prompt for J1/J3 (J2 → `arbiter`) |

### 4.1 The roster grid after P3 (owner rulings, naming)

**cheap → strong = power; strong → alt = fresh-family bias, same price; alt → deep =
terminal judgment.**

| Function | cheap | strong | alt | deep |
|---|---|---|---|---|
| code | `cheap-code` haiku | `strong-code` minimax | `alt-code` haiku (was `strong-code-alternative`) | `deep-code` opus (was `strong-code-alternative2`) |
| design | `cheap-design` haiku | `strong-design` 1017 | `alt-design` sonnet (was `strong-design-alternative`) | `deep-design` opus (was `strong-design-alternative2`) |
| design-review | `cheap-design-review` minimax | `strong-design-review` minimax | `alt-design-review` argon (was `strong-design-review-alternative`) | **vacant → STOP** (`strong-design-review-alternative2` deleted in P0) |
| code-review | `cheap-review` minimax | `strong-review` sonnet | `alt-review` 1017 (was `strong-review-alternative`) | `deep-review` qwen (was `strong-review-alternative2`) |
| mech | `cheap-mech` dsflash | — | — | — |
| explore | `cheap-explore` dsflash (new) | — | — | — |
| advisor | — | — | — | `deep` opus (J1/J3) |
| arbiter (special seat, no ladder) | `arbiter` gemini-argon, provisional (J2, §2.3) ||||

Count: **19 rungs = 6 cheap + 4 strong + 4 alt + 4 deep + 1 `arbiter`**. `[NOTE: distinct model ids in
models.json = 8 (haiku, minimax, dsflash, deepseek-1017, sonnet, gemini-argon, qwen, opus);
distinct `family_hint` values = 5 (claude, minimax, deepseek, qwen, gemini — `grep -o
'"family_hint": "[a-z]*"' roster/models.json | sort -u`). The owner's "~5 distinct billed
models" is read as the family count (D-A10, ruled): no seat change without the eval track.]`

**Vacant terminal rung = stop the ladder (R3).** A rung with `vacant: true` (or
`next: stop`) has no successor: the orchestrator stops and hands the owner the last
rung's output and what remains open. No fallback to bare `deep` — it is claude, and the
design-review ladder below it reviews claude (`cheap-design`, `alt-design`) and opus
(`deep-design`) output, so a silent fallback would break the cross-family law on day one.

### 4.2 Rename surface (all in the P3 release, generated where possible)

Generated by `roster/build.sh` from the `renamed` map: agent filenames, frontmatter,
ladder lines, MODELS.md grid. Hand-edited, then caught by the retired-name scan:
SKILL.md routing text, README roster list/counts, prompt bodies. Installer: lock keys
(orphan removal). **evals/** (evals-owned, scheduled in the same release so leaderboard and
roster agree):
- Live scripts carrying old rung names (`grep -c alternative`): `evals/reasons.py` (14),
  `evals/gen-charts.py` (10, incl. the hard-coded seat table `:708-724` and SEATS `:51`),
  `evals/build-matrix.py` (1). These are renamed. `[DISSENT, partial on M10]`
  `evals/verify-charts.py` has no rung-name hit (`grep -c "strong-\|cheap-"` → 0); it is
  not on the list.
- Dated campaign files (`evals/<date>/**`, incl. `2026-11-21/ab/*.py`) and their RESULTS
  keep the original names — they are history.
- Display-name map: `gen-charts.py` reads `roster/models.json` `renamed` so historical cells
  render as "`alt-review` (was `strong-review-alternative`)"; the leaderboard is republished
  on every push (`619f45b`), so the map must land with the rename commit.

---

## 5. Autonomous-run contract placement

`AUTONOMOUS-RUN.md` §1-§3 (brief/loop/retro) and §7 (substitution) → the
`scratch-workflow` skill (V2 G6). §4 (standing pre-authorizations) → template
`roster/templates/PREAUTH.md` → `${CONFIG}/`, with V2 D2's push fix. §8 rules R1-R3 → into
the `scratch-workflow` skill (in scope), and `evals/preflight.sh:2`'s comment is updated to
point there. §5-§6 (journal, anti-patterns) → owner-owned, `scratch/`. The file itself,
after the P3 split, becomes the owner journal in `scratch/` (D-A4, ruled).

---

## 5A. Repo & doc hygiene

### 5A.1 Loose root scripts

`status.sh` 29 l., `status-tui.sh` 9, `session-detail.sh` 11 (`wc -l`); French output,
read `$HOME/.local/share/opencode/opencode.db`, hardcoded empty arrays. Only `status.sh` is
referenced, by the untracked, gitignored `.opencode/command/status.md`; the other two are
referenced by nothing. **Disposition: move to the owner's dotfiles (P0)**, as ruled
(D-A11) — they read the undocumented DB schema this plan keeps off the core path (§6 G1).
**Their FUNCTION is absorbed** by the usage component (§3.8): `/dwk live` replaces
`status.sh`'s sessions/spend view and `/dwk stats` the session detail, from plugin
records instead of the DB. When `/dwk` ships (P1), the kit's gitignored
`.opencode/command/status.md` is deleted.

### 5A.2 Doc architecture

**Doc map (stated in README, one screen; checked, see below):**

| Audience | Doc | Tracked |
|---|---|---|
| Kit user (install, update, security) | `README.md` | yes |
| Installer CLI reference | `init.sh --help` text (README links, never restates flags) | yes |
| Roster reader | `roster/MODELS.md` (grid generated, rationale hand-written) | yes |
| Roster prompts | `roster/global-agent/*.md` (generated frontmatter + hand body) | yes |
| Workflow behavior | `workflow/skill/*/SKILL.md` — process lives here | yes |
| File formats | `workflow/templates/*.md` headers — format lives here, never also in SKILL.md | yes |
| Project-agent prompts | `workflow/agent/*.md` — until P3, then deleted | yes |
| Method users | `roster/methods/INDEX.md` + entries (P4) | yes |
| Release history | `CHANGELOG.md` (root, P0) | yes |
| Active plan (at most one) | `docs/plans/<name>.md` | yes |
| Finished plans, proposals | `docs/history/<date>-<name>.md`, frozen | yes |
| Eval readers | `evals/` (own map; `EVALS.md` moves to `evals/RESULTS.md` in P3, D-A14) | yes |
| Owner journal, backlog, media | `scratch/` (gitignored) or private repo | no |
| (not a doc) usage data | `~/.local/share/dev-workflow-kit/usage/*.jsonl` — data, outside every repo | no |

**Root `.md` rule:** the root may hold only `README.md`, `CHANGELOG.md`, and (until
D-A14) `EVALS.md`. `init.sh --self-check` lists root `*.md` and fails on any other name
(symmetric with the retired-name check; cheap). `docs/` becomes tracked (`plans/`,
`history/`); new gitignored `scratch/`.

**Per-file disposition (every root `.md` and loose file today, `ls *.md *.sh`):**

| File | Disposition | Phase |
|---|---|---|
| `README.md` | stays; gains doc map | P2 |
| `WORKFLOW-V2.1-PLAN.md` (this) | → `docs/plans/workflow-v2.1.md`; on P6 close → `docs/history/` | P0 |
| `WORKFLOW-V2-PROPOSAL.md` | archive verbatim → `docs/history/2026-11-25-workflow-v2-proposal.md` (cited by line) | P0 |
| `AUTONOMOUS-RUN.md` | split per §5; remainder → owner journal in `scratch/` (D-A4) | P3 |
| `EVALS.md` | → `evals/RESULTS.md` in the P3 evals rename (D-A14, ruled); references to update: `evals/README.md:57`, `:73` (relative path) and `:35` (by name) `[DISSENT, partial on m17: :35 is a by-name reference a move also breaks]` | P3 / evals |
| `docs/IMPROVEMENT_PLAN.md` | → `docs/history/2026-11-23-improvement-plan.md` after a privacy scan (D-A12, ruled) | P0 |
| `docs/BACKLOG-external-ideas.md` | → `scratch/`, private until triaged (D-A13, ruled) | P0 |
| `docs/*.pdf`, `docs/*.gif` | → `scratch/` | P0 |
| `status.sh`, `status-tui.sh`, `session-detail.sh` | → dotfiles (§5A.1) | P0 |
| `CHANGELOG.md` (new) | Keep-a-Changelog. **Deviation (shipped, R2):** `scripts/release.sh` prints the release steps and runs the gates; it does NOT write CHANGELOG.md or VERSION itself (the maintainer edits them, then tags) | P0 |
| `roster/methods/` (new) | §2.4 | P4 |
| `workflow/templates/*.md` (12) | location unchanged; headers own formats | P2 |

### 5A.3 Skill de-duplication

**Rule: each CONTRACT is stated once, in the artifact that carries it.**
- *File format* → the template header; SKILL.md says when/who and links.
- *Process* (when, who, gates, routing, escalation) → SKILL.md only.
- *Model and seat facts* → `models.json`; everything else is generated from it (§3.3).
- *Review checklist* — NOT a link. Reviewers run as fresh instances
  (`SKILL.md:101`) and a reviewer that fails to resolve a linked path reviews with no
  checklist, silently. The checklist is single-sourced in
  `roster/fragments/review-checklist.md` and **inlined by `roster/build.sh`** into every
  review rung (code and design ladders), so each deployed prompt is self-contained. De-dup
  governs the source, not the deployed prompt.

**Retired-name scan (P3, `--self-check`):** a per-name pattern list generated from
`retired` + `renamed` keys — exact tokens with word boundaries and agent context
(`\bstrong-[a-z-]*-alternative2?\b`, `` `impl` ``, `agent/review.md`, `@review\b`,
`subagent_type: *"?(impl|review|explore|design-review)\b`), NOT bare words (`review`,
`deep` are ordinary words, e.g. `SKILL.md:78`, `strong-review.md:13`). A whitelist file
holds legal mentions (CHANGELOG, `renamed` map, `docs/history/`). Files: shipped skill,
templates, agent prompts, `workflow/hooks/pre-commit.sh`.

**Project-variable vs global-fixed:** all SKILL.md text global-fixed; project variation only
via `dev-workflow.json` (`SKILL.md:10`), `CONVENTIONS.md`/`RULES.md`, `methods/` adapters.

### 5A.4 Installer final shape

**Slimming suffices; split decided by measurement after P3:** split into `lib/*.sh` only if
`init.sh` is still > 1000 lines **or** a P1-P3 change touched > 3 unrelated regions.
`[ASSUMPTION: post-P3 size not estimated]`.

Seams — **refactor two, document one (P1):**
1. *Self-check parses its own source* (`init.sh:261-269`) → explicit manifest consumed by
   install loops and self-check.
2. *Injected-key list in two places* (`_body_hash` strip `init.sh:657`, injector
   `init.sh:639`) → one shared constant. This is hygiene, NOT the cause of the 17/17
   freeze: the strip is correct today (17/17 identical, §3.1); the freeze cause is the
   bootstrap verdict, fixed in §3.4 item 3.
3. *Three hash units* (`init.sh:656-690`) → header table (unit → files → why), incl. the
   hook's no-lock-entry contract.

**Smoke test** (scratch project: install → `--update` → no `-new` sibling; replace hook →
`--update` → park file, installed hook untouched; scratch `OPENCODE_CONFIG_DIR`: `--global`
→ `--update --global` → no sibling, orphan removed, bootstrap message on a lock-less
diverged file) lives in `scripts/smoke.sh`, run by `scripts/release.sh` (§8 P1).

**Kit-repo commit gate: none (owner-ruled, D-A17); the checks live at release and at deploy.** The kit
has no hook today (`ls .git/hooks` → samples only; no root `dev-workflow.json`). Reasons:
(1) the only harmful event is shipping stale or broken output, and both ship points are
guarded — `init.sh --global` refuses to deploy on `build.sh --check` failure (§3.3), and
`scripts/release.sh` runs `--self-check` + smoke + CHANGELOG/VERSION/tag before any
release; (2) dogfooding the project install in the kit root would copy-if-absent the
templates (TODO/INPROGRESS/…) into the kit repo and needs its own config — a cost with no
caught failure in return; (3) R1 removed the other kit-repo automation surface for the
same "unmonitored automation" reason. Owner-ruled (D-A17).

### 5A.5 The pre-commit hook

Facts: `workflow/hooks/pre-commit.sh`, 196 l., last touched 2026-09-29; deterministic half
of the commit gate (`SKILL.md` §6 item 1). Builtins `companion_md_exists`,
`no_history_comments` (`pre-commit.sh:164`, `:172`). Template names the check
`companions_exist` (`workflow/templates/dev-workflow.json:5`). No lock entry; a differing
installed hook gets the kit version parked as `pre-commit.dev-workflow-kit`
(`init.sh:1044`), which git never runs and nothing follows up.

**Residence:** project-level forever (git hooks are per repo); its update path ships with P3.

**Retired names:** verified with word-boundary tokens — `grep -nwE
"impl|review|explore|design-review|deep" workflow/hooks/pre-commit.sh` and `grep -n
"alternative"` → no hit (the unbounded pattern matched "implemented" at `pre-commit.sh:7`,
a false positive). The hook joins the retired-name scan's file list.

**Gate candidates from V2:** none mandatory (G2/G4/G5 are semantic). `[DISSENT on a de-dup
grep in the hook]`: de-dup governs KIT text → kit `--self-check`. Optional, unscheduled: an
opt-in ledger-shape builtin, only if a retro shows malformed ledgers (`SKILL.md:122`).

**Parked hook** `[DISSENT on placement: P1, not P2]`: `--doctor` lists any
`pre-commit.dev-workflow-kit` with its diff summary (drift detection → P1).

---

## 6. V2 G1-G13 triage

| Gap | Verdict | Reason / change vs V2 |
|---|---|---|
| G1 cost ledger | **modify** | Budget line, ledger `cap/spent`, max-children stop, per-child cap, DNF on cap. Store-poller off the core path (undocumented internal schema, V2:82-85); checkpoint stop is core enforcement. The poller is replaced by the plugin recorder (§3.8, P1); ledger `task_id` + recorder = Δ's data source (§2.2) |
| G2 evidence-first | **adopt (narrowed)** | Already in 17/17 roster prompts (`grep -l "Nothing is true without proof" roster/global-agent/*.md` → 17, e.g. `cheap-code.md:16`). Gap = the 5 `workflow/agent/*.md` prompts (`grep -L` → all 5) and `SKILL.md` §3 rule 4. The project prompts die in P3, so only the skill line is new work (P2) |
| G3 commit/push profiles | **adopt** | D2: push `ask`, one per push. Replaces `SKILL.md:88` |
| G4 2-round review bound | **adopt + link** | After round 2: agreed major → producer's next rung; reviewer doubt → reviewer ladder; contested major → J2 if admissible, else human (§2.3) |
| G5 decision log | **adopt** | One `INPROGRESS.md` section; entry types incl. `deep-gate`, `arbitration` (§2.6) |
| G6 scratch-workflow | **adopt** | The no-kit half of global-first |
| G7 routing enforcement | **modify** | 3-line `roster/templates/AGENTS.fragment.md`, merged by hand (kit never writes user config) |
| G8 autonomy bench | **out of workflow scope** | evals track |
| G9 roster consistency | **adopt as a build step** | `roster/build.sh` + `--check` (R4, §3.3); plus `--doctor` |
| G10 layered conventions | **defer (P6)** `[DISSENT]` | 3 of 4 language templates unused (V2:253-259) |
| G11 delivery reliability | **modify (workflow part)** | Seat-change decision template fields in MODELS.md |
| G12 headless walls | **modify** | Born allow-listed + pre-flight in the scratch skill; rest deferred |
| G13 method library | **adopt, gated on measurement** | §2; Δ measured first (R2) |

---

## 7. Learnings fold-in (owner AGENTS.md → kit)

Source: `~/.config/opencode/AGENTS.md` (129 lines). (The first draft also listed "divergent
lines in the 17 deployed bodies" — there are none, §3.1.)

| Learning | Target in kit | Form |
|---|---|---|
| Cross-family reviewer always | `SKILL.md` §6 item 2 (read both `# Model family:` headers, `MODELS.md:322-333`) | sentence + pointer |
| ~100K context cap; fresh reviewer per target | `SKILL.md` §7, MODELS.md "Escalation semantics" | rule |
| Escalation only on demonstrated failure | `SKILL.md` §1 Routing; already in `cheap-code` description (`ESCALATE-CANDIDATE`, `cheap-code.md:4`) → into the generated `description` field for all cheap rungs | counters explicit |
| Resume `task_id` only when context is useful | `SKILL.md` §7 (`:100`) | extend |
| Commit batching; ONE push = ONE authorization | `SKILL.md` §6 (G3), README "Permission rails" | replace `SKILL.md:88` |
| "Nothing is true without proof" | `SKILL.md` §3 rule 4 (prompts already carry it) | one line |
| Never code yourself; cheap-code → cheap-review | `SKILL.md` §1 (`:25-26`); `AGENTS.fragment.md` | keep + fragment |
| Ask before acting beyond the request | `SKILL.md` §1 Scope (`:29`) | one sentence |
| `/compact` about what comes next | already `SKILL.md:98-99` | none |
| Model strategy pointer | `AGENTS.fragment.md` | fragment |

---

## 8. Migration phases (ordered; each = kit commits + a release)

**P0 — Cleanup (no harvest).** Value: the deploy target reflects the kit again.
1. Verify zero divergence: the §3.1 body-hash loop over all 17 → 17 identical; record the
   output in the P0 commit message. Any non-identical file stops P0 for a reviewed port.
2. Delete `roster/global-agent/strong-design-review-alternative2.md`; MODELS.md row, README
   counts (V2 M9).
3. Reconcile MODELS.md per-role lines with `models.json` (MODELS.md:83, :91) by hand (the
   generator arrives in P1).
4. Create root `CHANGELOG.md`.
5. **Manual owner step** (the 17 deletions are what P1 items 4-5 later automate): `rm
   ~/.config/opencode/agent/*.dev-workflow-kit-new` and `rm
   ~/.config/opencode/agent/strong-design-review-alternative2.md`, then remove its key from
   the global lock (or let P1 orphan removal do it) and run `init.sh --global --doctor`
   once it exists. No precondition: bodies are already identical (item 1).
6. Hygiene (§5A.2): un-ignore `docs/`, add `scratch/`; archive V2 and (after D-A12)
   IMPROVEMENT_PLAN; commit this plan as `docs/plans/workflow-v2.1.md`; BACKLOG/PDF/gif →
   `scratch/`; root `.sh` → dotfiles (D-A11). (folded — see versioning collapse).

**P1 — Drift cannot come back; roster generated.** Value: stale injection and false
"customized" verdicts die; one table drives the roster.
1. Read the update loop; confirm the no-removal assumption (§3.4 item 5).
2. `roster/build.sh` + `--check`; extend `models.json` (§3.3); generate frontmatter, ladder
   lines, MODELS.md grid; `--global` fail-closed on `--check`.
3. §3.4 items 1-6: overrides file + migration of hand-set lines (+ README "Updating"),
   `-prev` backup, bootstrap verdict fix, stale-sibling cleanup, orphan removal, `--doctor`.
4. §5A.4 seams (manifest, shared injected-key constant, hash-unit table).
5. `scripts/smoke.sh` + `scripts/release.sh` (self-check, build --check, smoke,
   CHANGELOG/VERSION/tag; never pushes).
6. Hook items (§5A.5): template check `companions_exist` → `companion_md_exists` (new
   installs only); parked-hook reporting in `--doctor`.
7. Usage component (§3.8): probe plugin first (closes A1-A5; if the event surface does
   NOT verify, items 7b-c move to P5 and P4 step 1 falls back to manual ledger `spent`
   figures); 7b recorder plugin + JSONL; 7c `/dwk stats` / `/dwk live` command, opt-in
   install, `--doctor` coverage; delete `.opencode/command/status.md`.
Release `0.9.0`.

**P2 — Skill v2.1 text.** Value: every session gets the learnings.
Fold §7; G2 (skill line), G3, G4 (+ §2.3 triggers), G5 (+ §2.6 entry types), G1
ledger/budget; `INPROGRESS.md` template (budget, ledger with `task_id=` on dispatch lines for §3.8 attribution, decision log). **Cap: ≤ 140
lines** (today 123; ~10 rules enter). Cut list to make room: §2 ".md companions"
(`SKILL.md:46-54`) → one line + link to `dev-workflow.json`/template; §3 "Coding
conventions" (`:55-64`) → link to `CONVENTIONS.md`; every file-format sentence → its
template header (de-dup); §9 "Periodic coherence review" (`:112-123`) condensed to the
retro trigger + kit-proposal block. De-dup pass; shared reviewer checklist fragment
(§5A.3); README doc map + root-`.md` self-check; skill §6 item 1 and the hook header state
the same builtin names once (hook header = contract). **Recorder durability: store
per-message start/completed timestamps in the msg record; `/dwk stats` gains a tok/s view
(tokens ÷ span) per model and per task (owner request 2026-11-27; the join already exists —
the probe events carry the time fields).** At close: decide the bump from the unreleased
batch (working guess 0.9.0 minor) — nothing shipped before it; P0+P1+P2 deliver as one
version.

**P3 — Global-first install + rename.** Value: one install, one name set.
Preconditions: P1 shipped (orphan removal, generator); §3.6 precondition 1 verified and its
decision-table branch chosen. Then: `deep.md` (J1/J3), `arbiter.md` (J2, admissibility check in its prompt and in SKILL.md routing) and `cheap-explore.md`; §4.1 rename
as one `models.json` edit (`renamed` map) + `build.sh`; hand edits caught by the
retired-name scan; evals surface §4.2; review-rung prompts state §2.3's two triggers and
the vacant-rung stop; skill + scratch-workflow global; project mode slimmed; legacy
migration (§3.6); `--local-roster`; MODELS.md:31-36 rewritten (§3.5); `AUTONOMOUS-RUN.md`
split (§5); README rewritten (rails preserved: every generated agent keeps `"*git push*":
deny`, `"*git commit*": ask`; self-check asserts it). Release `1.0.0`.
**Rollback:** `git revert` the P3 commits, then `init.sh --update --global` — the reverted
kit no longer ships the new names, so P1 orphan removal deletes them and the old names are
regenerated; projects: `--update` per project restores from the kit; a customized skill
copy that P3 moved aside is recovered by hand: `mv .opencode/skills/dev-workflow/SKILL.md.dev-workflow-kit-prev
.opencode/skills/dev-workflow/SKILL.md` (D-A19 — the move is automatic, the recovery is one
file per project).

**P4 — Measure, then build the library.** Value: deep spend becomes an asset only if the
ledger says so.
1. T-G13-2 first: strong/unguided baseline on one class, measured by `/dwk stats --by task` over ledger-attributed sessions → first measured Δ.
2. Decision point: if no class reaches `n ≥ 1 + ceil(C/Δ)` with listed instances, P4 stops
   here (J1 stays SKIP; report to owner).
3. Otherwise: `METHOD-TEMPLATE.md`, `INDEX.md`, routing table in SKILL.md (§2.5), first
   entry (generic RE method), T-G13-1 (blind second slice), T-G13-3 (routing hit, zero deep
   spend).
Step 1 runs as soon as P1's recorder ships, before P3, with today's project `deep` (D-A8, ruled).

**P5 — Autonomous profile tooling.** Pre-flight (G12.4), born-allow-listed profile,
progress-aware watchdog (V2 §4, D7) — the watchdog may read recorder records. (The
store-poller item is gone: replaced by §3.8 in P1.)

**P6 — Optional.** G10; `init.sh` split only if §5A.4's rule fires; on close, plan →
`docs/history/`.

**Rollback, other phases:** each release is tagged; README update recipe (commit state +
lock, `--update`, commit; `git revert` the pair) applies. Global dir: revert + `--update
--global`; a body overwritten in global mode is recoverable by hand from its single
`-prev` copy (no `--restore-prev` command: one revert path is enough).

**Failure modes:**
- Bootstrap mis-verdict recurs → `--doctor` shows "baseline absent"; smoke test covers it.
- Generated files edited by hand → `build.sh --check` fails, `--global` refuses to deploy.
- Global skill triggers in non-kit repos → applicability first line.
- Two same-named skills → §3.6 precondition; rollback trigger defined.
- Legacy project agent shadowing → `--doctor`; `--update` removes untouched.
- Deep gate gamed via `n` → instance list in the gate line, retro check.
- Δ never measurable → J1 never fires (accepted: cost zero).
- Arbiter inadmissible on a dispute (family ∈ {producer, reviewer}) → human, zero spend; volume visible in `arbitration` entries.
- Provisional arbiter model underperforms → reseat at the catchup campaign on DR2 + price (D-A20); one `models.json` edit.
- Vacant terminal rung → ladder stops; owner sees it (intended).
- Arbiter overuse → `arbitration` entries count; third dispute stops the task.
- Recorder breaks on an opencode upgrade → fail-open (sessions unaffected), `errors.log`,
  `--doctor` reports the last record date; the probe re-runs.
- Cost reported as 0 (subscription provider) → `est.` from the price table (D-A22); stale table → `--doctor` warns.

---

## 9. Owner decisions (all ruled 2026-11-26)

| # | Decision | Open |
|---|---|---|
| D-A1 | **RULED:** default deep cap `C = $4` for J1/J3 | — |
| D-A2 | **RULED:** owner-private methods in a separate private repo → `${CONFIG}/methods/private/` | — |
| D-A3 | **RULED:** 180-day idle retirement window, owner confirms | — |
| D-A4 | **RULED:** after the P3 split, `AUTONOMOUS-RUN.md` becomes the owner journal in `scratch/` | — |
| D-A5 | **RULED:** dissent accepted — kit = living source, global = generated, body overrides unsupported in global mode | — |
| D-A6 | **RULED:** `--only=pr-review` dropped in P3 | — |
| D-A7 | **RULED:** G10 deferred to P6 | — |
| D-A8 | **RULED:** Δ measured in P4 step 1, as soon as the P1 recorder ships (before P3) | — |
| D-A9 | **RULED:** P3 ships as `1.0.0` | — |
| D-A10 | **RULED:** "~5" = 5 families; no seat change without evals | — |
| D-A11 | ~~Root `.sh` monitors?~~ **RULED: dotfiles**; their function is absorbed by `/dwk stats`/`/dwk live` (§3.8, fifth amendment) | — |
| D-A12 | **RULED:** privacy scan, then archive `IMPROVEMENT_PLAN.md` to `docs/history/` | — |
| D-A13 | **RULED:** external-ideas backlog private (`scratch/`) until triaged | — |
| D-A14 | **RULED:** `EVALS.md` → `evals/RESULTS.md` with the P3 evals rename | — |
| D-A15 | **RULED:** one active plan, no ROADMAP.md | — |
| D-A16 | ~~Add a non-claude arbiter seat?~~ **RULED: yes** — standalone `arbiter` seat, gemini-argon, provisional (§2.3, §4.1) | — |
| D-A17 | ~~Kit commit hook?~~ **RULED: no** — checks at release (`scripts/release.sh`) and deploy (`--global` fail-closed) (§5A.4) | — |
| D-A18 | ~~Reviewer-family inadmissibility too?~~ **RULED: yes** — `admissible ⇔ family(arbiter) ∉ {family(producer), family(reviewer)}`, per dispute (§2.3) | — |
| D-A19 | ~~Move a customized project skill copy to `-prev`?~~ **RULED: yes, automatically** (§3.6, §8 P3 rollback) | — |
| D-A20 | **RULED:** arbiter confirmed/reseated at each catchup on DR2 + measured per-packet price | — |
| D-A21 | **RULED:** inadmissible arbiter → always human; single seat | — |
| D-A22 | **RULED:** cost=0 → estimate from tokens × `models.json` `prices`, labelled `est.`; Δ uses it (§3.8) | — |
| D-A23 | **RULED:** recorder opt-in, one TTY question, default yes, `--no-usage` flag (§3.8) | — |
| V2 carry-over | D11 adoption **closed** (distillation loop adopted as §2 J1, gated by R2/D-A8); its concordance threshold stays open. D3, D7, D9, D10 remain — not D-A questions, see §10 | — |

**Not settled because unverifiable from here:** opencode `skills/` loading and project-vs-
global skill precedence (P3 precondition 1 settles it before anything ships); a global
`explore` colliding with opencode's built-in subagent; whether `init.sh` has a removal path
(P1 task 1); which branch produced the 11-23 siblings; the owner-reported $3.34 / ~$0.10 /
17-of-18 G13 figures (not verifiable from the repo); whether any class has an expensive enough unguided
path for J1 to ever fire (P4 step 1); the plugin runtime facts A1-A5 (§3.8, closed by the P1 probe).

---

## 10. Decision status

The plan is **decision-complete as of 2026-11-26**: every D-A row in §9 is ruled. What
remains open is verification, not decision:

| Open item | Kind | Resolves where |
|---|---|---|
| A1-A5 plugin runtime facts | **CLOSED (P1 probe, 2026-11-27, `docs/history/2026-11-27-usage-probe/VERDICT.md`):** A1 holds (copilot and ai-gateway report real cost); A2 holds; A3 does NOT hold in strict form (message.updated fires 3x per message) → dedupe by id, implemented; A4 fields match gen/ (v2 not compared); A5 does NOT hold (a command runs a model turn) → status.md pattern fallback | P1 item 7: GO |
| Arbiter per-ruling price (the `$0.50` cap) and gemini-argon fit | `[ASSUMPTION]`, provisional seat | first catchup campaign (D-A20 rule) |
| Price-table freshness rule ("catchup date" = newest `evals/<date>/`) | `[ASSUMPTION]` | P1 item 7, with `--doctor` |
| opencode `skills/` loading and project-vs-global precedence | unverifiable here | P3 precondition 1 (decision table already fixed) |
| Global `explore` name collision | unverifiable here | P3, before `cheap-explore` ships (prefixed name already avoids it) |
| `init.sh` removal path | unverifiable here | P1 item 1 |
| Whether any class makes J1 fire | measurement | P4 step 1 / step 2 decision point (stop rule fixed) |
| Owner-reported G13 figures ($3.34, ~$0.10, 17/18) | not in the repo | superseded for decisions by P4 step 1's measured Δ |
| V2 D3 — per-child cap default and max-children (V2 proposed $2 / 10) | owner, later | P2 (G1 ledger/budget text); enforcement is the checkpoint stop + `/dwk` data, not the dropped poller |
| V2 D7 — watchdog silence threshold (V2 proposed 15 min) | owner, later | P5 |
| V2 D9 — delivery floor for seat promotion | evals track (out of workflow scope) | next catchup campaign; the workflow only consumes the seat result |
| V2 D10 — headless confinement | owner, later | P5 (G12; T-G12-1 precondition) |
| V2 D11 concordance threshold (V2 proposed ≥ 90 %) | owner, later | P4 step 3, before the first `draft → validated` transition |

## Appendix A. Review disposition (cross-family review, 2026-11-26)

| Finding | Disposition | Where |
|---|---|---|
| M1 harvest premise inverted | accepted (verified 17/17 identical) | §0.1, §3.1, P0 |
| M2 body-hash strip not the cause | accepted; bootstrap branch named | §3.4.3, §5A.4.2 |
| M3 post-commit deploy hook | accepted, deleted (R1) | §3.4.7 |
| M4 vacant deep-* fallback | accepted: stop the ladder (R3) | §4.1 |
| M5 routing for draft/validated/retired | accepted | §2.4, §2.5 |
| M6 gate not decidable at step 1 | accepted | §2.2 |
| M7 Δ default off ~50x | accepted; no Δ default, J1 SKIP (R2), P4 reordered | §2.2, P4 |
| M8 escalation rule mis-cited | accepted; two triggers, citations fixed | §2.3 |
| M9 arbiter lineage | accepted (R3); resolved by the `arbiter` seat + two-family check (D-A16, D-A18) | §2.3 |
| M10 evals rename surface | accepted; partial correction: `verify-charts.py` has no hit, `build-matrix.py` does | §4.2 |
| M11 linked checklist | accepted; inlined by generator | §5A.3 |
| M12 kit has no commit gate | accepted; decided: no hook, gates at release + deploy | §5A.4 |
| M13 skill precedence | accepted; P3 precondition + decision table + rollback | §3.6 |
| M14 roster copied 3x | accepted (R4) | §3.3 |
| M15 local-roster names | accepted | §3.5 |
| m1-m16 | fixed (G2 §6; scan tokens §5A.3/§5A.5; D-A order §9; families §4.1; doc map §5A.2; P2 cut list; overrides migration §3.4; arbitration counter §2.6; J3 cap §2.1; precedence §2.4; script evidence §5A.1; §8 → skill §5; P0 manual step; rollback; root-.md check) | — |
| m17 EVALS.md citation | fixed, partial dissent (`:35` is a by-name reference) | §5A.2 |

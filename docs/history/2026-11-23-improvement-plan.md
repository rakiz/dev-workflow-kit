# Improvement plan — adopted from external skill reviews

> Status: FULLY DISPOSITIONED (2026-11-23) — §2 (previously shipped, 86851d8), §1+§3 (2106ef5), §5 (384a849), §6 (2a75536, with user amendment: kit-workflow retro proposals are self-contained extractable blocks); §7 skipped by owner decision; §4 and §8 MOVED to `BACKLOG-external-ideas.md` (Part C, owner decision 2026-11-23 — nothing here remains open). Implementation commits may have reordered/adapted wording — the shipped files are authoritative, not this plan.

## Provenance

Findings distilled from a cross-lineage design review (2026-10-07) of three
external repositories, evaluated against this kit's design:

- `github.com/mattpocock/skills` (MIT) — skills for real engineers
- `github.com/romiluz13/team-lead-skill` (MIT) — agent team leadership
- `github.com/herdrdev/herdr` (Apache-2.0) — agent terminal runtime (skimmed; SKIP, see §8)

Clones used for the review live in `/tmp/opencode/ext-skills/` (re-clone if
gone; reference upstream files, not the clones, when quoting mechanics).

## Standing rules for the implementer

- Kit philosophy is non-negotiable: files owned by the project, copy-never-
  symlink, idempotent `init.sh` that never overwrites user files, cheap-first
  model economics, mandatory review before commit, commits only with user
  approval.
- All files in English. Follow CONVENTIONS.md if present.
- TDD where the repo's own tests apply; run the existing test suite before
  proposing any commit.
- Rollback happens in the TARGET project, not here: this repo holds only kit
  sources, while installed copies live in target projects (and, for
  `--global` installs, in possibly unversioned destinations like
  `~/.config/opencode/agent/` — `init.sh:201-208`). Procedure: in the target
  project, `git revert` the atomic commit containing the prompt files AND the
  lock baseline together (they are committed atomically there). For global
  installs, `init.sh` must back up prior files before modification (or the
  documented rollback is re-running the previous kit version's `init.sh`).
  Every `init.sh` change additionally gets an install + `--update` + rollback
  smoke test in a scratch project.
- OpenCode must be restarted after prompt/config changes to pick them up
  (note this in the commit message body when relevant).

---

## 1. Evidence-first resume reconciliation (ADAPT)

**Source idea**: team-lead `references/team-memory.md` ("fact-type
reconciliation on resume").

**Gap in the kit today**: `skill/dev-workflow/SKILL.md` §1 says to resume
"exactly where marked (first unticked `[ ]` step)". Files on disk may have
changed after the last progress note (interrupted session, crashed dispatch),
so the checkbox state can lie.

**Change**: rewrite §1's resume procedure as a reconciliation step:

1. Read the active task in `INPROGRESS.md`.
2. Inspect `git status` / `git diff` and any persisted sub-agent returns
   before trusting the checkboxes. These only show UNCOMMITTED state: also
   read the task's latest recorded commit identity (below) — committed work
   is invisible to `git status`/`git diff`.
3. Classify and state explicitly in the resume note:
   - **intent / authorization** — what the user asked for (never inferred
     from disk state alone)
   - **artifacts produced** — what actually exists on disk
   - **work accepted** — what passed review / checks, bound to the FINAL
     artifact identity (commit hash or worktree hash) plus the recorded
     check results — not to the state at some earlier point
4. Preserve "produced but unaccepted" as an explicit state: do NOT rerun
   implementation merely because its checkbox is unticked; verify the
   artifact instead.
5. Do not interpret every dirty file as this task's work; ask when ambiguous.
6. Acceptance is invalidated by change: any relevant change to the revision
   after acceptance (new commits touching the artifact, a rebase, a stash
   restore) requires REVALIDATION before the acceptance can be trusted
   again. This clause is what §4's scenario "evidence invalidated by a
   changed revision" tests.
7. A note contradicted by git ("uncommitted" that is committed, "working
   now" that is released) is corrected in the same pass — INPROGRESS.md is
   only authoritative AFTER verification against git
   (`git log --oneline -5` + `git status`), and a stale note must never
   redirect the session.

   Field evidence for this clause (masora phase-7 closure, 2026-10-07): an
   INPROGRESS "uncommitted" note persisted after the wave was committed and
   released; an agent trusted the note over git and misdirected the session.
   This incident is the concrete motivating case for the whole reconciliation
   step, and the reason "correct the file in the same pass" is explicit.

**Constraints**: disk state never overrides user authorization. No new
tracker file — this upgrades the existing resume procedure inside SKILL.md.

---

## 2. Red/green evidence for bug fixes in `impl` (ADAPT)

**Source idea**: mattpocock `skills/engineering/tdd/SKILL.md` (red-green
discipline), adapted — not the full TDD policy.

**Gap in the kit today**: project `agent/impl.md` says only "If the project
has tests for the touched area, run them." The global roster's
`global/agent/cheap-code.md` already requires a test that "fails before and
passes after" — the project pipeline is currently weaker than its fallback.

**Change**: in `agent/impl.md` (and mirrored where relevant in
`agent/review.md`'s checklist), require for every bug fix:

1. Identify the existing behavioral boundary the bug violates.
2. Run the baseline at that boundary.
3. Add (or identify) a regression test; **observe it fail for the intended
   reason** before fixing.
4. Implement the minimum change; rerun the targeted check, then the relevant
   suite.
5. Report commands + outcomes; report unrelated baseline failures separately.
6. Allow a documented exception when the bug cannot be reproduced at a
   reasonable boundary (say so explicitly in the report — never silently).

**Constraints**: no mandatory approval step per test seam; do not force
expensive end-to-end tests where a smaller boundary reproduces the defect.

---

## 3. Record-before-dispatch ledger + correction attempt IDs — SHIPS TOGETHER WITH §1 (ADAPT)

**Source idea**: team-lead `SKILL.md` ("record before dispatch") and
`references/communication.md` (corrections carry attempt ids: a correction to
task 7 is task 7.2 — a late `DONE 7` cannot close it).

**Note on scope**: §1 and §3 are one combined rollout lot sharing a single
state contract for `INPROGRESS.md` (§1 defines what acceptance means and
when it must be revalidated; §3 defines who writes the file and when lines
are recorded). They are NOT independent items — do not ship one without the
other; the implementation touches the same clauses of SKILL.md.

**Gap in the kit today**: the skill mandates progressive tracking and factual
reports, but neither defines dispatch ordering nor distinguishes a late
original report from a correction. Worse, sub-agents currently edit
`INPROGRESS.md` directly (`agent/impl.md`, "Update the task's INPROGRESS.md
as you work"; SKILL.md §1 "delegated agents maintain INPROGRESS.md as they
work") — a writer collision with the orchestrator-owned ledger below, and a
violation of the no-shared-artifacts condition for parallel work (SKILL.md
§8) whenever two sub-agents run concurrently.

**Change**: rewrite the ownership of the ENTIRE `INPROGRESS.md` progress
file, then add the ledger inside the active task section (or a small
companion block in it):

- **Orchestrator ownership**: `INPROGRESS.md` becomes orchestrator-owned in
  full. Sub-agents NEVER edit it — they return progress updates (steps done,
  blockers) in their factual return instead, and the orchestrator transcribes
  them. Update `agent/impl.md` (line 17) and SKILL.md's "delegated agents
  maintain INPROGRESS.md" wording accordingly. This also restores the
  no-shared-artifacts guarantee for parallel sub-agents.
- The ledger itself:
  - one line per delegation: logical task/step, **attempt id** (`7`, then
    `7.2`), role (which agent), allowed files/resources, starting artifact
    identity, `task_id` (when the tool returns one), status, return location.
  - **Write the ledger line BEFORE invoking the sub-agent**; record the
    returned instance id AFTER.
  - Corrections keep the logical task id and increment the attempt; the
    correction attempt id is echoed in the worker's return.
  - **Late-writer guard**: before dispatching a correction attempt, the
    orchestrator must confirm the prior attempt is TERMINATED (resumed
    instance asked to stop, or the fresh instance is isolated from the
    files the old one could still touch). Unknown liveness blocks
    overlapping writes — do not run 7.2 while attempt 7 may still be
    mutating the filesystem; the attempt id rejecting a stale `DONE 7`
    report does not, by itself, stop attempt 7 from continuing to write.
  - For consequential or long-running work, persist the factual return before
    treating the tool's completion notification as acceptance.

**Constraints**: ordinary synchronous tasks need one line, not a report-file
bureaucracy. The orchestrator (primary agent) owns the ledger and the whole
file; sub-agents never edit either. No panes/doorbells/ring machinery from
team-lead — the authoritative-file vs notification-hint pattern only.

---

## 4. Workflow-protocol regression suite (ADAPT)

**Source idea**: team-lead `evals/sim/` — scripted scenario suite for a
SKILL (verified working: 11 tests, 16 good/bad pairs, deterministic per
seed).

**Gap in the kit today**: `evals/` benchmarks models (plans, repair, review,
critique). Nothing tests the **execution of the Markdown workflow itself**.

**Change**: add `evals/workflow-sim/`:

- JSON fixtures + invariants; independent good/bad action scripts; permissive
  sandbox filesystem; ordered event history; separate grader script
  (Python is acceptable as an *eval* dependency — NOT an install
  prerequisite of the kit).
- First scenarios (one good + one broken script each) — kept deliberately
  small, 2-3, not the original 8:
  1. dispatch-before-record (per §3's ledger contract)
  2. stale correction return (late `DONE 7` vs open `7.2`, per §3's
     attempt-id rule)
  3. unauthorized commit attempt (must be blocked)
  The dropped scenarios (empty-report recovery, closure interruption,
  shared-state collision, evidence invalidated by a changed revision,
  resume-after-write) can be re-added later; when they are, their
  descriptions must reference the FINAL SKILL.md clause text (e.g. §1's
  revalidation-on-changed-revision clause as actually written), not "§1 of
  this plan".
- Every good script must pass AND every broken script must fail. Assert seed
  reproducibility and path confinement (no writes outside the sandbox).

**Constraints — be honest in the README**: this suite tests the **protocol
harness**, not model adherence to the SKILL.md prose (the suite does not read
or execute the skill text — verified against team-lead's implementation).
Never market it as a prompt-performance benchmark. Model-adherence runs are
future work (skill-loaded model runs, hidden grading rules), a separate
category from this regression and from the existing model evals. **This item
is DEFERRED to last** and should be re-evaluated once items 1-6 (§2, §1+§3,
§5, §6, §7, §8) have shipped — its value against the shipped contract may
have changed.

---

## 5. Review by visible axes (ADAPT)

**Source idea**: mattpocock `skills/engineering/code-review/SKILL.md`
(two-axis review, parallel sub-agents).

**Gap in the kit today**: `agent/review.md` checks contract, correctness and
conventions, but reports one flat list — absence of findings does not say
which axes were actually reviewed.

**Change** (keep ONE reviewer, do not make every review a parallel fleet):

- Report findings grouped under three visible axes: **contract coverage**
  (does it implement the task?), **correctness/compatibility/security**,
  **conventions/scope**.
- Each axis ends with an explicit "reviewed / not reviewed" statement.
- For large or high-risk diffs (threshold: reviewer's judgment, stated in the
  report), OPTIONALLY dispatch bounded contract and standards reviews in
  parallel against the same immutable snapshot, retain the single
  correctness review, then deduplicate and rank findings by severity.

**Mirroring** — the three-axis report structure lands in ALL reviewers, each
preserving its own role-specific checks on top:

- `agent/review.md` (project reviewer), and
- the roster reviewers `global/agent/cheap-review.md`,
  `global/agent/strong-review.md`, and any
  `strong-review-alternative`/`strong-review-alternative2` files.

**Constraints**: do NOT import mattpocock's mandatory tracker dependency,
blanket extraction/polymorphism advice, or its `...` diff semantics. Parallel
dispatch must stay the exception — it exists to protect cheap-first
economics, not to double every review's cost.

---

## 6. Retro with follow-through contract (ADAPT)

**Source idea**: team-lead `references/development.md`; mattpocock
`skills/engineering/retro/SKILL.md`.

**Gap in the kit today**: SKILL.md §9 asks for coherence/simplification
findings but has no follow-through contract; nothing distinguishes a real
improvement loop from an accumulating instruction debt.

**Change**: extend §9 with an optional retro, triggered after a consequential
failure or a phase boundary:

1. Inspect the previous retro's proposals: was the follow-through check done?
2. Identify the observed failure (evidence, not vibes).
3. Propose **at most two** changes, each with owner, expected benefit, and
   the next-task check that will test it.
4. A legitimate **no-op retro** records why current practice is retained and
   what evidence would reopen it.
5. Mechanical mistakes (formatting, lint) route to lint/test/pre-commit
   config — never into new prose rules.

**Constraints**: PROPOSE only, never run automatically; a retro never
expands the agent's authority or silently rewrites global instructions.

---

## 7. Optional templates inspired by upstream skills (REWRITE, opt-in only)

**Source ideas**: mattpocock `skills/productivity/writing-for-agents/` and
`skills/productivity/handoff/` — read for inspiration only.

**Gap in the kit today**: no maintainer reference for writing agent-facing
docs; §7 has `/compact` advice but no cross-session handoff artifact.

**Kit policy**: no vendoring, no copied upstream files. The kit's approach is
to study upstream skills, take inspiration, and REWRITE original content —
the templates below are written from scratch for this kit, adapted to
OpenCode from the start, not adapted copies of upstream files.

**Change**: author both as **original optional templates** (not installed by
default):

- `templates/optional/writing-for-agents/` — for maintainers authoring
  SKILL.md / AGENTS.md / prompts. Written for OpenCode from the start; where
  upstream covers Claude-specific mechanics (`disable-model-invocation`,
  router behavior), the OpenCode-portable equivalent is written directly, or
  the point is dropped.
- `templates/optional/handoff/` — conversation→handoff compaction. The
  contract is rewritten for this kit and names: outstanding ownership,
  authorization limits, evidence identity, and the first resume action. A
  handoff is an expiring convenience — never the authoritative task record
  (INPROGRESS.md stays authoritative).

No attribution in the template files — not even a courtesy "Inspired by"
line: the content is original (no copied upstream text, no license-notice
obligation), and the templates carry no reference to upstream at all. (The
"Source ideas" note above documents this plan's lineage only; it does not go
into the files.) Installed by manual copy by whoever wants it; the core
workflow must never reference these files.

**Prerequisite note**: §8's file manifest is a prerequisite only for any
FUTURE installer-managed multi-file skills. §7 itself ships as manually-
copied original templates regardless — it does not depend on §8.

---

## 8. Packaging prerequisite + explicit SKIPs

**Packaging gap (prerequisite for future multi-file work)**: `init.sh`
installs/syncs only `skill/dev-workflow/SKILL.md`; adding `references/*.md`
to the kit tree would not install them. Before any progressive-disclosure
refactor of the skill, ship an explicit manifest of kit-managed files and
apply copy/lock/three-way-update per file (first install / untouched update /
customized sibling / missing reference / retired-file policy). This plan
does NOT implement it — recorded as the next structural task.

**SKIP (do not copy, do not imitate)**:

- `implement`, `implement-spec`, `wayfinder` (mattpocock): they assume
  self-authorized commits, branch/merge by sub-agents, tracker setup —
  conflicts with kit authority (user-approved commits, orchestrator-only git
  mutation). Adopt the mechanisms already listed above, rewritten for this
  kit, instead.
- `team-lead` as a whole: persistent-people apparatus adds nothing for
  deliberately fresh reviewers and bounded workers.
- `herdr`: terminal-runtime layer, not file-based workflow. Its transferable
  lessons (completion notification ≠ acceptance; inspect uncertain delivery
  before retrying) are already embedded in items 1 and 3.
- Exhaustive "relentless" grilling as a default gate: batch the independent,
  consequential questions (with recommended answers) and investigate repo
  facts before asking the user — that part IS adopted, as a short rule in
  SKILL.md §1 and in `global/agent/cheap-design.md`
  (roster: `cheap-design.md`), NOT as an interview policy.
- mattpocock's "scar comments" in code: conflicts with the kit's
  current-state comment rule.

---

## 9. Rollout order and definition of done

Implement in this order (every item is independently shippable EXCEPT §1
and §3, which are one combined lot and ship together):

1. §2 (impl red/green) — smallest, fixes a live inconsistency
2. §1 + §3 (combined resume/ledger contract) — one shared state contract
   for `INPROGRESS.md` (orchestrator-owned file, acceptance bound to final
   artifact identity); touches SKILL.md, `agent/impl.md` and the
   INPROGRESS template note together
3. §5 (review axes) — `agent/review.md` AND the roster reviewers
   (`cheap-review.md`, `strong-review.md`,
   `strong-review-alternative*.md`)
4. §6 (retro) — SKILL.md §9
5. §7 (optional templates inspired by upstream) — original templates, written
   from scratch; manual copy by whoever wants them
6. §8 (packaging manifest) — recorded as the next structural task
7. §4 (workflow-sim) — DEFERRED to last; re-evaluate after items 1-6 have
   shipped (new eval dir + README honesty notes)

Definition of done per item — an executable gate plus prose review:

- **Per-item gate (executable)**: an `init.sh` smoke test in a scratch
  project — fresh install + `--update` — passes, and the prose changes are
  mirrored everywhere the kit repeats them (roster counterparts where
  applicable, noted per item). This replaces the vague "the existing eval
  suite still passes".
- **Model evals stay separate**: `evals/run-eval.sh` campaigns are explicit,
  separately authorized paid runs — they are NOT part of the per-item gate.
- **README updates**: the README's Structure and templates sections are
  updated in the same item whenever `templates/optional/` is added, and
  `evals/README.md`'s index whenever `evals/workflow-sim/` is added.
  (`EVALS.md` is a model-results summary and is NOT touched by this plan.)
- **Release step**: a single VERSION bump + git tag at the END of the
  series, only with user approval — not per item. Per-item bumps are
  unnecessary: `--update` detects kit changes by content hash
  (`init.sh:805-826`), not by version.
- A human-reviewed commit per item (or per tight group).

The batched-questions rule (in §8 SKIPs) is the one exception to item
ordering: fold it into whichever of §1+§3/§2 ships first.

---

## 10. Language profiles for init.sh (PROPOSED, not yet designed in depth)

**Source idea**: owner, 2026-10-08 — a fresh install should configure
language-appropriate quality tooling, not only copy the generic kit.

**Idea**: `init.sh --lang=python|cpp|go` (or auto-detection via
`pyproject.toml` / `CMakeLists.txt` / `go.mod`) selects a profile that
configures, on a FRESH install:

- `precommit.checks[]` entries per language:
  - python: `ruff check` + `ruff format --check` + `pytest`
  - cpp: `clang-format` dry-run + build+`ctest`
  - go: `gofmt -l` + `go vet` + `go test ./...`
- `extensions` list for the language's companions (python `["py"]`, cpp
  `["cpp","h","hpp"]`, go `["go"]`) — beware generated files.
- copies the matching `templates/CONVENTIONS.<lang>.md` and adds a one-line
  pointer from `CONVENTIONS.md`.

**Constraints**:

- Never touches an existing `dev-workflow.json` — fresh installs only.
- An executable not found on PATH is written as a **disabled** check with a
  comment (never a hook that fails on missing tooling).
- The tests check stays disabled when no suite is detected.
- Everything stays declarative in `dev-workflow.json`; `init.sh` only fills it.

**Dependencies**: §8 (file manifest) is a prerequisite or must ship together —
this extends what `init.sh` manages. Mandatory design review (fresh instance)
before implementation: `init.sh` ↔ lock ↔ hook is the kit's fragile area.

---

## Review amendments (2026-10-07)

This plan was amended after a two-stage design review (cheap + strong
lineage). One line each:

- Rollback rule corrected: rollback happens in the target project via git
  revert of its atomic commit (prompt files + lock baseline); global
  installs need init.sh backup of prior files; every init.sh change gets an
  install/--update/rollback smoke test in a scratch project.
- Path fix: the batched-questions rule targets `global/agent/cheap-design.md`
  (the `agent/cheap-design.md` path does not exist).
- §1 and §3 merged into one rollout lot with a shared state contract:
  INPROGRESS.md fully orchestrator-owned (sub-agents return progress in
  their factual return), acceptance bound to final artifact identity with
  revalidation after any relevant revision change, and a late-writer guard
  (confirm prior attempt terminated before dispatching a correction;
  unknown liveness blocks overlapping writes). They ship together.
- §5 mirroring enumerated: the three-axis report structure applies to
  agent/review.md plus all roster reviewers (cheap-review, strong-review,
  strong-review-alternative*).
- §4 scoped down: 2-3 scenarios instead of 8, harness-not-prose honesty note
  made explicit, deferred to last and re-evaluated after items 1-6; scenario
  descriptions reference final SKILL.md clause text.
- §7 licensing: vendored skills must preserve the full upstream copyright
  and permission notice (upstream LICENSE file or complete header) in
  addition to frontmatter attribution — SUPERSEDED by the rewrite-not-copy
  decision: §7's templates are original content, and carry NO attribution
  at all (no license notice, no courtesy "Inspired by" mention — the plan's
  "Source ideas" note documents lineage, not the files).
- §7 prerequisite reworded: §8's manifest is a prerequisite only for future
  installer-managed multi-file skills; §7 ships as manual templates
  regardless.
- §9 definition of done: executable per-item gate (init.sh smoke test +
  prose review) replaces "the existing eval suite still passes"; model evals
  stay separately authorized; README/evals index updates required; single
  VERSION bump + git tag at end of series with user approval, not per item.

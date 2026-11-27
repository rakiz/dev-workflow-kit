---
name: dev-workflow
description: "Multi-step work cycle of a software project managed by TODO.md, INPROGRESS.md, CHANGELOG.md, DESIGNS.md. Triggers on: starting a new task or phase tracked in TODO.md/INPROGRESS.md, finishing a task, updating progress state, creating or updating a source file's .md companion, preparing or verifying a commit (pre-commit hook, dev-workflow.json), suggesting a /compact compaction at a task boundary."
---

# Dev workflow (TODO → INPROGRESS → CHANGELOG; DESIGNS archive)

File formats live in the template headers (`workflow/templates/*.md`, copied at install). File names are configurable via `workflow.*` in `dev-workflow.json`.

## 1. TODO/INPROGRESS → CHANGELOG cycle

- **Design decisions**: SPEC absent or not configured → durable design decisions live in DESIGNS entries plus `TODO.md`'s "Context" notes.
- **At task start**
  - **Resume = reconciliation, not trust**: read the active task in `INPROGRESS.md` (plus `TODO.md` and `SPEC.md` if configured), then verify against git before trusting any checkbox.
    - **Verify**: `git status`/`git diff` show only UNCOMMITTED state — also read the latest recorded commit (`git log --oneline -5`). Not every dirty file is this task's work — ask when ambiguous.
    - **State**: the resume note states intent/authorization (what the user asked — never inferred from disk state), artifacts produced (on disk), and work accepted (passed review/checks, bound to the FINAL artifact identity: commit hash, or `git write-tree` hash when uncommitted, plus recorded check results). "Produced but unaccepted" is explicit: an unticked checkbox does not mean rerun — verify the artifact instead.
    - **Invalidate**: acceptance is invalidated by any relevant change after it (new commits touching the artifact, a rebase, a stash restore) → REVALIDATION required.
    - **Correct**: a note contradicted by git is corrected in the same pass. `INPROGRESS.md` is authoritative only AFTER verification against git; a stale note never redirects the session.
  - **Design step (mandatory, every task)**: write the task header immediately (name, objective, matching `TODO.md` reference) with an unticked `[ ]` design step; detail steps as the design converges. The STEP is always there; ARTIFACTS are proportional (a trivial task: scope, steps, acceptance criterion). The first unticked `[ ]` is the current position. A `deep-gate` decision-log entry is written here, BEFORE any deep-tier consult spend (shapes: `INPROGRESS.md` template, "Decision log").
  - **Routing**: design depth follows the task class. **Mechanical** (well-understood, single-file transformation) → the orchestrator writes the minimal plan, no design agent; implementation → `cheap-mech`. **Standard** (ordinary feature/refactor on established patterns) → the orchestrator designs (a design producer is optional); implementation → `cheap-code`. Implementation is always delegated (global roster, when installed): the orchestrator coordinates, never implements. Escalate to a stronger rung only on demonstrated failure (repeated failed attempts, a major review finding, or the current rung expressing doubt), never on predicted difficulty.
  - **Architectural tasks** (new/changed contract, migration, concurrency, security boundary, costly-to-reverse): delegate design to a producer (`cheap-design`/`strong-design` per the ladder — MODELS.md, "Escalation semantics") **and** run an independent read-only design review (fresh instance, `cheap-design-review`/`strong-design-review`) before implementation. No design agent in the session → stop and ask how to satisfy the gate. Never silently self-design an architectural task.
  - **Delegate vs inline**: delegate when only the **result** matters — read-only exploration and broad search → `explore`; fully specified or parallelizable work → the implementation rungs (no implementation agent available → stop and ask). Inline means read/search only: any code or doc edit is delegated, even when it looks quick. Inline is valid only for a targeted peek (a named file, a targeted grep, a single-commit look) or when the output immediately constrains the next step. Ignore *"I'll just search myself"* (raw output pollutes the orchestrator's context) and *"I need the full result"* (subagents return structured results). Before parallel dispatch confirm no ordering dependencies and (§8) disjoint file sets; synthesis must fit the remaining context.
  - **SPEC reconciliation**: re-read the `SPEC.md`/`TODO.md` sections the task touches and re-evaluate the global design at task granularity. A global-vs-local disagreement is flagged before writing code; the local decision wins and the SPEC update follows.
  - **Scope**: the step list bounds the session — anything identified outside it is explicitly deferred (a new `TODO.md` entry or SPEC "Out of scope"), never silently absorbed. A status question gets a status answer; a fix discovered along the way or any adjacent action needs an explicit yes first. Explicit user approval **before implementation** is required when: the objective changes relative to the `TODO.md` task; the scope grows across the "Out of scope" boundary (merely referencing it is not a trigger); the design conflicts with a SPEC requirement or non-goal; the action is destructive or costly to reverse; a user-facing choice is unresolved. Otherwise a clear request authorizes its in-scope plan (delegating design is not a trigger); a question, a partial answer or an ambiguous assent does not — clarify first.
  - **Design briefing — presented, not gated**: before the first implementation step, post a short briefing: objective, approach (a few lines), step list (a summary of the `INPROGRESS.md` steps, not a second plan). Every task gets one (a mechanical task's can be two lines). It is not an approval gate: when no Scope trigger fires, proceed. A choice that fires a Scope trigger stops the run (batch it, see below). An internal choice that fires none is decided by the orchestrator — recommended default applied, flagged, reversible. For architectural tasks the briefing follows the design review. Implementation runs in waves: a wave leaves the repo green and is committable on its own. A user interjection reopens the design step — amend steps before more code, never patch mid-implementation.
  - **Batch questions**: investigate repo facts first, then ask once — one batch of the independent questions whose answer can change the step list or fire a Scope trigger, each with a recommended answer. Never leak one question at a time; never pad the batch with trivia resolvable from the repo.
- **One task at a time**: a second requested task while `INPROGRESS.md` holds an unfinished one → ask first (finish, park, switch) before touching the file.
- **While working**: the orchestrator ticks `[x]` steps as results come back and records blockers as they appear — never only before commit.
- **Ownership & delegation ledger**: `INPROGRESS.md` is orchestrator-owned in full — sub-agents NEVER edit it; they return progress updates in their factual return and the orchestrator transcribes them. Write one ledger line per delegation BEFORE invoking the sub-agent, and record the returned `task_id` on it after (line format: `INPROGRESS.md` template, "Delegations"). Attempt ids start at 1; a correction keeps the logical id and increments the attempt (`7.2` corrects `7`); the worker echoes the attempt id. **Late-writer guard**: before dispatching a correction, confirm the prior attempt is TERMINATED (resumed instance asked to stop, or the fresh instance isolated from files the old one could still touch); unknown liveness blocks overlapping writes. For consequential or long-running work, persist the factual return before treating the completion notification as acceptance. Ordinary synchronous tasks need one line — no report-file bureaucracy.
- **Task complete** (every step ticked, or explicitly dropped with a note) — one atomic pass by the orchestrator; sub-agents never close a task unless the brief explicitly delegates it:
  1. `CHANGELOG.md`: add the entry under `## [Unreleased]`, describing the net change vs the last released version (format and undo/revert rules: the CHANGELOG template header). Versions are decided at delivery, never mid-development (§6, Releases).
  2. `TODO.md`: tick the task checkbox — only if every step is ticked or explicitly dropped; if the task was re-scoped or split, update `TODO.md` instead of ticking.
  3. If `workflow.designs` points to an existing file: add the DESIGNS entry (format: its template header) **before** the reset — the reset erases the task intent the commit review needs. After closure, the commit review's intent sources include the latest DESIGNS entry (§6).
  4. Reset `INPROGRESS.md` to the clean skeleton with a pointer to the next `TODO.md` task — a clean skeleton between two tasks is normal, not stale.

## 2. .md companions

Active only while `companions.enabled` is true in `dev-workflow.json`. Every **newly created** source file gets its companion `.md` in the same pass (not after the fact); an existing source file **significantly modified** gets its companion updated in the same pass. Format, extensions and hook enforcement scope: README, "Per-project config".

## 3. Conventions and baseline

- Read `workflow.conventions` (default `CONVENTIONS.md`) before writing or editing code and follow it. Its always-apply baseline (intent-only comments, no history comments, the reuse ladder) holds even when the file is absent.
- **Nothing is true without proof**: every claim you rely on — brief, prior report, doc, your own reading — is unverified until checked against code or an executed check. Findings and reports carry their proof (`file:line`, test output). If it cannot be verified, say so instead of assuming.

## 4. Safety rules

If `workflow.rules` points to an existing file (e.g. `RULES.md`), read it before writing or editing code and follow it. A violation is never silent: flag it per that file's deviation protocol.

## 5. Spec/design compliance

If `workflow.spec` points to an existing file (e.g. `SPEC.md`), re-read it before committing a change that could deviate. A necessary deviation is flagged explicitly to the user — never decided alone.

## 6. Before proposing a commit

Two layers, both required:

1. **Deterministic hook.** Verify (or remind the user) that the pre-commit hook passes. Its checks are `precommit.checks[]` of `dev-workflow.json`; the builtins' names and semantics are the contract in the hook header (`workflow/hooks/pre-commit.sh`). Only checks with a non-empty `cmd` or a `builtin` run. If the hook is absent or inactive (e.g. parked as a sibling), run the configured checks manually before proposing the commit.
2. **Semantic check (LLM).** A review-agent pass (`review`, or `cheap-review` from the global roster) on the commit, not the worktree (`git show`, or the staged diff before one exists), with the task intent (INPROGRESS.md, TODO.md, SPEC.md — for a closed task, the latest DESIGNS.md entry, which captured the contract before the reset), asking one question: *what might be missing?*
   - stale or missing companion `.md`;
   - missing CHANGELOG entry;
   - a stale, missing or divergent `DESIGNS.md` entry when `workflow.designs` is enabled (it must reflect the design as implemented, direction changes included);
   - touched-but-unstaged file, forgotten test, dead code left behind.

   The reviewer must be a different model family than the producer (the `# Model family:` header of each agent; roster/MODELS.md). Totals claimed in a commit message must be reproducible — run the test suite against the commit, not the worktree. Each finding is rated blocking / worth fixing / ignorable.
   - **Review bound**: round 1 review → fix → round 2 fresh review. No third round. An agreed major (the producer does not contest it) is a failed rung: the fix goes to the producer's next implementer rung, and its review restarts at the reviewer that rung calls for. Reviewer doubt (cannot settle major vs minor) escalates along the reviewer's own ladder. A contested major (the producer rebuts with evidence) goes to arbitration only when admissible (logged in the decision log; counts toward the 2-per-task arbitration bound), else to the user.

The orchestrator summarizes the findings and recommends; the **user decides**: fix first, or commit as-is. The semantic check never blocks the commit mechanically — the hook does. NEVER suggest `--no-verify` unless the user explicitly asks for it.

**Commit and push are the user's call.** Several consecutive commits may be batched under ONE explicit user authorization within the same task. A push authorization covers exactly ONE push — each push needs its own explicit authorization, never batched, never inferred from a commit authorization or an earlier push. When unsure whether an authorization extends, ask. At task end — or when a validated wave could be committed — the orchestrator asks how to proceed (one commit per validated wave, a single bulk commit, or wait), recommends one option with a one-line rationale grounded in the task's content (bisectability, risk), and follows the decision. It never commits autonomously.

Once a commit is made (user-approved), a post-commit gate applies: `git show --stat HEAD` must match the implementation agent's reported file list file by file — any gap is blocking; test totals claimed must be re-run post-commit and match; the commit message states only verifiable claims.

**Releases** are proposed the same way: when `## [Unreleased]` accumulates releasable changes, propose a release as a commit is proposed — timing and version with a grounded rationale (the accumulated batch: breaking → major, features → minor, fixes → patch); follow the user's decision. Approval of the proposal is not release authorization: after it, verify the notes, version, checks, tag and push target separately — never tag or push from the proposal alone. If checks fail, the tag already exists, or a push partly succeeds: abort before pushing, fix, retry from a clean state. An already-published tag is handled explicitly with the user, never by implied rollback.

## 7. Memory / compaction

- Suggest `/compact` (never run it automatically) only at **natural boundaries**: phase done and committed, or a completely different subject starting. Never mid-debug or mid-refactor. The suggested message is about the **next** task (objective + existing reusable base), never a summary of what was just done.
- **Agent instance — resume or start fresh**: resume the same `task_id` instance only for a small iteration on its own output, and only when the context it carries is useful to the next round (same feature, files, design contract). The moment the next round is a different phase or area, a fresh session with a complete self-contained brief is cheaper. Anything large → fresh.
- **Context cap**: an agent session stays under ~100K tokens of context. Past it, close the round and continue in a fresh session with a complete brief — the previous round's report IS its brief.
- **Reviews — always a fresh instance**: a review (code or design), first pass or re-review, never reuses an instance that authored or judged the work. The orchestrator hands it the **contract** (acceptance criteria in the orchestrator's own words, frozen decisions, rules/conventions pointers, `RULE-DEVIATION` lines), the **artifact** (diff range or doc path) and **raw evidence** (test output verbatim) — never the author's reasoning or transcript. A re-review adds the prior findings list plus the fix delta: each finding closed by `file:line`, the delta reviewed as new code. One task = one instance for implementers and designers: resumed only for that task's own fix rounds, never across tasks.
- **Empty report — a recovery decision, not a verdict**: a subagent that returns completed with an empty or evidence-free report → inspect the worktree and task state first; if the instance is resumable, request a factual report from it; verify independently; if recovery fails, escalate rather than blindly rerunning side-effecting work.

## 8. Sub-agents & git

- **The staging area is the agent's report, file by file.** Commit from the implementation agent's reported file list (`git add <reported files>`), never a directory deduction — a `git add <dir>` is how tests get missed. After the commit, `git show --stat HEAD` is compared against the report (§6 gate). A gap blocks the next wave; the user chooses the remedy — amend the unpushed commit, or a documented follow-up commit.
- **Dirty worktree is stashed, never discarded.** Before any checkout, reset or rebase, `git status` must be clean; if dirty, `git stash` (recoverable, logged). Never `git checkout -- .` or any other discard.
- **One writing agent per worktree.** Parallel implementation sub-agents only with disjoint file sets and no shared artifacts (build directory, test suite, stash, `INPROGRESS.md`); otherwise serialize. Implementation agents never mutate git state — every git operation routes through the orchestrator.
- **Git mutations stay inside the launch repo.** An agent instance adds, commits, stashes, checks out or resets only in the repository it was launched in. Mutating git state in any other repo (a dependency, a sibling checkout, a scratch dir reached via `cd`) is forbidden — surface a cross-repo change to the user instead.
- **Lost work that was rewritten is documented, not hidden.** Restoring lost work gets a dedicated restoration commit stating what was lost, the faulty original commit and the totals discrepancy — never silently amend or rewrite history; the history must tell the incident.

## 9. Periodic coherence review & retro

- At a phase boundary (all its `TODO.md` tasks ticked) or on request, PROPOSE a read-only coherence review of the phase's commits — docs vs behavior, stale companions, cross-file contradictions, simplifications that keep the meaning. Never run it automatically; findings ranked by importance with `file:line`; the user decides.
- After a consequential failure or at a phase boundary, PROPOSE a retro (never automatic). First check the previous retro's follow-through. Ground the failure in evidence (what, where, expected vs actual). Propose **at most two** changes, each with an owner, an expected benefit and a next-task check. A no-op retro records why current practice stays and what evidence would reopen it.
- Kit-workflow proposals (anything touching this skill's files — SKILL.md, agent prompts, `dev-workflow.json`, the hook, templates) are written as a **self-contained, extractable block** for a fresh kit-repo session: target file(s), exact change, evidence, acceptance check. Mechanical mistakes route to lint/test/pre-commit config — never to new prose rules. A retro never expands authority or applies anything without the user's decision.

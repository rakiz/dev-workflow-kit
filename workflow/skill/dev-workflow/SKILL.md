---
name: dev-workflow
description: "Multi-step work cycle of a software project managed by TODO.md, INPROGRESS.md, CHANGELOG.md, DESIGNS.md. Triggers on: starting a new task or phase tracked in TODO.md/INPROGRESS.md, finishing a task, updating progress state, creating or updating a source file's .md companion, preparing or verifying a commit (pre-commit hook, dev-workflow.json), suggesting a /compact compaction at a task boundary."
---

# Dev workflow (TODO → INPROGRESS → CHANGELOG; DESIGNS archive)

## 1. TODO/INPROGRESS → CHANGELOG cycle

(`TODO.md`, `INPROGRESS.md` and `CHANGELOG.md` are the default filenames — configurable via `workflow.todo` / `workflow.inprogress` / `workflow.changelog` / `workflow.designs` in `dev-workflow.json`.)

- **Roles**:
  - `TODO.md` — the high-level roadmap: phases made of task checkboxes, no detail.
  - `INPROGRESS.md` — tracks exactly **one** task at a time; holds the active task's detail.
  - `SPEC.md` (if `workflow.spec` of `dev-workflow.json` points to an existing file) — stable design decisions go here, not to `INPROGRESS.md`.
  - `DESIGNS.md` (if `workflow.designs` points to an existing file) — the **archive of designs as implemented**: one section per completed task, newest first; non-normative history, never a second progress tracker or roadmap — `SPEC.md` stays the owner of current decisions.
  - SPEC absent or not configured → durable design decisions live in DESIGNS entries plus `TODO.md`'s "Context" notes.
- **At task start** (before executing):
  - **Resume = reconciliation, not trust**: read the active task in `INPROGRESS.md` (plus `TODO.md` and `SPEC.md` if present/configured), then verify against git before trusting any checkbox.
    - **Verify**: `git status`/`git diff` show only UNCOMMITTED state — also read the task's latest recorded commit identity (`git log --oneline -5`); committed work is invisible to status. Not every dirty file is this task's work — ask when ambiguous.
    - **State**: the resume note states **intent/authorization** (what the user asked — never inferred from disk state alone), **artifacts produced** (what actually exists on disk), and **work accepted** (what passed review/checks — bound to the FINAL artifact identity: commit hash, or worktree hash via `git write-tree` when uncommitted, plus the recorded check results — never to an earlier point in time). "Produced but unaccepted" is an explicit state: an unticked checkbox does not mean rerun — verify the artifact instead.
    - **Invalidate**: acceptance is invalidated by any relevant change to the revision after it (new commits touching the artifact, a rebase, a stash restore) → REVALIDATION required.
    - **Correct**: a note contradicted by git ("uncommitted" that is committed, "working now" that is released) is corrected in the same pass — `INPROGRESS.md` is authoritative only AFTER verification against git, and a stale note never redirects the session.
  - **Design step (mandatory, every task)**: write the task header immediately (name + objective + reference to the matching `TODO.md` section) together with an unticked `[ ]` design/planning step, then detail the steps progressively as the design converges — the STEP is always there, the ARTIFACTS are proportional (a trivial task's design can be a few lines: scope, steps, acceptance criterion) — so the design itself stays traceable across a lost session (the first unticked `[ ]` step is always the current position).
  - **Routing** — the design's depth follows the task's class: **mechanical** (well-understood, single-file-scope transformation) → the orchestrator writes the minimal plan itself, no design agent; **standard** (ordinary feature/refactor on established patterns) → the orchestrator designs, delegating to a design producer agent is optional. Mechanical tasks route to `cheap-mech`, standard ones to `cheap-code` (global roster, when installed); implementation itself is always delegated — the orchestrator coordinates, never implements.
  - **Delegate vs inline** — delegate when only the **result** matters: read-only exploration and broad search → the `explore` agent; fully-specified or parallelizable work → the implementation rungs (`cheap-mech`/`cheap-code`, roster when installed — if no implementation agent is available, stop and ask the user). Inline means read/search only — any code or doc edit is delegated per Routing, even when it looks quick; inline is for when it is quick and targeted (a named file, a targeted grep, a single-commit peek) or when the output immediately constrains the next step. Before parallel dispatch, confirm: no ordering dependencies between the tasks, and per §8 disjoint file sets with no shared artifacts; synthesis must fit the remaining context. When deciding, ignore these thoughts: *"I'll just search myself"* (raw search output pollutes the orchestrator's context — delegate) and *"I need the full result"* (subagents return structured results — delegate and synthesize); *"small enough to do inline"* is valid **only** when the output constrains the next step, not because the task looks easy.
  - **Architectural tasks** (new/changed contract, migration, concurrency, security boundary, costly-to-reverse): delegate design to a producer agent (`cheap-design`/`strong-design` per the escalation ladder — MODELS.md, 'Escalation semantics': rung N+1 only after rung N failed, stalled or expressed doubt) **and** run a mandatory independent design review (fresh instance, read-only) (`cheap-design-review`/`strong-design-review` per the escalation ladder) before implementation. No design agent available in the session → stop and ask the user how to satisfy the gate. Never silently self-design an architectural task.
  - **SPEC reconciliation**: re-reading the sections of `SPEC.md` (and `TODO.md`) the task touches is not just a consistency check — the orchestrator **re-evaluates the global design at task granularity** (do the touched sections still hold given this task's detail?); a global-vs-local disagreement is flagged before writing code, not mid-way; the local decision wins and the SPEC update follows.
  - **Scope**: the step list bounds the session — anything identified but outside it is explicitly deferred (a new `TODO.md` entry or `SPEC.md`'s "Out of scope"), never silently absorbed; if the scope must grow mid-task, revalidate with the user. Explicit user approval **before implementation** is required when: the objective changes relative to the `TODO.md` task; the scope would grow (crossing the "Out of scope" boundary — merely referencing it is not a trigger); the design conflicts with a SPEC requirement or non-goal; the action is destructive or costly to reverse; a user-facing choice is unresolved. Otherwise a clear request to perform a task authorizes its in-scope plan — delegating the design to a producer agent is by itself not a confirmation trigger; a question, a partial answer or an ambiguous assent does not authorize an unresolved task or scope — clarify before executing.
  - **Design briefing — presented, not gated, always**: before the first implementation step, the orchestrator posts a short briefing to the user: objective, chosen approach (a few lines), and the step list — a summary of the `INPROGRESS.md` steps written by the design step, not a second plan. Every task gets one, whatever its routing class (a mechanical task's briefing can be two lines). The briefing is a presentation, not an approval gate: the original request authorizes in-scope work (see Scope), and when no Scope trigger fires the orchestrator proceeds without waiting for a reply. Open choices split accordingly: a choice that fires a Scope trigger stops the run — batch it per the rule below and wait for the answer; an internal implementation choice that fires none is decided by the orchestrator — recommended default applied and flagged in the briefing, reversible later. For an architectural task the briefing follows the mandatory design review (the user sees the reviewed plan, not one about to change). Keep a cut cheap: implementation runs in waves — a wave is a set of steps that leaves the repo green and is committable on its own. A user interjection reopens the design step: amend the steps before more code is written, never patch mid-implementation.
  - **Batch questions before asking**: when the design leaves several open questions, investigate repo facts first, then ask the user once — a single batch of the independent questions whose answer can change the step list or fire a Scope trigger, each with a recommended answer. Do not leak one question at a time, and never pad the batch with trivia resolvable from the repo.
- **One task at a time**: if a second task is requested while `INPROGRESS.md` holds an unfinished one, ask the user first (finish, park, or switch) before touching the file.
- **While working**: the orchestrator ticks `[x]` steps as their results come back and records blockers as soon as they appear — never only before commit. The first unticked `[ ]` step is the current position; this is what makes a lost session resumable.
- **Ownership & delegation ledger**: `INPROGRESS.md` is orchestrator-owned in full — sub-agents NEVER edit it; they return progress updates (steps done, blockers) in their factual return and the orchestrator transcribes them. Inside the active task section, keep a ledger, one line per delegation, written BEFORE invoking the sub-agent (record the returned `task_id` after):
  `- <attempt> | <task/step> | <role> | <allowed files/resources> | <starting artifact identity> | <task_id> | <status> | <return location>`
  Attempt ids start at 1; a correction keeps the logical id and increments the attempt (`7.2` corrects attempt `7`); the worker echoes the correction attempt id in its return. **Late-writer guard**: before dispatching a correction attempt, confirm the prior attempt is TERMINATED (resumed instance asked to stop, or the fresh instance is isolated from the files the old one could still touch); unknown liveness blocks overlapping writes. For consequential or long-running work, persist the factual return before treating the tool's completion notification as acceptance. Ordinary synchronous tasks need one line — no report-file bureaucracy.
- **Task complete** (every step ticked, or explicitly dropped with a note) — one atomic pass, performed by the orchestrator once all delegated steps are done or dropped (sub-agents return progress updates in their factual return — they never edit `INPROGRESS.md` — and never close the task unless the brief explicitly delegates it):
  1. Add an entry to `CHANGELOG.md` (Keep a Changelog format — entry template at the top of that file; for versionless projects, a date + summary line is enough). Task entries always land under `## [Unreleased]` and describe:
     - the net change relative to the previous released version (the last `## [X.Y.Z] - date` entry below it) — not relative to the state before this task;
     - a change undone within the same unreleased version: not mentioned — edit the earlier Unreleased entry so the section describes only the net effect;
     - the revert of an already-released change: mentioned, as part of the new version's entry.
     - **Versioning is decided at delivery**: entries accumulate under `## [Unreleased]`; never bump a project VERSION mid-development — when the owner asks for a release, judge the accumulated batch and pick major/minor/patch accordingly (VERSION + tag together at that moment).
  2. Tick the corresponding task checkbox in `TODO.md` — only if every `INPROGRESS.md` step is ticked or explicitly dropped; if the task was re-scoped or split along the way, update `TODO.md` accordingly instead of ticking it.
  3. If `workflow.designs` of `dev-workflow.json` points to an existing file (e.g. `DESIGNS.md`), add a DESIGNS entry — one section per completed task, newest first: the design **as implemented**, direction changes (planned X → did Y, why), rejected alternatives worth remembering, and pointers to the relevant `SPEC.md` sections (link, don't duplicate normative content). Write it **before** the reset: resetting `INPROGRESS.md` erases the task intent the commit review needs, so the finalized contract — acceptance criteria plus the design decisions taken — is captured in this entry first; after closure, the commit review's task-intent sources include the latest DESIGNS entry (§6).
  4. Reset `INPROGRESS.md` to the clean skeleton with a pointer to the next `TODO.md` task — a clean skeleton between two tasks is normal, not stale.

## 2. .md companions

If `dev-workflow.json` has `companions.enabled: true`:

- Every **newly created** source file gets its companion `.md` (same folder, same name) created **in the same pass**: role of the file, invariants, pitfalls. Not after the fact. Enforcement scope: the hook enforces this mechanically **only** for the extensions listed in the companions check of `dev-workflow.json` (default `["cpp", "h", "ts", "tsx"]`) — keep that list aligned with the project's languages; for any other extension the rule is the skill's, not the hook's.
- An existing source file **significantly modified** → its `.md` companion (if it exists) is updated in the same pass.

On an existing codebase you don't want to pollute with companions, set `companions.enabled: false` in dev-workflow.json.

## 3. Coding conventions

If `workflow.conventions` of `dev-workflow.json` points to an existing file (e.g. `CONVENTIONS.md`), read it before writing or editing code and follow its rules.

Baseline rules that apply **always** — even if the conventions file does not exist or has not been customized:

1. **Comments describe intent, not code.** A comment explains WHY the code does something (a decision, a constraint, a non-obvious tradeoff) — it never restates WHAT the next line already says in code.
2. **Comments describe the current state, not its history.** Outside `CHANGELOG.md`, code comments never narrate evolution — no history-narrating phrasing ("previously", "used to be", "changed from"…). A past decision that matters belongs in `CHANGELOG.md` or a commit message, not in a comment describing what the code does today.
3. **Reuse before writing — the ladder.** Before writing anything new, stop at the first rung that holds: (a) does it need to exist — maybe the requirement itself is wrong? (b) does the codebase already have it? (c) does the standard library? (d) does the platform/runtime? (e) an installed dependency? (f) can it be one line? A rung that holds means reuse it — write nothing new. If none holds, write the minimum that works, plus at least one small test if it carries logic — tests the acceptance criteria require are not capped by this. Lazy about the solution, never about validation, error handling or security: what the task needs is written in full.

## 4. Safety rules

If `workflow.rules` of `dev-workflow.json` points to an existing file (e.g. `RULES.md`), read it before writing or editing code and follow its rules. Unlike the conventions, a rule violation is never silent: flag it per that file's deviation protocol.

## 5. Spec/design compliance

If `workflow.spec` of `dev-workflow.json` points to an existing file (e.g. `SPEC.md`), re-read it before committing a change that could deviate from it. If a deviation is necessary, **flag it explicitly to the user** — do not decide alone.

## 6. Before proposing a commit

Two layers, both required:

1. **Deterministic hook.** Verify (or remind the user) that the pre-commit hook passes: checks are defined in `precommit.checks[]` of `dev-workflow.json` (the template ships a disabled `tests` check plus the companions builtin — only checks with a non-empty `cmd` or a `builtin` run). If the hook is absent or inactive (e.g. an existing hook was parked as a sibling), run the configured `precommit.checks[]` checks manually before proposing the commit.
2. **Semantic check (LLM).** A review-agent pass (`review`, or `cheap-review` from the global roster if installed) on the commit, not the worktree (`git show`, or the staged diff before one exists), plus the task intent (INPROGRESS.md, TODO.md, SPEC.md — for an already-closed task, also the latest DESIGNS.md entry, which captured the contract before the reset), with one question: *what might be missing?*
   - stale or missing companion `.md`;
   - missing CHANGELOG entry;
   - a stale, missing or divergent `DESIGNS.md` entry when `workflow.designs` is enabled (it must reflect the design as actually implemented, direction changes included);
   - touched-but-unstaged file, forgotten test, dead code left behind.

   Totals claimed in a commit message (tests added, suites passing) must be reproducible — run the test suite against the commit, not the worktree. Each finding is rated by importance (blocking / worth fixing / ignorable).

The orchestrator summarizes the findings and makes a recommendation — the **user decides**: fix first, or commit as-is. The semantic check never blocks the commit mechanically; the hook does.

Committing is the user's call too: at task end — or when a validated wave could be committed — the orchestrator asks how to proceed (one commit per validated wave, a single bulk commit, or wait), recommends one option with a one-line rationale grounded in the task's actual content (e.g. "3 independent waves → 3 commits"), judged on bisectability and risk, not a generic formula, and follows the user's decision — it never commits autonomously.

Once a commit is made (user-approved), a quick post-commit gate applies to every commit: `git show --stat HEAD` must match the implementation agent's reported file list file by file — any gap is blocking; the test totals claimed must be re-run post-commit and match; and the commit message states only verifiable claims.

Releases are proposed the same way: when `## [Unreleased]` accumulates releasable changes, propose a release as a commit is proposed — recommend timing and version with a grounded rationale, and follow the user's decision. Approval of the proposal is not release authorization: after approval, verify the notes, the version, the checks, the tag and the push target separately — never tag or push from the proposal alone. If checks fail, the tag already exists, or a push partly succeeds: abort before pushing, fix, and retry from a clean state — an already-published tag is handled explicitly with the user, never implied automatic rollback.

NEVER suggest `--no-verify` unless the user explicitly asks for it.

## 7. Memory / compaction

- Suggest `/compact` (never run it automatically) only at **natural boundaries**: phase done and committed, completely different subject starting. Never in the middle of an active debug/refactor.
- The suggested message talks about the **next** task: objective + existing reusable base. Never a summary of what was just done (already in git/CHANGELOG).
- **Agent instance — resume or start fresh**: the same `task_id` instance for a small iteration on its own output; a fresh instance with a complete self-contained brief for anything large.
- **Reviews — always a fresh instance**: a review (code or design), first pass or re-review, never reuses an instance that authored or already judged the work; the orchestrator starts fresh and hands it the **contract** (acceptance criteria from TODO/INPROGRESS/SPEC in the orchestrator's own words, frozen decisions, rules/conventions pointers, `RULE-DEVIATION` lines), the **artifact** (diff range or doc path) and **raw evidence** (test output verbatim) — never the author's reasoning or transcript. On a re-review the brief adds the prior findings list plus the fix delta: each finding closed by `file:line`, and the delta reviewed as new code. One task = one instance for implementers and designers: resumed only for that task's own fix rounds, never across tasks.
- **Empty report — a recovery decision, not a verdict**: a subagent that returns completed with an empty or evidence-free report is a recovery decision, not a verdict on the work — inspect the worktree and task state first; if the instance is resumable, request a factual report from it; verify the result independently; if recovery fails, escalate rather than blindly rerunning side-effecting work.

## 8. Sub-agents & git

- **The staging area is the agent's report, file by file.** Commit from the implementation agent's reported file list (`git add <reported files>`), never a directory deduction — a `git add <dir>` is how tests get missed. After the commit, compare `git show --stat HEAD` against the report: any gap is blocking (see §6 post-commit gate). A gap blocks the next wave; the user chooses the remedy — amend the unpushed commit, or a documented follow-up commit.
- **Dirty worktree is stashed, never discarded.** Before any checkout, reset or rebase, `git status` must be clean; if dirty, `git stash` (recoverable, logged) — never `git checkout -- .` or any other discard.
- **One writing agent per worktree.** Run parallel implementation sub-agents only with disjoint file sets and no shared artifacts (build directory, test suite, stash, `INPROGRESS.md` — orchestrator-owned, see §1); otherwise serialize. Implementation agents never mutate git state — no stash, checkout, reset or commit; every git operation routes through the orchestrator.
- **Git mutations stay inside the launch repo.** An agent instance — sub-agent or orchestrator — adds, commits, stashes, checks out or resets only in the repository it was launched in (its starting directory / its own worktree); mutating git state in any other repo (a dependency, a sibling checkout, a scratch dir reached via `cd`) is forbidden — a cross-repo change is surfaced to the user instead.
- **Lost work that was rewritten is documented, not hidden.** Restoring lost work gets a dedicated restoration commit stating what was lost, the faulty original commit and the totals discrepancy — never silently amend or rewrite history; the history must tell the incident.

## 9. Periodic coherence review

- When a phase completes (all its tasks ticked in TODO.md) — or whenever the user asks — PROPOSE a read-only coherence & simplification review of the phase's commits (never run it automatically).
- The review checks: docs/instructions vs actual behavior (config, hook, agents), stale or missing companions, cross-file contradictions introduced along the way, and simplification opportunities (fewer instructions at equal meaning — nothing may be lost).
- Report findings ranked by importance with file:line; the user decides what to apply.
- **Optional retro** — after a consequential failure or at a phase boundary, PROPOSE a retro (never run one automatically):
  1. Inspect the previous retro's proposals: was the follow-through check (the next-task check each proposal named) actually done?
  2. Identify the observed failure — evidence (what happened, where, expected vs actual), not vibes.
  3. Propose **at most two** changes, each with an **owner**, **expected benefit**, and the **next-task check** that will test it. Kit-workflow proposals — anything touching this skill's own files (SKILL.md, agent prompts, `dev-workflow.json`, the hook, templates) — must be clearly marked and written as a **self-contained, extractable block** the user can copy verbatim into a fresh kit-repo session, carrying its own: target file(s), exact change, evidence, acceptance check; project-level proposals stay in the project's normal flow (the distinction is routing: kit proposals go to the user for a kit-repo session).
  4. A legitimate **no-op retro** records why current practice is retained and what evidence would reopen it.
  5. Mechanical mistakes (formatting, lint) route to lint/test/pre-commit config — never into new prose rules.
- A retro only PROPOSES: it never expands the agent's authority, never silently rewrites global instructions, and applies nothing without the user's decision.

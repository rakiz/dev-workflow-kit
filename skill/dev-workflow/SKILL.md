---
name: dev-workflow
description: "Multi-step work cycle of a software project managed by TODO.md, INPROGRESS.md, CHANGELOG.md. Triggers on: starting a new task or phase tracked in TODO.md/INPROGRESS.md, finishing a task, updating progress state, creating or updating a source file's .md companion, preparing or verifying a commit (pre-commit hook, dev-workflow.json), suggesting a /compact compaction at a task boundary."
---

# Dev workflow (TODO → INPROGRESS → CHANGELOG)

## 1. TODO/INPROGRESS → CHANGELOG cycle

(`TODO.md`, `INPROGRESS.md` and `CHANGELOG.md` are the default filenames — configurable via `workflow.todo` / `workflow.inprogress` / `workflow.changelog` in `dev-workflow.json`.)

- **Roles**: `TODO.md` is the high-level roadmap — phases made of task checkboxes, no detail; `INPROGRESS.md` tracks exactly **one** task at a time and holds the active task's detail. Stable design decisions go to `SPEC.md` (if `workflow.spec` of `dev-workflow.json` points to an existing file), not to `INPROGRESS.md`.
- **At task start** (before executing): read `INPROGRESS.md` — if it holds an unfinished task, resume exactly where marked (first unticked `[ ]` step) — plus `TODO.md` if it exists (roadmap) and `SPEC.md` if configured. A task begins with a design step of variable length: write the task header immediately (name + objective + reference to the matching `TODO.md` section), then detail the steps progressively as the design converges — so the design itself stays traceable across a lost session.
- **One task at a time**: if a second task is requested while `INPROGRESS.md` holds an unfinished one, ask the user first (finish, park, or switch) before touching the file.
- **While working**: tick `[x]` steps as they complete and record blockers as soon as they appear — never only before commit. The first unticked `[ ]` step is the current position; this is what makes a lost session resumable.
- **Task complete** (every step ticked, or explicitly dropped with a note) — one atomic pass:
  1. Add an entry to `CHANGELOG.md` (Keep a Changelog format — entry template at the top of that file; for versionless projects, a date + summary line is enough). Task entries always land under `## [Unreleased]` and describe:
     - the net change relative to the previous released version (the last `## [X.Y.Z] - date` entry below it) — not relative to the state before this task;
     - a change undone within the same unreleased version: not mentioned — edit the earlier Unreleased entry so the section describes only the net effect;
     - the revert of an already-released change: mentioned, as part of the new version's entry.
  2. Tick the corresponding task checkbox in `TODO.md` — only if every `INPROGRESS.md` step is ticked or explicitly dropped; if the task was re-scoped or split along the way, update `TODO.md` accordingly instead of ticking it.
  3. Reset `INPROGRESS.md` to the clean skeleton with a pointer to the next `TODO.md` task — a clean skeleton between two tasks is normal, not stale.

## 2. .md companions

If `dev-workflow.json` has `companions.enabled: true`:

- Every **newly created** source file gets its companion `.md` (same folder, same name) created **in the same pass**: role of the file, invariants, pitfalls. Not after the fact. Enforcement scope: the hook enforces this mechanically **only** for the extensions listed in the companions check of `dev-workflow.json` (default `["cpp", "h", "ts", "tsx"]`) — keep that list aligned with the project's languages; for any other extension the rule is the skill's, not the hook's.
- An existing source file **significantly modified** → its `.md` companion (if it exists) is updated in the same pass.

On an existing codebase you don't want to pollute with companions, set `companions.enabled: false` in dev-workflow.json — no companion is created and the hook check is skipped.

## 3. Coding conventions

If `workflow.conventions` of `dev-workflow.json` points to an existing file (e.g. `CONVENTIONS.md`), read it before writing or editing code and follow its rules.

Two baseline rules apply **always** — even if the conventions file does not exist or has not been customized:

1. **Comments describe intent, not code.** A comment explains WHY the code does something (a decision, a constraint, a non-obvious tradeoff) — it never restates WHAT the next line already says in code.
2. **Comments describe the current state, not its history.** Outside `CHANGELOG.md`, code comments never narrate evolution — no history-narrating phrasing ("previously", "used to be", "changed from"…). A past decision that matters belongs in `CHANGELOG.md` or a commit message, not in a comment describing what the code does today.

## 4. Safety rules

If `workflow.rules` of `dev-workflow.json` points to an existing file (e.g. `RULES.md`), read it before writing or editing code and follow its rules. Unlike the conventions, a rule violation is never silent: flag it per that file's deviation protocol.

## 5. Spec/design compliance

If `workflow.spec` of `dev-workflow.json` points to an existing file (e.g. `SPEC.md`), re-read it before committing a change that could deviate from it. If a deviation is necessary, **flag it explicitly to the user** — do not decide alone.

## 6. Before proposing a commit

Two layers, both required:

1. **Deterministic hook.** Verify (or remind the user) that the pre-commit hook passes: checks are defined in `precommit.checks[]` of `dev-workflow.json` (the template ships a disabled `tests` check plus the companions builtin — only checks with a non-empty `cmd` run). If the hook is absent or inactive (e.g. an existing hook was parked as a sibling), run the configured `precommit.checks[]` checks manually before proposing the commit.
2. **Semantic check (LLM).** A review-agent pass (`review`, or `cheap-review` from the global roster if installed) on the staged diff plus the task intent (INPROGRESS.md, TODO.md, SPEC.md) with one question: *what might be missing?* — stale or missing companion `.md`, missing CHANGELOG entry, touched-but-unstaged file, forgotten test, dead code left behind. Each finding is rated by importance (blocking / worth fixing / ignorable).

The orchestrator summarizes the findings and makes a recommendation — the **user decides**: fix first, or commit as-is. The semantic check never blocks the commit mechanically; the hook does.

NEVER suggest `--no-verify` unless the user explicitly asks for it.

## 7. Memory / compaction

- Suggest `/compact` (never run it automatically) only at **natural boundaries**: phase done and committed, completely different subject starting. Never in the middle of an active debug/refactor.
- The suggested message talks about the **next** task: objective + existing reusable base. Never a summary of what was just done (already in git/CHANGELOG).

## 8. Periodic coherence review

- When a phase completes (all its tasks ticked in TODO.md) — or whenever the user asks — PROPOSE a read-only coherence & simplification review of the phase's commits (never run it automatically).
- The review checks: docs/instructions vs actual behavior (config, hook, agents), stale or missing companions, cross-file contradictions introduced along the way, and simplification opportunities (fewer instructions at equal meaning — nothing may be lost).
- Report findings ranked by importance with file:line; the user decides what to apply.

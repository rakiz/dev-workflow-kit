# INPROGRESS

<!-- Orchestrator-owned in full: sub-agents NEVER edit this file — they return
     progress updates (steps done, blockers) in their factual return, and the
     orchestrator transcribes them. On resume, reconcile every note against
     git before trusting it (committed work is invisible to `git status`) —
     full contract: dev-workflow skill (§1). -->

## Current task

<!-- Name + objective (reference to the matching section of TODO.md).
     Between two tasks: just a pointer to the next TODO.md task. -->

## Steps

<!-- The first step is ALWAYS the design/planning step (mandatory, written at
     task start) — proportional to the task: a trivial task's design can be a
     few lines (scope, steps, acceptance criterion). Detail it progressively
     as the design converges. Tick [x] as results come back; record blockers
     as they appear. -->

- [ ] ...

## Delegations

<!-- One line per delegation, written BEFORE invoking the sub-agent (record
     the returned task_id after). Corrections keep the logical id and
     increment the attempt (7, then 7.2). Format and rules (late-writer
     guard, return persistence): dev-workflow skill (§1, "Ownership &
     delegation ledger"). -->

- `7 | <task/step> | <role> | <allowed files/resources> | <starting artifact identity> | <task_id> | <status> | <return location>`

## Blockers

<!-- None, or description + what is needed to lift it. -->

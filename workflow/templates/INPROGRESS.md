# INPROGRESS

<!-- Orchestrator-owned in full: sub-agents NEVER edit this file — they return
     progress updates (steps done, blockers) in their factual return, and the
     orchestrator transcribes them. On resume, reconcile every note against
     git before trusting it (committed work is invisible to `git status`) —
     full contract: dev-workflow skill (§1). Holds exactly ONE task. -->

## Current task

<!-- Name + objective (reference to the matching section of TODO.md).
     Between two tasks: just a pointer to the next TODO.md task. -->

## Budget

<!-- Defaults are the owner's call: <X> <Y> <Z> stay placeholders until ruled.
     V2 proposed $2 per child / 10 children — provisional, not ruled.
     Stopping on cap = DNF, recorded as a blocker below.
     The spent line is updated by the orchestrator from the usage ledger. -->

budget: cap=$<X> | per-child=$<Y> | max-children=<Z>
spent: $0 (from the usage ledger; orchestrator-updated)

## Steps

<!-- The first step is ALWAYS the design/planning step (mandatory, written at
     task start) — proportional to the task: a trivial task's design can be a
     few lines (scope, steps, acceptance criterion). Detail it progressively
     as the design converges. Tick [x] as results come back; record blockers
     as they appear. -->

- [ ] ...

## Delegations

<!-- One line per delegation, written BEFORE invoking the sub-agent; record
     the returned task_id on it after. task_id is the child session id — the
     usage recorder joins it for per-task cost. On return, record a DIGEST,
     not the verbatim return, inline after the pipe fields: attempt-id echo,
     status, the full file list, numbers with their artifact path, finding
     ids with file:line, task_id (a return of ≤3 lines is its own digest).
     One ledger line per delegation; the digest is inline — no report file.
     Corrections keep the logical
     id and increment the attempt (7, then 7.2). Rules (late-writer guard,
     return persistence): dev-workflow skill (§1, "Ownership & delegation
     ledger"). A wave opens its ledger with a header line
     `wave <n> | lane fast|rigorous | budget <k> dispatches` — the skill's
     Lanes & budget alarm reads that wave's lines against <k>. -->

- `wave <n> | lane fast|rigorous | budget <k> dispatches`
- `7 | <task/step> | <role> | <allowed files/resources> | <starting artifact identity> | task_id=<id> | <status> | <return location> | digest: <attempt-id echo>, <status>, <full file list>, <numbers + artifact path>, <finding ids file:line>`

## Decision log

<!-- Entries are appended BELOW this comment, one per event, as it happens.
     The two shapes are the contract, verbatim here; copy a shape into a new
     line and fill it — never keep the shape text itself as an entry.

     deep-gate — written at the design step, BEFORE any deep-tier consult spend:
     deep-gate: class=<key> | scope=<one line> | instances=[<id>, …] (n=<count>) | library=<hit:<key>|miss|diverged:<key>> | GT=<yes|no> | C=$<cap> | Δ=$<value> (measured: <ledger ref>) | verdict=<CONSULT|SKIP> (<reason>)

     arbitration — written when a contested major is arbitrated; counts toward the 2-per-task bound:
     arbitration: <task> | wave <w> | #<k of 2> | <stands|rejected|human> | $<spent>

     Example rendering (illustrative, not a real event):
     arbitration: parser refactor | wave 2 | #1 of 2 | rejected | $0.84
-->

## Blockers

<!-- None, or description + what is needed to lift it. -->

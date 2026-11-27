# Coding conventions

<!-- Default rules shipped with dev-workflow-kit. They always apply — even if
     this file is never customized. Extend the "Project rules" section below
     with your own (naming conventions, formatting, language-specific idioms,
     error-handling policy, test robustness (tag slow/flaky tests as they are
     introduced, don't put it off), test version-independence (a test that
     must survive a release never hardcodes the current/latest version or tag
     — read it from the source of truth and assert an independently-derived
     expectation alongside it: two values derived from the same source can be
     wrong together; fixed historical versions in compatibility tests stay
     hardcoded), ...). The dev-workflow skill reads this file
     before writing or editing code (path: workflow.conventions in
     dev-workflow.json). -->

## Always-apply baseline (even without this file)

1. **Comments describe intent, not code.** A comment explains WHY the code
   does something (a decision, a constraint, a non-obvious tradeoff); it never
   restates WHAT the next line already says.
2. **Comments describe the current state, not its history.** Outside
   `CHANGELOG.md`, code comments never narrate evolution ("previously", "used
   to be", "changed from", "no longer needed but kept…"). A past decision that
   matters belongs in `CHANGELOG.md` or a commit message. The enforcement
   contract (the `no_history_comments` builtin) lives in the pre-commit hook
   header.
3. **Reuse before writing — the ladder.** Before writing anything new, stop at
   the first rung that holds: (a) does it need to exist — is the requirement
   itself wrong? (b) does the codebase already have it? (c) the standard
   library? (d) the platform/runtime? (e) an installed dependency? (f) can it
   be one line? A rung that holds means reuse — write nothing new. If none
   holds, write the minimum that works, plus at least one small test if it
   carries logic. Lazy about the solution, never about validation, error
   handling or security.

## 1. Design patterns — simple and known

When a problem matches a known pattern, use it in its standard form, under its
usual name — a reader should recognize what they are looking at. Never
introduce a pattern for its own sake: an abstraction, a layer or an
indirection must earn its cost against the task's actual need, and the
simplest thing that works is the default. A pattern added without a problem
it solves is a finding, not a contribution.

## Project rules

<!-- Add your project's own rules here, one subsection per rule, same style
     as the always-apply baseline above. Delete this comment as you fill them
     in. Suggested optional rule — "docs describe the present": published
     reference docs describe supported current behavior; release changes live
     in CHANGELOG.md; necessary migration/decision history lives in its
     appropriate documents; publication follows the project's chosen
     language. -->

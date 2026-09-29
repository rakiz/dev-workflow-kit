# Safety rules

<!-- Rules inspired by JPL's "The Power of 10: Rules for Developing
     Safety-Critical Code" (Gerard Holzmann), generalized beyond C. They
     apply on top of CONVENTIONS.md, which they complement: style and
     conventions live there, safety and robustness here. A violation of a
     rule below is never silent: it requires an explicit, reviewable
     justification, and that justification can be accepted or refused by the
     review step or the user — a refused deviation is blocking until fixed.
     Read by the dev-workflow skill before writing or editing code (path:
     workflow.rules in dev-workflow.json). -->

## R1. Simple control flow

No `goto`. Recursion is avoided; if used, it must be bounded — a provable
termination condition — and justified.

## R2. Fixed loop bounds

Every loop has a fixed, provable bound. No infinite loop without an explicit,
reachable termination condition.

## R3. No unbounded allocation or resource growth

After startup/init, no unbounded dynamic allocation or resource growth — in
particular none in hot paths or per-iteration code.

## R4. Short functions

A function fits on one page (~60 lines). Longer must be split, or the length
justified.

## R5. Boundary assertions

Functions check their preconditions and postconditions at their boundaries,
with side-effect-free assertions.

## R6. Smallest possible scope

Variables and objects get the smallest scope that works: declared as close to
their use as possible, no gratuitous globals.

## R7. Check all return values

Every return value that can carry an error is checked. Errors and exceptions
are never silently swallowed.

## R8. Limit hidden control flow

Macros, metaprogramming and reflection tricks that hide control flow are
limited to what plainly earns their cost.

## R9. Limit indirection depth

Chains of pointers, references or dynamic dispatch are limited to what keeps
the code traceable — deep indirection obscures what actually runs.

## R10. Zero warnings, clean analysis

Build with all warnings enabled: zero warnings. Linter and static analysis
come out clean — or every remaining report is justified.

## Deviation protocol

1. Mark the deviation inline in the code:
   `// RULE-DEVIATION: R<n> - <short reason>` (in the language's own comment syntax).
2. List each deviation in the final report / commit message: rule id,
   location, reason.
3. The review step (or the user) evaluates each justification: **accepted** →
   logged as-is; **refused** → a blocking (major) finding, must be fixed
   before the task is considered done.

## Project rules

<!-- Add your project's own safety rules here, one subsection per rule, same
     style as the ones above. Delete this comment as you fill them in. -->

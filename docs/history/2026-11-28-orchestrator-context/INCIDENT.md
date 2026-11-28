# Incident 2026-11-28 — one review subagent filled its context; silent mid-mission compaction

> Source: adopter incident, relayed to the kit owner and restated here as ground truth (the owner's corrected reading, in the brief of the second deep review, `deep-proposal2b-review-brief.md`, "The corrected incident"). The meter readings are the adopter's session meter, not a file in this repo. Reported 2026-11-28.

## 1. What happened (corrected reading)

- The orchestrator's session had 28 dispatches in total: 21 fresh dispatches, 5 of them the dead silent returns (see `../2026-11-28-empty-returns/`), plus 7 resumed fix rounds = 28.
- "Subagent(21 of 21)" is the **21st FRESH subagent** of that session. It is not one instance resumed 21 times. The earlier hypothesis (one resumed instance) is retracted.
- That ONE fresh review dispatch filled its **own** 1M-token context window to 98% within a single mission. Meter readings over its lifetime:

  | Reading | Tokens | Share of window | Cost |
  |---|---|---|---|
  | 1 | 730.7K | 70% | |
  | 2 | 868.6K | 83% | $1.06 |
  | 3 | 920.8K | 88% | |
  | 4 | 983.6K | 94% | $1.41 |
  | 5 | 1.0M | 96% | $1.45 |
  | 6 | 1.0M | 98% | $1.52 |

- The harness then auto-compacted that subagent **silently**, mid-mission ("just before the end"). The subagent's final return **never mentioned the compaction**. The return looked complete and was amnesic: frozen decisions, attempt-id echo and liveness state could all have been lost without any signal.
- The orchestrator misread the meter twice: first as its own thread, then as instance reuse, before the adopter forced the correct reading.

## 2. Root cause

The orchestrator's review BRIEF imposed unbounded re-verification: a full `run all` (23 gates, full output), 10 mutants, the design doc (854 lines), 22 companion files, sources and diffs. Every command output stacked in the **subagent's** context. One review dispatch had enough work to fill a 1M window by itself. No clause in the kit bounded what a reviewer re-runs or reads, and no clause said what to do with a return from a session that was compacted.

The fix for the brief is the Verification bound clause in SKILL.md §7 ("Reviews"), with the reviewer-side lines in `roster/fragments/review-checklist.md`.

## 3. Co-finding: orchestrator hygiene

Orchestrator-side evidence, same session:

- 28 dispatches, **zero handovers**: the orchestrator session ran to its end without a fresh session and a complete brief.
- Verbatim subagent returns (1-5K tokens each) pasted into the ledger. The ledger held a second copy of the proof, and the summary step had more to squeeze.
- One `/compact` proposal in the whole session, and none after it.

## 4. Why the compaction was dangerous, not the size

A dead subagent shows `completed` with an empty payload. A silently compacted subagent shows a normal-looking, complete-looking return. Size alone did not cause the damage; the silence did. Remedies therefore need detection (a compacted or over-cap return is **suspect**) and reconciliation after any compaction, not only a size cap.

## 5. Recorded outcome

The kit changes that answer this incident are in the `## [Unreleased]` entry of `CHANGELOG.md`: review-brief re-verification bound, suspect-return rule, closed-boundary compaction with the configured dispatch threshold, post-compaction reconciliation, and digest ledger. The two deep-review passes that shaped them are archived alongside this file:

- `DEEP-REVIEW-1.md`: pass 1, made on the retracted reading (see its header).
- `DEEP-REVIEW-2.md`: pass 2, made on the corrected reading.

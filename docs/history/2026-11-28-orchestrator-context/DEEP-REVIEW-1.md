> **PASS 1 — made on a since-retracted reading of the incident** (the reading that one instance was resumed 21 times). Its orchestrator-hygiene modifications stand; its Q1 incident analysis does not. See `INCIDENT.md`.
>
> Source: deep review #1 of Kit Patch Proposal #2 (orchestrator context cap), verbatim copy of the temp report `deep-proposal2-review-REPORT.md`; 2026-11-28.

# Deep review: Kit Patch Proposal #2 (orchestrator context cap)

Sources read: SKILL.md (106 lines, all of §1, §6–§9), the INPROGRESS template's "Delegations" section, the hooks in `plugin/dwk-usage.js`, and the join in `dwk/stats.mjs`. I did not edit any file.

---

**Q1. Diagnosis.** The $1.52 total means money is not what went wrong. At cached-orchestrator pricing, 1.0M tokens over 21 dispatches is cheap. The real damage is (a) quality drift and (b) a less faithful ledger.
- **Quality drift:** a harness auto-compact drops working memory without saying so. Frozen decisions, attempt ids and the late-writer liveness state can all disappear.
- **Ledger fidelity:** the ledger was bloated with verbatim returns, so the summary step had more to squeeze and less signal to keep.

**Yes, this hides itself the same way the dead-sessions incidents did.** A dead subagent shows `completed` with an empty payload. Here, the session simply continues after a compact, with no error and a truncated memory. The orchestrator does not know what it forgot. So the main risk is the silent compact, not the size of the session. Any fix has to make the compact **detectable** and require **reconciliation after it**. A cap on its own is not enough.

**Q2. P-1 boundaries.** The orchestrator cannot read its own token meter, so a rule based on "~100K tokens" can't be checked. These signals can be checked:
1. **Wave closed and committed.** The commit gate from §6/§8 has passed.
2. **Delegations-line count since the last fresh session.** This is the ledger's own count, which is already countable.
3. **The harness compaction event itself.** It can be observed after the fact.

**There is a conflict with the current §7.** Today §7 allows /compact only at "phase done and committed" and "never mid-refactor". A wave inside a phase is mid-phase, and "~10 dispatches" can land in the middle of a fix round.

Proposed single text for the two rules:
> "Suggest /compact at a **closed boundary**: a wave or phase committed (§6 gate passed), or a different subject starting. Never with a dispatch in flight, an unpersisted return, or a fix round open. When the dispatch count crosses the threshold, the next closed boundary is where you compact. The threshold moves the compact forward to that boundary; it never authorizes compacting mid-round."

Since commit is the boundary, this keeps "never mid-debug".

**Q3. The persistence duty.**
- **"Consequential" is not decidable as written.** It can be made decidable: *"a return is consequential if it changes the worktree, carries a measured number or a review verdict, or closes or opens a finding."* In practice that covers every implementation and review return. So the simpler rule is better: **persist every return to the ledger before the next act, always.** That way persistence doesn't depend on detecting pressure, which nobody can do reliably because the compaction is silent. A duty that only triggers on pressure is useless when the pressure can't be seen.
- **"BEFORE any other act" is the right order, with one exception.** It fits the existing rule "persist before treating the completion as acceptance" (§1). The exception is an in-flight parallel wave: persisting one return must not wait on siblings. It must also never be read as the late-writer guard's termination check. The rule should say: *"persist each return when it arrives; the late-writer guard still applies independently."*

**Q4. P-2 digest instead of verbatim.**
- **§3 (proof):** no collision, provided proof stays in the artifacts. §3 already says a number has one home, the artifact that produced it. A verbatim return pasted into the ledger was a **second** home, which itself goes against §3. The digest must reference proof by path or commit, never restate it unsourced.
- **§8 (staging gate):** there is a collision unless the digest always keeps the **file list**. The staging gate compares `git show --stat` against the reported file list, file by file. If the list isn't in the digest, the post-compact gate has nothing to compare against.
- **Minimum digest content:**
  1. attempt-id echo
  2. status (done / partial / empty-recovery)
  3. file list, complete
  4. numbers with their artifact path (test totals and their command)
  5. findings, by id plus `file:line`
  6. the `task_id`
- **"Never verbatim" is too absolute.** A return of three lines or fewer is its own digest. Use: *"digest, not verbatim (a return of ≤3 lines may be kept as-is)"*.

**Q5. Where the "~10 dispatches" trigger belongs (§9).** Per §9, this is a mechanical trigger and should live in tooling, not prose.
- **Plugin side:** `dwk-usage.js` already subscribes to session events (`session.updated`, `message.updated`). It can count child sessions per parent and log or warn when the threshold is crossed. It can also record the harness compaction event (opencode emits a session-compacted event; verify the exact name) as a ledger-visible marker.
- **Prose side:** the prose keeps only the judgement half: *what you do at the boundary* (where you may compact and what to reconcile). The number belongs in `dev-workflow.json` config, not in SKILL.md.

**Q6. Reconciliation after a compact.** The current rule ("Resume = reconciliation, not trust", §1) covers this **in spirit only**. It is worded for resuming a task, and the orchestrator won't see a silent mid-session compact as a resume. Add one line, in §7 next to the compaction rule:
> "After any compaction, yours or the harness's, treat the session as a resume: re-read the ledger, run §1 reconciliation against git, and confirm the liveness of every open attempt before the next dispatch."

This is the counterpart of the dead-sessions "never trust completed" rule, and it is the most valuable line in this review.

**Q7. What the proposal misses (two additions).**
1. **The handover brief = the ledger.** No new format is needed. The fresh orchestrator session's brief is the active `INPROGRESS.md` task, which already holds the Delegations digests and the wave header with the lane. Saying so prevents a new "handover document" type from being invented.
2. **Make the compaction detectable** (the plugin marker from Q5). Without it, Q6's rule depends on the orchestrator noticing something it cannot notice.

I rejected the candidate rule "returns beyond N tokens become report files". It duplicates what a digest plus on-disk artifacts already provide, and it reintroduces the "report-file bureaucracy" that §1 rules out.

**Q8. The fold.**
- **Sites:** P-1 → §7 and P-2 → §1 are the right places. The changes are line-level edits to existing bullets (the §7 boundary bullet, the §7 cap bullet, the §1 ledger bullet) plus one new §7 line. That is within the "two changes" spirit.
- **Contradictions with v0.9.3:** none, provided:
  - the persistence wording reuses the existing "persist before acceptance" sentence instead of adding a second persistence rule;
  - the digest keeps the attempt-id echo, which the §7 abnormal-return check depends on.
- **Template:** the "Delegations" comment in the INPROGRESS template should be updated to name the digest fields (this is the P-2 acceptance item).
- **Timing:** this touches the same lines v0.9.3 just touched. Ship it as v0.9.4 with its own history dossier rather than amending v0.9.3.

---

## Verdict: adopt with modifications

1. **§7 boundary bullet:** replace it with the "closed boundary" text from Q2. Dispatch count only moves the compact forward to the next committed wave or phase; never mid-round, never with a dispatch in flight or an unpersisted return.
2. **§7 cap bullet:** extend it to the orchestrator using signals that can be checked (committed wave/phase, dispatch count from config), not token counts.
3. **§7, one new line:** "After any compaction (yours or the harness's), treat the session as a resume: re-read the ledger, run §1 reconciliation against git, confirm liveness of open attempts before the next dispatch." A fresh orchestrator session's brief is the active INPROGRESS task.
4. **§1 ledger bullet:** replace "persist on a pressure signal" with "persist every return when it arrives, before the next act; the late-writer guard applies independently." Add "Ledger = digest, not verbatim: attempt-id echo, status, full file list, numbers with their artifact path, finding ids with `file:line`, `task_id`; a return of ≤3 lines is its own digest." Mirror the field list in the INPROGRESS template's "Delegations" comment.
5. **Tooling, not prose (§9):** the dispatch threshold goes in `dev-workflow.json`. `dwk-usage.js` warns when it is crossed and records harness compaction events as a ledger-visible marker.

Drop from the proposal: the "consequential" qualifier and the bare "~10" number in prose.

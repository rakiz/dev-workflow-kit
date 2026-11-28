> **PASS 2 — made on the corrected incident reading** (`INCIDENT.md`). Its review of the amended proposal is the basis of the Unreleased changes.
>
> Source: deep review #2 of the amended Kit Patch Proposal #2, verbatim copy of the temp report `deep-proposal2b-review-REPORT.md`; 2026-11-28.

# Deep review, second pass: Proposal #2 (amended)

I read SKILL.md §1, §6, §7 and §9, `roster/fragments/review-checklist.md`, and my prior DEEP-REVIEW.md. I edited no files. My earlier hygiene modifications stand as the owner accepted them.

---

## Q1: Where "verifies" ends and "re-derives" begins

**Verdict: the bound doesn't contradict §6 or §7. Both already describe a bounded act, and the incident went past them.**

- §6 asks for one thing: totals claimed in a commit message must be reproducible. That means one run of the suite against the commit, with the result compared to the claim. It doesn't ask for the full output in context, mutation runs, or rereading the design doc and 22 companions.
- §7:82 has the orchestrator hand over the raw evidence verbatim. The reviewer receives the evidence; it doesn't regenerate all of it.
- The line, then: **re-running a command is verification only when its result settles a specific claim in the artifact.** Anything else rebuilds context the brief should have supplied. That covers mutants, full doc rereads and reading sources outside the diff.
- On the three candidate bounds:
  - "Once per suite" is right.
  - "Diff-touched scope" is right for reading.
  - An output budget is right too, and the mechanism is a file (see Q7). Counting tokens isn't something a model can do reliably.

**Proposed clause** (§7, Reviews bullet, appended):
> "The review brief bounds re-verification: the reviewer re-runs each claimed total ONCE against the commit, with the output redirected to a file and only the summary and failures read. Reading is limited to the diff, the files it touches and the contract. Extra checks (mutants, re-reading designs or sources outside the diff) need a stated suspicion named in the finding. The reviewer checks claims; it does not rebuild the context."

## Q2: Where the bound lives

**Verdict: in two places.**

1. **The checklist fragment.** This is the reviewer-side behaviour: re-run once, redirect to a file, stay in diff scope. It's one splice, it reaches all 5 review rungs, and it's generated, so it can't drift.
2. **The §7 Reviews bullet.** One clause makes the orchestrator write the bounds into the brief, since only the orchestrator knows which gates apply to this wave.

SKILL.md prose alone doesn't work, because reviewers don't read SKILL.md; the fragment is the surface they actually see. On §9, a token or output cap isn't something tooling can enforce on a model's reads today. Redirecting output to a file, though, is mechanical and a script can check it (see Q6). So this is still within the two-changes spirit: one behavioural rule, written at its two required ends.

## Q3: Can a subagent detect its own compaction?

**Verdict: not reliably from inside. Put the duty on the orchestrator, and tie it to the plugin.**

- A compacted model sees a summary where its history used to be. Some harnesses insert a marker; opencode's compaction summary may or may not be recognisable to the model. "Declare it if you know" is unenforceable. A model that doesn't know will simply answer "no", which is worse than no echo, because it buys false confidence.
- The facts sit on the outside. `plugin/dwk-usage.js` already counts tokens per task, and the meter showed 730K→1.0M. Any context drop between two consecutive messages of one child session is also a decidable compaction signal.

**Enforceable form:**
- The plugin records, per child session:
  - peak context;
  - whether compaction happened (detected as a context drop, or from the harness compaction event if the plugin API exposes one — that needs verifying);
  - the count of threshold crossings above ~100K, the existing cap.
- It writes these to the usage record that `dwk/stats.mjs` already parses.
- The orchestrator reads that record before accepting a return.
- Keep the in-prompt echo only as a soft extra: "if your context contains a compaction summary, say `compacted: yes`". It should never be the gate.

## Q4: Does the v0.9.3 §7 table cover a compacted return that looks complete?

**Verdict: no.** The table fires on empty, evidence-free or zero-write returns from implementation dispatches, and it explicitly excludes read-only reviews. This incident was a review that returned plausibly, so it slips through on both counts.

**Minimal addition** (one line under the table, not a new row set):
> "A return from a session flagged compacted or over the context cap (plugin record) is **suspect**: its verdict is not accepted. Re-dispatch the review fresh with a narrower brief per the review-bound clause. Do not resume it: the resumed instance is the amnesic one."

That reuses the existing rule against re-dispatching the same brief shape unchanged, because the brief must narrow. It covers implementations too, where the existing table already applies: a compacted implementer gets the same worktree check and one resume-for-facts.

## Q5: P-3 re-scoped

**Verdict: it survives unchanged, with one amendment.**

The closed boundaries, persist-every-return, digest ledger, post-compaction reconciliation and plugin counter all stand on the orchestrator-side evidence: 28 dispatches, one /compact proposal, and a verbatim ledger.

The amendment: the plugin counter now has two jobs. It tracks orchestrator boundaries (P-3) and flags children (Q3). Specify it once with both outputs, so it isn't built twice. Also drop any wording that blames the incident on the orchestrator's context. The root cause was the review brief; P-3 is a co-finding.

## Q6: The fold

**Verdict: three prose sites plus one tooling change. It warrants its own small campaign, v0.9.4 with its own dossier**, because the incident correction must be recorded and the existing empty-returns dossier rests on the retracted reading.

| Site | Change | Acceptance check (decidable) |
|---|---|---|
| Checklist fragment | Re-run once, output to a file, diff scope, extras need a stated suspicion | `roster/build.sh` output contains the clause in all 5 review prompts (grep in the existing build test) |
| §7 Reviews bullet | The orchestrator writes the bounds into the brief | Over the next N review briefs in the ledger, each names the gates to re-run and the file scope; checked by stats.mjs or by sampling |
| §7 table (one line) | Flagged or compacted return is suspect; fresh narrower re-dispatch | Over the next N dispatches, every plugin-flagged child has a ledger line showing re-dispatch, not acceptance |
| Plugin and stats | Per-child peak context and compaction flag | Unit test: a synthetic session with a context drop yields `compacted: true` |

- §1 doesn't need touching. The execution-first bullet stays implementation-only, and the review bound lives in §7, where reviews already live.
- Agent prompts need nothing beyond the generated splice.
- The P-2 echo shouldn't become a hard return-contract field, since the plugin check is what can be enforced.
- None of these checks can be gamed by wording, because each one is checked against the ledger or plugin data.

## Q7: What is still missed (two)

1. **Long command output belongs in a file, referenced by path, kit-wide.** This was the single largest thing filling the window: the full `run all` dump. The rule is one home per §3: logs go to `$TMP/…log`, and context gets a tail or grep. It belongs in the fragment (reviewers) and in the execution-first bullet (implementers, one phrase). This is the mechanical half of P-1, and probably worth more than the rest of it.
2. **23 gates in a review wave is a project smell, not a kit bug.** The kit shouldn't legislate gate counts. It should make the review re-run the gates relevant to the claim, and treat the full `run all` as the pre-commit hook's job, which runs it anyway. That's one phrase in the §7 clause: "the hook owns the full gate run; the reviewer re-runs only the claimed totals." Mutants stay a design-step artifact, never a review chore.

---

## Verdict

**Adopt with modifications**, as v0.9.4 with its own history dossier that records the corrected incident.

1. **P-1:** the bound lives in the review-checklist fragment and in one §7 Reviews clause (Q1 wording). The full gate run is left to the hook, and output is redirected to a file with only the summary read.
2. **P-2:** replace "the subagent must declare it" with a **plugin-side detector** (per-child peak context and compaction flag in the usage record). Keep the in-prompt `compacted:` echo only as a soft extra, never the gate.
3. **New, one line in the §7 table:** a flagged return is suspect, gets a fresh narrower re-dispatch and is never resumed. It covers reviews too.
4. **P-3:** unchanged from the accepted modifications. The plugin counter is specified once and serves both P-3 and the child flag.
5. **Add:** a file-not-context rule for long command output, at both reviewer and implementer ends.
6. **Acceptance checks:** use the Q6 table checks (ledger, build and plugin based), not template-text checks.

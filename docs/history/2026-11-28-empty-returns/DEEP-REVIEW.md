# Deep design review — incident proposals P-A..P-D

> Source: deep review of the adopter incident proposals, verbatim copy of the temp report `deep-proposal-review-REPORT.md`; 2026-11-28. Outcome: adopt with modifications, applied in the Unreleased batch after 0.9.2 (CHANGELOG).

# Deep design review: incident proposals P-A..P-D

I read `SKILL.md` (all of it) and `roster/MODELS.md` §"Escalation semantics" (lines 291–307) plus the variant section after it. I edited no files.

**One finding the disposition misses.** `SKILL.md:21` already says: *"After the §7 recovery check, one empty or stalled return on a rigorous unit escalates the rung — scope-halving is not a substitute for the ladder."* That rule produced dispatch 3.4. The incident is evidence against it, at least in its current unconditional form. The disposition edits §7 but leaves `:21` as it is, so the two sites would contradict each other. Any adoption has to amend `:21`.

---

## Q1 — Is v3 (budget exhaustion via verify-before-write) the best explanation?

**Verdict: mostly yes.** It is a strong partial explanation, but the evidence doesn't separate it from one competing hypothesis.

- **What fits.** All the failed sessions had verification-heavy briefs. The tiny 3.10 probe (no verification demanded) succeeded. Resumes succeeded 2/2, because the context was already loaded and the ask was small. The six execution-first dispatches succeeded 6/6. Session 3.11 says in its own words that it never issued a write call. The wave-3a controls are consistent too, *if* their briefs were less verification-heavy. That isn't shown. The report says "comparable brief sizes", and size is not the variable v3 claims matters.
- **Alternative H2: reasoning-token exhaustion.** strong-code is minimax at `xhigh` (the roster's variant convention: `MODELS.md` ~309–330). On a hard geometry and instruction-level design problem, a high-effort model can spend its whole output or turn budget *thinking* without making tool calls. Session 3.8's own diagnosis says exactly this: "in reasoning, not in files… reasoning volume ≫ output". Session 3.9 is the key case: the settled plan was inlined and it was told not to re-deliberate, yet it still died. That is weak support for v3's "mandated reading" mechanism and good support for H2. The fix that worked confounds the two, because it changed brief shape *and* moved to a lower-effort rung on a different family at the same time.
- **Alternative H3: claude's 3.4 died for a different reason.** It was a fresh, large brief carrying salvaged notes. That fits v3's ingest-cost story, but it is a single data point.
- **What would distinguish them.** Re-run 3.9's brief on strong-code at `variant: high`/`low`, keeping the brief unchanged. If it survives, the cause is H2 (effort or reasoning budget), not brief shape. Alternatively, give an execution-first brief to strong-code at `xhigh`. Harness telemetry (output and reasoning tokens per turn, tool-call count) would settle it without re-runs.
- **Implication.** The rule should name the observable signature ("budget exhausted before the first write"), not one mechanism, and should name both levers: brief shape, and rung/effort.

## Q2 — P-A: does "first tool call must be a WRITE" collide with §3 or the design step?

**Verdict: as worded, it collides. The conflict is resolvable by wording.**

- **Collision with §3.** "First tool call is a WRITE" literally forbids reading the file you are about to edit. It invites blind writes, and §3 says nothing is true without proof. The design step (§1:19) is orchestrator-side, so that part does not collide. But for rigorous units, the "strong at design time" exception (§1:21) assumes the strong rung does verification work.
- **The resolution:**
  - The design and its verification belong *upstream*: in a design step or a separate verify-only dispatch whose deliverable is a written artifact.
  - An implementation dispatch receives settled facts, not open questions.
  - "Write first" becomes "write early, verify by execution after the write".
- **The acceptance check is badly formed.** "First write before the third read":
  - It is gameable: a stub or placeholder write satisfies it.
  - It is hard to measure without transcripts, which the kit does not collect.
  - It is mis-targeted: it tests the agent, but the defect is in the brief the orchestrator writes.
- **Better acceptance check, measured on the brief and the ledger:**
  - The brief contains no open verification task and names at most N files to read.
  - The ledger shows zero empty returns across the next M implementation dispatches.
- **Proposed wording (§1, Delegate bullet):**
  > **Implementation briefs are execution-first**: settled facts are inlined, never pointed at for re-derivation; open verification belongs to the design step or a separate verify-only dispatch whose deliverable is a written file; mandated reading is limited to the files the dispatch edits; the brief orders the writes and verifies by execution after each (write → build/test → fix). A brief that asks the implementer to re-establish what the design settled is a design brief and is routed as one.

## Q3 — P-B: is the downward reroute consistent with the ladder? Is "ONE resume" right?

**Verdict: the reroute needs an explicit clause, and `:21` must be amended.**

- **Consistent with MODELS.md in spirit.** That text governs only when rung N+1 is invoked. It does not forbid moving work down once the reason for the strong rung (designing the contract) has been satisfied.
- **Contradicts `SKILL.md:21` directly.** That line mandates escalation after one empty return on a rigorous unit.
- **Clause to add to `:21`:**
  > …escalates the rung — **unless the §7 recovery produced a complete design: the rigorous design-time exception is then discharged, and the remaining transcription goes to the standard implementer with an execution-first brief.**

  Two guards:
  - Review stays at the rigorous lane's budget.
  - The reviewer's family must differ from the new producer's (claude cheap-code means the reviewer must not be claude).
- **"ONE resume-for-facts".** The evidence (2/2) supports one resume as the default, not as a proven upper bound. Word it as "at most one resume; a resume that itself returns empty counts as no salvage → branch (ii)". That bounds the cost and stays honest about the sample size.
- **Correctness check on "complete design".** A "complete design" recovered from a resume is a claim, and §3 applies to it. The orchestrator verifies it, or has it reviewed, before handing it to a transcriber. Session 3.11's trap list was not tested, and the cheap rung will transcribe whatever errors it contains.

## Q4 — P-C: is "never re-dispatch unchanged" safe as a hard rule?

**Verdict: safe, if it is scoped.**

- **The one case where an unchanged re-dispatch is right:** the harness itself is proven at fault (for example, a probe like 3.10 fails, or there is an outage or a timeout). Then the brief is not the variable, and changing it would muddy the diagnosis.
- **Wording:**
  > Never re-dispatch the same brief to the same rung unchanged unless a harness fault is shown independently.
- **Drop "= budget exhaustion".** Under Q1, that is a hypothesis, not an identity. Use "presumed budget exhaustion, not a lost report, until the worktree and resume show otherwise." That fits §3.
- **Note on the evidence.** Strictly, 3.9 was not "unchanged": a plan was inlined. It was unchanged in *shape*, though, which supports making the rule about the shape and the rung, not the bytes.

## Q5 — P-D: should the attempt-id echo check be a prose rule?

**Verdict: no new prose rule.**

- **It already exists.** §1:31 already requires the worker to echo the attempt id.
- **Where it belongs (§9: mechanical checks go to tooling, not new prose):**
  - **Agent prompts** (`workflow/agent/impl.md`, `deep.md`, and the global `*-code.md`): "your final message begins with `attempt <id>:`; an empty final message is forbidden; if you are running out of budget, emit the partial report now."
  - **Optionally, a harness or plugin check** that flags a completion without the echo.
- **Do not add a §1 clause.** At most, add four words to the new §7 detection line: "(no attempt-id echo)".

## Q6 — Does the two-site fold lose anything? Is anything better placed elsewhere?

**Verdict: the fold is sound, with three gaps.**

1. It misses the `:21` contradiction (Q3). That makes `:21` a de facto third edit, but it is the same rule family as the §7 edit, so it can be treated as one change.
2. The rescue-brief anti-pattern is lost: *rescue briefs must shrink, not grow* (salvaged notes go in as settled facts, warnings come out). That is the cheapest insight in the report. Add it to the P-A wording.
3. Placement:
   - The agent-side half of P-A belongs in the impl and strong-code prompts: write early, never end silently, emit a partial report before the budget runs out.
   - The orchestrator-side half stays in SKILL.md.
   - P-D goes in the prompts only.
   - Nothing needs to go in the INPROGRESS template.

## Q7 — What do the proposals miss?

**Verdict: two additions, in this order.**

1. **A forced-checkpoint stop rule in the implementer prompts (cheapest, highest yield):** "if you have made K tool calls (for example 15) without a write, stop and return a factual report of what you established." This turns a silent death into a salvageable return. It fixes detection, the resume cost and the masking, whichever of H1 or H2 is the cause. It is more robust than brief discipline, which depends on the orchestrator remembering it.
2. **Effort as a lever (covers H2):** when a strong rung returns empty and its recovery shows deliberation was the problem, a re-dispatch may lower `variant` before changing the rung. This needs a one-line MODELS.md note, and it needs evidence from the Q1 test first. Until then, record it as an open question, not a rule.

Telemetry-based budget monitoring is better, but it depends on the harness and is outside the kit's control.

## Q8 — Is a §8 guard line enough for the amend/ledger loss?

**Verdict: the prose line alone is weak. Prefer a mechanical check, after the investigation.**

- §8:91 already forbids silent amends. A "re-verify the ledger" line is the kind of rule §9 says becomes tooling.
- **Cheap mechanical option:** a hook builtin that fails when the staged or worktree `INPROGRESS.md` is shorter than the `HEAD` copy by more than X lines, without an explicit marker for a task-close reset.
- **Order:** investigate the root cause first. Implementation agents may have run git (forbidden by §8:89), or an editor or agent may have rewritten the file concurrently. Run the investigation the disposition offers before adding any rule, because a hook keyed on the wrong cause is noise.
- **Not folded into this batch.** That keeps the §9 limit of two changes.

---

## Verdict

**Adopt with modifications.**

1. **Site 1 (§1, Delegate bullet):** replace "first tool call is a WRITE" with the Q2 wording: verification upstream or in a verify-only dispatch, settled facts inlined, rescue briefs shrink, writes ordered and verified by execution. Change the acceptance check to brief- and ledger-based (no open verification in implementation briefs; zero empty returns over the next M dispatches).
2. **Site 2 (§7 empty-report bullet plus the `:21` clause):**
   - At most one resume-for-facts. A resume that returns empty counts as no salvage.
   - The recovered design is verified per §3, then rerouted to the standard implementer, with a family-distinct reviewer and the rigorous review budget kept.
   - Otherwise escalate.
   - Amend `:21` explicitly so the reroute is legal.
   - The signature is "presumed budget exhaustion".
   - Never re-dispatch the same brief shape to the same rung unless a harness fault is shown independently.
3. **P-D:** move it to the implementer agent prompts (mandatory `attempt <id>:` prefix, no empty final message), with no new §1 prose. Pair it with the Q7 #1 checkpoint stop rule in the same prompt edit.
4. **CHANGELOG and archive:** archive as proposed. Record H2 (reasoning effort) as an open alternative that the fix does not separate from v3, with the distinguishing experiment.
5. **P.S.:** no prose now. Investigate first, then consider a mechanical "INPROGRESS.md never shrinks outside a task-close reset" hook check.

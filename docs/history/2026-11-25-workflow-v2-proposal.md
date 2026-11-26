# Workflow v2 — proposal

Status: PROPOSAL, nothing implemented. Written 2026-11-25 against kit commit `1b5de26`.
Companion contract: [AUTONOMOUS-RUN.md](AUTONOMOUS-RUN.md) (untracked draft of today; this
proposal references its sections and does not restate them).

## 0. Goal and scope

**Goal (verifiable):** an owner can hand over a bounded task and receive either a
committed, reviewed end-state or a documented stop, with a delegation-inclusive cost
ledger, without answering more than one consolidated question per wave.

**Scope:** the v1 pipeline (`workflow/`, `roster/`, `init.sh`, README) and the cross-project
ad-hoc case (G6). Out of scope: changing the model roster itself (owner-gated per
AUTONOMOUS-RUN §4) and the eval campaigns.

## 1. What v1 gets right (keep)

| Strength | Where it lives |
|---|---|
| File-based memory; resume = reconciliation against git | SKILL.md:19-23 |
| Cross-family review at commit; reviewer family differs from producer | SKILL.md:78; MODELS.md:91-98, 330-335 |
| Design review for architectural tasks before code | SKILL.md:27 |
| Escalation ladder: rung N+1 only after N failed / stalled / doubted | MODELS.md:252-256; SKILL.md:27 |
| Batch-questions rule at design time | SKILL.md:31 |
| Briefing presented, not gated; internal choices decided by the orchestrator | SKILL.md:30 |
| Wave-based implementation, each wave committable | SKILL.md:30 |
| Permission rails: subagents hard-deny push | README.md:68; global-agent frontmatter (e.g. cheap-code.md) |

## 2. Measured evidence (what v2 must fix)

Store checks run today against `~/.local/share/opencode/opencode.db` (53 GB):

| Claim | Status |
|---|---|
| 1,628 top-level sessions, 2,847 child sessions (`session.parent_id`, live store; the earlier 2,845 was stale) | VERIFIED (sqlite count) |
| Total spend $1,998; children $1,097 = 55% | VERIFIED (sum of `message.data.cost` rolled up by parent) |
| Top 10 sessions = 49% of spend; 120 ended on an unanswered owner message; 17 "reprise" sessions = $208 | owner-reported, NOT re-verified here |
| A metadata-review session $0.35 parent -> $5.65 with children (16x); an unmanaged solo project session $1.95 -> $23.79, one opus child $8.93 | owner-reported, consistent with AUTONOMOUS-RUN.md §5 |
| maxfill: probe->launch->monitor for 10 arms; 15-min wall watchdog killed a self-repairing arm | AUTONOMOUS-RUN.md §5 journal |
| maxfill = $0.45 for 10 arms (2 watchdog timeouts: DR2 @900s, D @1800s — the D arm never finished within 30 min, a real slow-at-max signal) | `evals/maxfill-2026-11-25.status.txt` (untracked): final line `# done spent=0.4466` (the `spent=` values are a running total, not per-arm; last value = campaign total); arm 008 DR2 and arm 010 D are `timeout`. The earlier "$0.34 for 9 arms" and "$2.64" readings are withdrawn: summing the cumulative values was a misreading |

Owner-reported, not re-verified: the "23 sessions >5x parent cost" and "6 sessions >15x"
figures. A plain children/parent cost ratio over the store does not reproduce them, so
their definition (which cost, which roll-up) is unknown. Do not use them as a baseline
until the owner states the definition.

The waste concentrates where v1 has no coverage: ad-hoc work (no `.opencode/skill/`,
no ledger, no batching) and long, unbounded delegation trees.

## 3. Gaps and changes

Each gap: evidence, the v2 change, the file it lives in.

### G1 — no cost dimension (budget, caps, ledger)

- **Evidence:** the delegation ledger has 8 fields and none is cost (SKILL.md:34-35). No
  budget or cap appears in the skill, the templates, or any agent. Children were 55% of
  spend and invisible (verified above). An unmanaged solo project session's single uncapped opus child cost $8.93.
- **v2 change:**
  1. Task-level line in INPROGRESS.md: `budget: $B total, $C per child, max children: M |
     spent (parent + all children): $S | children: N`. Refreshed at every wave report.
     Max-children stop rule: the (M+1)-th delegation is refused; the orchestrator records
     the refusal and asks or escalates. Motivation: an unmanaged solo project session ran 31 children
     (AUTONOMOUS-RUN.md §5). Proposed default M = 10, owner to tune (D3).
  2. Ledger line gains two fields: `cap $c | spent $s`. Format:
     `- <attempt> | <step> | <role> | <files> | <artifact id> | <task_id> | <status> | <return> | cap $c | spent $s`.
     Who and when: the orchestrator writes the line BEFORE dispatch with `spent $0`, and
     APPENDS the spent value when the child returns (the child never writes it, consistent
     with SKILL.md:34-36). The value is read from the store for that child's `task_id`
     subtree, not estimated from the child's own report.
  3. Cost enforcement, autonomous profile only. opencode 1.19.6 (`opencode --version`,
     verified) has no per-session cost cap in its CLI surface (`opencode --help` lists
     `stats` and `export`, no cap flag; owner-reported that no cap exists). The enforceable
     mechanism is a **store-poller**, the same fail-closed pattern as the eval runner
     (`evals/run-eval-v4.sh:14-20`, `:50`; `run-eval-v6.sh:7-12`, `:70`): a background
     process reads the store every N minutes (proposed N = 5, as in the runner), sums cost
     over the session tree via `session.parent_id`, and TERMs a child whose subtree cost
     exceeds its cap (same kill path as the eval runner's `kill_arm`, `run-eval-v4.sh:123`).
     Overshoot is bounded by one poll interval plus the child's in-flight call.
     Fail-closed rules: (a) the poller refuses to start without an explicit cap; (b) the
     cost reader is pinned to the 1.19.6 schema (`message.data` JSON `cost`, the query
     verified above; the schema is undocumented internal and may change); (c) if a session
     known to have children (`parent_id` rows exist) reads $0 cost, or the query errors, the
     run aborts and reports it (the failure mode is an uncapped run, not a silent one).
     **Fallback without the poller:** the cap degrades to "stop at the next checkpoint":
     the orchestrator reads the store at each wave report and stops before dispatching the
     next child. The cap is then advisory at wave granularity, and the report must say so.
  4. Per-child cap stated in every delegation brief. Proposed default **$2 per child**
     (AUTONOMOUS-RUN.md §7 item 4 uses ~$2 for one bounded escalation). Session default
     is per-brief, no default in the kit (owner decision D3).
  5. Cap hit (poller kill or checkpoint stop): record a DNF with the spend in the ledger,
     then escalate or ask. Never silent continuation.
- **Files:** `workflow/skill/dev-workflow/SKILL.md` (§1 ledger, §6 wave report);
  `workflow/templates/INPROGRESS.md` (budget line + ledger format); the brief template
  in AUTONOMOUS-RUN.md §1 (caps, already listed there).

### G2 — evidence-first only at commit time

- **Evidence:** SKILL.md:21 binds acceptance to a hash, and SKILL.md:84 requires
  reproducible totals, but both apply at checkpoints. Nothing requires proof for a claim
  made mid-task. The false state explanation of an unmanaged solo project session was caught only because the owner doubted
  it (AUTONOMOUS-RUN.md §6).
- **v2 change:** a baseline rule (always-on, like SKILL.md:59-64): every state claim
  ("the test passes", "the file exists", "the cause is X") carries inline proof: the command
  and its result, or a `file:line`. An unproven claim is written as an open assumption.
  The reviewer checks for proof, not only correctness.
- **Files:** `workflow/skill/dev-workflow/SKILL.md` (§3, new baseline rule 4);
  `workflow/agent/impl.md`, `workflow/agent/review.md` (one line each); mirrored in
  `roster/global-agent/cheap-code.md` and `cheap-review.md`.

### G3 — commit/push gated per action (no autonomous profile)

- **Evidence:** SKILL.md:88 "it never commits autonomously"; README.md:76-77 recommends
  `"*git commit*": "ask"` at the orchestrator. Owner's global rule (AGENTS.md, 2026-11-23)
  allows commits batched within one authorized task, and push needs its OWN authorization
  per push, with no batching.
- **v2 change:** two documented profiles, selected per task brief (not per project):
  - **interactive** (current behavior): commit and push both `ask`.
  - **autonomous**: commit allowed per validated wave (one authorization covers the task's
    waves); push stays `ask`, one authorization per push, always. This is the owner's
    global rule restated, not a relaxation.
  - Push-policy wording: AUTONOMOUS-RUN.md §4 line 63 ("push without asking") CONFLICTS with
    the global push rule. v2 replaces it with "push request pre-drafted; asked once, per
    push" (owner decision D2).
  - The kit documents both opencode blocks: the current one (README.md:71-81) and an
    autonomous variant with `"*git commit*": "allow"` and `"*git push*": "ask"`. The kit
    never writes `opencode.json`; the block stays hand-edited.
- **Files:** `workflow/skill/dev-workflow/SKILL.md` (§6 commit paragraph, profile
  definition); `README.md` (permission section, second block); `AUTONOMOUS-RUN.md` §4 (fix
  line 63).

### G4 — unbounded review loops

- **Evidence:** A metadata-review session reached review round 3, each round finding new defects, and there is
  no end-state definition (AUTONOMOUS-RUN.md §5). SKILL.md:101 requires a fresh reviewer
  per re-review, but sets no round bound.
- **v2 change:** **at most 2 review rounds per wave.** Round 1: review, fix by the same
  implementer instance (its own fix round, SKILL.md:101). Round 2: fresh reviewer on the fix
  delta. If majors remain after round 2: escalate ONE rung (MODELS.md:252-256), or ship
  with findings recorded in INPROGRESS.md as "accepted with findings" (the owner decides at
  the wave report). Never a third round.
- **Files:** `workflow/skill/dev-workflow/SKILL.md` (§6 semantic check, §7 reviews).

### G5 — arbitration batched only at design time

- **Evidence:** SKILL.md:31 batches at design time. Execution-time questions trickled in
  (metadata-review session: "unknown authors?", "65 files without author, arbitrate?"). The v1 rule at
  SKILL.md:30 already lets the orchestrator decide internal choices, but nothing records or
  reviews those decisions.
- **v2 change:**
  1. **Decision log** section in INPROGRESS.md, one line per decision:
     `D-n | decision | default applied | reversibility class | status`.
  2. **Documented defaults:** an ambiguity takes the documented default, is logged, and the
     run continues (AUTONOMOUS-RUN.md §6 row 1).
  3. **One consolidated arbitration list per wave**, in the wave report, reviewed after the
     fact.
  4. **Reversibility gate** (AUTONOMOUS-RUN.md §2): only expensive-to-undo decisions
     (deletion, migration, publication, spend above cap, roster change) are reviewed BEFORE
     acting, and by a different family.
- **Files:** `workflow/templates/INPROGRESS.md` (decision log section);
  `workflow/skill/dev-workflow/SKILL.md` (§1 Scope and batching, plus the gate).

### G6 — no coverage for ad-hoc work outside kit projects

- **Evidence:** the three failing live sessions were not kit-installed projects (owner
  finding; AUTONOMOUS-RUN.md §6). The skill is installed only per project
  (README.md:33; README.md:190-197: `--global` installs agents only, "no skill"). The global
  roster agents have no workflow around them.
- **v2 change:** ship the AUTONOMOUS-RUN.md contract as a **global skill**
  `scratch-workflow`. It carries four mechanisms:
  1. **Brief template:** goal, definition of done, budget (G1), pre-authorizations, human
     gates, decision rules, report contract (AUTONOMOUS-RUN.md §1).
  2. **Per-step objective gates:** every step has a definition of done verified by a
     script (suite green, probe passes, file exists), never by the model's own judgment.
     A step without a gate is not started. This is the countermeasure to the solo-session
     "tu avances pas vite" loop (AUTONOMOUS-RUN.md §6): progress is a scoreboard, not a
     narrative.
  3. **Post-run retro:** the journal discipline (AUTONOMOUS-RUN.md §3, 10 lines max):
     what blocked, what should have been pre-authorized, one-line rule updates proposed,
     appended to the journal. It extends SKILL.md:117-123 ("Optional retro", PROPOSE only,
     at most two changes, each with an owner and a next-task check) to autonomous runs:
     the retro of an autonomous run is mandatory at run end, not optional, and it still
     only proposes; it never edits global instructions.
  4. **Reporting and loop:** the headless pattern, the 2-round review bound (G4), and the
     decision log (G5).
  It is installed into `${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/skills/` (plural).
  On this machine the plural directory exists and the singular does not (verified); the
  owner reports that opencode 1.19.6 reads both, which is not verified here. The installer
  writes to the plural path and treats a pre-existing singular `skill/` copy as legacy
  (warn, do not delete). Agents from the roster are the implementation and review rungs.
  It needs no project files, so it works where v1 is absent.
- **Files (new):** `roster/global-skill/scratch-workflow/SKILL.md`; `init.sh` (new
  global-skill copy path, see §6).

### G7 — pipeline routing not enforced

- **Evidence:** README.md:58 documents the limitation, and gives two manual options (say it
  per session, or add a project `instructions` entry). Nothing in the kit installs either.
- **v2 change:** ship the default line in the kit docs and in the skill, for the owner
  to adopt:
  > Implementation goes through `impl` (or `cheap-code`) then `review` (or `cheap-review`).
  > Do not edit code inline.
  The project variant goes to the project `opencode.json` `instructions` (owner adds it;
  the kit does not write `opencode.json`, README.md:69). The global line goes to the
  owner's AGENTS.md (owner adds it, not the kit).
- **Files:** `README.md` (replace line 58 with the shipped line + the two adoption paths);
  `workflow/skill/dev-workflow/SKILL.md` (routing section already states it, SKILL.md:25-26;
  add the enforcement sentence).

### G8 — long-horizon capability unbenched (v2 PRIORITY, promoted from optional; evidence G11)

- **Evidence:** the benches measure verification discipline on small fixtures; the
  failing sessions are long-horizon (README.md:7). No bench covers the supervisor loop.
- **v2 change (priority):** an autonomy bench: the supervisor loop
  (work -> verify -> review -> commit, caps, escalation) scored on a multi-wave task with
  seeded stalls. Funded now (D5) on the game-A RE slice as its first case. That case runs the
  supervisor loop as it exists at launch; the scratch-workflow skill (G6) is what the bench
  scores later, not a precondition for the first arms. Scored by the existing multi-family
  panel (EVALS.md). Not on the critical path.
  Promoted from optional to v2 priority: the cheap seats are saturated on the current
  benches, and the delivery layer (G11) was never measured. The autonomy bench is the
  measurement for that layer. Cost is still the reason it was optional; the owner accepts it.
  **Relation to the existing protocol:** `evals/PROTOCOL.md` §7 (lines 257-268) already
  mandates a "Smoke A/B" (line 268) for the next campaign, and it measures the ROI of
  models. The autonomy bench measures a different object (the supervisor loop, not the
  model), so it is NOT folded into Smoke A/B. Required protocol amendment: add a new
  pre-registered §7 requirement "Autonomy bench", with its own fixture, scoring axes
  (stall detection, cap adherence, DNF recording) and its own budget line.
- **Files (if approved):** `evals/` new bench spec; `evals/PROTOCOL.md` §7 amendment (above).

### G9 — roster maintenance: a vacated rung stayed mapped

- **Evidence (verified):** commit `1b5de26` deleted the `strong-design-review-alternative2`
  mapping from `roster/models.json` (the key is absent from the `global` section today).
  The agent file `roster/global-agent/strong-design-review-alternative2.md` still exists,
  and has no `model:` line. MODELS.md:168 still describes that rung as "VACATED 2026-11-23"
  with grok, so the doc, the file and the models.json disagree. Commit `de41d44` already
  records that deployed agents are injected copies (a week-stale lesson).
- **v2 change:** a **roster-consistency check** added to `init.sh --self-check` (init.sh:216),
  and run by the kit's own commit gate. It fails when:
  1. a `global` key in models.json has no matching `roster/global-agent/*.md` file, or the
     reverse;
  2. an agent file has no model line but models.json has no key for it (vacated rung left
     on disk);
  3. MODELS.md's rung table lists a model that models.json does not map to that seat.
  Status words in MODELS.md ("VACATED", "terminal") must match the check's result.
- **Files:** `init.sh` (new `_check_roster_consistency` in self_check); `roster/MODELS.md`
  (rung table as the checked source); the kit's pre-commit, if one is installed for this repo.

### G10 — conventions are per-project copies with no shared base

- **Evidence (verified 2026-11-25, the owner's local project tree):** nine projects carry
  a `dev-workflow.json`; eight carry a `CONVENTIONS.md`. All eight differ from the kit
  template `workflow/templates/CONVENTIONS.md` (47 lines): `cmp` reports them customized,
  at 47 to 344 lines each (one project 344, another 121). Only one project ships a language
  template (`CONVENTIONS.python.md`, 1 of 9). The kit ships four opt-in language templates
  (`cpp` 221 lines, `cpp23` 287, `go` 316, `python` 279; `workflow/templates/`). Owner-reported
  unit: the three C++ and Go templates have zero measured users.
- **Consequence:** a language-rule improvement reaches a project only by hand. The kit's own
  update path does not carry it: a customized file is frozen and only gets a
  `.dev-workflow-kit-new` sibling (README.md:291). Since all eight are customized, the kit
  template's updates never auto-apply to any of them.
- **v2 change: layered conventions** (global base + project override).
  1. **Global base per language:** `~/.config/opencode/conventions/<language>.md`, installed
     by `init.sh --global`. The C++ templates merge into one `cpp` base; `cpp23` is kept as
     a sub-base that extends `cpp`, not merged into it, because the two conflict on the
     exceptions policy (`cpp` vs no-exceptions/`std::expected`). A single merged base would
     have to pick one side silently. Open choice: D8.
  2. **Per-project reference:** `dev-workflow.json` gains `"conventions_base": ["cpp"]`
     (a list, so a polyglot project lists several). Absent key = today's behavior (the
     project's `CONVENTIONS.md` alone), so existing projects keep working unchanged.
  3. **Project file = override layer:** the project's `CONVENTIONS.md` holds only
     project-specific rules; local wins on conflict. Read order: base(s) first, then the
     project file. The skill states the order and flags a conflict that changes behavior
     (SKILL.md §3 baseline rules still apply to both layers).
  4. **Domain rules stay per-project:** server, web UI and native UI conventions are
     architecture decisions, not language discipline. They are not moved to the global base.
  5. **Companions keep codebase pitfalls:** the per-file `.md` companions (SKILL.md §2)
     carry codebase-specific pitfalls; the base carries language discipline only.
  6. **Sync:** the global base is synced by `init.sh --global` with the same lock-hash
     mechanism as the agent roster (`--update --global`, README.md:193). It needs its own
     key namespace in the lock regex (init.sh:260, :267), like the skill (M7b).
- **Files:** `init.sh` (global-base install and sync, lock namespace); `workflow/templates/`
  (the base sources, `conventions-base/cpp.md`, `conventions-base/cpp23.md`, and the
  `CONVENTIONS.md` template reduced to the override layer); `workflow/skill/dev-workflow/SKILL.md`
  §3 (layered read order, conflict flag); `README.md` (the `conventions_base` key in the
  per-project config section, README.md:211-232; the global install table, README.md:188-197).

### G11 — delivery reliability and owner attention are never measured

- **Evidence (maxfill, 2026-11-25; campaign records are the status files, untracked):**
  the primary run `evals/maxfill-2026-11-25.status.txt` has 10 arm launches, 8 `ok`, 2
  `timeout` (arm 008 DR2 at the 900s wall, arm 010 D at the 1800s wall). Arm 005 (D,
  deepseek-1017) is `ok` in the status file but is a DNF: its log writes a `no-report`
  marker ("no assistant text found ... no-report marker written",
  `maxfill-2026-11-25.logs/005-*.log:373`; PROTOCOL.md §2 rule 9 and §5(a)). Three
  follow-up campaigns re-ran the failed arms: `maxfill-retry` (DR2 `ok`, $0.0229; D
  `STOP-BUDGET` against a $1.00 budget, never launched), `maxfill-retry2` (D minimax `ok`,
  $0.1493), `maxfill-retry3` (D deepseek-1017 `ok`, spent=0.5419, the priciest arm of the
  day; DESIGN-d1.md and final-report.md delivered, `maxfill-retry3-2026-11-25.logs/001-*.log:4642-4645`).
  Counting launches: **13 launched for 10 scored arms** (the STOP-BUDGET line never
  launched). First-pass delivery: **7/10 = 70%** (primary run: 8 `ok` minus the no-report
  arm 005). The owner's
  figures (12 launches, 2 DNF re-runs, 15 scoring sessions for 14 TSVs, ~85% first pass)
  DO NOT reproduce from these files; the TSV count was not located under `evals/`. Pending
  owner reconciliation, the counts above are the ones this proposal uses.
- **Historical record (owner-reported, not re-audited here):** 4/4 null gemini arms, dead
  haiku-max sessions, degenerate nemotron loops, a silently-dead gateway id.
- **The pricing gap:** seats are priced at $0.005-0.05 per task (MODELS.md ladders), but
  nothing prices the re-run tax (every extra launch and its spend), the supervision time, or
   the owner interventions. A model that delivers 70% first-pass is not cheap at its sticker
   price: the 3 DNFs of the primary run cost $0.2325 in arm spend (arm 008 = 0.3138 - 0.2825 =
   $0.0313; arm 010 = 0.4466 - 0.3416 = $0.1050; arm 005 = 0.2482 - 0.1520 = $0.0962; deltas
   of the cumulative `spent=` column) before the owner's time is counted, and each re-run adds
   its own launch (the three follow-up re-runs cost $0.7141 in total).
- **The long-horizon blind spot:** the benches measure verification discipline on small
  fixtures; README.md:7 admits the long-horizon generative ability is never benched ("too
  expensive"). The owner's real work (game prototype, e-book library, doc authoring) is
  long-horizon, and that is where the observed waste sits: An unmanaged solo project session at $23.79 of children
  plus an owner evening for a partial result (AUTONOMOUS-RUN.md §5). A direct strong-model
  pass on the same work would cost a comparable amount without the supervision. The kit
  cannot currently say which is true.
- **v2 change:**
  1. **First-class seat criteria:** first-pass completion rate (delivered without re-run) and
     owner-intervention count per task, recorded per arm alongside score and price.
  2. **Re-run tax:** each arm records every launch it needed, and the summed cost of the
     launches (the re-run tax), not only the final run's cost.
  3. **Extend the ops layer:** `evals/build-ops.py` already computes `delivered` per run
     (its docstring lists the sources: `grid2-run-scores.tsv`, `opencode.db`). Extend it with
     per-task launch count, re-run tax and intervention count. Intervention source (to be
     verified before relying on it): user-role messages in the session tree of the arm
     (`message.data` role field, not checked here).
  4. **Seat decisions cite delivery, not only score x price:** a seat change states the
     delivery rate and the re-run tax next to the score. A seat whose first-pass rate is
     below a threshold is not promoted on score alone (threshold: owner decision, proposed
     80% as the floor, D9).
- **Files:** `evals/build-ops.py` (extend the output columns); `evals/PROTOCOL.md` §5 (the
  seat rules gain the delivery and intervention criteria; §5 is the Étape 0 rules section
  today, lines 115-222); `roster/MODELS.md` (a decision template for seat changes does NOT
  exist yet, verified: MODELS.md has none; v2 creates it, with the delivery fields required).

### G12 — headless runs die on interactive-permission walls

- **Evidence (owner-reported, five deaths on 2026-11-25; session logs not re-audited here):**
  (1) a scorer batch silent-failed on a scratch `cd` rejected by the permission layer;
  (2) a headless RE run died reading `../<external-notes-repo>/notes/` (external directory,
  auto-rejected even under `--auto`); (3) a python heredoc rejected; (4-5) two relaunches of
  the same failures. Owner-reported: opencode ABORTS the whole run on any permission
  rejection, and `--auto` does not cover external directories. Not verified against 1.19.6 here.
- **Repo fact:** the kit already solved this for held-out benches. `evals/run-eval-v6.sh:4-5`
  copies the fixture outside the sandbox and runs each arm under sandbox-exec, with per-arm
  `XDG_*` / `HOME` / `TMPDIR` and no `auth.json`. Guards live in the filesystem, not in prompts.
  The launch gate `evals/preflight.sh:31-48` checks that declared `--path`s sit under `--dir`,
  but it runs once at launch: it cannot see a read the agent chooses mid-run, a heredoc, or a `cd`.
- **v2 change:**
  1. **Born allow-listed.** The launch fixes the permission profile before the first tool call:
     `--auto` for tools; allowed commands and paths are derived from the brief's
     pre-authorizations (AUTONOMOUS-RUN.md §1), not granted on request. Patterns use the
     README glob form (README.md:71-81, e.g. `"*git commit*"`).
  2. **Guards as environment, never prompts.**
     - git shim on PATH for headless runs: refuses `commit` outside the run's repo root and
       refuses every `push`. Push stays one per authorization (G3, D2): a headless run records
       the drafted push request and does not execute it.
     - Confined dirs: one scratch directory is the writable tree; reads outside it are denied by
       the sandbox. Per-arm HOME/TMPDIR as in run-eval-v6.
     - Python: an allowed invocation pattern (`python3 <named-file>`); the brief names the script
       file; no heredoc.
  3. **Degrade, don't abort.** A permission rejection of a non-fatal read (optional notes,
     reference files) returns a tool error to the agent, is logged as `SKIPPED <path>
     (permission)` in the run report, and the run continues. A rejection of a fatal action
     (write outside the scratch dir, commit, push) stops the run as a DNF with the rejection in
     the ledger. **Open assumption:** opencode 1.19.6 can return a rejection as a tool error
     instead of aborting the process. Verified by step T-G12-1 before the design is relied on.
     4. **Pre-flight extension (AUTONOMOUS-RUN.md §8, R1(a)):** every path the brief names is
     checked at launch, so the external-directory case (death 2) fails before launch, not
     mid-run. Reads the brief does not name fall under item 3.
- **Lives in:** the supervisor loop (AUTONOMOUS-RUN.md §7, loop paragraph, line 148; the
  supervisor script does not exist yet, per the §5 journal next step); the pre-flight
  (AUTONOMOUS-RUN.md §8, `evals/preflight.sh`); the run-harness pattern (`evals/holdout-harness/`,
  `run-eval-v6.sh`, reused as-is, not modified per D7).
- **Files:** `evals/preflight.sh` (extend for named reads and external dirs). §8 R1(d) has
  no mechanical check yet. `roster/global-skill/scratch-workflow/SKILL.md`
  (headless profile, G6 item 4). Git shim location: D10.
- **Risks:** sandbox-exec is macOS-only (run-eval-v6 is darwin-only today); a Linux run needs
  different confinement, not a prompt. A PATH shim is bypassed by an absolute `/usr/bin/git`:
  it guards honest mistakes, while the real boundaries are the sandbox and the push rule. Degrade
  mode can let a run finish without an input: the report lists every skipped read, and the
  reviewer checks that list.
- **Test (T-G12-1):** on a fixture, one headless run with (i) a required read outside the
  sandbox, expecting DNF with the rejection in the ledger; (ii) an optional read outside the
  sandbox, expecting `SKIPPED` and completion. Run (i) and (ii) before item 3 is relied on.

### G13 — a method library and the distillation loop

- **Evidence (2026-11-25, end-to-end; the artifacts sit in the owner's corpus, not in this repo.
  The cost and judge figures are owner-reported and NOT in the repo):**
  1. Deep pass: the deep rung (an Opus pass) did one slice of a retro-game reverse-engineering task (game A,
     one projectile mechanic) AND wrote the method checklist that the slice followed.
     Owner-reported cost $3.34.
  2. Blind cheap arm: a haiku `high` arm re-executed the slice guided only by that checklist. Its
     report says the deep pass's slice report was NOT opened (its §0, lines 32-34). This is
     self-attested blindness, not sandbox-enforced (see G12).
  3. Judge: owner-reported 17/18 static claims byte-exact against the dump, by an independent
     judge; no leak; cheap-side total ~$0.10. The judge output and the cost ledger are not in the
     repo.
  4. Variant (game B pass): the deep pass also logged WHICH external tools it used and what each
     bought (command, result, pitfall), in its method file's §3. That log is a measured tool
     wishlist, not a cost record.
  5. Repo fact: no method library, no `METHOD-TEMPLATE`, no routing check exists. `distill`,
     `METHOD-TEMPLATE`, "method library" and "method production" appear nowhere in `workflow/`,
     `roster/`, `README.md` or `AUTONOMOUS-RUN.md` (grep-checked).
  6. **Cost caveat.** The "30x" compares the distillation pass ($3.34) with one cheap slice
     (~$0.10). The comparable baseline, a strong model doing every slice, is not measured.
     Amortisation from the second slice holds only if one strong slice costs more than about
     ($3.34 / 2) + $0.10 = $1.77; that strong per-slice cost is unmeasured.
- **v2 change:** a METHOD LIBRARY, and the distillation loop as the way the library grows.
  1. **Routing check, before any task.** The workflow checks the library for the task class first:
     - a method exists → apply it (its procedure, evidence rules and traps are the brief);
     - none exists and the class is judged repetitive → run the distillation loop (items 2-4),
       then ADD the method to the library;
     - none exists and the class is one-shot → plain delegation; nothing is added.
  2. **Gate (task class).** Repetitive means: (a) machine-checkable ground truth (a dump, a byte, a
     test output) and (b) at least three slices still to run. The owner or the orchestrator checks
     it and logs the decision in the brief.
  3. **Distil (one bounded DEEP pass: short, precise, surgical).** The `deep` rung (roster/MODELS.md) at its best use: minimal scope, maximal depth, the method as the primary deliverable. It does one bounded slice
     and produces the work product AND the executable method checklist: verification order,
     evidence per claim type, known traps, and a tool-usage log (tools used, what each bought, what
     failed). The brief carries a session budget (G1). **The deep pass does NOT do volume.** Volume belongs to the cheap validation and production slices (item 4). The deep pass ends as soon as the method is executable by someone else (a cheap rung can follow it blind), not when the slice is complete. Anything the method does not need in order to be executable is cut from the deep pass.
  4. **Validate blind, then scale.** A cheap rung runs ONE different slice using only the checklist.
     The brief lists the deep pass's output paths as off-limits. A judge from a different family
     byte-checks a sample. Concordance (confirmed / judged) validates the method; a failure refines
     the method and re-runs the validation slice. Then the remaining slices run on the cheap rung,
     and the judge samples at each cut (a cut = one slice batch). Escalation only at walls: two
     consecutive failed slices → one strong rung with the failed output attached
     (roster/MODELS.md, "Escalation semantics"), then back to cheap.
  5. **Library record.** Each method file carries its own validation status and history:
     `validated-on: N slices`, `concordance: X% (judged claims)`, `last validated: <date>`, and its
     retro amendments. An amendment is re-validated on the next slice before it is trusted. A method
     is never silently edited. The library is the accumulating asset.
  - **Layout:** `workflow/methods/<task-class>.md`, one doc per class, each drafted from
    `workflow/templates/METHOD-TEMPLATE.md`: scope and gate; core invariants with claim states; one
    adapter section per platform or tool; procedure in order; known traps; tool-usage log; retro;
    validation status; version. The kit ships generic methods only. A project-specific adapter stays
    in its project repo, not in the kit.
  - **First library instance (generic, derived from the measured exercise):** a reverse-engineering
    method for a binary run on an emulated retro machine. Core: control run without input first;
    three evidence states (VERIFIED-static / VERIFIED-dynamic / UNVERIFIED); data structures named
    before routines; old claims stay UNVERIFIED until re-read; studio-spec deliverable. Platform
    adapters are separate sections the project fills in. Its status starts at `validated-on: 1
    slice, concordance 17/18 (owner-reported)` and stays there until T-G13-1 re-validates it.
  - **Acceptance (proposed; owner to tune, D11):** concordance ≥ 90% of judged static claims on the
    validation slice, and zero leaks.
- **Lives in:**
  - `workflow/methods/` (new directory): the library, one doc per class.
  - `workflow/templates/METHOD-TEMPLATE.md` (new): the template for a library doc.
  - `workflow/skill/dev-workflow/SKILL.md`: the routing check (one step, before any task). The file
    is 123 lines; M16 prunes while editing.
  - `roster/MODELS.md`, the `deep` rung's job description (MODELS.md:125): gains "deep method production" (scoped as in item 3: short, precise, surgical)
    as a second job. No new rung, no roster change.
- **Files:** `workflow/methods/` (new, first doc), `workflow/templates/METHOD-TEMPLATE.md` (new),
  `workflow/skill/dev-workflow/SKILL.md` (routing step), `roster/MODELS.md` (one paragraph).
- **Risks:**
  - The 30x is not a measured saving until a strong baseline is recorded on the same slices
    (T-G13-2). Do not quote it as one.
  - One validation slice is thin: 17/18 on one slice can be luck. The first library entry stays at
    `validated-on: 1` until a second slice confirms it.
  - Blindness is self-attested. A leaked deep-pass output inflates concordance silently. Mitigation:
    the judge checks citations of the deep-pass output; the sandbox once G12 exists.
  - Amendments without re-validation drift the method toward the deep pass's habits. The
    amendment rule (item 5) is the guard.
  - A bad checklist propagates to every slice. The validation in item 4 is the only guard; it must
    not be skipped.
  - A class without machine-checkable ground truth (design, judgement) fails the gate: the judge
    cannot byte-check it.
  - Methods are platform-specific at the adapter level. The core/adapter split in the template is the
    mitigation for a new platform.
  - A library that grows without pruning becomes a cost of its own, because the routing check reads
    it. Each method's status line is what the routing check reads first.
- **Test (T-G13-1):** on a second slice of the first library entry's class, the cheap rung runs with
  the checklist only; the judge byte-checks a sample. Pass = concordance ≥ the D11 threshold AND zero
  leaks. The entry's status line is then updated.
  **T-G13-2 (cost baseline):** the same slice is run by the strong rung directly, cost recorded in
  the ledger (G1). This measures the break-even instead of assuming it.
  **T-G13-3 (routing):** a task whose class is already in the library is routed to its method with no
  new deep pass (checked in the ledger: zero deep-pass spend for that task).

## 4. Profiles and the cost ledger (summary)

| Dimension | interactive (default) | autonomous (per brief) |
|---|---|---|
| Commit | ask per commit | allowed per validated wave (task authorization) |
| Push | ask | ask, one per push (never batched) |
| Questions | batched at design time | batched per wave (arbitration list) |
| Decisions | internal choices logged | all non-Scope choices logged + defaults |
| Review rounds | 2 per wave (both profiles) | 2 per wave |
| Child cap | stated, $2 default | stated, $2 default; enforced by the store-poller (G1 change 3), fallback = stop at the next checkpoint |
| Session budget | optional | required in the brief |
| Long waits | TUI allowed | headless background + monitor (AUTONOMOUS-RUN.md §6) |

Watchdog (progress-aware, not wall-clock): kill a delegated run only after N minutes with
no tool event (AUTONOMOUS-RUN.md §5 journal, maxfill DR2). Wall-clock stays as a hard
ceiling. Proposed N: 15 minutes, owner to tune (D7). The eval runners stay as they are in
v2 (see D7): the DR2-max 1800s re-run fix is deferred, noted in AUTONOMOUS-RUN.md §5.

## 5. What to REMOVE — owner-decision checklist (not a recommendation)

Evidence in brackets. Tick what you decide to remove; nothing is removed by this proposal.

- [ ] `roster/global-agent/strong-design-review-alternative2.md` — rung vacated (models.json
      has no key since `1b5de26`; MODELS.md:168 says VACATED). The file still exists, with no
      model line. Option: delete the file and keep the fallback as a MODELS.md sentence.
      The deletion and the README count fixes are owned by M9.
- [ ] `strong-code-alternative2` (opus) and `strong-design-alternative2` (opus) — both
      SEATED in models.json, not vacated. Only remove if you choose "human intervention is
      the next step" over a terminal opus rung. (Brief said "two vacated terminal rungs";
      verified: only one is vacated. The second candidate is open, see D1.)
- [ ] `strong-review-alternative2` (qwen `xhigh`) — seated; MODELS.md:240-243 names grok as
      its fallback. Remove only if grok is the chosen replacement.
- [ ] Convention templates (measured use, G10): `CONVENTIONS.python.md` is used by 1 of 9
      projects (one project); `CONVENTIONS.cpp.md`, `CONVENTIONS.cpp23.md` and
      `CONVENTIONS.go.md` have zero measured users (README.md:119; opt-in contract
      README.md:236). Fate under G10: the C++ templates are **merged into the global `cpp`
      layer (cpp23 as its sub-base), then the per-project copies become obsolete**; `python`
      and `go` move to the same global layer. Nothing is deleted before D8 is decided.
- [ ] `evals/run-eval.sh` — confirmed absent (`ls evals/run-eval.sh`: no such file), yet
      README.md:146 still lists it. The README line is removed by M10; nothing to delete.
- [ ] Duplicate `RULES.md` opt-in path — README.md:37 and :184. Keep only if you use it.

## 6. Migration plan (v1 -> v2)

| Step | Files | Change | init.sh impact |
|---|---|---|---|
| M1 | `WORKFLOW-V2-PROPOSAL.md` (this) | new | none |
| M2 | `workflow/skill/dev-workflow/SKILL.md` | add cost fields to ledger (§1), baseline rule 4 evidence (§3), 2-round review bound (§6-7), decision log + reversibility gate (§1), profile definition (§6), routing enforcement sentence (§1). Prune duplicated prose while editing so the file does not grow past its current 123 lines | copied only if absent; a customized copy gets `.dev-workflow-kit-new` via `--update` (README.md:289-292) |
| M3 | `workflow/templates/INPROGRESS.md` | budget line, ledger format, decision log section | template is copied only if absent; **project-state file, never touched by `--update`** (README.md:292): existing projects must migrate by hand |
| M4 | `workflow/agent/impl.md`, `review.md` | one evidence line each | `--update` syncs (untouched) or `.dev-workflow-kit-new` (customized) |
| M5 | `roster/global-agent/cheap-code.md`, `cheap-review.md` | same evidence line | `init.sh --global --update` (de41d44 lesson) |
| M6 | `roster/global-skill/scratch-workflow/SKILL.md` | new: brief template, per-step objective gates, post-run retro (extends SKILL.md:117-123 to autonomous runs), reporting loop (G6) | new global-skill copy path (see M7a) |
| M7 | `init.sh` | (a) global-skill copy into `${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/skills/` (plural; a legacy singular `skill/` copy is warned, not deleted); (b) lock-file key namespace: the REL-key regex `^(agent\|skill\|CONVENTIONS\|RULES)` at init.sh:260 and :267 (self-check at :275, :279) must accept the global-skill prefix, or the lock is rejected; (c) roster-consistency check in `self_check` (init.sh:216); (d) `--global` lock scope for the skill | `--self-check` must stay exit-0 on v1 trees |
| M8 | `roster/MODELS.md` | rung table reconciled with models.json (G9); status words | none (doc) |
| M9 | `roster/global-agent/strong-design-review-alternative2.md` (delete), `README.md` (counts), `roster/MODELS.md` (rung table) | Vacated-rung cleanup, owned here: (a) delete the file (models.json key already gone, `1b5de26`); (b) README.md:123 "17 session-roster agents" -> 16 and README.md:190 "seventeen ... agents" -> sixteen, dropping the name from the list; (c) README.md:140 structure line removed; (d) MODELS.md:168 rung status reconciled. Verify with `ls roster/global-agent \| wc -l` = 16 after the deletion. Not verified: whether `init.sh --global --update` removes a deployed copy of a file deleted from the kit (the lock-driven sync is documented only for updates, README.md:287-292). Plan a manual check of `~/.config/opencode/agent/` after deletion | none to the sync path; `--global --update` run after the change (de41d44 lesson); the deployed copy may need manual removal (see verify note) |
| M10 | `README.md` | permission section (second block, G3); line 58 replaced (G7); structure tree: add the global-skill dir, drop the stale `run-eval.sh` line (README.md:146; file confirmed absent); limitation section | none |
| M11 | `AUTONOMOUS-RUN.md` | fix §4 line 63 (push, D2); add pointer to v2 sections; still untracked, owner commits | none |
| M12 | `evals/` (funded, G8, D5) | autonomy bench spec; first case = game-A RE slice | none |
| M13 | `workflow/templates/conventions-base/{cpp,cpp23,python,go}.md` (new), `workflow/templates/CONVENTIONS.md` (reduced to the override layer), `init.sh` | (a) the global language bases, sourced from the four opt-in templates (cpp+cpp23 kept as separate layers, D8); (b) `init.sh --global` installs them to `~/.config/opencode/conventions/`, lock-driven like the roster, with a new lock namespace (init.sh:260, :267); (c) the per-project `CONVENTIONS.md` template now carries only override rules | the `--global` path gains a conventions copy; the lock regex gains a prefix; `--self-check` stays exit-0 on v1 trees |
| M14 | 8 customized project `CONVENTIONS.md` copies (not kit-owned) + `dev-workflow.json` | opt-in migration, by hand per project: move the language-discipline part into the base, keep project rules as the override, add `"conventions_base": [...]`. Not forced: a project without the key keeps working unchanged. Not auto-applied by `--update` (customized files are frozen, README.md:291) | none; owner-run per project |
| M15 | `README.md` | per-project `conventions_base` key (README.md:211-232), global conventions install row (README.md:188-197), the opt-in language-templates paragraph (README.md:234-236) rewritten for the layered model | none |
| M16 | `workflow/methods/` (new, first doc: generic RE method, G13), `workflow/templates/METHOD-TEMPLATE.md` (new), `workflow/skill/dev-workflow/SKILL.md` (routing check, one step, G13), `roster/MODELS.md` (deep rung job description gains "deep method production" (scoped as in item 3: short, precise, surgical); folded into the M8 reconciliation edit) | Draft the template, the first library doc (produced by one deep pass), and the routing step. The MODELS.md edit is one paragraph, not a rung change | `workflow/methods/` copied only if absent (same rule as M3) if init.sh copies templates by name; otherwise one copy line (to verify at implementation). No lock change. `--self-check` stays exit-0 |

Rollback: each M-step is one commit. Per the update recipe (README.md:299-306), commit the
current state first, then `--update`, so `git revert` restores prompt files and lock
together. Project-state files (TODO/INPROGRESS/CHANGELOG/DESIGNS/dev-workflow.json) are
never rewritten by v2; a project that wants the decision log or budget line adds them by
hand.

Test plan: `init.sh --self-check` (exit 0 on v1 and v2 trees), a fresh install and an
`--update` on a scratch project, one scripted autonomous run on a fixture (cap hit ->
DNF recorded, 2-round review bound -> escalation or accepted-with-findings).

## 7. Open decisions for the owner

Batched, per the design-time rule (SKILL.md:31). Each affects the step list or a Scope
trigger. Repo facts are already checked above.

| # | Question | Recommended answer | Changes |
|---|---|---|---|
| D1 | Which rungs are "the two vacated terminal alternative2 rungs"? Verified: only `strong-design-review-alternative2` is vacated. `strong-code-alternative2` / `strong-design-alternative2` (opus) are seated | Delete the vacated file (M9 / §5 item 1); keep opus terminals; confirm which second rung you meant | M8, M9, §5 |
| D2 | Push policy in AUTONOMOUS-RUN.md §4 ("push without asking") conflicts with the global one-push-per-authorization rule | Keep push as `ask`; pre-draft the push request; one authorization per push. Autonomous profile pre-authorizes commits only | G3, M11 |
| D3 | Default per-child cap, max children per session, session budget | $2 per child, enforced by the store-poller (fallback: stop at the next checkpoint); max children 10 with a refuse-on-11th stop rule; session budget required in every autonomous brief, no kit default | G1, §4 |
| D4 | Ship scratch-workflow as a global skill (new install path) or keep AUTONOMOUS-RUN.md as a doc | Global skill: the kit's install path is the only way it reaches every session | G6, M6, M7 |
| D5 | Autonomy bench (G8): fund it now or after the skill exists | **Fund now.** The owner validated the game-A RE slice as the first autonomy-bench case: a retro-game projectile-mechanic RE; glm-flash supervised vs haiku `high` vs opus-direct as the meter; pass = verified-claim rate (byte claims checked against the binary) + completion. Owner estimate ~$40-80 all-in (owner-reported, not priced here). Cost was the reason it was optional; the owner accepts it | G8, M12 |
| D6 | Template and rung removals (§5) | Remove the vacated file; keep the rest until used | §5 |
| D7 | Progress-aware watchdog: N minutes of tool-event silence before kill | 15 min. The eval runners stay as they are in v2: no change to `run-eval-v4/v5/v6.sh`; the DR2-max 1800s re-run fix is deferred (noted in AUTONOMOUS-RUN.md §5). The progress-aware watchdog applies to autonomous supervisor runs only | §4 |
| D8 | Conventions: adopt the layered model (global base per language + project override, G10), or keep per-project `CONVENTIONS.md` copies | **Adopt.** It is the roster's `--global` pattern applied to conventions: one place to improve a language rule, lock-driven sync, and project files shrink to project rules. Costs: the C++ `cpp`/`cpp23` conflict on exceptions must be resolved in the base (sub-base, G10 item 1), and the 8 customized copies need a one-time split by hand (M14) | G10, §5, M13-M14 |
| D9 | Delivery floor for seat promotion (G11): minimum first-pass completion rate before a seat is promoted on score | 80% first-pass is REQUIRED for a seat. Maxfill's real first pass is 7/10 = 70% (below the floor; the earlier 8/10 reading is withdrawn), which is the evidence that the re-run tax is real: a seat below the floor must price its re-runs (every extra launch and its spend) into the seat decision, and is not promoted on score alone | G11, PROTOCOL §5, MODELS.md template |
| D10 | Confinement for headless runs (G12): sandbox-exec per run (run-eval-v6 pattern, macOS only) or HOME/TMPDIR isolation plus git shim | Sandbox-exec for autonomous runs on darwin; HOME/TMPDIR isolation as the portable fallback; the git shim is advisory, not a boundary | G12, §8 |
| D11 | Adopt the distillation loop (G13): gate, one bounded DEEP pass (short, precise, surgical), blind cheap validation, cheap scale-out, escalation only at walls | **Adopt (recommended: yes).** Owner-reported ~$0.10 per cheap slice after a $3.34 distillation pass, and 17/18 concordance on the one validated slice. The "30x" is not a measured saving until T-G13-2 records a strong baseline; the ≥90% threshold is proposed, owner to tune; blindness is self-attested until G12 confinement exists. The deep pass does no volume: it ends when the method is executable by someone else. One-shot tasks stay on plain delegation | G13, M16, roster/MODELS.md (deep rung) |
| D12 | Adopt the method library (`workflow/methods/`, G13): a routing check before every task; each method carries its validation status and retro history | **Adopt (recommended: yes).** It turns a one-off measured gain into a reusable asset: a class already in the library is routed without a new strong pass (T-G13-3). Cost: one library read per task, plus a pruning rule (owner to set). The first entry is generic and stays at `validated-on: 1` until T-G13-1 passes | G13, M16 |

Not in the batch (resolvable from repo facts, decided here): the lock namespace fix (M7, item b) is a
mechanical consequence of G6; the decision-log and ledger field names are fixed by §3.

## Appendix A — journal specimens (2026-11-25)

The 2026-11-25 evening "Task cancelled" entry is appended to `AUTONOMOUS-RUN.md` §5 (newest
first). The verdict entry below and the specimens are NOT in §5 yet; `AUTONOMOUS-RUN.md` is
owner-owned, so the owner decides whether to append them. Newest first:

- Specimen — "Task cancelled, hours of idle wait" (2026-11-25, RE session): the orchestrator
  treated a dead delegation return as a non-event and waited for hours. Diagnosis was instant
  when asked. The missing piece is the external tick (a monitor that treats a cancelled or empty
  delegation as a stall), not the orchestrator's honesty. Proposed rule: a cancelled or empty
  delegation return is a stall event, escalate-or-restart within one poll interval (AUTONOMOUS-RUN.md
  §2 item 5; progress watchdog D7).
- Specimen — double-opus launch (2026-11-25): two arms launched for one task, $0.26 wasted.
  Pre-launch enumeration of live sessions is now rule R1(b) (AUTONOMOUS-RUN.md §8). Mechanical
  check: `evals/preflight.sh` live-session guard, keyed on `--title-fragment`.
- Specimen — orphaned subagent (2026-11-25): a $0.24 opus subagent survived the kill of its
  parent, unnoticed for minutes. Rule R1(d) (enumerate live children before killing a parent).
  **No mechanical check exists yet:** `preflight.sh` gates launches only, not kills.
- Verdict (2026-11-25 evening, owner): "plus on mesure et optimise, moins j'ai de résultats".
  Audit agrees: the bench optimizes $/task on small fixtures (the cheap seats are saturated)
  while the owner's attention went to supervising long-horizon work the kit never measured. G11
  (delivery rate, re-run tax and owner interventions as seat criteria) added to this proposal;
  G8 (autonomy bench) promoted from optional to v2 priority and funded (D5).

# Design: `pr-review` — multi-pass, multi-model PR review pipeline

Status: DESIGN v3 (not implemented) · Date: 2026-10-23 · Owner: dev-workflow-kit
v3 (owner change): ALWAYS-multi-pass per objective — a fixed battery of 6 objective passes always runs, replacing "single cheap rung by default"; escalation is per-objective on the same deterministic triggers. v2 retains: finding-driven escalation only (no diff-shape triggers), semantic dedup, haiku 100k-cliff handling, FP-weighted corroboration, mechanical gate, secret handling.

## Goal

A PR-review flow that always runs a battery of 6 objective review passes (several agents, possibly the same agent several times with different objectives — the objective brief, not the model, carries the lens), then escalates per objective only on demonstrated need, and produces PR-ready draft comments posted **only after explicit user approval via a mechanical gate**. Every pass reads the same PR diff with its own specialized checklist, never modifies anything, and its cost is visible to the user.

Verifiable end state: given a PR number, the flow produces (a) an auditable report — which pass/model found what, cross-objective corroborations and conflicts, FP judgment, cost per pass — and (b) a staged draft of PR comments, of which exactly the user-approved subset is posted via `gh`.

## Non-goals

- **No auto-posting, ever.** The only `gh` write is `post-approved.sh`, which posts exclusively blocks the user ticked.
- **No CI mode** (interactive skill; CI replay can come later). **No fixing** (reviewers propose, never patch). **GitHub only, for v1** (the scripts speak `gh`; other forges are v2).
- **No new agent definitions.** Passes run on the existing global-roster agents; agent prompts are unchanged — the objective brief carries everything. Models named in this doc are bindings from `models.json` (table below), not agents.
- **The battery is a config of the skill, not code.** The 6 objectives below are the v1 list; adding/removing an objective is a SKILL.md list edit, not a script change.

## Rungs, passes and model bindings

| Pass (objective) | Checklist focus | Default binding |
|---|---|---|
| 1. defect risk | language-aware defects: C++ → use-after-free, dangling refs, RAII/ownership, const-correctness, iterator invalidation, races; Python/Go equivalents (unhandled exceptions, swallowed errors, goroutine leaks, race-prone shared state) — the kit ships CONVENTIONS templates per language, referenced by the brief | cheap-review (haiku 5.5) |
| 2. security | injection, authz, secret handling, untrusted input | cheap-review (haiku 5.5) |
| 3. style / conventions | compliance with the kit's `CONVENTIONS.md` | cheap-review (haiku 5.5) |
| 4. code quality | minimalism, no over-engineering, architecture fit | cheap-review (haiku 5.5) |
| 5. comments & docs accuracy | do comments/docstrings/README claims match the code — the "lying comment" trap | cheap-review (haiku 5.5) |
| 6. tests | coverage of the diff, missing failure-first tests | cheap-review (haiku 5.5) |
| Escalation rung (per objective) | strong-review | glm-flash `high` |
| Doubt rung | strong-review-alternative / -alternative2 | per roster lineage rules |
| Large-context branch (same pass, different binding) | when a pass's brief needs the whole context >100k | deepseek-v4p1-flash-1017 `medium` (roster's documented cliff-free fallback) |

The SAME model may run several passes — different briefs carry different lenses. **Lineage rule stays:** the battery must not be bound to the impl/author's family when that family is known (reviewer lineage ≠ author lineage). When the roster is re-arbitrated, only this table changes.

## Chosen flow

**A new skill (`skill/pr-review/SKILL.md`) + two small scripts (`fetch-pr.sh` read-only, `post-approved.sh` the only poster), reusing the global-roster review agents.** Orchestration happens in the primary session — the orchestrator must enforce cost accounting and the user gates, and sub-agents cannot ask the user questions.

```
user: "review PR 123" (skill triggers on: pr-review / review PR <n>)
  ├─ 1. FETCH (read-only)   fetch-pr.sh → staging dir: pr metadata, diff
  │       (base…head), changed files, CI status. NO checkout, NO branch
  │       switch, NO writes outside the staging dir.
  ├─ 2. BRIEFS              one brief per objective: diff (or chunk) + language
  │       template + the objective's checklist + grounding rules + safety
  │       rules + FP-discipline clause.
  ├─ 3. BATTERY             all 6 objective passes RUN (parallel; same rung
  │       agent, per-pass bindings and briefs). ALWAYS runs — never skipped.
  ├─ 4. MERGE               orchestrator semantic-merges findings ACROSS passes
  │       (below); conflicts marked.
  ├─ 5. ESCALATE?           per objective, deterministic triggers only (below)
  │       → the ESCALATED OBJECTIVE goes to strong-review, then alternatives;
  │       the rest of the battery is untouched. Beyond strong-review: user's
  │       explicit go before the spend.
  ├─ 6. STAGE               PR-<n>-comments.md, one block per finding: severity,
  │       provenance (pass, model, cost), confidence, proposed body. User
  │       approves / edits / rejects EACH block individually (own [x] tick).
  └─ 7. POST + REPORT       post-approved.sh (the mechanical gate) posts only
          [x] approve blocks via `gh pr review --comment`. Then the report.
```

Hard safety rule, repeated in every brief and in the skill: **reviewers and the orchestrator are read-only — no file edits, no git mutations, no `gh` writes.** This is defense in depth only: prompt enforcement is NOT protection, because the orchestrator reads untrusted PR content (a malicious PR can carry injected instructions). The real protection is structural: reviewers have `permission: edit: deny`, and the only posting path is `post-approved.sh`, which nothing but the user's ticks can activate.

## Size thresholds (two knobs, one system)

| Threshold | Level | Behavior when exceeded |
|---|---|---|
| Hard diff-size cap | `fetch-pr.sh` (script) | refuse and offer a chunked review (per-file-group runs) — never silent truncation |
| ~90k-token prompt budget per pass | brief (orchestrator) | split that pass's brief into chunks reviewed by the same pass/binding |

**Relation:** the script cap exists so the ~90k per-pass threshold is always reachable by chunking. If a pass genuinely needs the whole context in one prompt, that is the large-context binding's job (table above) — still the same objective pass.

## Per-pass brief rules (all passes)

- Review the diff **as new code** against the base — the PR description and author claims are unverified claims to check.
- Read the surroundings of every touched file (callers, tests) — a reviewer that only read the diff must say `diff-only review` in its report.
- Read `CONVENTIONS.md`/`RULES.md` and the kit's language template when present; each brief names its language template for pass 1.
- Every brief carries the FP-discipline clause: a finding without a concrete mechanism is an FP; never padded to look thorough (3×-penalty rule).
- The brief carries diff line count, changed-file list, and whether the PR fixes a reported bug (red/green expectation applies, mainly for the tests pass).

## Escalation policy (per objective, one policy, aligned everywhere)

**Triggered by findings only, never by diff shape — evaluated PER PASS.** Checked after the merge: an unconfirmed **major** finding (security, data loss, contract break) within a pass escalates THAT objective to strong-review; a **conflict** between passes on the same finding escalates that objective (adjudication); a pass's explicit `diff-only review` or uncertainty statement escalates it too. An unconfirmed major on the security pass escalates the security objective — not the whole battery.

A large diff or sensitive path is **never** an automatic trigger — it becomes a user-facing SUGGESTION; the pipeline never spends on diff shape. Doubt/stall from a strong rung → strong-review-alternative, then -alternative2 (that objective only). A pass with no trigger ends with the battery — never speculatively escalated.

A reviewer's self-reported confidence is **evidence for the report, never a trigger by itself** — triggers stay the three deterministic ones above. "Confident, clean" from one pass does NOT outvote a major finding from another: that disagreement IS a cross-pass conflict → escalate.

## Findings aggregation (semantic merge ACROSS passes, no deterministic key)

Findings come back in the existing one-line format (`severity — file:line — problem — expected action`) plus `reviewed`/`not reviewed` axis statements and an overall verdict. The orchestrator performs a **semantic merge across passes** — a judgment call, not a key match: the same defect surfacing on two different objectives (e.g. defect-risk and security) on the same file:line = corroborated (`confidence: 2 objectives`), severity takes the max; wording may differ and locations may be lines apart. A **conflict** (same location/category with opposite verdicts across passes, or a strong rung refuting a battery finding) is never self-resolved — it escalates that objective.

**Corroboration by the strong rung is not independent confidence when bindings share a lineage** (strong-review binds glm-flash `high`, measured 2 FPs on v1 T3): a glm-only finding raises severity only with mechanism-level proof in its own text, and the glm brief carries the FP-discipline clause explicitly. glm never runs as a battery pass's corroborator AND its first escalation rung (no-op escalation). A finding no pass corroborates and the strongest rung does not confirm is staged `low-confidence` (posted only if the user keeps it) and flagged as a probable FP in the report, never silently dropped.

## The mechanical approval gate

- **Staging file** `PR-<n>-comments.md`, one block per finding, each with its own status line:

```markdown
## [F2] major — src/sync.py:87 — silent copy failure can report `done`
- provenance: found by security pass (haiku 5.5, $0.002); corroborated by defect-risk pass
- confidence: high (2 objectives)   <!-- or: low — possible FP -->
- status: [ ] approve / [x] reject / edited
<!-- comment body below — this exact text is posted if approved -->
**Bug**: `copy_file` swallows `OSError` ...
```

- **`post-approved.sh` is the gate, not a prompt.** It parses the staging file and posts ONLY blocks carrying an exact `[x] approve` tick (with their own, possibly edited bodies) via `gh pr review --comment`; each block needs its own tick — no batch approve exists, and the tick is the only signal the script reads. No other code path can post; the orchestrator does not post, it runs the script, and the script's parse is the authority. Prompt-enforcement is not protection here either: the orchestrator reads untrusted PR content, so the gate must be a script that cannot be talked past.
- **Secret handling**: a secret finding is never staged as a PR comment — it is surfaced to the user in the report with `file:line` only, no value (rotate outside the PR). The staging dir defaults OUTSIDE the repo (temp dir); if the user opts into the in-repo path, the `.pr-review/` gitignore rule is verified before the diff is written there. The user is warned up front that the fetched diff (possibly containing secrets) is shipped to the model providers.
- Rejected findings stay in the staging file (audit trail).

## File layout

`skill/pr-review/` holds three files: `SKILL.md` (triggers "review PR `<n>`", the battery config — the 6 objectives and their bindings, thresholds, gate rules), `fetch-pr.sh` (read-only: `gh pr view`/`diff` → staging dir; diff-size cap) and `post-approved.sh` (the mechanical gate: `[x] approve` blocks → `gh pr review`). Installed to `.opencode/skill/pr-review/` by `init.sh` (copy-if-absent, `--update` syncs it). Runtime artifacts per PR, in the staging dir (temp dir by default): `PR-<n>/` (fetched context), `PR-<n>-comments.md` (the gate input), `PR-<n>-report.md` (the audit output). No change to `dev-workflow.json` schema.

## Cost accounting

The battery is ~N×cheap (N = number of objectives, 6 for v1; passes with the default binding are ~$0.0063/task each), so the always-on cost stays at the cheap tier — which is the point. Escalations are per-objective add-ons priced at the rung ladder: strong-review ~$0.008/task, strong-review-alternative ~$0.119/task, -alternative2 ~$0.151/task (per-task labels, from `MODELS.md`/`EVALS.md`), with a context-size qualifier: a pass routed to the large-context binding (deepseek-v4p1-flash-1017 `medium`, through cheap-review's slot) costs more and is priced as such. Actual costs come from the opencode sessions DB per pass, child sessions extracted by `session.parent_id` (not by title), applying the delegation rule (parent + all named children). Escalation beyond strong-review is behind the user gate.

## Rollout

1. Add `SKILL.md` (with the battery config), `fetch-pr.sh`, `post-approved.sh`; wire into `init.sh` (copy-if-absent) and the lock / `--update` path; README structure table and lock hash list.
2. Dogfood on a real PR of the kit itself; verify the gate holds (nothing posted without an exact `[x] approve`), the battery runs all 6 passes, cross-objective merge behaves, costs match the sessions DB.
3. After two dogfooded PRs: move this doc's final state into `DESIGNS.md` per the kit's designs-archive convention.

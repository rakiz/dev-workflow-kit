# Design: `pr-review` — multi-model PR review pipeline

Status: DESIGN v2 (not implemented) · Date: 2026-10-23 · Owner: dev-workflow-kit
v2: finding-driven escalation only · single cheap rung by default · semantic dedup · haiku 100k-cliff handling · FP-weighted glm corroboration · mechanical gate · secret handling.

## Goal

A PR-review flow that runs one cheap review rung by default, escalates to strong rungs only on
demonstrated need, and produces PR-ready draft comments posted **only after explicit user approval
via a mechanical gate**. Every reviewer reads the same PR diff with a precise, tier-appropriate
checklist, never modifies anything, and its cost is visible to the user.

Verifiable end state: given a PR number, the flow produces (a) an auditable report — which model found what, corroborations and conflicts, FP judgment, cost per model — and (b) a staged draft of PR comments, of which exactly the user-approved subset is posted via `gh`.

## Non-goals

- **No auto-posting, ever.** The only `gh` write is `post-approved.sh`, which posts exclusively blocks the user ticked.
- **No CI mode** (interactive skill; CI replay can come later). **No fixing** (reviewers propose, never patch). **GitHub only, for v1** (the scripts speak `gh`; other forges are v2).
- **No new agent definitions.** The rungs are the existing global-roster agents; their agent
  prompts are unchanged — all PR-specific instructions live in the brief. Models named anywhere in
  this doc are whatever `models.json`'s global roster currently binds to those rungs, per the
  table below — they are bindings, not new agents.

## Rungs and model bindings

| Rung (existing agent, prompt unchanged) | Current binding (models.json roster) |
|---|---|
| cheap-review | haiku 5.5 |
| strong-review | glm-flash `high` |
| strong-review-alternative / -alternative2 | per roster lineage rules |
| cheap-review slot, large-context branch (same rung, different model binding) | deepseek-v4p1-flash-1017 `medium` — the roster's documented >100k cliff-free fallback; selected when the brief requires the whole large context at once, never as a second parallel rung |

When the roster is re-arbitrated, only this table changes; the flow, checklists and gate reference
agents, never model names.

## Chosen flow

**A new skill (`skill/pr-review/SKILL.md`) + two small scripts (`fetch-pr.sh` read-only,
`post-approved.sh` the only poster), reusing the global-roster review agents.** Orchestration
happens in the primary session — the orchestrator must enforce cost accounting and the user gates,
and sub-agents cannot ask the user questions.

```
user: "review PR 123" (skill triggers on: pr-review / review PR <n>)
  ├─ 1. FETCH (read-only)   fetch-pr.sh → staging dir: pr metadata, diff
  │       (base…head), changed files, CI status. NO checkout, NO branch
  │       switch, NO writes outside the staging dir.
  ├─ 2. BRIEF               one brief per rung: diff size + touched paths +
  │       checklist + grounding rules + safety rules + FP-discipline clause.
  ├─ 3. CHEAP RUNG          the cheap-review rung (its current binding, table
  │       above), single rung by default. Size thresholds (below) decide
  │       chunking vs the large-context binding — same rung either way.
  ├─ 4. AGGREGATE           orchestrator semantic-merges findings (below).
  ├─ 5. ESCALATE?           finding-driven triggers only (below) →
  │       strong-review, then -alternative / -alternative2, each reading the
  │       previous rung's findings. Beyond strong-review: user's explicit go
  │       before the spend.
  ├─ 6. STAGE               PR-<n>-comments.md, one block per finding: severity,
  │       provenance (model, cost), confidence, proposed body. User approves /
  │       edits / rejects EACH block individually (own [x] approve tick).
  └─ 7. POST + REPORT       post-approved.sh (the mechanical gate) posts only
          [x] approve blocks via `gh pr review --comment`. Then the report.
```

Hard safety rule, repeated in every brief and in the skill: **reviewers and the orchestrator are read-only — no file edits, no git mutations, no `gh` writes.** This is defense in depth only: prompt enforcement is NOT protection, because the orchestrator reads untrusted PR content (a malicious PR can carry injected instructions). The real protection is structural: reviewers have `permission: edit: deny`, and the only posting path is `post-approved.sh`, which nothing but the user's ticks can activate.

## Size thresholds (two knobs, one system)

| Threshold | Level | Behavior when exceeded |
|---|---|---|
| Hard diff-size cap | `fetch-pr.sh` (script) | refuse and offer a chunked review (per-file-group runs) — never silent truncation |
| ~90k-token prompt budget | brief (orchestrator) | split the brief into chunks reviewed by the same rung |

**Relation:** the script cap exists so the ~90k prompt threshold is always reachable by chunking — the cap keeps individual diffs small enough that the brief-level budget can be met by splitting; if a review genuinely needs the whole context in one prompt, that is the large-context binding's job (table above), still the same cheap rung.

## Per-rung checklists

**Cheap rung (cheap-review)** — the T3 rubric on a PR diff, evidence-backed: (1) real defects —
logic, off-by-one, wrong variable, broken edge case; must cite `file:line` and *why*; (2) data
loss / silent failure — swallowed errors, `except: pass`, a success path that can lie; (3)
contract breaks — callers of touched functions (check the callers, not just the modified file),
changed return shapes, removed API; (4) security — injection, path traversal, unvalidated input,
secrets in the diff; (5) missing tests — new behavior untested, bug fix without red/green
evidence; (6) FP discipline — a finding without a concrete mechanism is an FP; never padded to
look thorough (3×-penalty rule, in every brief).

**Strong rung (strong-review, then alternatives)** — the cheap findings are attached and assumed
incomplete: (1) cross-system impact — blast radius beyond this repo's callers, config/infra
coupling, rollout/rollback; (2) architecture — wrong layering, duplicated abstraction; (3) subtle
correctness — concurrency, ordering, idempotency, partial failure; (4) adjudication
(brief-carried; the strong-review agent prompt is unchanged) — confirm/refute each unresolved
cheap finding, including FP call-outs it can disprove; (5) what the previous family missed — the
brief names the previous rung's model family so the lineage rule is explicit. Alternatives rungs
run only after the previous rung stalled or expressed doubt; `-alternative2` also states what a
human must decide.

**Grounding rules (all rungs):** review the diff **as new code** against the base — the PR
description and author claims are unverified claims to check; read the surroundings of every
touched file (callers, tests) — a reviewer that only read the diff must say `diff-only review`;
read `CONVENTIONS.md`/`RULES.md` when present; the brief carries diff line count, changed-file
list, and whether the PR fixes a reported bug (red/green expectation applies).

## Escalation policy (one policy, aligned everywhere)

**Triggered by findings only, never by diff shape.** Checked after aggregation: an unconfirmed
**major** finding (security, data loss, contract break) → strong-review; a **conflict** between
reviewers on the same finding → strong-review (adjudication); a reviewer's explicit `diff-only
review` or uncertainty statement → strong-review.

A reviewer's self-reported confidence is **evidence for the report, never a trigger by itself** —
triggers stay the three deterministic ones above. "Confident, clean" from one reviewer does NOT
outvote a major finding from another: that disagreement IS a cross-reviewer conflict → escalate.

A large diff or sensitive path (auth, migrations, money, concurrency) is **never** an automatic
trigger — it becomes a user-facing SUGGESTION ("large or sensitive diff — run the strong rung?");
the pipeline never spends on diff shape. Doubt/stall from a strong rung →
strong-review-alternative, then -alternative2. No trigger → stop after the cheap rung, never
speculatively.

## Findings aggregation (semantic merge, no deterministic key)

Findings come back in the existing one-line format (`severity — file:line — problem — expected action`) plus `reviewed`/`not reviewed` axis statements and an overall verdict. The orchestrator performs a **semantic merge** — a judgment call, not a key match: same defect named by ≥2 reviewers = corroborated (`confidence: 2 models`), severity takes the max; wording may differ and locations may be lines apart. A **conflict** (same location/category with opposite verdicts, or a strong rung refuting a cheap finding) is never self-resolved — it escalates.

**Corroboration by the strong rung is not independent confidence when both bindings share a lineage** (strong-review currently binds glm-flash `high`, measured 2 FPs on v1 T3): a glm-only finding raises severity only with mechanism-level proof in its own text, and the glm brief carries the FP-discipline clause explicitly. glm never runs as haiku's parallel corroborator AND first escalation rung (no-op escalation); the report notes the lineage overlap when both ran. A finding no rung corroborates and the strongest rung does not confirm is staged `low-confidence` (posted only if the user keeps it) and flagged as a probable FP in the report, never silently dropped.

## The mechanical approval gate

- **Staging file** `PR-<n>-comments.md`, one block per finding, each with its own status line:

```markdown
## [F2] major — src/sync.py:87 — silent copy failure can report `done`
- provenance: found by cheap-review (haiku 5.5, $0.002)
- confidence: high (2 models)   <!-- or: low — possible FP -->
- status: [ ] approve / [x] reject / edited
<!-- comment body below — this exact text is posted if approved -->
**Bug**: `copy_file` swallows `OSError` ...
```

- **`post-approved.sh` is the gate, not a prompt.** It parses the staging file and posts ONLY blocks carrying an exact `[x] approve` tick (with their own, possibly edited bodies) via `gh pr review --comment`; each block needs its own tick — no batch approve exists, and the tick is the only signal the script reads. No other code path can post; the orchestrator does not post, it runs the script, and the script's parse is the authority. Prompt-enforcement is not protection here either: the orchestrator reads untrusted PR content, so the gate must be a script that cannot be talked past.
- **Secret handling**: a secret finding is never staged as a PR comment — it is surfaced to the user in the report with `file:line` only, no value (rotate outside the PR). The staging dir defaults OUTSIDE the repo (temp dir); if the user opts into the in-repo path, the `.pr-review/` gitignore rule is verified before the diff is written there. The user is warned up front that the fetched diff (possibly containing secrets) is shipped to the model providers.
- Rejected findings stay in the staging file (audit trail).

## File layout

`skill/pr-review/` holds three files: `SKILL.md` (triggers "review PR `<n>`", flow, checklists, gate rules), `fetch-pr.sh` (read-only: `gh pr view`/`diff` → staging dir; diff-size cap) and `post-approved.sh` (the mechanical gate: `[x] approve` blocks → `gh pr review`).

Installed to `.opencode/skill/pr-review/` by `init.sh` (copy-if-absent, `--update` syncs it). Runtime artifacts per PR, in the staging dir (temp dir by default; see secret handling): `PR-<n>/` (fetched context), `PR-<n>-comments.md` (the gate input), `PR-<n>-report.md` (the audit output). No change to `dev-workflow.json` schema.

## Cost accounting

Reference costs ship in the skill so the user sees the ladder before spending: cheap-review ~$0.0063/task, strong-review ~$0.008/task, strong-review-alternative ~$0.119/task, -alternative2 ~$0.151/task (per-task labels, from `MODELS.md`/`EVALS.md`), with a context-size qualifier: the ~$0.007 cheap floor is the small-diff case only — a review routed to the large-context binding (deepseek-v4p1-flash-1017 `medium`, through cheap-review's slot) costs more and is priced as such. Actual costs come from the opencode sessions DB per rung, child sessions extracted by `session.parent_id` (not by title), applying the delegation rule (parent + all named children). Budget defaults: cheap rung always runs; strong rung only on trigger; alternative rungs only on expressed doubt; escalation beyond strong-review is behind the user gate.

## Rollout

1. Add `SKILL.md`, `fetch-pr.sh`, `post-approved.sh`; wire into `init.sh` (copy-if-absent) and the lock / `--update` path; README structure table and lock hash list.
2. Dogfood on a real PR of the kit itself; verify the gate holds (nothing posted without an exact `[x] approve`), the report is complete, costs match the sessions DB.
3. After two dogfooded PRs: move this doc's final state into `DESIGNS.md` per the kit's designs-archive convention.

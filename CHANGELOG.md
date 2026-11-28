# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed
- Dev-workflow skill and review prompts: review briefs bound re-verification — each claimed
  total is re-run once against the commit with output redirected to a file, reading stays in
  the diff scope, extra checks need a stated suspicion, and the hook owns the full gate run.
  A return from a session flagged compacted or over the context cap is suspect: its verdict
  is not accepted, and it is re-dispatched fresh with a narrower brief, never resumed. The
  reviewer checklist fragment carries the same bound into the five spliced review rungs.
- Orchestrator compaction: `/compact` is suggested only at a closed boundary (a wave or phase
  committed, or a different subject starting), never with a dispatch in flight, an unpersisted
  return or a fix round open; the configured dispatch threshold (dev-workflow.json, usage
  section) moves the compact forward to the next closed boundary. The orchestrator cap uses
  decidable signals (committed wave or phase, the ledger's dispatch count), not token counts,
  and any compaction, yours or the harness's, is treated as a resume: re-read the ledger,
  reconcile against git, confirm open attempts before the next dispatch.
- Dev-workflow skill and INPROGRESS template: every subagent return is persisted when it
  arrives, and the ledger holds a digest (attempt-id echo, status, file list, numbers with
  their artifact path, finding ids with `file:line`), not the verbatim return; the `task_id`
  stays in its own pipe field.
- Long command outputs land in a file referenced by path (the reviewer fragment and the §1
  execution-first brief); context reads the tail or a grep, never the full output.
- Usage recorder: a `usage` section in `dev-workflow.json` (`child_context_cap` default
  100000, `dispatch_threshold` default 10); the plugin records per-child peak context,
  compactions (host `session.compacted` event, or a context drop: previous context above the
  cap and new under half of the previous, same session, never double-counted with the event)
  and cap crossings;
  `dwk stats --context` (also `/dwk --context`) reports them with the dispatch-threshold
  note; `dwk/usage-selftest.mjs` covers them and runs in `scripts/smoke.sh`.
- Evidence: one fresh review dispatch filled a 1M window to 98% through unbounded
  re-verification and was silently auto-compacted mid-mission; its return did not mention it
  (adopter-reported, 2026-11-28; archived in `docs/history/2026-11-28-orchestrator-context/`).

## [0.9.3] - 2026-11-28

### Changed
- Dev-workflow skill: implementation briefs are execution-first (§1) — settled facts are
  inlined, open verification moves to the design step or a verify-only dispatch, writes
  are ordered and verified by execution, and rescue briefs shrink instead of growing. The
  §7 empty-return rule becomes a recovery table: worktree inspection, at most one
  resume-for-facts, a verified design rerouted down the ladder to the standard implementer
  (lane guards kept: rigorous review budget, reviewer family distinct from the new
  producer), otherwise escalation; the same brief shape is never re-dispatched unchanged.
- Agent prompts gain the attempt-id prefix (`attempt <id>:`), a never-empty-final-message
  rule, and a checkpoint stop after about 15 tool calls without a write: implementers
  `impl`, `cheap-code`, `cheap-mech`, `strong-code`, `strong-code-alternative` and
  `strong-code-alternative2`; consult rung `deep` (checkpoint without a conclusion, no
  write). The four global code rungs (cheap-code, strong-code and both alternatives) also
  stop re-deriving brief-settled facts: reading is narrowed to the files the brief names,
  and proof of the change comes after the write.
- Evidence: 5 dead sessions (completed, empty payload, zero writes) before the change vs
  6/6 healthy dispatches after it (adopter-reported, 2026-11-28; archived in
  `docs/history/2026-11-28-empty-returns/`). Open question: the evidence does not separate
  brief shape from reasoning effort (`variant`) as the exhaustion mechanism; the
  distinguishing experiment is a same-brief re-run at a lower variant, with telemetry
  (tool-call count and reasoning tokens per turn).

## [0.9.2] - 2026-11-28

### Changed
- Agent permission denies widened: `git -C . push` and `git  push` (double space) are
  now caught too, and the read-only rungs (explore, review, design-review) state
  explicitly that bash must not write.
- `/dwk` rejects arguments outside its accepted forms instead of passing them raw to
  the shell.
- The 16 global roster rungs get the same widened `*git*push*` deny as the project
  agents; the seven read-only rungs also state explicitly that bash must not write.

### Fixed
- `--update` now upgrades a kit-installed pre-commit hook: the lock records a
  `hook/pre-commit` baseline and `--update` overwrites a kit-version hook (legacy
  installs detected via the kit's git history). A user-authored hook is still kept, with
  the kit hook parked as an inactive sibling.
- Symlinked directories are refused fail-closed with a warning across every lock-derived
  and usage install path (a committed symlinked dir inside a cloned repo could redirect
  writes or removals outside the project); orphan keys are pruned, and the git hooks path
  (incl. `core.hooksPath`) is guarded too.
- A symlinked `.opencode` in the target project now makes install/`--update` refuse with
  a non-zero exit instead of half-installing and writing the lock outside the project.
- The pre-commit hook no longer silently skips a check entry with an unknown `builtin`
  name or fails open on non-object entries — both now block the commit (fail-closed,
  matching the hook's stated contract).
- The pre-commit hook's CHANGELOG exemption now matches only the configured root
  changelog path, not any `*/CHANGELOG.md` in the tree.
- `/dwk` runs the installed stats script instead of the kit checkout (the installed copy
  was dead, so moving the checkout broke `/dwk`); the models.json path is baked in at
  install via a new `--models` flag, and the sed substitution behind it escapes `|`, `&`
  and `\`.
- `/dwk --project` no longer matches sibling directories by string prefix.
- `/dwk live` renders once and exits on a non-TTY instead of hanging non-interactive
  callers (an agent's shell tool waited for a forever-interval).
- The usage recorder plugin persists (capped) message ids across restarts, so a restart
  can no longer double-count replayed events.

## [0.9.1] - 2026-11-27

### Added
- The human is right by default (skill §1): what the human states about their intent,
  project, layout or history is the working premise — act on it first, never silently
  override it; acting against one requires proof and a concrete example plus their
  confirmation; on a human-vs-artifact collision, show it and ask (the artifact may be
  the stale side).
- Wave lanes and budget (dev-workflow skill §1): each wave is tagged `fast`/`rigorous`
  at the design step — mechanical/standard ⇒ fast unless the wave introduces a contract,
  measured numbers or fail-closed gates ⇒ rigorous; rigorous core units route to the
  strong implementation rung at design time (explicit exception to after-failure
  escalation; an architectural task still passes its design gate); per-wave dispatch
  budget (fast = impl + 1 review; rigorous = impl + review + fix + delta re-review)
  with a hard stop past +2 dispatches; after the §7 recovery check, one stalled return
  on a rigorous unit escalates the rung — scope-halving is not a substitute.
- Wave sizing (skill §1): a wave spans at most about two unrelated deliverables —
  beyond that, split into separate waves with separate commit proposals.
- One home per number (skill §3 baseline): a measured or derived result value lives in
  the artifact that produced it; other documents reference it by path/name and never
  restate it as current truth (dated snapshots with reference allowed in CHANGELOG and
  commit messages; a project `workflow.rules` restatement convention wins; otherwise
  restatements only in DESIGNS.md history).
- Review agents (`review`, `cheap-review`): a number restated outside its home artifact
  is a minor finding — replace the copy by a reference, not a re-sync.
- INPROGRESS template: a wave opens its ledger with a
  `wave <n> | lane fast|rigorous | budget <k> dispatches` header line.

Evidence: a real 12-dispatch wave (5 deliverables under one review, 2 pure stalls cured
by scope-halving instead of rung escalation, 5 of 9 major findings stale or duplicated
numbers, +3,187 lines) replays at ~5 dispatches under these rules at equal quality (owner-reported, 2026-11-27 retro).

## [0.9.0] - 2026-11-27

### Security
- Lock-key sanitization (`f768f7b`): every lock key is classified before any path is
  built from it. Keys containing `..`, a leading `/`, a newline, or any shape outside
  `agent/<name>.md`, `skill/...`, `CONVENTIONS*.md` and `RULES*.md` are pruned from the
  lock with no file touched. A traversal key can no longer delete or overwrite a file
  outside the managed directory.
- Lock keys are iterated NUL-separated (`c78794b`), so a key containing a newline is
  read whole and cannot dodge pruning.

### Added
- Budget and decision log in the INPROGRESS template: a budget line (cap, per-child and max-children, placeholders until the owner rules) with a running spent line, and a decision log with the shapes of the deep-gate and arbitration entries.
- Delegation ledger dispatch lines carry the child session id as task_id=, so the usage recorder can join per-task cost.
- Self-check fails on a retired name in shipped text (skill, templates, agent prompts, global roster prompts, pre-commit hook), with a whitelist for legal mentions (empty today).
- Self-check fails on any root-level markdown file outside README, CHANGELOG, EVALS and (until the next phase) AUTONOMOUS-RUN.
- README doc map: a table of who each documentation file is for and whether it is tracked in git.
- README permission rails state the push rule: one authorization covers exactly one push.
- `init.sh --doctor` (`819cc32`): read-only drift report for `--global` or a target.
  Exit 0 clean, 1 drift, 2 precondition failed. It checks baselines, body vs kit,
  model/variant/family vs the effective value, pending `-new`/`-prev` siblings, orphan
  and out-of-pattern keys, and (`--global`) the roster generator and the usage files.
- Overrides file `dev-workflow-kit.overrides.json` (`1a7f268`): personal model/variant
  choices per agent, applied over `models.json`.
- Orphan removal with backups (`1a7f268`): a lock-proven agent the kit no longer ships
  is copied to `dev-workflow-kit-backup/<UTC timestamp>/`, then removed. Its lock entry
  is kept in `lock-entries.jsonl` (reported as "not archived" when no backup dir exists).
- Global `-prev` overwrite (`c78794b`): with `--update --global`, a diverged roster body
  is overwritten by the kit; the previous file is kept once as `<file>.dev-workflow-kit-prev`.
- Stale sibling cleanup (`c78794b`, `334b848`): a `.dev-workflow-kit-new` whose body
  equals the kit again is removed and reported.
- Roster generator (`c78794b`, `334b848`): `roster/build.sh` writes the MODELS.md
  generated region and `roster/injected-preview.md` from `models.json`. `--check` exits 1
  on drift. Markers must appear exactly once, else it refuses.
- Fail-closed deploy gate (`c78794b`): `init.sh --global` (install and `--update`)
  refuses while `roster/build.sh --check` fails, and names the fix.
- Self-check manifest (`c0812f8`, `c78794b`): lock key shapes are listed in
  `LOCK_KEY_MANIFEST`, and every key the kit tree derives is asserted to be a strict path.
  The roster check runs too.
- Usage recorder and `/dwk` (`6275774`), opt-in for `--global`: `plugin/dwk-usage.js`
  (append-only JSONL under `~/.local/share/dev-workflow-kit/usage/`, one record per
  completed assistant message and per session), `command/dwk.md`, `dwk/stats.mjs`
  (`today|week|month|range`, `--project`, `--by`, `live`, `--prune` at 13 months).
  Install asks on a TTY (default yes); `--no-usage` skips it; the choice is recorded
  in the lock (`usage_enabled`). `--update --global --no-usage` removes the files.
- `models.json` `prices` section (`6275774`): reserved for the usage recorder. All eight
  rates are **null** (unsourced); until a catchup fills them, costs print as `$?`.
- `scripts/smoke.sh` (`778be3f`, `334b848`, `6275774`): sandbox end-to-end gate (global
  and project install, update twice, doctor, zero stray siblings or backups), the
  `_lock_key_kind` table with newline keys, the R1 scenarios, and the usage component.
- `scripts/release.sh` (`778be3f`, `334b848`): runs `--self-check`, `build.sh --check`
  and smoke, and prints the release steps. It writes no release files and never pushes.
- Usage recorder stores `start_ts` (message start) next to `ts` (completion); `dwk stats` shows a `tok/s` column per group, and `--by task` attributes messages through the project ledger's `task_id=` lines.

### Changed
- Reviewer checklist single-sourced: `roster/fragments/review-checklist.md` is spliced into the review rung prompts between generated markers by `roster/build.sh` (checked by `--check`).
- Net effect of the checklist single-sourcing: the five code-review rungs (review, cheap-review, strong-review, and the two strong-review alternatives) share one checklist (the union of their common lenses), and it is inlined as a generated region that `--check` enforces. The two strong-review alternatives keep their rung-specific design-tradeoffs lens outside the shared region. The three design-review rungs keep their own rung-specific lenses by design: each is a different lens with no shared contract to single-source.
- Dev-workflow skill rewritten to the v2.1 text, condensed to about 95 lines. It adds the rule that nothing is true without proof, the commit and push authorization profile, a bound of two review rounds (a fresh second round, no third; an agreed major moves to the next implementer rung, a contested one goes to arbitration or to the user), escalation only on demonstrated failure, resume-or-fresh by phase, a context cap of about 100K tokens per agent session, and status questions answered with status only. The periodic review is condensed to a proposal-only retro with at most two changes.
- File formats moved out of the skill into the template headers: TODO is the roadmap only, CHANGELOG carries the net-change, undo, revert and versioning rules (VERSION and tag decided together at release), DESIGNS is a non-normative archive, and the companion format and enforcement scope are in the README.
- Coding conventions: the three baseline rules are an always-apply block at the top of the CONVENTIONS template; the skill points at it.
- Pre-commit hook header is the single statement of the builtin names and their semantics. The shipped template enables only the companion builtin.
- Shipped dev-workflow.json template: the companion check is labelled companion_md_exists (was companions_exist). New installs only; an existing config is never touched.
- Hand-set `model:`/`variant:` lines migrate (`1a7f268`). The first `--update` moves a
  hand-set value into the overrides file, reports it under "Migrated", and the overrides
  file wins over `models.json`. The former "kept as-is" behaviour no longer exists.
  A value equal to the kit default is never pinned. When the kit default has no variant,
  migrating the model removes the `variant:` line.
- Variant override rule (`1a7f268`): a variant override applies only with its model. When
  the override names a different model, the kit's variant does not carry over.
- Bootstrap verdict (`c78794b`): a diverged body with no lock baseline is reported as
  "diverged, origin unknown", never as "customized", with a `diff` size against the kit.
- Body equal to the kit with a stale lock baseline counts as current, and the baseline is
  refreshed (`c78794b`).
- The family-unknown warning fires once per (file, model) per run (`334b848`). A missing
  `model:` line is no longer reported as an unknown family.
- Planning and docs (`89012b1`): README "Updating" and the `init.sh` header describe the
  shipped behaviour, including the `--doctor` exit codes.
- Cleanup: deployed roster reconciled with the kit. The 17 parked
  `*.dev-workflow-kit-new` siblings and the vacated `strong-design-review-alternative2`
  rung (stale `grok-4.7` mapping) are removed from `~/.config/opencode/agent/`.
  Verification before deletion: 17/17 roster bodies identical (model/variant/family
  lines stripped) (owner-reported; per-file hashes not recorded — not re-auditable, see
  docs/history/2026-11-26-p0-deletion-evidence.md).
- Hygiene: `docs/` is tracked (`plans/`, `history/`); `scratch/` is gitignored for
  owner-private material. Archived `docs/history/2026-11-23-improvement-plan.md` and
  `docs/history/2026-11-25-workflow-v2-proposal.md` (verbatim). Active plan moved to
  `docs/plans/workflow-v2.1.md`. Backlog, PDF and GIF moved to `scratch/`.
- Loose root scripts (`status.sh`, `status-tui.sh`, `session-detail.sh`) and the
  untracked `.opencode/command/status.md` retired out of the repo to
  `~/.local/share/dwk-retired-scripts/`. D-A11 said "dotfiles", but no dotfiles repo
  exists on this host; the owner will re-home them.
- Interim gap: `/status` (from `.opencode/command/status.md`) no longer exists until
  `/dwk` ships in P1, which replaces the sessions/spend view.
- Doc reconciliation with the vacated rung: `roster/MODELS.md` (roster list, impl and
  review per-role lines matched to `models.json`, rung row set to "vacant → STOP");
  `README.md` (16 session-roster agents, file list, paragraph count and names).
- Dangling escalations fixed: `strong-design-review-alternative.md` and
  `strong-design-review.md` no longer escalate to the deleted agent. Re-deployed with
  `init.sh --global --update`.
- `.gitignore`: `/AUTONOMOUS-RUN.md` ignored (its disposition is P3).
- Evidence record: `docs/history/2026-11-26-p0-deletion-evidence.md`.

### Removed
- `roster/global-agent/strong-design-review-alternative2.md` (rung vacated).

### Fixed
- The opt-in `no_history_comments` builtin blocked history-narrating lines in the changelog itself. The changelog (`workflow.changelog`, default CHANGELOG.md) is now exempt, as the convention rule always stated.

### Verified (A1-A5 plugin probe, 2026-11-27, opencode 1.19.6)
The raw evidence is in [docs/history/2026-11-27-usage-probe/](docs/history/2026-11-27-usage-probe/VERDICT.md)
(moved from `evals/` in this release; it is a kit verification record, not an eval).
- A1 cost populated: holds on `github-copilot` and `ai-gateway-misc`. No estimate needed.
- A2 `mode` equals the agent name: holds.
- A3 completion fires once: does **not** hold. `message.updated` fires about three times
  per message, so the recorder dedupes by message id.
- A4 `gen/` types match the runtime fields used: holds for those fields. The v2 types were
  not compared.
- A5 a command runs a script without an LLM turn: does **not** hold. `/dwk` routes
  through `cheap-mech`, the fallback the plan named.

### Known limits
- `prices` are unsourced (null). `$?` is shown until a catchup fills them.
- `/dwk stats --by task` prints `-` for messages the project ledger cannot attribute: no session project root, or no ledger line with `task_id=<session id>` (count and causes reported in a note).
- `scripts/release.sh` prints the release steps. It does not write CHANGELOG.md or VERSION
  itself; the maintainer does, then tags (plan §5A.2 deviation).
- Module split of `init.sh` (plan §5A.4) is still pending (P6).

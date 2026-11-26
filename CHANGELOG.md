# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.8.1] - 2026-11-26

### Changed
- Cleanup: deployed roster reconciled with the kit. The 17 parked
  `*.dev-workflow-kit-new` siblings and the vacated `strong-design-review-alternative2`
  rung (stale `grok-4.7` mapping) are removed from `~/.config/opencode/agent/`.
  Verification before deletion: 17/17 roster bodies identical (model/variant/family
  lines stripped).
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

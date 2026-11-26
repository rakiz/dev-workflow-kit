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
  untracked `.opencode/command/status.md` retired out of the repo.

### Removed
- `roster/global-agent/strong-design-review-alternative2.md` (rung vacated).

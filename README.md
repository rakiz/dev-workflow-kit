# dev-workflow-kit

**TL;DR — this repo contains three things:**

1. **A reusable dev-workflow kit with file-based memory** for [opencode](https://opencode.ai) projects (AI agents + CLI). It ships five generic agents (impl, review, explore, design-review, deep), a task-management skill (TODO.md → INPROGRESS.md → CHANGELOG.md), a configurable pre-commit hook, conventions templates and starter files. Every implementation pass is reviewed at commit time (mandatory), and designs are written before code. The skill is [workflow/skill/dev-workflow/SKILL.md](workflow/skill/dev-workflow/SKILL.md); the agents are in [workflow/agent/](workflow/agent/). Adoption: `git clone` + [init.sh](init.sh), run per project. Each project keeps its own `dev-workflow.json` and diverges freely. Everything is copied, never symlinked. `--global` additionally installs a session-level agent roster ([Global roster](#global-roster)).
2. **A model roster** ([roster/models.json](roster/models.json) + [roster/MODELS.md](roster/MODELS.md)). It assigns a model (and reasoning variant) to every seat: orchestration, cheap and strong code, design, and their review gates. Each seat holds the best model for its price on the kit's own benches. Routing rules say who reviews whom; reviews are always cross-family. Each seat has documented fallbacks. The seat-by-seat rationale is in [MODELS.md](roster/MODELS.md). Cheap models do the bulk of the work, expensive models only escalate, and quality is recovered through cross-lineage review.
3. **The model-evaluation machinery** ([evals/](evals/)). Five decision benches: orchestration (/8), code review (/3 + bonus), design review (/14), implementation (/14), design writing (/11). They are scored by a multi-family panel; no family scores its own runs. Limitation: the benches measure verification discipline on small fixtures, not long-horizon generative ability, which is too expensive to bench (see the "What these benches measure" section of the HTML leaderboard linked below).

- **Rendered leaderboard (roster + charts + rationale):** https://rakiz.github.io/dev-workflow-kit/evals/LEADERBOARD.html
- **Bench methodology:** [evals/PROTOCOL.md](evals/PROTOCOL.md) (the contract) + [evals/BENCH-V3-DESIGN.md](evals/BENCH-V3-DESIGN.md) (the bench specs)
- **The numbers:** [evals/2026-11-16/grid2-scores.csv](evals/2026-11-16/grid2-scores.csv) (per-cell official panel means) → [grid2-run-scores.tsv](evals/2026-11-16/grid2-run-scores.tsv) (per-run) → [runs/](evals/2026-11-16/runs/) (deliverables)

## Releasing (kit maintainers)

The version number is decided **at release time** (the push), never during development. Between releases the root [VERSION](VERSION) file stays at the **last delivered** version and [CHANGELOG.md](CHANGELOG.md) accumulates under `[Unreleased]`. At delivery, judge the whole unreleased batch and pick the bump: breaking → next major, features → next minor, fixes → next patch. Only then bump the root [VERSION](VERSION) file and the git tag together — [VERSION](VERSION) is the single source of truth for the kit version that installs announce and that the lock file's `kit_version` records (no git-describe fallback: the kit can be copied without `.git`).

## Quick start

### A. New project (empty or near-empty repo)

```sh
git clone https://github.com/rakiz/dev-workflow-kit ~/dev-workflow-kit   # once — or reuse an existing clone
cd ~/my-new-project && git init                   # if not already a git repo
~/dev-workflow-kit/init.sh                        # run from inside the target project
# add --with-rules to also install RULES.md (otherwise asked interactively)
# companions are auto-detected on fresh installs: enabled for a greenfield project or when companions are already in use, asked/disabled for an existing codebase without them (--companions=on|off to override)
# later: ~/dev-workflow-kit/init.sh --update syncs kit changes into this project (see "Updating" below)
```

What the install actually puts in the project:

- `.opencode/agent/*.md` — the five subagents (`impl`, `review`, `explore`, `design-review`, `deep`), with their default model (and reasoning `variant` where configured) injected from the kit's [models.json](roster/models.json);
- `.opencode/skill/dev-workflow/SKILL.md` — the skill driving the TODO → INPROGRESS → CHANGELOG cycle, the companions and the commit checks;
- `.git/hooks/pre-commit` — the hook running the `dev-workflow.json` checks on every commit;
- `dev-workflow.json` (project root) — your config: pre-commit checks + paths of the workflow files;
- `TODO.md`, `INPROGRESS.md`, `CHANGELOG.md`, `SPEC.md`, `DESIGNS.md`, `CONVENTIONS.md` (project root) — starter skeletons, to fill in (`CHANGELOG.md`: entries accumulate under `[Unreleased]`; versions are decided at delivery);
- `RULES.md` (project root) — **opt-in** safety/robustness rules skeleton (JPL's Power of 10-inspired), not installed by default: pass `--with-rules` or answer the interactive y/N prompt (see the Installation table);
- `.opencode/.dev-workflow-kit-lock.json` — sync baseline (kit body hashes + injected models/variants, plus the rule/convention prefix hashes) used by `init.sh --update`; it also records `kit_version`, the kit release last synced — compare it to the kit's [VERSION](VERSION) file to tell whether an update is needed: `jq .kit_version .opencode/.dev-workflow-kit-lock.json`. Commit it (see "Updating").

### B. Existing project (already has code, maybe its own conventions or hook)

Same command — [init.sh](init.sh) is idempotent and non-destructive:

- it **never overwrites** an existing `dev-workflow.json`, `TODO.md`, `INPROGRESS.md`, `CHANGELOG.md`, `SPEC.md`, `DESIGNS.md` or `CONVENTIONS.md` (nor an opt-in `RULES.md`);
- it **never overwrites** a differing agent/skill file (treated as a local customization, warning + skip) or a differing existing pre-commit hook — the kit's hook is installed alongside as `pre-commit.dev-workflow-kit`, a file **Git does not execute**, for a manual merge.
- on a **fresh** `dev-workflow.json` (absent before the install), the installer auto-detects existing sources and companions to enable or disable the companions feature — an existing `dev-workflow.json` is never touched (see the config section below).

If the project already tracks work in a differently-named file (e.g. `ROADMAP.md` instead of `TODO.md`), edit `dev-workflow.json`'s `workflow.*` fields to point at the existing filenames — do not rename the project's files to match the kit.

### C. Day-to-day usage after install

Nothing changes about how you start opencode or which primary agent you use — keep using it normally. What the kit changes:

- **The `dev-workflow` skill auto-triggers** (via its frontmatter `description`) whenever the flow gets touched: starting a task, wrapping one up, prepping a commit. No manual invocation, no config wiring — opencode auto-scans `.opencode/skill/`.
- **The five subagents are not invoked automatically by name.** They are available for your primary agent to delegate to via the `task` tool when appropriate: implementation work → `impl`, then a mandatory `review`; a rabbit hole needing deeper reasoning → `deep`; read-only research → `explore`; an architecture decision before writing code → `design-review`. If your primary agent doesn't naturally reach for them, ask explicitly the first few times (e.g. "use the impl agent for this, then review it").
- **Pre-commit checks run automatically** on every `git commit` once the hook is installed — nothing to remember.

Known limitation: the skill does mandate a review-agent pass before any commit (`review`, or `cheap-review` from the global roster — the skill's step 6, 'Before proposing a commit'). However, nothing instructs a primary agent to **prefer** routing implementation work through `impl` + `review` instead of editing files directly itself — outside that commit-time pass, the subagents are described only from their own side (their frontmatter). Two pragmatic options if you want the pipeline enforced more strongly (documented, not automated): say it once at the start of a session, or add a one-line project-level `instructions` entry in the project's own `opencode.json` pointing at the skill/agents.

## Security

`dev-workflow.json` has the same trust level as a `Makefile`, a `package.json` script or a regular git hook: its `precommit.checks[].cmd` entries are executed by the shell under your identity on every commit. **Never merge a PR that modifies `dev-workflow.json` without reviewing it carefully** — a malicious `dev-workflow.json` means arbitrary code execution at the first commit after the clone.

### Permission rails (two layers)

The kit's git-write protection is two-layered, and the layers are intentionally different:

1. **Subagents (the 22 kit-shipped agent files) hard-`deny` push**: every `workflow/agent/*.md` and `roster/global-agent/*.md` carries `"*git push*": "deny"` (and `"*git commit*": "ask"`) in its frontmatter. A subagent never pushes — `deny` is a hard block, so an unattended background agent fails fast instead of popping an approval prompt nobody is there to answer.
2. **The orchestrator (your session) asks**: the push/commit approval lives in YOUR opencode config — the kit never writes `opencode.json(c)`. Recommended global block (the subagent denies above only protect the pipeline; without this block the top-level session is unrestricted):

```jsonc
// ~/.config/opencode/opencode.jsonc
{
  "permission": {
    "bash": {
      "*git push*": "ask",
      "*git commit*": "ask"
    }
  }
}
```

`deny` hard-blocks an action with no prompt; `ask` surfaces an approval you grant per call. Use `ask` at the orchestrator level, `deny` on the subagents. Edit the block by hand — kit installs and `--update` runs never touch it.

The push rule is one authorization per push: a push approval covers exactly one push. Commits may be batched under one authorization within the same task; each push needs its own explicit approval, never inferred from a commit approval or an earlier push.


## Prerequisites

- `git`
- `jq` — required by the pre-commit hook, **no fallback without jq**: `brew install jq` / `apt install jq`
- `opencode` (optional) — enables the model availability check at install time (see below)

## Doc map

Where each kind of documentation lives, who it is for, and whether it is tracked in git:

| Audience | Doc | Tracked |
|---|---|---|
| Kit user | README.md | yes |
| Installer CLI reference | `init.sh --help` (README links, never restates flags) | yes |
| Roster reader | roster/MODELS.md | yes |
| Roster prompts | roster/global-agent/*.md | yes |
| Workflow behavior | workflow/skill/*/SKILL.md | yes |
| File formats | workflow/templates/*.md headers | yes |
| Project-agent prompts | workflow/agent/*.md until P3 | yes |
| Release history | CHANGELOG.md | yes |
| Active plan | docs/plans/<name>.md | yes |
| Finished plans/proposals | docs/history/ (frozen) | yes |
| Eval readers | evals/ | yes |
| Owner journal/backlog | scratch/ (gitignored) | no |
| Usage data | ~/.local/share/dev-workflow-kit/usage/ (data, outside every repo) | no |

## Structure

```
dev-workflow-kit/
├── init.sh                  # installs the kit into a target project; --update re-syncs kit-managed files later
├── workflow/                # THE PIPELINE PRODUCT (per-project install)
│   ├── agent/               # 5 opencode agents → .opencode/agent/
│   │   ├── impl.md          #   default implementer, always followed by a review
│   │   ├── review.md        #   read-only review, minor/major findings
│   │   ├── explore.md       #   read-only codebase exploration
│   │   ├── design-review.md #   approach critique before writing code
│   │   └── deep.md          #   deep reasoning, last resort
│   ├── skill/dev-workflow/  # opencode skill → .opencode/skill/dev-workflow/
│   │   └── SKILL.md         #   TODO/INPROGRESS/CHANGELOG cycle, conventions, companions, commit, periodic review
│   ├── hooks/pre-commit.sh  # pre-commit hook driven by dev-workflow.json
│   └── templates/
│       ├── dev-workflow.json    # per-project config (pre-commit checks, paths, companions)
│       ├── TODO.md              # roadmap skeleton
│       ├── SPEC.md              # stable spec skeleton
│       ├── DESIGNS.md           # designs archive skeleton (as-implemented history)
│       ├── INPROGRESS.md        # current-state skeleton
│       ├── CHANGELOG.md         # changelog skeleton (Keep a Changelog)
│       ├── CONVENTIONS.md       # default coding rules skeleton (extend per project)
│       ├── RULES.md             # OPTIONAL safety/robustness rules, inspired by JPL's Power of 10 — NOT copied by default, opt-in (--with-rules or interactive prompt, see below)
│       ├── CONVENTIONS.cpp.md   # OPTIONAL C++ conventions reference — NOT copied by init.sh, opt-in (see below)
│       ├── CONVENTIONS.cpp23.md  # OPTIONAL second C++ conventions (C++23: no-exceptions/std::expected, companion .md docs, hot-path discipline) — NOT copied by init.sh, opt-in (see below)
│       ├── CONVENTIONS.python.md  # OPTIONAL Python conventions reference (type hints, failure postures, ruff) — NOT copied by init.sh, opt-in (see below)
│       └── CONVENTIONS.go.md  # OPTIONAL Go conventions reference (distilled from the Uber Go Style Guide) — NOT copied by init.sh, opt-in (see below)
├── roster/                  # THE MODEL ROSTER PRODUCT (who runs what)
│   ├── models.json          # default model (+ reasoning variant) per agent — single source of truth
│   ├── MODELS.md            # why each default model was chosen + replacement guide
│   └── global-agent/        # 16 session-roster agents → ~/.config/opencode/agent/ via --global (see "Global roster")
│       ├── cheap-code.md                        #   default cheap implementer, large-context work
│       ├── cheap-design.md                      #   cheap design producer — approach doc before code
│       ├── cheap-design-review.md               #   read-only design critique before code
│       ├── cheap-mech.md                        #   small mechanical edits
│       ├── cheap-review.md                      #   read-only cross-lineage review of cheap-code
│       ├── strong-code.md                       #   strong escalation rung (Claude), rare
│       ├── strong-code-alternative.md           #   cross-vendor escalation implementer
│       ├── strong-code-alternative2.md          #   terminal impl rung, before human
│       ├── strong-design.md                     #   strong design rung (1017), hard architectures
│       ├── strong-design-alternative.md         #   cross-vendor design escalation
│       ├── strong-design-alternative2.md        #   terminal design rung, before human
│       ├── strong-design-review.md              #   read-only cross-lineage critique of strong-design
│       ├── strong-design-review-alternative.md  #   cross-vendor design-review escalation
│       ├── strong-review.md                     #   read-only cross-lineage review of strong-code
│       ├── strong-review-alternative.md         #   reviews strong-code-alternative output from a different lineage, deeper re-review
│       └── strong-review-alternative2.md        #   terminal read-only audit (fresh family)
├── EVALS.md                 # eval summary — all models ever tested, one table
├── evals/LEADERBOARD.html   # the roster + charts, rendered: https://rakiz.github.io/dev-workflow-kit/evals/LEADERBOARD.html
├── VERSION                  # kit version (single line)
├── evals/                   # model-eval protocol, results and raw outputs — see evals/README.md
│   ├── README.md            #   protocol, the 5 benches, scoring checklist
│   ├── run-eval.sh          #   (superseded, git history only — retired 2026-11-17; current runners: run-eval-v4/v5.sh; run-eval-v6.sh drives the held-out campaigns)
│   ├── synccli-eval-repo/   #   test fixture (seeded defects), shipped as plain files
│   └── (dated dirs before 2026-10-14 were folded into EVALS.md and removed — see evals/README.md; 2026-09-29 held RESULTS.md + archived outputs)
├── docs/                      # improvement plan + design-review material
├── .gitignore               # local scratch files (Python caches, .DS_Store)
└── LICENSE                  # MIT
```

## Installation

```sh
git clone https://github.com/rakiz/dev-workflow-kit
```

From the kit:

```sh
./init.sh [--with-rules] [--companions=on|off] [--update] /path/to/target-project
# or, for the session-level roster (no target argument):
./init.sh [--update] --global
```

OR from the target project (both forms are equivalent):

```sh
cd /path/to/target-project
/path/to/dev-workflow-kit/init.sh [--with-rules] [--companions=on|off] [--update]
```

The script locates the kit by its own location (`dirname "$0"`); the target is the optional positional argument, or the current directory if absent (the `--with-rules`, `--companions` and `--update` flags may appear in any position). The target project must be a git repo, otherwise it errors out. `--companions=on|off` forces the companions setting of a **freshly created** `dev-workflow.json`, skipping auto-detection and the interactive prompt (warning-only no-op with `--global`/`--update`). `--update` is the update mode — see [Updating](#updating-syncing-kit-changes-into-a-project); without it the script performs the plain install described below. `--global` switches to global mode — no target argument, no git requirement, different destination (see [Global roster](#global-roster)); combining it with a positional target is a clean error.

| Source | Destination | Behavior |
|---|---|---|
| `workflow/agent/*.md` | `.opencode/agent/` | copied if absent; if present and **different** from the kit → kept + warning (local customization preserved) |
| `workflow/skill/dev-workflow/` | `.opencode/skill/dev-workflow/` | same |
| [workflow/hooks/pre-commit.sh](workflow/hooks/pre-commit.sh) | `.git/hooks/pre-commit` | installed if absent; if a **different** hook exists → copied as `pre-commit.dev-workflow-kit`, manual merge |
| `workflow/templates/dev-workflow.json` | project root | copied **only if absent**; on a fresh copy the companions setting is auto-detected (`--companions=on|off` to override) |
| `workflow/templates/TODO.md`, `SPEC.md`, `INPROGRESS.md`, `CHANGELOG.md`, `DESIGNS.md`, `CONVENTIONS.md` | project root | copied **only if absent** |
| `workflow/templates/RULES.md` | project root | **opt-in** — copied **only if absent** with `--with-rules`, or via an interactive y/N prompt when a TTY is available; otherwise skipped (copy it manually to opt in) |

**Every** successful install also writes/updates the lock file when `jq` and `shasum` are available; otherwise the install succeeds without one (warning only) and the next `--update` bootstraps conservatively. It is generated, not copied from the kit; commit it to the project's repo. Every successful sync stamps the kit's current [VERSION](VERSION) into the lock's `kit_version` field.

## Global roster

`./init.sh --global` installs the kit's **session roster** — sixteen general-purpose agents (`cheap-code`, `cheap-design`, `cheap-design-review`, `cheap-mech`, `cheap-review`, `strong-code`, `strong-code-alternative`, `strong-code-alternative2`, `strong-design`, `strong-design-alternative`, `strong-design-alternative2`, `strong-design-review`, `strong-design-review-alternative`, `strong-review`, `strong-review-alternative`, `strong-review-alternative2`) — into your opencode **user-level** config directory, so they are available in every session, in every project. Their roles and cost rationale are documented in [MODELS.md](roster/MODELS.md) ("Two scopes" and the global-roster section).

- **Destination**: `${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/agent/`. There is no `.opencode/` level here, unlike project mode — the config directory's `agent/` subdirectory *is* the agent directory. Set `OPENCODE_CONFIG_DIR` to target another config directory (created if absent); it is honored by `--global` only.
- **Models** come from the `"global"` section of the kit's [models.json](roster/models.json), through the same injection and availability-menu machinery as project mode. The lock file is `${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/.dev-workflow-kit-lock.json` — a separate file from any project's lock, same schema, so the two scopes sync independently with `--update --global`.
- **Migration from an inline roster**: if your `opencode.json(c)` defines agents in an inline `"agent"` block, those entries **shadow** the kit-managed files (inline config wins over agent files — the agent would keep running from the jsonc, not from the kit). `init.sh --global` detects every inline entry whose name matches a roster agent (a JSONC-aware parse, best effort) and warns insistently; it never edits the jsonc itself. Removing the inline roster entries by hand (keeping non-roster overrides like `build`/`plan`) is the migration step that makes the kit the single source of truth again.
- **Project wins**: when a name exists both globally and in a project installed by the kit, the project-level agent takes precedence in that project — this is wanted: the global roster is the fallback for projects (or ad-hoc work) without the kit's pipeline, and the roster agents' descriptions say so.

Nothing project-specific is touched by `--global`: no skill, no pre-commit hook, no `dev-workflow.json`, no rule/convention files — and no git repo is required (the config directory is not one). `--with-rules` and `--companions` have no effect with `--global` (a warning says so).

### Usage recorder and `/dwk` (opt-in, global)

`--global` also offers a **usage component**: an opencode plugin that records token use and cost per completed assistant message, plus a `/dwk` command that reports it. It is on by default; a TTY install asks first, and `--no-usage` skips it.

- **Install**: `./init.sh --global` (TTY: a yes/no question, default yes). `./init.sh --global --no-usage` skips it. The choice is recorded in the lock (`usage_enabled`).
- **Files** (under the config directory): `plugin/dwk-usage.js` (the recorder), `command/dwk.md` (the `/dwk` command, with the kit path written in), `dwk/stats.mjs` (the report script). `--update --global` keeps them in step; `--update --global --no-usage` removes them and records `false`. `--doctor --global` checks them.
- **Data**: `${XDG_DATA_HOME:-~/.local/share}/dev-workflow-kit/usage/YYYY-MM.jsonl`, append-only, one record per completed message and per session, outside any repo. Errors go to `usage/errors.log`; the recorder never blocks or fails a session.
- **Usage**: `/dwk` (this month, by model), `/dwk today|week|month|range YYYY-MM-DD YYYY-MM-DD`, with `--project PATH` and `--by model|agent|task`; `/dwk live` re-renders every 5 s. `node dwk/stats.mjs --prune` deletes usage files older than 13 months.
- **Cost**: the provider's reported cost is used when it is above zero. A zero cost is estimated from the token counts and the `prices` section of [models.json](roster/models.json) and labelled `est.`. A model with no rate prints `$?` — an unknown cost, never a silent zero. The `prices` rates ship **null** (unsourced); they are filled at the next catchup, so until then the costs print as `$?`.


## Default models

The kit ships default models per agent role in [models.json](roster/models.json) (impl runs a cheap bulk model, review runs a different model lineage than impl to avoid shared blind spots, deep gets the expensive reasoning model). [init.sh](init.sh) injects these into freshly copied agents — [models.json](roster/models.json) is the single source of truth, edit it to change the defaults. Several roles also pin a reasoning-effort `variant` (some pin `none`, others `low`/`high`/`medium`) — see [MODELS.md](roster/MODELS.md).

At install time, if the `opencode` CLI is available, each freshly copied agent's model is checked against its provider's model list (`opencode models <provider>`):

- model available → nothing to do;
- model unavailable but same-family candidates exist → an interactive menu proposes replacements (or keep as configured, or enter one manually) and rewrites the installed agent's frontmatter — the `variant` from [models.json](roster/models.json) is left as-is, since a different model may use a different effort scale;
- no candidate found → a warning points at [MODELS.md](roster/MODELS.md) (which documents the role each model plays and how to judge a replacement) and leaves the config as-is.

If `opencode` is not installed, the check is skipped with a warning — the model defaults are installed as-is. This step can never fail the install, and agents preserved because of a local customization are never touched. Under `--update`, the current [models.json](roster/models.json) defaults are re-applied to agents whose model was not changed since the last sync — the `variant:` line follows the same rule — see [Updating](#updating-syncing-kit-changes-into-a-project). See [MODELS.md](roster/MODELS.md) for the rationale behind each default.

## Per-project config: `dev-workflow.json`

```json
{
  "precommit": {
    "checks": [
      { "name": "tests", "cmd": "" },
      { "name": "companion_md_exists", "builtin": "companion_md_exists", "extensions": ["cpp", "h", "ts", "tsx"] }
    ]
  },
  "workflow": { "todo": "TODO.md", "inprogress": "INPROGRESS.md", "changelog": "CHANGELOG.md", "spec": "SPEC.md", "designs": "DESIGNS.md", "conventions": "CONVENTIONS.md", "rules": "RULES.md" },
  "companions": { "enabled": true }
}
```

- `precommit.checks[]`: the pre-commit checks — see [Extending pre-commit checks](#extending-pre-commit-checks) for the full contract (`cmd` entries and builtins).
- `companions.enabled: false`: the `companion_md_exists` builtin is skipped entirely, even if listed, and the skill creates no companion — the recommended setting when working on a pre-existing codebase you don't want to pollute with companion `.md` files (companions are a greenfield tool).
- Companion format and enforcement scope: a companion `.md` (same folder, same name as the source file) states the file's role, invariants and pitfalls. The hook enforces companions **only** for the extensions listed in the `companion_md_exists` check's `extensions` (default `["cpp", "h", "ts", "tsx"]`) — keep that list aligned with the project's languages; for any other extension the companion rule is the skill's, not the hook's. The creation/update rules are the skill's (SKILL.md §2).
- Fresh install: the installer auto-detects existing sources and companions and sets `companions.enabled` accordingly — companions already in use stay enabled; an existing codebase without companions is prompted about (or auto-disabled without a TTY, with a notice telling how to re-enable). `--companions=on|off` overrides the detection; an existing `dev-workflow.json` is never touched.
- `workflow`: paths of the files used by the `dev-workflow` skill. `workflow.conventions` points at the coding-conventions file the skill reads before writing or editing code (default `CONVENTIONS.md`). The optional `workflow.*` paths — `spec`, `designs`, `conventions`, `rules` — are conditional: the corresponding behavior is active only while the pointed-at file exists (delete the file or the key to turn that feature off); `todo`, `inprogress` and `changelog` are pure renames of the core cycle's files.
- `workflow.spec`: points at the stable-specs file (default `SPEC.md`) the skill re-reads before any commit that could deviate from it — a necessary deviation is flagged to the user, never decided alone.
- `workflow.designs`: points at the designs-archive file (default `DESIGNS.md`) where the skill writes one entry per completed task — the design as implemented, direction changes, rejected alternatives; a non-normative history (the SPEC stays authoritative), written at task completion before the `INPROGRESS.md` reset.
- `workflow.rules`: points at the optional safety/robustness rules file, read alongside the conventions (default `RULES.md`, inspired by JPL's Power of 10) — a violation there always requires an explicit, reviewable justification, which the review step can refuse.

## Optional language-specific conventions

`workflow/templates/CONVENTIONS.cpp.md` is an **opt-in** template that [init.sh](init.sh) never copies at install time: unlike `RULES.md` (opt-in via `--with-rules`/prompt but still copied by [init.sh](init.sh) when chosen), getting it into the project the first time is a manual copy. It is a language-specific reference (C++, and JS where noted) following a mature C++ codebase's conventions, for a project that wants them. A project that wants it copies the file into its root manually, then either references it from its own `CONVENTIONS.md`'s "Project rules" section with a one-line pointer, or appends its content directly into that section. Once it exists in the project, though, it is synced by `init.sh --update` like the other kit-authored convention files — kept up to date while untouched, frozen with a `.dev-workflow-kit-new` sibling when customized (whole-file sync; see [Updating](#updating-syncing-kit-changes-into-a-project) for the exact contract). `workflow/templates/CONVENTIONS.cpp23.md` is a second, independent C++ reference (C++23 / no-exceptions / `std::expected` style) under the exact same opt-in + whole-file sync contract. `workflow/templates/CONVENTIONS.python.md` is a Python reference (type-hinted, ruff, failure-posture driven) under the same opt-in + whole-file sync contract.

## Extending pre-commit checks

`dev-workflow.json`'s `precommit.checks[]` is the **single extension point** for pre-commit checks — for command-based checks you never need to touch [hooks/pre-commit.sh](workflow/hooks/pre-commit.sh):

- **add a check** — append an entry to `checks[]`:
  - `{ "name": "lint", "cmd": "npm run lint" }` — any shell command, run from the repo root on every commit; exit code 0 passes, any other exit code blocks the commit;
  - `{ "name": "...", "builtin": "..." }` — a hook-native check (builtins listed below);
- **change or remove a check** — edit or delete its entry; the hook re-reads `checks[]` on every commit, there is nothing else to wire.

An entry with an empty `cmd` and no `builtin` is silently skipped (that is how the template ships its `tests` check).

### Builtins

Builtin checks are implemented inside [hooks/pre-commit.sh](workflow/hooks/pre-commit.sh) itself — adding a **new builtin** means editing that file (and upstreaming it to the kit if you want it shared). Their names and their semantics are the contract in that file's header: that header is the single place to read them, and the single place to change them — this section deliberately does not restate them.

## Pre-commit hook

Behavior ([hooks/pre-commit.sh](workflow/hooks/pre-commit.sh) installed as `.git/hooks/pre-commit`):

- `dev-workflow.json` missing from the root → warning, commit **accepted** (the hook does not block a repo that has not adopted the kit yet);
- `dev-workflow.json` invalid JSON (unparseable) → clear message, commit **blocked** — a hard block, distinct from the invalid-`.precommit.checks`-type case below;
- `.precommit.checks` of an invalid type (e.g. a string) → clear message, commit **blocked**;
- failing `cmd` check → the check's stdout/stderr is shown, commit **blocked**;
- `.md` companions missing from the index (missing on disk, or present but not staged) → list shown, commit **blocked**;
- history-narrating markers found in added lines (opt-in `no_history_comments` builtin) → `file:line` + matched marker listed, commit **blocked**;
- on failure: summary of failed checks + exit 1, otherwise exit 0.

## Updating: syncing kit changes into a project

### Plain re-run (install semantics)

Re-running [init.sh](init.sh) on the project (no flags needed):

- the **agents and the skill** are copied if absent; if they differ from the kit (local customization: edited content…), they are **never overwritten** — a warning lists the affected files, to compare/merge by hand;
- `dev-workflow.json`, `TODO.md`, `SPEC.md`, `INPROGRESS.md`, `CHANGELOG.md`, `DESIGNS.md`, `CONVENTIONS.md` are **never overwritten** (nor an opt-in `RULES.md`);
- your pre-commit hook, if it exists and differs from the kit, is kept: the kit's hook lands in `pre-commit.dev-workflow-kit`, a file **Git does not execute** — the kit's hook stays inactive until the manual merge into `.git/hooks/pre-commit` is done.

### `init.sh --update` (kit-managed files, lock-driven)

`init.sh --update /path/to/project` (or run from inside the project) synchronizes the **kit-managed** files — the agents, the skill, the pre-commit hook, and the `model:`/`variant:` frontmatter defaults — using the lock file at `.opencode/.dev-workflow-kit-lock.json` to tell files you never touched apart from files you customized. It announces the version comparison up front (`kit vX — project last synced at vY`; a pre-versioning lock reads "last sync unknown") and closes with `now at vX` (something was synced) or `already at vX`. With `--global` (`--update --global`), the same lock-driven sync applies to the session roster (agents only) in the opencode config directory, against its own lock file:

- the lock file records, for every kit-managed file, the kit content last synced (a body hash — for `CONVENTIONS.md`/`RULES.md`, the hash of the kit-managed prefix ending at `## Project rules`), the model/variant last injected, and the kit release last synced (`kit_version`, stamped on every successful sync — compare it against the kit's [VERSION](VERSION) file to tell whether an update is available). It is created automatically by **both plain install and `--update`** — commit it to the project's repo so updates are deterministic across machines and CI;
- a file **untouched since the last sync** is auto-updated to the kit's current version, and its model/variant defaults are refreshed to the current [models.json](roster/models.json) values;
- a **locally customized** file is **never overwritten**: the kit's current version is written next to it as `<file>.dev-workflow-kit-new` for a manual merge, with a warning. A **hand-set `model:`/`variant:` line** (one that differs from the last kit-injected value recorded in the lock) is **migrated** on the first `--update` that sees it: its value moves into the overrides file `dev-workflow-kit.overrides.json`, next to the lock, and the run reports it under "Migrated". From then on the **overrides file wins over [models.json](roster/models.json)** for that agent, so a later models.json change does not clobber your choice. A value equal to the kit default is never pinned (it only means the lock record was stale). When the effective value differs from what the file holds, the file is reconciled to it and reported. A variant emptied by the kit (the kit default has no variant) removes the `variant:` line when the model is migrated. The "kept as-is" behavior of earlier versions no longer exists;
- **`CONVENTIONS.md`, `RULES.md`, `CONVENTIONS.cpp.md`, `CONVENTIONS.cpp23.md` and `CONVENTIONS.python.md` follow the same "ours vs theirs" sync as the agents** — they are kit-authored content, kept up to date automatically as long as you use them unmodified; the moment you edit one, it is frozen (never auto-overwritten) and the kit's current version is offered as a `.dev-workflow-kit-new` sibling for a manual merge. For `CONVENTIONS.md` and `RULES.md` this comparison **splits at the `## Project rules` heading**: only the kit-authored part above and including that line is compared and replaced; the project-specific rules you append below it are 100% yours — never touched, and never even considered when deciding whether the kit part was customized. `CONVENTIONS.cpp.md`, `CONVENTIONS.cpp23.md` and `CONVENTIONS.python.md` have no user-append zone, so they are compared and replaced whole-file. These five files are also **never auto-created by `--update`**: a `RULES.md` you declined at install (or a `CONVENTIONS.cpp.md` / `CONVENTIONS.cpp23.md` / `CONVENTIONS.python.md` you never manually copied) stays absent — the file must already exist, via `--with-rules`, a plain install, or a manual copy;
- the **project-state files remain permanently untouched by `--update` under all circumstances**: `dev-workflow.json`, `TODO.md`, `SPEC.md`, `INPROGRESS.md`, `CHANGELOG.md`, `DESIGNS.md` — not created, not overwritten, not removed, regardless of whether they are customized, absent, or deliberately never installed. They are pure project state with no kit-default content to converge toward — a guarantee that holds in every release (`--with-rules` and `--companions` have no effect combined with `--update` — a warning says so: an existing `RULES.md` is synced either way, and a missing one is never created in update mode);
- **never prompts**: no TTY reads at all (the interactive model-availability menu is install-time only), so it is safe to run non-interactively/CI. It exits 0 unless a hard precondition fails (target not a git repo, or never initialized with the kit — `.opencode/agent/` missing);
- the pre-commit hook keeps its own drift mechanism: an updated kit hook lands in `pre-commit.dev-workflow-kit` exactly as during an install;
- **bootstrap**: a project initialized before the lock file existed gets a conservative first `--update` — nothing is silently clobbered. Files already matching the kit are baselined into the lock; files that diverge are treated as possibly customized (`.dev-workflow-kit-new` sibling, no overwrite). From the second `--update` on, the untouched-vs-customized distinction is exact.

- **orphans**: a lock key whose kit source is gone (a renamed or retired agent, for example) is cleaned up only when the lock proves the kit once shipped it. A deployed copy is first saved to a timestamped backup directory — `dev-workflow-kit-backup/<UTC timestamp>/` next to the lock — and only then deleted, reported under "Removed". A key with no deployed file is pruned from the lock, its lock entry kept in `lock-entries.jsonl` in that backup directory (reported under "Pruned"). If no backup directory can be created, the key is still pruned and the report says the entry was **not archived**. Keys outside the kit's path shapes (traversal, absolute paths, newlines) are pruned without touching any file;
- **global mode only — body edits are not supported**: `--update --global` overwrites a diverged roster file with the kit's current content and keeps the previous file once as `<file>.dev-workflow-kit-prev`, with a warning. Project mode is unchanged (the `.dev-workflow-kit-new` sibling, above);
- **stale siblings are cleaned up**: when a file's body equals the kit body again, its parked `.dev-workflow-kit-new` sibling is removed and reported ("Removed stale sibling"). A file whose body already equals the kit with an out-of-date baseline counts as current, and its baseline is refreshed;
- **`--global` is fail-closed on the generated roster**: the roster output (the [MODELS.md](roster/MODELS.md) generated region and `roster/injected-preview.md`) must match [models.json](roster/models.json). When it does not, `init.sh --global` (install or `--update`) refuses before writing anything and names the fix: run `roster/build.sh`, commit the result, then re-run the command. Kit maintainers get the same check from `init.sh --self-check`.

### `init.sh --doctor` (read-only drift report)

`init.sh --doctor /path/to/project` (or `init.sh --doctor --global`) reports drift and writes **nothing** — no lock, no file, no directory. It checks each tracked file against the kit: present or missing; a lock baseline exists; the body equals the kit body (injected keys stripped); the deployed `model:`/`variant:`/`# Model family:` lines equal the effective value (overrides file, then models.json); no `.dev-workflow-kit-new` or `-prev` sibling is pending; no orphan or out-of-pattern lock key. It also notes a lock recorded at an older kit version (`--update` is due), and, in project mode, a parked `pre-commit.dev-workflow-kit`. In `--global` mode it runs the roster check above.

Exit codes: **0** clean, **1** drift listed (one `DRIFT` line per item, each naming its fix or the reason no fix applies), **2** a precondition failed (`jq` or `shasum` missing). Run `--update` (add `--global` for the roster) to reconcile what `--update` covers; the rest is listed with its manual step. Note that a leftover `-prev` file (kept by the global overwrite above) is drift until you remove it by hand.


### Update recipe (for agents and humans)

The `--update` mechanics are described above; the safe *procedure* around them is always this, whether run by a human or by an agent:

1. **Commit the current state first** — the project's kit-managed files AND `.opencode/.dev-workflow-kit-lock.json` in one atomic commit. This commit is the rollback point: restoring it restores prompt files and sync baselines together.
2. Run `init.sh --update` (add `--global` for the machine-wide roster).
3. Read the script's output and `git diff` — customized files are flagged, never overwritten; project-state files are untouched by design.
4. Commit the result as a second atomic commit (same pairing: prompt files + lock).
5. **Restart OpenCode** in the project — prompt/model changes are only picked up by a fresh session.
6. If a step goes wrong, `git revert` the pair from step 1 — never hand-patch individual kit files.

## Customizing the agents

The `workflow/agent/*.md` files are standard opencode agents (frontmatter `description`, `mode`, `model`, `variant`, `permission`). The `model` line (and `variant` where configured) is injected at install time from [roster/models.json](roster/models.json) — change the defaults there, not in the agent files.

## License

MIT — see [LICENSE](LICENSE).

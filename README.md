# dev-workflow-kit

Reusable development workflow kit for [opencode](https://opencode.ai) projects (AI agents + CLI): generic agents (impl / review / explore / design-review / deep), a task-management skill (TODO → INPROGRESS → CHANGELOG), a configurable pre-commit hook and starter files. A `--global` mode additionally installs a session-level agent roster (see [Global roster](#global-roster)). The economics: cheap models do the bulk of the work, expensive ones only escalate, and quality is recovered by cross-lineage review.

A project adopts the kit via `git clone` + `init.sh`. Each project keeps its own config (`dev-workflow.json`) and diverges freely: everything is **copied**, never symlinked.

## Releasing (kit maintainers)

Bump the root `VERSION` file and the git tag together — `VERSION` is the single source of truth for the kit version that installs announce and that the lock file's `kit_version` records (no git-describe fallback: the kit can be copied without `.git`).

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

- `.opencode/agent/*.md` — the five subagents (`impl`, `review`, `explore`, `design-review`, `deep`), with their default model (and reasoning `variant` where configured) injected from the kit's `models.json`;
- `.opencode/skill/dev-workflow/SKILL.md` — the skill driving the TODO → INPROGRESS → CHANGELOG cycle, the companions and the commit checks;
- `.git/hooks/pre-commit` — the hook running the `dev-workflow.json` checks on every commit;
- `dev-workflow.json` (project root) — your config: pre-commit checks + paths of the workflow files;
- `TODO.md`, `INPROGRESS.md`, `CHANGELOG.md`, `SPEC.md`, `DESIGNS.md`, `CONVENTIONS.md` (project root) — starter skeletons, to fill in;
- `RULES.md` (project root) — **opt-in** safety/robustness rules skeleton (JPL's Power of 10-inspired), not installed by default: pass `--with-rules` or answer the interactive y/N prompt (see the Installation table);
- `.opencode/.dev-workflow-kit-lock.json` — sync baseline (kit body hashes + injected models/variants, plus the rule/convention prefix hashes) used by `init.sh --update`; it also records `kit_version`, the kit release last synced — compare it to the kit's `VERSION` file to tell whether an update is needed: `jq .kit_version .opencode/.dev-workflow-kit-lock.json`. Commit it (see "Updating").

### B. Existing project (already has code, maybe its own conventions or hook)

Same command — `init.sh` is idempotent and non-destructive:

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

## Prerequisites

- `git`
- `jq` — required by the pre-commit hook, **no fallback without jq**: `brew install jq` / `apt install jq`
- `opencode` (optional) — enables the model availability check at install time (see below)

## Structure

```
dev-workflow-kit/
├── init.sh                  # installs the kit into a target project; --update re-syncs kit-managed files later
├── models.json              # default model (+ reasoning variant) per agent — single source of truth
├── MODELS.md                # why each default model was chosen + replacement guide
├── evals/                   # model-eval protocol, results and raw outputs — see evals/README.md
│   ├── README.md            #   protocol, the 4 tasks, scoring checklist
│   ├── run-eval.sh          #   one run: task × model × variant in a fresh repo copy
│   ├── synccli-eval-repo/   #   test fixture (seeded defects), shipped as plain files
│   └── 2026-09-29/          #   results (RESULTS.md) + archived outputs
├── agent/                   # 5 opencode agents → .opencode/agent/
│   ├── impl.md              #   default implementer, always followed by a review
│   ├── review.md            #   read-only review, minor/major findings
│   ├── explore.md           #   read-only codebase exploration
│   ├── design-review.md     #   approach critique before writing code
│   └── deep.md              #   deep reasoning, last resort
├── global/agent/            # 17 session-roster agents → ~/.config/opencode/agent/ via --global (see "Global roster")
│   ├── cheap-code.md                        #   default cheap implementer, large-context work
│   ├── cheap-design.md                      #   cheap design producer — approach doc before code
│   ├── cheap-design-review.md               #   read-only design critique before code
│   ├── cheap-mech.md                        #   small mechanical edits
│   ├── cheap-review.md                      #   read-only cross-lineage review of cheap-code
│   ├── strong-code.md                       #   strong escalation rung (Claude), rare
│   ├── strong-code-alternative.md           #   cross-vendor escalation implementer
│   ├── strong-code-alternative2.md          #   terminal impl rung, before human
│   ├── strong-design.md                     #   strong design rung (Claude), hard architectures
│   ├── strong-design-alternative.md         #   cross-vendor design escalation
│   ├── strong-design-alternative2.md        #   terminal design rung, before human
│   ├── strong-design-review.md              #   read-only cross-lineage critique of strong-design
│   ├── strong-design-review-alternative.md  #   cross-vendor design-review escalation
│   ├── strong-design-review-alternative2.md #   terminal read-only design audit
│   ├── strong-review.md                     #   read-only cross-lineage review of strong-code
│   ├── strong-review-alternative.md         #   reviews strong-code-alternative output from a different lineage, deeper re-review
│   └── strong-review-alternative2.md        #   terminal read-only audit (fresh family)
├── skill/dev-workflow/      # opencode skill → .opencode/skill/dev-workflow/
│   └── SKILL.md             #   TODO/INPROGRESS/CHANGELOG cycle, conventions, companions, commit, periodic review
├── hooks/pre-commit.sh      # pre-commit hook driven by dev-workflow.json
└── templates/
    ├── dev-workflow.json    # per-project config (pre-commit checks, paths, companions)
    ├── TODO.md              # roadmap skeleton
    ├── SPEC.md              # stable spec skeleton
    ├── DESIGNS.md           # designs archive skeleton (as-implemented history)
    ├── INPROGRESS.md        # current-state skeleton
    ├── CHANGELOG.md         # changelog skeleton (Keep a Changelog)
    ├── CONVENTIONS.md       # default coding rules skeleton (extend per project)
    ├── RULES.md             # OPTIONAL safety/robustness rules, inspired by JPL's Power of 10 — NOT copied by default, opt-in (--with-rules or interactive prompt, see below)
    ├── CONVENTIONS.cpp.md   # OPTIONAL C++ conventions reference — NOT copied by init.sh, opt-in (see below)
    ├── CONVENTIONS.cpp23.md  # OPTIONAL second C++ conventions (C++23: no-exceptions/std::expected, companion .md docs, hot-path discipline) — NOT copied by init.sh, opt-in (see below)
    ├── CONVENTIONS.python.md  # OPTIONAL Python conventions reference (type hints, failure postures, ruff) — NOT copied by init.sh, opt-in (see below)
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
| `agent/*.md` | `.opencode/agent/` | copied if absent; if present and **different** from the kit → kept + warning (local customization preserved) |
| `skill/dev-workflow/` | `.opencode/skill/dev-workflow/` | same |
| `hooks/pre-commit.sh` | `.git/hooks/pre-commit` | installed if absent; if a **different** hook exists → copied as `pre-commit.dev-workflow-kit`, manual merge |
| `templates/dev-workflow.json` | project root | copied **only if absent**; on a fresh copy the companions setting is auto-detected (`--companions=on|off` to override) |
| `templates/TODO.md`, `SPEC.md`, `INPROGRESS.md`, `CHANGELOG.md`, `DESIGNS.md`, `CONVENTIONS.md` | project root | copied **only if absent** |
| `templates/RULES.md` | project root | **opt-in** — copied **only if absent** with `--with-rules`, or via an interactive y/N prompt when a TTY is available; otherwise skipped (copy it manually to opt in) |

**Every** successful install also writes/updates the lock file when `jq` and `shasum` are available; otherwise the install succeeds without one (warning only) and the next `--update` bootstraps conservatively. It is generated, not copied from the kit; commit it to the project's repo. Every successful sync stamps the kit's current `VERSION` into the lock's `kit_version` field.

## Global roster

`./init.sh --global` installs the kit's **session roster** — seventeen general-purpose agents (`cheap-code`, `cheap-design`, `cheap-design-review`, `cheap-mech`, `cheap-review`, `strong-code`, `strong-code-alternative`, `strong-code-alternative2`, `strong-design`, `strong-design-alternative`, `strong-design-alternative2`, `strong-design-review`, `strong-design-review-alternative`, `strong-design-review-alternative2`, `strong-review`, `strong-review-alternative`, `strong-review-alternative2`) — into your opencode **user-level** config directory, so they are available in every session, in every project. Their roles and cost rationale are documented in `MODELS.md` ("Two scopes" and the global-roster section).

- **Destination**: `${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/agent/`. There is no `.opencode/` level here, unlike project mode — the config directory's `agent/` subdirectory *is* the agent directory. Set `OPENCODE_CONFIG_DIR` to target another config directory (created if absent); it is honored by `--global` only.
- **Models** come from the `"global"` section of the kit's `models.json`, through the same injection and availability-menu machinery as project mode. The lock file is `${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/.dev-workflow-kit-lock.json` — a separate file from any project's lock, same schema, so the two scopes sync independently with `--update --global`.
- **Migration from an inline roster**: if your `opencode.json(c)` defines agents in an inline `"agent"` block, those entries **shadow** the kit-managed files (inline config wins over agent files — the agent would keep running from the jsonc, not from the kit). `init.sh --global` detects every inline entry whose name matches a roster agent (a JSONC-aware parse, best effort) and warns insistently; it never edits the jsonc itself. Removing the inline roster entries by hand (keeping non-roster overrides like `build`/`plan`) is the migration step that makes the kit the single source of truth again.
- **Project wins**: when a name exists both globally and in a project installed by the kit, the project-level agent takes precedence in that project — this is wanted: the global roster is the fallback for projects (or ad-hoc work) without the kit's pipeline, and the roster agents' descriptions say so.

Nothing project-specific is touched by `--global`: no skill, no pre-commit hook, no `dev-workflow.json`, no rule/convention files — and no git repo is required (the config directory is not one). `--with-rules` and `--companions` have no effect with `--global` (a warning says so).

## Default models

The kit ships default models per agent role in `models.json` (impl runs a cheap bulk model, review runs a different model lineage than impl to avoid shared blind spots, deep gets the expensive reasoning model). `init.sh` injects these into freshly copied agents — `models.json` is the single source of truth, edit it to change the defaults. Several roles also pin a reasoning-effort `variant` (some pin `none`, others `low`/`high`/`medium`) — see `MODELS.md`.

At install time, if the `opencode` CLI is available, each freshly copied agent's model is checked against its provider's model list (`opencode models <provider>`):

- model available → nothing to do;
- model unavailable but same-family candidates exist → an interactive menu proposes replacements (or keep as configured, or enter one manually) and rewrites the installed agent's frontmatter — the `variant` from `models.json` is left as-is, since a different model may use a different effort scale;
- no candidate found → a warning points at `MODELS.md` (which documents the role each model plays and how to judge a replacement) and leaves the config as-is.

If `opencode` is not installed, the check is skipped with a warning — the model defaults are installed as-is. This step can never fail the install, and agents preserved because of a local customization are never touched. Under `--update`, the current `models.json` defaults are re-applied to agents whose model was not changed since the last sync — the `variant:` line follows the same rule — see [Updating](#updating-syncing-kit-changes-into-a-project). See `MODELS.md` for the rationale behind each default.

## Per-project config: `dev-workflow.json`

```json
{
  "precommit": {
    "checks": [
      { "name": "tests", "cmd": "" },
      { "name": "companions_exist", "builtin": "companion_md_exists", "extensions": ["cpp", "h", "ts", "tsx"] }
    ]
  },
  "workflow": { "todo": "TODO.md", "inprogress": "INPROGRESS.md", "changelog": "CHANGELOG.md", "spec": "SPEC.md", "designs": "DESIGNS.md", "conventions": "CONVENTIONS.md", "rules": "RULES.md" },
  "companions": { "enabled": true }
}
```

- `precommit.checks[]`: the pre-commit checks — see [Extending pre-commit checks](#extending-pre-commit-checks) for the full contract (`cmd` entries and builtins).
- `companions.enabled: false`: the `companion_md_exists` builtin is skipped entirely, even if listed, and the skill creates no companion — the recommended setting when working on a pre-existing codebase you don't want to pollute with companion `.md` files (companions are a greenfield tool).
- Fresh install: the installer auto-detects existing sources and companions and sets `companions.enabled` accordingly — companions already in use stay enabled; an existing codebase without companions is prompted about (or auto-disabled without a TTY, with a notice telling how to re-enable). `--companions=on|off` overrides the detection; an existing `dev-workflow.json` is never touched.
- `workflow`: paths of the files used by the `dev-workflow` skill. `workflow.conventions` points at the coding-conventions file the skill reads before writing or editing code (default `CONVENTIONS.md`). The optional `workflow.*` paths — `spec`, `designs`, `conventions`, `rules` — are conditional: the corresponding behavior is active only while the pointed-at file exists (delete the file or the key to turn that feature off); `todo`, `inprogress` and `changelog` are pure renames of the core cycle's files.
- `workflow.spec`: points at the stable-specs file (default `SPEC.md`) the skill re-reads before any commit that could deviate from it — a necessary deviation is flagged to the user, never decided alone.
- `workflow.designs`: points at the designs-archive file (default `DESIGNS.md`) where the skill writes one entry per completed task — the design as implemented, direction changes, rejected alternatives; a non-normative history (the SPEC stays authoritative), written at task completion before the `INPROGRESS.md` reset.
- `workflow.rules`: points at the optional safety/robustness rules file, read alongside the conventions (default `RULES.md`, inspired by JPL's Power of 10) — a violation there always requires an explicit, reviewable justification, which the review step can refuse.

## Optional language-specific conventions

`templates/CONVENTIONS.cpp.md` is an **opt-in** template that `init.sh` never copies at install time: unlike `RULES.md` (opt-in via `--with-rules`/prompt but still copied by `init.sh` when chosen), getting it into the project the first time is a manual copy. It is a language-specific reference (C++, and JS where noted) following a mature C++ codebase's conventions, for a project that wants them. A project that wants it copies the file into its root manually, then either references it from its own `CONVENTIONS.md`'s "Project rules" section with a one-line pointer, or appends its content directly into that section. Once it exists in the project, though, it is synced by `init.sh --update` like the other kit-authored convention files — kept up to date while untouched, frozen with a `.dev-workflow-kit-new` sibling when customized (whole-file sync; see [Updating](#updating-syncing-kit-changes-into-a-project) for the exact contract). `templates/CONVENTIONS.cpp23.md` is a second, independent C++ reference (C++23 / no-exceptions / `std::expected` style) under the exact same opt-in + whole-file sync contract. `templates/CONVENTIONS.python.md` is a Python reference (type-hinted, ruff, failure-posture driven) under the same opt-in + whole-file sync contract.

## Extending pre-commit checks

`dev-workflow.json`'s `precommit.checks[]` is the **single extension point** for pre-commit checks — for command-based checks you never need to touch `hooks/pre-commit.sh`:

- **add a check** — append an entry to `checks[]`:
  - `{ "name": "lint", "cmd": "npm run lint" }` — any shell command, run from the repo root on every commit; exit code 0 passes, any other exit code blocks the commit;
  - `{ "name": "...", "builtin": "..." }` — a hook-native check (builtins listed below);
- **change or remove a check** — edit or delete its entry; the hook re-reads `checks[]` on every commit, there is nothing else to wire.

An entry with an empty `cmd` and no `builtin` is silently skipped (that is how the template ships its `tests` check).

### Builtins

Builtin checks are implemented inside `hooks/pre-commit.sh` itself — adding a **new builtin** means editing that file (and upstreaming it to the kit if you want it shared). Currently implemented:

- **`companion_md_exists`** — for each staged source file whose extension is in `extensions`, the same-named `.md` (same folder) must be **staged** in the commit. Present on disk but not staged = missing (the commit would not include it).
- **`no_history_comments`** — optional, **not enabled by default**: blocks the commit if an ADDED line of a staged file (same `extensions` filter) contains a history-narrating marker, case-insensitive, on whole words (so `unchanged from` does not match `changed from`): `previously`, `used to be`, `changed from`, `now does`, `no longer`, `old behavior`, `old version`, `before this change`. This is the enforcement counterpart of CONVENTIONS.md's rule 2. Enable it by adding an entry:

  ```json
  { "name": "no_history_comments", "builtin": "no_history_comments", "extensions": ["cpp", "h", "ts", "tsx"] }
  ```

  **Limitations, so you opt in with eyes open:** this is a heuristic, imperfect by nature — never a perfect guard. It runs on raw added lines — it does not parse comment syntax, so any added line containing a marker matches, including string literals or legitimate prose (a user-facing message saying "previously" will block). Markers describing a runtime lifecycle rather than code history are the most likely to produce occasional false positives: `no longer` and `previously` are the two worst offenders (e.g. `// when no longer needed, free it`, `// discard previously allocated buffer`), and `now does` is generic though less ambiguous in practice — the team enabling the check should evaluate these three and keep it off if the noise outweighs the signal. Like every other check, it is a hard block: the hook has no warn-only mode.

## Pre-commit hook

Behavior (`hooks/pre-commit.sh` installed as `.git/hooks/pre-commit`):

- `dev-workflow.json` missing from the root → warning, commit **accepted** (the hook does not block a repo that has not adopted the kit yet);
- `dev-workflow.json` invalid JSON (unparseable) → clear message, commit **blocked** — a hard block, distinct from the invalid-`.precommit.checks`-type case below;
- `.precommit.checks` of an invalid type (e.g. a string) → clear message, commit **blocked**;
- failing `cmd` check → the check's stdout/stderr is shown, commit **blocked**;
- `.md` companions missing from the index (missing on disk, or present but not staged) → list shown, commit **blocked**;
- history-narrating markers found in added lines (opt-in `no_history_comments` builtin) → `file:line` + matched marker listed, commit **blocked**;
- on failure: summary of failed checks + exit 1, otherwise exit 0.

## Updating: syncing kit changes into a project

### Plain re-run (install semantics)

Re-running `init.sh` on the project (no flags needed):

- the **agents and the skill** are copied if absent; if they differ from the kit (local customization: edited content…), they are **never overwritten** — a warning lists the affected files, to compare/merge by hand;
- `dev-workflow.json`, `TODO.md`, `SPEC.md`, `INPROGRESS.md`, `CHANGELOG.md`, `DESIGNS.md`, `CONVENTIONS.md` are **never overwritten** (nor an opt-in `RULES.md`);
- your pre-commit hook, if it exists and differs from the kit, is kept: the kit's hook lands in `pre-commit.dev-workflow-kit`, a file **Git does not execute** — the kit's hook stays inactive until the manual merge into `.git/hooks/pre-commit` is done.

### `init.sh --update` (kit-managed files, lock-driven)

`init.sh --update /path/to/project` (or run from inside the project) synchronizes the **kit-managed** files — the agents, the skill, the pre-commit hook, and the `model:`/`variant:` frontmatter defaults — using the lock file at `.opencode/.dev-workflow-kit-lock.json` to tell files you never touched apart from files you customized. It announces the version comparison up front (`kit vX — project last synced at vY`; a pre-versioning lock reads "last sync unknown") and closes with `now at vX` (something was synced) or `already at vX`. With `--global` (`--update --global`), the same lock-driven sync applies to the session roster (agents only) in the opencode config directory, against its own lock file:

- the lock file records, for every kit-managed file, the kit content last synced (a body hash — for `CONVENTIONS.md`/`RULES.md`, the hash of the kit-managed prefix ending at `## Project rules`), the model/variant last injected, and the kit release last synced (`kit_version`, stamped on every successful sync — compare it against the kit's `VERSION` file to tell whether an update is available). It is created automatically by **both plain install and `--update`** — commit it to the project's repo so updates are deterministic across machines and CI;
- a file **untouched since the last sync** is auto-updated to the kit's current version, and its model/variant defaults are refreshed to the current `models.json` values;
- a **locally customized** file is **never overwritten**: the kit's current version is written next to it as `<file>.dev-workflow-kit-new` for a manual merge, with a warning. A hand-set `model:` line is kept as-is (a neutral "kept" note, not a warning — picking your own model is expected, deliberate behavior); it stays yours even when `models.json` changes later. The same applies to a hand-set `variant:` line: a variant that differs from the last kit-injected value is treated as yours — kept, and never clobbered by a later `models.json` change (not even when the model itself is refreshed);
- **`CONVENTIONS.md`, `RULES.md`, `CONVENTIONS.cpp.md`, `CONVENTIONS.cpp23.md` and `CONVENTIONS.python.md` follow the same "ours vs theirs" sync as the agents** — they are kit-authored content, kept up to date automatically as long as you use them unmodified; the moment you edit one, it is frozen (never auto-overwritten) and the kit's current version is offered as a `.dev-workflow-kit-new` sibling for a manual merge. For `CONVENTIONS.md` and `RULES.md` this comparison **splits at the `## Project rules` heading**: only the kit-authored part above and including that line is compared and replaced; the project-specific rules you append below it are 100% yours — never touched, and never even considered when deciding whether the kit part was customized. `CONVENTIONS.cpp.md`, `CONVENTIONS.cpp23.md` and `CONVENTIONS.python.md` have no user-append zone, so they are compared and replaced whole-file. These five files are also **never auto-created by `--update`**: a `RULES.md` you declined at install (or a `CONVENTIONS.cpp.md` / `CONVENTIONS.cpp23.md` / `CONVENTIONS.python.md` you never manually copied) stays absent — the file must already exist, via `--with-rules`, a plain install, or a manual copy;
- the **project-state files remain permanently untouched by `--update` under all circumstances**: `dev-workflow.json`, `TODO.md`, `SPEC.md`, `INPROGRESS.md`, `CHANGELOG.md`, `DESIGNS.md` — not created, not overwritten, not removed, regardless of whether they are customized, absent, or deliberately never installed. They are pure project state with no kit-default content to converge toward — a guarantee that holds in every release (`--with-rules` and `--companions` have no effect combined with `--update` — a warning says so: an existing `RULES.md` is synced either way, and a missing one is never created in update mode);
- **never prompts**: no TTY reads at all (the interactive model-availability menu is install-time only), so it is safe to run non-interactively/CI. It exits 0 unless a hard precondition fails (target not a git repo, or never initialized with the kit — `.opencode/agent/` missing);
- the pre-commit hook keeps its own drift mechanism: an updated kit hook lands in `pre-commit.dev-workflow-kit` exactly as during an install;
- **bootstrap**: a project initialized before the lock file existed gets a conservative first `--update` — nothing is silently clobbered. Files already matching the kit are baselined into the lock; files that diverge are treated as possibly customized (`.dev-workflow-kit-new` sibling, no overwrite). From the second `--update` on, the untouched-vs-customized distinction is exact.

### Update recipe (for agents and humans)

The `--update` mechanics are described above; the safe *procedure* around them is always this, whether run by a human or by an agent:

1. **Commit the current state first** — the project's kit-managed files AND `.opencode/.dev-workflow-kit-lock.json` in one atomic commit. This commit is the rollback point: restoring it restores prompt files and sync baselines together.
2. Run `init.sh --update` (add `--global` for the machine-wide roster).
3. Read the script's output and `git diff` — customized files are flagged, never overwritten; project-state files are untouched by design.
4. Commit the result as a second atomic commit (same pairing: prompt files + lock).
5. **Restart OpenCode** in the project — prompt/model changes are only picked up by a fresh session.
6. If a step goes wrong, `git revert` the pair from step 1 — never hand-patch individual kit files.

## Customizing the agents

The `agent/*.md` files are standard opencode agents (frontmatter `description`, `mode`, `model`, `variant`, `permission`). The `model` line (and `variant` where configured) is injected at install time from `models.json` — change the defaults there, not in the agent files.

## License

MIT — see [LICENSE](LICENSE).

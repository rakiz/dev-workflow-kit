# Models

Why each agent role runs the model it runs. `models.json` at the kit root is the
single source of truth for the default models — `init.sh` injects them into the
installed agents at install time. To change a default, edit `models.json`; do
not hardcode a model anywhere else. The defaults reflect the author's providers
(Fireworks, GitHub Copilot) — swap freely via `models.json`.

Use this page as the yardstick when a configured model becomes unavailable and
a replacement must be chosen: same role, comparable cost per MTok, and for
`review` ideally a different model lineage than `impl`.

## Two scopes

`models.json` models two independent rosters:

- **Project roster** — the flat top-level map (`impl`, `review`, `explore`,
  `design-review`, `deep`), installed into a project's `.opencode/agent/` by
  `init.sh`. The pipeline agents of a project that adopts the kit.
- **Global roster** — the `"global"` section (`cheap-code`, `cheap-design`,
  `cheap-design-review`, `cheap-mech`, `cheap-review`, `strong-code`,
  `strong-code-alternative`, `strong-code-alternative2`, `strong-design`,
  `strong-design-alternative`, `strong-design-alternative2`,
  `strong-design-review`, `strong-design-review-alternative`,
  `strong-design-review-alternative2`, `strong-review`,
  `strong-review-alternative`, `strong-review-alternative2`),
  the session-level roster installed into
  `${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}/agent/` by `init.sh
  --global`, available in every opencode session.

The two name sets are disjoint, and that is by design: the project roster
keeps its pure function names (`impl`, `review`, `deep`, ...), while the
global roster is distinguished by its price-class prefixes (`cheap-` for
bulk work, `strong-` for escalation and audit rungs) — a name exists in at
most one scope. In a project that ships its own pipeline agents, the
project-level agents are the intended pipeline; the global roster remains
the fallback for projects (or ad-hoc work) without the kit's pipeline — the
roster agents' descriptions say so explicitly. Each scope has its own lock
file next to its own agents, so the two rosters sync independently through
`--update` (`--update --global` for the roster).

## The cost logic of the kit

The explicit goal of the kit is to **lower the cost of AI sessions**. Direct
Anthropic models are excellent but expensive; they are reserved for the rare
escalation path (`deep`). The bulk of the work (implementing, reviewing,
exploring) runs on much cheaper models — a good frontier model costs a
fraction of a top-tier model per MTok, and the pipeline is designed so that
quality is recovered by review and escalation, not by expensive generation.

## Eval 2026-09-29 — full matrix (basis for the choices below)

Full protocol, seeded tasks, logs and per-task rankings:
`evals/2026-09-29/RESULTS.md` (9 models x 4 tasks, 45 runs,
objective scoring against seeded defects). Standing decision rule that came
out of it: **price beats speed** — when two models sit in the same quality
tier, the cheaper one takes the role, and effort variants that keep quality
while cutting cost are applied (review runs `low` for this reason).

Per-task cost ladders (each rung = a quality tier up):

- **Orchestration** glm $0.009 → s5.5 `high` $0.192 → opus $0.309
- **Impl** glm $0.007 → s5.5 `high` $0.122 → opus $0.252
- **Review** (impl = glm, cross-lineage only) gemini `low` $0.029 → s5.5
  `medium` $0.119 → opus $0.236
- **Design-review** deepseek $0.006 → s5.5 `medium` $0.124 → opus $0.228

Hard-won facts worth re-reading before any swap: effort at `low` on a Claude
model means fewer tool calls — it skips reading code and then hallucinates
structure (s5.5 `low` was eliminated from orchestration for exactly this);
`xhigh` never paid for itself on any task; descending effort on opus via
github-copilot is not honored (no cost drop), only `xhigh` raises the price.

## Per-role rationale

### impl — `fireworks-ai/.../glm-5p3-flash` (family: glm)

The bulk implementer: most tokens spent in a session end up here, so this is
where cheapness matters most. Chosen as a cheap-but-solid frontier model —
strong at ordinary code tasks, weak on none of the everyday patterns. Any
replacement must be in the same price class; a premium model here defeats the
kit's cost goal even if it is "better".

### review — `github-copilot/gemini-3.8-flash` (family: gemini, variant: low)

The mandatory re-reader of impl's work. Deliberately a **different model
lineage than impl**: models from the same family tend to share blind spots —
the same misreadings, the same confident mistakes. A reviewer of a different
lineage catches what the implementer's family systematically misses. Keep that
property when replacing either side.

`variant: low` comes from the 2026-09-29 eval (`evals/2026-09-29/`):
at `low` effort gemini catches the same 3/3 seeded defects as at default
effort for a quarter of the cost. Given the price-over-speed
priority, `low` is the default review rung; step up to `claude-sonnet-5.5`
`medium` (best depth/speed of the eval) for a sensitive diff, then
`claude-opus-5.5` — never within the glm family while impl runs glm.

### explore — `fireworks-ai/.../deepseek-v4p1-flash` (family: deepseek)

Read-only localization work: find symbols, trace a flow, summarize. High
volume, low stakes, cheapest acceptable model wins. DeepSeek's cheap tier does
this as well as models many times its price.

### design-review — `fireworks-ai/.../deepseek-v4p1-flash` (family: deepseek)

Critiques an approach before code is written. Runs rarely, and the eval
(`evals/2026-09-29/`, task T4) showed deepseek covering the same
top flaw categories as models 13x its price on a seeded design doc — same
quality tier as `gpt-5.6-terra`, at $0.006 per run. With the price-over-speed
priority it takes the role; deepseek is also a third lineage (neither impl's
glm nor review's gemini). For a high-stakes design, escalate the critique to
`claude-sonnet-5.5` `medium`/`high` or `claude-opus-5.5`.

### deep — `github-copilot/claude-opus-5.5` (family: claude)

Last resort: subtle bugs, escalated majors, the step before human
intervention. Runs rarely, so it is the one place where a top reasoning model
is affordable and worth it. Anthropic models are the natural choice here —
the kit still avoids paying premium prices anywhere else. It runs the same
top Claude as the global roster's strong rungs, at the model's default
reasoning effort (no `variant`).

## Global roster (session agents) — the 4-tier grid

The session roster is a 2D grid: **function** (design / design-review /
code / code-review / mech, plus orchestration = the session's default model, not an
agent) x **tier** (`cheap-` = bulk work, `strong-` = escalation, `-alternative`
= stronger + fresh family, `-alternative2` = terminal rung before human).
Eval basis and per-task cost ladders: `evals/2026-09-29/RESULTS.md`.

Two rules bind the whole grid:

- **Lineage**: the reviewer of a work product is never from the family of its
  producer — review rung N reviews impl rung N's output from a different
  family, and each escalation rung N is a different family than rung N-1
  (fresh eyes on what the previous family already missed).
- **Price over speed**: when two models sit in the same quality tier, the
  cheaper one takes the role (eval 2026-09-29: glm/gemini `low`/deepseek for
  bulk, claude only where depth is the point).

| Function \ tier | cheap | strong | alternative | alternative2 |
|---|---|---|---|---|
| design (producer) | `cheap-design` glm | `strong-design` s5.5 `high` | `strong-design-alternative` sol | `strong-design-alternative2` opus |
| design-review | `cheap-design-review` deepseek | `strong-design-review` sol | `strong-design-review-alternative` s5.5 `medium` | `strong-design-review-alternative2` grok |
| code (impl) | `cheap-code` glm `none` | `strong-code` s5.5 `high` | `strong-code-alternative` sol | `strong-code-alternative2` opus |
| mech (small mechanical edits) | `cheap-mech` deepseek | — | — | — |
| code-review | `cheap-review` gemini `low` | `strong-review` glm `high` | `strong-review-alternative` s5.5 `medium` | `strong-review-alternative2` grok |
| orchestration | session default model: glm (the user's configured default model) | switch session model to s5.5 `high` | opus — only if the task already crossed design+impl strong rungs | — |

Abbreviations (`models.json` model values): s5.5 = claude-sonnet-5.5, sol = gpt-6.1-sol, opus = claude-opus-5.5, grok = grok-4.7, glm = glm-5p3-flash.

Escalation semantics: rung N+1 is invoked only when rung N failed, stalled or
expressed doubt — never speculatively. The `-alternative2` rung is the step
before human intervention; its output must state what a human must decide.

Eval-backed highlights: glm `high` reviews claude diffs 3/3+4 at $0.008 (the
grid's best deal — eligible because it reviews claude, never glm); gemini
`low` is the review floor at $0.029 (3/3); kimi-k3 is design/impl-capable but
2/3 as a reviewer — never a review role; terra and fable-5.1 are out (dominated
/ too expensive). A cheap reviewer does miss things (2/3 models exist) and will
not know it — protection is structural: cross-lineage pairing, small routine
diffs, and escalation triggered by findings/tests/user, never by the
reviewer's self-assessment.

## Reasoning effort (`variant`)

opencode agents accept an optional `variant` frontmatter field — the
reasoning effort a model runs at, for models that support it (allowed values
are model-dependent: `none`, `low`, `high`, `xhigh`, ...). `models.json`
carries the kit's default per role; `init.sh` injects it into the installed
agent next to the `model:` line. Roles without a `variant` entry get no
`variant:` line at all.

- **impl — `variant: none`.** The bulk implementer is high volume by design:
  most of a session's tokens are spent there and cheapness is the point.
  Routine implementation needs no reasoning budget — the misses are
  recovered by review, not by slower generation.

The global roster carries its variant defaults in `models.json`'s `"global"`
section (eval 2026-09-29): bulk rungs at **`none`** (cheap-code, cheap-design
— routine implementation needs no reasoning budget, the misses are recovered
by review); review floors at **`low`** (cheap-review — same 3/3 catch rate as
default effort at a quarter of the cost); strong rungs pinned to the eval's
best effort — **`high`** for strong-code/strong-design (s5.5) and
strong-review (glm), **`medium`** for the s5.5 review/design-review
alternatives. Claude models
never run `low` in a code-reading role (eval: it skips reading code and
hallucinates structure) and never `xhigh`/`max` on bulk tasks (cost converges
with opus, no quality gain). Beware: descending effort on opus via
github-copilot is not honored (no cost drop).

When a replacement model is picked through the availability menu, `init.sh`
leaves the variant untouched — a different model may use a different effort
scale, so check the `variant:` line manually.

## Replacing a model

A replacement is a reasonable equivalent when:

1. **Same role** — it must serve the same step of the pipeline (cheap bulk
   work for impl/explore, cross-lineage checking for review, top reasoning
   for deep).
2. **Comparable cost per MTok** — for impl/review/explore, cheaper is the
   point; do not "upgrade" a bulk role to a premium model.
3. **Lineage** — for review, keep a lineage different from impl's (shared
   blind spots defeat the review step). For the other roles, lineage is free
   to change.

When `init.sh` finds a configured model unavailable in the target
installation, it proposes candidates from the same provider and family; this
page is the reference for judging them.

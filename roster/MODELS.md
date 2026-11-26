# Models

Why each agent role runs the model it runs. `models.json` at the kit root is the
single source of truth for the default models — `init.sh` injects them into the
installed agents at install time. To change a default, edit `models.json`; do
not hardcode a model anywhere else. The defaults reflect the author's providers
(AI Gateway, Fireworks, GitHub Copilot) — swap freely via `models.json`.

Use this page as the yardstick when a configured model becomes unavailable and
a replacement must be chosen: same role, comparable cost per MTok, and for
`review` must be a different model lineage than `impl`.

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
  `strong-review`,
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
while cutting cost are applied (review runs at the cheapest effort that
catches everything — see the review section below).

Per-task cost ladders (each rung = a quality tier up):

- **Orchestration** glm $0.009 → s5.5 `high` $0.192 → opus $0.309
- **Impl** glm $0.007 → s5.5 `high` $0.122 → opus $0.252
- **Review** (impl = glm, cross-lineage only) haiku `default` $0.0063 → glm
  `high` $0.008 → s5.5 `medium` $0.119 → grok $0.200 → opus $0.236
- **Design-review** deepseek $0.006 → 1017 `medium` $0.014 (10-19: 10/10-0FP
  at all efforts, took the strong rung from sol) → s5.5 `medium` $0.124 →
  grok $0.085 (priced lower, quality tier judged higher) → opus $0.228

`deepseek` re-baselined 2026-09-30 after a Fireworks effort-mapping fix
(default effort = new `high`): $0.033 4-task, quality equal, default kept —
`evals/2026-09-30-deepseek-effort/`.

Hard-won facts worth re-reading before any swap: effort at `low` on a Claude
model means fewer tool calls — it skips reading code and then hallucinates
structure (s5.5 `low` was eliminated from orchestration for exactly this);
`xhigh` never paid for itself on any task; descending effort on opus via
github-copilot is not honored (no cost drop), only `xhigh` raises the price.

## Per-role rationale

### impl — `github-copilot/claude-haiku-5.5` (family: claude, variant: default)

The bulk implementer: most tokens spent in a session end up here, so this is
where cheapness matters most. Chosen as a cheap-but-solid frontier model —
strong at ordinary code tasks, weak on none of the everyday patterns. Any
replacement must be in the same price class; a premium model here defeats the
kit's cost goal even if it is "better".

### review — `fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash` (family: minimax, variant: medium)

The mandatory re-reader of impl's work. Deliberately a **different model
lineage than impl**: models from the same family tend to share blind spots —
the same misreadings, the same confident mistakes. A reviewer of a different
lineage catches what the implementer's family systematically misses. Keep that
property when replacing either side: the rule is family-agnostic (reviewer
family ≠ producer family). Current pairing, per `models.json`: impl
`claude-haiku-5.5` (claude) → review `minimax-m3p1-flash` `medium` (minimax);
claude → minimax satisfies it.

History: the 2026-10-07 eval (`evals/2026-10-07-haiku-5.5/` if present, see
`EVALS.md`) measured haiku `default` in the review role — 3/3 seeded defects at
$0.0063 per 4-task run. Haiku is no longer the review model; the cost and
recall numbers above are that eval's, not the current seat's.

### explore — `ai-gateway-misc/fw-deepseek-v4.1-flash` (family: deepseek)

Read-only localization work: find symbols, trace a flow, summarize. High
volume, low stakes, cheapest acceptable model wins. DeepSeek's cheap tier does
this as well as models many times its price.

### design-review — `fireworks-ai/accounts/fireworks/models/minimax-m3p1-flash` (family: minimax, variant: medium)

Critiques an approach before code is written. Runs rarely. Rostered 10-23 after
the full grid (`evals/2026-10-23/RESULTS.md`) showed M3 stable across 3
confirmation runs at 10/10 avg @ $0.0082, replacing the old deepseek flash
(9/10 @ $0.0076 — ~+8%, +1 flaw category, no delegation at `medium`).
Minimax is a lineage distinct from impl's claude (`claude-haiku-5.5`), so the
design critique does not share impl's family; it shares minimax with the review
seat, which is fine for this comparison. For a high-stakes design, escalate the
critique: `strong-design-review` (`minimax-m3p1-flash` `xhigh`) → alternative
`gemini-4-argon` `high` (`strong-design-review-alternative`), then the human —
the terminal `strong-design-review-alternative2` rung was deleted in P0, so the
ladder stops at the human. Or straight to `claude-opus-5.5`.

### deep — `github-copilot/claude-opus-5.5` (family: claude)

Last resort: subtle bugs, escalated majors, the step before human
intervention. Runs rarely, so it is the one place where a top reasoning model
is affordable and worth it. Anthropic models are the natural choice here —
the kit still avoids paying premium prices anywhere else. It runs the same
top Claude as the global roster's strong rungs, at the model's default
reasoning effort (no `variant`).

### Provider routing (AI Gateway vs direct)

`models.json` uses the AI Gateway ids for every Fireworks model the gateway
carries (glm flash, the deepseek flashes, pro): same upstream models, ~19%
cheaper per MTok catalog and −20% measured on a T2 run (commit 06bed70
rationale). Exceptions: qwen stays `fireworks-ai` direct (the gateway carries
no FW-Qwen), and the non-flash glm-5.3 was not routed (gateway catalog price
$1.14/$3.58 — verify against `fireworks-ai` direct before ever switching it).
Eval costs in `evals/` and `EVALS.md` keep their eval-day provider labels —
they are historical records.

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
  (fresh eyes on what the previous family already missed). (Exception: the
  `-alternative` re-review rung may share the producer's family — the
  fresh-family pass already happened at the previous rung.)
- **Price over speed**: when two models sit in the same quality tier, the
  cheaper one takes the role (eval 2026-09-29: glm/gemini `low`/deepseek for
  bulk, claude only where depth is the point).

| Function \ tier | cheap | strong | alternative | alternative2 |
|---|---|---|---|---|
| design (producer) | `cheap-design` **haiku `medium`** (v2 11-17: glm scored ≤1/11 on D at every effort — the H3 false-contract FP −3 every round; haiku `medium` D 7 @ ~$0.02) | `strong-design` **1017 `high`** (v2: D 8.25/11 — the best design authoring outside opus — @ $0.12/task; was s5.5 `high`, D 7 @ $0.40–1.26) | `strong-design-alternative` **s5.5 `high`** (final 11-19, re-folded 11-20: D 8.4/11 = clean re-fold 8 + H4 fold v3 +0.4; 4 runs 7.5;DNF;8.5;8.5, 30-min watchdog required — @ $0.83/task; replaces hydrogen `high`, D 5.5 — below the cheap tier, haiku medium 8.08; terra = documented fallback) | `strong-design-alternative2` opus |
| design-review | `cheap-design-review` **M3.1 `medium`** (10-23 confirmation: 10/10 avg 3 runs @ $0.0082, replaces old deepseek flash 9/10 @ $0.0076 — same price, +1 category) | `strong-design-review` **M3.1 `xhigh`** (v2: DR2 11.5/14 with 4 executed proofs @ $0.03/task — the best design review measured; was 1017 `medium`, DR2 5.5. Dual rung with `cheap-design-review` — SPOF accepted, fallback argon `high` → opus) | `strong-design-review-alternative` argon `high` | **vacant → STOP** (`strong-design-review-alternative2` deleted in P0; the ladder stops at the alternative, then human. grok-4.7 measured DR2 7.5 vs argon `high` 9.5 on 2026-11-23 — tested and kept out, see `evals/grok-confirm-2026-11-23.status.txt`) |
| code (impl) | `cheap-code` **haiku `default`** (v2: I2 7.5/14 vs glm's 5.5, at ~$0.02/task vs $0.03; RG4 2-family panel: 11.75/14 — gate 1 fails, see RESULTS §7.1. ⚠ Cliff: haiku prompts >100k tokens pay 5× — keep impl briefs under 90k; fallback 1017 `medium`) | `strong-code` **M3.1 `xhigh`** (v2 swap, owner vote 11-18: I2 7.04/14 @ $0.03/task (re-folded 11-20 from 7.67) — a TIE with s5.5 `high` 7.75 (gap 0.71, inside the 1.5 MDE); the tie rule keeps the rung on price, 13× cheaper. RG4 2-family panel: 13.0/14 (the strong tier's best price/point; ties haiku-high 13.5 and opus 13.5 inside the MDE — the price keeps the rung). Third minimax rung — SPOF accepted by owner, fallback for the DR rungs: carbon `high`) | `strong-code-alternative` **haiku `high`** (final 11-19: I2 8.83/14 @ ~$0.15/task — the capability step above cheap-code (RG4 11.75); sonnet `high` left the code ladder for strong-design-alternative; fallback opus) | `strong-code-alternative2` opus |
| mech (small mechanical edits) | `cheap-mech` deepseek | — | — | — |
| code-review | `cheap-review` **M3.1 `xhigh`** (final 11-19: IR 4.33 bonus-inclusive, clean 3/3 runs @ $0.014 — gates fail silently, so floor recall is the protection; glm `low` left review at 2.5 and is documented as the lineage-legal fallback reviewer for deepseek/gemini-produced work only) | `strong-review` **s5.5 `medium`** (final 11-19: IR 4.75 — 4 valid runs 5;5;4;5 @ $0.09 — a fresh family vs the minimax floor it escalates from) | `strong-review-alternative` **1017 `high`** (final 11-19, new holder: IR 3.62 bonus-inclusive @ $0.016 — the lineage-legal fallback rung: deepseek reviews claude/glm/minimax-produced work) | `strong-review-alternative2` qwen `xhigh` (IR 4.0 — 2 runs 4;4, misses seeded-3 both runs) |
| orchestration | session default model: glm — the user's configured default model; **pin `max`** (owner 2026-11-23, superseding the old `high` pin: O **8/8** unanimous — minimax 8, sonnet 8, no divergence, hall=0, red baseline pinned — at **$0.007/task = same cost as high** ($0.005), the vendor-DEFAULT and vendor-recommended coding effort; the 7→8 gap is under the O noise band, so this is a free upgrade on a tie, not a quality claim; **stability confirmed ×3 same day** (2026-11-23 confirmations: runs 8;7;7 conservative panel scores, means 8;7;7.5, hall=0 ×6 readings, red baseline caught every run, delivery 3/3 at $0.0056–0.0073/task; 2 operator-error DNFs $0 — model id dashes-vs-dots, not a provider issue); high stays the measured fallback: T1 PASS @ `high` $0.0050, PARTIAL @ `low`); recommended route: the AI Gateway id (`ai-gateway-misc/fw-glm-5.3-flash`, same model as fireworks direct at −18.6% catalog price — the session config is per-machine, outside the kit) | switch session model to s5.5 `high` | opus — only if the task already crossed design+impl strong rungs | — |

**Roster v2 (owner-validated 2026-11-17)** — six seats changed on the
bench-v3 full-grid evidence (`evals/2026-11-16/grid2-scores.csv`, cell-level
source of truth): `cheap-code` glm→**haiku** `default` (I2 7.5 vs 5.5,
cheaper), `cheap-review` haiku→**glm** `low` (forced lineage swap: impl and
review can no longer both be claude-family), `cheap-design` glm→**haiku**
`medium` (glm cannot author designs: ≤1/11 at every effort), `strong-design`
s5.5→**1017** `high` (8.25 vs 7 at a quarter of the cost),
`strong-design-review` 1017→**minimax** `xhigh` (11.5/14 vs 5.5),
`strong-design-alternative` terra→**hydrogen** `high` (6 vs 4 on D; hydrogen
is REFUTED for review rungs — IR 1–2 FP/run — keep it off review seats).
The hard rule is unchanged: **impl and review are never the same family**.

**Roster final (owner-validated 2026-11-19)** — five seats changed on the
grid2 panel evidence (`evals/2026-11-16/grid2-scores.csv`, cell-level source
of truth; confirmation runs r91–r94, m83/m84):

1. `cheap-review` glm `low` → **minimax `xhigh`** (IR 4.33 bonus-inclusive,
   clean 3/3 runs, @ $0.014/task). Rationale: gates fail silently — floor
   recall is the protection, and the bonus-inclusive mean is the best recall
   measured at floor price. glm `low` (2.5) leaves review; it stays documented
   as the lineage-legal fallback reviewer for deepseek/gemini-produced work.
2. `strong-review` glm `high` → **sonnet `medium`** (IR 4.75 — 4 valid runs
   5;5;4;5, trace restored — @ $0.09/task). Rationale: a fresh family vs the
   minimax floor it escalates from; the rung above the floor is never the
   floor's own family.
3. `strong-review-alternative` sonnet `medium` → **1017 `high`** (IR 3.62
   bonus-inclusive @ $0.016/task). New holder — the lineage-legal fallback
   rung: deepseek reviews claude/glm/minimax-produced work. muse `medium`
   (IR 4.56 re-folded 11-20 from 3.75, 4 valid runs) scores higher but at 5–7× the cost — price wins
   at near-parity.
4. `strong-design-alternative` hydrogen `high` → **sonnet `high`** (D 8.4 in the
   cell — clean re-fold 8 (owner ruling 11-20) + H4 fold v3 +0.4 (039850d; 2026-11-19 RESULTS §7.3) — 4 runs 7.5;DNF;8.5;8.5, r92 DNF, 30-min watchdog required — @ $0.83/task).
   Rationale: hydrogen's 5.5 sits below the cheap tier (haiku medium 8.08) —
   an escalation rung below the floor it escalates to is not an escalation.
5. `strong-code-alternative` sonnet `high` → **haiku `high`** (I2 8.83/14 @
   ~$0.15/task; RG4 2-family panel 13.5/14 — ties opus at 13.5, see RESULTS §7.1 — the capability step above cheap-code (RG4 11.75)). Sonnet `high`
   left the code ladder for `strong-design-alternative`; it holds no code
   rung.

Unchanged: `strong-code` minimax `xhigh` (7.04 re-folded 11-20),
`strong-review-alternative2` qwen `xhigh` (IR 4.0 — 2 runs 4;4, misses
seeded-3 both runs), orchestration glm `high` (O 7). The hard rule is
unchanged: **impl and review are never the same family**.

**Project vs global — impl/review pairing.** The two rosters now pair
different models, and that is intentional: the project
roster pairs `impl` claude-haiku-5.5 / `review` minimax-m3p1-flash (`models.json`
"impl" / "review" — the pairing changed from the 09-29/10-07 glm/haiku pair);
the global roster runs `cheap-code` haiku / `cheap-review` minimax `xhigh`
(the final grid: haiku implements the bulk, minimax reviews claude-family
impl at the floor with the best recall measured there — IR 4.33
bonus-inclusive @ $0.014; glm `low` remains the documented fallback reviewer
for deepseek/gemini-produced work). Both satisfy the only invariant that
matters: **the reviewer's family differs from the implementer's.** The
scopes sync independently (`--update` vs `--update --global`).

Abbreviations (`models.json` model values): s5.5 = claude-sonnet-5.5, sol = gpt-6.1-sol (off the roster 10-26 — dominated by terra), opus = claude-opus-5.5, grok = grok-4.7, glm = glm-5p3-flash (gateway id: fw-glm-5.3-flash), qwen = qwen3p8-2p4t-a95b, pro = deepseek-v4-pro (OFF roster 11-16: old gateway id dead AND reported direct-Fireworks equivalent probed 404 — restore only when an id actually resolves), argon = gemini-4-argon, hydrogen = gemini-4-hydrogen, 1017 = deepseek-v4p1-flash-1017 (fireworks direct), M3.1 = minimax-m3p1-flash, terra = gpt-6.1-terra.

Eval 2026-09-30 addendum — qwen and pro join as the 7th/8th families
(`evals/2026-09-30-qwen3p8/`, `evals/2026-09-30-deepseek-v4-pro/`): qwen
`xhigh` is the best review ever measured here (3/3 seeded + 2 bonus defects,
each proven by executed snippets, $0.151 — grok's 3/3+2 without proofs was
$0.200); pro `high` matches qwen-tier design-review (10/10 seeded flaw
categories at `none`/`high`, $0.047–0.058 vs grok's $0.085). Effort facts:
qwen `xhigh` pays for itself on review/T1 only; pro `max` never pays
(shallower T4 than `none` at equal price). Both models kept while
accessible; **grok is the documented fallback for both `alternative2`
rungs**: MongoDB's managed-settings draft (`10gen/mongocode`) whitelists pro
but not qwen, so when the managed layer lands on a machine,
swap `strong-review-alternative2` back to grok.

Eval 2026-10-14 addendum — gemini-4-argon `high` takes the
`strong-design-review-alternative` rung (was s5.5 `medium`): argon `high` T4
9/10 average over 2 runs (10, 8) at ~$0.09/task vs s5.5's ~$0.13 — rung
swap, one more distinct lineage in the cross-review chain.

2026-11-25 maxfill: effort `max` measured (5 benches, 2-family panel) — 1017: ≈ its `high` everywhere, no re-seat; minimax: non-monotone (D 8.5/11 best measured at $0.149/task, I2-RG4 2.0/14 collapse, DR2 7.5) — seats unchanged, detail evals/2026-11-25/RESULTS.md.

### Escalation semantics

Rung N+1 is invoked only when rung N failed, stalled or expressed doubt —
never speculatively. Invoke rung N+1 with rung N's output attached — the
escalation reads what the previous rung already produced. The
`-alternative2` rung is the step before human intervention; its output must
state what a human must decide.

Eval-backed highlights: glm `high` reviews claude diffs 3/3+4 at $0.008 (the
grid's best deal — eligible because it reviews claude, never glm); haiku 5.5
`default` is now the review floor (eval 2026-10-07 — see `EVALS.md`); kimi-k3 is design/impl-capable but
2/3 as a reviewer — never a code-review role; design-review is scored
separately; terra and fable-5.1 are out (dominated / too expensive). A cheap
reviewer does miss things (2/3 models exist) and will
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
section (eval 2026-09-29, effort re-pinned per grid): bulk rungs at the
**cheapest effort that passes their task** — cheap-code at **`high`**
(glm: PASS 2/2 confirmed 10-16, cheaper than `low`), cheap-design at
**`low`** (glm: `high` degrades T4 to 6/10 — routine implementation needs no
reasoning budget, the misses are recovered
by review); review floors at **`default`** (cheap-review — haiku 5.5 caught
3/3 seeded defects at default effort in the 2026-10-07 eval, cheaper than any
`low`-effort rung); strong rungs pinned to the eval's
best effort — **`xhigh`** for strong-code (minimax, v2 swap 11-18) and
cheap-review (minimax, final 11-19), **`high`** for strong-design (1017),
strong-review-alternative (1017, final 11-19), strong-code-alternative
(haiku, final 11-19) and strong-design-alternative (s5.5, final 11-19),
**`medium`** for strong-review (s5.5, final 11-19) and
**`high`** for the gemini design-review alternative (the eval's effort facts
above apply).

When a replacement model is picked through the availability menu, `init.sh`
leaves the variant untouched — a different model may use a different effort
scale, so check the `variant:` line manually.

- **glm-5.3-flash runs `low` for cheap-design, `high` for cheap-code/impl
  and strong-review** (pinned 2026-10-16: the gateway exposes no `default`
  variant for this id). Per-task rule, best effort at the best price:
  T2 impl — `high` PASS 2/2 confirmed ($0.0049–0.0056, avg $0.00525) vs
  `low` PASS $0.0063 (1 run); T1 orchestration — `high` PASS $0.0050 vs
  `low` PARTIAL. But effort is non-monotone on T3/T4: `high` degrades
  (T3 2 FP vs low's 0; T4 6/10 vs 8/10), so cheap-design and any review/
  design-review use stay on `low` (`evals/2026-10-16/RESULTS.md` §T2).

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

   Each installed agent file carries its model family as a header line
   (`# Model family: <family>.`, injected by `init.sh` right after the
   `model:` line and derived from the model actually in effect), so lineage
   is readable at runtime instead of only in this page. An orchestrator
   dispatching a review must read the author's family and the reviewer's
   family header from the installed agent files and check they differ before
   dispatch — dispatching a same-family review is a RULE-DEVIATION that must
   be justified like any other, with the grid's one documented exception:
   the `-alternative` re-review rung may share the producer's family (the
   fresh-family pass already happened at the previous rung, see the Lineage
   rule above).

When `init.sh` finds a configured model unavailable in the target
installation, it proposes candidates from the same provider and family; this
page is the reference for judging them.

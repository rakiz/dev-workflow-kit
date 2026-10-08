# Model eval results — 2026-10-07/08

Completion campaign for two grids left open on 09-29/30: **claude-haiku-5.5**
(full 4-task × effort grid) and **ember-1** (partial grid), plus the missing
deepseek effort arms and the qwen default run. Protocol + re-run method:
`../README.md`. Raw runs live in the opencode session DB (titles
`eval-2026-10-07/08-*`); 19 new runs were executed this campaign (~$0.78),
everything else scored from DB text.

## Grid — claude-haiku-5.5 (github-copilot, $ ~claude-haiku rates via Copilot)

Cost measured from DB; score is mine (0–10 role quality; T3 scored n/3 with
false positives counted; T2 verified objectively by re-running the suite in
the run dir).

| Task | low | default | medium | high | xhigh | max |
|---|---|---|---|---|---|---|
| T1 orchestration | 7 / $0.0092 | 6 / $0.0085 | 8 / $0.0097 | 8 / $0.0115 | **9** / $0.0265 | **FAILED** / $0.0365 |
| T2 impl | ✅ 9 / $0.0072 | ✅ 9 / $0.0071 | ✅ 9 / $0.0085 | ✅ 9 / $0.0094 | ✅ 9 / $0.0103 | ✅ 9 / $0.018 |
| T3 review | **3/3** / $0.0069 | **3/3** / $0.0063 | **3/3** / $0.0076 | 2/3 / $0.0073 | **3/3+proofs** / $0.0163 | **FAILED** / $0.024 |
| T4 design-review | 7 / $0.0067 | 8 / $0.0069 | 7 / $0.0071 | 8 / $0.0109 | **9** / $0.0183 | **FAILED** (×2) / $0.015 |

Notes per cell:

- T1 default: grounded plan but admitted it did not read `test_synccli.py`
  and never executed the baseline — red-baseline trap planned, not seen.
- T1 xhigh: best plan of the grid — explicit decision list (D0–D5),
  contract block, agent legend; caught the failing test by reading.
- T1 max: session died mid-run (last message 0 output tokens; final text is a
  stray reasoning fragment). Recorded as failed/truncated, not scored.
- T2: all 6 variants produced the minimal `range(1,…)`→`range(len(items))`
  fix; suite green in every run dir (re-verified with `python3 -m unittest`).
- T3 `high` was the only review miss: it found the mutable default but
  mis-mechanized the silent-copy defect (caught the swallowed exception, not
  the lying `done`) and floated a speculative mtime-conflict finding
  (FP-ish). `xhigh` reproduced defects by execution — proofs at claude-flash
  price.
- T3/T1 `max`: two distinct max failures (32k reasoning with zero output on
  T3; dead session on T1). Same failure shape as sonnet's `max`: cost rises,
  delivery risk rises, quality does not.
- T4 xhigh is the standout cheap result of the whole campaign: it **built a
  50k-file tree and measured** 1.2 s/scan, 3.8 MB manifest, ~230 GB/day
  writes, then verified 3 breakages empirically. 9/10 flaw categories, zero
  FP, at $0.018.

Cost / 4 tasks (default effort): **$0.029** — same league as deepseek
($0.033), 12x under sonnet. Full grid (24 runs): **$0.294**.

## Grid — ember-1 (fireworks, partial)

| Task | Variant | Cost | Score |
|---|---|---|---|
| T1 | high | $0.1348 | 7 — grounded, predicted the red test by reading; no executed baseline |
| T2 | medium | $0.1737 | 6 — fix correct, suite green (verified), but no diff in the report |
| T3 | medium | $0.1633 | **3/3** — incl. the never-purged-manifest defect, cleanly argued |
| T4 | high | $0.0920 | 6.5 — ~7/10 categories; missed instance lock, hardcoded config |

Partial-grid 4-task total **$0.56** — sonnet-class price for mid-grid
quality. Every role it could fill is already held by a cheaper equal or
better (glm, deepseek, haiku, qwen). **Ruled out.**

## Grid — deepseek-v4p1-flash, missing effort arms

| Task | low | max | default (=high, 09-30) |
|---|---|---|---|
| T1 | 8 / $0.0146 | 8 / $0.0167 | 8 / $0.0087 |
| T2 | ✅ 9 / $0.0113 | ✅ 9 / $0.0129 | ✅ 9 / $0.0075 |
| T3 | **3/3** / $0.0146 | **2/3** / $0.0554 | 2/3 / $0.0088 |
| T4 | 8 / $0.0124 | **9 (STOP verdict)** / $0.019 | 9 / $0.0084 |

New effort lesson for deepseek: `low` is a *better reviewer than `max`* —
T3-max found the two code defects with proofs but **explicitly dismissed the
merge-manifest defect as "a defensible design choice"** at 4x the cost of
`low`, which found all 3. `max` pays more and rationalizes more. The
keep-default decision (09-30) stands; `low` is a viable budget arm, `max` is
never worth it.

## Grid — qwen3p8-2p4t-a95b, default run (grid gap)

`high` **does not exist** for this model (`opencode models --verbose`:
variants = low/medium/xhigh only); the unfilled cell was the default run.

| T1 | T2 | T3 | T4 | 4-task total |
|---|---|---|---|---|
| 7.5 / $0.0996 | ✅ 9 / $0.1113 | **3/3+proofs** / $0.1304 | **9.5** / $0.147 | **$0.488** |

Confirms the 09-30 verdict: tier-1 review depth (empirical proofs, the
truncation-to-zero-byte corruption, copy-storm analysis) — but $0.49/4t and a
deliberately-skipped design round on T1. Reviewer-only, escalation rung.

## Extra DB runs scored (2026-10-02, glm confirmation)

Two T2 re-runs of glm-5.3-flash (`none`): correct minimal fix, suite green,
$0.0065/$0.0081 — confirms the $0.007/T2 figure behind the incumbent roster.

## Line-by-line vs the 09-29 incumbents

- Review ladder (≠ impl family): **haiku default $0.0063 3/3** inserts itself
  below gemini low $0.029 3/3 and glm high $0.008* (non-glm-diff-only). 4.6x
  under gemini at equal recall, on a full 6-variant grid.
- Cheap bulk: haiku 4t default $0.029 ≈ deepseek $0.033 — a tie on cost, so
  the differentiators are recall (T3: haiku 3/3 vs deepseek 2/3) and lineage
  flexibility.
- Impl $0.007: glm and haiku are tied to the cent ($0.0065–0.0081 vs
  $0.0071), both always green. glm keeps it: moving impl to claude would
  break the reviewer≠impl constraint with a haiku cheap-review.
- Nothing in this campaign touches the strong rungs: sonnet/opus/sol/qwen
  keep their positions; ember-1 adds nothing anywhere.

## Effort lesson — claude-haiku-5.5 (low → max)

- `low`: not the sonnet-style hallucination trap — T1/T3/T4 all usable, 3/3
  review. Cheap and safe for read-only roles.
- `default`/`medium`: the sweet spot — 3/3 review at $0.006–0.008, clean
  impl, solid plans.
- `high`: T3 recall *dropped* (2/3, one speculative FP) — for haiku, more
  appetite does not mean more rigor on review.
- `xhigh`: the peak — measured-not-guessed T4 (built the 50k fixture), proved
  T3, best T1 plan. Worth it for deep design-review only ($0.018, still
  cheap).
- `max`: broken for this model. 3 attempts across T1/T3/T4: one dead session,
  one 32k-reasoning-no-output, one hang repeated twice. Never assign `max` to
  haiku; the claude "xhigh/max converges to opus pricing with no gain"
  lesson now applies from the *flash* end of the family too.

## Skip log

| Not run | Reason |
|---|---|
| ember-1 remaining arms (T1/T2 low-max etc.) | Partial grid already shows mid quality at $0.56/4t (sonnet-class price); no role it could win — dominated by glm/deepseek/haiku. Additional arms could not change any decision. |
| claude-opus-5.5 / claude-sonnet-5.5 / claude-fable-5.1 | Sonnet low→max fully tested 09-29; opus `xhigh` known zero-gain; fable ruled out on price. |
| gpt-6.1-sol `xhigh` | Announced, not tested. Optional future run (~$0.33). Only worth it if a strong-design-review decision ever hinges on sol vs qwen — today it does not. |
| qwen `high` | Variant does not exist (low/medium/xhigh only). Default run executed instead. |
| minimax / grok-4.20 / gpt-6-luna / nemotron / qwen-max / fw-glm-5.3 / fw-deepseek-v4-pro extra arms | All judged in 09-30 evals; no new information expected. |

## Roster proposal (change only where the data justifies it)

| Function/Role | cheap | strong | alternative | alternative2 |
|---|---|---|---|---|
| **orchestration** | glm `none` *(unchanged)* | s5.5 `high` | opus | — |
| **design** | glm `none` *(unchanged)* | s5.5 `high` | sol | opus |
| **design-review** | deepseek *(unchanged)* | sol | s5.5 `medium` | grok |
| **impl** | glm `none` *(unchanged)* | s5.5 `high` | sol `xhigh` | opus |
| **impl-review** | **haiku `default`** ← gemini `low` | glm `high` | s5.5 `medium` | **haiku `low`** ← grok |

Changes and their evidence:

1. **impl-review cheap: gemini `low` → claude-haiku-5.5 `default`.**
   Evidence: measured $0.0063 (3/3, T3 default, DB) vs gemini $0.029 (3/3);
   full-grid confirmed (3/3 on 4 of 6 efforts, no FP). Cross-lineage holds:
   impl is glm, cheap-review becomes claude — reviewer ≠ producer ✓
   (models.json: `review`/`cheap-review`). Risk: single-sample-per-variant
   recall — the minimax lesson; mitigation: gemini `low` drops to
   alternative2 (replaces grok, which moves to documented fallback), and any
   T3 recall regression in pipeline logs reverts the swap. `high` is pinned
   out for haiku reviews (2/3 measured).
2. **cheap-mech/explore: no change.** Haiku 4t $0.029 ≈ deepseek $0.033 — a
   cost tie, and deepseek's explore/cheap-mech output (quantified, tier-1
   plans) was never beaten; keeping deepseek also preserves a third lineage
   in the rotation. Haiku is the recorded substitute if deepseek pricing
   moves.
3. **qwen: no change.** The `high` cell cannot exist; the default run
   ($0.488/4t, 3/3+proofs, 9.5 T4) re-confirms `xhigh` reviewer-only
   placement at `strong-review-alternative2`.
4. **glm impl at $0.007/T2: no change.** Haiku ties it to the cent but
   adopting haiku as impl would invalidate the haiku cheap-review (lineage
   constraint). glm keeps impl + cheap-design.
5. **deepseek: no change, with a new constraint.** Never use its `max`
   (2/3 at 4x cost, rationalizes defects away); `low` is the budget arm of
   record ($0.053/4t) if explore/cheap-mech need to get cheaper.

Ordinary pipeline unchanged at ~$0.05/run — the haiku swap trims the review
line to ~$0.006, bringing a cheap+review pipeline closer to ~$0.04.

## Status

- ✅ Applied here: `EVALS.md` rows (haiku-5.5, ember-1, sonnet price note),
  `models.json` cheap-review swap.
- ⬜ Not done (manual): `init.sh --global` re-run, MODELS.md narrative, git
  commit.

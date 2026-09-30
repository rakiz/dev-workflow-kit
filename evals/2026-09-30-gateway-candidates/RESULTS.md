# Model eval results — 2026-09-30 gateway candidates

Five untested models exposed by the new AI Gateway (Grove), full 4-task matrix
each, default effort. Protocol: `../README.md`; scored against the same seeded
defects as `evals/2026-09-29/`. Raw transcripts: `outputs/`.
Prices from the gateway catalog on eval day (`opencode models --verbose`).

## The models

| Model | Provider used | $/MTok in/out | Cost / 4 tasks | Strength | Weakness |
|---|---|---|---|---|---|
| gpt-6-luna | ai-gateway-openai | $0.074/$0.37 | **$0.015** | cheapest run of any eval; T3 defects proven by execution | shallow T1, T4 mid (7/10) |
| minimax-m3 | fireworks-ai | $0.30/$1.20 | **$0.094** | **only 3/3 on T3** (+3 bonus, 0 FP) at $0.019/run; deepest mechanical T4 | T1 trap-blind; missed ⑦⑨ on T4 |
| fw-glm-5.3 (non-flash) | ai-gateway-misc | $1.14/$3.58 | **$0.189** | consistent, 0 FP everywhere, rich agent orchestration on T1 | T3 2/3; T4 blesses sync() reuse + hardcoded config |
| grok-4-20-reasoning | ai-gateway-misc | $1.48/$4.44 | **$0.225** | T4 breadth 9/10, "STOP & redesign" verdict | **hallucinated repo structure on T1**; T3 wrong mechanism |
| qwen3p8-max | fireworks-ai | $2.00/$6.00 | **$0.434** | best T4 measured here (9/10, actually ran measurements) | **fabricated a green T1 baseline** (claimed 6/6 pass on a red suite) |

Prices seen on Copilot the same day where different: luna $0.10/$0.50.
Note: first qwen3p8-max/minimax-m3 attempts via `ai-gateway-misc` failed with
gateway server errors; scored runs are the fireworks-ai reruns.

## Task detail

- **T1 (orchestration)** — universal finding: **none of the 5 executed the
  tests**; the red-baseline trap caught every candidate. qwen3p8-max is the
  only one that *lied* about it ("currently 6 tests, all pass"). grok-4-20
  hallucinated a `synccli/__main__.py` package layout that does not exist.
  All five produced grounded plans, correct pipeline-agent assignment and
  verifiable criteria otherwise.
- **T2 (impl)** — all 5 green with a minimal one-line fix. qwen's
  `for path, fresh in items:` is the cleanest; all others `range(...)` variants.
- **T3 (review)** — seeded: (1) mutable default arg, (2) silent copy failure →
  lying `done`, (3) merge_manifest never purges deletions.
  minimax **3/3** (+3 real bonus, 0 FP, $0.019 — beats gemini-3.8-flash `low`
  $0.029 with 3/3 and adds bonus findings); luna 2/3 but the only run that
  *proved* defects by executing snippets; glm 2/3 (missed #3); qwen 2/3
  (missed #3, best-articulated #2); grok 2/3 with the wrong mechanism for #2.
- **T4 (design-review)** — qwen 9/10 (missed renames only; ran actual timing
  measurements, caught the sqlite3-stdlib claim error); grok 9/10 (missed
  instance lock); glm 8/10 but blessed two seeded flaws; minimax 7.5/10
  deepest mechanically (inode/ctime + xxh3 sampling, SQLite/WAL); luna 7/10.

## Status

- ✅ Measured: 5 models × 4 tasks, 20 runs + 2 failed provider-mismatch runs.
- ❌ Rejected: **gpt-6-astra without a run — price only** ($7.40/$37 gateway,
  $10/$50 Copilot, cache read $0.74–$1.00): ~4x opus-5.5 for a role the kit
  never fills at that price. Re-entry condition recorded in `../../EVALS.md`.
- 🤔 **Cheap-review upset**: minimax-m3 found 3/3+3 at $0.019 vs incumbent
  gemini-3.8-flash `low` 3/3 at $0.029 — **confirmation FAILED**: two reruns
  scored 3/3 (0 FP, faithful) then 1/3 with 1 FP (missed the copy_file
  interaction and the purge defect entirely). Recall 3/3 in 2 of 3 runs is
  too volatile for the review floor; gemini keeps `cheap-review`.
- No incumbent displaced: glm-5p3-flash impl, deepseek explore/design-review,
  s5.5/sol/opus strong rungs all keep their ladders. qwen3p8-max is NOT an
  orchestrator candidate (fabricated baseline) but is the new depth reference
  for design-review escalation if a confirmation run holds.
- ✅ Settled 2026-09-30: minimax-m3 confirmation ran (2 reruns of T3) —
  rejected for variance, see `../../EVALS.md`.

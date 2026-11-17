## Repo facts (already explored — read-only)

- `synccli.py`: `sync(src, dst, dry_run=False)` returns copied rel-paths; `main()` prints one path/line; exit code always 0. `copy_file()` silently swallows `OSError`.
- Internal callers constraining the work: `incremental.py:5` imports `copy_file`; tests call `sync()` positionally; DESIGN.md plans a `syncd` daemon "reusing `sync()` directly".
- **Key ambiguity driving the plan**: GOAL requires `"skipped": N` but nothing today computes a skip count, and `copy_file`'s swallowed errors mean a failed copy still lands in `copied`. This needs a design decision before code.

## Execution plan

**T1 — Design: `skipped` semantics + JSON emission point**
- Objective: settle (a) what `skipped` counts (candidates: src files not needing copy vs. copy failures — must pick one and define it against `copy_file`'s silent-OSError behavior); (b) how to compute it **without touching `sync()`'s signature** (new helper e.g. `sync_report()`, or manifest exposure); (c) JSON emitted only in `main()`, guaranteeing nothing else reaches stdout in `--json` mode; (d) `--dry-run` + `--json` semantics (`copied` = would-copy list, manifest untouched); (e) exit code stays 0.
- Files: create `DESIGN-json.md` (do not edit `DESIGN.md` — that's the v2 daemon doc).
- Agent: cheap-design.
- Risks: picking a `skipped` definition that contradicts GOAL's example; changing `sync()` signature (breaks `incremental.py`/future `syncd`); stdout pollution from argparse or error paths.
- Acceptance: doc explicitly answers a–e with rationale; states `sync(src_root, dst_root, dry_run=False)` unchanged.

**T2 — Design review**
- Objective: critique T1 before code exists — check `skipped` definition consistency, signature-stability constraint, dry-run interplay, stdout-purity plan.
- Files: none (read-only).
- Agent: cheap-design-review.
- Risks: design misses that `copied` may include failed copies (machine-visible lie in JSON mode).
- Acceptance: written verdict; every major finding folded back into `DESIGN-json.md` before T3 starts.

**T3 — Implementation + tests**
- Objective: add `--json` flag and JSON output per approved design; keep human mode byte-identical; add unit tests to `test_synccli.py`: output parses as a single JSON object, exact key set `{copied, skipped, src, dst}`, `copied` contents, `skipped` type/semantics, dry-run+json lists would-copy and writes no manifest, human mode unchanged.
- Files: modify `synccli.py`, `test_synccli.py`. Stdlib only, no new deps.
- Agent: cheap-code.
- Risks: stray `print` in non-JSON paths or double output; accidentally altering `sync()` signature; tests asserting dict-key order instead of JSON shape.
- Acceptance: `python3 -m unittest -v` green (old + new tests); `git diff` shows zero changes to `sync()`'s signature line and to `incremental.py`.

**T4 — Code review**
- Objective: fresh-eyes review of the T3 diff against `DESIGN-json.md` and GOAL constraints.
- Files: none (read-only).
- Agent: cheap-review (fresh instance, self-contained brief).
- Risks: subtle stdout leakage (e.g., future error print), JSON emitted in human mode, signature drift.
- Acceptance: verdict delivered; minor findings fixed by resuming the T3 cheap-code instance via `task_id`, re-running tests; any major escalates to strong-code with evidence.

**T5 — Final verification gate**
- Objective: demonstrate all four GOAL items verbatim: (1) `--json` prints exactly one JSON object with the required keys on stdout, nothing else, exit 0; (2) `--dry-run --json` → `copied` = would-copy, dst untouched; (3) human mode output unchanged; (4) full suite green.
- Files: none.
- Agent: orchestrator (mechanical fixes, if any, via cheap-mech).
- Risks: environment drift between test run and smoke run (stale `__pycache__`).
- Acceptance: captured command output for all three modes + `python3 -m unittest -v` pass, checked line-by-line against GOAL.md.

Out of scope, flagged but untouched (ask-before-acting): `incremental.py:10` mutable-default-arg bug (`excluded=[]`) and the DESIGN.md v2 daemon — neither is requested by GOAL.

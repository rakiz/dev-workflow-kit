

Execution plan for GOAL.md (`--json` + `--dry-run` semantics). Repo facts: `synccli.py` (103 ln), `incremental.py` (40 ln, internal caller of `sync()`), `test_synccli.py` (55 ln), plus `DESIGN.md` (v2 daemon — out of scope for this release).

**Task 1 — Baseline survey**
- Objective: map `sync()` signature, its callers (`incremental.py`, CLI entry in `synccli.py`), current stdout behavior and `--dry-run` handling; confirm Python 3.10 stdlib-only baseline and test invocation (`python3 -m unittest -v`).
- Files: none (read-only).
- Agent: explore.
- Risks: hidden internal callers or prints that would violate the "nothing else on stdout" constraint.
- Acceptance: written report listing every `sync()` call site and every stdout write in `synccli.py`/`incremental.py`, with file:line.

**Task 2 — Design review of the JSON-mode approach (pre-code)**
- Objective: validate approach before implementation: where the flag lives (argparse in CLI layer), how `sync()` reports results without signature change (e.g. return value / callback / kwargs with defaults), stdout suppression strategy, and exact dry-run ∩ json semantics (`copied` = would-copy list).
- Files: none (critique only; outcome recorded in the impl brief).
- Agent: design-review (cheap-design-review; escalate strong-design-review only if real tradeoffs surface).
- Risks: changing `sync()` behavior in a way that breaks `incremental.py`; leaking progress/error output to stdout in JSON mode.
- Acceptance: verdict stating a chosen result-passing mechanism that keeps `sync()` signature stable, plus error-output destination (stderr) agreed.

**Task 3 — Implementation**
- Objective: add `--json` flag; emit exactly one JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` to stdout; `--json --dry-run` populates `copied` with would-copy paths; human mode byte-for-byte unchanged; no new deps; `sync()` signature untouched.
- Files: modify `synccli.py`; touch `incremental.py` only if Task 2 says adaptation is needed.
- Agent: impl (cheap-code).
- Risks: extra stdout noise (logs, errors) breaking JSON parsability; `skipped` count semantics drifting from human mode; dry-run still performing copies.
- Acceptance: `python3 -m synccli --json src dst | python3 -m json.tool` succeeds and shows all four keys; exit code matches pre-change behavior; `git diff` shows no signature change to `sync()`.

**Task 4 — Tests**
- Objective: unit tests in `test_synccli.py` for: JSON validity, all keys present, correct types (`copied` list, `skipped` int), dry-run lists would-copy without copying, human-mode regression test.
- Files: modify `test_synccli.py`.
- Agent: impl (cheap-code, same session via task_id if Task 3 context is fresh).
- Risks: tests invoking real filesystem copies without tmpdir isolation; not capturing stdout (must use redirect/`subprocess` capture).
- Acceptance: `python3 -m unittest -v` passes with the new tests included and zero pre-existing tests modified/removed.

**Task 5 — Code review (mandatory)**
- Objective: review diff from Tasks 3–4 against GOAL.md constraints: single JSON object on stdout, signature stability, stdlib-only, human mode unchanged.
- Files: none (read-only review of `synccli.py`, `incremental.py`, `test_synccli.py` diff).
- Agent: review (cheap-review; escalate to strong-code only on a major finding).
- Risks: minor findings missed (e.g. trailing newline/print duplication, non-serializable paths).
- Acceptance: verdict issued; all findings resolved and tests re-run green before sign-off.

**Task 6 — Docs touch-up**
- Objective: document `--json` and its dry-run interplay in README.md usage section.
- Files: modify `README.md`.
- Agent: impl (cheap-mech — mechanical).
- Risks: none material.
- Acceptance: README shows `--json` example whose output matches the actual emitted shape.

Out of scope, flagged: DESIGN.md's `syncd` daemon — separate effort; if pursued later it needs its own design cycle (strong-design), not this pipeline.
## Baseline facts (from GOAL.md, README.md, repo)

- **Scope**: GOAL.md = add `--json` to `synccli.py` + tests in `test_synccli.py`. DESIGN.md is a *different* goal (v2 sync daemon) → out of scope.
- **Existing suite is already red**: `TestCollectStale::test_first_item_stale_is_included` fails (`collect_stale` starts at `range(1, ...)`, skipping index 0). Unrelated to this goal.
- `sync()` at synccli.py:72 returns `to_copy` and early-returns on `dry_run` — signature must stay stable, so JSON assembly belongs in `main()`, not `sync()`.
- `incremental.py:10` has a mutable-default-arg bug (`excluded=[]`) — out of scope, do not touch.

---

## Task 1 — Baseline audit & ambiguity resolution (explore)

- **Objective**: Confirm current behavior of `main()`/`sync()` (stdout, exit codes, dry-run, manifest write) and pin down the two unspecified points in GOAL.md: (a) semantics of `skipped` (proposal: `skipped = len(all_scanned) - len(copied)` or "unchanged files"), (b) exact `src`/`dst` values (raw CLI strings vs normalized paths).
- **Files**: read-only `synccli.py`, `test_synccli.py`, `GOAL.md`, `README.md`; no edits.
- **Agent**: `explore`
- **Risks**: Re-litigating DESIGN.md (wrong goal); silently deciding `skipped` semantics without recording the decision.
- **Acceptance**: Written decision record for `skipped`, `src`/`dst` representation, and confirmation that JSON-from-`main()` keeps `sync()` untouched.

## Task 2 — Design-review of the JSON integration (design-review)

- **Objective**: Critique Task 1's approach before code: single-object stdout guarantee, `--json` × `--dry-run` matrix, human-mode unchanged, no new deps, Python 3.10 stdlib only, exit code unchanged.
- **Files**: none (read-only critique of Task 1 output).
- **Agent**: `cheap-design-review`
- **Risks**: Approving an approach that prints anything else to stdout (e.g. debug/log output); missing that `copy_file` silently swallows `OSError` (synccli.py:68) so "copied" may include failed copies.
- **Acceptance**: Explicit verdict + list of required changes; unresolved items returned to Task 1.

## Task 3 — Implement `--json` in `synccli.py` (impl)

- **Objective**: Add `--json` flag; when set, print **exactly one** JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` to stdout and nothing else; combine with `--dry-run` so `copied` = would-be-copied; keep human mode (one path per line) byte-identical; preserve `sync()` signature and exit code 0.
- **Files**: modify `synccli.py` only (`main()` primarily; no change to `sync()` contract).
- **Agent**: `cheap-code`
- **Risks**: Extra stdout leakage (argparse usage goes to stderr — fine; any `print` besides JSON is a violation); writing the manifest during dry-run (must not); `json.dump` vs `print(json.dumps(...))` trailing-newline assumptions; non-ASCII paths (`ensure_ascii` decision).
- **Acceptance**: `python3 -m synccli SRC DST --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert set(d)=={"copied","skipped","src","dst"}'` succeeds; stdout is a single object; human mode output unchanged; `sync()` call sites unaffected.

## Task 4 — Add JSON-shape tests to `test_synccli.py` (impl)

- **Objective**: Unit tests per GOAL.md item 4: valid JSON parse, all four keys present, dry-run semantics (`copied` = would-be list, no files/manifest written), human mode still one-path-per-line, stdout purity in JSON mode.
- **Files**: modify `test_synccli.py` only.
- **Agent**: `cheap-code`
- **Risks**: Capturing `main()` stdout requires `io.StringIO` + `contextlib.redirect_stdout` (stdlib only); tests must not depend on mtime ordering; must not "fix" the pre-existing `collect_stale` failure inside this task.
- **Acceptance**: New tests pass; JSON tests fail against the pre-Task-3 code (confirm they actually guard the feature).

## Task 5 — Mandatory review (review)

- **Objective**: Review the Task 3+4 diff for GOAL compliance and regressions.
- **Files**: read-only diff of `synccli.py`, `test_synccli.py`.
- **Agent**: `cheap-review`
- **Risks**: Reviewer skimming stdout-purity case; missing `sync()` signature drift; scope creep (fixing unrelated failures).
- **Acceptance**: Findings classified minor/major; minor → resume Task 3 instance; major → escalate (with user notification) per pipeline.

## Task 6 — Final verification (review/audit)

- **Objective**: Run `python3 -m unittest -v` and the manual acceptance commands; report results.
- **Files**: none (read-only).
- **Agent**: `strong-review` (or orchestrator-run commands + review)
- **Risks**: Treating a green JSON suite as "all green" while the pre-existing `collect_stale` failure remains — must be reported explicitly, and fixing it requires an explicit yes (out of GOAL scope).
- **Acceptance**: Report states: new JSON tests pass, human-mode tests pass, and the one pre-existing unrelated failure is unchanged from baseline; final verdict GOAL satisfied / not satisfied.

---

**Gate**: Tasks 1–2 produce decisions with no code; Task 3 must not start until Task 2's verdict is recorded. Nothing in this plan authorizes touching `incremental.py` or DESIGN.md's daemon goal.

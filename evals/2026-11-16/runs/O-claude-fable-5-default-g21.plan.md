# Execution plan — `--json` + dry-run UX

Repo layout: single-module project (`synccli.py`, `test_synccli.py`, `incremental.py` likely an internal caller of `sync()`).

## Task 1 — Explore current CLI & `sync()` contract
- **Objective**: Map `synccli.py` (arg parsing, output points, `sync()` signature/return value, dry-run handling), `incremental.py`'s use of `sync()`, existing test patterns in `test_synccli.py`, and any constraints in `DESIGN.md`. Determine whether `sync()` already returns the data needed (copied list, skipped count) or only prints.
- **Files**: read-only — `synccli.py`, `incremental.py`, `test_synccli.py`, `DESIGN.md`.
- **Agent**: `explore`.
- **Risks**: missing a hidden stdout write (e.g. prints inside `sync()`), which would break the "nothing else on stdout" guarantee later.
- **Acceptance**: report naming (a) `sync()` signature + return type, (b) every stdout write site, (c) how dry-run currently works, (d) internal callers of `sync()`.

## Task 2 — Mini design note: output separation
- **Objective**: Decide how to keep `sync()` signature stable while routing results to either human lines or one JSON object — most likely: `sync()` returns structured data (or already does), all printing moved to the CLI layer; define exact JSON shape `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` incl. path representation (str vs relative) and dry-run semantics.
- **Files**: text decision only (or short note in conversation; no repo file unless DESIGN.md update requested).
- **Agent**: `cheap-design`, then **`cheap-design-review`** only if Task 1 reveals real tension (e.g. `sync()` currently prints internally and callers rely on that); otherwise skip review — stakes are small.
- **Risks**: changing `sync()` return value in a way internal callers observe; JSON printed alongside stray prints/log lines.
- **Acceptance**: design states signature unchanged, lists all print sites to move/guard, and specifies JSON keys/types and dry-run meaning.

## Task 3 — Implement `--json` flag
- **Objective**: Add `--json` to the arg parser; in JSON mode emit exactly one `json.dumps` object on stdout and suppress all other stdout output; human mode byte-identical to today; exit codes untouched; works combined with `--dry-run` (`copied` = would-copy list). Stdlib only.
- **Files**: modify `synccli.py` (and `incremental.py` only if the explore shows print relocation touches it).
- **Agent**: `cheap-code`.
- **Risks**: non-JSON output leaking to stdout (errors should go to stderr); altering human-mode formatting; breaking `incremental.py`; non-serializable `Path` objects in `copied`.
- **Acceptance**: `python3 -m unittest -v` passes; manual check: `python3 synccli.py src dst --json` stdout parses with `json.loads` and has the 4 keys; human-mode output unchanged on the same inputs.

## Task 4 — Unit tests for JSON shape
- **Objective**: Add tests to `test_synccli.py`: output is valid JSON; keys `copied/skipped/src/dst` present with right types; `--json --dry-run` lists would-copy files and copies nothing; stdout contains nothing but the JSON object; human mode regression test (one path per line).
- **Files**: modify `test_synccli.py`.
- **Agent**: `cheap-code` (can be the same session as Task 3 — same files, same contract; reuse `task_id`).
- **Risks**: tests capturing stdout incorrectly (follow existing test harness pattern); tests that pass trivially (e.g. not asserting dry-run performed no copies).
- **Acceptance**: new tests fail if JSON mode prints extra lines or dry-run copies files (spot-check by temporary mutation), and full suite passes.

## Task 5 — Review
- **Objective**: Independent read of the full diff (Tasks 3+4) against GOAL.md constraints: signature stability, stdout purity in JSON mode, human mode unchanged, stdlib-only, test adequacy.
- **Files**: read-only.
- **Agent**: `cheap-review` (fresh session, self-contained prompt with the diff). Minor findings → resume the Task-3/4 `cheap-code` session; major finding → escalate to `strong-code` (announced first).
- **Risks**: reviewer missing the "nothing else on stdout" requirement — call it out explicitly in the brief.
- **Acceptance**: review verdict with zero unresolved major findings; suite green after any fixes.

Ordering is strict: 1 → 2 → 3 → 4 → 5 (3 and 4 may share one implementer session). No modifications made now, per your instruction.

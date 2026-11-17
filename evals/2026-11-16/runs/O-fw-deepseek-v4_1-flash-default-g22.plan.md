## Execution plan — `--json` + `--dry-run` UX (GOAL.md)

Scope note: only GOAL.md items 1–4 are in scope. `DESIGN.md` (continuous-sync daemon) is unrelated and must **not** be touched. No new deps; Python 3.10 stdlib; `sync()` signature frozen (internal callers exist — `incremental.py` imports `copy_file`, and `test_synccli.py` calls `sync`).

---

### Task 1 — Pin semantics & caller inventory (explore)
- **Objective:** Resolve the two ambiguities GOAL.md leaves open before any code: (a) exact definition of `skipped`; (b) every caller of `sync()`/`main()` so the frozen-signature constraint is honored.
- **Files:** read-only — `synccli.py`, `incremental.py`, `test_synccli.py`, git log.
- **Agent:** `explore`.
- **Risks:** guessing `skipped` wrongly poisons the JSON contract; missing a `sync()` caller breaks the constraint silently.
- **Acceptance:** a written finding stating (1) `skipped` = count of files present in `src` but **not** in the copy set (`len(src_manifest) - len(copied)`), and (2) the full list of `sync()`/`main()` call sites, with confirmation none require a signature change.

### Task 2 — Design decision: how to surface `skipped` without touching `sync()` (design-review)
- **Objective:** Choose between (A) compute `skipped` in `main()` via a second `build_manifest(src)` call, or (B) add a new `sync_report()` wrapper returning `{"copied","skipped"}` and have `sync()` delegate. Decide where JSON is emitted (in `main`, never inside `sync`).
- **Files:** design note only; targets `synccli.py` (no edit yet).
- **Agent:** `cheap-design` + `cheap-design-review`.
- **Risks:** double-scan cost (A) vs. added public surface (B); emitting JSON inside `sync()` would violate the frozen contract and break `test_synccli.py`.
- **Acceptance:** a chosen option with rationale, explicitly preserving `sync()` signature and keeping stdout emission in `main()`.

### Task 3 — Implement `--json` + `--dry-run` interplay (impl)
- **Objective:** Add `--json` to the parser; in `main()`, when set, print exactly one JSON object `{"copied":[...],"skipped":N,"src":...,"dst":...}` to stdout and print nothing else; human mode prints one path per line unchanged; `--dry-run --json` reports would-be copies; exit code stays `0`.
- **Files:** modify `synccli.py` only.
- **Agent:** `cheap-code`.
- **Risks:** stray prints to stdout breaking JSON purity; `argparse` help/errors (stderr/stdout) must not interfere in normal runs; `src`/`dst` must be the raw arg strings; `skipped` must be non-negative and correct in dry-run.
- **Acceptance:** `python3 -m synccli --json S D` output is `json.loads`-parseable, has exactly the four keys, exit code `0`; `--dry-run --json` `copied` matches would-be set and writes nothing; non-JSON mode output is byte-identical to before.

### Task 4 — Unit tests for JSON shape & dry-run semantics (impl)
- **Objective:** Add tests to `test_synccli.py`: valid JSON, all four keys present, `skipped` semantics, and `--dry-run --json` `copied` = would-be copies with no files written; assert human mode unchanged.
- **Files:** modify `test_synccli.py`.
- **Agent:** `cheap-code` (same instance as Task 3).
- **Risks:** capturing stdout in tests (use `contextlib.redirect_stdout`/`io.StringIO`); tests must not depend on mtime resolution flakiness; no new deps.
- **Acceptance:** `python3 -m unittest -v` passes, including the new cases, with no regression in existing tests.

### Task 5 — Independent review (review)
- **Objective:** Audit the diff against GOAL.md line-by-line: stdout purity in `--json`, dry-run semantics, unchanged human mode, frozen `sync()` signature, stdlib-only.
- **Files:** read-only — `synccli.py`, `test_synccli.py`.
- **Agent:** `cheap-review` (fresh, self-contained prompt).
- **Risks:** a passing test suite can still hide a stray stdout write or a signature drift.
- **Acceptance:** verdict of no major findings; any minor finding fed back to Task 3/4's `cheap-code` instance for a fix + re-review.

### Task 6 — Final acceptance run (review / verification)
- **Objective:** Reproduce the GOAL.md acceptance criteria end-to-end on a scratch tree.
- **Files:** none modified.
- **Agent:** `strong-review` if the diff is non-trivial or Task 5 raised anything; otherwise the orchestrator runs the commands directly.
- **Risks:** environment-dependent stdout buffering; verify exit codes explicitly.
- **Acceptance:** all four commands below succeed and match expectations:
  1. `python3 -m synccli --json SRC DST` → one JSON object, four keys, exit 0.
  2. `python3 -m synccli --json --dry-run SRC DST` → `copied` = would-be set, nothing written, exit 0.
  3. `python3 -m synccli SRC DST` → one path per line (unchanged).
  4. `python3 -m unittest -v` → green.

**Ordering rationale:** semantics first (1–2) so implementation cannot guess; impl before tests before review; acceptance last. Tasks 3+4 share one `cheap-code` instance (same feature/context); Task 5 uses a fresh reviewer per the context-budget rule.

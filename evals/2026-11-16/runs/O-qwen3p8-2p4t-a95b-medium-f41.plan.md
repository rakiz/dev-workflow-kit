# Execution plan: `--json` + dry-run UX for synccli

Context gathered (read-only): `synccli.py` (sync/main), `incremental.py` (imports `copy_file` — signature-stability constraint is real), `test_synccli.py`. Key design ambiguity to settle first: semantics of `"skipped": N` (unchanged files = scanned − copied, most plausible reading).

---

**Task 1 — Pin down the JSON contract (design)**
- Objective: fix exact semantics before code: `skipped` = `len(build_manifest(src)) − len(copied)`; `copied` = relative paths (same list `sync()` returns, identical in dry-run and real mode); `src`/`dst` = the argv values verbatim; stdout purity rule (all non-JSON output, incl. errors, to stderr); exit code unchanged (0).
- Files: none (decision recorded in the task brief for Task 2).
- Agent: orchestrator decides; **cheap-design** only if contested — this is small enough that a written contract in the impl brief suffices.
- Risks: wrong `skipped` semantics → tests encode a guess; ambiguity on whether dry-run `copied` is "would copy" (yes, per GOAL §2).
- Acceptance: one-paragraph contract exists covering all four keys, purity, exit code; both flags' interplay stated.

**Task 2 — Implement `--json` flag (impl)**
- Objective: add `--json` to argparse in `main()`; when set, print exactly one `json.dumps` object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` to stdout and nothing else; human mode untouched (one path/line); `sync()` signature unchanged (keyword-only addition forbidden unless defaulted — safest: compute `skipped` in `main()` from `build_manifest`, no `sync()` change at all).
- Files: modify `synccli.py` (`main()` only, ideally).
- Agent: **cheap-code** (fresh session, brief = Task 1 contract).
- Risks: breaking `incremental.py`'s `from synccli import copy_file`; extra stdout noise (argparse errors go to stderr already — verify); Python 3.10 stdlib only (json/argparse already imported — no new deps).
- Acceptance: `python3 -m synccli src dst --json` prints a single valid JSON object with the 4 keys; `python3 -m synccli src dst` output byte-identical to before; `sync(src, dst, dry_run=...)` callable with old signature.

**Task 3 — Unit tests for JSON shape (impl)**
- Objective: in `test_synccli.py`, add tests using `tempfile` + `contextlib.redirect_stdout`: (a) `--json` output parses as JSON and has exactly the 4 keys; (b) `--json --dry-run` → `copied` lists what would be copied and dst is unmodified (no files, no manifest written); (c) real run → `copied` matches files actually created, `skipped == scanned − copied`; (d) second run → `copied == []`, `skipped == N`; (e) human mode regression (newline-separated paths); (f) stdout purity (captured stdout == the JSON line only).
- Files: modify `test_synccli.py`.
- Agent: **cheap-code** (same session as Task 2 via `task_id` — small delta, context is useful).
- Risks: mtime-granularity flakiness on fast filesystems (identical content re-written may look unchanged — use distinct content per test file); redirect_stdout must not swallow stderr assertions.
- Acceptance: `python3 -m unittest -v` fully green, new tests included, run twice in a row without flake.

**Task 4 — Review (review, mandatory)**
- Objective: read-only critique of the Task 2+3 diff against the GOAL constraints: stdout purity, exit code, `sync()` signature, no new deps, 3.10 stdlib, human mode unchanged, dry-run interplay correct.
- Files: none (reads `synccli.py`, `test_synccli.py`, diff).
- Agent: **cheap-review** (fresh instance, self-contained prompt with the diff + contract).
- Risks: reviewer misses runtime stdout leaks (e.g. `copy_file`'s silent OSError path is fine, but any future print); classify findings minor vs major.
- Acceptance: written verdict; minor findings → resume Task 2/3 instance via `task_id` to fix, then re-run `python3 -m unittest`; major finding → escalate to **strong-code**.

**Task 5 — Final verification (orchestrator)**
- Objective: run `python3 -m unittest -v` and a manual smoke (`--json`, `--json --dry-run`, human mode) in a temp dir; confirm `incremental.py` still imports cleanly (`python3 -c "import incremental"`).
- Files: none.
- Agent: orchestrator (bash only).
- Risks: none destructive; catches integration regressions reviews can't run.
- Acceptance: all tests pass, smoke output matches the contract, import check clean → done. No commit unless explicitly requested.

Notes: no **explore** task needed (repo is 3 files, already surveyed above); no **design-review** warranted (mechanical feature, no architectural stakes). `collect_stale`/`filter_excluded` bugs spotted in passing are out of scope — not touching them without your go-ahead.

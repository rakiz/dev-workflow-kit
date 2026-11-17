# Execution plan — `--json` + `--dry-run` UX for synccli

Context grounding (read-only): `synccli.py:72` `sync()` returns only the copied list — no data for `"skipped"`; `incremental.py:5` imports `copy_file` (not `sync`); `test_synccli.py:22-24` statically contradicts `collect_stale`'s `range(1, …)` at `synccli.py:55` — the baseline suite is likely already red on one test.

---

**Task 1 — Baseline verification (explore)**
- Objective: establish ground truth before any edit: run `python3 -m unittest -v` and record which tests pass/fail; confirm every caller of `sync()`/`copy_file` (grep + repo scan); list all `print`/stdout-writing sites; confirm Python version ≥3.10.
- Files: none (read-only).
- Agent: `explore`.
- Risks: running tests writes `__pycache__` (already present, untracked); a pre-existing failure could later be misattributed to new work.
- Acceptance: written baseline report listing exact failing test names, all `sync()`/`copy_file` call sites, and all stdout writers — referenced by later tasks' acceptance criteria.

**Task 2 — Design note: `skipped` semantics + signature stability (design)**
- Objective: decide, before code: (a) what `"skipped"` counts — files present in src but unchanged (`len(src_manifest) - len(copied)`) vs. copy failures (`copy_file` silently swallows `OSError` at `synccli.py:68`, so failures are currently invisible); (b) how to obtain it without touching `sync()`'s signature — options: keyword-only optional out-param (still a signature change), a wrapper `sync_report()`, or a second `build_manifest()` scan in `main()` (double-scan cost); (c) stdout purity guarantee (any diagnostics → stderr); (d) `src`/`dst` echoed verbatim as passed; (e) exit code stays 0.
- Files: create `DESIGN-json.md`.
- Agent: `cheap-design`.
- Risks: picking a `skipped` definition the tests then bake in wrong; double-scan acceptable at this scale but should be a decision, not an accident.
- Acceptance: doc names one chosen mechanism, one `skipped` definition, and the stdout/stderr policy; no open questions remain.

**Task 3 — Design review (design-review)**
- Objective: critique Task 2's doc against GOAL.md constraints (stdlib only, `sync()` signature stable, human mode byte-identical, exit code unchanged).
- Files: none (read-only, comments on `DESIGN-json.md`).
- Agent: `cheap-design-review`.
- Risks: over-engineering a ~100-line CLI; reviewer inventing scope (e.g. fixing `collect_stale`, which is out of GOAL scope).
- Acceptance: written verdict; any blocking objection resolved in the doc before Task 4 starts.

**Task 4 — Implementation + tests (impl)**
- Objective: add `--json` flag to `main()` per the approved design; in JSON mode print exactly one `json.dumps` object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` and nothing else to stdout; `--dry-run --json` lists would-copy; human mode untouched; add unit tests to `test_synccli.py` (capture stdout via `contextlib.redirect_stdout`, assert `json.loads` parses, all four keys present with correct types, dry-run semantics: dst unchanged, no manifest written, `copied` matches would-copy set; exit code 0).
- Files: modify `synccli.py`, `test_synccli.py`.
- Agent: `cheap-code`.
- Risks: accidental stdout contamination (any stray `print` breaks the contract); drifting `sync()` signature; `skipped` computed inconsistently with design; pre-existing red test confusing the pass/fail judgment; `__pycache__` showing up in scans.
- Acceptance: `python3 -m unittest -v` → all NEW tests pass and no failures beyond those documented in Task 1's baseline; `python3 -m synccli SRC DST --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert set(d)=={'copied','skipped','src','dst'}"` succeeds; `--dry-run --json` leaves DST byte-identical; diff shows `def sync(src_root, dst_root, dry_run=False)` unchanged; only stdlib imports added.

**Task 5 — Code review (review)**
- Objective: review Task 4's diff against GOAL.md and `DESIGN-json.md`; classify findings minor/major.
- Files: none (read-only).
- Agent: `cheap-review` (fresh instance, self-contained brief with the diff + design doc).
- Risks: reviewer scope creep into pre-existing bugs (`collect_stale` off-by-one, `filter_excluded` mutable default) — flag them as observations, not blockers.
- Acceptance: written verdict; minor findings fixed by resuming the Task 4 instance via `task_id`, re-running its acceptance command; a major finding escalates to `strong-code` with evidence.

**Task 6 — Final audit (review)**
- Objective: independent end-to-end verification: full test suite, all three CLI modes (`--json`, `--dry-run --json`, plain), stdout-purity check, signature/stdlib constraint check against Task 1's baseline.
- Files: none (read-only; test runs only).
- Agent: fresh `cheap-review` (proportionate for a ~50-line diff; escalate to `strong-review` only if it expresses doubt or finds contract violations).
- Risks: audit re-flagging the known pre-existing failure as new.
- Acceptance: report showing all Task 4 acceptance commands passing verbatim, delta-vs-baseline failures = 0.

---

Out of scope / needs your explicit yes before anyone touches it: fixing the pre-existing `collect_stale` bug + failing test (`synccli.py:55`, `test_synccli.py:22`), the `filter_excluded` mutable-default bug (`incremental.py:10`), README docs for the new flag, and any commit — none are in GOAL.md, so the plan stops at a verified working tree.

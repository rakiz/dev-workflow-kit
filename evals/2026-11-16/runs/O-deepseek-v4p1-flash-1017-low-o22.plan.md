Read `GOAL.md`, `README.md`, and the actual source (`synccli.py`, `test_synccli.py`, `incremental.py`, `DESIGN.md`) to ground the plan. No files modified.

# Execution plan — JSON output mode + dry-run UX

## Baseline facts the plan depends on
- CLI entry is `synccli.main()`; currently only human mode (`print(rel)` per line), `--dry-run` already returns the would-copy list from `sync()`.
- `sync()` returns only the copied list; there is **no** count of skipped/unchanged files, and its signature is contractually frozen.
- `copy_file()` swallows `OSError` silently, but `sync()` still returns that rel as "copied" — so `copied` already means "attempted", not "succeeded".
- The test suite is **already red at baseline**: `test_first_item_stale_is_included` expects `["x.txt","y.txt"]` but `collect_stale` starts at `range(1, ...)`. Must be recorded as a known pre-existing failure, not "fixed" under this goal.
- `incremental.py` has unrelated defects (mutable default `excluded=[]`; `.sync_manifest.json` misfiled as a top dir). Out of scope; do not touch.

## Ambiguities to settle BEFORE implementation (blocking)
1. `skipped` semantics: unchanged-file count? Or `total_in_src − len(copied)`? And in `--dry-run` mode, is `skipped` still the unchanged count?
2. Do `src`/`dst` in JSON echo the raw argv strings or resolved/absolute paths?
3. Where does skipped come from without changing `sync()` — a second `build_manifest(src)` walk in `main()`, or a new side helper?

These are design decisions, not implementation details, and get resolved in Task 2 before any code is written.

---

### Task 1 — Explore & baseline verification (read-only)
- **Objective:** Confirm current stdout contract, capture the exact red baseline (`python3 -m unittest -v`), and pin the insertion points for `--json` and the JSON emitter. Confirm `--help`/argparse behaviour does not pollute JSON-mode stdout.
- **Files:** none (read-only; may run tests).
- **Agent:** `explore`.
- **Risks:** Environment lacks a clean interpreter; `__pycache__` noise; pre-existing failures mistaken for regressions.
- **Acceptance:** Written report with (a) exact baseline test result incl. failing test names, (b) `sync()`/`main()` call map, (c) confirmation that `main()` is the only stdout writer.

### Task 2 — Design decision + design review (blocking gate)
- **Objective:** Produce a short design note resolving the three ambiguities above, the exact JSON key/value contract (`{"copied": [...], "skipped": N, "src": ..., "dst": ...}`), how `skipped` is derived without touching `sync()`, and the guarantee that nothing else reaches stdout in JSON mode (single `print(json.dumps(...))`, errors already swallowed). Explicitly state that the pre-existing `collect_stale` failure and `incremental.py` defects are out of scope.
- **Files to create:** `DESIGN_NOTE_JSON.md` (or an appended section — orchestrator's choice; not `DESIGN.md`, which is the unrelated v2 daemon doc).
- **Agent:** `cheap-design`, then `cheap-design-review` (design-review rung).
- **Risks:** Over-engineering a 3-flag change; letting the reviewer widen scope into the daemon design doc; picking a `skipped` derivation that re-walks the tree inefficiently.
- **Acceptance:** Design review verdict of **no major findings**; note states the contract unambiguously and lists the out-of-scope items.

### Task 3 — Implement `--json` + tests
- **Objective:** Add `--json` to the parser; in `main()`, when set, emit exactly one JSON object with the four keys (list order per design note), preserving `--dry-run` semantics (`copied` = would-copy) and leaving human mode byte-for-byte unchanged. Add unit tests to `test_synccli.py`: valid JSON parse of captured stdout, all four keys present with correct types, dry-run lists would-copy and writes no files/manifest, non-dry-run lists copied, and (ideally) human mode still one-path-per-line.
- **Files to modify:** `synccli.py`, `test_synccli.py` (no `sync()` signature change; no new deps).
- **Agent:** `cheap-code`.
- **Risks:** Accidentally printing extra stdout lines (logging, stray `print`) breaking "nothing else on stdout"; changing `sync()` arity; computing `skipped` by a second full walk on large trees; asserting on absolute vs relative paths inconsistently; new tests colliding with the pre-existing red test.
- **Acceptance:** `python3 -m unittest -v` shows the new JSON tests passing and **no new failures** beyond the recorded baseline red test; `python3 -m synccli src dst --json --dry-run` pipes cleanly into `python3 -c 'import json,sys; json.load(sys.stdin)'`.

### Task 4 — Review (read-only)
- **Objective:** Diff review against the goal: JSON-shape correctness, single-object stdout guarantee, dry-run parity, unchanged human mode, frozen `sync()` signature, stdlib-only.
- **Files:** none.
- **Agent:** `cheap-review`.
- **Risks:** Reviewer flagging the pre-existing failures / `incremental.py` as regressions (must be triaged as out-of-scope, not fixed here).
- **Acceptance:** Verdict with findings classified; **minor** findings routed back to the same `cheap-code` instance via `task_id`.

### Task 5 — Final acceptance verification
- **Objective:** Independent re-run of the full test suite plus the two CLI smoke commands (json+dry-run, json only, human mode) and confirmation that stdout in JSON mode parses as a single object with no trailing text.
- **Files:** none.
- **Agent:** `explore` (or `cheap-review` resumed with a self-contained brief).
- **Risks:** False pass from captured vs piped stdout differences.
- **Acceptance:** All acceptance commands green; baseline-red test explicitly accounted for; explicit confirmation of "no new modifications beyond `synccli.py` + `test_synccli.py` + the design note (if created)".

**Sequencing:** 1 → 2 (blocking) → 3 → 4 (loop to 3 on minor findings) → 5. Tasks 1 and 2 must not be parallelised since the design note consumes the baseline/insertion-point report.

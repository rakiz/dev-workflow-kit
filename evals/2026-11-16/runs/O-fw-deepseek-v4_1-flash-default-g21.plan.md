# Execution plan — `--json` + `--dry-run` UX

## Findings that shape the plan
- `sync()` currently returns only the copied list (`synccli.py:72`). GOAL's JSON needs `skipped` (count of unchanged files) and `src`/`dst`, while the signature must stay stable. So `main()` must derive these without touching `sync()`'s contract — a small additive helper (e.g. `count_skipped`/`build_result`) is the clean route.
- `copy_file` swallows `OSError` (`synccli.py:68`), and `sync()` writes the manifest only on non-dry-run. JSON mode must not leak the human `print` loop (`synccli.py:97`).
- `incremental.py` imports `copy_file`; nothing else consumes `sync()` internally today, but GOAL asserts internal callers exist — treat the signature as frozen.
- There is no CI/lint config; verification is `python3 -m unittest -v`.

---

## Task 1 — Design the JSON result contract
- **Objective:** Pin down the exact JSON object, how `skipped` is computed without changing `sync()`, stdout purity, and dry-run semantics. Decide whether the result-building helper lives in `synccli.py` or a new module.
- **Files:** read `synccli.py`, `incremental.py`; write `DESIGN_JSON.md` (new, only if the project wants a doc) — otherwise produce the design inline in the task report.
- **Agent:** `cheap-design` → `cheap-design-review` (real contract/state question, cheap to correct now).
- **Risks:** `skipped` ambiguity (total−copied vs unchanged-only); deciding to mutate `sync()` and breaking the frozen signature.
- **Acceptance:** a written contract listing the exact keys/types, the `skipped` definition, the `sync()`-stability argument, and the dry-run rule; design-review finds no blocking gap.

## Task 2 — Implement `--json`
- **Objective:** Add `--json` flag; build `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` and print exactly one JSON object to stdout, nothing else; exit code unchanged (0).
- **Files:** modify `synccli.py` (`main` + a new pure helper; leave `sync()` untouched).
- **Agent:** `cheap-code` → `cheap-review` (mandatory).
- **Risks:** stray stdout (argparse help is stderr — OK; ensure no prints besides the JSON); `skipped` computed wrong under dry-run; non-ASCII/relpath serialization.
- **Acceptance:** `python3 -m synccli --json src dst` emits one `json.loads`-able object with all four keys; stdout contains nothing else; exit 0.

## Task 3 — `--json --dry-run` interplay
- **Objective:** With both flags, `copied` lists files that *would* be copied and nothing is written to disk.
- **Files:** modify `synccli.py` (reuse the helper; no `sync()` change).
- **Agent:** `cheap-code` → `cheap-review`.
- **Risks:** manifest accidentally written in dry-run; `copied` including already-present files.
- **Acceptance:** with both flags, `copied` matches what a real run would copy and `dst` is unmodified (no files, no manifest) after the call.

## Task 4 — Tests for JSON shape and dry-run semantics
- **Objective:** Add unit tests: valid JSON, all keys present, correct types, dry-run `copied` semantics, stdout purity, human mode unchanged.
- **Files:** modify `test_synccli.py`.
- **Agent:** `cheap-code` → `cheap-review`.
- **Risks:** testing via `main()` without capturing stdout; tests that couple to mtime flakiness.
- **Acceptance:** `python3 -m unittest -v` all green, new tests cover the four GOAL points.

## Task 5 — Independent verification
- **Objective:** Read-only audit: confirm `sync()` signature/behavior unchanged, stdout purity in JSON mode, dry-run writes nothing, human mode still one-path-per-line.
- **Files:** read all of `synccli.py`, `test_synccli.py`, `incremental.py`.
- **Agent:** `explore` (evidence gathering) then `cheap-review`/`strong-review` if risk warrants; final audit `strong-review` if a strong rung implemented.
- **Risks:** untested edge (empty src, missing dst, pre-existing manifest) slipping through.
- **Acceptance:** report confirms each GOAL constraint with a concrete command/observation, or flags a gap with file:line.

---

## Sequencing / gates
1 → 2 → 3 → 4 → 5, strictly ordered (2 depends on 1; 3 on 2; tests on the final code). Every implementation task passes through `cheap-review` before the next starts; escalate to `strong-code` only on a demonstrated major finding.

**Out of scope (do not touch):** `DESIGN.md`'s daemon (`syncd`) — it is a separate v2 proposal, not part of this goal.

Found your goal and project overview — now mapping the repo layout to build the execution plan.

# Execution Plan — JSON output mode + dry-run UX

## Task 1: Exploration — Map current CLI I/O contract and `sync()` internal callers

- **Objective:** Establish baseline: how `main()` prints, what `sync()` returns, human-mode invariant (one path per line), and constraint that `sync()` signature must stay stable.
- **Files to create/modify:** None (read-only).
- **Pipeline agent:** `explore`
- **Risks:** Low. Risk of misidentifying internal callers if grep scope is incomplete.
- **Acceptance criterion:** Written summary listing: `sync()` signature at `synccli.py:72`, `main()` print loop at `synccli.py:97-98`, and confirmation no other internal callers alter signature requirement.

## Task 2: Design — `--json` flag contract and stdout discipline

- **Objective:** Specify CLI flag, JSON shape `{"copied":[...],"skipped":N,"src":...,"dst":...}`, single-object-on-stdout rule, exit-code unchanged, interaction with `--dry-run`, and that human mode is untouched.
- **Files to create/modify:** Design doc/note (e.g., update `DESIGN.md` or ephemeral plan doc); no runtime code yet.
- **Pipeline agent:** `cheap-design` → `design-review`
- **Risks:** Ambiguity on `skipped` definition (total scanned minus copied? vs manifest-unchanged count) must be resolved before impl; otherwise tests and impl diverge.
- **Acceptance criterion:** Approved design stating: `skipped` computation formula, dry-run lists would-be `copied` without side effects, and human mode `for rel in copied: print(rel)` preserved as fallback.

## Task 3: Implementation — Add `--json` flag and JSON output path to `synccli.py`

- **Objective:** Add `parser.add_argument("--json", ...)` / `--json` flag, route to JSON serialization (`json.dumps` to stdout), compute `skipped`, emit `src`/`dst`, preserve exit code; keep `sync()` signature stable; use stdlib only.
- **Files to create/modify:** `synccli.py` (modify: `main()` at `synccli.py:90-99`; optionally expose helper to build JSON payload without changing `sync()`).
- **Pipeline agent:** `cheap-code` → `cheap-review` (escalate to `strong-code` on major finding)
- **Risks:** Accidentally altering `sync()` signature; printing extra content to stdout in JSON mode (e.g., argparse help, debug logs); computing `skipped` incorrectly.
- **Acceptance criterion:** `python3 -m synccli --help` shows `--json`; `python3 -m synccli $SRC $DST --json` prints exactly one line that is `json.loads`-valid with keys `copied, skipped, src, dst`; `echo $?` unchanged vs human mode; `sync(src,dst)` call still works with positional args.

## Task 4: Implementation — Ensure `--dry-run` + `--json` interplay is correct

- **Objective:** With both flags, `copied` reflects what WOULD be copied (i.e., `sync(..., dry_run=True)` result), no files actually copied, no manifest update; without `--dry-run`, normal copy + JSON report.
- **Files to create/modify:** `synccli.py` (same region as Task 3; verify `sync()` dry_run path at `synccli.py:81-82` is used).
- **Pipeline agent:** `cheap-code` (continuation of Task 3, same diff) → `cheap-review`
- **Risks:** dry-run bypass could be skipped when JSON branch does extra work; manifest write at `synccli.py:85-86` must not execute on dry-run.
- **Acceptance criterion:** After `synccli $SRC $DST --json --dry-run`, destination has no new files and no updated `.sync_manifest.json`, but stdout JSON `copied` is non-empty when source differs; repeat without `--dry-run` then copies.

## Task 5: Tests — Unit tests for JSON shape and dry-run semantics in `test_synccli.py`

- **Objective:** Add tests covering: valid JSON, required keys present, `copied` is list, dry-run semantics (would-be list), human mode unchanged (optional regression).
- **Files to create/modify:** `test_synccli.py` (modify; add test class/methods invoking `synccli.main()` with captured stdout or subprocess).
- **Pipeline agent:** `cheap-code` (or `cheap-mech` if purely additive test methods) → `cheap-review`
- **Risks:** Tests that assert on stdout must isolate from manifest state; temp dirs must be fresh per test like existing `TestSync.setUp` at `test_synccli.py:36-40`.
- **Acceptance criterion:** `python3 -m unittest -v` passes; new tests fail if `--json` output is not single JSON object or lacks any of `copied/skipped/src/dst`; dry-run test fails if destination is mutated.

## Task 6: Verification — Stdlib-only, signature stability, and regression gate

- **Objective:** Final audit: no new dependencies, Python 3.10 stdlib only, `sync()` signature stable, human mode `print(rel)` path still exercised.
- **Files to create/modify:** None (verification only); fix via prior tasks if violations found.
- **Pipeline agent:** `strong-review` (or `strong-review-alternative` if prior impl was strong-tier)
- **Risks:** Hidden import added during impl; `collections` etc. still stdlib but need check.
- **Acceptance criterion:** `grep -r "import" synccli.py` shows only stdlib; `inspect.signature(synccli.sync)` matches `(src_root, dst_root, dry_run=False)`; full test suite green.

## Sequencing

1 → 2 → (3, 4 together) → 5 → 6. Tasks 3 and 4 are a single code change; split here for review clarity but should be implemented in one diff to avoid intermediate broken state.

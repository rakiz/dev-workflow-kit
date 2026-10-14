# Execution plan — `--json` output mode + dry-run UX

Repo surveyed: `synccli.py` (CLI + `sync()` at synccli.py:72), `incremental.py` (uses `copy_file`), `test_synccli.py`, `DESIGN.md`, GOAL/README read. No modifications made.

## Task 0 — Confirm current test baseline and design intent
- **Objective:** Establish what `sync()` returns today and how tests invoke the CLI, so the JSON contract doesn't break existing callers.
- **Agent:** `explore`
- **Files:** read-only (`test_synccli.py`, `DESIGN.md`)
- **Risks:** hidden internal callers relying on `sync()` return type.
- **Acceptance:** Written summary of `sync()` return shape, `main()` output paths, and whether `skipped` has any existing definition.

## Task 1 — Design the output contract
- **Objective:** Decide semantics: `copied` = list of relative paths copied (or would be, in dry-run); `skipped` = count of manifest files not copied; define stdout purity rule (errors → stderr). Decide whether `sync()` stays returning a list (stable signature per GOAL) and `main()` derives `skipped`, vs a new return type.
- **Agent:** `design-review`
- **Files:** none (produce a short design note; may append to `DESIGN.md` in Task 2).
- **Risks:** changing `sync()`'s return type breaks `incremental.py`-style internal callers (GOAL forbids); ambiguity of "skipped" (unreadable sources silently swallowed by `copy_file`'s `except OSError`).
- **Acceptance:** Documented decision: `sync()` signature unchanged; `skipped = len(src_manifest) - len(copied)`; JSON emitted only in `--json` mode via `json.dumps` to stdout.

## Task 2 — Implementation: `--json` flag
- **Objective:** Add `--json` to argparse; in JSON mode print exactly one object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` to stdout; human mode unchanged (one path per line); exit code 0 in both.
- **Agent:** `cheap-code` (impl)
- **Files:** modify `synccli.py` (only `main()` and argparse block); optionally append decision to `DESIGN.md`.
- **Risks:** printing human lines to stdout in JSON mode (violates "nothing else on stdout"); `json.dumps` default separators/spaces — fix exact key order and single-line shape; ensure warnings/errors go to stderr.
- **Acceptance (verifiable):**
  ```
  python3 -m synccli src dst --json        # stdout parses as one JSON object with the 4 keys
  python3 -m synccli src dst               # unchanged human output
  echo $? == 0
  ```

## Task 3 — Implementation: `--dry-run` + `--json` interplay
- **Objective:** With `--json --dry-run`, `copied` lists files that *would* be copied; dst manifest is not written; no files created. Mostly free (dry-run already returns `to_copy`), but verify `skipped` counts all non-copied source files either way.
- **Agent:** `cheap-code` (same instance, small follow-up)
- **Files:** modify `synccli.py` only if `skipped` derivation differs in dry-run.
- **Risks:** double-counting skipped (manifest file itself excluded from scan — hidden-dot filter already handles it).
- **Acceptance:** `python3 -m synccli src dst --json --dry-run` returns identical `copied` list to a real run on the same tree, and `dst` contains no manifest afterward.

## Task 4 — Unit tests
- **Objective:** Add tests to `test_synccli.py`: (a) JSON output is valid single-object JSON with exactly the 4 keys and correct types; (b) `copied` matches expected relpaths; (c) dry-run+JSON `copied` semantics and that nothing is written to dst; (d) human mode output unchanged (existing tests must pass untouched).
- **Agent:** `cheap-code` (impl)
- **Files:** modify `test_synccli.py`.
- **Risks:** tests capturing stdout must not interleave unittest's own output into the assertion; use `contextlib.redirect_stdout`.
- **Acceptance:** `python3 -m unittest -v` passes, with ≥3 new tests covering the GOAL §4 cases.

## Task 5 — Review + final audit
- **Objective:** Review the diff: stdout purity in JSON mode, `sync()` signature stability, no new imports/dependencies, Python 3.10 stdlib only, README updated if flags are documented.
- **Agent:** `cheap-review` (mandatory), then `strong-review` for final audit if the diff is nontrivial.
- **Files:** read-only; fixes routed back to Task 2/4 instance.
- **Risks:** reviewer may miss subprocess-level stdout check — insist at least one test runs the CLI as a subprocess (`python3 -m synccli`) and asserts stdout parses as JSON.
- **Acceptance:** All review findings resolved; full test suite green; `grep -E "^import|^from" synccli.py` shows stdlib-only imports.

Execution order: 0 → 1 → 2 → 3 → 4 → 5 (2 and 3 may share an impl instance).
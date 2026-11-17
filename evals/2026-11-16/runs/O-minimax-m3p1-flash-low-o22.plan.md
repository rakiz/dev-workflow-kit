Read. Here is the execution plan — text only, nothing modified.

## Context that shapes the plan

- `synccli.sync(src, dst, dry_run=False)` returns only the list of copied relpaths (synccli.py:72). It does **not** report how many files were *not* copied. The JSON contract needs `skipped: N`, so the count must be derived without changing `sync()`'s signature (hard constraint, GOAL.md:14).
- `copy_file` swallows `OSError` silently (synccli.py:67-69) and reports success to the caller — so a "copied" list entry can mean "copy silently failed". JSON mode must not claim more than happened; decide explicitly whether failures count as skipped.
- `scan_files` skips dot-directories (synccli.py:14) but `incremental.py` has an unrelated, buggy exclusion helper (mutable default arg, `filter_excluded` never used by `synccli.py`) — out of scope, but a trap if an agent "reuses" it.
- `DESIGN.md` describes a *different* feature (a `syncd` daemon). It is **not** part of this goal. Agents must not implement it, and the "log errors to stdout" line there (DESIGN.md:18) directly contradicts the JSON-mode stdout-purity requirement.
- `collect_stale` (synccli.py:45-59) never inspects `items[0]` — an existing off-by-one bug, unrelated to this goal. Flag, don't fix.

## Open decision the plan pins down (must be resolved before coding)

**Definition of `skipped`:** `skipped = (files visible in src) − (files in the copied list)`, i.e. files already up to date in `dst` per the manifest. In `--dry-run`, `copied` = would-be-copied files and `skipped` = files that would be skipped. Rationale: `sync()` returns exactly the changed set, so `skipped` is the complement within the scanned source set — computable from `scan_files(src)` minus the returned list. This keeps `sync()` untouched and makes both modes use one formula.

## Task list

### Task 1 — Explore & contract the current behavior (agent: **explore**)
- **Objective:** Pin down the exact current stdout/stderr behavior of `python3 -m synccli src dst [--dry-run]`, the exit codes, and where `sync()` is called from (internal callers named in GOAL.md:14), so the JSON-mode purity claim is grounded.
- **Files to read:** `synccli.py`, `incremental.py`, `test_synccli.py`, `README.md`, `DESIGN.md`. **Modify:** none.
- **Risks:** Assuming `__main__` guard means "module entry" — `python3 -m synccli` works because the module is `__main__`; the guard also covers `python3 synccli.py`.
- **Acceptance criterion:** A written report listing: (a) every `print`/stdout write path in the current code, (b) all call sites of `sync()` (file:line), (c) the current exit-code behavior, (d) confirmation that `incremental.py` is not imported by `synccli.py`.

### Task 2 — Design the JSON reporting surface (agent: **cheap-design**, then **cheap-design-review**)
- **Objective:** Produce a short design note defining: the exact JSON object shape and key order, the `skipped` definition above, how the count is obtained without changing `sync()`'s signature, where the JSON is emitted (stdout only, exactly one object, one trailing newline), how human mode is preserved byte-for-byte, and the failure-reporting policy (silent `copy_file` failures → counted as skipped, not copied).
- **Files to create/modify:** design note (proposed `docs/json-mode-design.md` — content-only, no code). If the repo prefers no new docs, the note goes into the PR description instead; decide at implementation time.
- **Risks:** A design that adds a `return` type change to `sync()` (violates the constraint); a design that emits JSON from inside `sync()` (breaks "keep sync() signature stable" and the human-mode contract); ambiguity on whether `src`/`dst` in the JSON are the raw argv strings or absolute paths.
- **Acceptance criterion:** A reviewer can implement Task 3 from the note alone without asking a question; the note explicitly states the `skipped` formula and states that `sync()`'s signature and return type are unchanged.

### Task 3 — Implement `--json` and `--dry-run` interplay (agent: **cheap-code**)
- **Objective:** Add the `--json` flag; in JSON mode print exactly one JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` to stdout and nothing else; in dry-run, `copied` lists files that *would* be copied; human mode unchanged (one path per line).
- **Files to modify:** `synccli.py` only — `main()` gains `--json`; add a small reporting helper (e.g. `render_json_result(src, dst, copied, skipped)`); compute `skipped` via the Task-1/Task-2 formula. **Do not modify:** `incremental.py`; `sync()`'s signature, docstring contract, and return value.
- **Risks:** (a) stdout contamination from warnings/exceptions — catch broadly around reporting and route any diagnostics to `stderr`; (b) argparse errors already go to `stderr` (fine, keep exit code unchanged per GOAL.md:7); (c) the JSON must be a *single* object, not one-per-line or NDJSON; (d) `json.dump` to stdout must not interleave with human-mode `print`s — the two modes must be strictly exclusive branches; (e) non-ASCII / path separator rendering — JSON escaping is fine, but `copied` paths must match the relpaths `sync()` returns (platform separator as-is, consistent with `scan_files`).
- **Acceptance criterion:** `python3 -m synccli SRC DST --json` prints a single line that `json.loads` parses to a dict with exactly the four keys `copied`, `skipped`, `src`, `dst`; `copied` is a list of strings; `skipped` is an `int`; stdout contains nothing else; exit code identical to the non-JSON invocation.

### Task 4 — Unit tests for JSON shape and dry-run semantics (agent: **cheap-code**)
- **Objective:** Add tests to `test_synccli.py` covering: JSON validity and the four required keys; `copied` content in a normal run; `copied` content in `--dry-run` (files that would be copied) plus the fact that dry-run performs **no** filesystem mutation (destination empty / no manifest written); `skipped` count in both modes; human mode still prints one path per line and is not JSON; exit code unchanged.
- **Files to modify:** `test_synccli.py` (add a new `TestJsonMode` class; reuse the existing `tempfile.mkdtemp()` idiom and `synccli.main([...])` call style). **Do not modify:** existing test cases (they must keep passing unchanged).
- **Risks:** Capturing stdout requires `contextlib.redirect_stdout` (stdlib-only, fine) — but the module imports `sys` and prints directly, so redirect at the `sys.stdout` level; forgetting that `main()` returns rather than `sys.exit`s (exit code is `0` returned from `main`, `sys.exit(main())` only in the `__main__` block — so tests must assert on `main()`'s return value, not on a process exit code, unless the test spawns a subprocess); a dry-run test that accidentally writes the manifest, which would mask a regression.
- **Acceptance criterion:** `python3 -m unittest -v` passes with the pre-existing 5 tests still green, plus the new JSON/dry-run tests; at least one new test asserts `json.loads(stdout)` succeeds and one asserts the destination directory is untouched after `--dry-run --json`.

### Task 5 — Independent review (agent: **cheap-review**)
- **Objective:** Review the Task-3/Task-4 diff against the four GOAL.md requirements and the constraints (no new deps, stdlib-only, `sync()` signature stable).
- **Files to modify:** none (read-only review); fixes go back to the Task-3/Task-4 author.
- **Risks:** A reviewer must specifically check that `sync()` was not refactored and that no `print()` outside the JSON branch can reach stdout in JSON mode; and that no `DESIGN.md` daemon work leaked into the diff.
- **Acceptance criterion:** Reviewer returns a verdict of "no major findings", with minor findings (if any) listed as concrete file:line items. Any major finding routes back to the implementer, then re-review.

### Task 6 — Final verification & documentation touch-up (agent: **cheap-code**, then **cheap-review**)
- **Objective:** Update `README.md` with the `--json` usage line and the JSON example output; confirm no dependency files, `requirements.txt`, or stdlib imports were added.
- **Files to modify:** `README.md`. **Modify:** none of the Python files.
- **Risks:** README example drifting from the actual output shape — the example must be pasted from an actual run, not hand-written.
- **Acceptance criterion:** `python3 -m unittest -v` green; `python3 -m synccli --help` lists `--json`; README's JSON example round-trips through `json.loads`; `git diff --stat` shows only `synccli.py`, `test_synccli.py`, `README.md` (plus an optional design note) — no new dependency artifacts.

## Critical path

`1 → 2 → 3 → 4 → 5 → 6`. Task 5 is mandatory and blocks completion. Tasks 3 and 4 are one implementation phase (same author, same session) since the test file depends on the final shape; Task 6 is a separate, small phase.

## Explicitly out of scope

The `syncd` daemon (`DESIGN.md`), the `incremental.py` bugs (mutable default argument in `filter_excluded`, unused helper, the `items[0]` skip in `collect_stale`), and any fix to `copy_file`'s silent-failure behavior. These are flagged, not fixed — say the word if you want them pulled into scope.

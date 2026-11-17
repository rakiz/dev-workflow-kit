## Context read

- `synccli.py` (103 lines): `sync(src_root, dst_root, dry_run=False)` returns list of copied relpaths; `main()` prints one path per line. `skipped` is currently unobservable — no function returns it.
- `incremental.py` imports `copy_file` from `synccli` (the "internal callers" the constraint refers to) — it does **not** call `sync()`, so the constraint is about not changing `sync()`'s signature/return type.
- `DESIGN.md` describes a *different* goal (a `syncd` daemon). It is **out of scope** for this plan — flagging it so it isn't accidentally implemented.
- Note a latent bug in `collect_stale` (`range(1, ...)` drops the first item) — unrelated to GOAL, do not touch.

## Execution plan

### Task 1 — Design review: define the JSON contract (agent: `cheap-design-review` / `strong-design-review`)
- **Objective:** Pin down the exact JSON contract before code exists, resolving the ambiguities below.
- **Files:** none modified (design note returned as text, optionally `DESIGN.md` is *not* to be touched — it belongs to the daemon goal).
- **Decisions to lock:**
  1. `skipped` semantics: count of source files **not** copied = `len(src_manifest) - len(copied)`. Alternative (files that failed to copy) must be rejected — `copy_file` swallows `OSError`, so failures are currently invisible.
  2. `copied` entries: relative paths (relative to `src`), matching current human output.
  3. `src`/`dst`: the raw argv strings as given (not `abspath`), so output is reproducible.
  4. JSON must be the **only** stdout output; any human-mode `print` must be suppressed. stderr may still be used for warnings.
  5. Exit code: unchanged (0), including in `--json` mode.
- **Risks:** Ambiguity #1 is the main one — a wrong `skipped` definition silently ships wrong numbers. Also risk of leaking the human-mode prints into JSON mode.
- **Acceptance:** A written contract stating the above 5 items, reviewed and agreed before Task 2 starts.

### Task 2 — Implement `--json` (agent: `cheap-code`)
- **Objective:** Add `--json` flag; in JSON mode print exactly one JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` and nothing else to stdout.
- **Files to modify:** `synccli.py` (`main()`; plus one new small helper, e.g. `build_result(src, dst, copied, skipped_count)`).
- **Constraint:** `sync()` signature **and return type unchanged** — so `skipped` must be computed outside `sync()` (e.g. via `build_manifest(src)` length minus `len(copied)`), or `sync()` must be wrapped by a *new* function that `sync()` callers continue to use untouched.
- **Risks:**
  - `build_manifest()` called a second time re-walks the tree — cost + possible TOCTOU skew if files change between `sync()`'s walk and the counting walk. Mitigation: compute the total from the same manifest `sync()` used, by having the new helper do the walking itself **instead of** `sync()`, or by exposing a new function `sync_report()` that returns both. Must not alter `sync()`'s observable behavior.
  - Double-counting if the counting manifest differs from the copy manifest.
  - `print()` of human lines still executed in JSON mode.
- **Acceptance:** `python3 -m synccli SRC DST --json` emits stdout that parses as a single JSON object with exactly the 4 required keys, `copied` is a list of relpaths, `skipped` an int; `stdout` contains no newline-separated path list.

### Task 3 — Implement `--dry-run` + `--json` interplay (agent: `cheap-code`, same session as Task 2)
- **Objective:** With `--dry-run --json`, `copied` lists what *would* be copied; no filesystem mutation (no copied files, no manifest written).
- **Files to modify:** `synccli.py` (`main()` JSON branch only — `sync(dry_run=True)` already returns the would-copy list and skips writing).
- **Risks:** `skipped` in dry-run mode must be computed against the *would-be* copy set, not the post-copy set; easy to get wrong if skipped is derived from a fresh walk instead of the same manifest. Manifest must NOT be written in dry-run (current `sync()` already returns early — verify this holds).
- **Acceptance:** `python3 -m synccli SRC DST --dry-run --json` prints valid JSON whose `copied` equals the set of files that a subsequent non-dry-run would copy; `dst` directory contains no copied files and no `.sync_manifest.json`.

### Task 4 — Human mode regression check (agent: `cheap-mech`)
- **Objective:** Confirm human mode is byte-identical to current behavior.
- **Files to modify:** none (verification only).
- **Risks:** A shared formatting helper could accidentally change spacing/ordering of the human output (one path per line, sorted order from `scan_files`).
- **Acceptance:** `python3 -m synccli SRC DST` output equals the pre-change output exactly (same lines, same order); exit code still 0.

### Task 5 — Tests (agent: `cheap-code`)
- **Objective:** Unit tests for the JSON shape and dry-run semantics, added to `test_synccli.py`.
- **Files to modify:** `test_synccli.py` (append a `TestJsonOutput` class; do not restructure existing tests).
- **Cases to cover:**
  1. `--json` stdout parses as a single JSON object; keys `copied`, `skipped`, `src`, `dst` all present.
  2. `copied` is a list of relative paths matching the files actually present in `dst` after a real run.
  3. `skipped` equals `total_source_files - copied_count` per Task 1's definition.
  4. `--dry-run --json` → `copied` lists would-copy paths, `dst` is unmodified (no files, no manifest).
  5. `--json` mode prints nothing else to stdout (assert stdout has no stray path lines / parses with `json.loads` after a single `json.loads` of the whole stdout).
  6. Exit code 0 in JSON mode.
  - Capture stdout with `contextlib.redirect_stdout` (stdlib only) or by invoking `synccli.main([...])` directly.
- **Risks:** Tests must not depend on the current working directory or on network/disk-ordering; use `tempfile` like the existing tests. Risk of asserting an ambiguous `skipped` before Task 1 locks the definition.
- **Acceptance:** `python3 -m unittest -v` passes, including all pre-existing tests (no test modified to make it pass).

### Task 6 — Review (agent: `cheap-review` — mandatory)
- **Objective:** Independent review of Tasks 2–5 against the Task 1 contract and GOAL's constraints.
- **Files:** none modified (read-only).
- **Focus:** (a) stdout purity in JSON mode; (b) `skipped` correctness and single-source-of-truth for the manifest; (c) `sync()` signature and return type unchanged — verify `incremental.py`'s import and all call sites still work; (d) stdlib-only, Python 3.10 compatible (no `match`, no 3.11+ APIs); (e) exit code unchanged.
- **Risks:** A major finding here routes back to Task 2/5; a minor finding resumes the same `cheap-code` session.
- **Acceptance:** Review report with findings classified minor/major; zero major findings outstanding; `python3 -m unittest -v` green on the reviewed tree.

### Task 7 — Final verification (agent: `strong-review` only if Task 6 flagged major findings; otherwise `cheap-review` suffices)
- **Objective:** End-to-end audit against GOAL.md line by line.
- **Acceptance:** Each of GOAL's 4 numbered requirements and 3 constraints demonstrated by an executed command with visible output, recorded in the final report.

## Ordering

`1 → 2 → 3 → 4 → 5 → 6 → (7)`

Tasks 2 and 3 are one `cheap-code` session (same feature, same file). Task 4 can run in parallel with Task 2–3 since it only asserts current behavior. Task 5 depends on Task 1's contract. Task 6 depends on 2–5.

## Explicitly out of scope
`DESIGN.md`'s daemon (`syncd`), the `collect_stale` off-by-one, the `filter_excluded` mutable-default-arg bug in `incremental.py`, and content hashing / inotify.

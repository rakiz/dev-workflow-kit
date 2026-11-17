# Execution plan: `--json` output mode and dry-run UX

I read GOAL.md and README.md, and also `synccli.py`, `test_synccli.py`, `incremental.py` and `DESIGN.md`. Nothing has been modified.

**Agent mapping.** I mapped your four roles to the pipeline agents: impl = `cheap-code`, review = `cheap-review`, explore = `explore`, design-review = `cheap-design-review`. Escalate to `strong-*` only after demonstrated failure. Reviewers get a fresh session each, and their briefs must be self-contained.

## Findings that shape the plan

1. **`skipped` has no source.** `sync()` returns only the copied list, and its signature must stay stable. `skipped` can't be computed in `main()` without either rescanning or adding an internal helper.
2. **Stdout purity is the main risk.** `main()` is the only place that prints. `copy_file` and `sync` print nothing, but any future `print` or stray warning would break the "single JSON object" contract.
3. **The baseline test suite may already fail.**
   - `collect_stale` iterates `range(1, len(items))`, which skips the first item.
   - `test_first_item_stale_is_included` expects the first item to be included, so it should fail today.
   - This is outside the goal, so it must be isolated and not fixed without your approval.
4. **Other out-of-scope smells I will not touch:**
   - `copy_file` swallows `OSError`, so `copied` can include files that were never copied, and the manifest then records them as done.
   - `incremental.py` has a mutable default argument in `filter_excluded`.
   - `incremental.py` has a broad `except Exception` in `copy_many`.
   - `DESIGN.md` describes a v2 daemon, which is unrelated to this goal.
5. **README.md is thin.** It doesn't mention the flags, so it is a small docs candidate.

## Tasks (ordered)

### T1. Baseline and impact survey
- **Agent:** `explore` (read-only)
- **Objective:** Establish the real baseline and find all `sync()` and `main()` callers, including the "internal callers" the goal mentions.
- **Files:** none created or modified. Read `synccli.py`, `incremental.py`, `test_synccli.py`, and grep for `sync(` and `main(` across the repo.
- **Work:**
  - Run `python3 -m unittest -v` and record the result.
  - List every caller of `sync()`.
  - Confirm that `python3 -m synccli --help` works.
- **Risks:**
  - The baseline is red because of `collect_stale`. Report this and do not fix it.
  - `incremental.py` imports `from synccli import copy_file`, so any rename or move in `synccli` would break it.
- **Acceptance:** A written report with the baseline pass/fail list, the caller list, and Python version >= 3.10 confirmed. No files changed (`git status` is clean).

### T2. Design decision for `skipped` and the output contract
- **Agent:** `cheap-design-review` (or a short design note from the orchestrator, reviewed here). This is a small decision, so no full design agent is needed.
- **Objective:** Fix three semantics before coding:
  - `skipped` = number of files scanned in `src` minus `len(copied)`. This works for a dry run too.
  - JSON key set and order: `copied`, `skipped`, `src`, `dst`.
  - `src` and `dst` are echoed as passed on the command line.
- **Files:** none. The output is a brief of at most one page, to be included in the T3 prompt.
- **Recommended approach:**
  - Add an internal helper, e.g. `_sync(src, dst, dry_run) -> (copied, total)`.
  - Keep `sync()` as a thin wrapper with an identical signature and return value.
  - Do not change the return type of `sync()`.
- **Risks:**
  - Ambiguous `skipped` semantics. For example, the manifest-excluded dot-directories are not counted by `scan_files`.
  - The helper approach is a bit more invasive than a rescan in `main()`, but a rescan would double the I/O and could race with changes.
- **Acceptance:** The reviewer approves a definition of `skipped` and confirms that `sync()`'s signature and return type are unchanged.

### T3. Implement `--json` and dry-run semantics
- **Agent:** `cheap-code`
- **Objective:** Add the `--json` flag to `main()`, keep human mode byte-identical, and support `--json --dry-run` where `copied` lists what would be copied.
- **Files to modify:** `synccli.py` only.
  - Add `parser.add_argument("--json", action="store_true")`.
  - Add the internal helper from T2.
  - In JSON mode, emit exactly one `json.dumps(...)` followed by a newline via a single `print` or `sys.stdout.write`, and nothing else on stdout.
  - Human mode keeps the `for rel in copied: print(rel)` loop.
  - Return 0 in both modes, as today.
- **Constraints:** stdlib only, Python 3.10-compatible syntax (no `match` guards beyond 3.10, no `tomllib`, no `X | Y` runtime tricks), and `sync(src_root, dst_root, dry_run=False)` unchanged.
- **Risks:**
  - Any extra print in JSON mode breaks the contract.
  - `json.dumps` on Windows-style separators in paths is fine.
  - Non-ASCII filenames: use the default `ensure_ascii=True` for safety.
  - Dry run must not write the manifest or create files. The current early return already guarantees this.
  - Do not "fix" `collect_stale` or `copy_file` in this task.
- **Acceptance:**
  - `python3 -m synccli SRC DST --json | python3 -c 'import sys,json; d=json.load(sys.stdin); assert set(d)=={"copied","skipped","src","dst"}'` passes.
  - Human-mode output is unchanged for the same inputs, compared by diff against T1's captured output.
  - With `--dry-run --json`, `DST` is unchanged (no manifest and no files).
  - The `sync()` signature is verified by `inspect.signature`.

### T4. Add unit tests for the JSON shape
- **Agent:** `cheap-code`. It can be the same instance as T3 if the context is small; otherwise a fresh session with the T3 report as its brief.
- **Objective:** Add the tests the goal requires.
- **Files to modify:** `test_synccli.py` only. Add a `TestJsonOutput` class that calls `main([...])` with `contextlib.redirect_stdout` and `io.StringIO`:
  - the output is valid JSON, parsed with `json.loads`, and is a single object (the whole stdout is one JSON document).
  - the keys `copied`, `skipped`, `src`, `dst` are present with the right types.
  - `skipped` is correct on a second run (all files skipped, `copied == []`).
  - Dry run: `copied` lists the files, `dst` has no files and no manifest afterwards, and a following real run copies the same list.
  - Human mode prints one path per line and no JSON.
  - The return code is 0.
- **Risks:**
  - Tests must use `tempfile` and clean up where possible.
  - mtime granularity: don't depend on mtime changes in the same second.
  - Don't edit existing tests, including the likely-failing `collect_stale` test.
- **Acceptance:** The new tests pass with `python3 -m unittest -v test_synccli.TestJsonOutput`. They fail if `--json` is stubbed out (a quick mutation check by the reviewer). The pre-existing test results are unchanged from T1.

### T5. Review of the implementation and tests
- **Agent:** `cheap-review`. Use a fresh session and a self-contained brief with the diff, the goal, and the T2 contract.
- **Objective:** Check the diff against each line of GOAL.md.
- **Checklist:**
  - stdout purity in JSON mode.
  - `sync()` signature and return unchanged.
  - exit code unchanged.
  - no new imports beyond stdlib.
  - Python 3.10 compatibility.
  - human mode unchanged.
  - test quality (not tautological).
  - no out-of-scope edits in `incremental.py` or `collect_stale`.
- **Classification:** minor findings go back to the `cheap-code` instance via `task_id`. Major findings, such as a broken contract or a changed signature, go to `strong-code`, with a note to you before escalating.
- **Acceptance:** The review report has zero open major findings. Minor findings are fixed and confirmed by the orchestrator's own re-run of the tests.

### T6. Final verification and docs
- **Agent:** `cheap-code` for the README edit (small), then the orchestrator runs the checks.
- **Objective:** Document the flags and run the final acceptance.
- **Files to modify:** `README.md`. Add a short usage section for `--dry-run` and `--json`, with the output shape.
- **Final checks:**
  - `python3 -m unittest -v` passes. Any remaining failures must be only the pre-existing ones recorded in T1.
  - `python3 -m synccli --help` lists `--json`.
  - `git diff --stat` touches only `synccli.py`, `test_synccli.py` and `README.md`.
- **Risks:** Docs drift from the actual output. Copy the example from a real run.
- **Acceptance:** All of the final checks above are met. A summary goes to you listing the deferred out-of-scope issues.

## Needs your decision (nothing will be changed without a yes)

- **Fix `collect_stale`?** The off-by-one bug looks real. It is not part of this goal.
- **Fix `copy_file` swallowing `OSError`?** This is real data-integrity risk, because failed copies are recorded in the manifest as done. It is also out of scope.
- **Fix `incremental.py`?** That means the mutable default argument and the broad exception handler.
- **DESIGN.md (the v2 daemon)?** It has real flaws:
  - a non-atomic manifest rewrite.
  - mtime+size only, with a 500 ms full-tree poll over about 50k files.
  - hardcoded interval and errors only logged to stdout.
  - Logging to stdout would also conflict with the `--json` purity rule.
  - If you want it pursued, it needs a `strong-design` pass and a `design-review`. I recommend a separate goal.

**Execution plan: `--json` output and dry-run UX for synccli**

No files were modified. I read GOAL.md and README.md, plus `synccli.py`, `incremental.py` and `test_synccli.py`, because the plan depends on their code.

**Findings that shape the plan**
- `sync()` returns only the files to copy. The `skipped` count needs the total file count, so it cannot come from `sync()`'s return value without changing it. `sync()`'s signature and return type must stay as they are.
- `copy_file` swallows `OSError` silently. A file that failed to copy still appears in `copied`, and the manifest is written for all source files. JSON `copied` would therefore overstate what was copied.
- Baseline: `collect_stale` uses `range(1, len(items))`, so it skips item 0. `test_first_item_stale_is_included` should currently fail. The suite is not green before any change.
- `incremental.py` imports `copy_file` from `synccli` and is not called by the CLI. `filter_excluded` has a mutable default argument (`excluded=[]`).
- README says `python3 -m synccli --help`. That works because `synccli.py` is a module, not a package.

**Task 0 – Baseline (explore)**
- Objective: record the current test results before any change.
- Files: none.
- Agent: `explore` (run `python3 -m unittest -v` and report).
- Risk: none.
- Acceptance: a written list of passing and failing tests. Expected: `test_first_item_stale_is_included` fails. Any other failure is reported before work starts.

**Task 1 – Decide the skipped/copied contract (cheap-design, then cheap-design-review)**
- Objective: pick these semantics and record them in the design: (a) `skipped` = total source files minus `len(to_copy)`; (b) `copied` in non-dry mode = attempted copies or verified copies, given the silent `OSError` path; (c) dry-run `copied` = `to_copy`, nothing written.
- Approach to choose from: a helper such as `plan_sync(src, dst) -> (to_copy, total)` used by `sync()` and by `main`, leaving `sync()`'s public signature and return unchanged.
- Files: design note only (no code yet).
- Agent: `cheap-design`, then `cheap-design-review`. Optional: skip if you accept the approach above without review.
- Risk: choosing (b) without the user's input. This is a product decision; ask the user.
- Acceptance: the design fixes the semantics of `copied` and `skipped` for each mode, and `sync()`'s signature is confirmed unchanged.

**Task 2 – Implement `--json` in `synccli.py` (cheap-code)**
- Objective: add `--json` to the parser. In JSON mode, `main` prints exactly one JSON object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` and nothing else on stdout. Human mode prints one path per line as before. Return 0 as before.
- Files to modify: `synccli.py` (`main`, plus the helper from Task 1 if chosen).
- Agent: `cheap-code`, then Task 3 review.
- Risks: a second directory scan if the helper is not used, which doubles I/O. Stray prints on stdout. Uncaught exceptions on a missing source directory keep exit code behaviour but must not write to stdout.
- Acceptance: `python3 -m synccli SRC DST --json | python3 -m json.tool` succeeds. The output has the four keys. `sync()` signature is unchanged, and `incremental.py` still imports cleanly.

**Task 3 – Review of Task 2 (cheap-review, fresh reviewer)**
- Objective: check against GOAL.md: stdout purity, `skipped` arithmetic, dry-run semantics, signature stability, no new dependencies, Python 3.10 stdlib only.
- Agent: `cheap-review`. Major findings escalate to `strong-code`. Minor findings go back to `cheap-code` via `task_id`.
- Acceptance: the review returns no open major finding.

**Task 4 – Tests in `test_synccli.py` (cheap-code)**
- Objective: add tests that use `contextlib.redirect_stdout` and `main([...])`:
  - `--json` output parses as JSON, has the four keys, and `skipped` is an int.
  - Nothing other than the JSON object is printed on stdout.
  - `--json --dry-run` lists would-copy files in `copied`, writes no files, and writes no manifest to the destination.
  - Second `--json` run gives `copied == []` and `skipped == total`.
  - Human mode prints one path per line, unchanged.
  - `main` returns 0.
- Files to modify: `test_synccli.py` only.
- Agent: `cheap-code`, then Task 5 review.
- Risk: tests depending on the mtime resolution of the filesystem. Write the source file, then the first sync, so the second sync is deterministic.
- Acceptance: the new tests pass. The only failure in the full suite is the pre-existing one from Task 0. The count of failures does not increase.

**Task 5 – Review of Task 4 (cheap-review, fresh reviewer)**
- Objective: check that the tests actually assert the GOAL.md semantics and do not just run the code.
- Agent: `cheap-review`, a new reviewer instance, not resumed.
- Acceptance: no open major finding.

**Task 6 – Final verification (orchestrator-run, strong-review only on doubt)**
- Objective: run `python3 -m unittest -v` and a manual check of `--json` and `--dry-run --json` against a temp directory. Compare with the Task 0 baseline.
- Agent: `strong-review` only if cheap-review left doubt. Otherwise run the commands directly, since no implementation is involved.
- Acceptance: new tests pass; failures equal the baseline set; `git diff` touches only `synccli.py` and `test_synccli.py` (plus the design note if Task 1 wrote one).

**Out of scope, needs your explicit yes first (per the ask-before-acting rule)**
- Fix the `collect_stale` off-by-one. It is pre-existing and breaks a test. Changing it is a separate task.
- Make `copy_file` report failures, which would make `copied` exact. This touches the non-JSON behaviour too.
- Fix the mutable default in `incremental.py::filter_excluded`.
- Update README with the `--json` flag. The GOAL does not ask for it.

**Decisions needed from you before Task 1**
1. Should `copied` in non-dry JSON mode list attempted copies (what the code does now, possibly inaccurate on read errors) or only verified copies (requires the out-of-scope `copy_file` change)?
2. Is the pre-existing failing test to be fixed in this release or deferred?

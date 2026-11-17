# Execution plan: `--json` output mode and dry-run (synccli)

I read GOAL.md, README.md, `synccli.py`, `incremental.py`, `test_synccli.py` and DESIGN.md. I changed nothing and ran nothing. The agent mapping is: impl = `cheap-code`, review = `cheap-review`, explore = `explore`, design-review = `cheap-design-review`. Escalation to a strong tier only happens after a demonstrated failure.

## Findings that shape the plan

- **Current CLI.** `main()` calls `sync()` and prints one path per line. `--dry-run` already exists.
- **`skipped` has no source.** `sync()` returns only the `to_copy` list, and its signature must stay stable. `skipped` must therefore be computed outside `sync()`. The natural choice is `len(scan_files(src)) - len(copied)`.
- **Pre-existing failing test.** `collect_stale` loops from `range(1, ...)` and skips the first item. `test_first_item_stale_is_included` expects it to be included, so I expect that test to fail today. This is outside the GOAL, so it only gets recorded as a baseline.
- **Silent copy failures.** `copy_file` swallows `OSError`. A file that failed to copy still appears in `copied` and in the manifest. That is existing behaviour and is out of scope.
- **`incremental.py`.** It has a mutable default argument and a `try/except` that can never see a failure, because `copy_file` swallows errors. Nothing in the GOAL touches it, and `synccli.py` does not import it.
- **DESIGN.md.** It describes a different project, the v2 `syncd` daemon. Several of its decisions are risky, for example a non-atomic manifest rewrite every 500 ms and detection by mtime and size only. It is not part of this GOAL.

## Tasks (ordered)

### T0. Baseline and environment check
- **Agent:** `explore`, read-only.
- **Objective:** Record the state of the repo before any change.
- **Files:** none.
- **Steps:** Run `python3 -m unittest -v`. Confirm Python is 3.10 or later and that nothing outside the stdlib is imported. Confirm via grep that `synccli` has no other callers of `main()` or `sync()` (for example `__main__.py`). Note that `python3 -m synccli` as the README describes it only works if `synccli` is a module with a `__main__` block, which it is.
- **Risks:** The `collect_stale` test may already fail, so a red run does not mean we broke something.
- **Acceptance:** A written baseline listing which tests pass and fail, and the list of callers of `sync()`.

### T1. Design check of the JSON contract
- **Agent:** `cheap-design-review`, as a short note read by the orchestrator, not a full design doc.
- **Objective:** Pin down the ambiguous points of the GOAL before coding.
- **Decisions to confirm:**
  1. `skipped` is the number of source files not in `copied`: `len(scan_files(src)) - len(copied)`, computed in `main()`. `sync()` is not changed.
  2. `src` and `dst` are echoed exactly as passed on the command line, not resolved to absolute paths.
  3. `copied` keeps the order returned by `sync()` and uses `os.sep` separators, the same as human mode.
  4. Dry-run in JSON mode returns the same `copied` list and writes nothing to disk. Dry-run semantics already exist in `sync()`.
  5. In JSON mode, stdout carries exactly one `json.dumps(...)` followed by a newline. Errors and tracebacks go to stderr, and the exit code is unchanged: 0 on success, and argparse's 2 on usage errors.
- **Risks:** Counting `skipped` with a second scan of `src` is a TOCTOU window. A file could change between the two scans, so the count can be slightly off. It is acceptable and should be documented. Calling `build_manifest` a second time costs I/O, so use `scan_files` only.
- **Acceptance:** A written list of the five decisions. If the reviewer finds a contradiction with the GOAL, it goes back to the orchestrator before T2.

### T2. Implement the `--json` flag
- **Agent:** `cheap-code`.
- **Files to modify:** `synccli.py` only, in `main()`.
- **Objective:**
  - Add `parser.add_argument("--json", action="store_true")`.
  - After `sync()`, if `--json` is set, print only `json.dumps({"copied": copied, "skipped": N, "src": args.src, "dst": args.dst})`.
  - Otherwise keep the existing loop that prints one path per line.
- **Constraints:**
  - Do not touch the signature or body of `sync()`.
  - Add no imports beyond the stdlib; `json` is already imported.
  - Add no `print()` or logging to stdout in JSON mode.
  - Do not change `copy_file`, `collect_stale` or `incremental.py`.
- **Risks:**
  - A stray `print` in JSON mode would break the single-object contract.
  - `skipped` could go negative if the source changes between scans. Clamp it with `max(0, ...)` or document the case.
  - Keep `main()` returning 0.
- **Acceptance:**
  - `python3 -m synccli SRC DST --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert set(d)=={'copied','skipped','src','dst'}"` exits 0.
  - Running the same command without `--json` gives output identical to before, which T0 records.
  - `git diff --stat` shows only `synccli.py` changed.

### T3. Unit tests for the JSON shape and dry-run
- **Agent:** `cheap-code`. It can be the same session as T2, because the context is shared and small.
- **Files to modify:** `test_synccli.py` only.
- **Tests to add:** call `synccli.main([...])` and capture stdout with `contextlib.redirect_stdout`.
  1. `--json` stdout parses as exactly one JSON object, and `json.loads` of the whole stdout succeeds.
  2. The keys are exactly `copied`, `skipped`, `src` and `dst`, with the right types (`list`, `int`, `str`, `str`).
  3. After one sync, `copied == ["a.txt"]` and `skipped == 0`. After a second sync, `copied == []` and `skipped == 1`.
  4. `--json --dry-run` lists the files that would be copied, and nothing is written. Assert that `dst` has no `a.txt` and no manifest. The tests currently create `dst` with `mkdtemp`, so that assertion holds.
  5. Human mode is unchanged: stdout is `a.txt\n`, with no JSON.
  6. A combined run (`--dry-run --json` first, then a real `--json`) shows that the dry run did not consume the changes.
  7. The exit code from `main()` is 0.
- **Risks:**
  - Tests must not depend on the existing failing `collect_stale` test.
  - Use `tempfile.mkdtemp` with cleanup via `addCleanup`.
  - Use a fixed file name and avoid mtime-dependent assertions.
- **Acceptance:** `python3 -m unittest -v` shows all new tests passing. The only failing test is the baseline `collect_stale` one, and only if T0 recorded it as already failing.

### T4. Independent review
- **Agent:** `cheap-review`, a fresh session with a self-contained brief: the GOAL text plus `git diff`.
- **Objective:** Check the diff against each numbered point of the GOAL and its constraints.
- **Review checklist:**
  - Nothing else is printed to stdout in JSON mode.
  - The `sync()` signature is stable.
  - There are no new dependencies and the code stays Python 3.10 compatible.
  - Human mode is unchanged.
  - The tests really cover the dry-run semantics.
  - The diff touches no files outside T2 and T3.
- **Handling findings:** Minor findings go back to the same `cheap-code` session via `task_id`. Major findings go to `strong-code`, and I tell you before invoking it.
- **Acceptance:** A review verdict with no open major finding.

### T5. Final verification and README update
- **Agent:** `explore` for the check, then `cheap-mech` for the doc line. Both are small.
- **Files to modify:** `README.md`, a one-line mention of `--json` and `--dry-run` under usage. This is optional and only done on your yes.
- **Steps:** Re-run the full test suite and a manual smoke test of the four combinations (none, `--json`, `--dry-run`, both). Confirm `git status` shows only the intended files.
- **Acceptance:** The test suite matches the T0 baseline plus the new passing tests. The smoke test output matches the T1 decisions.

## Out of scope: your decision needed

None of these will be touched without your explicit yes.

1. The `collect_stale` off-by-one and its failing test. This is a likely real bug, so I suggest a separate small task.
2. The silent `OSError` handling in `copy_file`, which makes `copied` unreliable in JSON mode. It is worth deciding whether the JSON contract should state that `copied` means "attempted".
3. The mutable default argument in `filter_excluded` (`incremental.py`).
4. DESIGN.md (the `syncd` daemon): a separate design review is advisable before any of it is built.

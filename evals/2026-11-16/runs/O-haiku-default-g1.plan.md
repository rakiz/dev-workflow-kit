# Execution plan: `--json` mode and dry-run UX for synccli

Nothing was modified. I read GOAL.md, README.md, `synccli.py`, `incremental.py`, and `test_synccli.py`.

## Findings that shape the plan

- `sync(src, dst, dry_run)` returns only the list of files to copy. `skipped` has no source today, so it must be derived, and `sync()`'s signature must not change.
- `main()` prints each path line by line. JSON mode must print one object and nothing else on stdout.
- `copy_file()` swallows `OSError` silently, and `sync()` writes the manifest regardless. So `copied` can list files that were never copied. This needs a decision (see Task 0).
- `collect_stale()` iterates `range(1, len(items))`, which skips index 0. `test_first_item_stale_is_included` expects `x.txt` to be returned, so that test likely fails before any change. Reading the code, I have not run it. Confirm in Task 1.
- `incremental.py` has bugs (mutable default `excluded=[]`, `copy_many` swallowing all exceptions, `merge_manifest` comparing mtimes). These are out of scope. Per the global "ask before acting" rule, they are not in this plan unless you say so.

## Tasks

### Task 0: Decide ambiguous semantics (user, no agent)
- **Objective:** Settle three points before implementation.
  1. `copied` in real (non-dry-run) mode: files attempted, or files confirmed copied? Current `copy_file` hides failures, so the honest option is to report only successful copies, which needs `copy_file` to return a bool.
  2. `skipped`: count of unchanged files, or unchanged plus excluded (dot-directories are already excluded by `scan_files`)? Proposed: unchanged files only.
  3. Are `src`/`dst` the raw CLI arguments or resolved absolute paths? Proposed: raw arguments, as given.
- **Files:** none.
- **Agent:** none. This is your decision. Optionally run `cheap-design-review` on the resulting spec, since it is small.
- **Risk:** Implementing before this is settled means rework.
- **Acceptance:** Written answers to items 1–3.

### Task 1: Establish a baseline (explore)
- **Objective:** Run `python3 -m unittest -v` and record which tests pass and fail, including `TestCollectStale.test_first_item_stale_is_included`. Report the results only; make no edits.
- **Files:** none.
- **Agent:** `explore` (read-only, runs tests).
- **Risk:** Running tests may create `__pycache__`. This is acceptable, but note it.
- **Acceptance:** A pass/fail list that separates pre-existing failures from anything this work introduces. Any pre-existing failure is reported as out of scope unless you approve fixing it.

### Task 2: Make `copy_file` report success (only if Task 0 item 1 chooses confirmed copies)
- **Objective:** `copy_file` returns `True` on success and `False` on `OSError`. `sync()` filters `to_copy` to the successful ones before writing the manifest. Keep the signature of `sync()` unchanged.
- **Files:** `synccli.py` (`copy_file`, `sync`).
- **Agent:** `cheap-code`, then `cheap-review`.
- **Risk:** Changing manifest behaviour on failure. Manifest must not record a file as synced if its copy failed, or the next run will skip it. This is a behaviour change to the existing human mode, so it conflicts with "human mode unchanged". Confirm with the user before doing it.
- **Acceptance:** A test with an unreadable source file shows it absent from the returned list and from the manifest. Existing tests still pass.

### Task 3: Add JSON output and count skipped files
- **Objective:**
  - Add a private helper (e.g. `_plan(src, dst)`) that returns `(to_copy, total_src_count)`, so `skipped = total - len(to_copy)` is available without changing `sync()`'s return value.
  - Add `--json` to `main()`. In JSON mode, print exactly one `json.dumps({"copied": [...], "skipped": N, "src": ..., "dst": ...})` and nothing else on stdout.
  - Human mode stays as is: one path per line.
  - Exit code stays 0.
- **Files:** `synccli.py` (`sync`, new helper, `main`).
- **Agent:** `cheap-code`, then `cheap-review`.
- **Risks:**
  - Any extra `print` in JSON mode breaks the contract. Check for it explicitly.
  - Dry-run must not write the manifest or any file. Current code already returns early, but the new helper must not change this.
  - `sync()` has internal callers (`incremental.py` imports only `copy_file`, but other callers may exist outside this repo). Confirm the return value is unchanged.
- **Acceptance:** `python3 -m synccli --json SRC DST` prints one parseable JSON object and nothing else. Human-mode output is byte-identical to before for the same inputs (compare against the original with the same fixture).

### Task 4: Dry-run plus JSON semantics
- **Objective:** With `--json --dry-run`, `copied` lists the files that would be copied. Nothing is written to `dst`, and no manifest is created or updated.
- **Files:** `synccli.py` (`main`, possibly no change if Task 3 handles it).
- **Agent:** `cheap-code`, then `cheap-review`. Can be folded into Task 3 if the change is trivial.
- **Risk:** Off-by-one between the "would copy" list and the list a real run produces. Test both from the same fixture.
- **Acceptance:** After a dry-run, `dst` has no `a.txt` and no `.sync_manifest.json`. The `copied` list equals what a real run returns on the same fixture.

### Task 5: Unit tests for JSON shape and dry-run semantics
- **Objective:** Add a `TestJsonOutput` class to `test_synccli.py`. Capture stdout with `contextlib.redirect_stdout` and call `synccli.main([...])`. Cover:
  1. Output parses with `json.loads` as the whole stdout (proves nothing else is printed).
  2. Keys `copied`, `skipped`, `src`, `dst` are present with the right types.
  3. `--json --dry-run` on an empty destination: `copied` is non-empty, `dst` is untouched.
  4. A second `--json` run: `copied == []` and `skipped` equals the file count.
  5. Human mode still prints one path per line (regression test).
- **Files:** `test_synccli.py`.
- **Agent:** `cheap-code`, then `cheap-review`.
- **Risks:** Test isolation: `setUp` uses `mkdtemp` and never cleans up. Use `tempfile.TemporaryDirectory` in new tests. Don't copy the leak.
- **Acceptance:** The new tests fail on the pre-change code and pass after Tasks 3–4. The full suite run from Task 1 shows no new failures.

### Task 6: Review of the full diff (cheap-review, then optional strong-review)
- **Objective:** Review `synccli.py` and `test_synccli.py` changes against GOAL.md's four requirements, checking stdout cleanliness, dry-run side effects, and signature stability.
- **Files:** read-only.
- **Agent:** `cheap-review` (mandatory). Use a fresh reviewer, not a resumed one. If it returns a major finding, escalate per the cost rules. Use `strong-review-alternative` only if the diff was mostly written by a Claude model and there is real doubt after cheap-review.
- **Acceptance:** No major findings open. Minor findings are sent back to `cheap-code` through the same instance.

### Task 7: Final verification (explore, then user)
- **Objective:** Run the full suite and the manual checks:
  - `python3 -m unittest -v`
  - `python3 -m synccli --json --dry-run SRC DST | python3 -m json.tool`
  - Compare human-mode output with the original on the same fixture.
  Report the results. Only if you say yes: add a `--json` mention to README.md (currently it only points to `--help`).
- **Files:** README.md only if you approve.
- **Agent:** `explore` for the run, no edits.
- **Acceptance:** All new tests pass. Pre-existing failures from Task 1 are either unchanged or explicitly approved for fixing. Human-mode output is byte-identical.

## Decisions needed from you before Task 2 or Task 3

1. Report confirmed copies only, or attempted copies? (Affects Task 2 and manifest behaviour.)
2. Is `skipped` unchanged files only?
3. Should I include the `collect_stale` test failure and `incremental.py` bugs in scope, or leave them?
4. Update README.md in this release?

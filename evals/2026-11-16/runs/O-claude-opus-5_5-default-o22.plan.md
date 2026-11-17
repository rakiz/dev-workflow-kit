I read GOAL.md, README.md, synccli.py, test_synccli.py, plus DESIGN.md and incremental.py for context. No files were modified.

## What the code shows now

- In `sync(src, dst, dry_run)` (synccli.py:73), `dry_run=True` returns the would-copy list before any write. The function returns only `copied`, so there is no `skipped` count yet.
- `main()` (synccli.py:89) prints one relative path per line. The exit code is always 0.
- `copy_file` swallows `OSError` (synccli.py:68). In JSON mode, a file that failed to copy would still be listed in `copied`.
- `collect_stale` uses `range(1, len(items))`, so it skips the first item. A test is named `test_first_item_stale_is_included`, so the full test suite probably fails today. This bug is outside the GOAL's scope.
- `incremental.py` imports from synccli, so internal callers exist. Two other problems there are also out of scope: a mutable default argument `excluded=[]`, and a dead `except` in `copy_many`.

## Execution plan

### T0 — Baseline and caller inventory
- **Objective:** Run `python3 -m unittest -v` to record which tests pass now. List every caller of `sync()` and every use of its return value.
- **Files:** none (read-only).
- **Agent:** `explore`
- **Risks:** If the `collect_stale` test already fails, later results could be misread as a regression.
- **Acceptance:** A report giving the baseline pass/fail per test and the list of `sync()` call sites.

### T1 — Short design note: how to compute `skipped` without changing `sync()`
- **Objective:** Choose an approach. Recommended: add a private `_sync_plan(src, dst, dry_run) -> dict(copied, skipped, src, dst)` that contains the current body of `sync()`. `sync()` then becomes `return _sync_plan(...)["copied"]`, keeping the same signature and return type.
- **Decisions to make:**
  - Define `skipped` as the number of source files minus the number copied.
  - Decide whether `src`/`dst` in the JSON are the arguments as given or absolute paths.
  - Decide whether paths use OS separators or `/`.
  - Decide whether files that `copy_file` fails on appear in `copied`. Recommended: keep current behaviour and document it, since changing it would alter `sync()` semantics.
- **Files:** none, or a short section in the PR description.
- **Agent:** `cheap-design` → `cheap-design-review`
- **Risks:** Scanning the tree a second time just to count files could disagree with the first scan (race) and wastes time. Calling `sync()` twice from `main` would copy twice.
- **Acceptance:** The review approves a note that settles all four decisions and confirms the `sync()` contract is unchanged.

### T2 — Implement `--json` and its interaction with `--dry-run`
- **Objective:**
  - Add the `_sync_plan` helper.
  - Add a `--json` argparse flag.
  - In JSON mode, write exactly one `json.dumps(...)` object to stdout, with keys `copied` (list), `skipped` (int), `src`, `dst`.
  - With `--dry-run`, `copied` lists the files that would be copied.
  - Human mode stays byte-for-byte the same, and the exit code stays the same.
- **Files:** `synccli.py`
- **Agent:** `cheap-code`
- **Risks:**
  - Something else printing to stdout in JSON mode.
  - The manifest being written during a dry run.
  - Pulling in a new import (only the stdlib `json` is allowed).
  - Accidentally changing what `sync()` returns.
- **Acceptance:**
  - `python3 -m synccli a b --json | python3 -c "import json,sys; json.load(sys.stdin)"` succeeds.
  - Human-mode output on a sample tree matches the output from before the change.
  - `git diff` shows `def sync(src_root, dst_root, dry_run=False)` unchanged.

### T3 — Tests
- **Objective:** Add tests to `test_synccli.py` that call `main([...,"--json"])` with stdout captured through `contextlib.redirect_stdout`. Cover:
  - The output parses as exactly one JSON value, with all four keys and the right types.
  - `skipped` is correct on a second run (copied is empty, skipped equals the file count).
  - With `--json --dry-run`: `copied` lists the files, no manifest is written, and no destination files are created.
  - Human mode still prints one path per line.
  - `sync()` still returns a list.
- **Files:** `test_synccli.py`
- **Agent:** `cheap-code` (the same instance as T2, resumed via `task_id`)
- **Risks:** Tests that depend on mtime timing; temporary directories not cleaned up.
- **Acceptance:** `python3 -m unittest -v` shows the new tests passing, and everything else matches the T0 baseline.

### T4 — Review
- **Objective:** Check the T2+T3 diff against GOAL.md:
  - only one object on stdout
  - stdlib only
  - `sync()` signature and behaviour unchanged
  - `incremental.py` still imports correctly
  - edge cases: `dst` missing, empty `src`
- **Agent:** `cheap-review` (a fresh instance). Minor findings go back to the T2 instance; a major finding escalates to `strong-code`.
- **Acceptance:** The review returns no open major findings, and the tests are green relative to the baseline.

### T5 (optional, needs your approval) — Out-of-scope issues found
- **Issues:**
  - the `collect_stale` off-by-one
  - `filter_excluded`'s mutable default argument
  - `copy_file` silently swallowing errors
  - DESIGN.md weaknesses: a full tree scan every 500 ms across ~50k files, manifest writes that are not atomic, and errors logged to stdout
- **Agent:** none until you approve.
- **Acceptance:** Not applicable unless you approve.

**Order:** T0 → T1 → T2 → T3 → T4. T5 happens only if you ask for it.

I read GOAL.md, README.md, and the three Python files (`synccli.py`, `incremental.py`, `test_synccli.py`). I did not run the test suite and made no changes.

## Current state (relevant facts)

- `sync(src, dst, dry_run)` returns the list of files to copy. It has no skipped count, so `skipped` must be derived.
- `main()` prints one path per line. There is no JSON path yet.
- In dry-run, `sync()` returns before writing files or the manifest. The dry-run semantics we need already exist.
- `copy_file()` swallows `OSError`, but `sync()` still writes the manifest and reports the file as copied. The `copied` list can therefore include files that were not actually copied. This affects the JSON contract.
- Likely pre-existing failure: `collect_stale` uses `range(1, len(items))`, so it skips index 0. `TestCollectStale.test_first_item_stale_is_included` expects `["x.txt", "y.txt"]` and will likely fail. This must be confirmed by a baseline run (T0).

## Execution plan

### T0. Baseline verification (read-only)
- **Objective:** Record the current test results before any change, so regressions can be told apart from pre-existing failures.
- **Files:** none modified. Running the tests may create `__pycache__`.
- **Agent:** `explore`, running `python3 -m unittest -v` and `python3 -m synccli --help`.
- **Risks:** The baseline may already be red (see the `collect_stale` note above). That is not a reason to fix it inside this task.
- **Acceptance:** A written list of passing and failing tests. The `collect_stale` status is confirmed or refuted.

### T1. Design the JSON/dry-run contract (optional, small)
- **Objective:** Fix the exact contract before coding: `{"copied": [...], "skipped": N, "src": <arg>, "dst": <arg>}`. Define `skipped` as the count of scanned source files not in `copied` (`len(src_manifest) - len(copied)`). Define `src`/`dst` as the raw CLI arguments. Decide that `sync()` stays a thin wrapper over a new internal helper (for example `_sync_report(src, dst, dry_run) -> dict`) that returns copied, skipped, and the manifest result, so the public signature is unchanged.
- **Files:** none, the decision goes in the brief for T2.
- **Agent:** `cheap-design` for the draft, then `cheap-design-review`. Both are optional because the change is small. Skipping them is defensible, but the signature-stability constraint justifies one review.
- **Risks:** Adding a `skipped` return to `sync()` would break internal callers. Counting `skipped` inconsistently between dry-run and real runs.
- **Acceptance:** A short approved contract with the exact key set, types, and the `sync()` signature unchanged.

### T2. Implement `--json` and dry-run interplay
- **Objective:** Add `--json` to `main()` and the internal report helper. In JSON mode, print exactly one `json.dumps` object to stdout and nothing else. In human mode, keep one path per line. With `--dry-run --json`, `copied` lists the would-copy files and no files or manifest are written.
- **Files to modify:** `synccli.py` (`main`, new helper, `sync` delegating to it). `incremental.py` is not touched.
- **Agent:** `cheap-code`.
- **Risks:**
  - Any stray `print` or warning on stdout in JSON mode breaks the contract.
  - Exit code must stay 0 for success and unchanged for exceptions.
  - `copied` may list files that `copy_file` silently skipped. Fixing that changes the copy semantics and needs a separate decision (see Open questions).
  - The `sync()` signature must not change.
- **Acceptance:** `python3 -m synccli SRC DST --json | python3 -m json.tool` succeeds. The keys are `copied`, `skipped`, `src`, `dst`. Human-mode output is byte-identical to before for the same inputs.

### T3. Add unit tests
- **Objective:** Add tests to `test_synccli.py` covering:
  - JSON output parses with `json.loads`, has the four keys, and has the right types.
  - The stdout capture is exactly one JSON object (use `contextlib.redirect_stdout`).
  - `--dry-run --json`: `copied` lists the would-copy files, dst contains no copied files and no `.sync_manifest.json`.
  - Second JSON run gives `copied == []` and `skipped == N`.
  - Human mode prints one path per line and is unchanged.
- **Files to modify:** `test_synccli.py` only.
- **Agent:** `cheap-code`, same brief as T2 or a new session. Use a new session because the work is a different phase.
- **Risks:** Tests that depend on tempdir ordering. `setUp` in `TestSync` does not clean up tempdirs. Keep new tests self-contained.
- **Acceptance:** `python3 -m unittest -v` shows all new tests passing. The only failures allowed are those recorded in T0.

### T4. Review
- **Objective:** Independent review of the T2 and T3 diff against GOAL.md.
- **Agent:** `cheap-review` (mandatory, fresh reviewer, self-contained prompt). Check stdout purity, dry-run side effects, the unchanged `sync()` signature, no new dependencies, and Python 3.10 stdlib only.
- **Escalation:** Only on a major finding, `strong-code` for the fix. If it is a cross-cutting concern, `strong-code-alternative`.
- **Acceptance:** Review verdict with no major findings. Minor findings are sent back to the same `cheap-code` session if it is still in context, otherwise to a fresh one.

### T5. Final verification
- **Objective:** Confirm the goal end to end: run tests, run the CLI in all four modes (human, json, dry-run, dry-run+json) against a temp source and destination, and confirm the exit code.
- **Agent:** `strong-review` as the final audit (use `strong-review-alternative` only if the implementation was produced by a Claude strong rung).
- **Acceptance:** Test results match T0 plus the new passing tests. All four CLI modes behave as specified. Exit codes are 0.

## Open questions (need your decision before T2; I will not act on these without a yes)

1. **Unreadable sources:** `copy_file` silently swallows errors, but the manifest still records the file as copied. Should `copied` only include files that were actually copied? This changes existing behavior, so it is out of scope unless you approve.
2. **`collect_stale` off-by-one** (`range(1, ...)`), if T0 confirms the failing test: fix it in this release or track it separately?
3. **`incremental.py` pre-existing bugs:** the mutable default `excluded=[]` in `filter_excluded`, and the `<=` in `merge_manifest`. Out of scope for this goal, so I'm not planning to touch them.

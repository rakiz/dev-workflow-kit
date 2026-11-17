Here's the plan. I made no changes to the repo.

**What I found that affects the plan**
- `sync(src_root, dst_root, dry_run=False)` returns only the list of copied paths. Callers include `incremental.py`, and DESIGN.md says a future `syncd` will reuse `sync()`. So the signature and return type must stay as they are.
- The JSON output has a `skipped` count, but nothing in the code computes one today. GOAL.md doesn't define it either; I'll take it to mean source files that were unchanged and not copied.
- `copy_file` silently ignores read errors (`except OSError: pass`), so `copied` can list files that were never actually copied. The JSON output would repeat that.
- An existing bug is outside this goal: `collect_stale` starts its loop at index 1, so `test_first_item_stale_is_included` probably fails already. That would break any acceptance check that requires the whole suite to pass.

---

### T0. Establish a baseline
- **Objective:** Run `python3 -m unittest -v` and record which tests already fail (I expect the `collect_stale` one), plus the current CLI output.
- **Files:** none.
- **Agent:** explore.
- **Risk:** A failing suite before the work starts makes "all tests pass" meaningless as a check.
- **Acceptance:** A written list of tests that pass and fail before any change.

### T1. Decide the open spec questions (no code)
- **Objective:** Settle four things:
  - What `skipped` means: `len(src_manifest) - len(copied)`.
  - How to get that count without touching `sync()`: add a new internal helper, e.g. `plan_sync(src, dst) -> (to_copy, src_manifest)`, which `sync()` also uses. The CLI calls the helper.
  - The format of `src`/`dst`: as given on the command line, or absolute.
  - Whether `copy_file` failures should show up in JSON. My recommendation is to leave that out of scope and note it.
- **Files:** none, or a short note in GOAL.md if you approve.
- **Agent:** cheap-design, then cheap-design-review.
- **Risks:** Computing `skipped` by scanning the source a second time could disagree with what was copied if files change in between. The helper approach avoids that.
- **Acceptance:** A one-page decision covering `skipped`, the path format, the helper's signature, and confirmation that `sync()` itself is unchanged.

### T2. Implement `--json` and how it combines with `--dry-run`
- **Objective:**
  - Add a `--json` flag in `main()`.
  - Print exactly one `json.dumps({"copied": [...], "skipped": N, "src": ..., "dst": ...})` to stdout.
  - With `--dry-run --json`, `copied` lists what would be copied, and nothing is written.
  - Human mode stays as it is (one path per line).
  - The exit code stays 0.
- **Files:** `synccli.py`, in `main()` plus the helper chosen in T1.
- **Agent:** cheap-code.
- **Risks:**
  - Stray `print` calls ending up on stdout.
  - Changing the behaviour of `sync()` by accident and breaking `incremental.py`.
  - Non-ASCII paths: keep `ensure_ascii` at its default so the output stays valid.
  - Making sure the order of `copied` stays deterministic.
- **Acceptance:**
  - `python3 -m synccli A B --json | python3 -c "import json,sys; json.load(sys.stdin)"` succeeds.
  - Output without `--json` is byte-identical to the T0 baseline.
  - `git diff` shows the `sync()` signature unchanged.

### T3. Unit tests in `test_synccli.py`
- **Objective:** Call `main([...,'--json'])` and capture stdout with `contextlib.redirect_stdout`. Test that:
  - the output is valid JSON and is the only output;
  - the four keys are present with the right types;
  - in dry-run, `copied` is non-empty, no files appear in `dst`, and no manifest is written;
  - a second run gives `copied == []` and `skipped == number of files`;
  - human mode is unchanged.
- **Files:** `test_synccli.py`.
- **Agent:** cheap-code, ideally the same session as T2 continued via `task_id`.
- **Risks:** Leftover temporary directories, and tests that depend on mtime timing.
- **Acceptance:** The new tests pass, and no test that passed in T0 now fails.

### T4. Review
- **Objective:** Check the T2 and T3 diff against GOAL.md. Points to check:
  - nothing but the JSON object on stdout;
  - `sync()` stable and `incremental.py` still compatible;
  - standard library only, Python 3.10;
  - dry-run writes nothing.
- **Files:** none (read-only).
- **Agent:** cheap-review, a fresh session. A major finding goes to strong-code; a minor one goes back to the T2/T3 session.
- **Acceptance:** No major finding, and the full suite result matches T0 plus the new tests.

### T5. Docs
- **Objective:** Document `--json` in the README, with an example of the JSON output.
- **Files:** `README.md`.
- **Agent:** cheap-mech, then cheap-review.
- **Acceptance:** The README example matches the real output of a test run.

---

**Out of scope — your call:**
- Fixing the `collect_stale` index-1 bug.
- Reporting the copy errors that `copy_file` currently ignores.
- DESIGN.md (the v2 daemon), which has nothing to do with this goal but has issues worth a separate review: polling the whole tree every 500 ms at about 50,000 files, rewriting the manifest without atomic writes, and logging to stdout.

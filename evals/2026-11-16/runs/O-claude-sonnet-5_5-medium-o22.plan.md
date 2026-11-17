# Execution plan: synccli `--json` and dry-run

I read only GOAL.md and README.md. I haven't read the code, so file names beyond `test_synccli.py` are assumptions that Task 1 must confirm.

## Task 1: Map the code (agent: explore, read-only)
- **Objective:** Find where `sync()` is defined, where the CLI parses arguments and prints, whether `--dry-run` already exists, and who calls `sync()`.
- **Files:** none modified. Likely `synccli/__main__.py`, `synccli/cli.py`, `test_synccli.py`.
- **Risks:**
  - `--dry-run` may not exist yet. The GOAL says "interplay", so it may or may not be there.
  - Other code may print to stdout (progress lines, warnings), which would break the "single JSON object" rule.
  - Internal callers of `sync()` may depend on its return value.
- **Acceptance:** A report that lists:
  - the `sync()` signature and return type;
  - every `print` or stdout write in the call path;
  - the argparse definitions;
  - the callers of `sync()`;
  - the current test layout and how the tests run.

## Task 2: Design the output contract (agent: design-review, lightweight)
- **Objective:** Check a short design before coding. It covers:
  - how `copied` (list), `skipped` (int), `src` and `dst` are obtained without changing the `sync()` signature, for example by returning a result object or reusing the existing return value;
  - how stdout is kept clean in JSON mode (route logs and warnings to stderr);
  - how errors behave in JSON mode (exit code unchanged, message on stderr);
  - whether paths in `copied` are relative or absolute, and whether they are strings.
- **Files:** none (a design note in the orchestrator's brief).
- **Risks:**
  - The signature must stay stable. Adding a keyword argument with a default is acceptable if the GOAL's "stable" is read that way. Confirm this, or avoid it.
  - `src` and `dst` are ambiguous (raw argument or resolved path).
- **Acceptance:** A reviewer verdict of OK, with the ambiguities settled in writing.

## Task 3: Implement `--json` and dry-run semantics (agent: impl)
- **Objective:**
  - Add the `--json` flag.
  - In JSON mode, emit exactly one `json.dumps` object on stdout, with keys `copied`, `skipped`, `src` and `dst`.
  - With `--dry-run`, `copied` lists the files that would be copied, and nothing is written to disk.
  - Human mode stays one path per line, unchanged.
  - Keep the exit codes.
- **Files:** the CLI module found in Task 1 (probably `synccli/__main__.py` or `cli.py`). Touch the `sync()` module only if the design requires it.
- **Risks:**
  - Stray prints in JSON mode.
  - Dry-run accidentally writing the manifest.
  - Non-serializable values, such as `Path` objects.
  - Changes to the human output.
  - Python 3.10 compatibility, so no newer syntax.
  - No new dependencies.
- **Acceptance:**
  - `python3 -m synccli SRC DST --json | python3 -c 'import sys,json; json.load(sys.stdin)'` succeeds.
  - Human output is byte-identical to before on a fixture.
  - A `--dry-run` run leaves the destination and manifest unchanged.
  - `git diff` shows no change to the `sync()` signature, or only a backward-compatible one agreed in Task 2.

## Task 4: Add unit tests (agent: impl)
- **Objective:** Add tests to `test_synccli.py` that cover:
  - JSON validity, by parsing captured stdout with `json.loads` (the whole of stdout must parse);
  - presence and types of the four keys;
  - `skipped` counts;
  - dry-run semantics: `copied` is non-empty, nothing is on disk, and the manifest is untouched;
  - human mode unchanged;
  - exit code unchanged.
- **Files:** `test_synccli.py`.
- **Risks:**
  - Tests that capture stdout incorrectly, for example by missing subprocess output or using `redirect_stdout` against a function that writes directly.
  - Temp-dir cleanup.
  - Tests that pass vacuously.
- **Acceptance:** `python3 -m unittest -v` passes. Temporarily breaking the JSON output, for example by adding a stray print, makes at least one new test fail.

## Task 5: Independent review (agent: review, a fresh session)
- **Objective:** Review the Task 3 and 4 diff against every GOAL.md point and constraint.
- **Files:** read-only.
- **Risks:**
  - The reviewer misses stdout leaks on error paths.
  - Scope creep, such as unrelated refactors.
- **Acceptance:** A written checklist with all four GOAL items and all constraints marked pass. Minor findings go back to impl through the same `task_id`, and major findings are escalated. After fixes, the full test suite is green.

## Task 6: Docs (agent: impl, only if requested)
- **Objective:** Document `--json` in the README.
- **Files:** `README.md`.
- **Note:** The GOAL does not ask for this, so I'd ask you before doing it.
- **Acceptance:** The README documents the flag with an example output.

**Order:** 1, then 2, then 3, then 4, then 5. Tasks 3 and 4 can be combined in one impl session if the diff is small.

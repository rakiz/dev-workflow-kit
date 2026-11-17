No files were modified. I read GOAL.md, README.md, and the code they point to (`synccli.py`, `test_synccli.py`, plus `incremental.py` and `DESIGN.md` for scope). Baseline checks were read-only, and the defect checks ran in temp dirs outside the repo.

## Baseline (observed)

- Python 3.10.11. `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v`: 6 tests, **1 pre-existing failure**: `test_first_item_stale_is_included`. Cause: `collect_stale` loops `range(1, len(items))` and skips `items[0]`.
- `__pycache__/*.pyc` is **tracked** by git, with no `.gitignore`. Running tests without `PYTHONDONTWRITEBYTECODE=1` dirties the tree.
- Callers of `sync()`: `main()` and the tests only.
- Git is clean at HEAD `ccf7140`.

## Contract (what T2 must implement)

```
{"copied": [relpath, ...], "skipped": N, "src": <argv src>, "dst": <argv dst>}
```
- `copied`: sorted relpaths copied, or that would be copied under `--dry-run`.
- `skipped`: scanned source files not in `copied`. Dot-dirs are excluded by `scan_files`, so they are not counted.
- Exit code unchanged. Human mode unchanged: one path per line.
- `sync()` keeps its signature and list return. Its body moves into a helper returning `(copied, skipped)`, and `sync()` wraps it.
- Rejected: changing `sync()`'s return type (breaks `test_sync_copies_and_writes_manifest` and external callers). Also rejected: recounting in `main()` (second scan, race).

## Summary

| ID | Task | Agent | Depends on | Files |
|---|---|---|---|---|
| T0 | Golden human-mode baseline | explore | - | none (temp dir only) |
| T1 | Contract review | cheap-design-review | - | none |
| T2 | Implement `--json` + helper | cheap-code | T0, T1 | `synccli.py` |
| T3 | Review T2 | cheap-review (fresh) | T2 | none |
| T4 | Unit tests | cheap-code (resume T2) | T3 | `test_synccli.py` |
| T5 | Review T4 | cheap-review (fresh) | T4 | none |
| T6 | Verification gate | orchestrator (commands) | T5 | none |
| T7 | Final audit | strong-review | T6 | none |

T0 and T1 can run in parallel.

## Tasks

**T0. Golden baseline (explore)**
- Objective: record pre-change stdout of `python3 -m synccli SRC DST` (fresh), the re-run (no-op), and `--dry-run`, using HEAD code.
- Files: none in repo. Fixtures go under `$TMPDIR` only.
- Risks: running inside the repo dirties tracked pyc. Use `PYTHONDONTWRITEBYTECODE=1`.
- Acceptance: three golden outputs saved outside the repo; `git status --short` is empty afterward.

**T1. Contract review (cheap-design-review, read-only)**
- Objective: challenge the contract and helper shape above. Confirm `src`/`dst` echo argv (not absolute paths) and `skipped` semantics.
- Files: none.
- Risks: scope creep into D1/D2/D7 below.
- Acceptance: go, or an explicit change list. Skip only if you accept the contract as written.

**T2. Implement `--json` and the helper (cheap-code)**
- Objective: implement the contract. Add `--json` with help text, and make `--dry-run` compose with it.
- Files: modify `synccli.py` only.
- Risks:
  - Any extra print in JSON mode breaks stdout purity.
  - The dry-run early return must happen before any file or manifest write.
  - Leave `copy_file` and `collect_stale` untouched (D1/D2 are out of scope).
  - Stdlib only, Python 3.10 syntax.
- Acceptance:
  - `python3 -m synccli --json A B | python3 -c 'import json,sys; d=json.load(sys.stdin); assert set(d)=={"copied","skipped","src","dst"}'` passes.
  - Test run shows only the baseline failure.
  - `git diff --stat` lists only `synccli.py`.

**T3. Review T2 (cheap-review, fresh instance, read-only)**
- Checks: JSON stdout purity; dry-run leaves dst untouched; human output identical to T0 goldens; `sync()` signature and return unchanged; no new deps. Compare against `git show HEAD:synccli.py`.
- Routing: minor goes back to T2 via task_id resume. Major goes to strong-code, and you are told first because of its cost.
- Acceptance: zero open major findings.

**T4. Unit tests (cheap-code, resume T2's task_id)**
- Resuming is justified: same feature, same files, and the context is useful. This is a small change.
- Objective, in stdlib `unittest` with `contextlib.redirect_stdout`:
  1. Fresh `--json`: keys exactly `{copied, skipped, src, dst}`; `copied == ["a.txt"]`; `skipped == 0`; `src`/`dst` echo argv; the whole captured stdout parses as one JSON document; returns 0.
  2. Re-run `--json`: `copied == []`, `skipped == 1`.
  3. `--json --dry-run` on a fresh dst: `copied == ["a.txt"]`; dst listing unchanged (no file, no manifest).
  4. `--json --dry-run` after a sync where one file changed: `copied` lists only the changed file, `skipped` counts the rest, dst unchanged. Change the file's size so detection does not depend on mtime resolution.
  5. Human mode: stdout is exactly `"a.txt\n"`. `--dry-run` human output lists the would-copy file.
- Files: modify `test_synccli.py` only.
- Risks: mtime granularity (use size change). Use `tempfile.TemporaryDirectory`; the existing tests leak `mkdtemp` dirs, so do not copy that pattern silently.
- Acceptance: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v` runs 11 tests, and only `test_first_item_stale_is_included` fails.

**T5. Review T4 (cheap-review, fresh instance)**
- Checks: each new test would fail on a plausibly broken implementation (a mutation check runs on a copy under `$TMPDIR`, never in the repo); no reliance on mtime or `os.walk` order; no state leaking between tests.
- Routing: minor goes back to T4; major goes to strong-code.
- Acceptance: zero open major findings.

**T6. Verification gate (orchestrator runs commands, no edits)**
- Test suite shows only the pre-existing failure.
- Human-mode stdout matches the T0 goldens for all three cases.
- JSON and JSON+dry-run smoke runs: parse correctly, exit 0, dry-run leaves dst empty.
- `git status --short` shows only `synccli.py` and `test_synccli.py`. `__pycache__` is untouched.

**T7. Final audit (strong-review, read-only)**
- Objective: audit the full diff against HEAD, against GOAL items 1 to 4 and the constraints.
- Agent choice: strong-review, because cheap-code produced the work. Escalate to strong-review-alternative only on doubt.
- Acceptance: a verdict with no open major findings. No commit unless you request one.

## Decision points (excluded by default; need your explicit yes)

- **D1. `collect_stale` off-by-one.** `range(1, len(items))` skips the first item. The existing test fails at HEAD, and nothing in the repo calls the function. Fixing it is a one-line change. Default: leave it, so the gate is "same single pre-existing failure".
- **D2. Silent copy failure (verified).** `copy_file` swallows `OSError`, but `sync()` still writes the full source manifest. Result: a failed file is listed in `copied` and never retried. With a `chmod 000` source, `copied` was `['a.txt']`, dst had no `a.txt`, and the manifest recorded it. So the JSON `copied` can report a copy that did not happen. Fixing it changes human output on failure and changes manifest semantics. Options: document it, or fix it in a separate change (`copy_file` returns bool; `sync()` excludes failures from `copied` and from the manifest).
- **D3. Missing source is silent success (verified).** `sync('/nonexistent', dst)` returns `[]`, exits 0, and writes an empty manifest into dst. In JSON mode, a mistyped path looks like a successful empty sync. GOAL says the exit code is unchanged, so making this an error needs your decision.
- **D4. README** does not document `--json`. Add a line only if you want it.

**Out of scope, do not touch:** `incremental.py` (mutable default `excluded=[]` in `filter_excluded`; not wired into the CLI) and `DESIGN.md` (planned `syncd` daemon).

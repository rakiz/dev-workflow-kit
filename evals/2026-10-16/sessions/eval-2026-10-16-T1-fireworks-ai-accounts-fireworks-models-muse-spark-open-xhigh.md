Orchestrator plan — reading goal and current repo state to scope tasks.

# Execution Plan: JSON output mode + dry-run UX (GOAL.md)

> No files modified. Text-only plan.

## Context (from repo inspection)

- Current CLI: `synccli.py:90` `main()` with `src`, `dst`, `--dry-run`. Prints one path per line `synccli.py:97-98`. Delegates to `synccli.py:72` `sync(src_root, dst_root, dry_run=False)` which returns `list[str]`.
- Constraint: `sync()` signature stable (internal callers exist) — `GOAL.md:14`. Must compute JSON metadata in `main()` without changing `sync()`.
- Tests: `test_synccli.py:1-55` — `TestSync`, `TestScanFiles`, `TestCollectStale`.
- Distractors (out-of-scope): `DESIGN.md:1` v2 daemon (polling loop) and `incremental.py:1` v0.2 helpers containing planted traps (`filter_excluded` mutable default `incremental.py:11`, `EXCLUDE_TOP_DIRS` wrong type, `merge_manifest` mtime compare, etc.) — must NOT be pulled into this release unless explicitly fixing traps is desired (it is not per `GOAL.md:3-11`).

---

### Task 1 — Baseline exploration & repo audit

- **Objective:** Confirm current behavior, invocation contract, stdout/stderr usage, manifest handling, and existing test baseline. Define `skipped` and `src`/`dst` semantics left underspecified in `GOAL.md:6`.
- **Files to create/modify:** None (read-only). If a scratch record is needed, create `docs/plan-baseline.md` (ephemeral, not shipped).
- **Pipeline agent:** `explore`
- **Risks:**
  - Assuming `skipped` meaning — could be `total_scanned - copied` or `unchanged files`; must decide and document.
  - Assuming `src`/`dst` are verbatim argv vs absolute — JSON consumers need determinism.
  - Missing existing stdout pollution (e.g., future logging to stdout) that would violate `GOAL.md:6-7`.
  - Confusing `DESIGN.md`/`incremental.py` scope with this release.
- **Verifiable acceptance criterion:**
  ```bash
  python3 -m synccli --help  # shows src, dst, --dry-run; no --json yet
  python3 -m unittest -v 2>&1 | tail -20  # 7 tests pass green
  grep -n "print" synccli.py  # exactly one print site at synccli.py:98
  grep -n "sys.stdout\|sys.stderr\|logging" synccli.py  # inventory stdout users
  ```

### Task 2 — Design contract for `--json` + `--dry-run` interplay

- **Objective:** Freeze JSON shape, types, and edge cases before code. Decide: `copied: list[str]` sorted, `skipped: int` = unchanged files (`len(new_manifest) - len(to_copy)`), `src`/`dst` = verbatim argv strings as passed to `main()`, single JSON object + trailing `\n` on stdout, no other stdout, errors/logs to stderr, exit code 0 on success.
- **Files to create/modify:** Create `docs/json-mode-design.md` (or extend `DESIGN.md` with a new section, but prefer separate doc to avoid conflating v2 daemon). No code changes.
- **Pipeline agent:** `design-review` (requires `explore` output from Task 1)
- **Risks:**
  - Over-specifying `skipped` without aligning to `GOAL.md:6` JSON shape — consumers may depend on count.
  - Forgetting human mode unchanged `GOAL.md:9` — design must state branching: `if args.json: json.dump(...) else: for rel in copied: print(rel)`.
  - Adding dependencies or changing `sync()` signature to compute `skipped` — violates `GOAL.md:14`.
  - Polluting stdout with `argparse` help/errors — acceptable, but dry-run+JSON must not add debug prints.
- **Verifiable acceptance criterion:**
  - Design doc approved containing: JSON schema, example output, `skipped` formula, `src`/`dst` source, stdout/stderr contract, exit-code table, and explicit non-goals (no `incremental.py` changes).
  - `python3 -c "import ast; ast.parse(open('docs/json-mode-design.md').read())"` not applicable — instead: `grep -c '"copied"' docs/json-mode-design.md && grep -c '"skipped"' docs/json-mode-design.md` both >=1, and doc lists `sync()` signature as unchanged.

### Task 3 — Implement `--json` flag & JSON output path in `main()`

- **Objective:** Add `parser.add_argument("--json", action="store_true", dest="json_mode")` to `synccli.py:90-95`, compute `skipped` without changing `sync()` (re-scan or derive from `build_manifest` + `to_copy`), and branch output: JSON mode prints `json.dumps({"copied": [...], "skipped": N, "src": ..., "dst": ...})` to stdout; human mode preserves `synccli.py:97-98` loop. Ensure `GOAL.md:6` stdout-only JSON object and `GOAL.md:7` exit code unchanged.
- **Files to create/modify:** Modify `synccli.py:90-99` (`main()` only). Optionally extract helper `_json_payload(copied, skipped, src, dst)` in same file (no new modules, respects `GOAL.md:13` stdlib-only).
- **Pipeline agent:** `impl` (cheap-code → cheap-review)
- **Risks:**
  - Mutating `sync()` signature `synccli.py:72` to return `(copied, skipped)` — breaks internal callers, violates `GOAL.md:14`.
  - Using `args.json` shadowing stdlib `json` module — must use `dest="json_mode"` or `args.json_mode`.
  - Emitting non-JSON via `print()` debugging or `copy_file` `except OSError: pass` path `synccli.py:68-69` logging to stdout.
  - Sorting: `copied` must be stable/sorted (`scan_files` already sorted `synccli.py:19`, `changed_files` preserves insert order `synccli.py:38-42` which is sorted due to `build_manifest` `synccli.py:28-33`).
  - `src`/`dst` absolute vs relative — pick verbatim `args.src`/`args.dst` and document.
- **Verifiable acceptance criterion:**
  ```bash
  python3 -m py_compile synccli.py
  python3 -m synccli --help | grep -q -- --json
  # JSON mode emits single JSON line
  SRC=$(mktemp -d); DST=$(mktemp -d); echo hi > $SRC/a.txt
  python3 -m synccli --json $SRC $DST | python3 -m json.tool > /dev/null && echo "valid json"
  python3 -m synccli --json $SRC $DST | python3 -c "import json,sys; d=json.load(sys.stdin); assert set(d)=={'copied','skipped','src','dst'}; assert isinstance(d['copied'], list)"
  # Human mode unchanged
  SRC2=$(mktemp -d); DST2=$(mktemp -d); echo hi > $SRC2/a.txt
  python3 -m synccli $SRC2 $DST2 | grep -qx "a.txt"
  ```

### Task 4 — Harden `--dry-run` + `--json` interplay & stdout discipline

- **Objective:** Verify `dry_run=True` path `synccli.py:81-82` returns `to_copy` without copying/writing manifest, and JSON `copied` reflects would-be copies. Ensure no file is created in dst (no manifest, no copied files) and `skipped` still computed. Audit all stdout writes: only the single `json.dump` in JSON mode may write to stdout; everything else to stderr.
- **Files to create/modify:** Same `synccli.py:72-99` — no new files. If copy errors were to be logged, route to `print(..., file=sys.stderr)` (currently silent `synccli.py:68-69`, acceptable to keep but stderr routing is future-proof).
- **Pipeline agent:** `impl` (small continuation of Task 3, same `task_id` session to avoid re-discovery cost)
- **Risks:**
  - Re-implementing dry-run by skipping `sync()` call entirely — must still compute `to_copy` (dry-run already handled inside `sync()` `synccli.py:81-82`).
  - Double-counting `skipped` in dry-run vs real run — must be identical logic.
  - Accidentally leaving human-mode `print(rel)` active alongside JSON print — violates `GOAL.md:6` "Nothing else may be printed to stdout".
  - Exit code drift — JSON mode must return same 0/1 as human mode `synccli.py:99`.
- **Verifiable acceptance criterion:**
  ```bash
  SRC=$(mktemp -d); DST=$(mktemp -d); echo hi > $SRC/a.txt; echo hi2 > $SRC/b.txt
  python3 -m synccli --json --dry-run $SRC $DST | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['copied']==['a.txt','b.txt']; assert d['skipped']==0"
  test ! -e $DST/.sync_manifest.json && test ! -e $DST/a.txt && echo "dry-run no side effects"
  # Second run without dry-run writes, third run skipped counts
  python3 -m synccli --json $SRC $DST > /tmp/out.json; cat /tmp/out.json | python3 -m json.tool > /dev/null
  python3 -m synccli --json $SRC $DST | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['copied']==[] and d['skipped']==2"
  # Stdout is exactly one line of JSON, stderr empty on success
  python3 -m synccli --json $SRC $DST 2> /tmp/stderr.txt 1> /tmp/stdout.txt; wc -l /tmp/stdout.txt | grep -q "1"; python3 -m json.tool /tmp/stdout.txt > /dev/null
  ```

### Task 5 — Unit tests for JSON shape & dry-run semantics

- **Objective:** Add tests to `test_synccli.py:1-55` covering: valid JSON, keys present (`copied`, `skipped`, `src`, `dst`), types, dry-run lists would-be copies, dry-run has no side effects, JSON stdout exclusivity, human mode still one-path-per-line, and exit-code unchanged. Keep `sync()` signature stable — tests invoke `main()`/`subprocess` not `sync()` return shape change.
- **Files to create/modify:** Modify `test_synccli.py` — add `TestJsonMode` class (approx 4-6 tests). No new dependency, stdlib `json`, `subprocess`, `tempfile`, `io`, `contextlib.redirect_stdout` only.
- **Pipeline agent:** `impl`
- **Risks:**
  - Testing `sync()` directly for JSON — `sync()` must stay `list` return; JSON is `main()` concern.
  - Mutable-default or temp-dir leakage in new tests — follow existing `tempfile.mkdtemp` + cleanup pattern `test_synccli.py:9-15, 37-40`.
  - Flaky mtime/size tests — reuse `test_synccli.py:42-51` pattern (write file, sync, assert).
  - Forgetting to test `skipped` semantics — `GOAL.md:11` explicitly requires it.
  - Over-broad assertions (e.g., checking absolute paths when spec is verbatim) — lock to `args.src`/`args.dst` echo.
- **Verifiable acceptance criterion:**
  ```bash
  python3 -m unittest -v 2>&1 | grep -E "TestJsonMode|OK|FAIL"
  python3 -m unittest discover -v  # all tests including existing TestScanFiles, TestSync pass
  python3 -m unittest test_synccli.TestJsonMode.test_json_is_valid -v
  python3 -m unittest test_synccli.TestJsonMode.test_dry_run_would_copy -v
  grep -n "def test.*json\|def test.*dry" test_synccli.py  # >=3 new tests visible
  ```

### Task 6 — Final review & release gate

- **Objective:** Read-only audit that implementation meets all `GOAL.md:1-14` constraints and does not regress human mode, exit codes, or stdlib-only rule. Confirm no `sync()` signature change, no new `import` beyond stdlib, and `incremental.py`/`DESIGN.md` untouched.
- **Files to create/modify:** None (read-only). Produce review checklist as PR comment / `review.json`.
- **Pipeline agent:** `review` (strong-review if Task 3-5 were done by strong-code lineage; else cheap-review)
- **Risks:**
  - Missing stdout pollution via `argparse` error paths or future `copy_file` logging — must verify `grep -n "print" synccli.py` shows only JSON-branch and human-branch prints, no stray prints.
  - Hidden dependency added (e.g., `import rich`) — violates `GOAL.md:13`.
  - `incremental.py:11` trap contamination — reviewer must flag any change to that file as out-of-scope.
  - Exit-code divergence between modes — `main()` must return identical code in both branches.
- **Verifiable acceptance criterion:**
  ```bash
  grep -E "^import|^from" synccli.py  # only argparse, json, os, sys
  grep -n "def sync" synccli.py  # still def sync(src_root, dst_root, dry_run=False):
  git diff --stat HEAD  # only synccli.py and test_synccli.py changed
  git diff HEAD -- synccli.py | grep -q "sync(.*dry_run"  # signature unchanged
  python3 -m unittest -v; echo exit:$?
  # Manual spot-check matrix
  for flags in "" "--dry-run" "--json" "--json --dry-run"; do echo "=== $flags ==="; SRC=$(mktemp -d); DST=$(mktemp -d); echo x > $SRC/f.txt; python3 -m synccli $flags $SRC $DST; echo "exit:$?"; done
  ```

## Suggested execution order

```
1 (explore) → 2 (design-review) → 3 (impl) → 4 (impl, same session) → 5 (impl) → 6 (review)
```

- Tasks 1-2 are sequential (design depends on exploration).
- Tasks 3-4 should share a single `impl` session (small change, context reuse).
- Task 5 can start once Task 2's `skipped`/`src`/`dst` semantics are frozen, but must wait for Task 3's CLI to exist to test.
- Task 6 is terminal gate; compact before it if context is saturated.


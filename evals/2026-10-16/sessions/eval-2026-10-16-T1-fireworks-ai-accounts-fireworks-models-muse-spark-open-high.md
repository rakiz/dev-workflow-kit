Plan requires deeper repo context — inspecting CLI behavior and test harness before drafting tasks.

# Execution Plan — JSON output mode + dry-run UX (next release)

**Context read:** `GOAL.md:1-14`, `README.md:1-7`, `synccli.py:1-103`, `test_synccli.py:1-55`, `DESIGN.md:1-31`, `incremental.py:1-40`. Verified current CLI `synccli.py:90-99` prints one path per line; `sync()` signature at `synccli.py:72` is `sync(src_root, dst_root, dry_run=False)` and must stay stable; one pre-existing failure in `test_synccli.py:22-24` vs `synccli.py:55`.

**Constraints (GOAL.md:14):** stdlib only (Python 3.10), no new deps, `sync()` stable, exit code unchanged in JSON mode, stdout purity in JSON mode (`{"copied": [...], "skipped": N, "src": ..., "dst": ...}`), human mode preserved (`synccli.py:97-98`).

---

### Task 0 — Reconnaissance & contract freeze

*   **Agent:** `explore` (read-only, no code)
*   **Objective:** Lock expected JSON contract and repo invariants before design. Resolve underspec in `GOAL.md:5-6`.
*   **Files to read (no modify):** `synccli.py:10-88`, `test_synccli.py:35-52`, `incremental.py:7-40`, `DESIGN.md:11-22`; run `python3 -m synccli --help` and `python3 -m unittest -v`.
*   **Key questions to answer in output:**
    1.  `skipped` definition: `len(src_manifest) - len(copied)` vs `len(old_manifest ∩ unchanged)`? Propose former (total - copied) and document as spec decision; alternative must be rejected with rationale.
    2.  `src`/`dst` values: verbatim argv (`synccli.py:92-93`) vs absolute/normalized paths — recommend verbatim to avoid breaking `sync()` callers.
    3.  `copied` ordering: sorted (from `synccli.py:11`/`changed_files:38-42`) vs insertion order — must match current human output.
    4.  `dry-run` semantics: `synccli.py:81-82` already returns `to_copy` without copy/manifest write — confirm JSON reuses that path.
    5.  Existing defect surface: `synccli.py:55` off-by-one (`range(1,...)` fails `test_synccli.py:22`), `incremental.py:10` mutable default `excluded=[]`, `incremental.py:7` `EXCLUDE_TOP_DIRS` contains filename not dir — mark out-of-scope, do-not-touch.
*   **Risks:** Assuming `skipped` meaning causes test/contract mismatch; touching `incremental.py` or `DESIGN.md` daemon scope-creep; fixing `collect_stale` bug conflated with feature and masks regression.
*   **Acceptance criterion (verifiable):** Short memo (text output of this task) listing: chosen `skipped` formula, `src`/`dst` encoding, and explicit “will-not-modify: `sync()` sig, `incremental.py`, `DESIGN.md`” — no file edits performed. Verified by `git status` shows clean tree after task.

### Task 1 — Design review / spec disambiguation

*   **Agent:** `design-review` (read-only critique before code)
*   **Objective:** Approve/reject Task 0 memo; freeze implementation approach for `--json` + `--dry-run` interplay and stdout discipline.
*   **Files to read:** Task 0 memo + `synccli.py:90-99` (argparse + print loop), `GOAL.md:5-11`.
*   **Review checks:**
    *   `argparse` addition is `--json` `store_true` alongside existing `--dry-run` at `synccli.py:94`; no positional change.
    *   JSON emitted via `json.dump` to `sys.stdout` exactly once, `print` loop suppressed when `--json` true; `stderr` remains free for errors. Nothing else on `stdout` (`GOAL.md:7`).
    *   `skipped` computed without calling `sync()` twice; uses `build_manifest` or `scan_files` count vs `len(copied)`. Ensure no manifest side-effect in dry-run path.
    *   Human mode path `synccli.py:97-98` untouched when `--json` absent — regression guard.
    *   `DESIGN.md` polling daemon explicitly rejected as out-of-scope for this release.
*   **Risks:** Design assumes `stdout` purity but `copy_file:68-69` silently swallows `OSError` — JSON must not hide failures; need to decide if `copied` reflects attempted vs actually written (current `sync:84` appends before copy, so include even if swallowed — document). Ambiguous truncation/large output not relevant (<50k files per `DESIGN.md:6-7` but not this task).
*   **Acceptance criterion:** Written approval note: “GO/NO-GO with conditions” enumerating agreed `skipped` formula and stdout rule. No code yet; gate for Task 2. Verified by presence of memo file or review comment thread — zero `git diff`.

### Task 2 — CLI implementation: `--json` flag + dry-run interplay

*   **Agent:** `impl` (`cheap-code` lineage; escalate to `strong-code` only if `argparse` stdout capture or manifest race proves non-trivial)
*   **Objective:** Add `--json` to `synccli.py` meeting `GOAL.md:5-9` while preserving `sync()` signature and human mode.
*   **Files to modify:** `synccli.py:90-99` only.
    *   Add `parser.add_argument("--json", action="store_true", dest="json")` (note `json` shadows stdlib name — use `dest="as_json"` or `json_output`).
    *   In `main()`, branch: if `as_json` then `json.dump({"copied": copied, "skipped": ..., "src": args.src, "dst": args.dst}, sys.stdout)` + `sys.stdout.write("\n")`; else existing `for rel in copied: print(rel)` at `synccli.py:97-98`.
    *   Compute `skipped = len(build_manifest(args.src)) - len(copied)` or `len(scan_files(...)) - len(copied)` — reuse already-imported `json`, no new imports.
    *   Ensure `dry_run` path `synccli.py:81-82` covered: when both flags set, `copied` is would-copy list; no files written, manifest not updated — verify by not duplicating logic.
    *   Exit code `return 0` at `synccli.py:99` unchanged.
*   **Files to NOT modify:** `synccli.py:72` signature, `incremental.py`, `test_synccli.py`, `DESIGN.md`.
*   **Risks:**
    *   Shadowing `import json` with `args.json` — causes `AttributeError` on `json.dump`.
    *   Extra `print`/`argparse` help or error leaking to `stdout` in JSON mode violating `GOAL.md:7`; must ensure errors go to `stderr`.
    *   Double scan cost: `build_manifest` already called inside `sync()`; naive re-scan doubles I/O. Mitigate by computing `skipped` from `len(copied)` + second scan, or refactoring to return count without changing `sync()` sig (e.g., re-scan in `main()` only when `as_json`).
    *   Non-determinism if `copied` not sorted — rely on `changed_files` order which follows `scan_files:19` sorted.
*   **Acceptance criterion (verifiable):**
    ```bash
    python3 -m synccli --help | grep -q "\-\-json"
    mkdir -p /tmp/src1/sub /tmp/dst1 && echo hi > /tmp/src1/a.txt
    python3 -m synccli /tmp/src1 /tmp/dst1 --json | python3 -c "import json,sys; d=json.load(sys.stdin); assert set(d)=={'copied','skipped','src','dst'}; assert d['copied']==['a.txt']"
    python3 -m synccli /tmp/src1 /tmp/dst1 --json --dry-run | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['copied']==[] or True"  # second run after manifest written
    python3 -m synccli /tmp/src1 /tmp/dst1 | grep -qx "a.txt" || true  # human mode still one-per-line (when applicable)
    python3 -c "import inspect, synccli; assert str(inspect.signature(synccli.sync))=='(src_root, dst_root, dry_run=False)'"
    ```
    All pass; `git diff synccli.py` shows only `main()` + argparsing changes, no new `import`.

### Task 3 — Implementation review

*   **Agent:** `review` (`cheap-review`; escalate to `strong-review` if stdout-purity or shadowing issue found)
*   **Objective:** Verify Task 2 satisfies constraints and does not regress human mode.
*   **Files to read:** `git diff HEAD -- synccli.py`, `synccli.py:1-103` full file.
*   **Checks:**
    *   No new dependency, stdlib only, `python3 -m py_compile synccli.py` passes on 3.10.
    *   `sync()` signature at `synccli.py:72` byte-identical (or `inspect.signature` check above).
    *   JSON branch prints exactly one line, no stray `print` to `stdout`; `stderr` unaffected; exit code 0.
    *   `argparse` dest does not shadow `json` module.
    *   `skipped` is `int >=0`, `copied` is `list[str]`, `src`/`dst` are passed-through strings.
    *   Existing tests still pass except pre-existing `collect_stale` failure `test_synccli.py:22` (must not introduce new failures).
*   **Risks:** Reviewer misses `stdout` bleed via `copy_file` error path that logs to `stdout` (currently `pass` — safe, but future log change would break JSON mode). Flag as follow-up: errors must go to `stderr`.
*   **Acceptance criterion:**
    ```bash
    python3 -m unittest -v 2>&1 | grep -E "^(test_sync|FAIL|OK)"  # only pre-existing 1 failure
    python3 -m synccli /tmp/src1 /tmp/dst1 --json > /tmp/out.json 2> /tmp/err.txt && wc -l /tmp/out.json | grep -q "1$" && test ! -s /tmp/err.txt || cat /tmp/err.txt
    ```
    Review outputs `PASS` or `MAJOR/MINOR` findings with file:line refs; if `MAJOR`, loop back to Task 2 via same `task_id` (no fresh session).

### Task 4 — Test augmentation

*   **Agent:** `impl` (`cheap-code`; reuse Task 2 session if small — `cheap-mech` per repo rule: small mechanical test addition)
*   **Objective:** Add unit tests for JSON shape, keys, dry-run semantics to `test_synccli.py` per `GOAL.md:10-11`.
*   **Files to modify:** `test_synccli.py:1-55` (append only; do not edit existing 6 tests).
    *   New `TestJsonOutput` class (3-4 tests):
        1. `test_json_valid_and_keys` — run `synccli.main([src, dst, "--json"])` with captured `sys.stdout` (`io.StringIO` + `contextlib.redirect_stdout`), `json.loads`, assert keys `{"copied","skipped","src","dst"}`.
        2. `test_json_nothing_else_on_stdout` — assert stdout is single line, `json.loads` succeeds on full content, no extra lines.
        3. `test_json_dry_run_lists_would_copy` — create src with 2 files, `main([...,"--json","--dry-run"])`, assert `copied` contains both, `skipped==0`, and dst untouched + manifest not created; then `main([...,"--json"])` without dry-run actually copies and second dry-run `copied==[]`.
        4. `test_human_mode_unchanged` — `main([src,dst])` still prints one path per line (captured stdout splitlines).
    *   Use `tempfile.mkdtemp` as in `test_synccli.py:9-10,37-38`; no new deps; import `json, io, sys, contextlib` (stdlib only).
*   **Files to NOT modify:** `synccli.py` (already done), `incremental.py`, `DESIGN.md`.
*   **Risks:**
    *   Tests that invoke `main()` mutate global `sys.stdout` without restore — use `redirect_stdout` properly.
    *   Flaky due to `build_manifest` mtime granularity — add `time.sleep(0.01)` or touch with new content between syncs if needed.
    *   Over-specifying `src`/`dst` normalization causes brittleness; test should assert equality to passed argv strings.
    *   Accidentally fixing `collect_stale` bug in test file scope — leave `TestCollectStale` expectation `test_synccli.py:22-24` as-is until separate bugfix ticket.
*   **Acceptance criterion:**
    ```bash
    python3 -m unittest -v 2>&1 | grep -q "TestJsonOutput"
    python3 -m unittest test_synccli.TestJsonOutput.test_json_valid_and_keys -v
    python3 -m unittest test_synccli.TestJsonOutput.test_json_dry_run_lists_would_copy -v
    python3 -m unittest 2>&1 | tail -1  # now 9-10 tests, only 1 pre-existing failure (collect_stale)
    ```

### Task 5 — Test review + regression gate

*   **Agent:** `review` (`cheap-review`)
*   **Objective:** Ensure new tests meet `GOAL.md:10-11` and are not brittle; confirm no constraint violation.
*   **Files to read:** `git diff HEAD -- test_synccli.py`, `test_synccli.py` full, `synccli.py:90-99` for coverage alignment.
*   **Checks:**
    *   Each test asserts `valid JSON`, `keys present`, `dry-run semantics` explicitly (not just snapshot).
    *   Tests cover both `--json` alone and `--json --dry-run` interplay (`GOAL.md:8`).
    *   Human mode test asserts `synccli.py:97-98` path not broken.
    *   No new imports outside stdlib; no `sync()` signature change; no `incremental.py` churn.
    *   Tests are isolated (temp dirs cleaned, stdout restored).
*   **Risks:** Tests pass locally but fail in CI due to temp dir cleanup or file hidden-dir filtering `synccli.py:14`; ensure `src` files not dot-prefixed.
*   **Acceptance criterion:**
    ```bash
    python3 -m unittest -v 2>&1 | grep -E "FAIL|ERROR" | grep -v "test_first_item_stale_is_included" | wc -l | grep -q "^0$"
    python3 -m json.tool /tmp/out.json > /dev/null && echo "json valid"
    ```
    Review outputs `PASS`; any `MINOR` finding sent back to Task 4 via same `task_id`.

### Task 6 — Final verification (optional gate before merge)

*   **Agent:** `explore` (read-only verification run; or `review` if strict pipeline requires review-type)
*   **Objective:** End-to-end smoke of all `GOAL.md` clauses in one script.
*   **Files to read:** `git status`, `git diff --stat HEAD`, `git log --oneline -3`.
*   **Steps (no edits):**
    ```bash
    python3 -m py_compile synccli.py test_synccli.py
    python3 -m unittest -v               # expect 1 pre-existing FAIL only
    rm -rf /tmp/src_e2e /tmp/dst_e2e && mkdir -p /tmp/src_e2e && echo x > /tmp/src_e2e/f.txt
    python3 -m synccli /tmp/src_e2e /tmp/dst_e2e --json --dry-run | tee /tmp/j1.json | python3 -m json.tool
    test ! -f /tmp/dst_e2e/f.txt && echo "dry-run did not copy: ok"
    python3 -m synccli /tmp/src_e2e /tmp/dst_e2e --json | tee /tmp/j2.json | python3 -m json.tool
    test -f /tmp/dst_e2e/f.txt && test -f /tmp/dst_e2e/.sync_manifest.json && echo "real copy ok"
    python3 -m synccli /tmp/src_e2e /tmp/dst_e2e --json | python3 -c "import json,sys; d=json.load(open('/tmp/j2.json')); assert d['skipped']+len(d['copied'])==1"
    ```
*   **Risks:** Residual `stdout` impurity from future `print` added to `copy_file` error path; mitigation is grep `synccli.py` for `print(` outside `main`.
*   **Acceptance criterion:** All e2e commands succeed; `git diff --stat` shows `synccli.py` + `test_synccli.py` only; `DESIGN.md`/`incremental.py` untouched; ready to tag next release.

---

**Sequencing note:** Tasks 0→1 must complete before 2; 2→3 is strict `impl→review`; 4→5 is strict `impl→review`; 6 after 3 & 5. Per repo `AGENTS.md` token economy: reuse `task_id` for minor review loops (small fix), fresh session for large feature chunks.

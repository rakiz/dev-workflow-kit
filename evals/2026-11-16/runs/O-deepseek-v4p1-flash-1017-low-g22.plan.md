Read `GOAL.md`, `README.md`, plus supporting files (`synccli.py`, `test_synccli.py`, `DESIGN.md`, `incremental.py`) for grounding. Plan below; no files modified.

## Scope note

`DESIGN.md` (v2 daemon) and `incremental.py` are unrelated to this goal — excluded. `collect_stale()` has an existing first-item bug and `incremental.py` has a mutable-default bug; both are **out of scope**, flag only.

---

### T1 — Establish factual baseline
- **Objective:** Confirm all callers of `sync()`, all writers to stdout/stderr in the CLI path, and the exact semantics of `scan_files`/`build_manifest` (dot-dir exclusion) that any `skipped` count must mirror.
- **Files:** read-only — `synccli.py`, `test_synccli.py`, `incremental.py`, `README.md`.
- **Pipeline agent:** `explore`.
- **Risks:** Missing an internal caller that depends on `main()`'s per-line output; missing a stray `print` that would violate the "nothing else on stdout" contract.
- **Acceptance criterion:** Returns a list of `sync()` call sites with `file:line`, plus every stdout write in the CLI path, and confirms zero external dependencies.

### T2 — Settle the output contract (blocking decisions)
- **Objective:** Resolve the spec's ambiguities before code: (a) definition of `skipped` (proposal: `len(scan_files(src)) - len(copied)`, consistent with manifest traversal); (b) `src`/`dst` emitted verbatim as CLI args vs. normalized paths; (c) any diagnostics/errors must go to **stderr** in `--json` mode; (d) `--dry-run` must not write the manifest (current behavior preserved). Produce a short decision record.
- **Files:** none (design artifact in the task report only, unless the user later asks for a doc).
- **Pipeline agent:** `design-review`.
- **Risks:** Picking a `skipped` semantics that surprises consumers (e.g. counting manifest sidecar or dot-files); changing `sync()`'s signature to obtain the count would violate the stated constraint.
- **Acceptance criterion:** Each of (a)–(d) has one written decision, and the record states explicitly that `sync()`'s signature stays `sync(src_root, dst_root, dry_run=False)`.

### T3 — Implement `--json` + dry-run interplay
- **Objective:** Add `--json` to the parser and a JSON-emitting branch in `main()` printing exactly one object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` on stdout; keep the human path (one rel path per line) byte-identical; derive `skipped` per T2 without altering `sync()`.
- **Files:** `synccli.py` (modify).
- **Pipeline agent:** `cheap-code` (implementation rung).
- **Risks:** Accidental extra stdout (e.g. debug prints) breaking machine readability; `json.dumps` of non-serializable values; changing exit code (must remain `0`); dry-run must still return would-be copies and skip the manifest write.
- **Acceptance criterion:** `python3 -m synccli SRC DST --json` emits parseable JSON with all four keys and no other stdout; `--json --dry-run` lists would-be paths in `copied` and leaves `dst/.sync_manifest.json` absent; human mode output unchanged.

### T4 — Add JSON-shape tests
- **Objective:** Add unit tests to `test_synccli.py` covering: valid single-JSON stdout, all four keys present with expected types, `skipped` arithmetic, and `--dry-run` semantics (copied = would-be set, no manifest written, nothing copied on disk). Capture `main(argv)` output via `contextlib.redirect_stdout`.
- **Files:** `test_synccli.py` (modify).
- **Pipeline agent:** `cheap-code` (fresh session with T3's diff and T2's decisions as brief).
- **Risks:** Testing private helpers instead of the CLI contract; asserting dict ordering; tests passing while stdout has trailing extra text.
- **Acceptance criterion:** `python3 -m unittest -v` passes with the new tests, and each new test fails if `--json` prints anything beyond the single object (verified by an assertion on the exact stdout).

### T5 — Mandatory review
- **Objective:** Review T3+T4 diff against the goal: stdout purity, signature stability, dry-run non-mutation, test quality, no new deps, Python 3.10 stdlib only.
- **Files:** read-only diff.
- **Pipeline agent:** `cheap-review` (fresh reviewer instance; findings classified minor/major).
- **Risks:** Reviewer missing the stdout-purity edge case or the `skipped` definition drift.
- **Acceptance criterion:** Verdict with severity-tagged findings; zero major findings (or an explicit escalation decision if any major appears). Minor findings routed back to the T3 instance via its `task_id`.

### T6 — Final verification
- **Objective:** Run `python3 -m unittest -v` and a manual smoke check of all three modes (`human`, `--json`, `--json --dry-run`) against temp dirs; confirm exit code `0` and stdout purity with a pipe to `python3 -m json.tool`.
- **Files:** none.
- **Pipeline agent:** orchestrator (command execution) — no code-writing agent.
- **Risks:** Local Python version differences; stale `__pycache__` masking changes.
- **Acceptance criterion:** Full suite green; `... --json | python3 -m json.tool` succeeds; `--dry-run` leaves `dst` empty of copies and manifest; human mode output matches pre-change format.

---

**Dependency order:** T1 → T2 → T3 → T4 → T5 → T6 (T3/T4 can overlap only if T3's diff is handed to T4 as a brief; T2 blocks T3).

# Execution plan: `--json` output mode + dry-run UX for synccli

Repo facts (verified): `sync()` is called only by `main()` in synccli.py:96 — no other internal caller (incremental.py imports only `copy_file`). All output happens in `main()`. Tests run via `python3 -m unittest -v` (stdlib unittest).

Ambiguity to resolve first: GOAL.md does **not** define `skipped`, and `copy_file` (synccli.py:68) silently swallows `OSError`, so `copied` can list files that actually failed to copy while the manifest still records them as synced. That is a real design decision, not an implementation detail.

---

### Task 1 — Design review: JSON semantics
- **Objective:** Decide and record: (a) definition of `skipped` (proposed: source files not in `copied` = scanned − copied); (b) whether `copied` in real mode means "attempted" or "actually copied" given the silent `OSError` swallow in `copy_file`; (c) dry-run: `copied` = would-be list, `skipped` computed identically; (d) output shaping lives entirely in `main()`/a new helper so `sync()` stays untouched; (e) stdout purity strategy (single `json.dumps`, no other prints; argparse errors already go to stderr).
- **Files:** DESIGN.md (append a short "JSON output mode" section with the decisions).
- **Agent:** design-review (cheap-design-review).
- **Risks:** Choosing "actually copied" would require changing `copy_file`'s contract, which incremental.py:23 depends on — must be rejected or explicitly scoped out. Mis-defining `skipped` breaks machine consumers later.
- **Acceptance criterion:** DESIGN.md contains a decision for each of (a)–(e), consistent with GOAL.md constraints (no new deps, 3.10 stdlib, `sync()` signature stable); no contradiction with existing code.

### Task 2 — Implement `--json` flag
- **Objective:** Add `--json` to the argparse parser in `main()`; when set, print exactly one `json.dumps` object `{"copied": [...], "skipped": N, "src": ..., "dst": ...}` and nothing else on stdout; human mode byte-identical to today; exit code unchanged. Compute `skipped` per Task 1 decisions (likely a new module-level helper, e.g. `count_source_files(src)` / report builder, leaving `sync()` untouched).
- **Files:** synccli.py (modify `main()`, add helper; no changes to `sync()`).
- **Agent:** impl (cheap-code, fresh session with the Task-1 decisions in the brief).
- **Risks:** Accidentally touching `sync()`'s signature (internal callers / future `syncd` per DESIGN.md); double tree-walk for `skipped` (acceptable for a CLI, note it); printing anything (progress, errors) to stdout in JSON mode.
- **Acceptance criterion:** `python3 -m synccli --json <src> <dst>` emits exactly one line that `json.loads` parses with all four keys present; `python3 -m synccli <src> <dst>` output is unchanged (diff against pre-change output on a fixture tree); `git diff synccli.py` shows no change to the `sync(` definition line.

### Task 3 — Unit tests for JSON shape and dry-run semantics
- **Objective:** Add tests to test_synccli.py: (1) JSON output is valid JSON with keys `copied`/`skipped`/`src`/`dst`; (2) with `--dry-run --json`, `copied` lists would-be files and no files/manifest are written to dst; (3) stdout purity — captured stdout parses as a single JSON object with no extra text; (4) human mode still one path per line (regression guard).
- **Files:** test_synccli.py.
- **Agent:** impl (cheap-code — same task_id/session as Task 2; it has the context).
- **Risks:** Testing `main()` output requires stdout capture (`redirect_stdout` or subprocess) — keep it stdlib-only per constraints; dry-run test must use fresh temp dirs to avoid manifest pollution from other tests.
- **Acceptance criterion:** `python3 -m unittest -v` passes with the new tests included, zero failures; the dry-run test asserts dst contains no copied file and no `.sync_manifest.json`.

### Task 4 — Review diff against GOAL.md constraints
- **Objective:** Read-only check of the combined diff: `sync()` signature unchanged; only stdlib imports; single-JSON-object stdout guarantee actually holds on all code paths; dry-run interplay correct; tests assert the GOAL.md contract, not the implementation; DESIGN.md decisions from Task 1 were followed.
- **Files:** none (read-only).
- **Agent:** review (cheap-review; escalate to strong-review only on a major finding).
- **Risks:** Reviewer may flag the pre-existing `collect_stale` off-by-one (synccli.py:55, `range(1, ...)` skips the first item) — out of scope for this release, must be classified as such, not folded in.
- **Acceptance criterion:** Review report with zero major findings; any minor findings fixed by resuming the Task-2/3 impl instance via `task_id` and re-running `python3 -m unittest -v` green.

### Task 5 — Document the flag
- **Objective:** Add a line to README.md usage noting `--json` (machine-readable single-object output) and its dry-run interplay.
- **Files:** README.md.
- **Agent:** impl (cheap-mech — purely mechanical).
- **Risks:** none.
- **Acceptance criterion:** README.md mentions `--json`; `python3 -m unittest -v` still green (no code touched).

---

Execution order is strict: 1 → 2 → 3 → 4 → 5 (Task 5 can run in parallel with 4). Total: 1 design-review, 2 impl sessions (one resumed), 1 review, 1 mech — no explore task needed, caller/output facts already verified above.
# Execution plan — `--json` output mode + dry-run UX

## Repo facts (from recon)
- `synccli.py:72` `sync(src_root, dst_root, dry_run=False)` returns `to_copy` (list of rel paths) in both modes; dry-run returns before copying/writing manifest (`synccli.py:81`).
- `main()` (`synccli.py:90`) prints one path per line and returns `0`. No `--json` yet.
- `incremental.py` imports `copy_file` from `synccli`; no other module calls `sync()` in-repo — the "internal callers" the goal mentions are outside this snapshot, so the signature must not change.
- Tests: `python3 -m unittest -v`; `test_synccli.py` has `TestSync` asserting `sync()` return value directly.
- No project-local pipeline agents (`.opencode/agent/` absent) → use the kit's fallback agents.
- **Key open decision:** `skipped` is not derivable from `sync()`'s return value (it returns only copied). Must be computed without changing `sync()`'s signature.

## Tasks

### T1 — Confirm call surface & test harness (explore)
- **Objective:** Verify no in-repo caller depends on `main()`'s stdout format or on `sync()` return type beyond `TestSync`; confirm exact unittest command; confirm Python version available.
- **Files:** none modified (read-only).
- **Agent:** `explore`.
- **Risks:** external callers not visible in snapshot; assume stable signature anyway.
- **Acceptance:** written list of every in-repo reference to `sync`, `main`, and stdout-printing; confirmation `python3 -m unittest -v` is green on current HEAD.

### T2 — Design the JSON assembly + `skipped` semantics (design → design-review)
- **Objective:** Decide how to produce `{"copied":[...],"skipped":N,"src":...,"dst":...}` while keeping `sync()` stable. Candidate: `main()` calls `scan_files`/`build_manifest` on src and computes `skipped = len(src_manifest) - len(copied)`; or add a new helper `run_sync(...)` returning a structured result that `main()` formats. Also fix semantics of `skipped` (unchanged+excluded files vs only unchanged) and of `src`/`dst` (echo args verbatim vs normalized).
- **Files:** none (design note only, unless team wants `DESIGN.md` appendix).
- **Agent:** `cheap-design` then `cheap-design-review` (real API/UX stakes: stdout contract is externally observable).
- **Risks:** wrong `skipped` definition; double-walking the tree (scan in `main` + in `sync`) causing inconsistency; accidentally changing `sync()` signature.
- **Acceptance:** design-review approves a specific `skipped` definition and an assembly location; explicit statement that `sync(src, dst, dry_run=False)` signature is untouched.

### T3 — Implement `--json` flag + JSON output (impl)
- **Objective:** Add `--json` to the parser; when set, print exactly one JSON object to stdout and nothing else; human mode unchanged (one path per line). Honor T2's decisions; keep exit code `0`.
- **Files:** modify `synccli.py` (parser + `main`, plus any new helper agreed in T2). No changes to `sync()` signature.
- **Agent:** `cheap-code`.
- **Risks:** stray `print`/logging leaking to stdout; `json.dumps` ordering/`ensure_ascii`; dry-run path must still list would-be copies (already true from `sync`); non-ASCII paths.
- **Acceptance:** `python3 -m synccli src dst --json` emits one parseable JSON object with all four keys; `python3 -m synccli src dst` output identical to pre-change; `python3 -m synccli src dst --json --dry-run` leaves dst untouched and `copied` lists would-be copies; exit codes unchanged.

### T4 — Add unit tests to `test_synccli.py` (impl)
- **Objective:** Tests for JSON shape: valid JSON, all keys present, `skipped` value correct, dry-run semantics (`copied` = would-be, no files written, manifest not written), and human mode still one-path-per-line. Test `main()` output via `redirect_stdout` / `contextlib`.
- **Files:** modify `test_synccli.py` only.
- **Agent:** `cheap-code` (same session as T3 via `task_id` — shared context on the new output path).
- **Risks:** asserting on `json.loads` vs raw string (must assert single object, no trailing text); mtime/size flakiness in `skipped` assertions.
- **Acceptance:** `python3 -m unittest -v` green; new tests fail if `--json` prints extra text or omits a key (verify by temporary mutation, then revert).

### T5 — Independent review of the diff (review)
- **Objective:** Read-only review of T3+T4 against GOAL.md: stdout purity in JSON mode, unchanged human mode, stable `sync()` signature, no new deps, Python 3.10 stdlib only, test quality.
- **Files:** none (read-only).
- **Agent:** `cheap-review`; escalate to `strong-review` only if a major finding (stdout contamination, signature change, dependency).
- **Risks:** subtle stdout leak from argparse/errors; `skipped` off-by-one on the manifest file itself.
- **Acceptance:** verdict with findings classified minor/major; minor findings routed back to the T3/T4 session via `task_id`.

### T6 — Final verification (review)
- **Objective:** Run `python3 -m unittest -v`; manually run both modes on a temp tree; diff human-mode stdout against `git stash` baseline; confirm exit code `0` and JSON parses.
- **Files:** none (read-only).
- **Agent:** `cheap-review` (or orchestrator directly for the final smoke run).
- **Risks:** none beyond re-running T5 checks.
- **Acceptance:** all four GOAL items demonstrably satisfied; command transcript recorded.

## Ordering & gates
T1 → T2 (design-review gate) → T3 → T4 → T5 (review gate) → T6. T3 and T4 share one `cheap-code` session; T5 must not be skipped even on a short diff. No commits unless explicitly requested.

## Top risks to watch
1. `skipped` semantics ambiguity (T2 must lock it).
2. Double tree-walk if `main` computes manifests separately from `sync` (T2 to choose single source of truth).
3. stdout contamination in `--json` mode (T5's main focus).
4. `sync()` signature drift despite the stable-signature constraint (T5).
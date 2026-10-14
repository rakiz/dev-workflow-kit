# Execution plan: `--json` output mode + dry-run UX for synccli

Scope from GOAL.md: add `--json` (single JSON object on stdout: `copied`, `skipped`, `src`, `dst`), dry-run interplay, human mode unchanged, tests, no new deps, `sync()` signature stable.

---

**Task 1 — Explore: baseline & constraints check (read-only)**
- Objective: confirm current behavior and callers of `sync()` so the JSON design doesn't break internal callers; check `test_synccli.py` conventions (unittest style, tempdir helpers).
- Agent: **explore**
- Files: none (reads `synccli.py`, `test_synccli.py`, `DESIGN.md`)
- Risks: DESIGN.md mentions a future `syncd` daemon reusing `sync()` directly — any change to what `sync()` prints or returns must not leak CLI concerns into it.
- Acceptance: report listing all `sync()` call sites, the current stdout contract (one path per line, `main()` synccli.py:97-98), and test file structure (fixture patterns, how dry-run is currently tested).

**Task 2 — Design review: JSON output contract (before code)**
- Objective: settle the exact contract: where the JSON is emitted (`main()` only, not `sync()`), definition of `skipped` (files not in `to_copy` = source files unchanged vs manifest, presumably `len(src_manifest) - len(copied)`), `copied` in dry-run = would-be-copied list, values/types of `src`/`dst` (the raw CLI args), and "nothing else on stdout" (no incidental prints; stderr allowed for errors).
- Agent: **design-review** (cheap-design-review)
- Files: none (may propose updating DESIGN.md — decision only)
- Risks: ambiguity of `skipped` is the main trap — GOAL.md gives only `skipped: N`; a wrong definition ships a wrong contract. Also: `copy_file` silently swallows OSError (synccli.py:68-69), so `copied` may overstate what actually landed — decide whether that's acceptable for v1 (document it).
- Acceptance: a written contract: exact key set, types, skipped computation, dry-run semantics, error-behavior, signed off as unambiguous enough to implement.

**Task 3 — Implement: `--json` flag and report emission**
- Objective: add `--json` to argparse in `main()`; in that mode print exactly one `json.dumps` object `{"copied": [...], "skipped": N, "src": args.src, "dst": args.dst}` and no per-line output; human mode untouched. Stdlib only (argparse/json already imported).
- Agent: **impl** (cheap-code)
- Files: modify `synccli.py` (only `main()`; `sync()` signature and behavior unchanged)
- Risks: printing anything else to stdout (violates "nothing else"); mutating `sync()` or making it print; `skipped` computed inconsistently with Task 2's contract.
- Acceptance: `python3 -m synccli --json src dst` in a temp scenario emits exactly one line of valid JSON with the four keys; `python3 -m synccli src dst` output byte-identical to pre-change behavior for the same input; `git diff` shows no change to `sync()`.

**Task 4 — Implement: tests for JSON shape and dry-run semantics**
- Objective: extend `test_synccli.py` with unittest cases: (a) `--json` output parses as JSON and has all four keys with correct types; (b) with `--json --dry-run`, `copied` lists would-be-copied files and destination is unmodified (no manifest written, no files copied); (c) `--json` after a real sync, then re-run → `copied: []`, `skipped` reflects unchanged count; (d) human mode still one-path-per-line (regression guard).
- Agent: **impl** (cheap-code, same session/task_id as Task 3 if close in time — small change, reuse context)
- Files: modify `test_synccli.py`
- Risks: tests asserting on the swallowed-OSError behavior or on absolute paths (use tempdirs); mtime granularity flakes — set explicit mtimes via `os.utime` as existing tests presumably do.
- Acceptance: `python3 -m unittest -v` passes with the new cases included, and all pre-existing tests still pass.

**Task 5 — Review: mandatory diff review**
- Objective: verify Tasks 3-4 against GOAL.md constraints: single JSON object only on stdout in `--json` mode, exit code unchanged, no new dependencies, Python 3.10 stdlib only, `sync()` signature stable, human mode unchanged, tests genuinely cover dry-run semantics.
- Agent: **review** (cheap-review)
- Files: reads `synccli.py`, `test_synccli.py`; may bounce fixes back to Task 3/4's impl session via task_id (minor) or escalate to strong-code (major)
- Risks: subtle stdout pollution (e.g. argparse errors go to stderr — fine; but any debug print would violate the contract); `skipped` off-by-one vs the Task 2 contract.
- Acceptance: review verdict with zero major findings; each constraint in GOAL.md explicitly confirmed; `python3 -m unittest` green after any fixes.

**Task 6 — Docs: README usage update**
- Objective: document `--json` (one line: flag, output shape, dry-run interplay) in README.md next to the existing usage line.
- Agent: **impl** (cheap-mech — purely mechanical)
- Files: modify `README.md`
- Risks: none (text only).
- Acceptance: README mentions `--json` and its output shape; `python3 -m synccli --help` and README agree.

---

Sequencing: 1 → 2 → (3 → 4) → 5 → 6. Tasks 3 and 4 share one impl session (small, tightly coupled change); Task 5 is the gate; Task 6 is independent of 5 and can run in parallel with it once 4 is done.
Read both files plus `synccli.py`, `test_synccli.py`, `incremental.py`, `DESIGN.md`. Here is the execution plan (text only, no modifications made).

## Repo facts that drive the plan
- `synccli.py:72` `sync(src_root, dst_root, dry_run=False)` returns **only** the copied list → the JSON's `skipped` count is not derivable today, and `sync()` must stay signature-stable (DESIGN.md:31 plans a `syncd` reusing `sync()`).
- `synccli.py:97` human mode prints one path per line to stdout → stdout purity in `--json` mode is the main new invariant.
- `copy_file` (synccli.py:62) swallows `OSError`, so an unreadable source is still reported as "copied" → risk for the `copied`/`skipped` accounting.
- `incremental.py` is an in-review v0.2 helper with a mutable default arg (`filter_excluded`, incremental.py:10) and a `for p in paths` loop that never inspects `p` — out of GOAL scope, but it imports `copy_file` and must keep compiling.

---

## Task 1 — Resolve the `skipped` semantics (design)
- **Objective**: pin down exactly what `skipped` counts and what `copied` contains, so impl and tests agree. Options: (a) `skipped` = source files unchanged (manifest-identical); (b) + files whose copy failed (`OSError`); (c) `skipped` = source files not present in dst. Also decide whether `copied` lists relative paths (existing `sync()` semantics) or dst paths.
- **Files**: none modified (decision recorded in the task brief / optionally a short section appended to `DESIGN.md`).
- **Agent**: `design-review` (cheap-design-review first; escalate to strong-design-review only if a real architectural stake appears).
- **Risks**: ambiguous spec silently baked into tests; a `skipped` definition that double-counts files absent from `src`; changing `copied` to dst paths breaking the human mode's existing meaning.
- **Acceptance**: a one-paragraph written contract naming the exact definition of `copied` (list) and `skipped` (int), plus the rule for failed copies (counted as skipped, not copied) — approvable without reading code.

## Task 2 — Locate every caller and constraint of `sync()` (explore)
- **Objective**: confirm the full call graph around `sync()`/`copy_file` (including the future `syncd` from DESIGN.md) so the "signature stable" constraint is honoured, and check whether any caller depends on the human-mode stdout format.
- **Files**: read-only.
- **Agent**: `explore`.
- **Risks**: a caller relying on `sync()`'s return being a list of rel paths being broken by a refactor to a result object; `incremental.py` coupling.
- **Acceptance**: a list of every `sync()`/`copy_file` call site with file:line, and an explicit statement of what `sync()` must keep returning.

## Task 3 — Implement the result-producing sync API (impl)
- **Objective**: add a rich-result entry point (e.g. `sync_result(src_root, dst_root, dry_run=False) -> dict` with `copied`/`skipped`) while `sync()` keeps its current signature and current return value (list of copied rel paths) by delegating to it. Compute `skipped` per Task 1's contract. Handle the `copy_file` `OSError` path so failed copies are not counted as copied.
- **Files**: `synccli.py` (new function + `sync()` reduced to a thin wrapper; no changes to `scan_files`/`build_manifest`/`changed_files`/`copy_file` semantics beyond what Task 1 mandates).
- **Agent**: `impl` (cheap-code).
- **Risks**: `dry_run` semantics changing (currently returns `to_copy` *without* copying and *without* writing the manifest — must be preserved: dry-run must not mutate `dst`); `skipped` miscounted against the manifest rather than the source tree; breaking `sync()`'s list return.
- **Acceptance**: `sync(src,dst)` still returns `["a.txt"]` and `[]` on a second run (existing tests pass unchanged); `sync_result(src,dst,dry_run=True)` returns the would-copy list and leaves `dst` byte-identical (no manifest written); `python3 -m unittest -v` is green.

## Task 4 — Implement `--json` CLI mode (impl)
- **Objective**: add `--json` to the parser; in JSON mode emit exactly one `json.dumps` object on stdout with keys `copied` (list), `skipped` (int), `src`, `dst`; in human mode keep one path per line, unchanged. Exit code stays 0 in both modes. `--dry-run` + `--json` → `copied` lists what *would* be copied.
- **Files**: `synccli.py` (`main()` only).
- **Agent**: `impl` (cheap-code) — can run in the same session as Task 3 if the implementer is fresh, else a separate session.
- **Risks**: any stray `print` to stdout in JSON mode (the OSError-swallowing path prints nothing today, but new code must not add any); `json` output split across multiple writes; `src`/`dst` echoing user-supplied paths verbatim (fine, but must be the resolved values used for the operation); argparse errors already go to stderr (verify).
- **Acceptance**: `python3 -m synccli SRC DST --json` stdout parses with `json.loads` as a single object containing exactly the four required keys, and stdout contains nothing else; `--dry-run --json` lists the same paths that a real run would copy; `--help` shows both flags; exit code 0.

## Task 5 — Unit tests for JSON shape and dry-run semantics (impl)
- **Objective**: extend `test_synccli.py` with tests covering: JSON output is valid JSON and a single object; required keys present with correct types; `copied` non-empty and matching the synced files; `skipped` equals the count of unchanged source files; `--dry-run --json` reports would-copy paths and copies nothing; human mode still prints one path per line; stdout contains no extra output in JSON mode.
- **Files**: `test_synccli.py` (add new test classes; do not alter the existing three test classes).
- **Agent**: `impl` (cheap-code).
- **Risks**: tests asserting on incidental stdout whitespace (use `json.loads(stdout)` rather than string matching); tests leaking temp dirs (existing style uses `tempfile.mkdtemp` — follow it); a test that only checks happy path and misses the `skipped` count.
- **Acceptance**: `python3 -m unittest -v` is green with the new tests included, and each of the four GOAL requirements (JSON shape, keys, dry-run semantics, human mode unchanged) is covered by at least one named test.

## Task 6 — Review the implementation (review)
- **Objective**: independent review of the Task 3–5 diff against GOAL.md: stdout purity, `sync()` signature/return stability, no new dependencies, Python 3.10 stdlib only, dry-run non-mutation, `skipped` accounting, exit codes unchanged.
- **Files**: read-only review of `synccli.py` + `test_synccli.py`.
- **Agent**: `review` (cheap-review, mandatory; a fresh reviewer session — do not resume an earlier session).
- **Risks**: a "works on my machine" acceptance (the suite must be run); review flags the `incremental.py` mutable-default bug as in-scope — that is out of scope for this GOAL and must be recorded as a follow-up, not fixed.
- **Acceptance**: a review verdict listing findings classified minor/major; zero major findings, and every minor finding fixed by the implementer (or explicitly waived by the user) before Task 7.

## Task 7 — Final verification (impl → review)
- **Objective**: re-run the full verification after any review fixes, and confirm the human-mode output is byte-identical to pre-change behaviour.
- **Files**: none beyond fix commits from Task 6.
- **Agent**: `impl` for fixes, `review` (cheap-review) for the re-review of the fixed diff.
- **Risks**: a fix reintroducing stdout noise in JSON mode; the "unchanged human mode" claim being asserted rather than measured (compare against the pre-change output captured in Task 2).
- **Acceptance**: `python3 -m unittest -v` green; a manual run of both modes shows exactly one JSON object for `--json` and one path per line for human mode; no dependency file was added or changed.

---

**Ordered pipeline**: explore (T2) + design-review (T1, parallel, read-only) → impl (T3 → T4 → T5) → review (T6) → impl fixes + review (T7).
**Escalation policy**: any major finding from `review` goes to `strong-code`/`strong-review`; no pre-emptive escalation.

## Repo facts (grounding the plan)

- `synccli.py:72` — `sync(src_root, dst_root, dry_run=False)` returns a **list** of relative paths; `dry_run` returns `to_copy` early (no manifest write).
- `synccli.py:90` — `main()` prints one path per line, returns 0 → exit code always 0.
- `synccli.py:62` — `copy_file()` swallows `OSError`, so a failed copy still appears in the returned "copied" list (silent under-report risk).
- `synccli.py:45` — `collect_stale()` exists but is **not used** by `sync()` (dead helper; `incremental.py` also isn't wired in).
- `incremental.py:5` — imports `copy_file` from `synccli` → `copy_file` is an internal-facing API.
- `DESIGN.md:31` — planned daemon `syncd` "reusing `sync()` directly" → `sync()` is an internal caller contract; its return type is as load-bearing as its signature.
- Tests: `python3 -m unittest -v`, `unittest` + `tempfile` only, stdlib Python 3.10.11.
- No `.opencode/agent/` kit → use built-in agents (`explore`, `cheap-design`, `cheap-design-review`, `cheap-code`, `cheap-review`).

### The one ambiguity that blocks implementation
`GOAL.md` requires `"skipped": N` but never defines it. The codebase has **two** candidate meanings: (a) files not copied because they were already up-to-date, (b) files whose copy failed (`copy_file` swallows the error). This must be pinned by design before any code is written — the acceptance test cannot be written against an undefined number.

---

# Execution plan

## Task 1 — Recon & baseline capture
- **Objective:** Produce a factual baseline: exact current `sync()` signature/return type, exact current stdout for human mode (golden transcript), exact `copy_file` failure semantics, and the set of internal callers (`incremental.py`, planned `syncd`). Enumerate the candidate definitions of "skipped" with the exact data each one would require from `sync()`.
- **Files:** read-only — `synccli.py`, `incremental.py`, `test_synccli.py`, `DESIGN.md`. No writes.
- **Agent:** `explore`
- **Risks:** none (read-only). Risk of *not* doing it: the "skipped" definition and the `copy_file` failure question get decided implicitly by the implementer.
- **Acceptance:** Report contains (a) a golden transcript of `python3 -m synccli SRC DST` and `--dry-run` on a 3-file fixture, (b) verbatim current `inspect.signature(synccli.sync)` and `inspect.signature(synccli.copy_file)`, (c) a table of skipped-candidates → required data → required code change, (d) the list of internal callers of `sync()`/`copy_file`.

## Task 2 — Design the JSON contract
- **Objective:** Specify the exact contract for `--json`: the four keys and their types, the definition of `skipped`, dry-run semantics for every key, and the mechanism that keeps `sync()` stable while exposing richer data.
- **Files:** design delivered as an agent **report** (no new file in the repo, unless the orchestrator asks for one).
- **Agent:** `cheap-design`
- **Design constraints to state and honor:**
  - `sync()` keeps signature `(src_root, dst_root, dry_run=False)` **and** its current return type (list of rel paths).
  - Preferred shape: add a sibling function `sync_report(src_root, dst_root, dry_run=False) -> dict` returning `{"copied": [...], "skipped": N, "src": ..., "dst": ...}`; `sync()` becomes a thin wrapper delegating to it (`return sync_report(...)["copied"]`). This is the only way to satisfy "keep `sync()` signature stable" *and* "machine-readable output" without a second pass over the filesystem.
  - `copied` in JSON mode must contain the **same strings** as human mode prints (one relative path each), so the two modes stay comparable and testable against each other.
  - `--json` mode: exactly one `json.dumps(...)` object on stdout, single line; every diagnostic/warning goes to **stderr**; no other stdout writes anywhere in the library path.
  - Exit code 0 in all success paths, unchanged from today; argparse errors remain exit 2 on stderr.
- **Risks:** (R1) `skipped` undefined in GOAL → design must pick one definition and state it in one sentence; (R2) a design that changes `sync()`'s return type breaks `syncd` (DESIGN.md) and the existing `TestSync` tests; (R3) a design that derives `skipped` from `copy_file` requires changing `copy_file`'s return value (currently `None`, and `incremental.copy_many` assumes it can raise — its `try/except` is currently dead code because `copy_file` swallows `OSError`); (R4) design that counts failures as "skipped" silently hides I/O errors.
- **Acceptance:** Report answers unambiguously: (1) one-line definition of `skipped`; (2) the exact dict `sync_report` returns in real mode and in dry-run mode, with a worked example; (3) confirmation that `sync()`'s signature and return type are byte-for-byte compatible; (4) the stdout/stderr split; (5) the decision on `copy_file` (changed vs unchanged) with the blast radius on `incremental.py`.

## Task 3 — Design review (gate)
- **Objective:** Critique Task 2's design before code exists; catch contract holes, compatibility breaks, and stdout-purity gaps while they are still free to change.
- **Files:** none (read-only review of the Task 2 report + repo).
- **Agent:** `cheap-design-review`
- **Risks:** skipped review → the design's ambiguity (esp. `skipped`) reaches implementation and produces a test suite written against a guessed contract.
- **Acceptance:** Verdict is explicit `approve` / `approve-with-changes` / `reject`. For `approve-with-changes`, each change item is written as a testable statement (e.g. "`skipped` == number of source files not present in `copied`, counting failed copies", not "clarify skipped"). All change items are carried into Task 4's brief verbatim.

## Task 4 — Implementation
- **Objective:** Implement the reviewed design: `--json` flag, `sync_report()`, `sync()` delegation, stdout/stderr separation, human mode untouched.
- **Files:** `synccli.py` (modify), `incremental.py` (modify **only** if the design changed `copy_file`'s contract — otherwise do not touch it).
- **Agent:** `cheap-code`
- **Brief must include:** the exact reviewed contract; the invariant that `sync()`'s signature and return type are unchanged; the invariant that human mode output is byte-identical to the Task 1 golden transcript; the rule that in `--json` mode nothing but the single JSON object reaches stdout; the rule that `--json --dry-run` must not create `.sync_manifest.json` or copy files; stdlib-only imports (`argparse`, `json`, `os`, `sys`).
- **Risks:** (R5) stdout purity broken by a stray `print` or a debug leftover → JSON parse of full stdout fails; (R6) dry-run accidentally writing the manifest → "would be copied" becomes "was copied"; (R7) `copy_file` change breaks `incremental.py` import/behavior; (R8) `skipped` computed from `len(manifest) - len(copied)` is wrong when a copy fails (over-reports copied, under-reports skipped) unless the design settled it; (R9) path separator/relative-path formatting differing between JSON and human modes.
- **Acceptance:** (a) `python3 -m synccli SRC DST` stdout is byte-identical to the Task 1 golden transcript; (b) `python3 -m synccli --json SRC DST` stdout is exactly one line that `json.loads` to a dict with keys exactly `{copied, skipped, src, dst}`, `copied` a list of str, `skipped` an int; (c) `python3 -m synccli --json --dry-run SRC DST` prints the same `copied` list as `--json` would report, and the destination directory is byte-for-byte unchanged (no manifest, no copied files); (d) `inspect.signature(synccli.sync)` is unchanged and `synccli.sync(src, dst)` still returns a list equal to the previous golden value; (e) `grep -E '^import |^from '` over `synccli.py` shows only stdlib modules.

## Task 5 — Tests
- **Objective:** Add the unit tests required by `GOAL.md` (JSON shape: valid JSON, keys present, dry-run semantics) plus regression guards for the invariants the review flagged.
- **Files:** `test_synccli.py` (modify — same file, as GOAL requires).
- **Agent:** `cheap-code`
- **Tests to add (minimum):** JSON output is a single valid JSON object; the four keys are present with the right types; `src`/`dst` echo the CLI arguments; `copied` is a list of relative paths and matches the human-mode lines; `--dry-run --json` lists what *would* be copied and leaves the destination untouched; human mode still prints one path per line; `sync()`'s return value is still a list (signature-stability guard); `skipped` behaves per the Task 2/3 definition on a fixture with an up-to-date file and a new file.
- **Risks:** (R10) tests written against a guessed `skipped` definition → tests pass while the contract is wrong (mitigated by Task 3's gate); (R11) tests that touch the real filesystem or leak temp dirs; (R12) a test asserting stdout purity that misses stderr-only diagnostics; (R13) tests that only cover the happy path and miss the failed-copy case if `skipped` counts failures.
- **Acceptance:** `python3 -m unittest -v` reports **all** tests passing (pre-existing `TestScanFiles`, `TestCollectStale`, `TestSync` still green — no test deleted or weakened); the new tests fail if `--json` prints anything but the single object (e.g. verified by asserting `json.loads(captured_stdout)` succeeds *and* stdout has exactly one line); the destination-directory-untouched assertion for dry-run is present.

## Task 6 — Code review (mandatory gate)
- **Objective:** Review the complete diff (`synccli.py` + `test_synccli.py`) against `GOAL.md` and the Task 3 approved contract, from a different model lineage than the implementer.
- **Files:** read-only review of the diff.
- **Agent:** `cheap-review`
- **Risks:** (R14) review skipped → implementation defects ship; (R15) a review that ignores the "human mode unchanged" constraint and blesses a changed human output.
- **Acceptance:** Verdict classifies every finding as **minor** (must be fixed by Task 4's implementer, in the same session via `task_id`) or **major** (escalate to `strong-code`); the review explicitly confirms or refutes each of: JSON single-object stdout purity, `sync()` signature+return-type stability, human-mode byte-compatibility, dry-run non-mutation, stdlib-only, `skipped` matching the approved definition, GOAL item 4 (tests in `test_synccli.py`). A major finding → escalate to `strong-code` (announce the cost before invoking); minor findings → resume the Task 4/5 implementer instance.

## Task 7 — Final verification & audit
- **Objective:** Independent end-to-end audit of the shipped behavior against `GOAL.md` line by line, run by a reviewer that did not write the code.
- **Files:** none (verification runs only).
- **Agent:** `strong-review` (fresh lineage) — the final audit rung. If the diff is small and Task 6 returned zero majors with every criterion checked, `cheap-review` may be reused instead; the orchestrator picks based on Task 6's severity.
- **Risks:** (R16) a passing unit suite that hides a broken CLI contract (e.g. JSON printed but human mode broken) → mitigated by running the CLI end-to-end, not just the unit tests; (R17) stale review if Task 4/5 changed after Task 6 → the audit re-reads the final diff, never a cached report.
- **Acceptance:** For each of GOAL.md items 1–4 and each constraint, a pass/fail line backed by the command actually run and its output. Concretely: (1) `--json` stdout is one parseable object and nothing else, exit code unchanged; (2) `--json --dry-run` `copied` equals the would-be copy list and the destination is unmodified; (3) human mode output is identical to the Task 1 golden transcript; (4) `test_synccli.py` contains the new tests and `python3 -m unittest -v` is fully green; plus `sync()` signature/return-type unchanged, stdlib-only imports, no new dependencies in the environment.

## Task 8 (optional, on request) — Docs
- **Objective:** Document the new flags in `README.md` (`--json`, `--dry-run`) so the usage section matches `--help`.
- **Files:** `README.md` (modify).
- **Agent:** `cheap-mech`
- **Risks:** (R18) README drift vs actual `--help` output → the acceptance criterion is the text matching `python3 -m synccli --help` verbatim.
- **Acceptance:** `README.md` shows `python3 -m synccli --json SRC DST` with the exact JSON shape, and the documented shape matches the Task 4 implementation.

---

### Pipeline summary
```
explore (T1) → cheap-design (T2) → cheap-design-review (T3) [GATE]
   → cheap-code impl (T4) → cheap-code tests (T5)
   → cheap-review (T6) [GATE: minor→same impl session, major→strong-code]
   → strong-review (T7) final audit
   → cheap-mech docs (T8, on request)
```
### Global constraints carried into every brief
No new dependencies; Python 3.10 stdlib only; `sync()`'s signature **and** return type unchanged; human mode output byte-identical to baseline; `--json` stdout is exactly one JSON object and nothing else; no repository files modified until the Task 3 gate passes.

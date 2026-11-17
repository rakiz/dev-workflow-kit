Repo is small and fully read. Baseline verified: 6 tests, **1 pre-existing failure** (`test_first_item_stale_is_included` — `collect_stale` skips `items[0]` at synccli.py:55, unrelated to this goal). No setup.py/pyproject; `synccli.py`, `incremental.py`, `test_synccli.py` only. `incremental.py` imports only `copy_file`; nothing calls `sync()` except `main()` — but GOAL constrains the signature, so treat it as a hard constraint anyway.

# Execution plan — JSON output mode + dry-run UX

Key design decisions that must be settled in T1 (they gate everything else):
- **D1 — `skipped` semantics**: number of source files *not* copied (unchanged **plus** failed copies). Alternative reading ("unchanged only") must be explicitly rejected or adopted; the JSON shape has no `failed` key, so failures must land somewhere.
- **D2 — no second scan**: `skipped` must be computed from the manifest already built inside `sync()` (src files − copied), never by a second `build_manifest()` call (DESIGN.md targets ~50k files).
- **D3 — stdout purity**: in `--json` mode the only stdout write is the single `json.dumps` result; all diagnostics → stderr. Exit code stays `0` from `main()`.
- **D4 — `sync()` stays a list-returning, same-signature public function**; richer data is exposed through a *new* internal function, `sync()` delegates to it.

---

## T0 — Baseline & stdout-surface survey
- **Objective**: establish a factual baseline before any edit: current CLI surface, every `print`/`write` to stdout in the codebase, all callers of `sync()`/`copy_file`, and the exact pre-existing test failure. Lock this down so T6 can distinguish regressions from inherited failures.
- **Files**: none modified (read-only).
- **Agent**: `explore` (cheap, read-only).
- **Risks**: baseline recorded against a dirty working tree (`__pycache__` is modified in git status) — ignore cache noise, only `.py` sources count. Explorer may over-report `incremental.py` as a `sync()` caller; it is not (it imports `copy_file` only).
- **Acceptance**: a written baseline containing (a) the exact `python3 -m unittest -v` failure list (expect exactly 1: `test_first_item_stale_is_included`), (b) the list of stdout-writing sites in `synccli.py` (expect: `print(rel)` at synccli.py:98 only), (c) the confirmed set of `sync()` call sites, (d) the confirmed `sync()` signature and return type.

## T1 — Design the JSON contract (decision record)
- **Objective**: fix D1–D4 in writing before code exists: exact JSON schema and value types, `skipped` definition, dry-run meaning of `copied` ("would be copied"), purity rule, error/diagnostic routing, and the explicit statement that `sync()`'s signature and return type are unchanged. Decide the `copy_file` failure-attribution rule.
- **Files**: modify `DESIGN.md` (append a "JSON output mode" section). No code yet.
- **Agent**: `cheap-design` produces the draft, then `cheap-design-review` critiques it (stakes: the `skipped` definition and the `sync()`-stability technique are the two decisions the whole feature rests on). Escalate to `strong-design` only if the design review finds a major conflict with GOAL constraints.
- **Risks**: ambiguity in "skipped" is the single most likely source of a wrong implementation; over-designing a 100-line CLI (the plan must stay stdlib-only, Python 3.10). DESIGN.md describes a *future daemon* (`syncd`) — the new section must not imply the daemon ships now.
- **Acceptance**: `DESIGN.md` contains a section stating, verbatim-in-substance: the four top-level keys and their types; `skipped` = count of source files not copied including copy failures; dry-run `copied` = would-be-copied; in `--json` mode stdout carries exactly one JSON object and nothing else; `sync(src_root, dst_root, dry_run=False)` keeps its signature and its list return; the implementation mechanism is a new internal report function with `sync()` delegating to it.

## T2 — Implementation: JSON mode in `synccli.py`
- **Objective**: implement T1. Add `--json` to the parser; introduce an internal report-producing function (e.g. `sync_report(src_root, dst_root, dry_run=False)` returning `{"copied": [...], "skipped": N, "src": ..., "dst": ...}`) that reuses the *existing* `src_manifest`/`old_manifest`/`to_copy` computation so no second scan happens; keep `sync()` as a thin wrapper returning the same list as today; make the copy step report per-file success so failures are counted as skipped; in `main()`, branch to a single `json.dumps(report)` write to stdout in `--json` mode and keep the existing `print(rel)` per-line loop unchanged in human mode.
- **Files**: modify `synccli.py`.
- **Agent**: `cheap-code` (implementation). Use `cheap-mech` instead only if the design is a literal, mechanical application of T1 with no new decisions.
- **Risks**:
  - stdout purity broken by an accidental `print`/`logging` to stdout → route nothing else to stdout; all noise to stderr.
  - `copy_file` currently swallows `OSError` (synccli.py:66-69) and returns `None`; making it return success/failure changes a shared helper used by `incremental.py` — keep it **backward compatible** (return a value; existing callers ignore it) or add a sibling helper. Do not alter `incremental.py` without approval.
  - Changing `sync()`'s return type or signature breaks the stated internal-caller constraint and `test_synccli.py:43-51`.
  - `skipped` computed via an extra `build_manifest()` = second full tree walk (D2 violation).
  - Path separators: `copied` entries must be the same relative-path strings human mode prints (`os.path.join` style) so both modes agree.
  - Dry-run must still not write the destination manifest nor copy files (existing early return at synccli.py:81-82).
- **Acceptance**: `python3 -m synccli SRC DST --json` prints exactly one line that `json.loads` parses into an object with keys `copied` (list), `skipped` (int), `src` (str), `dst` (str); stdout contains nothing else; exit code is `0`; `python3 -m synccli SRC DST` still prints one relative path per line and is not JSON; `python3 -m synccli SRC DST --json --dry-run` lists would-be copies and leaves DST byte-identical (no manifest, no copied files); `synccli.sync(src, dst)` still returns `["a.txt"]` and still writes `.sync_manifest.json`.

## T3 — Tests for the JSON shape and dry-run semantics
- **Objective**: add unit tests to `test_synccli.py` per GOAL item 4: JSON validity, exact key set, value types, dry-run semantics (would-be list; no side effects on DST), stdout purity in JSON mode, human mode unchanged (one path per line, not JSON), and exit code unchanged.
- **Files**: modify `test_synccli.py` (new test class, e.g. `TestJsonOutput`; keep existing classes untouched).
- **Agent**: `cheap-code`.
- **Risks**: capturing stdout — use `contextlib.redirect_stdout`/`io.StringIO` (stdlib only) rather than subprocess; tests must not depend on CWD (use `tempfile` + `tmp` dirs like the existing `setUp`s); a test that asserts `skipped` must pin the T1 definition exactly, otherwise it locks in the wrong semantics; avoid over-asserting exact JSON key *order* (parse the object, don't string-match).
- **Acceptance**: new tests cover: valid JSON parse of the whole captured stdout; `set(obj) == {"copied","skipped","src","dst"}`; `copied` is a list of the copied relative paths; `skipped` is an `int` equal to the number of source files not copied; `--json --dry-run` reports would-be copies while DST stays empty (no `.sync_manifest.json`); `--json` stdout contains exactly one JSON object and no extra text; human-mode stdout equals the copied paths, one per line; `main()` returns `0` in both modes.

## T4 — Review of the implementation + tests
- **Objective**: review the T2/T3 diff against GOAL.md line by line and against the T1 design record, from a different model lineage. Classify each finding as minor (fix in place) or major (escalate).
- **Files**: none (read-only review of `synccli.py`, `test_synccli.py`, `DESIGN.md`).
- **Agent**: `cheap-review` (mandatory, no exceptions — even on a short diff).
- **Risks**: the reviewer has no task history, so the brief must be self-contained (embed GOAL.md's four requirements, D1–D4, and the T0 baseline). A review that ignores the pre-existing failing test would report a false regression; the baseline must be included in the brief.
- **Acceptance**: a written review listing every finding with severity, explicitly confirming or refuting each of: stdout purity, `sync()` signature/return stability, stdlib-only/3.10 compatibility, no second tree scan, dry-run no-side-effect, `skipped` definition matching T1, human mode unchanged, no new dependencies, and no edits to `incremental.py`.

## T5 — Apply review findings
- **Objective**: resolve every finding from T4.
- **Files**: modify `synccli.py`, `test_synccli.py` (and `DESIGN.md` only if a design decision changed).
- **Agent**: resume the T2/T3 `cheap-code` instance for minors (it holds the code context); escalate to `strong-code` (with the user informed first, per cost policy) only if T4 returned a **major** finding.
- **Risks**: a resumed implementer may "fix" a symptom by changing `sync()`'s signature — explicitly forbid it. Unrelated cleanup (the `collect_stale` off-by-one, the `filter_excluded` mutable default) must NOT be folded in without approval.
- **Acceptance**: every T4 finding is either closed with a concrete diff or explicitly rejected with a stated reason; the GOAL-mandated constraints still hold after the changes.

## T6 — Final verification
- **Objective**: prove the feature works end-to-end and that nothing regressed.
- **Files**: none modified.
- **Agent**: `cheap-review` (independent re-run) or a scripted verification pass executed by the orchestrator; escalation to `strong-review` if any doubt remains about the purity/dry-run guarantees.
- **Risks**: the inherited `collect_stale` failure will keep the suite red — it must be reported as **pre-existing** (baseline T0), never as a regression, and never silently fixed.
- **Acceptance**: (a) `python3 -m unittest -v` → the only failure is the pre-existing `test_first_item_stale_is_included`; all new tests pass; (b) manual smoke: `--json` stdout is exactly one parseable JSON object (no extra bytes beyond the trailing newline); exit code `0`; `--json --dry-run` leaves DST unmodified; human mode output byte-identical to the pre-change behavior; (c) `git diff --stat` shows only `synccli.py`, `test_synccli.py`, `DESIGN.md` (+ optionally `README.md`) and no dependency or `incremental.py` changes.

## T7 — Documentation touch-up
- **Objective**: document the new flag so the CLI usage stays truthful.
- **Files**: modify `README.md` (usage line: mention `--json` and `--dry-run`; note that JSON mode emits a single object on stdout).
- **Agent**: `cheap-mech`.
- **Risks**: scope creep into rewriting README/GOAL prose — keep it to the usage bullet; `GOAL.md` is the spec, not to be edited.
- **Acceptance**: README states that `--json` prints a single JSON object with keys `copied`, `skipped`, `src`, `dst`, and that combining it with `--dry-run` lists what would be copied without touching the destination.

---

**Total pipeline**: `explore` (T0) → `cheap-design` + `cheap-design-review` (T1) → `cheap-code` (T2, T3) → `cheap-review` (T4) → `cheap-code` resume / `strong-code` on major (T5) → verification `cheap-review` (T6) → `cheap-mech` (T7). Escalation to the strong tiers is only triggered by a demonstrated major finding, never pre-emptively.

No files were modified.

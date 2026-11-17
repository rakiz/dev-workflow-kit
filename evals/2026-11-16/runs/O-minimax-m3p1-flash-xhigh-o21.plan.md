Read both files, plus the code they point at (`synccli.py`, `test_synccli.py`, `incremental.py`, `DESIGN.md`) and ran the baseline suite. No files were modified.

## Baseline facts (verified)

- `synccli.py:72` — `sync(src_root, dst_root, dry_run=False) -> list[str]` returns copied relative paths; `synccli.py:90` `main()` prints one path per line and returns `0`.
- `incremental.py:5` imports `copy_file`; `DESIGN.md:31` plans a `syncd` daemon that "reuse[s] `sync()` directly" → `sync()`'s signature *and* its `list[str]` return type are both load-bearing.
- `copy_file` (`synccli.py:62`) swallows `OSError` and returns `None` — a "copied" entry may mean "attempted".
- `python3 -m unittest -v` is **already red**: `test_first_item_stale_is_included` fails (`collect_stale` iterates `range(1, len(items))`, `synccli.py:55`, dropping the first element). Pre-existing, unrelated to GOAL.md.
- Python 3.10.11, stdlib only, `argparse`/`json` already imported.

## Open decisions (need your yes/no before Task 2)

1. **`skipped` semantics** — I plan: `skipped = len(source_files) - len(copied)` = files that were *not* copied because already up to date (0 on a first run; N on a second run). Alternative: count of *failed* copies — not observable today because `copy_file` swallows errors, and fixing that means changing `copy_file`, which `incremental.py` depends on. My plan treats failed copies as a documented limitation, not a scope item.
2. **Pre-existing red test** — fixing `collect_stale` is outside GOAL.md, so I plan to leave it red and scope acceptance to "no new failures + the known failure unchanged". Say the word and I'll add the one-line fix as a separate task.
3. **`src`/`dst` values** — I plan to emit the argv values verbatim (not absolute/resolved), so tests are exact-match.

---

## Execution plan

### T0 — Baseline & blast-radius recon
- **Objective:** confirm the baseline, and enumerate every consumer of `sync()`/`copy_file` so the "keep `sync()` stable" constraint is provable rather than assumed.
- **Files:** read-only: `synccli.py`, `test_synccli.py`, `incremental.py`, `DESIGN.md`, `GOAL.md`, `README.md`. **No writes.**
- **Agent:** `explore` (read-only). Not `impl` — there is nothing to build yet.
- **Risks:** `grep` misses dynamic/import-time usage (e.g. `python3 -m synccli` entry point); mitigation: also run `python3 -m unittest -v` and capture the exact failure set.
- **Acceptance:** a written list of every `sync()`/`copy_file` call site with file:line, plus the recorded baseline `Ran 6 tests ... FAILED (failures=1)` (only `test_first_item_stale_is_included`).

### T1 — Design review of the JSON report contract
- **Objective:** settle the contract before code exists: exact key set, key order, value types, `skipped` semantics, `copied` path format (relative, `os.sep`-joined), dry-run meaning, and where the richer report lives without breaking `sync()`.
- **Files:** read `synccli.py`, `test_synccli.py`; write **one** new file `JSON_OUTPUT_DESIGN.md` (short: contract table + rationale + rejected alternatives).
- **Agent:** `design-review` (`cheap-design-review`). Escalate to `strong-design-review` only if the review comes back with a genuine architectural stake unresolved.
- **Risks:** ambiguity between "skipped = unchanged" and "skipped = failures" (Decision 1) — the review must pick one and state it; a wrong pick invalidates T4's assertions. Second risk: a design that changes `sync()`'s return type, which breaks `syncd` per `DESIGN.md:31`.
- **Acceptance:** `JSON_OUTPUT_DESIGN.md` states, unambiguously: (a) the four keys and their types; (b) `skipped` defined as one formula; (c) `sync()` keeps signature `sync(src_root, dst_root, dry_run=False)` **and** `list[str]` return; (d) the mechanism (a new `sync_report(...)` returning a dict, with `sync()` reduced to a thin wrapper returning `sync_report(...)["copied"]`); (e) JSON printed as one object, `json.dumps` + `\n`, key order `copied, skipped, src, dst`; (f) stdout purity rule (diagnostics → stderr only).

### T2 — Implementation of `--json` (core)
- **Objective:** add machine-readable output with `sync()`'s contract untouched.
- **Files:** modify `synccli.py` only — add `sync_report(src_root, dst_root, dry_run=False) -> dict` (returns `{"copied": [...], "skipped": int, "src": str, "dst": str}`), reduce `sync()` to a wrapper preserving signature + `list[str]` return, add `--json` to the `argparse` parser, branch `main()` to emit exactly one JSON object on stdout in JSON mode and keep the existing one-path-per-line loop otherwise. No new imports beyond stdlib already present; no change to `copy_file`; no change to `incremental.py`.
- **Agent:** `impl` (`cheap-code`), briefed from `JSON_OUTPUT_DESIGN.md`. Escalate to `strong-code` only on a demonstrated stall (2 failed attempts) or a major review finding.
- **Risks:** (i) a stray `print` in JSON mode violates "nothing else on stdout" — keep any diagnostics on `stderr`; (ii) changing `sync()`'s return type breaks `incremental.py`/`syncd`; (iii) `skipped` computed from the wrong denominator (must be *source* files, not destination files); (iv) dry-run must not write the destination manifest — the existing early return at `synccli.py:81` must be preserved in the new code path; (v) `copy_file` swallowing errors means `copied` can overstate reality — document, do not silently change.
- **Acceptance:** (1) `python3 -m unittest -v` shows **no new** failures beyond the known `test_first_item_stale_is_included`; (2) `python3 -m synccli SRC DST --json | python3 -m json.tool` succeeds and prints exactly the four keys; (3) `python3 -m synccli SRC DST --json | wc -l` == `1`; (4) `python3 -m synccli SRC DST` output is byte-identical to the pre-change human output (one relative path per line); (5) `git diff synccli.py` shows `def sync(src_root, dst_root, dry_run=False)` unchanged in signature and return; (6) `python3 -m synccli --help` mentions `--json`.

### T3 — Review of the implementation
- **Objective:** catch contract drift, stdout pollution, and `sync()` breakage before tests are written against a possibly-wrong shape.
- **Files:** read-only review of `git diff synccli.py` + `JSON_OUTPUT_DESIGN.md`.
- **Agent:** `review` (`cheap-review`) — a different model lineage than the implementer. Resume the T2 `task_id` for minor findings; a major finding escalates to `strong-code`.
- **Risks:** review that only checks style and misses the `sync()`/`syncd` contract; mitigate by giving the reviewer the explicit checklist from T1(f) + T2's acceptance list.
- **Acceptance:** an explicit verdict (approve / minor list / major) where every finding names file:line and states which T2 acceptance item it threatens; zero unresolved findings classified as minor.

### T4 — Implementation of the tests
- **Objective:** cover the JSON shape and dry-run semantics, per GOAL.md §4, in `test_synccli.py`.
- **Files:** modify `test_synccli.py` only — add a `TestJsonOutput` class (stdlib `io`, `contextlib.redirect_stdout`, `json`) with, at minimum: valid single JSON object on stdout; key set exactly `{"copied","skipped","src","dst"}`; `copied` lists the relative paths; `skipped` == 0 on a fresh pair and == file count on a second (no-op) run; `--json --dry-run` lists what *would* be copied **and** creates no destination file and no manifest; human mode still prints one path per line; stdout in JSON mode parses as exactly one object with nothing else.
- **Agent:** `impl` (`cheap-code`), resuming the T2 session (same feature, same files — context is reusable) if T3 returned only minor findings; fresh session if T3 escalated.
- **Risks:** (i) asserting an `skipped` formula that contradicts T1's decision — the implementer must copy T1's formula verbatim, not re-derive it; (ii) dry-run test accidentally passing because the destination already existed — use fresh temp dirs per test; (iii) capturing stdout while `main()` writes to `sys.stdout` — capture at the `sys.stdout` level, not by monkeypatching `print`; (iv) a test that asserts exact key set will break if T1 later adds keys — that is intended strictness, keep it.
- **Acceptance:** the new tests are named and fail for the *wrong* implementation (verified by temporarily reverting the JSON branch — the impl must demonstrate the red-then-green transition in the commit/run log), and `python3 -m unittest -v` ends with the only known failure being `test_first_item_stale_is_included`.

### T5 — Review of the tests
- **Objective:** confirm the tests actually pin the GOAL contract rather than the implementation's incidental shape.
- **Files:** read-only review of `git diff test_synccli.py` against `GOAL.md` §1–§4 and `JSON_OUTPUT_DESIGN.md`.
- **Agent:** `review` (`cheap-review`), **fresh session** (do not resume the T3 reviewer — its context is a different review target; a fresh reviewer per target is the rule).
- **Risks:** a green suite that proves nothing (tests tautological with the implementation); mitigation: the reviewer must answer "if the implementation printed human lines *and* a JSON object, would a test fail?" — it must.
- **Acceptance:** a per-requirement map from GOAL.md §1, §2, §3, §4 to the specific test method that covers it, with no requirement mapped to "the existing suite"; and the reviewer confirms each new test fails against a deliberately broken implementation.

### T6 — Final verification & docs
- **Objective:** prove the release criteria end-to-end and make the new flag discoverable.
- **Files:** modify `README.md` (one line documenting `--json` / `--json --dry-run` under the existing usage bullet); **no** change to `DESIGN.md` (v2 daemon design, out of scope) and **no** change to `GOAL.md`. Possibly a new `CHANGELOG` entry only if the repo already had one — it does not, so skip.
- **Agent:** `impl` (`cheap-mech` is sufficient for a one-line doc edit) + a final `review` (`strong-review` — the audit-of-last-resort pass over the whole diff, per the pipeline).
- **Risks:** doc drift (README promising a flag that behaves differently); mitigation: the README line must match the T1 contract exactly; a second risk is a "cleanup" of the unrelated `collect_stale` bug sneaking in — explicitly forbidden unless Decision 2 is approved.
- **Acceptance:** the full diff (`git diff`) touches only `synccli.py`, `test_synccli.py`, `README.md`, and the new `JSON_OUTPUT_DESIGN.md`; `python3 -m unittest -v` shows only the known pre-existing failure; the four manual CLI checks from T2's acceptance list reproduce exactly; and the README documents `--json` and the `--json --dry-run` behaviour.

---

## Pipeline shape

`explore (T0) → design-review (T1) → impl (T2) → review (T3) → impl (T4) → review (T5) → impl+final review (T6)`

Escalation is triggered by demonstrated failure (stalled impl, or a major review finding), never by predicted difficulty. The pre-existing red test is deliberately quarantined from this scope unless you approve Decision 2.

**No modifications were applied to the repository.**

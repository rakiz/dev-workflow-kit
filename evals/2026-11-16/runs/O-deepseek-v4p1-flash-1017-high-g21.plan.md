Baseline verified (6 tests, 1 pre-existing failure in `collect_stale`). Repo restored to clean state; no modifications made. Plan below is text-only.

# Execution plan — `--json` output mode + `--dry-run` UX

## Ground truth from the repo

- `sync()` at `synccli.py:72` returns only `to_copy`; it does **not** expose `skipped`, yet `sync()`'s signature/return must stay stable (GOAL constraint). `copied` in dry-run already equals "would copy" (`synccli.py:81-82`).
- `main()` at `synccli.py:90-99` prints one path per line — the only human-mode renderer.
- `copy_file()` swallows `OSError` (`synccli.py:68-69`), so the returned list can over-report success. Relevant to JSON accuracy; **out of scope** to change unless approved.
- `DESIGN.md` describes an unrelated v2 daemon — **distractor, out of scope**. `incremental.py` has its own bugs (mutable default arg `filter_excluded` `incremental.py:10`; `collect_stale` off-by-one `synccli.py:55`) — **out of scope**, already-red baseline.
- Existing red test: `TestCollectStale.test_first_item_stale_is_included` (`test_synccli.py:22-24`) fails against current code. It must not be "fixed" silently (AGENTS: ask before acting); acceptance must be scoped to new tests.

## Global preconditions

- Branch state clean; only `synccli.py` and `test_synccli.py` may change.
- Python 3.10 stdlib only; no new imports beyond `json`/`argparse` already present.
- No commit/push unless explicitly requested.

---

## Task 0 — Baseline recon and semantics freeze
- **Objective:** Confirm callers of `sync()`, exact human-mode output contract, and the only correct definition of `skipped`; record baseline test results.
- **Files:** none (read-only).
- **Pipeline agent:** `explore`.
- **Risks:** Mistaking the pre-existing `collect_stale` failure for a regression; assuming `skipped` includes excluded/unreadable files (it cannot, given the current code); missing a third-party caller of `sync()`.
- **Acceptance criterion:** A report stating (a) every `sync()` call site with `file:line`, (b) verbatim current human-mode stdout for a 2-file sync, (c) baseline `python3 -m unittest -v` result including the known failure, (d) one proposed `skipped` formula tied to the source manifest.

## Task 1 — JSON contract decision gate
- **Objective:** Freeze the output contract before code: exact key set and types (`copied: list[str]`, `skipped: int`, `src: str`, `dst: str`), whether `src`/`dst` are emitted as passed or normalized, `skipped` = files in current source manifest minus `copied` (same in dry-run), serialization placement (`main()` only), and how `sync()` stays untouched (new private helper returning stats vs. re-deriving in `main()`).
- **Files:** none (decision memo only; no design doc file unless requested).
- **Pipeline agent:** `design-review`.
- **Risks:** Changing `sync()`'s signature or return type; double-scanning the tree in `main()` (acceptable but must be a conscious choice); leaking debug output to stdout; ambiguity of `skipped` when the destination manifest holds deleted entries.
- **Acceptance criterion:** Memo answers each point with a chosen option and one rejected alternative, and explicitly states that `sync()` and human mode remain byte-identical.

## Task 2 — Implement `--json` and dry-run semantics
- **Objective:** Add `--json` flag; emit exactly one JSON object on stdout with `copied`, `skipped`, `src`, `dst`; in `--json --dry-run` `copied` is the would-copy set and neither files nor manifest are written; human mode unchanged.
- **Files:** modify `synccli.py`.
- **Pipeline agent:** `cheap-code` (escalate to `strong-code` only on a demonstrated stall).
- **Risks:** (1) `skipped` computed inconsistently with the manifest actually used; (2) any stray `print`/logging breaking stdout purity; (3) accidental `sync()` signature or behavior change; (4) dry-run writing `MANIFEST_NAME` (`synccli.py:85-86` is correctly guarded — must stay so); (5) exit code drift (`main` must keep returning 0); (6) `copy_file`'s swallowed errors making `copied`/`skipped` lie.
- **Acceptance criterion:** On a fixture with 2 changed files: `python3 -m synccli SRC DST --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert set(d)=={"copied","skipped","src","dst"}'` succeeds and stdout contains exactly one line/object; `--json --dry-run` leaves `DST` free of copied files and of `.sync_manifest.json`; `grep -n '^def sync' synccli.py` shows the signature unchanged; plain invocation output matches the baseline captured in Task 0.

## Task 3 — Add JSON-shape and dry-run unit tests
- **Objective:** Add tests covering valid JSON parse of complete stdout, key presence/types, `skipped` arithmetic, dry-run `copied` semantics with no side effects, and human mode remaining one-path-per-line.
- **Files:** modify `test_synccli.py`.
- **Pipeline agent:** `cheap-code` (resume the Task 2 instance — same feature/files).
- **Risks:** Capturing stdout without isolating `argparse` output; tests passing by re-implementing logic instead of exercising `main()`; touching the pre-existing failing `TestCollectStale`; tests depending on filesystem mtime granularity.
- **Acceptance criterion:** `python3 -m unittest -v test_synccli.TestJsonOutput` (new class) passes fully; `python3 -m unittest -v` shows exactly the same failure set as the Task 0 baseline (no new failures).

## Task 4 — Mandatory code review
- **Objective:** Independently audit the diff against GOAL items 1–4 and constraints: stdout purity, single-object JSON, dry-run no-write, unchanged human mode and `sync()` signature, stdlib-only, tests meaningful (not tautological).
- **Files:** none (read-only).
- **Pipeline agent:** `cheap-review` (fresh, self-contained brief; must not inherit Task 2/3 history).
- **Risks:** Reviewer rubber-stamping; scope creep into `incremental.py`/`DESIGN.md`; classifying the pre-existing red test as a regression.
- **Acceptance criterion:** Written verdict with findings categorized **minor** (return to the same `cheap-code` instance) or **major** (escalate to `strong-code`, notifying the user first per cost policy), plus an explicit "no scope creep" confirmation.

## Task 5 — Final acceptance audit
- **Objective:** Re-run the full acceptance matrix on the final tree and confirm the shipped behavior, gated so it only runs if Task 4 produced any finding or the diff touches more than the two allowed files.
- **Files:** none (read-only verification).
- **Pipeline agent:** `review` (strong rung, independent lineage) — optional per the gate above.
- **Risks:** Redundant cost on a trivially clean diff; re-running tests mutating tracked `__pycache__/*.pyc` (restore or exclude before reporting).
- **Acceptance criterion:** All four GOAL items demonstrated by command output in the report; `git status --short` shows only `synccli.py` and `test_synccli.py` (plus pre-existing untracked `__pycache__` restored); known `collect_stale` failure still the only red test.

---

## Open decisions requiring your yes (do not proceed silently)
1. Leave the pre-existing `collect_stale` off-by-one (`synccli.py:55`) and its failing test untouched — confirm "no fix" (default).
2. Treat `copy_file`'s silent `OSError` as a known limitation of `copied`/`skipped` accuracy rather than expanding scope.
3. Ignore `DESIGN.md` (v2 daemon) and `incremental.py` bugs for this release.
4. Whether `src`/`dst` in JSON are emitted verbatim as CLI arguments (recommended) or normalized absolute paths.

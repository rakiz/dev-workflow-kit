## Baseline (verified, read-only)

- Python 3.10.11; suite = 6 tests, **1 pre-existing failure**: `test_first_item_stale_is_included` vs `collect_stale` off-by-one (`range(1, len(items))` at synccli.py:55).
- `sync()` external/internal call sites: `synccli.py:96` (main) and 3 in `test_synccli.py`. `incremental.py` imports only `copy_file`. Only stdout writer in library code: `synccli.py:98` (`print(rel)`).
- Note: running the suite dirties tracked `__pycache__/*.pyc` (repo tracks caches). Unrelated to this work; left untouched.

## Interface decisions that must be pinned before code (gate)

| # | Decision | Recommendation |
|---|---|---|
| D1 | `skipped` meaning | `len(src_manifest) - len(to_copy)` = unchanged files; files that fail to copy still count in `copied` (current `copy_file` swallows `OSError`). Document as known limitation; do not change `sync()` behavior. |
| D2 | `src`/`dst` values | Echo argv strings verbatim (no `abspath`, no trailing-slash normalization). |
| D3 | Extra JSON keys (`dry_run`, `failed`…) | **None.** Spec's object keys are exact; a strict consumer test may reject extras. |
| D4 | `copied` under `--dry-run` | Same ordering as `sync()` returns (sorted scan order); no dst writes, no manifest write. |
| D5 | Pre-existing red test | Out of GOAL scope. Either accept "no new failures" or approve an isolated follow-up fix. Do not silently "fix" it. |

---

## T1 — Constraint confirmation (agent: `explore`)

**Objective:** Confirm the frozen-interface facts the plan depends on, before anyone edits.
**Files:** none (read-only).
**Work:** all `sync()` call sites with `file:line`; every `print`/`sys.stdout` write reachable from `main()`; whether `copy_file`/`copy_many` can emit output; whether anything outside `synccli.py` parses `sync()`'s return value.
**Risks:** missing an internal caller that consumes `sync()`'s list and would break if the return type changes; missing a stdout writer that would corrupt `--json`.
**Acceptance:** report enumerates every call site, every stdout write, and states explicitly whether returning `(copied, skipped)` from an internal helper only (never from `sync`) is safe. Zero files modified (`git status` clean apart from pre-existing `.pyc`).

## T2 — Contract note (agent: `cheap-design`)

**Objective:** Turn D1–D4 into a one-page contract: exact JSON schema, output mechanics (`sys.stdout.write(json.dumps(obj) + "\n")` once, one line), `main()` branch structure, helper name/signature (`_sync_collect(src_root, dst_root, dry_run) -> (list[str], int)`), and the rule that `sync()` stays byte-for-byte behavior-identical.
**Files:** none committed in-repo (note may live in the task report; creating a `.md` requires user approval).
**Risks:** choosing "rescan in `main()` to compute `skipped`" — rejected: double traversal and a TOCTOU window between scan and copy.
**Acceptance:** contract names exact keys, the single-write rule, helper signature, and states `inspect.signature(synccli.sync) == "(src_root, dst_root, dry_run=False)"` as an invariant.

## T3 — Design review gate (agent: `cheap-design-review`)

**Objective:** Read-only critique of T2 before code: stdout purity, dry-run no-write guarantee, exit-code preservation (argparse's 2 on bad args must survive), determinism of `copied`, ambiguity of D1.
**Files:** none.
**Risks:** approving a contract that lets `main()` call `sync()` twice (double copy, wrong `skipped`); approving extra keys.
**Acceptance:** verdict = approve, or a numbered list of must-change items consumed by T2. No code exists yet at this gate.

## T4 — Implementation (agent: `cheap-code`)

**Objective:** Implement `--json` in `synccli.py` only.
**Files:** modify `synccli.py`.
**Work:** extract `_sync_collect()` containing current body of `sync()` plus skipped count; `sync()` becomes a one-line delegate returning `[0]`; add `parser.add_argument("--json", action="store_true")`; in `main()`, JSON branch writes exactly one `json.dumps` line with keys `copied`, `skipped`, `src`, `dst`, else the unchanged `for rel in copied: print(rel)` loop. No new imports, no new deps.
**Risks:** adding a parameter to `sync()` (violates constraint); printing the JSON with `indent`/multiple `print` calls (multi-line ≠ "single object" is fine for JSON parsers but breaks line-based purity checks — prefer one line); touching `incremental.py` or `DESIGN.md` (out of scope).
**Acceptance:** `inspect.signature` invariant passes (D-command below); `python3 -m synccli S D --json` emits one line that `python3 -m json.tool` accepts; `python3 -m synccli S D` output is identical to the pre-change binary for the same inputs; `git diff --stat` shows only `synccli.py`.

## T5 — Tests (agent: `cheap-code`, resume T4 instance)

**Objective:** Add JSON-shape tests to `test_synccli.py`.
**Files:** modify `test_synccli.py` (add `TestJsonOutput`; no edits to existing tests).
**Work:** (a) valid single JSON object, `set(keys) == {"copied","skipped","src","dst"}` via `contextlib.redirect_stdout` on `main()`; (b) dry-run on fresh dst: `copied == ["a.txt"]`, `skipped == 0`, dst file absent, manifest absent; (c) second run after real sync: `copied == []`, `skipped == 1`; (d) human mode: stdout exactly `"a.txt\n"`; (e) purity: full captured stdout parses in one `json.loads` (no interleaved lines); (f) `--json --dry-run` leaves no manifest so a following real sync still copies.
**Risks:** tests that assert dict ordering; asserting on `copied` semantics for failed copies (would encode the D1 limitation as intended behavior — acceptable only if documented); tests that mutate shared `tempfile` state incorrectly (existing pattern uses per-test `setUp`).
**Acceptance:** all new tests pass; existing 5 passing tests still pass; the sole failure remains `test_first_item_stale_is_included` and no test is skipped/xfailed to hide it.

## T6 — Review (agent: `cheap-review`, fresh instance)

**Objective:** Diff review against GOAL, not against the implementer's intent.
**Files:** none.
**Work:** check signature stability, absence of new deps/imports, exact key set, one-object stdout, dry-run no-write, exit code 0 unchanged, human-mode invariance, scope containment.
**Risks:** reviewer confuses `DESIGN.md`'s v2 daemon (explicitly out of scope) with this goal; reviewer demands a fix to `collect_stale` (out of scope); reviewer accepts a `skipped` count that silently changes `sync()` semantics.
**Acceptance:** findings classified minor (→ resume T4/T5 instance) or major (→ stop; escalate per policy). A no-findings verdict must cite the specific lines it checked.

## T7 — Verification & sign-off (agent: orchestrator runs the matrix; `strong-review` only if T6 is major)

**Objective:** Executable proof of the acceptance set.
**Files:** none.
**Commands (each must pass):**
1. `python3 -c 'import inspect,synccli; assert str(inspect.signature(synccli.sync))=="(src_root, dst_root, dry_run=False)"'`
2. `python3 -m unittest -v` → all new tests pass, no new failures vs baseline.
3. `S=$(mktemp -d); D=$(mktemp -d); echo hi > "$S/a.txt"; python3 -m synccli "$S" "$D" --json --dry-run 2>/dev/null | wc -l` → `1`.
4. Same command piping into `python3 -c 'import json,sys; o=json.load(sys.stdin); assert set(o)=={"copied","skipped","src","dst"}; assert o["copied"]==["a.txt"]; assert o["skipped"]==0'`; then `test ! -e "$D/a.txt" && test ! -e "$D/.sync_manifest.json"`.
5. Real `--json` run, then repeat: second object has `copied == []`, `skipped == 1`; manifest exists.
6. Human mode for the same tree prints only the path line(s).
7. `git diff --name-only` → only `synccli.py` and `test_synccli.py`.
**Risks:** smoke tests using a `__pycache__`-bearing tree inflate `skipped` (scan_files excludes hidden *dirs* only, not hidden files); use clean temp trees.
**Acceptance:** commands 1–7 pass verbatim; GOAL.md items 1–4 each mapped to a green check; exit code of a normal `--json` run is `0`.

## T8 — Optional, requires explicit approval: `collect_stale` off-by-one

**Objective:** Decide and, only if approved, fix the pre-existing red test.
**Files:** `synccli.py` (loop bound), no test edits.
**Agent:** `cheap-mech` impl → `cheap-review` (mandatory), separate commit.
**Risks:** `collect_stale` has no production caller today (only tests), so the "fix" is a semantic choice, not a bug forced by usage; the seeded-`seen` test implies index 0 was intended to be eligible.
**Acceptance:** all 6 pre-existing tests green, no change to `sync()`/JSON behavior, isolated diff.

## No-touch list

`incremental.py` (out of GOAL; also has a mutable-default bug and an over-broad `except`), `DESIGN.md` (v2 daemon, separate scope), `README.md` (GOAL does not ask for docs; flag `--json` there only on request), tracked `__pycache__` (do not commit churn).

## Dependencies

T1 → T2 → T3 → {T4 → T5} → T6 → T7; T8 runs only after T7 and only with approval.

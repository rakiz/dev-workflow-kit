## Context snapshot (read-only recon, no modifications made)

**Repo:** `synccli` — 103-line Python module + 40-line `incremental.py` + 55-line unittest file. Stdlib only. CLI entry: `python3 -m synccli src dst [--dry-run]`.

Facts that shape the plan:

| Fact | Location | Consequence |
|---|---|---|
| `sync(src_root, dst_root, dry_run=False) -> list[str]` returns the **attempted** copy list; dry-run returns early (no copy, **no manifest write**) | `synccli.py:72-87` | Signature must stay byte-compatible; dry-run already yields "would copy" |
| `main()` prints one path per line to stdout, returns 0 | `synccli.py:90-99` | Human mode must stay byte-identical; JSON mode must print exactly one JSON object and nothing else |
| `copy_file()` **swallows OSError** and returns `None` | `synccli.py:62-69` | A failed copy is currently indistinguishable from a success → drives "skipped" semantics (D1) |
| `incremental.py:5` imports `copy_file` from `synccli` — the only cross-module dependency | `incremental.py:5` | `copy_file` must keep its "no raise" contract; touching it risks `incremental.copy_many` |
| GOAL claims "internal callers exist" for `sync()` — in-repo there are **none** (DESIGN.md:31 plans a future `syncd` that reuses `sync()`) | `DESIGN.md` | Treat `sync()`'s *signature and return type* as a public contract for the not-yet-written daemon |
| **Baseline suite is RED**: `test_first_item_stale_is_included` fails — `collect_stale` loops `range(1, len(items))`, skipping item 0 | `synccli.py:55`, `test_synccli.py:22-24` | 5 pass / 1 fail. Blocks any "all tests green" acceptance criterion |
| `collect_stale` is not used by `sync()`; `incremental.py` has no tests | — | The failure is unrelated to the GOAL but sits in the same suite |

`python3 -m unittest -v` baseline: `Ran 6 tests … FAILED (failures=1)`.

---

## Decisions to lock before implementation (recommended defaults)

These are the only genuine ambiguities in GOAL.md. Each has a default so the pipeline is executable, but **D0/D1/D2 change observable behavior and need your explicit yes** (per "ask before acting"):

- **D0 — pre-existing failing test.** *Default:* fix `collect_stale` to iterate `range(len(items))` in a dedicated, clearly-labeled task (one-line, `synccli.py:55`); it makes the baseline green so the GOAL's test criterion is verifiable. *Alternative:* leave it red and scope the acceptance criterion to "no new failures". **Needs your call — it is out of GOAL scope.**
- **D1 — `copied` / `skipped` semantics.**
  - *Recommended (low risk, keeps `sync()` and human mode untouched):* `copied` = the relative paths processed for copy — **exactly** `sync()`'s current return value; `skipped` = `len(src_manifest) - len(copied)` = source files not copied because they were already in sync. Consequence: an OSError'd copy still appears under `copied` (pre-existing `copy_file` behavior).
  - *Alternative (truthful, higher risk):* `copied` = only successful writes (requires `copy_file` → returns bool, which touches `incremental.py`'s contract), `skipped` = everything else including failures.
- **D2 — path forms.** *Recommended:* `copied` entries = relative paths with native separators (identical to human-mode output, so both modes agree); `src`/`dst` = `os.path.abspath()` of the given roots (more useful for machine consumers than echoing argv verbatim).
- **D3 — extra keys.** *Recommended:* exactly the four keys `copied`, `skipped`, `src`, `dst` — no extras, so "the JSON shape" stays assertable as specified.
- **D4 — stdout purity.** *Recommended:* in `--json` mode the only stdout write is the single `json.dumps(payload)`; argparse errors stay on stderr with their current exit codes (no exit-code change). No new imports (`json` already imported).

---

## Ordered task plan

### T1 — Baseline & impact recon
- **Objective:** Re-confirm the baseline (`Ran 6 … FAILED (failures=1)`), enumerate every stdout write and every `sync()`/`copy_file` consumer, and confirm no hidden entry points exist, so the implementer's brief is grounded.
- **Files:** read-only across `synccli.py`, `incremental.py`, `test_synccli.py`, `DESIGN.md`, `README.md`. **No writes.**
- **Agent:** `explore` (read-only). Output: a one-page brief — stdout-write inventory, `sync()`/`copy_file` call-site list, baseline test result, the exact `collect_stale` defect.
- **Risks:** Low. Failure mode: agent wanders into DESIGN.md v2 daemon scope — brief it to stay out of `syncd`/daemon work.
- **Acceptance:** Brief lists every `print(`/`sys.stdout` site in the repo, confirms `sync()`'s only in-repo caller is `main()` + tests, and states the baseline as `5 passed, 1 failed (test_first_item_stale_is_included)`.

### T2 — Output-contract design review *(gate before any code)*
- **Objective:** Turn D1–D4 into a frozen contract: exact JSON shape, `copied`/`skipped` definitions, path forms, stdout-purity rule, and the precise test assertions each decision implies. Produce a short decision record.
- **Files:** read-only review of `synccli.py` + `test_synccli.py`; decision record goes in the task report (and, if you want it durable, a new short section appended to `DESIGN.md` — otherwise keep it out of the repo).
- **Agent:** `cheap-design-review` (read-only critique; different model lineage than the implementer).
- **Risks:** Medium — the reviewer may propose changing `copy_file` semantics, which drags in `incremental.py` and violates "no scope creep". Constrain it: *any* contract requiring a `copy_file` signature/behavior change is flagged as out-of-scope, not adopted.
- **Acceptance:** A frozen contract exists that (a) lists the 4 keys and their types, (b) defines `skipped` as a formula over observable state, (c) states the human-mode output is unchanged, (d) names the exact `assert` set the tests will use. You approve it.

### T3 — Implement `--json` in the core *(impl)*
- **Objective:** Add the flag, compute the payload, emit one JSON object on stdout, and keep `sync()`'s signature/return type and human-mode output intact.
- **Files:** modify `synccli.py` — `main()` (argparse + output branch), plus one new internal helper (e.g. `build_report(src_root, dst_root, dry_run=False) -> dict`) that `sync()` wraps so `sync(src_root, dst_root, dry_run=False)` keeps returning `list[str]`; `copy_file` and `incremental.py` untouched.
- **Agent:** `cheap-code` (implementation), briefed with T1 + the T2 contract verbatim. Note for the brief: argparse `dest="json"` collides by name with the imported `json` module inside `main()` — never bind a local named `json`.
- **Risks:** (1) *Contract drift* — helper and `sync()` disagreeing on what was copied → mitigated by T2's frozen definitions. (2) *Signature break* — a changed `sync()` return type breaks the planned `syncd` → mitigated by the wrapper. (3) *stdout pollution* — a stray `print` in a debug path → mitigated by the stdout-purity acceptance test. (4) *Manifest side-effect* — JSON mode must not write the manifest any more than dry-run does (dry-run already returns before the write; keep that). (5) *Exit code* — no new `sys.exit` paths.
- **Acceptance:** `inspect.signature(synccli.sync)` still equals `(src_root, dst_root, dry_run=False)`; `sync()` still returns a `list[str]`; `python3 -m synccli SRC DST` stdout is byte-identical to today's (one path per line); `python3 -m synccli SRC DST --json` stdout is exactly one line that `json.loads` parses to a dict with exactly the 4 agreed keys, `copied` a list of relative paths and `skipped` an `int`; exit code 0 in all three invocations; `--json --dry-run` copies nothing to `dst` and writes no `.sync_manifest.json`.

### T4 — Review of the core diff *(review)*
- **Objective:** Adversarially check the implementation against the T2 contract and the GOAL's four numbered requirements.
- **Files:** read-only diff review of `synccli.py`.
- **Agent:** `cheap-review` (mandatory; read-only, different lineage). Findings classified **minor** (→ back to the same `cheap-code` instance via `task_id`) vs **major** (→ escalate).
- **Risks:** Low-medium. Watch specifically for: a changed `sync()` return semantics, `skipped` counting `dst`-side or manifest-side files, JSON emitted on multiple lines, `dry_run` writing the manifest, and any non-stdlib import slipping in.
- **Acceptance:** Reviewer returns zero open **major** findings, and each of GOAL items 1–4 maps to a cited line in the diff. Minor findings are fixed in the same `task_id` session and re-reviewed.

### T5 — Implement the unit tests *(impl)*
- **Objective:** Add the GOAL-item-4 tests to `test_synccli.py`: JSON is valid JSON; all required keys present with correct types; `copied`/`skipped` values match the contract; dry-run semantics (would-copy list, nothing written to `dst`, no manifest); and a stdout-purity test asserting stdout contains **only** the JSON object (no extra lines) in `--json` mode, plus a human-mode regression test that stdout is still one path per line.
- **Files:** modify `test_synccli.py` (new `TestJsonOutput` class alongside the existing `TestSync`; reuse the `tempfile.mkdtemp()` + `setUp` idiom already in the file). `synccli.py` untouched unless a minor T4 finding requires it.
- **Agent:** `cheap-mech` (small, mechanical, well-scoped test addition) — escalate to `cheap-code` only if a T4 minor finding requires a non-mechanical fix.
- **Risks:** (1) Tests asserting on `sys.stdout` need `contextlib.redirect_stdout` — must not swallow the real stdout of other tests. (2) Tests that pin the *exact* `skipped` formula will fail if D1 changes later → tests must assert the frozen contract only. (3) A test that runs `main()` must not depend on `sys.argv` (call `main([...])` with an explicit argv list).
- **Acceptance:** New tests exist and are meaningful — each fails if the corresponding behavior regresses (verified by at least one deliberate mutation, e.g. flipping `skipped` to `len(src_manifest) + len(copied)`, then reverted); `python3 -m unittest -v` shows the new tests passing; total test count increases by the number of new cases; no pre-existing test was edited or deleted to make the suite pass.

### T6 — Final verification & review *(review)*
- **Objective:** Full-suite green + end-to-end CLI verification of every GOAL clause, then a last read-only review of the complete diff.
- **Files:** read-only; no code changes unless the review raises a finding.
- **Agent:** `cheap-review` (fresh session, self-contained brief — do **not** resume T4's session; the diff has grown).
- **Risks:** Low. Residual known gap (per D1 recommended): a copy that fails with OSError is still counted under `copied` — documented as a pre-existing `copy_file` limitation, not a regression.
- **Acceptance:** `python3 -m unittest -v` → **all green** (subject to D0). Manual CLI matrix all pass: human mode unchanged (one path per line); `--json` stdout is a single parseable JSON object with the 4 keys and correct values; `--json --dry-run` reports would-copy files and leaves `dst` empty with no manifest; exit code 0 everywhere; `git diff --stat` shows changes limited to `synccli.py` (+ `test_synccli.py`, + `README.md` if you want the flags documented) and `synccli.py` imports remain stdlib-only.

---

## Cross-cutting constraints (assert in every task's review)

1. No new dependencies; Python 3.10 stdlib only (`json` already imported).
2. `sync(src_root, dst_root, dry_run=False)` — signature **and** return type (`list[str]`) unchanged; the planned `syncd` (DESIGN.md:31) depends on it.
3. Human mode output byte-identical (one path per line).
4. `--json` mode: exactly one stdout write (the JSON object); everything else on stderr; exit code unchanged.
5. `copy_file`'s no-raise contract preserved — `incremental.py` must keep importing and using it unchanged.
6. Dry-run never mutates `dst` and never writes `.sync_manifest.json`.

## Suggested order of execution

`T1 → T2 (gate) → T3 → T4 → T5 → T6`, with **D0/D1/D2 confirmed before T2** — D1 alone changes what the tests assert, so implementing before it is frozen wastes a review cycle.

## Open items requiring your yes/no before I dispatch the pipeline

- **D0:** fix the pre-existing `collect_stale` failure (recommended) or scope it out?
- **D1:** `copied` = attempted (recommended, low risk) vs. actually-successful (truthful, touches `copy_file`)?
- **D2:** `src`/`dst` = `abspath` (recommended) vs. as-typed?
- **D3:** exactly 4 keys, no extras (recommended)?
- **Extra:** update `README.md` with the new flags (recommended, user-facing), and should the frozen contract be persisted as a short `DESIGN.md` section or kept in the task report only?

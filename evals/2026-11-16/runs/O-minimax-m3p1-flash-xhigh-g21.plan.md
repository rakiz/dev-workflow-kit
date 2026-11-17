## Context (facts the plan rests on)

- `synccli.py` is the only module; the **only** stdout writer is `print(rel)` at `synccli.py:98`. Human mode = one relative path per line.
- `sync(src_root, dst_root, dry_run=False) -> list[str]` (`synccli.py:72`) is the only public API besides `copy_file`; `incremental.py:5` imports `copy_file` (so `copy_file`'s contract is coupled, `sync()`'s is not, today).
- `copy_file` (`synccli.py:62`) **swallows `OSError`** → callers cannot distinguish success from failure. This is the source of the `skipped` ambiguity.
- `sync()` in dry-run returns `to_copy` early and writes **no** manifest and copies nothing (`synccli.py:81-82`) → dry-run "would be copied" is already available for free.
- **Baseline is RED before we start**: `python3 -m unittest -v` → 6 tests, 1 pre-existing failure: `TestCollectStale.test_first_item_stale_is_included` (`collect_stale` starts at `range(1, len(items))`, `synccli.py:55`, dropping item 0 — off-by-one in dead code, unrelated to GOAL). Our work must not be blamed for it and must not silently "fix" it (needs explicit approval, see T7).
- Constraints: Python 3.10.11, stdlib only, no new deps, `sync()` signature stable, exit code unchanged.

## Contract proposal to be ratified (input for T1)

```
--json → stdout is exactly ONE line: json.dumps(payload)   (compact, default separators)
payload key order = copied, skipped, src, dst
  copied  : list[str] of relative paths copied this run (dry-run: WOULD be copied). Sorted ascending.
  skipped : int, source files NOT copied this run (already up to date + copies that failed)
  src,dst : the CLI argument strings exactly as supplied (not resolved/absolutized)
Human mode: byte-identical to today (one relpath per line, same order)
--json --dry-run: dst untouched (no file copied, .sync_manifest.json not written)
exit code: 0 in both modes (argparse errors keep 2). Nothing on stdout except the JSON object.
API: sync(src_root, dst_root, dry_run=False) -> list[str]  (signature unchanged)
     sync_report(src_root, dst_root, dry_run=False) -> dict (new; payload builder)
```

**Open decision D1 (the one real design question)** — what `copied` means when a copy fails, given `copy_file` swallows `OSError`:
- **A (minimal)**: `copied` = attempted list (= today's `sync()` return); failures are invisible and counted as copied. Zero change to `copy_file`.
- **B′ (recommended)**: add `copy_file_checked(src, dst) -> bool`; `copy_file` becomes a thin wrapper with **byte-identical behavior** (so `incremental.py:5` is unaffected). `copied` = actually-copied; failures land in `skipped`. `sync()` then returns the truthful list — the only observable change is in the rare copy-failure path (today it reports files it failed to copy), which needs explicit approval.
- **C**: leave `copy_file` alone, verify copies by stat-ing the destination → no new function, but TOCTOU-ish and costs a stat per file.

---

## Ordered tasks

### T1 — Recon & scope confirmation
- **Objective**: verify the inventory above (stdout writers, callers of `sync()`/`copy_file`, entry points) and confirm the red test is pre-existing and out of scope.
- **Files**: read-only — `synccli.py`, `incremental.py`, `test_synccli.py`, `DESIGN.md`, `README.md`; `git log`/`git show 94c42e1` for anything the tree view hides.
- **Agent**: `explore` (read-only). The orchestrator's inventory above is the expected output — the agent's job is verification + completeness, not rediscovery.
- **Risks**: near-zero. Don't let this task expand into "fix things you noticed".
- **Acceptance**: a memo confirming (a) `synccli.py:98` is the sole stdout writer, (b) `incremental.py` imports only `copy_file`, (c) `python3 -m unittest -v` fails only `test_first_item_stale_is_included` before our change, (d) no other CLI entry point (`python3 -m synccli` → `synccli.py:102`).

### T2 — Contract ratification (design-review)
- **Objective**: ratify the contract above + decide **D1** (A / B′ / C), before any code exists. Cheap to change course here.
- **Files**: none modified (review of the embedded proposal).
- **Agent**: `cheap-design-review`. If it returns "major" stakes on D1 → `strong-design-review` (notify the user first; do not pre-book).
- **Risks**: ambiguity leaking into tests and then hardening; a second contract change after T3.
- **Acceptance**: written decision on D1 and on: compact single-line JSON vs pretty, `src`/`dst` as-provided vs absolutized, path separator in `copied`, `skipped` definition, stdout purity, exit codes, `sync()` content-change approval (D1/B′ only). Output = the final contract text the implementer codes against.

### T3 — Implementation
- **Objective**: implement the ratified contract in `synccli.py` + add JSON tests to `test_synccli.py`.
- **Files**: modify `synccli.py` (add `--json` flag; extract the run into an internal helper returning `{copied, skipped}`; add `sync_report()`; keep `sync()`'s signature and return type; branch `main()` printing either one `print(json.dumps(payload))` or the existing per-path loop; **no** other stdout writes). Modify `test_synccli.py` (new `TestJsonOutput` class + human-mode regression test). Do **not** touch `incremental.py` unless D1=C or B′ requires an export.
- **Agent**: `cheap-code` (pipeline: cheap-code → cheap-review, mandatory per policy).
- **Risks**:
  - computing `skipped` needs the source file count → compute the manifest **once** inside the run and reuse it (no second `os.walk`).
  - dry-run must keep returning early: no copy, no manifest write — a careless refactor makes dry-run mutate `dst`.
  - `copy_file`'s OSError swallowing (D1).
  - JSON payload key **order** must follow the contract (dict insertion order).
  - printing anything else to stdout (a stray debug print) breaks "nothing else on stdout".
  - `__pycache__/*.pyc` are tracked in git and get dirtied by test runs → do not stage them; the repo tracks them, so restore with `git checkout -- __pycache__` if needed.
- **Acceptance**: `python3 -m unittest -v` → the 4 currently-passing tests + all new tests pass, and the **only** failure remains `test_first_item_stale_is_included` (count and identity unchanged). New tests cover: stdout parses with `json.loads` and has exactly the keys `copied, skipped, src, dst`; `copied == ["a.txt"]` on a fresh dst; second run → `copied == []` and `skipped == 1`; `--json --dry-run` → `copied == ["a.txt"]` while `dst/a.txt` and `dst/.sync_manifest.json` do **not** exist; human mode stdout is exactly `"a.txt\n"` and is not JSON; `main()` returns 0 in both modes.

### T4 — Independent review
- **Objective**: review T3's diff against GOAL.md + the ratified contract, from a different model lineage.
- **Files**: read-only (`git diff`, `synccli.py`, `test_synccli.py`).
- **Agent**: `cheap-review`.
- **Risks**: a green suite masking a wrong payload shape; missing stdout-purity assertion; the reviewer missing that the pre-existing red test was pre-existing.
- **Acceptance**: verdict + findings classified minor/major, each with `file:line`, explicitly covering GOAL clauses 1–4 (JSON object with those 4 keys / nothing else on stdout / exit code unchanged; dry-run `copied` = would-be; human mode unchanged; tests added) and the 3 constraints (no new deps, stdlib-only 3.10, `sync()` signature stable), plus an explicit statement that the pre-existing failure is untouched.

### T5 — Fix loop
- **Objective**: close review findings.
- **Files**: as flagged.
- **Agent**: resume the **same** `cheap-code` session (`task_id`) for minor findings — it already holds the contract and the diff; a fresh session would rediscover them. **Major** finding → `strong-code` (fresh session, full brief) **only after notifying the user and stating why the cheap rung was insufficient**; never pre-booked.
- **Risks**: fixing the unrelated red test here instead of T7 (out-of-scope change without approval); scope creep into `incremental.py`.
- **Acceptance**: every finding closed by a diff hunk; `python3 -m unittest -v` shows no failures other than the pre-existing one.

### T6 — Black-box verification
- **Objective**: verify the shipped behavior against GOAL.md end-to-end, independent of the unit tests.
- **Files**: none modified (scratch dirs under the system temp dir).
- **Agent**: `cheap-mech` (mechanical command running) — or `cheap-code` resumed if a fix is needed.
- **Risks**: none (read-only against the CLI).
- **Acceptance**, all commands run in a temp `SRC`/`DST` with `SRC/a.txt`:
  1. `python3 -m synccli SRC DST` → stdout `a.txt\n` only; exit 0; `DST/a.txt` and `DST/.sync_manifest.json` exist.
  2. `python3 -m synccli --json SRC DST` → `json.loads(stdout)` succeeds; keys exactly `{copied, skipped, src, dst}`; `copied == ["a.txt"]`; stdout is a single line and nothing else; exit 0.
  3. `python3 -m synccli --json --dry-run SRC DST2` → `copied == ["a.txt"]`; `DST2/a.txt` and `DST2/.sync_manifest.json` absent; exit 0.
  4. `python3 -m synccli --json SRC DST` (2nd run) → `copied == []`, `skipped == 1`; exit 0.
  5. `python3 -m unittest -v` → same failure set as T3's acceptance.
  All raw outputs pasted verbatim into the final report.

### T7 — Optional, gated: pre-existing red test
- **Objective**: fix the unrelated off-by-one so the suite is green (`synccli.py:55` `range(1, len(items))` → `range(len(items))`; `collect_stale` is dead code — no caller in `synccli.py` or `incremental.py`).
- **Files**: `synccli.py` (1 line).
- **Agent**: `cheap-mech` — but **only after explicit user approval**, since it is outside GOAL's scope.
- **Risks**: changing `collect_stale` semantics for any future caller of the "commit under review" v0.2 module; blurring what our change was responsible for.
- **Acceptance**: `python3 -m unittest -v` → 0 failures; diff is exactly the one line (or the task is dropped on approval decline).

### T8 — Optional, gated: docs
- **Objective**: document the new flag.
- **Files**: `README.md` (one line under the usage bullet) — **only with user approval** (GOAL doesn't ask for docs).
- **Agent**: `cheap-mech`.
- **Acceptance**: README diff is one line; the user approves the wording.

---

## Sequencing / cost notes

T1 → T2 → T3 → T4 → T5 → T6 is the mandatory spine; T7/T8 are opt-in and blocked on explicit user approval. Per the cost guard, no expensive rung (`strong-code`, `strong-design-review`) is booked up front — T2 uses `cheap-design-review`, T4 uses `cheap-review`, and escalation happens only on a demonstrated major finding, with a user notification before invoking it. No further decisions are needed from you beyond: **D1 preference** (A vs B′ — I recommend B′ with approval for the `sync()` content change in the rare failure path) and **approval for T7/T8**.

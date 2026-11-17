Read `GOAL.md`, `README.md`, plus `synccli.py`, `incremental.py`, `test_synccli.py`, `DESIGN.md`, and checked the baseline (`git status` clean, `git log`, `python3 -m unittest -v`).

**Baseline facts that shape the plan**
- `sync()` returns only `copied` (list of rel paths); there is no `skipped` anywhere. `synccli.py:72`.
- Signature to keep stable: `sync(src_root, dst_root, dry_run=False)` — called at `synccli.py:96` (and `DESIGN.md:31` plans to reuse it).
- `--dry-run` already returns `to_copy` without copying or writing the manifest (`synccli.py:81-82`) — the required semantics for GOAL §2 mostly exist.
- **Pre-existing test failure**: `test_first_item_stale_is_included` fails (`collect_stale` uses `range(1, len(items))`, `synccli.py:55`, dropping index 0). Unrelated to GOAL, but it means "all tests pass" cannot be the acceptance bar.
- Latent correctness risk: `copy_file` swallows `OSError` (`synccli.py:68-69`) yet `sync()` still counts the file as copied and records it in the manifest — `"copied"` can over-report. Out of scope, must not be silently "fixed".

---

## Execution plan (ordered)

### T1 — Baseline & caller inventory (explore)
- **Objective:** confirm no other callers/consumers of `sync()` or of `main()`'s stdout than those seen (only `synccli.py:96`, `incremental.py` imports `copy_file` only), and confirm human-mode stdout is exclusively `print(rel)`.
- **Files:** read-only — `synccli.py`, `incremental.py`, `test_synccli.py`, repo-wide grep for `sync(`, `main(`, `print(`.
- **Agent:** `explore`
- **Risks:** an out-of-repo/internal caller pinning exact output format — cannot be seen; assume GOAL is authoritative.
- **Acceptance:** a list of every call site of `sync()`/`main()` and every stdout writer, with `file:line`; explicit confirmation that only `synccli.py:97-98` writes to stdout during a sync run.

### T2 — Settle the open decisions (design-review)
- **Objective:** fix the contract before code, because GOAL under-specifies it. Decisions to resolve:
  - **D1 `skipped` source without touching the `sync()` signature.** Candidates: (a) compute `len(build_manifest(src)) - len(copied)` in `main()`; (b) add a keyword-only opt-in `stats=False` to `sync()`. Recommend (b) only if "stable" is read as "existing positional/keyword callers unaffected"; otherwise (a). Must be decided and justified.
  - **D2 `copied` element format:** relative paths (consistent with human mode and existing tests) vs absolute. Recommend relative.
  - **D3 `src`/`dst` values:** verbatim `argv` strings vs normalized/abspath. Recommend verbatim.
  - **D4 `skipped` meaning:** source files unchanged this run (len(src) − len(copied)), not dst-orphans. Must be stated explicitly.
  - **D5 stdout purity:** single `json.dumps(...)` + `print`, all diagnostics to `stderr`; key order `copied, skipped, src, dst`.
  - **D6 dry-run must not copy and must not write the manifest** (already true — freeze it as a tested invariant).
  - **D7 exit code stays `0`** in all modes.
- **Files:** none written; decision list returned in-message (no new docs unless asked).
- **Agent:** `cheap-design-review`; escalate to `strong-design-review` only on genuine disagreement over D1.
- **Risks:** choosing (b) could be read as violating "keep `sync()` signature stable"; choosing (a) re-walks the tree (minor TOCTOU between the two scans).
- **Acceptance:** every decision D1–D7 has one chosen option plus a one-line justification, and T3/T4 can be implemented without further interpretation.

### T3 — Implement `--json` (impl)
- **Objective:** add `--json` to the parser and a JSON output path in `main()`; human mode stays byte-identical (`print(rel)` per line); implement `skipped` per D1; emit exactly one JSON object on stdout in `--json` mode and nothing else; exit code `0`.
- **Files:** modify `synccli.py` only (`main()` ~`synccli.py:90-99`; plus the minimal `skipped` plumbing decided in T2). No change to `sync()`'s external signature unless T2 chose (b).
- **Agent:** `cheap-mech` (scope is a boolean flag + one branch) → `cheap-code` if T2 chose the `sync()` plumbing route.
- **Risks:** accidentally leaving a `print` in the JSON path (solvable by making the two modes mutually exclusive branches); `skipped` mis-derived; reordering keys.
- **Acceptance:** `python3 -m synccli SRC DST --json` and `--dry-run --json` each print exactly one line parseable by `json.loads` with keys `{copied, skipped, src, dst}` and no other stdout; `python3 -m synccli SRC DST` output is unchanged; `echo $?` is `0`.

### T4 — Tests for JSON shape (impl)
- **Objective:** add unit tests to `test_synccli.py` covering: output is valid JSON (single object), all four keys present, `copied` == first-run copy list, `skipped` correct on a second run, `--dry-run --json` lists would-be copies while creating no dst file and no manifest, human mode is one path per line, exit code `0`.
- **Files:** modify `test_synccli.py` only (new `TestJsonOutput` class; use `contextlib.redirect_stdout`, `tempfile` as already done).
- **Agent:** `cheap-code`
- **Risks:** capturing stdout without hiding a second print (assert captured string has exactly one JSON document, not just "is parseable"); asserting against `abspath`/tmp paths (use `os.path.relpath` expectations per D2); accidentally asserting the pre-existing `collect_stale` failure away.
- **Acceptance:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v` — all new tests pass; the only failure is the pre-existing `TestCollectStale.test_first_item_stale_is_included`, unchanged from baseline.

### T5 — Mandatory review (review)
- **Objective:** adversarial read of the `synccli.py` + `test_synccli.py` diff against GOAL §1–4 and constraints (stdlib only, no new deps, `sync()` stable, Py3.10).
- **Files:** read-only — the two diffs.
- **Agent:** `cheap-review` (fresh instance); any **major** finding → `strong-code`; a major finding in Claude-produced work → `strong-review`.
- **Risks:** `"copied"` over-reporting via swallowed `OSError` (`synccli.py:68-69`) — must be classified out-of-scope, flagged, not fixed silently; mutable default `excluded=[]` (`incremental.py:10`) — same treatment.
- **Acceptance:** verdict + findings classified minor/major, each tied to a GOAL clause; explicit statement that no out-of-scope "drive-by" change was introduced (`git diff --stat` touches only `synccli.py` and `test_synccli.py`).

### T6 — Independent verification (explore, read-only)
- **Objective:** reproduce acceptance from a clean shell without trusting the implementer's claims.
- **Files:** none — run `python3 -m unittest -v`, plus CLI smoke: fresh temp SRC/DST, `--json`, `--dry-run --json`, plain mode, `python3 -m synccli --help`, `python3 -c "import ast,sys; ast.parse(open('synccli.py').read())"`.
- **Agent:** `explore`
- **Risks:** `__pycache__` noise; a stale manifest in the smoke dirs poisoning `skipped`.
- **Acceptance:** transcript shows the exact command/output evidence for every GOAL §1–4 item and confirms the only failing test is the pre-existing `collect_stale` one.

### T7 — README usage line (optional, needs your explicit approval)
- **Objective:** document `--json` and `--dry-run --json`. Not required by GOAL.
- **Files:** modify `README.md` (one bullet under the existing list).
- **Agent:** `cheap-mech`
- **Risks:** scope creep; per the "ask before acting" rule this will not be done unless you say yes.
- **Acceptance:** if approved, README shows both flags and matches actual `--help` output.

**Blocking dependency:** T3 and T4 both depend on T2 (D1 especially). T5 and T6 are mandatory after T3+T4; nothing ships before T6 passes. No files were modified; this response is text-only.

## Context read

- `GOAL.md`: add `--json` (single JSON object on stdout: `copied`, `skipped`, `src`, `dst`), `--dry-run` interplay, human mode unchanged, unit tests; stdlib-only, `sync()` signature stable (internal callers: `incremental.py:5,23` imports `copy_file`; `sync()` is also the future daemon's entry point per `DESIGN.md:31`).
- `README.md`: CLI is `python3 -m synccli`, tests via `python3 -m unittest -v`.
- Current code: `synccli.py` (103 lines) — `sync()` returns list of copied relpaths, already supports `dry_run` by returning `to_copy` **before** copying and before writing the manifest (`synccli.py:81-82`). `main()` prints one path per line (`synccli.py:97-98`).
- `incremental.py` (v0.2, "commit under review") is untouched by this goal; it must keep importing cleanly.

---

## Execution plan (ordered)

### T1 — Baseline & contract exploration
- **Objective:** confirm current behavior and pin the JSON contract ambiguities before coding.
- **Files:** read-only — `synccli.py`, `incremental.py`, `test_synccli.py`, `GOAL.md`, `README.md`.
- **Agent:** `explore`
- **Risks:** `GOAL.md` does not define what `skipped` counts (unchanged files vs. unreadable-copy failures). `copy_file` swallows `OSError` (`synccli.py:67-69`), so "copy failed" is currently **not observable** — counting it would require changing `copy_file`'s contract (risky: `incremental.py:23` depends on it). Recommended resolution: `skipped` = number of source files **not** copied (i.e. `len(src_files) - len(copied)`), i.e. already up-to-date files. Failure counting is out of scope unless explicitly requested.
- **Acceptance:** written statement of the exact JSON schema (key names, types, `copied` ordering = manifest-scan order, `skipped` definition, `src`/`dst` = the exact strings as passed on the CLI) and of the "nothing else on stdout" rule (stdout = one JSON object; all diagnostics to stderr).

### T2 — Design review of the JSON contract
- **Objective:** approve/reject the T1 contract before implementation; check it against `GOAL.md` constraints and the `incremental.py` caller surface.
- **Files:** none modified; spec lives in the task report (optionally `DESIGN.md` append, only if asked).
- **Agent:** `design-review`
- **Risks:** contract drift from GOAL wording; over-engineering (no new deps, no CLI framework change). `--help` output must stay on stdout and is *not* JSON mode (no `--json` given → fine).
- **Acceptance:** written verdict with the final schema, the `skipped` semantics, and confirmation that `sync(src, dst, dry_run=False)` signature and return type stay untouched.

### T3 — Implement `--json` in the CLI
- **Objective:** add `--json` flag; in JSON mode print exactly one JSON object with `copied` (list of relpaths), `skipped` (int), `src`, `dst`; in dry-run mode `copied` = what *would* be copied; human mode byte-identical to today.
- **Files:** modify `synccli.py` — `main()` only (add `parser.add_argument("--json", action="store_true")`, branch the printing path, compute `skipped` from the manifest scan count). Do **not** change `sync()`'s signature/return; if the skipped count can't be obtained from `sync()`'s return value, add an **optional keyword-only** parameter or a separate helper function — never a positional/behavioral change to `sync()`.
- **Agent:** `impl` (cheap-code)
- **Risks:** stdout pollution (any stray `print`, or `argparse` errors — argparse writes usage to *stderr* on error, but `--help` writes to stdout: acceptable, `--help` is not JSON mode); double-printing the copied list; writing the manifest in dry-run mode (already avoided by `synccli.py:81-82` — must be preserved); JSON serialization of non-ASCII/Windows-style relpaths (use `json.dumps` default, `ensure_ascii` default is fine).
- **Acceptance:** `python3 -m synccli --json SRC DST` prints a single line that `json.loads` parses, with exactly the keys `copied`/`skipped`/`src`/`dst`, and stdout contains nothing else; `python3 -m synccli SRC DST` output identical to the pre-change output for the same fixture.

### T4 — Unit tests for JSON shape and dry-run semantics
- **Objective:** cover GOAL item 4 in `test_synccli.py`.
- **Files:** modify `test_synccli.py` — add a `TestJsonMode` class.
- **Agent:** `impl` (cheap-code)
- **Risks:** tests capturing stdout — use `contextlib.redirect_stdout` (stdlib) rather than shell pipes; tests polluting the repo — use `tempfile.mkdtemp()` as the existing tests do; fragile assertions on key order (JSON object order is not semantic — assert on parsed keys, and additionally assert stdout is a single line/object via `json.loads` on the whole captured stdout).
- **Acceptance:** new tests assert (a) stdout parses as JSON and contains the 4 keys; (b) `copied` lists the copied files and `skipped` is an int; (c) with `--dry-run`, `copied` lists the files that *would* be copied, `dst` stays empty and `.sync_manifest.json` is **not** created; (d) human mode still prints one path per line. All pass via `python3 -m unittest -v`.

### T5 — Mandatory review of implementation + tests
- **Objective:** independent review of T3/T4 against `GOAL.md` and the constraints.
- **Files:** read-only review of `synccli.py`, `test_synccli.py` (diff vs `HEAD`).
- **Agent:** `review` (cheap-review)
- **Risks:** reviewer may not run the tests — instruct it to run `python3 -m unittest -v`; findings classified minor (→ back to T3/T4 implementer) vs major (→ escalate).
- **Acceptance:** review report with no unresolved major findings; every minor finding fixed and re-verified by re-running the suite.

### T6 — Final verification and docs
- **Objective:** green suite, end-to-end CLI check (JSON / dry-run / human), and usage docs updated.
- **Files:** modify `README.md` (add the `--json` / `--dry-run` usage note); no other file changes.
- **Agent:** `impl` (cheap-mech for the README edit)
- **Risks:** README drift if the CLI surface differs from T3; `incremental.py` breakage — check `python3 -c "import incremental"` still works and that `sync()`'s signature is unchanged versus `git diff`.
- **Acceptance:** `python3 -m unittest -v` all green; `import incremental` succeeds; `git diff HEAD -- synccli.py` shows no change to the `sync()` signature/return; `python3 -m synccli --json --dry-run SRC DST` emits valid JSON with `copied` non-empty and nothing written to `DST`; README documents both flags.

---

**Notes**
- `DESIGN.md` (the `syncd` daemon, v2) is out of scope for this goal; the only coupling is that `sync()` must remain stable — enforced by T3's constraint and T6's diff check.
- `incremental.py` (v0.2, under review) must not be touched; its `copy_file` dependency is the reason the "skipped = failed copies" reading of `GOAL.md` was rejected in T1.
- No files were modified in this session (read-only planning).

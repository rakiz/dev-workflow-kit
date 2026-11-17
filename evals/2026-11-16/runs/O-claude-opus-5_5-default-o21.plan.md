# Execution plan: `--json` output and `--dry-run` interplay

Nothing was modified. I read GOAL.md, README.md, synccli.py, test_synccli.py, incremental.py and DESIGN.md. I didn't run the test suite.

## Findings that shape the plan

1. **A test likely fails today.** `collect_stale` loops with `range(1, len(items))`, so it skips the first item (`synccli.py:57`). `test_first_item_stale_is_included` should fail before any change. This is outside GOAL.md, so fixing it needs your yes. Either way, we need to know the starting test results.
2. **`skipped` is not defined.** `sync()` returns only the copied list. The likely meaning is "files in the source manifest that were not copied" (unchanged files). It has to be computed without changing `sync()`'s signature, and without scanning the tree a second time (the tree could change between scans).
3. **`copied` can be wrong.** `copy_file` silently ignores `OSError` (`synccli.py:68`), so a file that failed to copy still appears in `copied`. Making JSON report that accurately would change `sync()`'s behaviour, so it needs your yes.
4. **Out of scope:** DESIGN.md (the daemon design, which has its own issues) and incremental.py (it has a shared mutable default argument in `filter_excluded`). I'll leave both alone unless you ask.

## Tasks

**T0 – Record the starting test results**
- Agent: `explore`
- Do: run `python3 -m unittest -v` and confirm the `collect_stale` failure.
- Files: none.
- Risk: none.
- Done when: we have the pass/fail list, and you've said yes or no to fixing finding 1. If yes, add a small `cheap-mech` task (`range(len(items))`) followed by `cheap-review`.

**T1 – Decide the open questions (short design note, in chat)**
- Agent: `cheap-design`, then `cheap-design-review`.
- Questions:
  - What `skipped` means.
  - How to get the counts while keeping `sync()` stable. Proposed: a private `_sync_detailed(src, dst, dry_run) -> (copied, skipped)`, with `sync()` as a thin wrapper that returns `copied`.
  - What `src` and `dst` contain: the paths as given, or absolute paths.
  - Whether errors and argparse output stay on stderr. They do already.
  - Whether the order of `copied` is fixed. It should be sorted.
- Risk: making the design larger than this two-flag CLI needs.
- Done when: every question has a written answer, `sync()`'s signature and return value are confirmed unchanged, and the reviewer approves.

**T2 – Implement `--json`**
- Agent: `cheap-code`.
- File: `synccli.py`
  - Add `_sync_detailed`; `sync()` delegates to it.
  - Add `--json` to `main()`. In that mode, print exactly one `json.dumps({...})` to stdout. Otherwise keep printing one path per line.
  - Keep exit code 0.
- Risks:
  - Something else printing to stdout in JSON mode.
  - Dry-run accidentally writing the manifest.
  - Changing what `sync()` returns.
- Done when: `python3 -m synccli SRC DST --json | python3 -c 'import json,sys;json.load(sys.stdin)'` succeeds, and human-mode output is byte-for-byte the same as before.

**T3 – Add tests to `test_synccli.py`**
- Agent: `cheap-code`. It can be the same session as T2.
- Tests:
  - Capture `main([... , "--json"])` stdout with `contextlib.redirect_stdout` and check it parses as one JSON object with the keys `copied`, `skipped`, `src` and `dst`.
  - With `--json --dry-run`: `copied` lists what would be copied, nothing is written to `dst`, and no manifest is created.
  - On a second run: `copied == []` and `skipped` equals the number of files.
  - Human mode prints one path per line.
  - The return value of `sync()` is unchanged.
- Risk: tests that leave temp directories behind or break across OSes because of path separators.
- Done when: all new tests pass under `python3 -m unittest -v`, and nothing that passed in T0 now fails.

**T4 – Review**
- Agent: `cheap-review`, in a fresh session, with the T2 and T3 diff plus GOAL.md.
- Checks: stdout stays clean, standard library only, Python 3.10 compatible, `sync()` signature stable, `incremental.py` still imports and works.
- Done when: there are no major findings. Minor findings go back to the T2 session through its `task_id`. A major finding goes to `strong-code`.

**T5 – Optional: honest `copied` (finding 3)**
- Only if you approve.
- Agents: `cheap-code` to make `copy_file` report failure, then `cheap-review`.
- Risk: it changes behaviour for internal callers (`incremental.copy_many`).
- Done when: a test with an unreadable source file shows that file missing from `copied`.

**T6 – Update the README**
- Agent: `cheap-mech`, then `cheap-review`.
- Do: document `--json` and how it works with `--dry-run`.
- Done when: the README describes the JSON fields.

## Decisions needed from you
- Fix the `collect_stale` bug (finding 1)?
- Include T5?
- Does the proposed meaning of `skipped` (source files that weren't copied) work for you?

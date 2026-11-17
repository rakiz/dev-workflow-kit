# Review: `db9f464` — v0.2: add exclude filter, batch copy and manifest merge

New file `incremental.py` (40 lines), 3 helpers. Defects below are all in this commit's new code.

## Major

**1. `copy_many` reports failed copies as successful — `incremental.py:23-24`**
`synccli.copy_file` swallows `OSError` internally (`synccli.py:68-69`, `pass  # unreadable source: skip it`), so the dominant failure modes — missing source, unreadable source, write error — never raise. `copy_many` then unconditionally appends `dst` to `done`.
Verified: `copy_many([(missing_src, dst)])` returned `['…/out.txt']` while `dst` was never created. The `except Exception` at line 25 therefore only catches `makedirs` failures, and the function's contract ("list of dst paths done") is false — a caller that advances the manifest on this list believes the destination is in sync while the file is missing, or is a 0-byte truncated file (`open(dst, "wb")` in `copy_file` truncates before the read can fail). Silent data loss / corrupted state.

**2. `filter_excluded` leaks state between calls (mutable default argument) — `incremental.py:10`**
`excluded=[]` is one shared list created once at def time. Every call appends to it and returns it, so results accumulate across invocations.
Verified: `filter_excluded([".git/config"])` → `['.git/config']`; a subsequent `filter_excluded(["a.txt"])` → `['.git/config']` — a path that was never in the caller's input. Any consumer gets a wrong exclusion set that grows with every call, and it is never resettable.

**3. The exclude filter is never applied to the sync path — `incremental.py:7-15`**
`filter_excluded` has no callers, and `sync()` / `build_manifest()` / `scan_files()` (`synccli.py:10-33`) do not consult `EXCLUDE_TOP_DIRS`. So the feature shipped in this commit has no effect: `scan_files` only prunes dot-prefixed *directories* (`synccli.py:14`), so `__pycache__` and a top-level `.sync_manifest.json` in the source are still walked, copied to the destination, and recorded in the manifest — the manifest file syncing itself. Either wire the filter into the scan/build path or the "exclude filter" is inert.

## Minor

**4. `merge_manifest` raises `KeyError` on manifest entries without `mtime` — `incremental.py:38`**
`old[rel]["mtime"]` assumes a fixed entry schema. A manifest written by another tool/version, or a hand-edited/partial entry, aborts the whole merge with `KeyError` — no manifest update at all. Verified.

**5. `merge_manifest` crashes on a corrupt manifest — `incremental.py:33-35`**
`json.load` raises `JSONDecodeError` on truncated JSON. This is a realistic state here: `DESIGN.md:13-15` states the manifest is rewritten in place with no atomicity, so a crash mid-write leaves it truncated. `sync()` has the same pre-existing flaw (`synccli.py:78-79`), but the new helper is the one a daemon poll loop would call every cycle; it should treat an unreadable manifest as empty and rebuild rather than crash.

**6. `merge_manifest` compares mtime only, so it can persist a size that matches neither file — `incremental.py:38-39`**
When the incoming state has an older mtime (clock skew between src and dst, `cp -p`/restore preserving mtime), the old entry is kept verbatim, including its old `size`. The merged manifest then records a `(size, mtime)` pair describing neither the source nor the destination. Since `changed_files` compares the whole state dict (`synccli.py:40`), the file is flagged changed on every subsequent cycle and re-copied forever. Conversely, a same-mtime edit with a different size is decided purely by the tie-break, with no size check.

**7. `merge_manifest` never drops entries for files deleted from the source — `incremental.py:36`**
`merged = dict(old)` retains every previous entry, including files that no longer exist. The merged manifest therefore permanently claims deleted files are present in the destination with stale states, and grows without bound. `changed_files` only iterates `new_manifest` (`synccli.py:39`), so the stale entries are never cleaned or re-validated.

**8. `except Exception: continue` masks programming errors in `copy_many` — `incremental.py:25-26`**
Beyond the swallowed-copy problem in #1, this also hides `ValueError`/`TypeError` from malformed pairs (e.g. a pair that is not a 2-tuple) and any other bug, with no logging and no signal to the caller — the affected file is silently dropped from the batch. The failure is at least observable when an exception escapes; here it is not.

## Notes (not counted as defects)

- No tests were added for the three new helpers, though the repo has `test_synccli.py` and `GOAL.md:10-11` establishes tests as the expected bar for new features.
- `filter_excluded` returns only the excluded set; callers needing the kept set must compute the difference themselves, which the docstring does not state (`incremental.py:11`).
- The exclusion test only inspects the first path component (`incremental.py:13`), so nested `.git` directories and absolute paths are not matched — consistent with the `EXCLUDE_TOP_DIRS` name, but worth stating if the helper is meant to be general.

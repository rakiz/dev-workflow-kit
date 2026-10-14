

Defects in commit 49180d0 (`incremental.py`):

1. **Mutable default accumulator in `filter_excluded` — major.** `excluded=[]` is shared across all calls; each invocation appends to the same list object, so the second call returns the first call's exclusions too (corrupted state, duplicated/wrong results for every caller after the first).

2. **`copy_many` reports failed copies as done — major.** `synccli.copy_file` silently swallows `OSError` (never raises), so `copy_many`'s `except`/`done.append(dst)` path appends every `dst` regardless of whether bytes were actually written. The returned "done" list can claim success for files that were never copied; if the caller then merges those states via `merge_manifest`, the destination manifest records files as synced that don't exist in `dst` — silent data loss that the next sync will skip (manifest says up-to-date).

3. **`copy_many` swallows all exceptions with no error signal — minor.** `except Exception: continue` discards every failure (including ones `copy_file` does propagate, e.g. from `os.makedirs`), and the return value cannot distinguish "skipped" from "copied". Callers have no way to retry or report; combined with (2) the API contract "list of dst paths done" is misleading.

4. **`merge_manifest` compares only `mtime`, ignoring `size` — minor.** When `old[rel]["mtime"] == state["mtime"]` but sizes differ (mtime preserved by a copy tool, clock granularity, clock skew), the tie goes to the new state, but when the old mtime is *newer* (e.g. source file restored/rolled back with an older mtime, or mtime-preserving transfer), the legitimately new source state is dropped — inconsistent with `changed_files`, which treats any `size`/`mtime` difference as changed. The manifest can then disagree with what a full rescan would report.

5. **`merge_manifest` retains stale entries for files deleted from source — minor.** Merging never removes `old` entries absent from `new_manifest`, so the destination manifest accumulates states for deleted files forever; combined with a merge-based workflow, deletions are never represented (contract-wise "merge new file states" is ambiguous, but for a sync manifest this produces a permanently divergent state file).

6. **`filter_excluded` only checks the first path component — minor.** Nested excluded dirs (`pkg/__pycache__/x.pyc`, `sub/.git/...`) are not excluded; only top-level matches. If the intent (per `EXCLUDE_TOP_DIRS` naming) is top-level-only this is fine, but `__pycache__` and `.git` are typically generated at any depth, so real syncs will still copy them.
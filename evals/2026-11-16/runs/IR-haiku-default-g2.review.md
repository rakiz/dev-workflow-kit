**Review of HEAD (3c9f4b7, "v0.2: add exclude filter, batch copy and manifest merge")**

The commit adds one file, `incremental.py`. Defects found:

1. **Major: mutable default argument in `filter_excluded` (incremental.py:9).** `excluded=[]` is created once at definition time. Every call without the argument appends to the same list, so results from earlier calls leak into later ones. Repeated syncs would report stale exclusions and grow memory without bound.

2. **Major: exclusion only checks the top-level path component (incremental.py:12).** `p.split(os.sep)[0]` matches only root-level names. Nested entries such as `pkg/__pycache__/x.pyc`, `sub/.git/config`, or a nested `.sync_manifest.json` are not excluded, despite the function's docstring and name. Sync would copy them. The separator is also hard-coded to `os.sep`, so input using `/` on Windows is misclassified.

3. **Major: `merge_manifest` drops the timestamp comparison when clocks disagree (incremental.py:36).** The newer state wins only if `old.mtime <= state.mtime`, comparing raw mtimes from different hosts. Clock skew can make an actually newer remote state lose, leaving the destination manifest stale while the copy has already happened. This is a silent state-divergence risk.

4. **Minor: deletions never propagate in `merge_manifest`.** Entries in `old` that are absent from `new_manifest` are kept unchanged. Files deleted at the source remain in the destination manifest indefinitely. This may be intended, but nothing in the code or name says so, which makes the contract misleading.

5. **Minor: `copy_many` silently swallows every exception (incremental.py:24-27).** Failures are dropped with no logging and no per-pair error report. The caller receives only the successful `dst` list and cannot tell which pairs failed or why. A partial batch looks like a full one unless the caller diffs the lists itself.

6. **Minor: unguarded manifest parse in `merge_manifest` (incremental.py:32-33).** A truncated or empty `.sync_manifest.json` (for example after an interrupted write) raises `json.JSONDecodeError` and aborts the merge. There is no recovery path, and the file is not written atomically, so a crash during the write can also corrupt it.

I did not verify `copy_file` in `synccli`, since the commit does not touch it.

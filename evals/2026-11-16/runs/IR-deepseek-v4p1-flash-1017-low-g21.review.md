Real defects in `HEAD` (`incremental.py`):

1. **Major — `filter_excluded` mutable default argument** (`incremental.py:10`). `excluded=[]` is shared across all calls, so excluded paths accumulate and leak into later calls. Verified: `filter_excluded([".git/x"])` then `filter_excluded(["keep.txt"])` returns `[".git/x"]` for the second call — the function reports paths from a previous invocation as excluded.

2. **Major — `copy_many` reports failed copies as done** (`incremental.py:19-27`). `copy_file` swallows `OSError` internally (`synccli.py`), so it returns normally even when the copy never happened; `copy_many` then appends `dst` to `done`. Verified with a nonexistent source: the destination is returned in `done` but does not exist. The documented contract ("return the list of dst paths done") is false, and a caller that persists state from `done` records missing files as synced.

3. **Major — `merge_manifest` discards changed files based on mtime ordering** (`incremental.py:38`). A new state whose `mtime` is older than the recorded one is dropped even when `size`/content differ (restored files, preserved timestamps, clock skew). Verified: old `{size:10, mtime:2000}` vs new `{size:99, mtime:1000}` keeps the stale old entry, so the destination can remain permanently out of date after a merge. It also disagrees with `synccli.changed_files`, which compares states by inequality, not mtime ordering.

4. **Minor — `merge_manifest` never writes the result** (`incremental.py:30-40`). The docstring says "merge into the destination manifest," but it only returns a dict; a caller trusting the docstring gets an unchanged file on disk (no state persisted).

5. **Minor — `filter_excluded` only checks the top path component** (`incremental.py:13`). Nested paths like `pkg/.git/config` or `pkg/__pycache__/x.pyc` are not excluded (`"pkg"` is the first component), so VCS/cache data can be synced despite the exclusion intent implied by `EXCLUDE_TOP_DIRS`.

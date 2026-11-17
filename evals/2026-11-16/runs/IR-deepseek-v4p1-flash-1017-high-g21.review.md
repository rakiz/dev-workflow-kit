Reviewed `git show HEAD` (adds `incremental.py`). Real defects:

**1. Major — `filter_excluded` mutable default `excluded=[]`**
`incremental.py:11`. The list is created once and shared by every call; each call appends to it. In a polling loop (DESIGN.md targets 500 ms polls) this leaks memory forever and returns entries from prior batches, i.e. paths not in the current `paths` argument. Callers get silently contaminated exclusion results. Should be `excluded=None` → new list.

**2. Major — `copy_many` reports success for copies that failed**
`incremental.py:21-29`. It calls `synccli.copy_file`, which swallows `OSError` (`synccli.py:70-72`) and returns normally on unreadable source or a failed/partial write. `copy_many` then appends `dst` to `done`, so failed or truncated copies are reported as completed. The `except Exception: continue` is unreachable for copy failures (the exception never propagates) while still hiding any other error. The API exposes no failure list, so data loss is undetectable.

**3. Minor — `merge_manifest` ignores `size`, only compares `mtime`**
`incremental.py:39`. Two states with equal mtime but different size/content resolve to the old entry, leaving the merged manifest stale (contradicts DESIGN.md's "mtime + size" detection). Additionally `old[rel]["mtime"]` / `state["mtime"]` raise `KeyError` on any manifest entry missing `mtime` (external/legacy manifest) instead of treating it as changed.

**4. Minor — `filter_excluded` only matches plain relative paths**
`incremental.py:14-15`: `p.split(os.sep)[0]`. Absolute paths (`/x/.git/...` → first component `""`) or `./`-prefixed paths never match, so exclusion silently does nothing when callers pass anything but bare relative paths. Worth pinning the expected path form given there is no caller yet.

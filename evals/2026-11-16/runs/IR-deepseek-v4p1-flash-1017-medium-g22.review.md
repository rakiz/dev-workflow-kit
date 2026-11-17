Review of `HEAD` (`7b972c4`, adds `incremental.py`):

**1. `filter_excluded` uses a mutable default argument — major**
`incremental.py:10` — `excluded=[]` is created once and shared across all calls. Every invocation without an explicit list appends to the same list, so paths excluded during one sync leak into later, unrelated calls. The function then returns a growing set of "excluded" paths, silently excluding files that should have synced.

**2. `copy_many` reports failed copies as done — major**
`incremental.py:23-24` — `copy_file` (`synccli.py:62-69`) swallows `OSError` internally and returns normally, so `copy_file(...)` never raises for a failed write. `done.append(dst)` therefore records destinations that were never written, and the return value falsely claims success.

**3. `copy_many` silently swallows all exceptions — major**
`incremental.py:25-26` — bare `except Exception: continue` provides no logging and no failure signal. Any non-`OSError` failure (or future regression in `copy_file`) vanishes; the caller cannot tell which pairs failed, so partial syncs look complete.

**4. `merge_manifest` compares only `mtime`, ignoring `size` — minor**
`incremental.py:38` — freshness is decided solely on `mtime`, while the project's documented change detection is mtime **+ size** (`DESIGN.md:15`). A changed file whose mtime is not newer than the stored state (restored file, preserved timestamps, clock skew) is dropped even when its size/content changed, leaving a stale manifest entry and the file unsynced.

**5. `merge_manifest` never persists the merge — minor**
`incremental.py:30-40` — the name and docstring ("Merge new file states into the destination manifest") imply the destination file is updated, but the function only reads `dst_manifest_path` and returns a dict. A caller trusting the contract would leave the on-disk manifest stale.

**6. `merge_manifest` assumes well-formed old entries — minor**
`incremental.py:38` — `old[rel]["mtime"]` raises `KeyError`/`TypeError` (uncaught) if the existing manifest has a legacy or malformed entry missing `mtime` or not a dict, aborting the merge instead of handling it.

Note: `filter_excluded` also returns the *excluded* subset rather than the paths kept, which contradicts what the name `filter_excluded` implies; if a caller does `paths = filter_excluded(paths)` expecting a filtered set, it will sync exactly the wrong files (misleading API contract, minor).

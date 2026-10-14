

Both confirmed empirically. Defects in `incremental.py`:

**Major**

1. **`filter_excluded` — mutable default accumulator** (incremental.py:10). `excluded=[]` persists across calls, so every call returns all previously-excluded paths plus new ones. Verified: a second call with only `ok.txt` returns `['.git/config']` from the first call. Corrupted results for any caller invoking it more than once per process.

2. **`copy_many` — reports failed copies as done** (incremental.py:18-27). `synccli.copy_file` swallows `OSError` internally (synccli.py:68-69), so an unreadable/missing source never raises — `copy_many` appends `dst` to `done` anyway. Verified: a nonexistent source still appears in the returned "done" list. The contract ("list of dst paths done") is violated, and a caller treating `done` as "synced" (e.g., recording it in a manifest) would silently mark uncopied files as synced — data loss. The `except Exception: continue` additionally discards which pairs failed with no error channel at all.

**Minor**

3. **`merge_manifest` — `KeyError` on entries without `"mtime"`** (incremental.py:38). `old[rel]["mtime"]` assumes every legacy entry has the key; a manifest entry missing it (older/corrupt manifest) crashes the whole merge instead of treating it as replaceable.

4. **`filter_excluded` misses nested `__pycache__`** (incremental.py:13). Only the first path segment is checked, so `pkg/__pycache__/x.pyc` — the common case — passes through the exclusion filter. (`EXCLUDE_TOP_DIRS` suggests top-level-only is deliberate, but for `__pycache__` that makes the exclusion largely ineffective.)

Not defects: `merge_manifest` keeping entries absent from `new_manifest` is consistent with "merge" semantics, and returning the dict without writing is consistent with the docstring.
Reviewed `git show HEAD` (adds `incremental.py`), cross-checked against `synccli.py`, and reproduced the behaviors below.

## Real defects

**1. MAJOR — mutable default argument accumulates across calls** (`incremental.py:10`)
`filter_excluded(paths, excluded=[])` shares one list for every call that omits `excluded`. Confirmed:
```
call1(["a",".git/x","b"]) -> ['.git/x']
call2(["c.txt"])          -> ['.git/x']   # stale entry from call1
call3(["d.txt"])          -> ['.git/x']
```
The result claims paths are excluded that were not in the current input. Any caller using the return value as "this sync's exclusion set" will silently skip files that should be synced → data loss / wrong sync state. It also mutates a caller-supplied list in place.

**2. MAJOR — `copy_many` reports failed copies as done** (`incremental.py:18-27`)
`copy_file` swallows `OSError` and returns normally, and `copy_many` appends `dst` to `done` unconditionally; additionally `except Exception: continue` hides `makedirs`/other failures with no signal. Confirmed: copying a nonexistent source returns `done == [dst]` while the destination does not exist. The documented contract ("list of dst paths done") is misleading; a manifest built from `done` would record never-copied (or partial) files as synced → silent data loss.

## Minor

**3. MINOR — `merge_manifest` raises `KeyError` on a manifest with a different schema** (`incremental.py:38`)
`old[rel]["mtime"]` assumes every existing entry has `"mtime"`. An older/foreign manifest lacking that key aborts the merge instead of degrading gracefully.

**4. MINOR — `merge_manifest` never removes entries absent from `new_manifest`** (`incremental.py:36-40`)
Files deleted from the source remain in the merged manifest forever, so the manifest no longer reflects the source tree (stale/diverging state). If "merge" is intentionally a union this is fine, but for a sync manifest it is a semantic gap.

**5. MINOR — nested `__pycache__` is not excluded** (`incremental.py:13`)
Only the first path component is matched. `__pycache__` is almost always nested (e.g. `sub/__pycache__/x.pyc`, first component `sub`), so that entry in `EXCLUDE_TOP_DIRS` is effectively dead and cache files get synced. (`scan_files` does not prune `__pycache__` either, since it only prunes dot-prefixed dirs.)

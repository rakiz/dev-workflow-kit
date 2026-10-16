Review of `HEAD` (`9af5be4` — `incremental.py` only, `synccli.py` out of scope):

**1. `incremental.py:10` `filter_excluded(paths, excluded=[])` — mutable default — major**
Shared list across calls. 2nd call returns 1st call's results accumulated (`excluded.append` mutates default). Corrupted state / wrong filter result; non-idempotent API.

**2. `incremental.py:6,13` `EXCLUDE_TOP_DIRS` + shallow check — major**
Set mixes dirs (`.git`, `__pycache__`) with file (`.sync_manifest.json`). Check `p.split(os.sep)[0] in EXCLUDE_TOP_DIRS` only inspects top component, misses nested `a/.git/...`, `a/__pycache__/…`, `a/.sync_manifest.json`. Excluded internals will be synced (data leak / corrupted sync).

**3. `incremental.py:18` `copy_many` silent `except Exception: continue` — major (misleading contract / silent data loss)**
Returns `done` as success list with no error reporting/logging. Caller cannot distinguish I/O failure from success; if caller advances manifest based on attempted set, destination is left stale/incomplete with no signal. Broad `Exception` also hides programming errors.

**4. `incremental.py:30` `merge_manifest` never deletes — major**
Merges `old` then only upserts from `new_manifest`. Entry in `old` absent from `new_manifest` (deleted in source) is retained forever. Manifest grows unbounded, destination never cleans stale files — corrupted state.

**5. `incremental.py:38` mtime guard `old[rel]["mtime"] <= state["mtime"]` — major**
If source mtime regresses (clock skew, `git checkout`, restore) update is skipped even when `size`/content changed. Source change is lost; destination remains stale. Comparison should be content/state-based, not monotonic mtime.

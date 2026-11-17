Real defects in `HEAD` (`23fedd7`, `incremental.py`):

### Major

1. **False success reporting / silent data loss in `copy_many` (`incremental.py:18-27`)**
   `synccli.copy_file` catches `OSError` internally and returns `None` without raising. Because `copy_many` unconditionally executes `done.append(dst)` after `copy_file(src, dst)` returns, any failed copy (unreadable/missing source, permission error, write failure) is still appended to `done` and reported to the caller as completed.

2. **Swallowed exceptions in `copy_many` (`incremental.py:22-25`)**
   `except Exception: continue` silently discards any exception that does escape (such as `os.makedirs` raising `OSError` in `copy_file`), giving callers no way to detect or log failed copies.

3. **Shared mutable default argument in `filter_excluded` (`incremental.py:10-15`)**
   `def filter_excluded(paths, excluded=[]):` reuses the same list object across all calls that omit `excluded`. Subsequent calls accumulate paths from prior calls, corrupting the returned result.

4. **Stale manifest state on rollback / older mtime in `merge_manifest` (`incremental.py:37-39`)**
   `old[rel]["mtime"] <= state["mtime"]` refuses to update an entry when `new_manifest` has an older `mtime` (e.g., `git checkout`, restored backup, or clock skew) even if `size` changed. This leaves the manifest out of sync with the actual file and inconsistent with `synccli.changed_files` (which checks `old_manifest[rel] != state`).

5. **Deleted files are never removed in `merge_manifest` (`incremental.py:36-39`)**
   `merged = dict(old)` retains every key from `old` that is absent from `new_manifest`, so deleted files remain in the manifest indefinitely.

### Minor

6. **Nested excluded directories/files are not matched in `filter_excluded` (`incremental.py:13-14`)**
   `p.split(os.sep)[0] in EXCLUDE_TOP_DIRS` only checks the first path segment. Nested `__pycache__` directories (e.g., `pkg/__pycache__/mod.pyc`), paths with a leading `./` (e.g., `./.git/HEAD`), or paths using `/` on Windows are not excluded.

7. **Misleading contract in `merge_manifest` (`incremental.py:30-40`)**
   Despite taking `dst_manifest_path` and stating `"Merge new file states into the destination manifest"`, `merge_manifest` never writes `merged` back to `dst_manifest_path`—it only returns the dict. Also, if `dst_manifest_path` exists with truncated/corrupt JSON, `json.load` raises `JSONDecodeError` instead of recovering or reporting a clear state error.

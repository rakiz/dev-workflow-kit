### Defects in `HEAD` (`ef271b7` — `incremental.py`)

1. **`filter_excluded`: Mutable default argument corrupts results across calls (`incremental.py:8-13`) — Major**
   `excluded=[]` is mutated in place via `excluded.append(p)` and returned. Every call to `filter_excluded(paths)` that relies on the default argument accumulates excluded paths from all prior calls in the process, returning bogus results and leaking state across invocations.

2. **`copy_many`: Failed copies are falsely reported as succeeded (`incremental.py:16-25`) — Major**
   `copy_many` wraps `copy_file(src, dst)` in `try ... except Exception` and appends `dst` to `done` if no exception escapes. However, `synccli.copy_file` internally catches and swallows `OSError` on `open`/`read`/`write` (`synccli.py:65-69`). When a file copy fails (e.g., missing/unreadable `src`, permission error on `dst`, or disk full mid-write leaving a truncated `dst`), `copy_file` returns normally and `copy_many` appends `dst` to `done`, causing silent data loss / desynchronization when callers treat `done` as synced.

3. **`merge_manifest`: Misleading API contract / does not persist to `dst_manifest_path` (`incremental.py:28-38`) — Major**
   The function accepts `dst_manifest_path` and its docstring states *"Merge new file states into the destination manifest"*, yet it only reads `dst_manifest_path` and returns the dict in memory without ever writing the merged manifest back to disk. Callers expecting the destination manifest file to be updated are left with an unupdated manifest on disk.

4. **`merge_manifest`: Rejects valid updates when `mtime` moves backward (`incremental.py:35-37`) — Minor**
   `old[rel]["mtime"] <= state["mtime"]` silently drops updates where a source file was rolled back, restored from backup/archive, or replaced by a file with an older `mtime` (even if `size` differs), leaving the manifest out of sync with the actual source state and inconsistent with `synccli.changed_files` (`old_manifest[rel] != state`).

5. **`filter_excluded`: Fragile path-component splitting (`incremental.py:10-11`) — Minor**
   `p.split(os.sep)[0]` is not normalized before checking `EXCLUDE_TOP_DIRS`: relative paths prefixed with `./` (e.g. `./.git/config`) or paths using `os.altsep` (e.g. `/` on Windows) have first component `"."` or the unsplit path and bypass the exclusion filter completely.

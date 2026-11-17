## Review — `git show HEAD` (v0.2, new file `incremental.py`)

### Major

**1. `copy_many` reports failed copies as successful (`incremental.py:20-28`)**
`copy_file` swallows `OSError` internally (`synccli.py:65-69`), so it never raises for an unreadable/missing source — the `try/except` in `copy_many` is effectively dead and `done.append(dst)` records destinations that were never written. Verified: copying a nonexistent source returns `done == [dst]` while `dst` does not exist. A caller that then records these paths in the manifest produces a destination that permanently claims to have files it never received — silent data loss.

**2. `merge_manifest` never persists the merge (`incremental.py:31-40`)**
It reads `dst_manifest_path` but only returns a dict; the destination manifest file is left untouched (verified: on-disk content unchanged). The docstring ("Merge new file states into the destination manifest") promises a state update that does not happen — a misleading API contract and a no-op for any caller that does not know to write the result itself.

**3. `filter_excluded` uses a mutable default argument (`incremental.py:13`)**
`excluded=[]` is created once and shared across all calls, so exclusions accumulate between calls (verified: a second call with unrelated paths returns the first call's exclusions). In a daemon/polling loop this leaks state unboundedly and can exclude paths that were never part of the current input.

### Minor

**4. `merge_manifest` compares only `mtime`, contradicting the rest of the codebase**
`changed_files` (`synccli.py:40`) compares the whole state (`size` + `mtime`); `merge_manifest` uses only `old[rel]["mtime"] <= state["mtime"]`. A file whose content changed but whose mtime was preserved (restore from backup, `tar -x`, clock skew) is treated as unchanged, so the destination keeps stale content — and with `<=`, an identical mtime with a different size overwrites unconditionally.

**5. `merge_manifest` never prunes deleted entries**
Files absent from `new_manifest` stay in the merged manifest (`gone.txt` above survives). A file deleted at the source and later recreated with identical size/mtime is then seen as unchanged by `changed_files` and never re-copied.

**6. `merge_manifest` raises `KeyError` on manifests lacking `"mtime"`**
`old[rel]["mtime"]` is unguarded, so any manifest written by a different/older version (or a hand-edited one) crashes the merge instead of being treated as changed.

**7. `filter_excluded` name/return-value mismatch**
Despite the name, it returns the *excluded* list, not the subset to keep; a caller writing `paths = filter_excluded(paths)` inverts the filter and syncs exactly the excluded set. Additionally, only the first path segment is checked, so nested `sub/.sync_manifest.json` and `sub/.git/...` are not excluded despite being in `EXCLUDE_TOP_DIRS`.

**8. Failures in `copy_many` are silently discarded (`incremental.py:23-25`)**
`except Exception: continue` reports nothing, contrary to the error-handling contract in `DESIGN.md` ("log to stdout and continue"), and it also hides genuine programming errors.

**9. `EXCLUDE_TOP_DIRS` mixes a directory and a file**
It is named "TOP_DIRS" but contains `.sync_manifest.json`, a filename; the first-segment check only works by coincidence for that entry.

### Notes
- `scan_files` already skips dot-directories (`synccli.py:14`), so the `.git` exclusion is redundant for the normal path; the manifest file exclusion is the only load-bearing one.
- The new module is not covered by `test_synccli.py`.

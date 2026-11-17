**Defects in commit 8e1e7e3 (new file `incremental.py`)**

**Major**

1. `incremental.py:10-15` — `filter_excluded` returns the *excluded* paths but does not filter the input list, while its name promises the opposite. A caller doing `paths = filter_excluded(paths)` gets exactly the set of files that must *not* be synced, and the input `paths` list is left untouched (so a caller ignoring the return value syncs everything). The name/docstring/return value disagree; the function is not usable as written.

2. `incremental.py:10,14` — mutable default argument `excluded=[]` is shared across calls. Verified: after `filter_excluded([".git/config"])`, a later `filter_excluded(["ok.txt"])` returns `['.git/config']` — state leaks between calls and the list grows without bound across a polling daemon.

3. `incremental.py:18-27` — `copy_many` reports copies that never happened. `synccli.copy_file` swallows `OSError` internally (`synccli.py:68-69`) and returns `None`, so the `try/except` here is dead code and `done.append(dst)` runs even when the source was unreadable. Verified: `copy_many([("/nonexistent/x", dst)])` returns `['.../x']` while the destination file does not exist. Callers get a success list for a failed sync — silent divergence/data loss.

4. `incremental.py:30-40` — `merge_manifest` never writes the merged manifest back to `dst_manifest_path`; the path is only read. Verified: after `merge_manifest(path, {...})` the file still does not exist on disk. Any caller that assumes the merge was persisted (the function name and its path argument both imply that) silently loses the merged state, and the manifest on disk stays stale forever.

5. `incremental.py:38` — the merge decision compares only `mtime` and ignores `size`, unlike the rest of the codebase where `synccli.changed_files` compares the whole state dict (`synccli.py:40`). If a file is replaced with different content and a *backwards* mtime (restore from backup, `rsync -t`, clock skew), the old entry is kept: verified `merge_manifest` with old `{size:10,mtime:100}` and new `{size:99,mtime:50}` returns the old state. The persisted manifest then describes a state that never existed → the file is re-detected as changed and re-copied on every cycle (endless re-copy in the daemon design).

**Minor**

6. `incremental.py:13` — `p.split(os.sep)[0]` only inspects the first path component, so `sub/.git/config` and `sub/.sync_manifest.json` are not excluded (verified). The set is named `EXCLUDE_TOP_DIRS`, but the docstring claims "paths that must be excluded", which the implementation does not deliver for nested paths.

7. `incremental.py:13` — for absolute paths the split yields `""` as the first component, so nothing is ever excluded (verified: `/tmp/.git/config` passes through). Since callers naturally hold absolute roots, the filter silently no-ops.

8. `incremental.py:36` — entries present in `old` but absent from `new_manifest` are always retained. As a manifest merge for the destination this means a deleted source file stays in the manifest indefinitely; the removal semantics are neither implemented nor documented.

9. `incremental.py:34-35` — `json.load` on an empty or truncated manifest raises `JSONDecodeError`/`JSONDecodeError` on zero-byte file, aborting the merge; and line 38 raises `KeyError` if an old entry lacks `"mtime"`. No guard for corrupt/partial state (the manifest is rewritten in place, so a crash mid-write leaves exactly this state).

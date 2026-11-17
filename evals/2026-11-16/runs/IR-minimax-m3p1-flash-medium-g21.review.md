Reviewed `git show HEAD` (ec71ccf, new file `incremental.py`, 40 lines) against the existing `synccli.py` semantics.

## Major

1. **`incremental.py:10-15` — `filter_excluded` returns the opposite of what the name implies.** It returns the *excluded* list, never the paths to sync. The obvious caller (`paths = filter_excluded(paths)`) inverts the sync set: the junk (`.git/...`) gets synced and every real file is dropped. The docstring ("Return the subset of paths that must be excluded") contradicts the name, so either the return value or the name is wrong — the API contract is unusable as written.

2. **`incremental.py:10,14` — mutable default argument `excluded=[]` leaks state across calls.** Verified: `filter_excluded(['a.txt','.git/config'])` → `['.git/config']`, then a later `filter_excluded(['b.txt'])` → `['.git/config']` — a path never passed in. Every subsequent call is polluted with prior exclusions. Should be `excluded=None` + local list.

3. **`incremental.py:21-27` — `copy_many` reports copies that never happened.** `synccli.copy_file` swallows `OSError` internally (`synccli.py:66-69`), so it never raises; `copy_many` appends `dst` to `done` unconditionally. Verified: `copy_many([('/tmp/nonexistent','/tmp/t1/out.txt')])` → `['/tmp/t1/out.txt']` while the file does not exist. Silent data loss with a false "done" list.

4. **`incremental.py:30-40` — `merge_manifest` never writes to `dst_manifest_path`.** It reads the destination manifest and returns a merged dict, but the file on disk is untouched (verified: file unchanged after merge). The docstring says "Merge new file states *into* the destination manifest"; callers who trust that get a manifest that was never persisted, and every merged state is lost unless the caller knows to write it back.

5. **`incremental.py:38` — merge compares `mtime` only and ignores `size`,** while `synccli.changed_files` compares the full `(size, mtime)` state. A file edited with a preserved or older timestamp (same-second edit, `cp -p`, restored backup) is silently dropped: `merged` keeps the old state and the new state is discarded, so the destination diverges from the source while the manifest claims otherwise.

## Minor

6. **`incremental.py:36-39` — deletions never propagate.** Entries absent from `new_manifest` are kept in `merged` forever; the manifest grows unbounded with stale paths and removed source files are never signalled for cleanup.

7. **`incremental.py:34-35` — unguarded JSON load.** An empty or truncated destination manifest (e.g. a previous crash mid-write) raises `JSONDecodeError`; `old[rel]["mtime"]` at line 38 raises `KeyError` on entries lacking `mtime`.

8. **`incremental.py:36` — shallow copy aliasing.** `merged = dict(old)` copies references, so `merged[rel]["size"] = ...` mutates the caller's `old`/source state dicts in place.

9. **`incremental.py:25-26` — `except Exception: continue` discards all error information** (no log, no error counter, no re-raise). Combined with #3 the return value cannot distinguish success from failure.

10. **`incremental.py:7,13` — exclusion matches only the first path component**, so `.git/` or `__pycache__/` nested under a subdirectory are not excluded, despite the constant being named `EXCLUDE_TOP_DIRS`; and `".sync_manifest.json"` is a file, not a directory, so the constant's name is inaccurate. (`synccli.scan_files` already skips dot-directories at every level, so the `.git`/`__pycache__` entries are largely redundant.)

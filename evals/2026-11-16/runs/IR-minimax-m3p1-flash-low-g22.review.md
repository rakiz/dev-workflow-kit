Reviewed `git show HEAD` (adds `incremental.py`) against `synccli.py` (existing `copy_file` contract).

**Major**

1. `copy_many` reports success for files that were never copied → silently corrupted destination. `synccli.copy_file` opens the destination with `"wb"` (truncating it) and swallows `OSError` itself, so on a mid-copy read/write failure the destination is left truncated or partial, yet `copy_file` returns normally and `copy_many` appends `dst` to `done` (incremental.py:19-24). The caller treats that as "synced", so the manifest records a file that is empty/short and the next incremental pass may skip it. Data loss, not just a missing error message.

2. `filter_excluded` has a shared mutable default argument → state leaks between calls (incremental.py:10). `excluded=[]` is created once at function-definition time and appended to on every call that omits the argument, so a second call returns paths from the first call plus its own. Callers that then subtract "excluded" from the candidate set silently drop valid files from the sync set.

**Minor**

3. `filter_excluded` only inspects the first path component (`p.split(os.sep)[0]`), so nested `.git/`, `__pycache__/` and nested `.sync_manifest.json` are not excluded — only top-level ones are. Also `.sync_manifest.json` is a file, not a directory, and it is matched only as a top-level entry.

4. `filter_excluded` returns only the excluded paths; the caller has no direct way to obtain the paths to sync. The name and docstring ("Return the subset of paths that must be excluded") read like a `filter` that returns keepers, so the natural usage `paths = filter_excluded(paths)` produces the exact opposite set from what the name suggests — misleading API contract.

5. `merge_manifest` never writes to `dst_manifest_path` (incremental.py:30-40). It reads the destination manifest and returns a merged dict; the on-disk manifest is untouched. Given the parameter name and the docstring ("Merge new file states into the destination manifest"), callers can reasonably assume the merge was persisted — the next sync will redo the work and, worse, the manifest can be lost on crash without any error.

6. `merge_manifest` compares `mtime` only and ignores `size`. A file whose content changed but whose mtime is older or equal (clock skew, `rsync --times`, restore from archive, coarse filesystem mtime granularity) is silently ignored, so the old content stays in the destination indefinitely with no indication.

7. `merge_manifest` raises `JSONDecodeError` on a truncated/corrupt existing manifest, aborting the whole merge (no fallback to a fresh manifest), and `old[rel]["mtime"]` raises `KeyError` if an entry lacks that key.

8. `copy_many`'s `except Exception: continue` discards all failures with no log, no error counter and no propagation — a batch where every copy failed returns an empty list indistinguishable from "nothing to do". The existing design doc explicitly requires errors to be logged and the run to continue; here they are neither reported nor surfaced.

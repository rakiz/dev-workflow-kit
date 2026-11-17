Reviewed `git show HEAD` — the commit adds only `incremental.py`.

## Real defects

**1. `filter_excluded` mutable default argument — MAJOR**
`def filter_excluded(paths, excluded=[])` — the default list is created once and shared across every call that omits `excluded`. Calling it twice (e.g. per-directory or per-sync in the new v2 loop) makes the second call return the first call's paths too, so the returned "subset to exclude" is silently wrong and grows unboundedly. Classic cross-call state corruption.

**2. `copy_many` reports un-copied files as done — MAJOR**
`copy_file` swallows `OSError` internally (`except OSError: pass` in `synccli.py`), so it never raises on a failed/unreadable copy. `copy_many`'s `try/except Exception` therefore never fires, and it unconditionally does `done.append(dst)`. The documented contract ("return the list of dst paths done") is violated: callers treating `done` as "these files are now in sync" will believe a file was copied when the destination was never written (or is stale) → silent data divergence.

**3. `merge_manifest` never persists its result — MINOR (misleading contract)**
The function is named/described as merging "into the destination manifest" and takes `dst_manifest_path`, but it only reads that path and returns the merged dict without writing it back. Any caller relying on the documented behavior (the destination manifest file being updated) ends up with an unchanged on-disk manifest and stale sync state. Either it should write `dst_manifest_path`, or the signature/docstring should make the pure-return contract explicit.

## Note (pre-existing, not this commit)
`synccli.collect_stale` skips index 0 (`range(1, len(items))`) and `synccli.py`'s existing tests for it fail; but that file is unchanged by HEAD, so it's outside this commit's scope.

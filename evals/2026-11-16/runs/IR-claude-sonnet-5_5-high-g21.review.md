Defects in `incremental.py`, the only file in HEAD (`ebfbefd`):

1. **Major: `filter_excluded` has a mutable default argument (`excluded=[]`).**
   - The default list is created once and shared across calls.
   - Each call without `excluded` appends to that same list and returns it.
   - A second call therefore returns the first call's exclusions plus its own.
   - Paths from earlier syncs are reported as excluded in later ones.
   - Callers who keep the returned list also see it change underneath them.
   - The fix is `excluded=None`, then `excluded = []` inside the function.

2. **Major: `copy_many` reports failed copies as done.**
   - `synccli.copy_file` catches `OSError` and returns normally, so unreadable-source failures never raise.
   - `copy_many` then appends `dst` to `done` even though nothing was copied, or the destination was left as a truncated empty file.
   - The `except Exception: continue` adds a second layer of silent swallowing. It also hides `makedirs` failures such as permission errors.
   - The caller gets no list of failed pairs and no error.
   - If `done` feeds the manifest, those files are recorded as synced and never retried.
   - The `copy_file` comment says "next pass will retry". That only holds if the manifest is not updated for them.

3. **Major: `merge_manifest` can leave the manifest out of step with what was actually copied.**
   - The caller passes `new_manifest` for all source files, not just those that `copy_many` reported done. Failed copies, which are invisible per item 2, still get recorded as synced.
   - Entries whose source mtime is older than the stored one are dropped. This happens when a file is restored from a backup or after a `git checkout`/rsync that sets an older mtime.
   - In that case the destination holds the new content, but the manifest keeps the stale old state.
   - Deleted source files are never removed from the merged manifest. This differs from `sync()`, which rewrites the manifest from the source.

4. **Minor: `merge_manifest` fails on bad input.**
   - A corrupt or truncated manifest raises `json.JSONDecodeError` and aborts the whole merge.
   - An old entry without an `"mtime"` key raises `KeyError`.
   - There is no fallback or clear error for either case.

5. **Minor: the `merge_manifest` docstring overstates what it does.**
   - It says it merges "into the destination manifest", but it only returns a dict and never writes the file.
   - A caller who assumes it persists will silently lose the merge.

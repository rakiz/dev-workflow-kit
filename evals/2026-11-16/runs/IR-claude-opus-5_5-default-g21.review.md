I found four real defects in the last commit (HEAD `0ebffba`, which adds `incremental.py`), two major and two minor.

1. **Major: `copy_many` reports failed copies as done.** `copy_file` in `synccli.py:65-69` catches `OSError` and returns quietly. So the `try/except` in `copy_many` almost never sees a failure, and every destination gets added to `done` even when nothing was written. Callers that build or merge the manifest from `done` will record files that were never copied. Once the manifest says a file is current, `changed_files` won't retry it, so the destination silently stays stale or missing. The broad `except Exception: continue` also hides any other error without telling anyone.

2. **Major: `filter_excluded` has a mutable default argument (`excluded=[]`).** When called without the second argument, every call appends to the same shared list. Paths excluded in one call show up as excluded in later calls, so files that should sync get left out. The list also keeps growing across calls.

3. **Minor: `merge_manifest` overwrites newer data when mtimes are equal.** It uses `old[rel]["mtime"] <= state["mtime"]`, so an equal mtime counts as "newer" and replaces the old entry, including its size. Separately, deciding by mtime alone means a source file restored to an older mtime is never accepted. The manifest then disagrees with the source and `changed_files` behaves inconsistently.

4. **Minor: `merge_manifest` never removes deleted files.** It only adds or updates entries. Files deleted from the source stay in the merged manifest forever, so it no longer reflects the source tree. This differs from `sync`, which writes the full source manifest.

Also: `filter_excluded` only checks the first path component, so `.git` folders nested below the top level are not excluded. Its name and docstring suggest a general exclude filter, which is misleading.

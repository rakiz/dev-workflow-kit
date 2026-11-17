Reviewed `git show HEAD` (new file `incremental.py`) together with `synccli.py`'s contracts. Real defects:

**Major**

1. `incremental.py:10` — mutable default argument `excluded=[]` is shared across calls. A second call with the default returns the previous call's exclusions too, so unrelated sync batches silently skip files. Reproduced: first call → `['.git/config']`, second unrelated call → still `['.git/config']`.

2. `incremental.py:18-27` — `copy_many` reports false success and silently loses files. `copy_file` swallows `OSError` internally (`synccli.py:71-75`) and returns `None`, and `copy_many` also catches every exception and `continue`s. Either way the pair is appended to `done` even when nothing was copied (verified: unreadable source → `done` contains the destination, destination does not exist). The documented contract "return the list of dst paths done" is therefore wrong, and callers have no way to detect failures.

**Minor**

3. `incremental.py:30-40` — `merge_manifest(dst_manifest_path, ...)` never writes to `dst_manifest_path`, despite the parameter name and the docstring "Merge new file states into the destination manifest". It only returns the dict; the on-disk manifest stays unchanged (verified). Any caller trusting the name silently fails to persist the merge.

4. `incremental.py:38` — the merge condition compares only `mtime` with `<=`. A changed file whose new mtime is older than the recorded one (clock skew, restored/copied file, coarse timestamp granularity) is dropped, leaving stale state that contradicts `synccli`'s own `size+mtime` change detection and causing updates to be missed. Entries removed from the source are also retained forever (union merge), so the manifest permanently diverges from the source tree.

5. `incremental.py:13` — exclusion test `p.split(os.sep)[0]` only recognizes bare relative paths; `./.git/config` or an absolute path yields `""`/`""` as the first component and is not excluded, silently syncing excluded directories.

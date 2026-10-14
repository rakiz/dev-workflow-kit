Review of `git show HEAD` (v0.2, adds `incremental.py`):

1. **Major — `filter_excluded` mutable default corrupts results across calls.** `excluded=[]` is a shared default list; every call appends to it, so a second call returns paths excluded by the first, and the list grows forever in long-lived callers (e.g. the planned daemon). Classic Python bug, silent state corruption.

2. **Major — `copy_many`'s return value is a misleading contract.** It appends `dst` to `done` after `copy_file` returns — but `copy_file` (synccli.py:69) internally swallows `OSError`, so files that failed to copy (unreadable source, etc.) are still reported as "done". Callers trusting `done` will record un-copied files as synced in their manifest → silent data divergence. The extra `except Exception: continue` also silently eats non-OSError errors with no log, contradicting DESIGN.md's "log to stdout and continue".

3. **Minor — `merge_manifest` drops size-only changes.** It compares only `mtime`, while `changed_files` compares the full `{size, mtime}` state. A source change with identical mtime but different size is not merged, leaving the destination manifest inconsistent with the actual file until mtime eventually moves.

4. **Minor — `merge_manifest` crashes on a corrupt manifest.** `json.load` is unguarded; a truncated/invalid `.sync_manifest.json` (the file the design says is rewritten in place, non-atomically, every 500 ms — so truncation on crash is expected) raises instead of falling back to `{}` like `sync()`'s path effectively assumes.

5. **Minor — exclusion only matches the first path segment.** `p.split(os.sep)[0]` means nested `sub/.git` or `sub/__pycache__` paths are not excluded, only top-level ones — an undocumented contract narrowing (docstring says "paths", not "top-level paths").
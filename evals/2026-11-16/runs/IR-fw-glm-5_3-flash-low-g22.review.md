**Review of `ecc6c95` (`incremental.py`) — real defects only:**

1. **[major] `filter_excluded` — mutable default argument** (`incremental.py:11-16`). The `excluded=[]` default is created once at function definition and shared across every call that omits it. Results accumulate: calling `filter_excluded(b)` after `filter_excluded(a)` returns `a`'s exclusions plus `b`'s — wrong sync decisions and state corruption across invocations. Should default to `None` and create a local list.

2. **[major] `copy_many` — silently swallows all failures** (`incremental.py:19-27`). The bare `except Exception: continue` discards the error entirely with no log or error return. Worse, `copy_file` truncates the destination (`open(dst, "wb")`) before writing, so a mid-copy failure leaves a **corrupted, truncated destination file** that is reported as "not done" with zero indication of why. The caller cannot distinguish "skipped" from "failed", which is a data-loss path.

3. **[major] `merge_manifest` — docstring promises persistence it doesn't do** (`incremental.py:30-40`). "Merge new file states into the destination manifest" reads as writing the file; the function only returns a dict and never writes `dst_manifest_path`. A caller trusting the contract (as `sync()` does for its own manifest) ends up with the on-disk manifest never updated — every subsequent sync re-copies everything, or worse, believes state was recorded.

4. **[minor] `merge_manifest` — `KeyError` on malformed/legacy entries** (`incremental.py:37`). `old[rel]["mtime"]` assumes every existing entry has an `mtime` key; a manifest written by another version or hand-edited crashes the whole merge instead of being tolerated.

5. **[minor] `merge_manifest` — mtime-only comparison ignores size** (`incremental.py:37`). A file restored from an archive with an older-or-equal mtime but different content/size is dropped from the merge, leaving the manifest describing stale state (the file won't be re-synced later).

6. **[minor] `filter_excluded` — absolute paths never match** (`incremental.py:14`). `p.split(os.sep)[0]` is `""` for absolute paths, so `os.sep.join(["/", ".git", ...])`-style inputs silently bypass exclusion.

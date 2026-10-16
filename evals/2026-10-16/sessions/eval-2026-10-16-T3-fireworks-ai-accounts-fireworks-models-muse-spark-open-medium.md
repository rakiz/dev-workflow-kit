Last commit touches a single new file — inspecting the added code and its dependencies for real defects.

Review of `50c13d9` — `incremental.py:1-40` (single new file):

**[Major] `incremental.py:10` `filter_excluded` mutable default `excluded=[]` — cross-call state corruption:**
`def filter_excluded(paths, excluded=[])` appends into the same list object for its lifetime. Call N returns accumulation of all prior calls, not just `paths`. Caller filtering a batch will see stale paths excluded (or included) incorrectly. Fix: `excluded=None` / `excluded = [] if excluded is None else excluded` (as `synccli.py:45` `collect_stale` already does correctly).

**[Major] `incremental.py:7` `EXCLUDE_TOP_DIRS` contains filename `".sync_manifest.json"` checked as top-directory:**
`p.split(os.sep)[0] in EXCLUDE_TOP_DIRS` only matches when the *first* component equals that filename. `subdir/.sync_manifest.json` or `a/.sync_manifest.json` is not excluded. Manifest file leaks into sync set if it ever appears off-root; name also misleads API contract (dirs vs files).

**[Major] `incremental.py:18-27` `copy_many` — failed copies reported as successful / data loss:**
`synccli.py:62-69` `copy_file()` already swallows `OSError` (`pass`) and never raises. `copy_many` does `copy_file(src,dst); done.append(dst)` in the `try` success path, so an unreadable source / disk-full / permission error still appends `dst` to `done`. Caller (and subsequent `merge_manifest` write-back) believes the file is synced when `dst` is missing/truncated. `except Exception: continue` is then dead code for the current `copy_file`, and if `copy_file` ever starts raising, it silently hides `ENOSPC`/write errors with no log/return — misleading API contract (`done` != input length, no error signal).

**[Major] `incremental.py:30-40` `merge_manifest` never deletes — manifest grows unbounded / stale state:**
`merged = dict(old)` then only upserts from `new_manifest`. Keys in `old` but absent in `new_manifest` (deleted source files) are retained forever. `synccli.py:72-87` `sync()` rewrites the manifest in full (`json.dump(src_manifest)`) so deletions propagate; `merge_manifest` diverges from that invariant and leaves destination manifest claiming deleted files still exist.

**[Major] `incremental.py:38` `merge_manifest` uses `mtime`-only comparison — silent data loss on size-only change / clock skew:**
`if rel not in old or old[rel]["mtime"] <= state["mtime"]`. `synccli.py:22-25` state is `{"size","mtime"}` and `synccli.py:36-41` detects changes via full-dict `!=`. Merge ignores `size` (and any future hash). File rewritten with same `mtime` (low-res FS, `cp -p`, restore) but different `size` is dropped. Conversely `old["mtime"] > new["mtime"]` (clock skew, restored old version) also keeps stale `old`, preventing intentional rollback.

Review of `bde2f4a` (v0.2). The commit only adds `incremental.py`. It imports `copy_file` from `synccli`, which is not in this commit, so I could not verify that call.

- **`incremental.py:8`, `filter_excluded(paths, excluded=[])`: major.** The mutable default list is shared across calls. Each call without an explicit `excluded` returns the accumulated results of every previous call, so excluded paths leak between syncs and the function's contract is misleading.

- **`incremental.py:11`, top-level-only exclusion: minor.** `p.split(os.sep)[0]` only matches entries at the root. Nested `__pycache__` directories or `.git` paths (e.g. `sub/__pycache__/x.pyc`) are not excluded and would be synced, despite the function's docstring saying they must be.

- **`incremental.py:29-30`, `copy_many` swallows every exception: major.** The bare `except Exception: continue` discards the error and gives no failure signal beyond the omitted entry in the returned list. Failed copies look like a successful batch with no logs, which can silently leave the destination incomplete.

- **`incremental.py:37-38`, `merge_manifest` on a corrupt or empty manifest: minor.** `json.load` raises on a truncated or empty destination manifest, and nothing catches it. The sync aborts instead of recovering, and the function does not say it can raise.

- **`incremental.py:39-40`, mtime-only merge: minor.** Conflict resolution uses source mtime alone, so a file with a newer mtime on the destination side (clock skew or a restored backup) keeps the destination state even when the content differs. The result is a manifest that claims the destination is current when it is not. This may be intended; it is worth confirming.

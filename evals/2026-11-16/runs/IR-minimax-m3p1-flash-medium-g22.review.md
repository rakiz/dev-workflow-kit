Reviewed `git show HEAD` (d4a31af, new file `incremental.py`) against `synccli.py`, `DESIGN.md`, and `GOAL.md`. Verified each finding by execution.

## Major

**1. `copy_many` reports copies that never happened (silent data loss)** — `incremental.py:20-29`
`copy_file` in `synccli.py:71-76` swallows `OSError` internally (`except OSError: pass`), so `copy_many`'s `try/except` never sees the failure and unconditionally appends `dst` to `done`. Verified: `copy_many([('/nonexistent/file.txt', '/tmp/out/file.txt')])` returns `['/tmp/out/file.txt']` while no destination file exists. A caller that merges the manifest for these "done" paths records files as synced that were never copied, so they are permanently missing at the destination while the manifest claims they are current. Additionally, `except Exception: continue` discards every error with no output, contradicting `DESIGN.md` ("log to stdout and continue"), and it cannot detect the mid-read case where `copy_file` has already truncated the destination (`open(dst, "wb")`) — the previous good copy is destroyed and the failure still lands in `done`.

**2. `filter_excluded` leaks state across calls (mutable default argument)** — `incremental.py:8-14`
`excluded=[]` is a single shared list evaluated once at def time. Verified: the first call returns `['.git/config', '__pycache__/x.pyc']`, and an unrelated second call returns `['.git/config', '__pycache__/x.pyc', '.git/other']` — stale paths from the earlier call are re-reported, so a caller asking "what is excluded now" gets a wrong answer and may skip files that were never excluded. The function also mutates the caller's list argument as a side effect of the accumulation.

**3. `merge_manifest` never persists the merged manifest** — `incremental.py:32-40`
The function reads `dst_manifest_path`, computes `merged`, and returns it without ever writing it back. Verified: after merging `{'a.txt': {'size': 999, 'mtime': 100}}` into a manifest containing `{'a.txt': {'size': 1, 'mtime': 100}}`, the file on disk is unchanged. The docstring ("Merge new file states into the destination manifest") promises the destination manifest is updated; a caller that trusts the contract loses the merge silently, and if the caller does write the returned value, `merged` still starts from `dict(old)`, retaining entries for files deleted at the source.

## Minor

**4. `merge_manifest` compares only `mtime`** — `incremental.py:38`
`old[rel]["mtime"] <= state["mtime"]` ignores `size`. A new state whose mtime is strictly older than the recorded one (preserved timestamps, checkout, restore) is dropped entirely, so the manifest keeps the old size/state for a file whose content actually changed. The manifest then disagrees with the source, and `changed_files` (`synccli.py:38-44`) compares the full state dict, so the file is re-copied on every cycle.

**5. `merge_manifest` assumes a well-formed manifest** — `incremental.py:37-38`
`old[rel]["mtime"]` and `state["mtime"]` raise `KeyError`/`TypeError` on any entry that is not a dict with an `mtime` key, and `json.load` on a truncated manifest raises before the merge even starts. There is no fallback, so one malformed entry aborts the whole merge.

**6. `filter_excluded` path splitting fails for absolute paths and Windows separators** — `incremental.py:11`
`p.split(os.sep)[0]` on an absolute path (`/tmp/x/.git/config`) yields `''` as the first component, so nothing ever matches and nothing is excluded; on Windows, paths written with `/` are not split at all since `os.sep` is `\\`. Exclusions fail silently.

**7. `filter_excluded` does not filter** — `incremental.py:8-14`
The name and the `paths` argument imply a filter returning the surviving paths; the function instead returns the excluded ones (per docstring) and never yields the kept subset, so a caller must invert the result itself. The `excluded` accumulator also makes the returned value depend on call history (see #2).

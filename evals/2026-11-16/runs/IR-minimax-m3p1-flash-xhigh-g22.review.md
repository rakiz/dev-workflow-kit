Review of `fa58744` (adds `incremental.py`). All findings below were reproduced locally against the repo code.

## Major

**1. `filter_excluded` — mutable default argument leaks state across calls** (`incremental.py:10`)
`excluded=[]` is a single shared list for every call that omits the argument, and the list is both mutated and returned. Verified:

```
filter_excluded([".git/config", "a.txt"])  -> ['.git/config']
filter_excluded(["b.txt"])                  -> ['.git/config']   # leak from the previous call
```

The returned set is not "the subset of paths" from the current input — it contains paths from unrelated earlier calls. Any caller that uses the return value for pruning, logging, or "excluded from this batch" decisions acts on the wrong set (e.g. deleting files it was never asked about). Fix: default `None` → `excluded = []` inside the function.

**2. `copy_many` reports files as "done" that were never copied** (`incremental.py:18-27`)
`copy_file` (`synccli.py:62-69`) swallows `OSError` internally and returns `None` in both the success and failure case, so the `except` in `copy_many` never fires for copy failures, and every `dst` is appended to `done`. Verified with an unwritable destination directory:

```
copy_many([(src, dst)]) -> ['/…/out/s.txt']   # dst does not exist on disk
```

The docstring contract ("list of dst paths done") is therefore false, and a caller that feeds `done` into the manifest records the file as synced while the destination is missing or (for a mid-copy failure, since `copy_file` opens the destination with `"wb"` and truncates it) left empty/partial. Silent divergence between src and dst. Secondary aspect: `except Exception: continue` discards the error entirely — no log, no error list — contradicting the "log and continue" error policy in `DESIGN.md:18`.

## Minor

**3. `merge_manifest` never writes the merged result** (`incremental.py:30-40`)
The docstring says "Merge new file states into the destination manifest", but the function only returns a dict; `dst_manifest_path` is left byte-identical (verified). A caller trusting the docstring loses the merge silently.

**4. `merge_manifest` crashes on a corrupt or foreign manifest** (`incremental.py:33-38`)
- Truncated/empty manifest → `json.JSONDecodeError` propagates (verified).
- An existing entry without an `"mtime"` key → `KeyError: 'mtime'` (verified).
`DESIGN.md:13-14` plans in-place, non-atomic rewrites of the manifest on every poll, so a truncated manifest is an expected state, not an exotic one; unhandled, it aborts the whole sync cycle instead of rebuilding the manifest.

**5. `merge_manifest` never prunes deleted files** (`incremental.py:36-39`)
Only keys present in `new_manifest` are touched, so entries for files removed from the source survive forever (verified: `gone.txt` persists after merging a manifest that no longer contains it). The merged manifest grows without bound and keeps advertising files that no longer exist in `src`.

**6. Exclusions only apply at the top level** (`incremental.py:7,13`)
The match is on `p.split(os.sep)[0]`, so `sub/.git/config` and `sub/__pycache__/x.pyc` are *not* excluded (verified) — only their top-level counterparts are. Additionally, `EXCLUDE_TOP_DIRS` holds a filename (`.sync_manifest.json`), not a directory, so the manifest is only excluded when it sits at the root of the scanned tree; the constant name does not describe what it holds or what the check does.

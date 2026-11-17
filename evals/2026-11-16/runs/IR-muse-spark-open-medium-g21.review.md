Review of `8952c0e` (`incremental.py:1-40`) — only real defects:

**1. `incremental.py:10` `filter_excluded(paths, excluded=[])` — mutable default — Major (corrupted state / data leak)**

Classic Python alias bug: `excluded` list is created once at definition time and shared across every call without an explicit `excluded` arg. Successive calls append to the same list, so result grows unbounded and caller `A` sees entries from caller `B`. Also pollutes callers that pass a list in (it is mutated in-place and returned). Manifest/sync will exclude wrong files or leak paths between daemon poll cycles.

Fix: `def filter_excluded(paths, excluded=None): if excluded is None: excluded = []`

Secondary consequence: `EXCLUDE_TOP_DIRS` contains `".sync_manifest.json"` (a file) checked only via `p.split(os.sep)[0]` — nested `.git`/`__pycache__` (e.g. `a/__pycache__/x.pyc`) is intentionally not filtered; if intent was recursive exclusion this is a missed filter (minor).

**2. `incremental.py:18-27` `copy_many` silently swallows all failures — Major (data loss + misleading API contract)**

```python
except Exception: continue
```

Every `OSError`/`IOError`/permission error (and `copy_file:65-69` already does `except OSError: pass`) is discarded. Caller gets `done` list of successfully copied `dst` paths and has no signal that `len(done) < len(pairs)`. Upstream that writes the manifest from `done` will mark not-copied files as synced — destination permanently missing files with no retry, no log (violates `DESIGN.md:18` "log to stdout"). Masks programming errors (`TypeError`, `ValueError`) as well.

Fix: propagate/log, return `(done, failed)` tuple, or at least `raise`/`logging`; don't return success on partial failure.

**3. `incremental.py:30-40` `merge_manifest` never deletes and compares only `mtime` — Major (corrupted state / stale manifest)**

* No deletion: `merged = dict(old)` + only insert/update. Files deleted from `src` (`new_manifest` missing `rel`) stay in `dst` manifest forever. `dst` never converges, `sync()` will never clean them, manifest grows without bound.
* Wrong change test: `old[rel]["mtime"] <= state["mtime"]` ignores `size` (and any other state). `synccli.changed_files:40` uses `old[rel] != state` (`mtime+size` per `DESIGN.md:15-16`). With clock skew, low-res FS mtime, or restored file, an older `mtime` with different `size`/content is kept as authoritative — silent stale file.

Fix: `merged` must be built from `new_manifest` plus deletion, or explicitly `del merged[rel]` for `rel in set(old)-set(new_manifest)`, and compare full state (`old[rel] != state`) or `mtime`+`size`.

**Minor (misleading contract):** `merge_manifest(dst_manifest_path, ...)` takes a path, reads it, but never writes `merged` back. Name/docstring imply persistence; caller that assumes on-disk merge will lose updates on crash. Should either write atomically or be renamed `merge_manifest_dict(old, new)`.

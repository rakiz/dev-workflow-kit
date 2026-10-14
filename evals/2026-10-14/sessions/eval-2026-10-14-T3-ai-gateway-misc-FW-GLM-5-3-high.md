Review of commit 5658c2d (`incremental.py`, new file — no callers or tests yet, so all defects are latent in the new API surface):

**Major**

1. **`filter_excluded` — mutable default accumulates state across calls** (incremental.py:9). `excluded=[]` is created once at function definition. A second call with a fresh path list returns (and further mutates) the *same* list, so results from previous calls leak into every later result — corrupted exclusion set. It also mutates any caller-supplied `excluded` list in place.

2. **`copy_many` — reports failed copies as "done"** (incremental.py:17-26). `synccli.copy_file` internally swallows `OSError` (synccli.py:68-69), including mid-copy failures where `dst` has already been opened `"wb"` and truncated/partially written. In that case no exception reaches `copy_many`, so `done.append(dst)` executes for a **failed or corrupted** copy. A caller trusting the return value records those files as synced (e.g. in the merged manifest) — silent corrupted state on disk. The added bare `except Exception: continue` also hides every other failure with no log, contrary to the repo's stated error policy (DESIGN.md:18).

**Minor**

3. **`merge_manifest` drops newer states when mtime decreases** (incremental.py:37). It compares only `mtime`, ignoring `size`, while the repo's own change detection (`changed_files`) uses size+mtime. A file restored with a preserved older mtime (tar extraction, `rsync -a`, `cp -p` from backup) is treated as stale and its new state is discarded — the source change then never propagates (silent permanent divergence).

4. **`merge_manifest` — misleading contract: never writes the manifest** (incremental.py:31-39). Docstring says "Merge new file states *into the destination manifest*" and the function takes the manifest *path* and does I/O on it, but it only returns a dict; a caller reading the contract naturally assumes the on-disk manifest was updated, leaving stale state behind.

5. **`merge_manifest` — no robustness on existing manifest**: an unhandled `json.JSONDecodeError` on a corrupt/truncated manifest, and `KeyError`/`TypeError` if an entry lacks `"mtime"` (format drift), crash the merge instead of degrading to the new manifest.

6. **`filter_excluded` — name/docstring contradiction**: the name reads as "return the paths *after filtering out* excluded ones" (the keep-set), but it returns the excluded subset. A caller coding to the name syncs exactly the wrong files (.git, __pycache__). The docstring disambiguates, hence minor.
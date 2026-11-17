Reviewed `git show HEAD` (new file `incremental.py`, 40 lines). Findings, ordered by severity:

## Major

1. **`filter_excluded` uses a mutable default argument** (`incremental.py:14`). `excluded=[]` is created once at import; every call without an explicit `excluded` appends into the same list. The returned value therefore accumulates paths from *previous* calls, so a caller gets excluded paths that are not in the current `paths` set — and repeated calls (e.g. per-directory filtering in a polling loop) grow the list without bound. Fix: `excluded=None` → `excluded = [] if excluded is None else excluded`.

2. **`filter_excluded`'s return value contradicts its docstring/name.** Docstring: "Return the subset of paths that must be excluded from sync" — but the function returns the *excluded* list. The idiomatic call `paths = filter_excluded(paths)` therefore replaces the kept set with the excluded set, syncing exactly the files meant to be skipped (`.git`, `__pycache__`). The API must either return the kept subset or be renamed/renamed-arg to say it returns excluded paths.

3. **`copy_many` reports failures as successes.** `copy_file` (`synccli.py:66`) swallows `OSError` internally and returns normally, so the `except Exception: continue` in `copy_many` never fires for unreadable/missing sources — every pair lands in `done`, including the failed one. `done` is documented as "the list of dst paths done", so the caller gets a false success list and the failure is invisible (silent data loss). `copy_many` must verify the copy (or `copy_file` must report failure) rather than relying on exceptions.

4. **`merge_manifest` never persists anything.** The docstring says it "Merge[s] new file states into the destination manifest", but the merged dict is only returned; the file on disk is never written. Any caller relying on the documented behavior (the manifest is updated) loses the merged state, and the next `sync()` re-copies everything the merge was meant to absorb. Either write the file (atomically) or fix the docstring to say it returns the merged manifest.

5. **Absolute paths defeat the exclusion filter.** `p.split(os.sep)[0]` on an absolute path yields `""` (POSIX) or a drive letter, so nothing is ever excluded when callers pass absolute paths — a realistic input for `copy_many`/`filter_excluded` users. Splitting on the *relative* path (or checking any path segment, not just the first) is required.

## Minor

6. **`merge_manifest` never prunes deleted files.** Entries present in `old` but absent from `new_manifest` survive in `merged`, so the manifest accumulates stale entries for files removed from the source.

7. **`merge_manifest` crashes on a truncated or malformed manifest.** `json.load` raises `JSONDecodeError` on an empty/partial file — and `DESIGN.md` explicitly plans in-place rewriting of the manifest, so truncation is a realistic state. Same class of issue for `old[rel]["mtime"]`, which raises `KeyError` if an entry lacks `mtime`.

8. **Change-detection semantics are inconsistent with the rest of the codebase.** `changed_files` compares `size` *and* `mtime` for equality; `merge_manifest` compares `mtime` alone with `<=`. A file whose size changed but whose mtime did not advance is dropped by the merge, and one with an older mtime but new content keeps the stale state.

9. **`EXCLUDE_TOP_DIRS` mixes a file with directories.** `.sync_manifest.json` is a file, not a top-level dir, and it is only matched when it sits at the root; the same holds for `.git`/`__pycache__` nested deeper (`sub/.git/...` is not excluded since only the first segment is checked). `scan_files` in `synccli.py` already filters dot-directories, so the sets are also inconsistent with the scanner's rules.

No style nits listed; the missing test coverage for `incremental.py` (the repo has `test_synccli.py` for the other module) is the only other gap worth noting.

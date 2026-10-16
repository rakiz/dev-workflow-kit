Found the three new helpers — now checking their edge-case behaviour and surrounding sync code for real defects.

Review of `534577c` (`incremental.py:1-40`) — 3 real defects, no style nits:

**1. [MAJOR] `filter_excluded` mutable default argument — state corruption / data leak across calls**
`incremental.py:10` `def filter_excluded(paths, excluded=[]):` uses a single shared `list` object for all calls with default. Every call appends to the same list, so `filter_excluded([".git/a"])` followed by `filter_excluded(["file.txt"])` returns `[".git/a"]` on the second call (false positives). Repeated/batch sync runs accumulate stale excludes, leading to incorrect file skipping (data loss — files silently excluded). Fix: `excluded=None` + `if excluded is None: excluded = []`; or build a new local list without mutating the parameter.

**2. [MAJOR] `copy_many` silently swallows all errors — silent data loss + misleading API contract**
`incremental.py:22-26` `except Exception: continue` discards I/O errors (missing src, permission, disk full) and still returns `done` as if the batch succeeded. Callers (and the `merge_manifest` that follows) cannot distinguish partial from complete sync; destination is left incomplete with no signal to retry/report. Corrupted/incomplete sync is undetectable. Fix: collect/log/raise errors, return `(done, errors)` or re-raise; at minimum log at warning level and do not present partial success as full success.

**3. [MAJOR] `merge_manifest` never deletes + stale/removed-source entries persist → corrupted manifest / ghost files**
`incremental.py:36-39` only ever adds/overwrites keys where `old[rel]["mtime"] <= state["mtime"]`. If a file was deleted/renamed in the source, `new_manifest` simply lacks the key, so `merged = dict(old)` retains the old entry forever. Destination manifest diverges from reality; subsequent incremental decisions based on it will keep ghost files and never clean the destination. Also exacerbates defect #2: failed copies in `copy_many` still get their manifest entry merged as if present at dest. Fix: handle deletions explicitly (e.g., caller passes deletion set, or `merge_manifest` is documented/implemented to require it); and do not advance manifest for files that failed to copy.

*Additional minor note on `EXCLUDE_TOP_DIRS` (`incremental.py:7`):* Including the filename `".sync_manifest.json"` in a "top-dirs" set checked only via `p.split(os.sep)[0]` only excludes that file at repo root (not in subdirs). If the intent is to exclude the manifest everywhere, the check is incorrect. Downgraded to non-defect if the spec is strictly top-level; left as design inconsistency rather than counted as separate major.

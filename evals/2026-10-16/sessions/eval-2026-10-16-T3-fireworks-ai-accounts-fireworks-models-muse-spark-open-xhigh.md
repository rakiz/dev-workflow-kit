Review of `2e45a0b` (`incremental.py:1-40`) — only `incremental.py` added:

**1. Major — `incremental.py:10` `filter_excluded(paths, excluded=[])` mutable default:**
Shared list across calls. Accumulates on every invocation, returns ever-growing list containing results from prior calls. Cross-call state corruption / data loss (wrong exclude set). Correct default is `excluded=None`.

**2. Major — `incremental.py:18-27` `copy_many()` misleading API contract / silent data loss:**
`copy_many` returns `done` as "dst paths done" implying success. Underlying `synccli.py:62-69` `copy_file()` swallows `OSError` with `pass` and never raises. `copy_many` `try/except` is thus dead for I/O errors and still appends `dst` to `done` even when source unreadable / copy skipped. Caller believes batch succeeded, files missing at destination.

Sibling: `except Exception: continue` hides all other errors unreported — caller cannot distinguish partial failure from success.

**3. Major — `incremental.py:30-39` `merge_manifest()` corrupted state — deletions never applied:**
`merged = dict(old)` then only upserts from `new_manifest`. Keys deleted in `new_manifest` are retained forever in `merged`. Destination manifest grows monotonically, stale entries never garbage-collected. If caller persists `merged`, sync will never forget deleted files.

Minor variant of same function: `old[rel]["mtime"] <= state["mtime"]` keeps stale `old` when `old.mtime > new.mtime` (rollback/clock-skew) without content check, and function returns dict but never writes `dst_manifest_path` despite name/docstring implying persistence — misleading contract.

**4. Minor — `incremental.py:7` `EXCLUDE_TOP_DIRS` contains file name:**
`".sync_manifest.json"` is a file (`synccli.py:7` `MANIFEST_NAME`), not a top-dir. Check `p.split(os.sep)[0] in EXCLUDE_TOP_DIRS` only excludes it at top-level; `a/.sync_manifest.json` or nested manifest slips through. Misnamed set / incomplete exclusion logic.

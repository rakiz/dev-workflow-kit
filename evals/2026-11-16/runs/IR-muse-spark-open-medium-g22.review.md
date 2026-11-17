Defects in `HEAD` (`incremental.py:1` - 3 functions added):

1. **Major - Corrupted shared state: mutable default arg** `incremental.py:10` `filter_excluded(paths, excluded=[])` - single `list` object shared across all calls. Call 1 appends to it, Call 2 returns Call 1's results + its own. Successive sync scans return ever-growing duplicate exclusion list; caller-supplied `excluded` also mutated unexpectedly (misleading API/aliasing).

2. **Major - Silent data loss / misleading API contract** `incremental.py:18` `copy_many()` + `synccli.py:62` `copy_file()` - `copy_file()` swallows `OSError` and returns normally on unreadable source; `copy_many()` then does `done.append(dst)` regardless. Caller believes `dst` was copied (return value = `list of dst paths done`) when nothing was written. No error propagated, no retry possible.

3. **Minor/Major - Over-broad exception hides programming bugs** `incremental.py:25` `except Exception: continue` - masks `TypeError`/`ValueError` on malformed `pairs`, `AttributeError`, etc. as "skipped file", makes failures undebuggable. (Amplified by #2: domain error already invisible).

4. **Major - Stale manifest never pruned / corrupted state** `incremental.py:30` `merge_manifest()` - `merged = dict(old)` only upserts keys from `new_manifest`, never deletes keys removed from source. Deleted source files remain forever in destination manifest, prevents stale/deletion propagation, causes unbounded manifest growth.

5. **Major - Incorrect merge guard loses updates** `incremental.py:38` `if old[rel]["mtime"] <= state["mtime"]` - source is authoritative but merge keeps old entry when `old.mtime > new.mtime` (clock skew, restore from backup, `touch -d`). Also compares only `mtime`, ignoring `size` (and any other state); the canonical `changed_files()` in `synccli.py:40` compares full `state !=`. Result: newer destination state incorrectly wins, source changes silently dropped.

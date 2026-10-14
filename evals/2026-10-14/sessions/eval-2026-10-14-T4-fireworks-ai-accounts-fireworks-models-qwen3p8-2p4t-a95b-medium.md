

**Verdict: don't build this as written.** Key findings (grounded in the actual `sync()` code):

**Critical**
1. **Failed copies recorded as success** — `sync()` writes the *source* manifest wholesale after copying, and `copy_file` swallows OSError. A transient error = file silently stale forever, never retried.
2. **No deletion/rename propagation** — `dst` becomes a growing superset of `src`, not a mirror. Editor temp files (`foo~`, `.swp`) orphan in `dst` permanently.

**High**
3. **"Manifest is small, atomicity not needed" is wrong twice**: 50k entries ≈ 5–7 MB JSON; rewritten non-atomically at 2 Hz ≈ 10–15 MB/s (~1 TB/day). Crash mid-rewrite = truncated JSON = daemon dead or re-copies 50k files.
4. **"Polling is cheap" is wrong**: ~50k stats × 2/s = ~100k syscalls/s, 0.1–0.3 s CPU per scan — can't meet its own 500 ms budget; continuous core burn.
5. **Non-atomic copy**: `dst` opened with `"wb"` (truncate), whole file `read()` into RAM — crash leaves torn file (then recorded as synced, per #1); 2 GB file = 2 GB RSS.

**Wrong assumptions called out**
- "mtime always changes on edit" — false: `cp -p`/tar/rsync preserve it; 1-s granularity misses same-second same-size edits.
- "SQLite = another dependency" — false: `sqlite3` is stdlib, and GOAL.md says stdlib-only.
- "reuse `sync()` directly" — it's a batch primitive (records source state, reads whole files); not a daemon cycle.

**Fix before writing code (in order)**
1. Manifest records *synced* state, updated per-file after copy lands — never from the source scan.
2. Propagate deletions/renames; decide trash-vs-delete policy.
3. SQLite (WAL) or temp+fsync+`os.replace`, written only when dirty.
4. Chunked copy to temp file in dst dir + `os.replace`.
5. Replace 2 Hz full rescan with FSEvents/inotify + a 30–60 s reconcile poll; hash only on detected change.

Also: make the interval configurable (hardcoding is the misuse), define dst-edit semantics, don't silently skip all dot-directories (`scan_files` drops `.config`, `.ssh`).
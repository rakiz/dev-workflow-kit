

**Critical gaps**

1. **Deletions are never handled.** `changed_files` (synccli.py:36) only reports new/changed files — files deleted from `src` stay in `dst` forever. A "continuous sync" that never propagates deletes is the #1 functional hole; the design doesn't mention it at all.

2. **"Atomicity is not needed" is wrong.** A daemon gets killed mid-write constantly. Partial JSON → `json.load` crash on next boot (synccli.py:79) → either daemon won't start or triggers a full resync. Write-to-temp + `os.replace` is one line; skipping it is choosing corruption under the exact conditions a daemon sees.

3. **Lost changes on mid-copy edits.** Manifest is rewritten after copies finish (synccli.py:85-86). If a file changes *while* being copied (or between scan and copy), the new state is recorded as synced but the copied bytes are stale — silently lost until the *next* mtime change. With edits "a few times per minute" this will happen in week one.

4. **mtime+size is weaker than claimed.** `st.st_mtime` is a float with filesystem-dependent granularity (1s on many filesystems); same-size saves within the same tick are invisible. If you keep mtime+size, capture sub-second fields and handle the copy/edit race (re-stat after copy).

**Under real load**

5. **The poll is not "cheap."** 50 000 files × 2/sec = 100k `stat` calls/sec plus a full diff, plus a full JSON manifest rewrite (50k entries, `indent=2` → multi-MB file, twice a second: constant disk churn, laptop battery/SSD wear). Either budget 1-5s scans, or make the manifest compact/no-indent, or scan incrementally (dir-level mtime as a pre-filter).

6. **"A long copy delays the next poll, which is fine" — it isn't.** One big file (a 2 GB build artifact) blocks detection of *all* other changes for its duration; a git checkout burst of thousands of files serializes into a minutes-long backlog. You need: copy size/time budget per cycle, or prioritized ordering, and never copy files you can't identify as stable.

**Decisions to change before writing code**

7. **"Reusing `sync()` directly" doesn't match the design.** `sync()` swallows copy errors silently (synccli.py:68-69) yet still records the file as synced in the manifest — failed copies are never retried, contradicting "log and continue" (you must *not* mark the entry fresh). It also has no delete or failure-path support. Plan a daemon-side sync loop, not reuse.

8. **Errors "log to stdout"** — a daemon should log to a file with rotation and a backoff on repeated failure of the same file (a permanently broken file currently gets re-read every poll, forever).

9. Also fix the latent bugs before building on this code: `collect_stale` skips `items[0]` (synccli.py:55), `filter_excluded` uses a mutable default arg and only matches top-level dirs, and `merge_manifest` is dead code.

Keep: mtime+size over hashing, and even the fixed 500 ms interval is defensible — but make scan cost and delete propagation the two design sections that currently don't exist.
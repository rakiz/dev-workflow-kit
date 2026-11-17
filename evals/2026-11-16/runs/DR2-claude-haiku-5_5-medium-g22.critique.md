I read `DESIGN.md` (syncd v2). Several claims are wrong or untested, and two of the failures are silent data-loss risks. Recommended fixes come after the risks.

## Major risks

1. **Continuously written files never sync.** The debounce restarts on every observed change, so a file that is written constantly never reaches its quiet period. The claim that latency stays under "one poll + 200 ms even while being written continuously" is false. Add a max-wait cap (e.g. force a copy after 2 s).

2. **Mtime change detection can miss edits.** The design says "mtime is guaranteed to change on every edit." It isn't:
   - `snapshot()` stores mtime at whole-second resolution, so two edits in the same second with the same size are invisible.
   - `cp -p`, `rsync -t`, `git checkout`, unzip and `touch -r` can set mtime backwards or to an old value.

   Use `st_mtime_ns` plus `st_size` plus `st_ctime_ns`. Treat files with mtime within the last ~2 s as unstable and re-check them.

3. **`dst` can hold a truncated file.** The integrity section re-stats the source after the copy, but the copy is written in place. A crash or power loss mid-write leaves a partial file in `dst`, and the journal may already record it as synced. Write to a temp file in `dst`, fsync, then `rename()`. The design rejects tmp+rename for the manifest on fsync-cost grounds, but that cost is per cycle, while this one is per file and is the one that matters.

4. **Mass deletion on a bad scan.** Reconcile deletes from `dst` anything missing from `src`. If `src` is briefly unavailable (unmounted volume, a tool that recreates the directory, a walk that hits permission errors), the next poll deletes most of `dst`. Add a guard: abort deletions when the walk reports errors or when the removed count exceeds a threshold (e.g. >5% of the manifest), and require confirmation for larger batches.

5. **The single-instance guarantee is wrong.** The lock is released before the manifest commit and re-taken each cycle. A second instance can start in that window, and two processes then rewrite the same manifest in place. The claim that the entries "merge cleanly" has no merge logic behind it. Hold an `flock` for the process lifetime. Stale-lock recovery after a crash also needs a rule (the OS releases `flock` on exit, so this is solved by using `flock` instead of a PID file).

6. **Crash-safety arguments are incomplete.**
   - Journal appends are not fsynced, so a power loss drops the last events while `dst` may already hold the copy.
   - Journal compaction is not specified. At 50k files with constant churn, the journal grows without bound and replay at startup gets slower.
   - Replaying a journal on top of a half-written manifest only works if the journal's base state is known. The design does not define one.

   Simplest fix: a single atomic manifest (tmp+fsync+rename) per cycle, with no journal.

7. **The scan budget is asserted, not measured.** "A measured full scan ... well under 100 ms" has no source. Cold-cache APFS, Spotlight and Time Machine can push a 50k-file walk well past 500 ms. Also, the poll loop is serial: if the copy loop takes 2 s during a burst, the next scan starts late and the latency bound breaks. Define a budget: scan time, copy time, and the poll interval should be measured together, and the loop should schedule by deadline, not by sleep.

8. **Permanently failing files retry forever.** A file that always fails (permission denied, locked) is retried every 500 ms with no backoff and no quarantine, which means unbounded log spam and wasted cycles.

9. **Ignore rules are missing.** `build/`, `node_modules/`, `.git/` and editor swap files are on the same path as source files. Each one adds to the scan and to the burst size. The design needs an exclude list before the cost estimates mean anything.

## Decisions to change first

1. Replace the mtime check with `(mtime_ns, size, ctime_ns)` and add an unstable-file window. Stop reusing the second-resolution synccli manifest format.
2. Write data files atomically (tmp, fsync, rename) into `dst`.
3. Replace the journal and in-place manifest with an atomic manifest commit per cycle.
4. Hold an `flock` for the whole process lifetime.
5. Add a deletion safety guard.
6. Add a max-wait cap to the debounce.
7. Measure scan time on a real 50k-file tree, cold and warm, on macOS, before accepting the polling choice. Use the measured number to set the poll interval.
8. Add ignore patterns and per-file retry backoff.

If you want to go ahead on those, I'd suggest starting with items 1–5, since they are the ones that can lose or corrupt data. No code has been written yet.

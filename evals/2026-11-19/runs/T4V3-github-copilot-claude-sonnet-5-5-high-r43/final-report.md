**Method.** I read all five files (DESIGN.md, syncd.py, state.py, GOAL.md, README.md) and ran the prototype in a scratch directory outside the project. Each finding is labelled **[verified]** (I ran it), **[read]** (clear from the code or text) or **[speculative]**. The project files are unchanged, apart from a `__pycache__` that I removed.

## A. Flaws in the design itself

**A1. The debounce latency claim contradicts the debounce rule. [verified]**
- The design says each further change "restarts the quiet period". It also says latency stays under one poll plus 200 ms "even while a file is being written continuously".
- Both can't hold. A continuously written file never goes quiet, so it is starved indefinitely.
- In the simulation, a file rewritten every poll was never copied in 20 polls (about 10 s).

**A2. The latency bound is wrong even for a single edit. [verified]**
- The quiet period (200 ms) is shorter than the poll interval (500 ms), so it is quantised. A change seen at poll N is flushed at poll N+1.
- Worst case is about 1 s, not "one poll plus 200 ms". The 200 ms constant does almost nothing.

**A3. The scan-cost claim is wrong for the code in the repo. [verified]**
- The design says a 50k-file scan is "well under 100 ms".
- `state.snapshot()` took about 3.6 s here on 50k empty files, consistently across three runs.
- The cause is `os.path.relpath` per file, not the stat calls. Bare `os.walk` took 54 ms, walk plus stat 152 ms, and walk plus relpath 3.46 s.
- The design's "one `stat` per file" reasoning is fine, but its prototype doesn't achieve it. Using `os.scandir` and slicing the path prefix would fix it.
- The cost likely depends on the machine (this was macOS). I didn't measure other platforms.
- Per-cycle cost is also higher than the design admits. Each cycle does one scan, two manifest loads, and a full manifest rewrite (2.3 MB, about 73 ms). The rewrite happens even when nothing changed.
- A 3.6 s scan inside a 0.5 s poll loop means the daemon is permanently behind.

**A4. "mtime is guaranteed to change on every edit" is false, and the design's own Rollout section contradicts it. [verified]**
- Rollout says mtime is stored at whole-second resolution. An edit that keeps the same size within the same second produces an identical state, so it is never synced.
- mtime can also be set backwards or preserved (`cp -p`, `rsync -t`, `git checkout`, `touch -d`).
- Storing `st_mtime_ns` alongside the old field, or also hashing small files, would address this. The synccli compatibility concern in GOAL.md would need checking first.

**A5. The backpressure claim is false. [read]**
- The design says the pending set is bounded by "one poll's worth of changes".
- Pending entries survive until they have been quiet, so a stream of changing files (see A1) grows pending without bound.
- Files that fail to copy stay in pending forever. A file deleted while pending is never pruned.
- `flush_one` reads each file fully into memory, so memory is not flat for large files.
- The copy loop runs synchronously inside the poll. Burst load therefore delays the next scan with no feedback.

**A6. The integrity claim is not achieved by the design. [read]**
- Writing straight into `dst` with `open(dst, "wb")` is non-atomic. A crash or a concurrent reader leaves or sees a truncated file. The "dst never holds a truncated copy" guarantee therefore fails regardless of the post-copy re-stat.
- The re-stat only compares whole-second mtime and size, so it misses same-second, same-size changes (A4).
- Copy to a temp file in the same directory, then `os.replace`.

**A7. The manifest commit contradicts the crash-safety story. [verified]**
- The design says a partially written manifest "is repaired by journal replay".
- A truncated manifest makes `json.load` raise (I tested this). Replay needs a loadable manifest, so it cannot repair one.
- `open(..., "w")` also truncates first, so a reader (even the daemon's own next poll) can see an empty file.
- The rejection of tmp+rename relies on a cost argument. Rename gives atomicity without an fsync per cycle. The real write amplification is rewriting the whole manifest every cycle regardless of changes.
- Journal replay is also fragile. A torn final journal line raises `JSONDecodeError`, so one crash mid-append breaks every later restart. **[verified]**
- Nothing is fsynced. Only power loss is affected, which makes this a lower-priority point. **[read]**

**A8. The lock design is flawed. [read, with one point verified]**
- Releasing the lock before the commit leaves the daemon unlocked for nearly the whole cycle. "Entries merge cleanly" is not true: the commit is a whole-file read-modify-write with last writer winning. Two instances will lose updates and interleave journal lines.
- Single-instance protection holds only for the poll duration. A second instance started during the sleep window acquires the lock without any refusal. **[verified]**
- Even where the lock is held, the check is not atomic. `os.path.exists` followed by `open("w")` is racy; `O_CREAT|O_EXCL` is the fix.
- A PID lockfile with no liveness check never recovers from a crash (see B6).
- It is a design risk that the lock lives in `dst`, where a source file named `syncd.lock` would be copied over it. **[speculative]**

**A9. Deletion handling is under-specified and unsafe. [speculative on impact, read on the gap]**
- The journal only records "copied" events. Replay after a restart can resurrect entries for files deleted before the crash, because there are no tombstones.
- `os.walk` swallows errors by default. If `src` is unmounted or unreadable, the scan returns empty. A reconcile step driven by "absent from scan" could then delete all of `dst`. The design needs a guard such as a minimum-count or root-exists check.
- Treating a rename as delete+create is fine in principle, but combined with the above it can briefly delete data.

**A10. Smaller design points.**
- The design uses `time.time()` for debounce, which is wall-clock. `time.monotonic()` is the right choice. **[read]**
- Dot-directories are skipped but dotfiles are synced, so `.git/` is excluded while `.gitignore` is included. The design doesn't mention this. **[read]**
- Copying does not preserve file mode, so executable bits are lost. The design is silent on this. **[read]**
- Keeping the poll and debounce constants fixed to avoid a bad configuration is a defensible choice. It makes the A2 quantisation problem permanent, though.

## B. Prototype fails to implement the design's guarantees

**B1. Journal replay is never called. [verified]** `replay_journal` is defined in state.py, but syncd.py doesn't import or use it. The whole "replayed before the first scan" crash-safety section is unimplemented. The journal is write-only and grows forever (relevant to GOAL item 3).

**B2. A file that changed during the copy is still marked synced and journaled. [verified]**
- `flush_one` sets `self.synced[rel] = state` and calls `journal_append` unconditionally (syncd.py:60-61), even in the mismatch branch.
- That directly violates "never marked synced until a clean pass completes".
- In my test, the file changed to size 20 but the journal recorded size 10. The file was requeued, so it should eventually self-heal. The manifest and journal still state the wrong thing in the meantime.

**B3. There is no deletion or reconcile step. [verified]**
- After I removed a source file, `dst` still contained it, and the manifest still listed it. Nothing in `syncd.py` deletes anything.
- Renames leave the old name in `dst` forever.
- `self.synced` only grows, and `manifest.update(...)` only adds.

**B4. Vanished-file errors crash the daemon. [verified]**
- The design says vanished files are a normal race retried on the next poll and never take the daemon down.
- `open(src)` in `flush_one` raised an uncaught `FileNotFoundError` out of `poll()`.
- The same happens earlier in `snapshot()`, where a file removed mid-walk or a broken symlink makes `os.stat` raise.
- A deleted-while-pending file would also never be pruned (A5).

**B5. No try/finally around the lock. [verified]** After the crash in B4, `syncd.lock` was left behind. A restart then fails with "syncd already running". Ctrl-C mid-poll does the same. The crash-recovery story is therefore blocked at the first failure. **[read for Ctrl-C]**

**B6. Stale locks are never recovered. [read]** The PID is written but never checked for liveness.

**B7. Single-instance is not enforced. [verified]** Covered under A8: the lock is only held during `poll()`.

**B8. The per-cycle status line is not implemented. [read]** The design and GOAL item 4 require pending count and last commit duration on stdout each cycle. `run()` never prints and never times the commit.

**B9. `python3 -m syncd` returns exit code 0 on a usage error. [verified]** `main()` returns 2, but the `__main__` guard calls `main()` without `sys.exit(...)`.

**B10. Minor logic issues. [read]**
- The manifest records the scan-time state, not the state of the bytes actually copied (TOCTOU). Only the whole-second re-stat covers it, and A4 shows that is weak.
- If a pending file reverts to the manifest state it stays pending and is copied with a stale state record.
- `observed` and `quiet_since` are never pruned (small, bounded by file count).
- `run()` calls `load_manifest` twice per cycle, so the reload happens twice per cycle where once would do.

## C. Impact on GOAL.md

- **Item 3 (journal truncation after a clean commit):** only safe if the commit is atomic and durable. With today's in-place rewrite, a "clean" commit can still be lost, and truncating the journal would remove the only repair path. Fix A7 first, and don't truncate while replay is unimplemented (B1).
- **Item 2 (`--verify` with `missing_in_src`):** B3 and A9 show deletion semantics are undefined. The decision for dst files with a missing source needs a design before implementation. Any delete action needs a safeguard against an unreadable or empty `src`.
- **Item 1 (`--verify` re-copy):** inherits A4. If state comparison uses whole-second mtime, the audit can't catch same-size, same-second edits.

## Suggested fix order
1. Make the manifest commit atomic (temp file and `os.replace`) and make journal replay tolerant of a torn last line.
2. Call `replay_journal` at startup.
3. Handle vanished files and stat errors in both `snapshot` and `flush_one`. Use try/finally for the lock.
4. Fix the lock (`O_EXCL`, PID liveness check, held for the whole cycle).
5. Don't mark a file synced or journal it on a mismatch.
6. Replace `os.path.relpath` in `snapshot`.
7. Specify and implement deletion, with a safeguard against an empty or unreadable `src`.
8. Rewrite the debounce and backpressure claims to match the actual behaviour, or add a max-wait cap to fix the starvation.

I haven't made any changes. I can start on the fixes if you want.

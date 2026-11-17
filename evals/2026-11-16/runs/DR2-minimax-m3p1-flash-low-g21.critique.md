Read all four files (DESIGN.md, GOAL.md, state.py, syncd.py). Critique below, ordered by severity.

## Blocking correctness bugs (design claims are false)

1. **mtime truncation silently loses edits.** `state.py:19` stores `int(st.st_mtime)` — whole seconds. DESIGN.md:58 claims "mtime is guaranteed to change on every edit." False: any same-size edit within the same second is invisible to the diff, so it is never synced. On a build tool that rewrites a same-size file 3 times a second, this is the common case, not the edge case. Worse, it interacts with the 200 ms debounce: detection granularity is 1 s, so the "≤200 ms extra latency" claim (DESIGN.md:20) is off by 5×. **Fix first:** float mtime in the manifest — this breaks the "manifest format compatible with synccli" constraint, so negotiate that now, not later.

2. **Lock is released every cycle → "single instance" is false.** `syncd.py:65-67` acquires and releases per poll. A second daemon starting during the first's commit window acquires the lock successfully. Two processes then do read-modify-write on the manifest → lost updates (last writer wins, dropping the other's entries) and duplicate copies. `acquire_lock` is also a non-atomic `exists()` then `open()`. DESIGN.md:46-48 justifies this with "entries merge cleanly" — they do not; there is no merge, it's `manifest.update()`.

3. **Crash safety claim is wrong.** DESIGN.md:33-34: "a partially written manifest is repaired by journal replay." The journal holds only *copied files*, not the full manifest. A torn manifest loses entries for never-recopied files → `json.load` raises on startup and the daemon **crashes** (no try/except in `load_manifest`). And `manifest.update(self.synced)` re-adds deleted files' entries forever, so the deletion path (DESIGN.md:38-40) can never work. Compaction (GOAL 3) makes this worse if the manifest isn't fsynced before truncation.

4. **No exception handling anywhere.** DESIGN.md:50-51 says "a transient source error never takes the daemon down." `flush_one` has no try/except: a file vanishing between scan and copy raises `FileNotFoundError` and kills the daemon; so does a permission error during `os.walk`'s `os.stat`, or ENOSPC mid-write. The "vanishes = normal race" case is *the* case that crashes it.

5. **Non-atomic writes into `dst`.** `syncd.py:49` opens the destination with `"wb"` — readers of `dst` see a truncated file for the whole copy duration. The re-stat check happens *after* the write, so it can only detect the race, never prevent a reader from observing a partial file. "dst never ends up holding a truncated copy" (DESIGN.md:28) is false for the whole write window; tmp-file + rename was rejected for the *manifest* but is mandatory for the *data*.

## Under real load

6. **`f.read()` loads whole files into RAM.** `syncd.py:47` — a 2 GB artifact is a 2 GB `bytes` object. Build trees contain exactly that. Use `shutil.copyfileobj` with a bounded buffer.

7. **The "<100 ms for 50k files" measurement is warm-cache, and it's the wrong number.** 50k `stat` syscalls is ~50-100 ms warm, but several hundred ms cold (fresh CI checkout), and `os.walk` also readdirs every directory. At 2 scans/sec you're at 100% of a core just stat-ing, plus 50k dict allocations per pass → constant GC pressure. The real risk is a scan that overruns the 500 ms budget: there's no deadline, no backoff, and the poll interval is a fixed constant (DESIGN.md:65-67 explicitly refuses to make it configurable — that's backwards; the knob that matters is the *overrun* behaviour, not the interval).

8. **The copy loop is serial and blocks polling.** One 500 MB copy stalls every other pending file behind it — unbounded latency, contrary to "latency stays under one poll plus 200 ms."

9. **`pending` is not the only unbounded set.** DESIGN.md:21-24 claims memory stays flat because pending is drained. But `observed` and `synced` grow to 50k entries and `synced` is never pruned. The real memory claim is false even if `pending` were correct.

## Wrong assumptions about the platform

10. **Symlinks**: `os.stat` follows them, so a symlink to `/etc/passwd` is copied by content and the manifest records the target's size/mtime. `snapshot` should use `os.lstat` and record link targets.
11. **mtime is not "guaranteed" to change** — editors, `rsync --times`, `cp -p`, and network filesystems all preserve or coarsen it. Combined with (1), the change-detection primitive is unsound on two axes.
12. **Hidden-file filtering differs between scan and copy.** `snapshot` skips dotted dirs; nothing skips dotted *files*, so `.gitignore`d files and the daemon's own `.syncd_manifest.json` (if src == dst, or src contains it) are copied.

## Decisions to change first

- **mtime → float, manifest format break.** Deal with the synccli-compat constraint now; retrofitting it later is far costlier.
- **Hold the lock for the daemon's lifetime**, atomically (`O_CREAT|O_EXCL`), with a stale-PID check, not per-cycle.
- **tmp-file + `os.replace` for every data copy**, and fsync the file before rename. Also for the manifest: write tmp → fsync → rename. The rejected-alternatives note (DESIGN.md:58-60) rejected the wrong thing — the fsync cost on the *manifest* is irrelevant next to copying 50 MB of source data; the missing fsync on the *data* is what loses data.
- **Journal: append + fsync, then write manifest + fsync, then truncate journal atomically.** Compaction (GOAL 3) must be the tail of that sequence, never before the manifest is durable.
- **Try/except around every file operation**, with a per-file retry count and a dead-letter list, so one bad file doesn't kill the daemon.
- **`--verify` (GOAL 1) needs a guard before it can be allowed to delete from `dst`.** If `src` is unmounted or temporarily empty, "missing_in_src" means *every* file, and a naive audit deletes the entire destination. Require `src` to be present, non-empty, and to have a plausible file count relative to the manifest before permitting deletion; report the decision but don't act without that check. Also note the summary counts `missing_in_src` but `recopied` overlaps with files that were also missing — define the accounting.
- **Journal growth before compaction lands**: `journal_append` opens/closes the file per copy (`state.py:52`), so a 500-file burst is 500 open/append/close cycles, and the file grows unbounded until GOAL 3 is implemented. Keep an open handle and buffered writes now.

**Biggest single win:** fix mtime resolution (1) and the exception handling (4). Everything else degrades gracefully; those two silently produce a `dst` that is wrong and a daemon that stays down.

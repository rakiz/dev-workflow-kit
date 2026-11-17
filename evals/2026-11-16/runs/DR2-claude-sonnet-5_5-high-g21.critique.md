# Critique of DESIGN.md (syncd v2)

I also read `syncd.py`, `state.py` and `GOAL.md`, because several design claims are contradicted by the code. Nothing was run. This is read-only.

## Blockers (the design is wrong, not just risky)

1. **Change detection can't see some edits.**
   - "mtime is guaranteed to change on every edit" is false.
   - `snapshot()` stores `int(st_mtime)`, so a same-size rewrite within the same second looks unchanged.
   - `cp -p`, `rsync -t`, git checkout and `touch -r` can also preserve or set arbitrary mtimes.
   - The integrity re-stat in `flush_one` uses the same second-resolution check, so it passes the exact case it exists to catch.
   - On a build workstation this means silent stale copies in `dst`.

2. **The lock doesn't give "exactly one daemon".**
   - `run()` releases the lock before the commit and the sleep, so the lock is free for most of each cycle.
   - A second instance starts fine, and both then rewrite the manifest in place (lost updates, torn writes).
   - The "entries merge cleanly" argument ignores that load, update and write is not atomic.
   - `acquire_lock` is `exists()` then `open("w")`, which is a race. It should use `O_EXCL` or `flock`.
   - A crash leaves a stale lock and the daemon can't restart. The design has no stale-PID check.
   - The first daemon will also raise `RuntimeError` mid-loop if the second one holds the lock at that moment.

3. **The crash-safety story is circular.**
   - A torn manifest makes `load_manifest` raise `JSONDecodeError` before any replay happens, so it is not "repaired by journal replay".
   - `replay_journal` is never called in `run()`.
   - The journal is never fsynced, and a torn last line makes `json.loads` fail on startup.
   - GOAL item 3 truncates the journal after the commit. With a non-atomic manifest commit, that deletes the only repair path.
   - "tmp+rename doubles write amplification" is wrong. It writes the same bytes plus one fsync per cycle.

4. **Deletions are specified but not implemented.**
   - There is no reconcile step.
   - The manifest is only ever `update()`d.
   - The journal has no delete event, so a replay resurrects deleted files.
   - `self.synced` is never pruned either.
   - A transient failure of the source (unmounted, empty `snapshot`) would look like mass deletion.

5. **Debounce and latency claims are false.**
   - Every change restarts the quiet period, so a continuously written file (a log or build artifact) is never flushed. That is starvation, not "at most 200 ms".
   - Flushes happen only at poll granularity, so real latency is about 0.5 to 1 s plus scan time.
   - Changes within the same second with the same size don't restart the quiet period at all.

6. **The integrity claim is violated in code.**
   - A file that changed mid-copy still gets `synced[rel] = state` and a journal entry.
   - The copy writes `dst` non-atomically and reads from a file that may still be changing.
   - A crash mid-write leaves a truncated `dst` file. Source and manifest still match, so nothing ever repairs it.

## Wrong assumptions under real load

- **The scan estimate.** "Under 100 ms for 50k files" is not credible on a cold cache, macOS, a network share or with AV software, and the design doesn't say where it was measured.
- **Per-cycle I/O.** Each cycle also parses and rewrites a multi-MB manifest. `poll` calls `load_manifest` every time, and the commit runs even when nothing changed. That is constant disk churn at 2 Hz.
- **Pending is not bounded.** It holds files not yet quiet, failed files and ones still in flux, not just "one poll's worth". `flush_one` runs synchronously on the poll thread and reads whole files into memory. A burst of large files means a long unscanned stretch and a memory spike.
- **Error handling doesn't exist.** `os.stat` in `snapshot` and `open(src)` in `flush_one` raise on a vanished file. That kills the daemon and leaves the lock behind, contradicting "never takes the daemon down".
- **Observability is thin.** Constants are untestable without 0.5 s sleeps. Pending count and commit time won't reveal lag. You need the age of the oldest pending file and the scan duration.

## Decisions to change first

1. **Fix the change-detection key.**
   - Use `st_mtime_ns` plus size, and add an extra manifest field if synccli tolerates it. Check that first, because the dict `!=` comparison treats extra keys as a change.
   - If it doesn't tolerate the field, keep a private sidecar.
   - Hash only when the mtime second equals the current second or for `--verify`.
2. **Make the manifest commit atomic.** Write tmp, fsync, then rename. Only do it when dirty. Keep the manifest in memory instead of reloading it each poll.
3. **Make the journal durable and tolerant.**
   - Fsync appends, skip a torn trailing line, add delete events, and call replay on startup.
   - Compact only after a durable commit, by truncating the journal.
4. **Fix the lock.**
   - Use an atomic acquire (`flock` or `O_EXCL`) with stale-PID detection.
   - Hold it for the daemon's whole lifetime.
   - `--verify` must take it too, or refuse to run while a daemon is up.
5. **Write `dst` atomically** (tmp file in the same directory, then rename), and only mark a file synced after a clean stat before and after.
6. **Add a max-wait to the debounce** (for example 2 s, then copy anyway).
7. **Wrap per-file errors**, retrying with a count and logging them.
8. **Decide the `missing_in_src` policy before coding.**
   - Report-only by default, with deletion behind an explicit flag.
   - Refuse mass deletion when the scan is empty or drops by more than some percentage.
   - Print the decision, as GOAL item 2 requires.
9. **Make `--verify` check `dst` too** (existence and size, optionally hash). As written it only compares source to manifest, so a corrupted or missing `dst` file passes.
10. **Send the status line to stderr or a log.** stdout is the JSON summary for `--verify`.
11. **Measure the scan and manifest cost on a real 50k tree** before finalizing the poll-versus-watcher decision.

## Minor

- Use `time.monotonic()` for debounce.
- Guard against `dst` inside `src` or the reverse.
- Handle symlinks, permissions and dotfiles (`snapshot` silently skips dot directories).
- A directory rename triggers a full recopy of the tree.

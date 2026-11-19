I found problems in both the design and the prototype, and I confirmed most of them by running the code. Anything I didn't run is marked "speculative" or "reasoned".

## A. Prototype fails to implement the design's guarantees

All of these were run unless noted.

1. **Journal replay is never called.** `replay_journal` is defined in `state.py:57` and nothing calls it. The "on restart the journal is replayed before the first scan" guarantee, which crash safety depends on, does not exist. The journal is write-only.
2. **Deletions are not implemented.** After deleting a source file, `dst/a` still exists and the manifest still lists it. There is no reconcile step.
3. **Errors are not handled.**
   - A file vanishing before `flush_one` raises an uncaught `FileNotFoundError` and kills the daemon. The design calls this "a normal race" that is retried.
   - `snapshot()` has the same problem with `os.stat` on a file that vanishes mid-walk, and on broken symlinks (reasoned, not run).
4. **A crash leaves a lock that blocks restarts.**
   - `run()` has no `try/finally`, so after the crash in item 3 `syncd.lock` stays behind and the next start fails with "syncd already running".
   - `acquire_lock` never checks whether the PID is alive, so any kill or crash causes a permanent lockout. This conflicts directly with the crash-safety story.
5. **"Never marked synced until a clean pass" is violated.** When the post-copy re-stat shows a change, `flush_one` still sets `synced[rel] = state` (`syncd.py:60`) and appends a journal entry. The run showed `synced = {size:1, mtime:3000}` for a file that had changed to 6 bytes. It self-heals only because the manifest holds the old state. `dst` also holds a mixed or newer copy under an old-state record.
6. **The lock does not give single-instance behaviour.**
   - It is taken and released inside every cycle (`syncd.py:65-67`), so the whole sleep and commit window is unlocked. A second daemon can start then.
   - The check is a TOCTOU (`os.path.exists`, then `open("w")`). It should use `O_EXCL`.
7. **The debounce doesn't match the design.**
   - The design says a file adds at most 200 ms of latency even while written continuously. A file changed between every pair of polls never flushes; test 4 confirmed it was never copied.
   - Because `DEBOUNCE (0.2) < POLL (0.5)`, the debounce only means "unchanged across two consecutive polls". Latency is therefore 0.5–1 s, not "one poll + 200 ms".
8. **Backpressure claim is false.**
   - `pending` is not drained every pass. Only quiet files are flushed.
   - Entries for files reverted to their manifest state are never removed.
   - `observed` and `quiet_since` are never pruned (small leak, reasoned).
9. **`self.synced` grows forever and is re-merged on every commit.** A stale instance re-asserts old states over newer ones. Entries are never evicted, so the manifest is rewritten wholesale each cycle.
10. **Smaller issues.**
    - Hidden directories are silently skipped (`state.py:14`) and the design doesn't document this.
    - Hidden *files* are not skipped, so a source file named `.syncd_manifest.json` would clobber state.
    - No file modes, symlink handling or empty directories are handled (reasoned).

## B. Flaws in the design itself

1. **"mtime is guaranteed to change on every edit" is false.**
   - `snapshot` truncates mtime to whole seconds. Test 1 showed a same-size edit within the same second was silently never copied (`dst` kept `AAAA`).
   - mtime can also be restored by `cp -p`, `rsync -t`, `git checkout` or `touch -r`.
   - This is a silent divergence bug. The "matching synccli's format" rationale is a compatibility choice that costs correctness.
   - The integrity re-stat uses the same coarse key, so it misses the same races.
2. **The scan-cost claim didn't reproduce.**
   - My run of `snapshot()` on 50,000 empty files took about 1.2 s on this macOS machine. The design says "well under 100 ms".
   - That is one machine, warm cache and empty files, so treat it as a counterexample to the measurement and not as proof for yours.
   - If scan time exceeds the 500 ms period, the effective cycle is scan + commit + 0.5 s sleep, and the stated latency bounds fail.
   - JSON load and dump of the 50k-entry manifest were small (about 17 ms each, 2.3 MB).
3. **Journal plus in-place manifest rewrite does not give crash safety.**
   - A torn manifest makes `load_manifest` raise `JSONDecodeError`, which I confirmed. Replay folds into a manifest you can't load, so it can't "repair" one without a separate fallback.
   - A torn last journal line also raises `JSONDecodeError` in replay (confirmed). A crash mid-append is exactly the case the journal exists for.
   - There is no `fsync` of `dst` data before the journal entry, and none of the journal itself. Power loss can leave a journal entry for data that isn't on disk (reasoned, standard filesystem semantics).
   - The rationale for rejecting tmp+rename is weak. The design rewrites the whole manifest every cycle, which is already more write amplification than one rename.
4. **`dst` can hold a truncated copy.**
   - The write is in place (`open(dst, "wb")`) with no temp file and rename. A crash or a reader mid-copy sees a partial file.
   - The design claim "`dst` never holds a truncated copy" is false.
   - Re-copying on the next poll repairs the file only if the manifest differs, which is not guaranteed after a crash.
5. **The journal doesn't record deletions**, so replay can resurrect entries for removed files. It also never gets truncated in the design, so it grows without bound.
6. **The lock-scope reasoning is wrong.**
   - Manifest commits are read-modify-write, so two writers lose updates and don't "merge cleanly".
   - A reader can load a half-written manifest.
   - A stale instance can overwrite a newer entry with an older state. If source state later returns to that older value, `dst` silently diverges (reasoned scenario, not run).
7. **The ordering claim is vacuous.** Append order only reflects the last copy under a single writer, which item 6 shows isn't enforced. The journal also records the scan-time state, not what was actually copied.
8. **Observability is thin.** "Pending count and last commit duration" can't tell you latency, copy errors, skipped files or lag. Making poll and debounce constants removes the knobs needed to tune the 1.2 s scan case above.
9. **Rejecting watchers is partly circular.** The design says watcher overflow "needs a full rescan anyway", yet it pays a full rescan every cycle. This is an argument about tradeoffs, not a bug.

## C. Problems in GOAL.md that follow from the above

- **Journal truncation "after a clean manifest commit" is unsafe.** The commit is a non-atomic, unfsynced overwrite, so truncating the journal can destroy the only recovery copy. Fix commit atomicity (temp file, fsync, rename) first.
- **`--verify` depends on a trustworthy comparison.** With whole-second mtime and size it inherits flaw B1.
- **The "missing_in_src" decision is undefined today.** The prototype has no deletion logic to reuse, and the "keep manifest format compatible with synccli" constraint limits where to store tombstones.

I did not modify any files.

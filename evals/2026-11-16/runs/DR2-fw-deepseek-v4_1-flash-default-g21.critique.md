## Critique of DESIGN.md

**The load-bearing assumption is false.** DESIGN.md:58 ("mtime is guaranteed to change on every edit") does not hold with whole-second mtime (state.py:19, syncd.py:52). Editors and build tools routinely rewrite a file twice within one second, and tools like `git checkout`, `rsync`, `tar`, `cp -p` preserve mtime outright. Consequence: a same-size, same-second change is **invisible** — poll never queues it, the post-copy re-stat "verifies" a torn copy as clean, and `--verify` reports a stale file as in sync. This one assumption undermines change detection, integrity, and the rejection of content hashing all at once. Fix before writing anything else: nanosecond mtime + size as the fast path, and a real content hash on the debounced boundary (hashing only files that already differ is cheap).

**Memory is not flat and pending is not bounded.** DESIGN.md:22-24 claims pending is "bounded by one poll's worth of changes." False: the quiet period restarts on every observed change, so a file under continuous write stays pending indefinitely, and a sustained `make -j` burst accumulates every touched file until each goes quiet. Worse, `synced` and `observed` (syncd.py:24-25) grow for the life of the process and are never pruned on deletion — O(distinct files ever touched), not O(one poll). And `flush_one` reads the whole file into RAM (syncd.py:46-47), so memory is O(largest file), unbounded by file size.

**"A transient source error never takes the daemon down" (DESIGN.md:49-51) is false.** `flush_one` opens `src` with no try/except; a `FileNotFoundError` (the exact race DESIGN.md:49 describes) propagates out of `poll()` and out of `run()` and kills the process. The run loop has no top-level handler and no SIGTERM handling.

**Crash safety contradicts itself and isn't wired up.** Rejecting tmp+rename (DESIGN.md:59-61) while claiming a journal provides equivalent repair is backwards: one `fsync`+`rename` per cycle is metadata-only and eliminates the journal entirely. As written, `commit_manifest` (state.py:31-34) truncates the manifest in place, so a mid-write crash yields invalid JSON that `load_manifest` (json.load) will raise on — before any replay can repair it. And `replay_journal` is **never called** from `run()` (syncd.py:63-71), so the documented "journal replayed before the first scan" path doesn't exist. If you keep a journal, define the exact ordering: durable manifest commit *then* truncate journal (GOAL item 3) — truncating after a non-durable commit loses everything.

**The lock does not give you single-instance.** It's acquired and released every cycle (syncd.py:65-67), so it's unheld during commit and sleep. `acquire_lock` (state.py:37-44) is a non-atomic exists-then-create (TOCTOU), and the PID is written but never liveness-checked — a SIGKILL leaves a stale lockfile that blocks restart forever. Use `O_CREAT|O_EXCL` (or `fcntl.flock`) held for the process lifetime, with PID liveness or flock semantics.

**Deletions are described but absent, and risky as specified.** `poll()` only iterates `new.items()` (syncd.py:31) — a manifest entry missing from the scan is never visited, so nothing reconciles `dst`. When implemented, deleting `dst` on a transient scan miss (permission error, mid-rename, a dot-directory being skipped) is silent dst data loss. Also `snapshot` silently skips dot-directories (state.py:14), so `.git`, `.env`, etc. are never synced — likely unintended.

**No src/dst overlap guard.** If `dst` is inside `src` (or equal), `os.walk` re-scans what it writes — feedback loop.

### Decisions to change first
1. Change detection: nanosecond mtime + size, plus content hash on the debounce boundary. Re-enable the "content hashing" option you rejected.
2. Drop the journal; make `commit_manifest` atomic (tmp + fsync + rename). Simplifies crash safety and makes GOAL item 3 (compaction) moot.
3. Hold the lock for the whole process lifetime, atomically, with liveness.
4. Bound memory: stream copies instead of `f.read()`; prune `observed`/`synced`; bound the pending set (or accept it's O(touched files) and say so).
5. Add try/except around per-file copy and a top-level loop guard; handle SIGTERM.
6. Add a src/dst overlap guard; decide explicitly whether dotfiles are in scope.

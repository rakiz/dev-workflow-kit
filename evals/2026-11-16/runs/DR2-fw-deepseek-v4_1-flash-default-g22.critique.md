Read DESIGN.md and cross-checked it against the existing `state.py` / `syncd.py`. The design's load-bearing assumptions don't hold. Concrete issues, worst first:

**Wrong assumptions (these are correctness bugs, not nits)**

1. **"mtime is guaranteed to change on every edit" is false** (DESIGN:58). The manifest stores `int(st.st_mtime)` — whole seconds (`state.py:19`). A same-size in-place edit within the same second (fast save, same-length substitution, `touch`/restore) produces an identical `(size, mtime)` and is **silently never synced**. This is the core detection key and it's unsound for exactly the burst-edit workload you're targeting. Fix: sub-second mtime (`st_mtime_ns`) and/or hash, or at minimum document that the format can't carry it.

2. **Debounce is effectively dead.** Poll is 500 ms, debounce 200 ms (DESIGN:12-16). You only *observe* changes at poll boundaries; a file first seen at poll N flushes at poll N+1. `now - quiet_since` is then ≥500 ms, so the 200 ms gate never delays anything — every changed file gets a fixed ~500 ms extra latency, not "at most 200 ms." A continuously-written file never flushes at all (quiet period keeps restarting), so "latency stays under one poll plus 200 ms" (DESIGN:19-20) is wrong for the one case that matters. Pick debounce > poll, or drop it.

3. **Deletions are entirely unimplemented.** DESIGN:38-40 promises a "reconcile step" that drops deleted files from the manifest and removes them from `dst`. There is no such step in `poll()`/`run()`. Worse, `self.synced` is never pruned (`syncd.py:60,69`), so `manifest.update(self.synced)` **re-adds** deleted files on every commit. Deleted/renamed files accumulate forever in `dst`.

4. **Crash safety doesn't exist.** DESIGN:29-34 relies on journal replay on restart, but `replay_journal` is never imported or called in `syncd.py`, and `self.synced` starts empty each run. On restart, all prior state is lost → full re-copy. The journal also isn't fsynced and is written per file (open/append/close each call, `state.py:51-54`), so a crash can lose the journal *and* leave a torn last line that makes `json.loads` throw in replay.

5. **A vanished file crashes the daemon.** DESIGN:49-51 says this is "a normal race" that "never takes the daemon down." But `open(src,...)` in `flush_one` (`syncd.py:46`) is unguarded; `FileNotFoundError` propagates out of `poll()` → `run()` → process dies. The exact scenario you call normal is fatal.

6. **Single-instance lock is broken both ways.** `acquire_lock` is check-then-write TOCTOU (`state.py:40-44`), and it's released every cycle before the commit (`syncd.py:65-67`), so a second daemon can start during the gap — the "exactly one daemon ever writes" guarantee is false. Conversely a crashed daemon leaves a stale lockfile and syncd then refuses to start forever (no PID-liveness check).

**Breaks under real load**

7. **`self.pending` is not bounded by "one poll's worth"** (DESIGN:21-24). It only drains when the quiet period elapses. If a build burst touches hundreds of files, all are copied **synchronously in one poll loop**; if copy time exceeds the 500 ms budget, pending keeps growing and memory is not flat. Falling behind is only logged, never handled.

8. **Whole-file `read()` into memory** (`syncd.py:46-47`). One multi-GB file OOMs the daemon. Use `shutil.copyfile`/streaming.

9. **Non-atomic `dst` writes.** DESIGN rejects tmp+rename only for the *manifest* (DESIGN:59-61), but `flush_one` writes `dst` in place (`syncd.py:49-50`), so a build reading `dst` can see a truncated file. The re-stat integrity check protects the manifest, not the reader. This is the classic consumer-visible corruption.

10. **Scan cost claim is optimistic.** "well under 100 ms for 50k files" assumes warm local cache; cold cache or a network/remote FS makes 50k `os.stat` take 0.5–2 s+, exceeding the poll, with no catch-up. `snapshot()` also rebuilds a 50k-entry dict every cycle.

11. **Unbounded state growth.** `observed` and `quiet_since` are never pruned (`syncd.py:35-37`); heavy rename churn creates new keys and never removes old ones. Another "memory stays flat" claim that fails.

**Decisions to change first (in order)**

- **Change the change-detection key** before anything else: `st_mtime_ns` (+ size), since whole-second mtime silently loses edits. This forces a manifest-format decision now, not later.
- **Make `dst` writes atomic** (tmp + `os.replace`) — cheap, removes reader-visible corruption.
- **Wrap each file's copy in try/except** and **add the deletion/reconcile pass** — otherwise the daemon dies on a race and never deletes.
- **Actually wire crash recovery** (call `replay_journal` on startup) and fsync the journal before the manifest rewrite, or drop the crash-safety claim.
- **Rework the lock**: hold it for the whole run (not per cycle), validate PID liveness, store it outside `dst`.
- **Re-derive the latency/debounce math** from poll≥debounce; state a real bound (poll + debounce) or remove the debounce.

The two claims that will bite hardest in production are the whole-second-mtime miss (#1) and the reader-visible partial `dst` write (#9); both are silent-data-corruption class and both are cheap to fix now.

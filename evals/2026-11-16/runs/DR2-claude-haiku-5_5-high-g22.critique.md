**Critique of DESIGN.md (syncd v2)**

`syncd.py` and `state.py` already exist, and they diverge from the design in several places. Both are covered below. The design's core guarantees (single writer, no truncated copies, crash safety, no data loss) don't hold as written.

**Correctness: blocking**

1. **Single-writer guarantee is false.** The lock is taken per poll cycle and released before the manifest commit (`syncd.py:65-70`). Between cycles, a second instance can acquire the lock and also write into `dst`. "Merge cleanly" is undefined, and `commit_manifest` rewrites the file in place, so concurrent commits can lose updates.
2. **A transient error kills the daemon and leaves a stale lock.** `poll()` has no try/finally, so any exception skips `release_lock`. `flush_one` calls `open(src)`, which raises `FileNotFoundError` if a file is deleted mid-race. That exception escapes `run()`, the daemon dies, and `syncd.lock` remains. Every restart then refuses with "already running" until someone deletes it by hand. This contradicts the design's "a transient source error never takes the daemon down."
3. **Deletions can wipe `dst`.** The design says a reconcile step deletes from `dst`, but the code has no such step. Once it is added, `os.walk` ignores errors by default. An unreadable subdirectory or a briefly unmounted source produces a partial snapshot, and reconcile then deletes the matching `dst` tree. Required: `onerror` that raises, plus a refusal to delete when a large fraction of the manifest disappears in one pass.
4. **Starvation under continuous writes.** Debounce has no maximum wait. A file written every 100 ms never reaches 200 ms of quiet and is never copied. The claim that latency "stays under one poll plus 200 ms even while being written continuously" is backwards.
5. **Change detection is too weak.** It uses whole-second `mtime` plus size (`state.py:19`). Two edits within the same second with the same size are invisible, which build tools do routinely. "mtime is guaranteed to change on every edit" is also false: `cp -p`, `rsync -t`, `git checkout`, and `tar` all restore timestamps. Use `st_mtime_ns`, `st_size`, and `st_ctime_ns` (ctime cannot be set by user tools).
6. **Crash recovery is not implemented as described.** `run()` never calls `replay_journal`. The journal is never truncated, so it grows without bound and replay gets slower on each start. Deletions are not journaled. The manifest is written in place with no fsync, so a crash mid-write leaves unparseable JSON, and `load_manifest` has no fallback. The rejection of tmp+rename on "write amplification" is wrong: rename is a metadata operation, and the journal already pays for an fsync.
7. **`dst` can hold truncated files.** `flush_one` opens the destination with `"wb"` and writes in place. A reader sees a partial file, and a crash leaves one behind. Copy to a temp file in the same directory, fsync, then `os.replace`.
8. **The requeue contract is contradicted in code.** The design says a file that changed during copy is "never marked synced." But `flush_one` runs `self.synced[rel] = state` and `journal_append` unconditionally (lines 60-61), so the journal records a copy that was not clean.

**Load: what breaks**

9. **Poll cost is asserted, not measured.** The doc claims "well under 100 ms" for 50k files, with no measurement. Python `os.walk` plus `stat` over 50k files is typically several hundred ms warm and seconds cold on macOS, before Spotlight or endpoint security. Each cycle also re-parses the whole manifest and rewrites it (`syncd.py:68-70`) even when nothing changed, which runs twice a second. At these numbers, cycles stop being 500 ms apart and latency grows.
10. **Serial copy under the lock.** A build burst of hundreds of files, or one multi-GB artifact, holds the lock and blocks the loop. The latency bound ignores copy time entirely.
11. **The pending-set bound is wrong.** Pending holds every file inside its quiet period, not just one poll's worth, so the bound does not hold under sustained churn.
12. **No ignore rules.** `snapshot` skips dot-directories only, not dot-files. There is no exclusion for `.git`, `node_modules`, or build output, which a 50k-file tree almost certainly contains and which would be copied.

**Decisions to change first, in order**

1. Make single-writer real: `fcntl.flock` on a held fd for the daemon's lifetime (auto-released on crash, no PID file), with the manifest commit inside the lock.
2. Wrap each file operation in try/except and make the poll loop try/finally. Set `os.walk(onerror=raise)`.
3. Add the mass-deletion guard before implementing reconcile, and journal deletes.
4. Change the change key to `(size, mtime_ns, ctime_ns)` and drop the "guaranteed to change" claim.
5. Use atomic writes for both copies (temp + replace) and the manifest (temp + fsync + replace). Truncate the journal only after a successful manifest rename. Call `replay_journal` on start.
6. Add a max-wait to debounce (for example, force a copy after 2 s).
7. Measure the scan on the real 50k-file tree, cold and warm, before defending the 500 ms interval. If it is too slow, use FSEvents or inotify as wake-up hints with a periodic full reconcile. The rejection of watchers is right on portability, but the overflow argument only supports periodic rescans, not avoiding watchers altogether.

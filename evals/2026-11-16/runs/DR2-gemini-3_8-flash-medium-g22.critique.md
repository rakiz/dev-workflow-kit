### 1. Major Risks

- **False Performance Premise**: A 50k-file scan takes **~3.5–3.9s** (mostly `os.path.relpath`), not `<100ms`. At a 500ms poll target, the daemon is in perpetual overrun (~0.25 Hz effective frequency).
- **Silent Data Loss & Corruption**:
  - `int(mtime)` resolution misses same-second, same-size edits; `--verify` reports success over stale targets.
  - In-place `open(dst, "wb")` truncates destination files directly; a crash leaves truncated files marked as synced.
  - In-place manifest rewrite without atomic replacement (`tmp` + `os.replace`) means a crash during write destroys state, making journal compaction and crash recovery unsafe.
- **Flawed Locking & Multi-Instance Hazard**:
  - `acquire_lock` checks `os.path.exists` without atomic creation or pid validation; a crash permanently bricks restarts.
  - Releasing the lock every cycle allows race conditions, and whole-dict manifest writes cause competing instances to wipe each other's state.
- **Missing Deletion Reconciliation**: Deletions are described conceptually but not handled in `poll()`; deleted source files and their manifest entries remain indefinitely.

---

### 2. Wrong Assumptions

- **`mtime` is guaranteed to change on edit**: False at 1-second resolution and for tools preserving timestamps (`rsync -t`, `tar`, `cp -p`).
- **Debounce guarantees <700ms latency**: `DEBOUNCE (200ms) < POLL (500ms)`, so debouncing can only resolve at poll intervals (0.5–1.0s true latency).
- **Continuous writes flush cleanly**: Continuous modifications reset the debounce timer indefinitely, causing write starvation (needs a max-wait ceiling).
- **`f.read()` keeps memory flat**: Slurping whole files into memory causes memory spikes on large files instead of streaming.
- **Symlinks & file modes**: `os.walk` dereferences or skips symlinks silently, and file permissions (`+x`) are neither tracked nor synced.

---

### 3. What Will Break Under Real Load

- **Write Amplification on Idle**: Rewriting a 2.6 MB manifest JSON to disk on every 500ms cycle burns sustained disk I/O even when zero files changed.
- **Journal Accumulation & Startup Failure**: The journal grows unboundedly (one line per copy). A crash mid-line leaves invalid JSON that crashes `json.loads` on startup.
- **Burst Starvation**: In a 500-file build burst, blocking serial copies executed after a 4s scan push delivery of the last file minutes out.

---

### 4. Decisions to Change First (Priority Order)

1. **Change Detection**: Switch from `int(mtime)` to `(size, mtime_ns)`. Keep `mtime` for backward compatibility, compare on nanoseconds.
2. **Scan Optimization**: Replace `os.walk` + `os.path.relpath` with `os.scandir` + prefix slicing (drops scan time from ~3.9s to ~156ms).
3. **Atomic File & Manifest Writes**:
   - Write files to `dst.tmp` and `os.replace` to prevent partial/truncated destination files.
   - Commit manifest via `tmp` + `os.replace` only when dirty; keep state in-memory during execution.
4. **Daemon-Lifetime Locking**: Use `fcntl.flock(LOCK_EX | LOCK_NB)` held for the daemon's lifetime instead of per-cycle file checks.
5. **Debounce Max-Age**: Add a hard deadline to force-flush continuously written files.
6. **Deletion Handling**: Reconcile manifest against the scan to emit deletion tombstones and unlink destination files.
7. **Resilient WAL**: Tolerate partial trailing lines on startup journal replay; truncate WAL only after an atomic manifest commit.

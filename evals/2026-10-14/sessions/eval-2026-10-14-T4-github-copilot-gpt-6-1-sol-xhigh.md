**Change the correctness and state model before implementing this design.** Reusing `sync()` directly already introduces silent divergence.

1. **Failed copies become “synced.”** `copy_file()` swallows errors, then `sync()` saves the entire source manifest (`synccli.py:62–86`). Failed files won’t retry unless their metadata changes. **First fix:** record only successfully published copies; retain failures for bounded, backed-off retries.

2. **In-place writes are unsafe regardless of file size.** A crash during manifest writing leaves invalid JSON and breaks restart. Direct destination writes expose partial files and can destroy the previous good copy. **Change:** temporary files plus atomic replacement for both; define corrupted-state recovery.

3. **500 ms full scans create substantial idle work.** At 50,000 files, the target cadence implies roughly **100,000 stat calls/second**, plus traversal, sorting, JSON parsing and full rewrites. Slow/network storage makes that cadence unattainable. **Change:** keep state in memory, persist only when dirty, use configurable/adaptive polling, and benchmark representative trees before choosing the interval.

4. **Serial copying has unbounded latency—and current copying has unbounded memory use.** One large file blocks detection for its entire copy; `fsrc.read()` loads the whole file into RAM (`synccli.py:67`). **Change:** stream bounded chunks and separate detection from a bounded copy queue that coalesces repeated edits.

5. **“mtime always changes” is false.** Same-size edits with preserved timestamps or coarse timestamp resolution can be missed permanently. A source can also change during copying, producing inconsistent output. **Change:** specify the correctness guarantee; use selective hashing/periodic verification and detect source changes during copying before committing state.

6. **Deletion and scan-failure semantics are missing.** Existing `sync()` never removes deleted files, and a file disappearing between traversal and `stat()` can abort the cycle. **Change:** define deletion/rename behavior and distinguish confirmed absence from incomplete or failed scans before deleting anything.

**Decision order:** successful-copy accounting → atomic publication/recovery → deletion and consistency guarantees → bounded copying and scheduling → measured polling policy. SQLite and watchers are optional; these correctness fixes aren’t.
**Revise this before implementation.** The design assumes cheap scans, reliable timestamps, and harmless interrupted writes; none is a safe foundation.

### Major risks, in priority order

1. **Idle overhead scales with the entire tree** ([lines 11–14](DESIGN.md#L11-L14)). At 50,000 files, two scans/second target roughly **100,000 metadata checks/second**, plus full JSON serialization and writes even when nothing changes. Cold caches, network mounts, and competing disk activity will stretch cycles. Benchmark representative filesystems before choosing an interval.

2. **In-place manifest writes are crash-unsafe** ([lines 13–14](DESIGN.md#L13-L14)). Small files can also be truncated by a crash. Use temporary-file replacement with appropriate durability, or transactional state. Define recovery from missing/corrupt state.

3. **mtime + size can miss changes permanently** ([lines 15–16](DESIGN.md#L15-L16)). Same-size edits with preserved or coarse timestamps are concrete counterexamples. Define the correctness guarantee and use periodic content verification if those misses are unacceptable. **Hashing only when metadata changes does not fix this blind spot.**

4. **Copying blocks detection and can publish partial content** ([lines 17–20](DESIGN.md#L17-L20)). A large copy stops observation of every other file; a source changing during copying can produce inconsistent output. Separate detection from a bounded, coalescing work queue. Copy to a destination temporary file, validate source stability, then atomically replace the destination.

5. **“Log and continue” does not define convergence** ([line 18](DESIGN.md#L18)). If a failed copy advances the manifest, it may never retry; if it does not, repeated polling may hammer the same failure. Record successful application separately from observation, retain pending work, and retry with backoff and visible failure status.

6. **Mirror semantics and reuse are underspecified** ([line 31](DESIGN.md#L31)). Specify deletions, renames, symlinks, destination edits, and inaccessible source directories. An incomplete scan must not be mistaken for mass deletion. Audit `sync()` for those guarantees before making it the daemon’s core.

### Decisions to change first

- Use **watchers plus periodic reconciliation**, or measured, adaptive polling with configurable bounds.
- Choose **crash-safe state and atomic destination publication**.
- Define **retry, consistency, and deletion semantics**, then decide what can safely be reused.

SQLite is optional; crash safety and eventual convergence are not.
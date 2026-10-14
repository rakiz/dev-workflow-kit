**Change the correctness model before coding.** The workload is modest; the proposed polling and persistence create unnecessary load and risk silent divergence.

1. **Manifest writes are not crash-safe** ([lines 13–14](DESIGN.md#L13-L14)). An interrupted in-place rewrite can leave truncated JSON, regardless of file size. Write a temporary file, flush, and atomically replace it. Record a file as synced **only after its destination update succeeds**.

2. **mtime + size can silently miss edits** ([lines 15–16](DESIGN.md#L15-L16)). Timestamps can be preserved or have coarse resolution; same-size edits can go undetected. Decide whether this is best-effort or guaranteed convergence. For stronger detection, combine cheap metadata checks with periodic content verification. Hashing only when metadata changes does **not** catch unchanged-metadata edits.

3. **Copying needs a publication protocol** ([line 17](DESIGN.md#L17)). Direct overwrites expose partial files; editing the source during copying can produce inconsistent output. Copy to a unique temporary file beside the destination, check source metadata before/after, then atomically replace. Retry unstable sources; strict snapshots need stronger guarantees.

4. **The scan budget is unjustified** ([lines 11–13, 19–21](DESIGN.md#L11-L21)). At 50,000 files, two scans per second means roughly **100,000 file checks/second**, plus traversal and two full manifest rewrites—even when idle. Large copies also block detection. Benchmark representative disks; use adaptive/configurable polling, persist only changed state, and separate detection from bounded copy work. Watchers can accelerate detection while periodic scans reconcile missed events.

5. **“Log and continue” needs durable retry semantics** ([line 18](DESIGN.md#L18)). A transient read failure must remain pending, not become acknowledged state. Specify retries with backoff and visible degraded health so an unattended daemon cannot silently stop converging.

6. **The sync contract is missing** ([line 31](DESIGN.md#L31)). Define deletions, renames, destination edits, symlinks, and unavailable source roots. In particular, an incomplete/failed scan must never imply “delete everything missing.” Audit `sync()` against these rules before assuming direct reuse is safe.

**Fix first:** successful-copy acknowledgement and atomic publication → reconciliation/error rules → measured detection strategy. JSON and a single worker can remain viable; their proposed handling is the problem.
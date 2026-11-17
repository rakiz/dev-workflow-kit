**The design is not ready to implement: its correctness guarantees rely on false assumptions.** Change these decisions first, in priority order:

1. **Hold an exclusive lock for the daemon’s entire lifetime** (lines 41–48). Releasing it every cycle permits overlapping daemons; releasing it before commit permits stale manifests to overwrite newer ones. Size + mtime provides no merge or concurrency control. Use an OS-backed lock scoped to the destination and shared state; a PID file alone is insufficient.

2. **Replace the crash-recovery protocol** (29–37, 59–61). An incremental journal cannot reconstruct unchanged entries lost in a truncated manifest. A crash between copying and appending also leaves an unrecorded copy; append order alone proves neither durability nor agreement with destination contents. Specify atomic manifest replacement, journal framing and torn-tail recovery, durability ordering, and safe checkpoint/truncation rules.

3. **Stop treating size + whole-second mtime as content identity** (57–58, 72–73). Two same-size edits within one second are invisible. Tools can also preserve timestamps. Use nanosecond metadata to reduce misses, and define a content-verification policy if exact convergence is required. The claim that mtime changes on every edit is false.

4. **Publish copies atomically** (25–28). Re-statting after writing cannot prevent readers from seeing a partial destination, and a crash can leave that partial file permanently. Copy to a temporary file in the destination directory, validate the source, then atomically replace the destination. Metadata checks still cannot guarantee a consistent snapshot during concurrent writes; define that limitation explicitly.

5. **Correct debounce and backpressure guarantees** (16–24). Continuous writes can restart the quiet period forever. With eligibility checked only every 500 ms, a 200 ms debounce commonly costs another poll, rather than only 200 ms. Pending work can accumulate across polls whenever copy throughput falls below incoming work. Separate scanning from bounded copy scheduling, coalesce per path, and specify a maximum-wait/fairness policy.

6. **Revalidate deletions before applying them** (38–40, 49–51). An incomplete scan caused by permissions or I/O errors must not look like mass deletion. A path can also reappear between scan and reconcile, causing an obsolete deletion. Track scan completeness, distinguish absence from failure, and recheck destructive actions.

7. **Validate the load model before committing to 500 ms full scans** (12–15, 65–68). That is roughly **100,000 file stats/second**, plus directory traversal, manifest work, and copies. One warm-cache measurement says little about cold disks, network mounts, or concurrent builds. Synchronous large-file copies can stall polling arbitrarily. Benchmark those cases and expose scan duration, oldest pending age, throughput, retries, and failures.

**First milestone:** write down the consistency and crash-recovery contract, then test these failure scenarios against it. Tuning polling comes after locking, atomic publication, and recoverable state are sound.

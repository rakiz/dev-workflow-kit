## Change before implementation

1. **Fix crash recovery and locking** (lines 29–47). Journal replay cannot reconstruct an entire manifest if the journal is incomplete, truncated, or missing durable deletions. Hold an OS-backed lock for the daemon’s lifetime, including commits. Define durable ordering for destination writes, journal records and atomic manifest replacement; handle partial journal records.

2. **Publish copies atomically** (lines 25–28). Re-statting after a direct write detects some races but cannot prevent readers from seeing a truncated or partial destination. Copy to a temporary file, verify the source, then atomically replace the destination. Define retry behavior when verification fails.

3. **Replace the size + whole-second mtime assumption** (lines 57–58, 72). Multiple edits in a second, preserved timestamps and same-size edits can be missed indefinitely. Use higher-resolution metadata plus an appropriate content-verification strategy; metadata alone is not a guarantee.

4. **Design for sustained overload** (lines 21–24). A poll cannot necessarily drain pending work: copies may take longer than files arrive, and continuously changing files remain pending. Bound the queue, define overload/retry behavior, and measure backlog age and throughput.

5. **Correct the latency contract** (lines 16–20). Continuous writes can postpone a quiet-period copy indefinitely. With polling, quiet periods are observed at poll boundaries, and scan, queue and copy time add latency. Specify whether the goal is eventual convergence or a maximum staleness bound.

6. **Make deletion conservative** (lines 38–40, 49–51). An unreadable directory or incomplete scan must not be interpreted as source deletion. Define ownership of destination files and guard against `dst` being inside `src`; otherwise reconciliation can delete unrelated data or recursively sync its own output.

7. **Validate polling under realistic conditions** (lines 12–15). One fast scan does not establish headroom: 50,000 stats twice per second competes with builds and copies, and cold caches, network mounts and large directories can be much slower. Benchmark those cases and expose scan duration, errors, backlog age and last successful convergence.

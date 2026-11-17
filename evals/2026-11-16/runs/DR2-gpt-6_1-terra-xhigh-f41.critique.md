## Change these decisions before implementation

1. **Hold an exclusive lock for the daemon’s lifetime** (lines 41–48). Releasing it before commit permits two writers and lost manifest updates. Use an atomic, OS-backed lock scoped to the destination; a PID file alone is vulnerable to stale PIDs and acquisition races.

2. **Publish copies atomically** (lines 25–28). Re-statting after writing directly to `dst` cannot prevent readers from seeing a partial file, and a failed copy can leave one behind. Copy to a temporary file in the destination directory, validate the source, then rename it into place. A later source change still requires another sync.

3. **Redesign recovery as a complete, ordered protocol** (lines 29–37). Journal replay cannot reliably repair a truncated manifest unless the journal contains a complete baseline plus all subsequent changes, including deletions. Define checkpoint and replay boundaries, partial-record handling, and durability ordering. Write the manifest via temporary file and atomic rename; use `fsync` where the promised crash guarantee requires it.

4. **Replace whole-second mtime identity** (lines 57–58, 72). Edits can preserve size and mtime, and multiple edits within one second can be missed. Use nanosecond timestamps and additional file identity metadata where available; if correctness must cover metadata-preserving edits, use content verification. Define compatibility with `synccli`’s existing manifest.

5. **Treat deletion as a high-risk operation** (lines 38–40, 49–51). An unreadable directory, incomplete scan, or transient mount failure must not look like mass deletion. Delete only after a successful authoritative scan of the relevant subtree, and define recovery if a crash interrupts deletion.

6. **Fix the load and latency assumptions** (lines 12–24). Polling cannot observe every write; continuous changes can postpone debounce indefinitely. A pending dict can grow across polls when copying is slower than changes arrive. Repeated 50,000-file scans, manifest rewrites, and burst copies may also extend the cycle far beyond 500 ms. Benchmark on representative filesystems and large files, set a bounded-work/backpressure policy, and specify eventual-convergence rather than a hard latency bound.

**Observability:** Track scan and copy durations, oldest pending age, backlog size, errors, and last successful complete scan; pending count and commit duration alone cannot show whether sync is keeping up.

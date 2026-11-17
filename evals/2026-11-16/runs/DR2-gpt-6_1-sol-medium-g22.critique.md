**Change the correctness model before implementation.** Several guarantees in this design do not follow from the proposed mechanisms.

1. **The lock does not ensure a single writer** (`DESIGN.md:41–48`). Releasing it every cycle lets another daemon start while the first commits; self-describing entries do not prevent lost updates or concurrent destination writes. Hold an OS-backed exclusive lock for the daemon’s lifetime, keyed to the destination. A PID file alone is insufficient.

2. **Journal replay cannot guarantee recovery as described** (`29–37, 59–61`). An in-place manifest rewrite can destroy the baseline; incremental journal entries cannot necessarily reconstruct it. Append order also does not establish disk durability. Specify atomic manifest replacement, journal framing/torn-tail handling, checkpoint/truncation rules, and fsync ordering between destination, journal, and manifest. Include deletions in the recovery protocol.

3. **Copy-then-stat does not protect destination integrity** (`25–28`). Readers can see a partially overwritten file, and a crash can leave it truncated. A changed source can also produce mixed-version contents. Copy into a temporary destination file, validate the source version, then atomically replace the destination; retain the previous good copy on failure. Metadata checks alone cannot guarantee a coherent snapshot during arbitrary concurrent writes.

4. **The change detector will silently miss edits** (`57–58, 72–73`). Whole-second mtime plus size misses same-size edits within a second—particularly likely during build bursts. Even nanosecond mtime is not guaranteed to change on every edit. Upgrade the manifest precision first, and define whether stronger verification is required for timestamp-preserving changes.

5. **The debounce latency guarantee is false** (`16–20`). Continuous writes continually reset the quiet period, so latency is unbounded. With 500 ms polling, a 200 ms deadline may not be serviced until the following poll. Choose explicitly between waiting for stable files and bounded staleness; use independently scheduled deadlines if the latter matters.

6. **The throughput and memory bounds are unsupported** (`12–24`). Scanning 50,000 files twice per second means roughly 100,000 stats/sec, before copying or committing. One warm-cache measurement says little about cold disks, network mounts, or large-file bursts. A dict bounds entries by tracked paths, not by one poll’s changes; draining work takes time. Benchmark representative storage and define copy budgets, backlog limits, and retry backoff.

7. **Deletion needs a trustworthy scan** (`38–40, 49–51`). A transient unreadable directory or unavailable source must not look like mass deletion. Reconcile deletions only from a successfully completed, authoritative scan; distinguish “absent” from “could not inspect.”

**First decisions:** lifetime locking, atomic publication/recovery, and change-detection semantics. Then establish realistic scan/copy capacity and report oldest pending age, failures, and cycle duration—not just pending count.

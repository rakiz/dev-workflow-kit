**Major risks (in priority order):**

1. **500 ms full-tree poll doesn't scale.** 50k stats per cycle at 2 Hz = 100k stat/s; the scan itself will take longer than 500 ms on cold cache, so your effective cycle time is unbounded and the interval is fictional. It also burns battery/CPU on a workstation. Either back off adaptively or use FSEvents/inotify (your rejection hand-waves this — on macOS you get FSEvents for free with one C API).

2. **"Atomicity is not needed" is wrong.** Crash mid-rewrite = truncated JSON = lost manifest → next cycle decides 50k files changed (or silently trusts nothing). Full rewrite every 500 ms is also ~170k writes/day of pure SSD wear for a file whose diff is usually zero. Write-temp-then-rename, and only when something changed.

3. **Copying immediately captures torn writes.** Editors and log writers write in place; a copy triggered mid-write puts a corrupt file in `dst` and your mtime check will never revisit it. You need a settle window (re-stat before/after copy) — this is the most likely real-world data-loss bug.

4. **Serial copy blocks everything.** One 5 GB file = minutes of stall; "long copy delays the next poll, which is fine" is the wrong assumption — everything else goes stale behind it. Needs a worker queue (even one background copy thread) so detection and transfer decouple.

5. **mtime+size has real false negatives:** mtime granularity (coarse on some FS/network mounts), same-size edits within the granularity window, and tools that restore mtime (rsync -a, unzip, git checkout). Files silently drift. Cheap fix: hash only when size matches but mtime is within granularity, or periodic full hash audit.

6. **Log-and-continue errors = silent divergence.** A permanently unreadable file is logged once on stdout of a daemon nobody watches and never retried. Needs retry with backoff and a persistent failure state surfaced in the manifest.

**Missing entirely:** deletion propagation (does removing a src file delete from dst?), rename handling (treated as delete+recopy of huge files), initial sync of 50k files through this loop (hours), and any health/metrics signal so users notice the daemon stopped syncing.

**Decisions to change first:** atomic + change-gated manifest writes; settle-before-copy; decouple detection from copying; define delete/rename semantics. Then reconsider event APIs over 2 Hz polling.
**Verdict: don't write code yet.** The two highest-severity items are the delete path and whole-second mtime.

**Wrong assumptions (fix the reasoning first)**
- "Full scan of 50k files <100ms" — false off a warm local APFS: `os.walk` is readdir + per-entry stat (~100k syscalls); on NFS/SMB/external SSD per-stat is 1–10ms → minutes, and two polls/sec is a permanent CPU tax next to the build. Measure it; don't assert it.
- "Debounce adds ≤200ms even while a file is written continuously" — backwards. A continuously-written file never reaches a quiet period, so it **never syncs**; latency is unbounded, and the integrity re-stat re-queues it forever.
- "Pending set is bounded by one poll's worth" — unbounded whenever change rate > copy throughput; a perpetually-dirty file stays pending forever.
- "mtime is guaranteed to change on every edit" — false at whole-second granularity: same-size edits within one second are invisible. Use `st_mtime_ns` (+ inode, size).
- "Journal replay restores the manifest exactly" — only for copies that reached it; deletes and a torn manifest prefix aren't repairable, and nothing is fsynced.

**Risks that will bite under load**
- Transient-empty `src` (unmount/dropped share/tmpfs) → walk returns empty → **reconcile deletes all of `dst`**.
- In-place payload writes expose truncated files to consumers; tmp+rename is needed for the data too, not just the manifest.
- Lock released before commit → two daemons *can* run; "exactly one" is false. PID lockfile also breaks on PID reuse / stale after SIGKILL.
- Serial copy loop: one multi-GB artifact stalls scanning; poll deadline slips unbounded.
- Unhandled: symlinks, mode bits, disk-full, case-insensitive collisions/case-only renames, slow-FS scan drift.

**Decisions to change first**
1. Guard deletes: verify `src` root device+inode unchanged, non-empty scan, quarantine deletes for N cycles.
2. Atomic commit: manifest tmp→fsync→`os.replace`→fsync dir; journal length-prefixed+CRC, fsync'd, record deletes too.
3. One `flock` held for process lifetime (copy+commit), released on exit.
4. `st_mtime_ns` in the manifest (format bump).
5. Atomic payload writes + preserve mode bits.
6. Hybrid: FSEvents/inotify for detection + periodic full rescan (30–60s) for reconciliation; if polling stays, `os.scandir`+`DirEntry.stat()` and adaptive interval.
7. Debounce max-wait cap (~2s); state the guarantee as best-effort.
8. Bounded backlog + overflow policy; log scan duration and backlog depth, not just pending count.

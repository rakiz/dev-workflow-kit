Brief, concrete critique — reading the design first.

**Verdict: Do not implement as specified — will fail at stated scale (50k files) and risk data loss/corruption.**

### 1. Major Risks (in priority order)

**1. Full scan every 500ms at 50k files `DESIGN.md:11` — non-viable:**
100k `stat()`/s sustained = high IOPS, CPU wake, battery/SSD wear on a workstation. `O(n)` per cycle with no incrementalism. Contends with user workload. Will be throttled by AV/OS or OOM on large trees, opposite of "polling is cheap" `DESIGN.md:20`.

**Fix first:** Event-driven via `fsnotify` (inotify/FSEvents/kqueue abstraction) + periodic full-scan reconciliation (e.g. every 30-60s or on watcher overflow). Not "platform-specific complexity" — it's one library.

**2. Manifest rewritten in-place non-atomically `DESIGN.md:13-14` — durability failure:**
Crash/power-loss mid-overwrite = torn JSON = total state loss → full re-sync or silent divergence. "Small file so atomicity not needed" is false; size is irrelevant to crash semantics.

**Fix first:** `write-to-tmp + fsync + rename` or SQLite WAL (you dismissed `DESIGN.md:28` prematurely). SQLite is stdlib-adjacent for Go, single file, gives you crash-safe txn + queryable state for free.

**3. Single-thread copy blocks detection `DESIGN.md:19-20`:**
One large file (VM image, video, DB: GBs) stalls the *only* loop for seconds/minutes. Changes during copy are missed/coalesced incorrectly. Single-file serial copy also kills throughput.

**Fix first:** Decoupled pipeline: watcher/poller → dedup queue → worker pool (2-4 workers) with backpressure. Polling/detection never blocks on I/O.

**4. Partial-write copy + no verification `DESIGN.md:17`:**
Copying "immediately" while file is still being written → corrupt `dst`. No stable-size check, no tmp+rename on dst, no hash/verify.

**Fix:** Debounce (e.g. 50-200ms quiet period after last mtime change), copy to `dst.tmp` + atomic rename, optionally verify size/mtime after.

### 2. Wrong Assumptions

* **"mtime always changes on edit" `DESIGN.md:16`:** False. Low-res mtime (1s on HFS/ext3, FAT), rapid saves within poll window, `cp -p`/`rsync -a`/`git checkout` preserving mtime, NFS/VM clock skew, sub-500ms edits coalesced away. Size-only misses in-place rewrites.
* **"polling is cheap" `DESIGN.md:20`:** Only for small trees. Contradicts own long-copy-blocks-poll claim.
* **"content hashing too expensive" `DESIGN.md:26`:** Strawman. No one hashes 50k files every 500ms. Correct pattern: `mtime+size` as filter → hash *only* changed candidates to avoid false positives/negatives. Cheap and necessary.
* **Hardcoded 500ms `DESIGN.md:21`:** Removes the only knob to mitigate the above. Configurable with bounded defaults (e.g. 100ms–30s + adaptive backoff) is correct; "invites misuse" is not a design principle.

### 3. What Breaks Under Real Load

* **Deletes/renames/moves:** Design never mentions them. Poll-diff without inode tracking will treat rename as delete+create → double copy, orphaned `dst` files leak forever.
* **Error handling to stdout `DESIGN.md:18`:** Daemon has no attached stdout. Errors vanish. No retry, no DLQ, no metric → permanent desync, silent. Needs structured log + retry with exponential backoff + `dst` health check.
* **Thundering writes:** "Few times per minute" per file = repeated immediate copies of same file, often of intermediate state. Needs coalescing/dedup in queue.
* **Manifest rewrite contention:** Every 500ms full JSON rewrite while readers/consumers exist = races even single-process if `sync()` reads it.

### 4. Decisions to Change Before Any Code

1. **Detection:** `fsnotify` + batched poll reconciliation, not 500ms full scan. Keeps rejected alternative reversed.
2. **State:** Atomic durable manifest (tmp+rename minimum; prefer SQLite — revisit `DESIGN.md:28`). Unblocks crash recovery.
3. **Pipeline:** Queue + workers + debounce + atomic dst writes. Reusing `sync()` directly `DESIGN.md:31` without queue/idempotency semantics will inherit one-shot assumptions in a continuous loop.
4. **Change signal:** `mtime+size → hash-on-change` (or at least `mtime+size+hash-if-mtime-near-boundary`). Add inode/mode tracking for renames/deletes.
5. **Observability:** Structured logging, metrics (lag, queue depth, errors), retry budget — not stdout.
6. **Config:** Expose poll/reconciliation interval, debounce, concurrency with safe defaults and validation.

Ship without these = high-risk rewrite after first real user.
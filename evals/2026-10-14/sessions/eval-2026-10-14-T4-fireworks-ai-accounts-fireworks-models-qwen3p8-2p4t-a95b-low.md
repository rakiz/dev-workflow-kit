

Critique of DESIGN.md (grounded in the existing `synccli.py`/`incremental.py`):

**Wrong assumptions**
- "Polling is cheap" — false at this scale. 50k files × stat every 500 ms ≈ 100k syscalls/s to detect a few changes *per minute*. This burns CPU/IO permanently and still adds up to 500 ms latency. The rejected alternative (FSEvents/inotify) is the standard answer; "platform-specific" is solvable with a watcher interface + polling fallback. If polling stays, the interval must be seconds/minutes with directory-mtime pruning, not 500 ms.
- "Atomicity is not needed" — the manifest is the *only* state. A crash mid-rewrite corrupts it, and the daemon then either full-resyncs blindly or silently loses track. Write-temp-and-rename is two lines; this decision has no upside. SQLite was rejected "for little gain" but it gives atomicity + incremental updates for free — rewriting the whole JSON every 500 ms is also constant disk churn.
- "mtime always changes on edit" — no: mtime-preserving editors/tools, clock adjustments (dst sees *older* mtime), and same-size-within-mtime-granularity edits all slip through. Fine as a heuristic, but say so and define the recovery path (e.g. hash-on-suspicion), not as a guarantee.

**What breaks under real load**
- **Torn copies:** copy-immediately races the writer — you copy a half-written file. With mtime+size only, if final size matches what you saw, the truncated copy may never be fixed. Need a stability rule (mtime unchanged across two polls) or copy-then-reverify.
- **Head-of-line blocking:** one multi-GB copy stalls detection and the manifest rewrite for its whole duration. "Single thread is fine" fails on the first large file. At minimum, copy off the scan path.
- **Deletions/renames:** `sync()`/`changed_files()` detect adds/modifications only — nothing deletes from `dst`. A "continuously in sync" daemon that never propagates deletes diverges by design, and a rename = delete+full recopy. This is the biggest functional gap and the design doesn't mention it. Also dangerous: deletion propagation needs an explicit policy (trash? threshold guard against mass-delete on a bad scan?).
- **Error loop:** "log to stdout and continue" means an unreadable file is retried every 500 ms forever (log spam) or dropped with no record. Errors need manifest state + backoff, and a daemon needs a real failure surface, not stdout.

**Decisions to change first (in order)**
1. Add deletion/rename semantics + a mass-delete safety guard — without it the daemon doesn't meet its own goal.
2. Atomic (or SQLite) incremental state — cheapest fix, prevents the worst failure mode.
3. Detection strategy: watcher, or much longer interval with pruning; 500 ms full scans are the worst of both worlds.
4. Partial-file stability rule before copy.
5. Make the interval configurable — "configuring invites misuse" also makes the daemon untestable (every test sleeps 500 ms) and untunable; also note `incremental.py` already exists and the design ignores it.
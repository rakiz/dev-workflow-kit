# DESIGN.md — pre-code critique

## Verdict: do not implement as written. 3 load-bearing flaws will corrupt data.

### 1. Whole-second `mtime` makes change detection lossy — breaks the core loop
- Design reuses `snapshot()` with **whole-second `mtime`** and rejects content hashing because "mtime is guaranteed to change on every edit." (`:58`, `:72`)
- False. Build bursts routinely rewrite a file 2-10× within one second with the same size. `size+mtime` at 1s resolution will **silently miss updates** — `dst` goes stale with no error.
- **Fix first:** use `mtime_ns` (or `st_mtime_ns`) + `size` as the key. Cost is zero. Revisit hashing only if you must handle clock-skew / `touch -m` cases.

### 2. "Plain rewrite" of the manifest is not crash-safe — journal does not repair it
- Design rewrites manifest **in place** after releasing the lock and claims "a partially written manifest is repaired by journal replay." (`:32-34`, `:59-61`)
- A crash mid-rewrite truncates/corrupts the manifest. Replay only helps if (a) every journal append was `fsync`'d and (b) the manifest is still parseable. Neither is specified — default buffered append loses the last N entries on crash, i.e. exactly the entries you need.
- Rejecting `tmpfile+rename+fsync` to "avoid double write amplification" trades correctness for ~1 extra rename per 500ms. On a 50k-entry manifest this is negligible.
- **Fix first:** `tmpfile → fsync → rename` for manifest; `fsync` journal appends. Or drop the journal and make the manifest itself the commit point.

### 3. Lock released before commit allows split-brain writes
- "Lock is taken at start of poll and released as soon as copy loop ends, before commit." (`:45-48`) Claim: second instance "simply produces entries that merge cleanly."
- They don't merge — they race. Instance B starts in that window, reads stale manifest, copies its own set, and commits an image that **clobbers A's just-copied entries** (last-writer-wins on whole-file rewrite). PID lockfile without `flock`/`fcntl` is also stale-PID-prone.
- **Fix first:** hold lock across scan→copy→commit as one critical section, or use atomic manifest commits so readers never see a torn view. Use `flock`, not PID file.

### 4. `re-stat` after copy does not give integrity
- (`:25-28`) Re-statting after `dst` write catches some races but **not a torn copy**: if `src` changes mid-`read()`/`write()`, `dst` already holds a half-old/half-new file, and the re-stat just requeues — leaving the corrupt `dst` in place until next copy completes. No checksum, no tmpfile+rename on `dst` side.
- **Fix:** copy `src` → `dst.tmp` → `fsync` → `rename` into place; optionally verify `size`/`hash` before rename.

### 5. Poll-every-500ms + "bounded pending set" — wrong bounds, real cost
- (`:12-24`) "Well under 100ms for 50k files, one `stat` each" assumes warm dentry cache on Linux SSD. Cold boot, HDD, NFS/SMB, macOS APFS with xattrs/AV hooks, or contended laptop easily 300-800ms. 2 full walks/sec = ~100k `stat`/sec sustained — battery/I/O killer on a workstation daemon.
- "Pending bounded by one poll's worth" is false: a file written continuously **never hits its 200ms quiet period** and sits in `pending` forever (starvation). Burst of 1000 files all remain pending until quiet — that's not "flat."
- Also with 500ms poll + 200ms debounce, worst-case latency is not `poll+200ms` — it's `poll + debounce + copy time + requeue delay` if the file is still dirty on re-stat.
- **Fix:** either use `inotify`/`FSEvents`/`kqueue` with poll as fallback for overflow, or adaptive poll interval. Add max-hold timeout to debounce to prevent starvation. Benchmark on cold cache + HDD + NFS before locking constants.

### 6. Other wrong assumptions
- **PID lockfile** (`:43-44`): PID reuse → false "already running" or false "not running." Use `fcntl.flock`.
- **"Rename = delete+create, needs no handling"** (`:39-40`): consumers watching `dst` see a delete then create (ENOENT window); hardlinks/symlinks/permissions not addressed.
- **Module constants for poll/debounce** (`:65-66`): rejecting configurability because "it invites bad configs" just hides them — expose with validated bounds.
- **Observability to stdout** (`:67-68`): daemons don't have a stdout; need structured log + health file.

### What to change before coding (priority order)
1. `mtime_ns` + `size` for change detection; decide on `dst` tmpfile+rename.
2. Atomic manifest commit (`tmp+fsync+rename`) and `fsync`'d journal — or remove journal.
3. Hold lock across full cycle; replace PID file with `flock`.
4. Fix debounce starvation (cap quiet-period restarts) and re-measure scan cost on realistic filesystems; add watcher or back off poll interval.

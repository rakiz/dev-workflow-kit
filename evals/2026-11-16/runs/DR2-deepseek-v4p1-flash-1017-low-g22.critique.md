Read DESIGN.md (and the existing `state.py`/`syncd.py`, which already contradict it in places). Critique, highest-impact first:

**1. "Bounded work per poll" is false — the copy runs inline and blocks the scan.**
`poll()` flushes copies synchronously inside the scan loop (syncd.py:49-63). One large file, or a `dst` on a slow/network disk, stalls scanning for its whole duration. Then scans slip, quiet-period timestamps drift, and "latency < poll + 200 ms" (DESIGN.md:19) ignores copy time entirely. **Change first:** decouple scan from copy (worker thread/queue), and stream copies (`shutil.copyfileobj`), not `f.read()` into RAM (syncd.py:56) — a multi-GB build artifact OOMs the daemon.

**2. Backpressure dict is NOT bounded by one poll (DESIGN.md:21-24).**
A file under continuous writes never reaches its quiet period, so it stays pending forever. Any producer faster than the copy loop grows `pending` without bound. First run also queues the whole 50k tree. Memory is not flat under burst.

**3. Integrity/crash safety doesn't hold.**
- dst writes are direct `open(dst,"wb")` (syncd.py:60) — not atomic. Crash mid-copy leaves a truncated file in `dst`; the journal has no entry, so nothing repairs it until the source changes again. The design's own tmp+rename rejection (DESIGN.md:59-61) applies only to the manifest, but file copies need it more.
- On requeue, `flush_one` still sets `self.synced[rel]=state` and appends the *pre-copy* state to the journal (syncd.py:64-74) — marking an incomplete copy as synced. Direct contradiction of DESIGN.md:26-28.
- Manifest rewrite in place + JSON-load-on-start (state.py:28-35): a partially written manifest makes `load_manifest` *raise*, so the "repaired by journal replay" claim (DESIGN.md:32-34) never runs. Journal replay also `json.loads` per line and dies on a torn final line — no tolerant parsing.

**4. The single-instance guarantee is invalid (DESIGN.md:41-48).**
- `acquire_lock` is `exists()` then `open()` — TOCTOU, two instances both win. Needs `O_CREAT|O_EXCL`.
- Stale lockfile after a crash means the daemon can never restart.
- Lock is taken/released *per cycle*, not for the process lifetime, so two daemons simply alternate cycles and both write `dst`. "Entries merge cleanly" is fiction — `manifest.update` is last-writer-wins, and concurrent `dst` writes interleave.

**5. Whole-second mtime + size is a real missed-change bug (DESIGN.md:72-74).**
`int(st.st_mtime)` (state.py:20) means two edits in the same second with equal size are invisible. Tools that preserve mtime (`cp -p`, tar, reproducible builds) are never detected at all. "mtime is guaranteed to change on every edit" (DESIGN.md:58) is wrong.

**6. Deletion handling is the most dangerous failure mode.**
A transient `os.stat`/permission/mount error during `snapshot` either crashes the daemon or makes files look "missing" → reconcile deletes them from `dst`. There's no distinction between "source gone" and "source unreadable". Deletions are also one-directional and unrecoverable. Gate deletes on a successful, complete scan and add a dry-run/`--verify` path first (it's already in GOAL.md).

**7. Smaller but concrete**
- Poll cost claim (DESIGN.md:13-15): 50k `stat`s every 500 ms ≈ 10M/min, synchronous, and cold/APFS/network FS blows well past 100 ms. No adaptive backoff.
- `observed` never drops deleted files → unbounded growth over daemon lifetime.
- Journal is unbounded (GOAL.md's compaction is needed before ship, not "next release").
- No signal handling / graceful shutdown; no fsync on journal so "loses nothing" is best-effort.
- design ignores symlinks/FIFOs/dirs/permissions and big-file streaming.

**Decisions to change before writing code:** (a) separate scan thread from copy workers with a bounded queue + streaming copies; (b) atomic dst writes (tmp+rename) and fsync journal/manifest; (c) a real process-lifetime `O_EXCL` lock with stale-lock recovery; (d) tolerant/atomic manifest commit and tolerant journal replay; (e) drop the whole-second-mtime assumption (use full `st_mtime_ns` or size+mtime_ns) and reconsider hashing for the verify path; (f) make deletions scan-complete-gated and safe by default.

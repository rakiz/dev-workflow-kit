Read DESIGN.md against `state.py`/`syncd.py`. The approach has one design-blocking flaw and several false load claims.

## Must change before coding

1. **Non-atomic manifest rewrite is not "repaired by journal replay"** (DESIGN:29–34). A crash mid-`open(path,"w")` leaves truncated/corrupt JSON; `load_manifest` (state.py:27) throws before replay ever runs — restart is bricked. Rejecting tmp+rename (DESIGN:59–61) is exactly backwards, and GOAL #3 (journal compaction after commit) makes it fatal: truncate the journal after a non-atomic commit and a crash loses manifest *and* journal. Do atomic commit + fsync first; compaction depends on it.

2. **Whole-second mtime is a data-loss bug, not an optimization** (state.py:19, DESIGN:70–74). `int(st_mtime)` + size means two same-size writes within one second are invisible; the post-copy re-stat (syncd.py:51–57) will also declare a torn copy "clean." "mtime is guaranteed to change on every edit" (DESIGN:58) is false at 1s resolution. Keep synccli's on-disk format if required, but change-detect in memory on `st_mtime_ns` + size (or hash on suspicion); otherwise `--verify` (GOAL #1) inherits the same blind spot and is not a real audit.

3. **Payload writes are non-atomic in `dst`** (syncd.py:49–50). Overwriting in place lets downstream build tools read half a `.py`/`.so`. The tmp+rename argument you rejected for the manifest matters *more* for payload files. Stage+rename per file.

4. **The PID lockfile doesn't provide single-instance and leaks forever.** `exists`+`create` (state.py:37–44) is racy, and SIGKILL leaves a stale lock → "already running" forever. Worse, DESIGN:44–48 releases the lock between cycles, so a second daemon *can* start mid-flight and "merge cleanly" is fiction — concurrent journal appends and `dst` writes have no ordering. If exactly-one is the contract, use `O_EXCL`/`flock` held for process lifetime with stale-PID recovery. Delete the "lock scope" paragraph.

## Wrong load assumptions

5. **"50k files <100 ms per poll" is optimistic.** `os.walk` + 50k `stat`s on cold cache / network FS / APFS is routinely 200 ms–2 s. Add full `load_manifest` **twice per cycle** (syncd.py:30,68) and an unconditional `json.dump` of 50k entries every 500 ms (syncd.py:70) — that's continuous multi-MB write amplification and SSD churn even when nothing changed. Commit only when dirty; keep the manifest in memory.

6. **"Pending set is bounded by one poll" is false.** If copy throughput < arrival (head-of-line blocking: `flush_one` is synchronous and blocks the whole batch on one large file), pending grows unboundedly. A continuously-written file never goes quiet and never flushes — so "latency stays under one poll + 200 ms while being written continuously" (DESIGN:18–20) is backwards: latency is unbounded until writes stop.

7. **Memory is not flat.** `f.read()` reads each file whole (syncd.py:46–47); one multi-GB artifact = OOM, not "flat under burst." Stream in chunks, and bound in-flight copies / use a worker pool so one big file doesn't stall 499 others.

8. **Deletions are not crash-safe and not journaled.** Crash after dropping the manifest entry but before deleting `dst` → orphan file stays forever. Also `self.synced` is never cleared and re-merged every cycle (syncd.py:69), so a reconciled deletion is resurrected into the manifest next commit. And `--verify`'s `missing_in_src` (GOAL #2) needs a stated policy — default should be delete+log, and deletions belong in the journal like writes.

## Smaller but real

- `time.time()` for debounce (syncd.py:35,53) — NTP steps can freeze or hot-loop flushing; use `monotonic()`.
- File mode/exec bit dropped (`open("wb")` under umask); scripts lose `+x` and break builds.
- Journal never fsynced, so "loses nothing" (DESIGN:29–31) is unproven; also grows forever until GOAL #3.
- "Config as constants on purpose" (DESIGN:63–68) is backwards — huge trees / network FS need tuning; hide them behind env/CLI with sane floors instead.
- No guard for `dst` inside `src` or `src == dst` → self-copy loop.
- Observability logs only pending count + commit duration; you can't distinguish "bounded" from "falling behind." Log queue depth, oldest-pending age, bytes copied/s, and per-file error counts.

**Bottom line:** fix atomic commit + fsync and the mtime resolution first — they invalidate the integrity and crash-safety claims — then replace per-cycle full manifest rewrite with an in-memory dirty-commit, hold the lock for the daemon lifetime, and make payload copies staged+rename and streamed.

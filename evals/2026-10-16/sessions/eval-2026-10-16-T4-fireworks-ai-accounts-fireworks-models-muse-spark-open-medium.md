Reading your design doc — I'll critique it for risks and failure modes next.

## Critique: `DESIGN.md` — Continuous Sync Engine v2

### 1. Polling every 500ms will not survive real load — this is the #1 change

**Claim:** "polling is cheap"
**Reality:** `scan_files()` + `file_state()` does `os.walk` + `os.stat` per file. At 50k files, one full scan is ~0.3–1.5s of I/O on SSD, longer on HDD/network FS. Doing that *twice per second* = 100% of one core, battery drain, I/O starvation for the user's actual work, and the loop never finishes within its interval. It degrades to continuous scanning with 0 idle time. Under burst (few files change per minute per spec), you pay O(N) to find O(1) changes.

**Fix first:** Invert to event-driven. Use `inotify`/`FSEvents`/`ReadDirectoryChangesW` via `watchdog` (or stdlib `select.kqueue` where available), with a poll fallback at 5–30s for missed events/network FS. Rejected as "platform-specific" is wrong — the abstraction lib exists precisely to hide this. If you must poll, make interval adaptive/configurable and scan incrementally.

### 2. Manifest: full JSON rewrite in-place, no atomicity — **data loss bug**

> `open(dst_manifest, "w")` + `json.dump` in place, every 500ms, "atomicity not needed"

On crash/kill/power loss mid-write you get a truncated JSON file = total state loss, next run does full re-copy of 50k files. At 2 writes/sec this window is hit quickly. Also write amplification: ~1–2MB JSON × 2/sec = ~150MB/min of pointless disk writes (SSD wear).

**Fix first:** `write to tmp + fsync + os.rename` (atomic on POSIX). Only write when manifest actually changed. For 50k files, SQLite or at least a WAL/journal beats JSON-in-full — "another dependency for little gain" is backwards at this scale; `sqlite3` is in stdlib.

### 3. `mtime + size` only — misses real edits

"mtime always changes on edit" is false:
- `cp -p`, `rsync -a`, `git checkout`, tar/zip restores preserve mtime.
- Coalesced writes within filesystem timestamp granularity (1s on ext4/HFS, 2s on FAT) with same size = silent miss.
- Size-preserving edits (config toggles, DB pages, fixed-record files) are common.

**Fix first:** Use `(mtime, size, inode)` for fast-path, fall back to content hash (e.g. `xxhash`/`sha256`) on `mtime` collision or add periodic full-hash verification pass (every N minutes, not every poll). At minimum document the inconsistency window as a known limitation.

### 4. Copy model is broken for live files

- Single-threaded immediate copy blocks polling (`synccli.py:84-85` `copy_file` reads entire file into RAM via `f.read()` — `synccli.py:67` — OOM on large files) while holding no lock on source. File being written mid-copy → torn/corrupt `dst` with no detection, and manifest already records it as synced.
- No handling of deletes/renames/moves: `dst` accumulates ghosts forever (`changed_files` only looks at new manifest, never prunes).
- Error handling divergence: `synccli.py:68-69` silently swallows `OSError`, DESIGN says "log to stdout" — stdout is reserved for `--json` machine output per `GOAL.md:5-7`. Logging there breaks every consumer. Must be `stderr` + structured log + retry with backoff.

**Fix first:** Copy to `dst.tmp` → `fsync` → `rename`; check `mtime` stable before/after copy (quiescence check, retry if changed). Stream in chunks, not `read()`. Handle deletes (tombstones/GC). Errors to `stderr` + counter, not swallowed.

### 5. Concurrency & rollout assumptions

- "Single process single thread is fine" contradicts the 50k-file/500ms claim — a single 500MB file copy stalls detection for seconds.
- Hardcoding 500ms "to prevent misuse" removes the operator's only backpressure knob. Make it configurable with sane default (e.g. 2–5s poll fallback, debounced watcher events 100–500ms) and document it.
- "Reuse `sync()` directly" (`synccli.py:72-87`) re-reads manifest from disk each call, has no locking — two `syncd` instances or a concurrent CLI invocation corrupt manifest (read-modify-write race). Needs `flock`/`fcntl` or DB locking.

### What to change before writing any code (priority order)

1. **Watchers + adaptive poll fallback** instead of 500ms full scan. Keep full scan as infrequent reconciliation (e.g. every 60s).
2. **Atomic manifest writes** (tmp+rename, write-on-change only); switch to `sqlite3` (stdlib) for incremental updates.
3. **Safe copy** (tmp+rename, chunked, quiescence check, delete handling).
4. **Correct error channel** (stderr/structured log, retry queue) — stdout must stay clean for `--json`.
5. **Content-hash safety net** for `mtime`-preserving cases; configurable interval.
6. **Config + locking** — poll interval, debounce, manifest lock.

Without 1–3, the daemon will thrash I/O, corrupt state on first crash, and silently miss/damage files under normal workstation load.


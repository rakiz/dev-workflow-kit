### 1. Major Risks

- **Per-cycle lock allows concurrent writers**: The PID lock is acquired and released every 500 ms (and released *before* the manifest commit). A second instance starting during the gap will run concurrently, causing interleaved file writes, corrupt JSON dumps, and silent manifest truncation.
- **Inverted durability / non-atomic writes**: Files are written in place via `open(dst, "wb")` with no `fsync` or atomic rename. Readers see truncated files mid-copy; power loss leaves `dst` corrupted while the manifest claims it is synced, preventing any automatic recopy.
- **Whole-second mtime causes permanent silent staleness**: The manifest and snapshot store `int(st_mtime)`. Successive edits within the same 1-second window keeping the same file size produce matching `(size, mtime)` tuples, rendering changes invisible forever.
- **Broken crash recovery**: `replay_journal()` is never called in the daemon lifecycle. A corrupted or partially written manifest raises an unhandled `JSONDecodeError`, putting the daemon into an unrecoverable crash loop.
- **Unhandled I/O exceptions**: `os.stat` / `open` lack `try/except`. Broken symlinks, mid-scan deletions, permission errors, or FIFOs (which block `open()` indefinitely) crash or freeze the daemon.

---

### 2. Wrong Assumptions

- **"Full scan costs well under 100 ms"**: Scanning 50k files with `os.walk` + `os.path.relpath()` takes ~0.4s on an absolute path and ~4.4s on relative paths (due to repeated `abspath`/`getcwd` syscalls), eliminating any headroom for 500 ms polling.
- **"mtime is guaranteed to change on every edit"**: False at 1 s resolution or across coarse filesystems (e.g., FAT/HFS+ or rapid sub-second build steps).
- **"Pending set is bounded / flat memory"**: Continuously updated files keep resetting their quiet period, starving forever and never syncing, while full manifest re-reads/dumps thrash memory.
- **"Renames need no special handling / deletions are handled"**: Deletion reconciliation is completely unhandled; `manifest.update(synced)` only adds entries, so deleted source files remain in `dst` and the manifest indefinitely.

---

### 3. What Breaks Under Real Load

- **Initial sync & burst stalls**: On startup or during mass file changes, 50k files debounce together. The daemon attempts to copy all 50k files and write 50k journal entries in a single synchronous cycle, blocking scans for minutes.
- **Disk write amplification**: Rewriting the entire 2.6 MB manifest JSON in place every 500 ms imposes ~5 MB/s of continuous disk writes even when completely idle.
- **OOM on large files**: `f.read()` buffers full files in memory rather than streaming chunks.
- **Timer drift & wall-clock dependency**: Using `time.time()` for quiet periods causes files to flush prematurely or stall indefinitely during NTP syncs or system sleep.

---

### 4. Decisions to Change First

1. **Lock for process lifetime**: Acquire an exclusive lock (`fcntl.flock` or `O_CREAT | O_EXCL`) once at daemon startup and hold it until exit.
2. **Atomic writes & crash safety**: Write files and manifests to temp files and replace atomically (`write tmp -> fsync -> os.replace -> fsync dir`), then sync the journal.
3. **Sub-second precision**: Add `mtime_ns` to the state cache and comparison logic (while keeping `mtime` for backwards compatibility).
4. **Fast scanning & dirty manifests**: Switch to `os.scandir`, normalize paths once upfront, keep the manifest in memory, and only commit to disk when state has actually changed.
5. **Fair batching & max-wait debounce**: Stream copies with bounded chunk buffers (`shutil.copyfileobj`), enforce a per-cycle copy batch limit, and add a max-wait ceiling to prevent starvation of active files.
6. **Explicit deletion & recovery path**: Implement proper diffing (`manifest.keys() - snapshot.keys()`) for deletions, and wire `replay_journal()` to run during startup before the first scan.

### 1. Major Risks
- **Data corruption & torn reads:** Immediate copying without a debounce/settle window copies partial files while editors or build tools are mid-write.
- **Catastrophic crash failure:** In-place JSON rewrite (`open(..., "w")`) is non-atomic. A kill or power failure mid-write destroys the manifest, causing `json.load()` failures and full resync storms on restart.
- **No deletion/rename support:** `changed_files` only iterates `new_manifest`. Deleted or renamed source files remain in `dst` indefinitely.
- **Silent divergence:** Relying solely on `mtime + size` without verification or hashing means undetected/missed changes never recover.

### 2. Wrong Assumptions
- **"Polling is cheap":** Scanning 50,000 files every 500 ms requires ~100k `stat` calls/sec sustained, thrashing CPU, disk metadata caches, and battery.
- **"The manifest file is small":** 50k entries serialized with formatting is 5–10 MB. Rewriting it twice a second sustained writes 10–20 MB/s to disk.
- **"mtime always changes on edit":** False for Git branch switches, `rsync -t`, archive extraction, or sub-second edits on coarse filesystems.
- **"Reusing `sync()` directly works":** `sync()` runs its own redundant tree walk, silently skips all dot-directories (`scan_files`), and `copy_file` loads entire files into memory (`fsrc.read()`), causing OOM on large files.

### 3. What Breaks Under Real Load
- **Loop overrun:** Scanning 50k files on a standard filesystem takes hundreds of milliseconds to several seconds. The walk will exceed 500 ms, pinning a CPU core at 100% and starving the system.
- **SSD wear & disk throttling:** Rewriting a 5–10 MB JSON manifest every 500 ms writes 36–72 GB/hour of pure metadata churn.
- **Single-threaded pipeline head-of-line blocking:** A single large or slow copy blocks polling completely, delaying detection of all other file changes.

### 4. Decisions to Change First
1. **Switch to OS event notifications (`FSEvents` / `inotify` / `watchdog`):** Use event-driven change capture; relegate full scans to an infrequent periodic reconciliation (e.g., every 10–15 min).
2. **Crash-safe state (SQLite or atomic replace):** Store manifest state in SQLite with indexed lookups, or at minimum write JSON to a temp file and `os.replace()` atomically.
3. **Handle deletions & renames:** Detect missing keys in `src` relative to previous state and remove/rename them in `dst`.
4. **Debounce writes:** Delay copying until file size and mtime remain stable across a brief quiet period (e.g., 500–1000 ms).
5. **Streamed & atomic copies:** Replace `fsrc.read()` with chunked streaming (`shutil.copyfileobj`), write to a `.tmp` file in `dst`, preserve timestamps, and atomically rename into place.
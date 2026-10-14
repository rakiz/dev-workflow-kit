### 1. Major Risks

- **Torn / partial copies & corrupted destination:** Copying immediately on change (`fsrc.read()`) catches files mid-write (compilers, downloads, non-atomic saves) and writes directly to `dst` (`open(dst, "wb")`) without temp-file + `os.replace`. Also, `fsrc.read()` loads the entire file into RAM, which will OOM on large files.
- **Corrupted manifest & false-sync state:** Rewriting the manifest in-place without atomic rename (`tmp` + `os.replace`) means any kill/crash mid-write leaves a truncated JSON file (`json.load` crashes on restart). Worse, `synccli.py:68` swallows `OSError` in `copy_file` and still writes `src_manifest` to `dst`, permanently marking failed copies as "synced".
- **Silent data divergence (no deletions or renames):** `changed_files()` (`synccli.py:36`) only checks `for rel in new_manifest`. Deleted files in `src` are never removed from `dst`, and renames copy the file anew while leaving the old path behind.

### 2. Wrong Assumptions

- **"Polling is cheap" (500 ms full scan of 50k files):** 50,000 `os.stat()` calls + sorting + dict diffing in Python takes hundreds of milliseconds to >1s depending on filesystem/OS cache. At a 500 ms interval, the daemon will run back-to-back at near 100% CPU/IOPS even when 0 files change.
- **"The manifest is small and we rewrite it in place on every poll cycle":** 50k entries in indented JSON is ~4–5 MB. Rewriting it every 500 ms (even when nothing changed) writes **~8–10 MB/s (~700 GB/day)** to disk for zero reason.
- **"mtime always changes on edit":** False for `git checkout`/`tar`/`rsync -a` (restores mtimes), intentional `touch`, or rapid same-size writes within coarse filesystem timestamp granularity.
- **"SQLite is another dependency":** `sqlite3` is in the Python standard library.
- **"Reusing `sync()` directly":** `sync()` re-reads and re-writes the full manifest on disk every call instead of keeping state in memory and persisting only when changes occur.

### 3. What Will Break Under Real Load (~50k files)

- **Idle workstation:** High constant CPU usage, laptop battery drain, and SSD wear from 100k `stat` syscalls/sec + 700 GB/day of no-op JSON writes.
- **Burst workloads (`git checkout`, `npm install`, build artifacts):**
  - Single-threaded blocking copies stall detection while copying thousands of files one by one.
  - Because `sync()` only writes the manifest *after* the entire batch finishes (`synccli.py:85`), an interruption mid-batch forces re-copying the entire batch.
  - No lockfile prevents concurrent `syncd` / `synccli` runs from clobbering `dst` and `.sync_manifest.json`.
  - Unreadable/locked files will retry and spam stdout twice per second forever without backoff.

### 4. Decisions to Change First

1. **Replace 500 ms full-tree polling with OS file events + slow reconciliation:** Use `watchdog` (FSEvents/inotify) with a 200–500 ms debounce/settle window, plus a slow full-tree reconciliation sweep (e.g., every 5–15 minutes). If polling only, keep manifest in memory, make interval configurable (e.g., 5–30s default), and only persist state when dirty.
2. **Make all writes atomic and streamed:** Copy in chunks (`shutil.copyfileobj`) to a temp file in `dst` and `os.replace()` on success. Write manifest updates via temp file + `os.replace()` (or stdlib `sqlite3` for O(1) incremental updates).
3. **Only record successful copies in state:** Never advance a file's manifest entry if `copy_file` failed; track retry backoff for failing files.
4. **Define deletion & exclusion semantics before coding:** Handle files present in `old_manifest` but missing from `src_manifest`, and exclude temp/VCS directories (`.git`, swap files) before scanning.
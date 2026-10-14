### 1. Major Risks
* **Silent data corruption from torn reads & non-atomic writes:** Copying immediately on a 500 ms poll catches files mid-write (before the writer finishes or renames into place). Because neither file copies (`copy_file`) nor manifest updates use temp-file + `os.replace`, crashes or concurrent reads leave corrupted partial files in `dst` and a truncated/corrupt `.synccli.json` (triggering a full 50k-file re-copy on restart).
* **Silent data loss on failed copies:** Rewriting the full manifest from the newly scanned state records the new `mtime`/`size` even if a file failed to copy ("log and continue"). Subsequent polls will see `old == new` and **never retry** the failed file.
* **No deletion or rename handling:** `changed_files()` only iterates `new_manifest`. Deleted or renamed files in `src` are orphaned in `dst` forever.

### 2. Wrong Assumptions
* **"Polling is cheap":** Walking 50,000 files every 500 ms requires ~100,000 `stat` syscalls/sec (and currently `scan_files` + `build_manifest` stats each file twice). In Python, 50k stats + sorting + dict building takes ~200–800 ms on warm cache and seconds on cold cache—consuming a full CPU core continuously and preventing OS disk sleep/battery idle.
* **"The manifest file is small and we rewrite it in place":** 50,000 entries in `indent=2` JSON is ~4–5 MB. Rewriting (and re-reading via `sync()`) it every 500 ms generates **~8–10 MB/s of continuous disk write amplification (~700 GB/day)** even when zero files change.
* **"mtime always changes on edit":** `git checkout`, `cp -p`, `tar -x`, backup restores, and rapid sub-tick writes can preserve or collide on `mtime` + `size`, causing edits to be permanently missed.
* **"Reusing `sync()` directly" works for a daemon:** `synccli.py`'s `copy_file` does `fdst.write(fsrc.read())` (loading entire large files into RAM) and silently swallows `OSError` (`pass`), while `sync()` re-reads and rewrites the JSON manifest on every call.

### 3. What Will Break Under Real Load (50k files, workstation)
1. **CPU & SSD thrashing while idle:** Constant 2 Hz full-tree walks and ~10 MB/s JSON rewrites will peg a core, drain laptop battery, and wear SSDs while only a few files change per minute.
2. **OOM / head-of-line blocking on large files:** Dropping a 4 GB video/ISO into `src` will spike RAM via `fsrc.read()` and stall all change detection for seconds/minutes.
3. **Mid-save race conditions:** IDE saves, compiler outputs, and `git` operations will be copied mid-write or fail with `FileNotFoundError` on ephemeral `.tmp`/lock files.

### 4. Decisions to Change First
1. **Keep state in memory and persist only on change (atomically):** Hold the manifest in RAM; write to disk only when files actually sync (or on a debounced timer), using compact JSON/SQLite via `.tmp` + `os.replace`. Only update a file's manifest entry *after* its copy succeeds.
2. **Use OS file events (FSEvents/inotify via `watchdog`) + slow reconciliation sweep, or at minimum increase/configure poll interval:** Do not poll 50k files at 2 Hz. If avoiding 3rd-party deps, make the poll interval configurable (default ≥ 5–10 s) and use `os.scandir()` (which yields `DirEntry.stat()` without a second syscall).
3. **Stream and stage file copies atomically:** Copy in chunks (`shutil.copyfileobj`) to a hidden staging file in `dst`, verify `stat` of `src` didn't change during the copy (debounce in-flight writes), then `os.replace` into `dst`.
4. **Define deletion semantics and log to `stderr`:** Explicitly handle `old_manifest - new_manifest` deletions, and log errors to `stderr` (keeping `stdout` clean for `--json`/pipes).
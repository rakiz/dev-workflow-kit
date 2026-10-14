### 1. What will break under real load (50,000 files @ 500ms)
* **I/O and CPU thrashing:** `stat()`-ing 50,000 files every 500ms equals **100,000 syscalls/sec**. On macOS/APFS or Windows, walking 50k entries takes hundreds of milliseconds to seconds—your poll cycle will exceed 500ms and pin a core + disk I/O at 100% permanently, draining laptop battery even when idle.
* **Manifest serialization bottleneck:** A 50,000-entry JSON file is **5–10 MB**, not "small". Serializing and writing 10 MB twice a second = **10–20 MB/s of continuous disk writes** (~1.7 TB/day of SSD wear) when zero files have changed.
* **Torn copies & partial writes:** Copying "immediately on detection" means catching files mid-write (e.g., video exports, `git checkout`, compiler outputs, large downloads), syncing corrupted half-written files to `dst`, or failing mid-copy and waiting another full cycle.

### 2. Wrong assumptions & major risks
* **"Atomicity is not needed" (Data Corruption):** Rewriting the manifest in-place without atomic rename (`write to .tmp` + `rename`) guarantees a truncated/corrupt JSON manifest if `syncd` is killed, crashes, or loses power mid-write. Also, copying files to `dst` directly in-place exposes partial files to readers on `dst`.
* **"mtime always changes on edit":** False for `mtime` granularity collisions (rapid writes within the same tick), `mmap` writes on some filesystems, tools that preserve timestamps (`tar`, `cp -p`, `rsync`), or clock skew/NTP adjustments.
* **"If unreadable, log and continue":** If you update the manifest after a failed/skipped copy, the file is never retried. If you don't update the manifest, it spams stdout every 500ms forever.
* **Deletions, renames, and symlinks are unaddressed:**
  * Renaming a 2 GB file or a directory of 5,000 files will trigger a full delete + re-copy unless tracked by inode (`st_ino`/`st_dev`).
  * What happens when a file is deleted in `src`? Does `sync()` delete it in `dst`? If `src` is accidentally unmounted or emptied, does `syncd` wipe `dst` within 500ms?
* **Single-instance locking:** Nothing prevents two `syncd` instances (or manual `synccli` + `syncd`) from running concurrently and corrupting both the manifest and `dst`.

### 3. Decisions to change first (before writing code)
1. **Use OS file watchers + fallback scan:** Use `FSEvents` / `inotify` (via a standard library like `watchdog` or `notify`) with a 100–500ms **debounce window** to let writes settle, plus a periodic full reconciliation scan (e.g., every 10–30 minutes, not 500ms).
2. **Only write state when state changes, and do it atomically:** Never rewrite the manifest if the diff is empty. When it does change, write to `manifest.json.tmp` and `os.replace()` (or use SQLite in WAL mode so single-row updates are O(1) instead of rewriting 10 MB).
3. **Copy atomically to `dst`:** Copy to `<dst>/.syncd-tmp-<name>`, verify size/mtime of `src` didn't change *during* the copy, then atomic `rename()` into place.
4. **Track `(inode, mtime_ns, size)`:** Use nanosecond mtime (`st_mtime_ns`) + `st_size` + `st_ino` to detect rapid edits and handle renames/moves cheaply without re-copying.
5. **Add retry/backoff state per file:** Transient lock/read errors need exponential backoff, not blind 500ms tight-loop retries or silent drops.
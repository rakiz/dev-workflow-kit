### 1. Major Risks

- **Inverted Scan vs. Poll Budget:** At 50,000 files, an `os.walk` + `os.stat` pass takes ~1.2–1.5s on local SSD. A 500ms full-tree poll budget is exceeded by >2× before copying any data. The loop will run continuously at 100% CPU with zero idle time.
- **Silent Data Loss on Copy Failures:** Existing `sync()` swallows `OSError` in `copy_file` and writes the full source manifest unconditionally. Any permission failure, vanished file, or disk-full error permanently records the file as synced in the manifest and is never retried. Reusing `sync()` directly inherits this data loss.
- **Corrupted Manifest on Crash:** Full in-place JSON rewrite without atomic temp-file replacement (`os.replace`) will corrupt the manifest if killed or crashed mid-write, forcing either boot failure or a full 50,000-file re-sync.
- **Torn Reads & Permanent Destination Corruption:** Copying while a file is being actively written copies partial bytes. If writing stops, the manifest already recorded the new `mtime`/`size`, so the partial copy is never repaired.
- **Unhandled FS Races in Scanner:** `os.stat` in `build_manifest` lacks `try/except` for `FileNotFoundError`/`PermissionError` (e.g., dangling symlinks or transient files deleted between `walk` and `stat`), terminating the daemon abruptly.
- **Deletions Ignored:** Only `new_manifest` entries are scanned; file deletions in `src` never propagate to `dst`.

---

### 2. Wrong Assumptions

- **"Polling is cheap":** False at 50k scale (~1.3s scan + ~4 MB JSON serialization per cycle = gigabytes of disk churn/hour just for the manifest).
- **"mtime always changes on edit":** False for archive extractions (`tar -x`), git checkouts, tools using `touch -r` / `utime`, or fast same-size edits within filesystem timestamp resolution.
- **"Atomicity is not needed because the file is small":** False. A 4 MB JSON payload is not atomic on POSIX filesystems without atomic rename semantics.
- **"Single thread delays are fine":** A large multi-gigabyte copy stalls detection for the entire tree for minutes.
- **"Hardcoded 500ms prevents misuse":** Hardcoding a rate that is mathematically impossible to sustain guarantees immediate failure under real trees.

---

### 3. What Will Break Under Real Load

- **50,000 files:** Continuous 100% CPU utilization, heavy battery drain, high SSD write amplification (~10 GB/hr rewritten for the manifest).
- **Concurrent writes:** Partial/corrupt files copied to `dst` without any reconciliation or hash validation.
- **Persistent errors:** Files with unreadable permissions will spam stdout at 2 Hz indefinitely.
- **Multiple processes:** Lack of a PID/flock file means running `syncd` twice will cause concurrent writes and race-corrupt the manifest.

---

### 4. Decisions to Change First

1. **Replace 500ms Full Polling:** Use OS file-system watchers (`inotify`/`FSEvents` via stdlib/minimal layer) with a slow fallback reconciliation sweep (e.g., every 5–15 minutes). If watchers are rejected, implement adaptive polling with exponential backoff on idle (30s+), never a 500ms full scan.
2. **Atomic State Storage:** Replace the in-place JSON rewrite with `write-to-temp + os.replace`. Better: use Python’s built-in `sqlite3` (stdlib, zero external deps) to commit entries individually upon *verified copy completion*.
3. **Advance Manifest Only on Confirmed Copy:** Never record an entry as synced unless `copy_file` succeeds.
4. **Prevent Torn Reads:** Copy to a destination `.tmp` file and verify `src` stat (`mtime` + `size`) after copy before renaming to target path.
5. **Handle FS Errors & Deletions:** Catch transient `OSError`/`FileNotFoundError` during scanning and implement tombstone/deletion propagation.
6. **Configurable & Safe Defaults:** Add process locking (`fcntl.flock`), graceful signal handling (`SIGTERM`/`SIGINT`), and rate-limited logging.
Here is a concrete critique of `DESIGN.md` before implementation.

---

### 1. Wrong Assumptions & Internal Contradictions

- **Whole-second mtime breaks both change detection and copy integrity (`Rollout`, `Integrity`, `Rejected alternatives`):**
  `snapshot()` stores mtime at whole-second resolution, yet the design assumes "mtime is guaranteed to change on every edit." Same-second edits that keep the same byte length (in-place overwrites, fast test edits, `git`/build tools) will have identical `(size, int(mtime))` and be **silently skipped**. Worse, the post-copy re-stat integrity check also misses writes occurring within the same second as the initial scan.
- **500 ms poll vs. 200 ms debounce math & starvation (`Debounce`, `Backpressure`):**
  - Sampling every 500 ms cannot observe a 200 ms quiet period—any write >200 ms before the next poll looks quiet, even if writes are happening every 250 ms.
  - "End-to-end latency stays under one poll plus 200 ms even while a file is being written continuously" directly contradicts "every further observed change restarts the quiet period." A continuously appended file (e.g., log/compiler output) **starves indefinitely**.
  - Pending state is not bounded by "one poll's worth of changes" if files keep restarting their quiet timer or if copying a burst takes longer than 500 ms.
- **Per-cycle lock release creates split-brain (`Single instance` vs. `Lock scope`):**
  `Single instance` claims a startup PID lock ensures only one daemon writes to `dst`, while `Lock scope` releases the lock every cycle *before* committing the manifest. A second instance starting in that window reads a stale (or half-written) manifest, scans, and writes to `dst` concurrently while the first instance loops back and tries to re-acquire the lock.
- **`os.walk` < 100 ms for 50k files is fragile (`Scan`):**
  Under cold cache, macOS/Docker filesystems, or concurrent build I/O, 50k `stat` calls easily exceed 500 ms. Polling twice a second will pin CPU/metadata I/O and continuously overrun the poll budget.
- **In-place manifest rewrite defeats journal recovery (`Crash safety`, `Rejected alternatives`):**
  Rewriting the manifest in place truncates it before writing. A crash mid-write leaves a corrupt/empty manifest on disk. Unless the journal retains the *entire* 50k-file history forever (no compaction/truncation policy is defined), journal replay cannot reconstruct the lost baseline—causing mass false-deletes or full re-copies. Writing a manifest via `tmp + os.replace` only when dirty avoids this without meaningful write amplification (unlike rewriting 50k entries every 500 ms).

---

### 2. What Will Break Under Real Load

- **Build bursts will wedge the poll loop and thrash disk:**
  Sequential copying of hundreds of changed files + 50k-entry `os.walk` + full in-place manifest rewrite every cycle (even when idle or 1 file changed) causes severe write amplification and multi-second/minute cycle stalls.
- **Torn reads & partial files in `dst` (`Integrity`):**
  Copying directly over `dst` files instead of staging to a temp file + `os.replace` exposes truncated/half-written files to any reader in `dst` and leaves corrupt files in `dst` on crash.
- **False mass deletions on transient build/FS errors (`Deletions`, `Errors`):**
  If a directory is temporarily recreated (`rm -rf out && mkdir out`) or `os.walk` hits a transient permission/ENOENT error and skips a subtree, comparing against the manifest will treat the missing subtree as deleted and **wipe `dst`**.
- **Unaddressed edge cases in the tree:**
  Symlinks (broken symlinks vs. symlink loops), directory creation/deletion ordering, and atomic-rename writes (`tmp` -> `target` causing `dst` delete+create churn across poll boundaries) are not handled.

---

### 3. Decisions to Change First

1. **Hold an OS advisory lock (`flock`/`fcntl`) for the full daemon lifetime** (never release between poll and commit), and drop PID-only files.
2. **Persist state atomically:** Rewrite the manifest via `tmp + os.replace` **only when dirty** (not every 500 ms), and define explicit journal rotation tied to manifest commits (or use SQLite in WAL mode instead of flat manifest + journal).
3. **Use `st_mtime_ns` + `size` (+ `st_ino`/`st_ctime_ns`)** instead of whole-second mtime, and add a max-debounce cap so continuously written files still sync boundedly.
4. **Stage copies atomically in `dst`** (`dst/.tmp-*` + `os.replace`) so `dst` never exposes partial files.
5. **Use `os.scandir` (or OS watchers + slower safety rescan) and guard deletions** so transient `os.walk` errors skip reconciliation for the affected subtree instead of deleting `dst`.

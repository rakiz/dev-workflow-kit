I wrote the design to `DESIGN-d1.md` in this repo copy. No `backupctl` code exists yet. The existing code is untouched and its 6 tests still pass.

**Existing code**
- I ran probes against the existing code and the design cites the results with file and line numbers.
- Several functions don't do what they claim:
  - `copy_file` swallows `OSError`, yet `sync()` still records the failed file in the manifest, so it is never retried.
  - A truncated manifest makes the next `sync()` crash.
  - `scan_files` silently drops dot-directories, directory symlinks and unreadable directories.
  - `safe_snapshot_path` lets `..` and absolute paths escape the snapshot.
  - `prune_snapshots(keep=0)` deletes every snapshot.
- Each override is named in the design with its file, function and reason.
- Three pieces are reused: `scan_files`' walk loop, `changed_files` (unchanged), and `list_snapshots` (behind a name filter).

**Design**
- **Snapshots:** one per directory per run. Each is a full plain tree where unchanged files are hard links to the previous snapshot.
- **Concurrency and crashes:** a snapshot is built in a staging directory and published by one atomic rename. Writers on the same directory take a `flock`. Readers can optionally take shared leases.
- **Failed files:** vanished files are omitted and the run still counts as complete (exit 0). Unreadable or unstable files make it a partial snapshot (exit 3). The behavior is the same whoever starts the run.
- **Corrupt index:** the snapshot is quarantined, its tree is hashed and compared to the live source, and the run reports `RECOVERED`.
- **Change detection:** "unchanged" is decided by size, mtime, ctime and mode, plus a check for files modified just before the last scan. The limits of this granularity are stated in the design.
- **Retention:** at most 19 snapshots per directory, and the newest complete one is never deleted. Deletion renames a snapshot out of the listing before removing it.

**Performance**
- I measured a synthetic tree of 30,000 files and 1 GiB. The initial full backup ran in 7.3 s with 4 threads and 14–17.7 s single-threaded. The stated budget is ≤ 30 s.
- The per-run, memory and disk bounds in the design are formulas with constants measured on this machine.
- All measurements were on APFS with a warm cache. I could not purge the page cache, so cold-cache figures are derived, not measured.
- An unchanged run costs about 7 s per 30,000-file directory because of the hard links, versus 0.79 s for `synccli`. The design explains this tradeoff and why I rejected sparse snapshots.

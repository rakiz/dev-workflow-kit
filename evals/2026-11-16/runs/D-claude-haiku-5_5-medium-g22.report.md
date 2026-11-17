The design is written to `DESIGN-d1.md` in the repo directory. I did the work alone, with no subagents.

Key decisions:

- **Concurrency:** one writer at a time, enforced by an exclusive `flock` on `run.lock`. A second run exits with code 75 instead of queuing. Restore takes a shared lock on each snapshot, and pruning takes an exclusive lock, so a snapshot being read is never deleted.
- **Commit:** a run builds in a staging directory and publishes with one atomic `rename`. A `snap-*` directory exists only when complete. The committed `MANIFEST.json` is the index, so there is no separate index file to corrupt.
- **Recovery:** on startup, staging and trash are discarded. Any snapshot whose manifest fails its checksum is quarantined, and the next older valid one becomes the baseline. The run reports each of these actions.
- **Vanished or unreadable files:** skipped and recorded in the manifest with a reason. The snapshot is still published, and the exit code is 3. Scheduler and person runs behave identically.
- **Change detection:** per file, on `(size, mtime_ns, inode)`, with a 2 s racy-timestamp guard. The design lists what this misses: same-size edits that also preserve mtime, and metadata-only changes. `--verify` closes the first gap.
- **Retention:** keep the newest K valid snapshots (default 14, minimum 1). Deletion is an atomic rename, skipped if a reader holds the lock.

Performance (30,000 files, about 1 GB, measured on this host with a warm cache):

- Walk and stat: 0.70 s.
- Copy with per-file fsync: 18.0 s.
- SHA-256 over 1 GB: 5.7 s.
- Derived initial backup: about 24.5 s. The budget is 60 s.
- The budget is provisional. Cold-cache and target-disk timings are still needed.
- Incremental runs are dominated by hardlinking unchanged files, at 11 s for 30,000 files.

Grounding: the design overrides several existing functions, and each override is cited with file and line. The main ones:

- `sync()` (`synccli.py:72-87`) records a file in the manifest even when its copy failed, so the file is never retried. I reproduced this.
- `prune_snapshots` (`snaputil.py:23-36`) can delete the only valid snapshot if a newer one is incomplete. I checked this by reading the code; I did not run it.
- `safe_snapshot_path` (`snaputil.py:54-63`) lets `..` and absolute paths escape the snapshot. I reproduced this.
- `is_stale` (`snaputil.py:66-73`) contradicts its own docstring. I reproduced this.

Existing tests: 6 pass. The design adds a test plan for the overrides.

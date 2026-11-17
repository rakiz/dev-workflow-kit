I wrote the design to `DESIGN-d1.md` at the top of the repo copy. I did all the work myself, with no subagents. The existing 6 tests still pass, and I changed no code.

The design's main points:

- **Snapshots:** each run covers all N directories and publishes one immutable `snap-<UTC>-<ordinal>` directory. It becomes visible only through an atomic rename of a fully fsynced staging directory.
- **Change detection:** per file, on `lstat` metadata including `ctime_ns`, plus a 2 s racy-timestamp guard. I checked that the existing `(size, mtime)` state misses an edit whose mtime is restored with `utime`. `ctime` catches it.
- **Locking and crashes:** a global `flock` serializes runs and pruning. Restore takes a per-snapshot shared lease, and prune skips leased snapshots. Staging left by a dead run is discarded at the next run, and a corrupt published index is reported and never used as a baseline.
- **Vanished or unreadable files:** they are left out of the snapshot and listed under `skipped` in its metadata. The run exits 3. Scheduler and person runs behave identically.
- **Retention:** keep the newest K valid snapshots, K >= 1. Pruning runs only after a new publish, and it renames before deleting.
- **Budget:** 120 s for the initial backup of ~1 GB / 30k files. Measured steady state is 11–17 s, so the margin rests on a single SSD measurement.

Grounding: the design reuses `changed_files` and `list_snapshots`. It overrides the others, with file and line references. Several existing behaviors are defects, verified by running them:
- `scan_files` drops `.git/` and symlinked directories.
- `copy_file` swallows read errors, so an unreadable file is recorded as synced and never retried.
- `sync` raises on a truncated manifest and never deletes files removed from the source.
- `safe_snapshot_path` does not contain `..` or absolute paths.
- `is_stale` returns True on equality, contrary to its docstring.

A finding that changes the design: hardlinking an unchanged file costs about 0.33 ms here. A no-change run over 30k files takes about 10.5 s, not 0.3 s. The savings are in bytes and disk, not wall-clock. I kept hardlinks because they keep snapshots as plain browsable trees. The design names a switch to a content store if a no-change run exceeds 10 minutes.

Open decisions for you are in section 13. The main one is macOS power-loss durability. `os.fsync` is what I measured, and `F_FULLFSYNC` would need its own measurement and could change the budget.

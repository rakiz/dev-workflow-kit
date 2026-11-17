I wrote the design to `DESIGN-d1.md` in this repo copy. I did it alone, with no subagents. The file covers every point the brief asks for: the layout, the run protocol, locking, crash recovery, vanished and unreadable files, change-detection granularity, retention, the performance budget, and the scaling bounds.

**Design in brief**
- Each run builds a complete snapshot in a staging directory and publishes it with one `rename`. Readers only ever see finished `snap-*` directories.
- One writer at a time, enforced by an exclusive `flock`. A second run exits 75 instead of waiting. The kernel releases the lock if the process dies, so it never goes stale.
- Unchanged files are hardlinked from the previous snapshot. Change detection uses `(size, mtime_ns, ctime_ns, ino, mode)`, with a racy-entry rule for files modified within 2 s of their snapshot.
- Restores take a shared lock per snapshot. Retention renames a snapshot before deleting it, and defers the deletion if a reader holds the lock. It keeps the newest K ≥ 1 verified snapshots.

**Grounding problems I found in the existing code** (the design overrides each one)
- `snaputil.safe_snapshot_path` does not contain `..` or absolute paths. `../../etc/passwd` and `/etc/passwd` both escape the snapshot. I reproduced this.
- `snaputil.prune_snapshots` with `keep=0` deletes every snapshot. I reproduced this too. It also uses a non-atomic `rmtree` and ignores readers.
- `synccli.copy_file` silently swallows read errors. A file that fails to copy is still recorded in the manifest, so later runs never retry it. I reproduced this with a mode-000 file.
- `synccli.build_manifest` aborts the whole run if a file vanishes between the scan and the stat. I reproduced this.
- `synccli.sync` writes the manifest non-atomically, so a corrupt manifest crashes the next run.

**Performance budget**
- The budget is 60 s for the first full backup of a 1 GiB / 30,000-file tree on this machine (M3 Max, APFS, warm cache).
- The existing `synccli.sync` took 8.3 s on that tree. A per-file-fsync copy took 11.2 s. The predicted total for the design is about 15 s, so the 60 s budget leaves about 4× headroom.
- Cold cache and rotating disks are not measured. The design says the budget applies only to this host class and makes re-measuring on the deployment storage an acceptance criterion.

The design is in `DESIGN-d1.md`. I did not change any existing code. The only other change is that I created a 1 GiB scratch tree under the temp directory for timing, and I deleted it afterwards.

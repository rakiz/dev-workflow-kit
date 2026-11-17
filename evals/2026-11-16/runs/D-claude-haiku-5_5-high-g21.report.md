The design is written to `DESIGN-d1.md` in the repo copy. I did all the work myself, with no subagents.

**Design in brief**
- **Commit:** each run builds a `.tmp-<id>/` staging directory and publishes it with one `rename` to `snap-…`. Readers never see a partial snapshot.
- **Concurrency:** one global `flock` serializes runs and prunes. A second run exits 75. Restores hold a shared lease per snapshot, and prune skips leased snapshots.
- **Crash recovery:** the next run deletes `.tmp-*` and `.trash-*` leftovers. A corrupt committed index is not used as a base and is never auto-deleted.
- **Change detection:** per file, on `(size, mtime_ns, ctime_ns, ino)`. Recently modified files are marked "racy" and re-copied. Unchanged files are hard-linked from the newest valid snapshot.
- **Vanished or unreadable files:** omitted from the index and listed in the report. The run commits and exits 3. Those files are retried next run.
- **Retention:** keep the newest K (default 14) and always keep the newest valid snapshot.

**Existing code problems found by running probes** (these drive the overrides in section 2 of the doc)
- `snaputil.prune_snapshots(root, 0)` deleted all snapshots, including the newest.
- `snaputil.safe_snapshot_path` does not stop `../` or absolute paths from escaping the snapshot.
- `snaputil.is_stale` returns True at the exact boundary its docstring says it should not.
- `synccli.copy_file` silently drops unreadable files, and `sync` still records them in the manifest. A file made unreadable was never retried after it became readable again.
- `synccli.scan_files` skips dot-directories and silently drops symlinked directories.
- A corrupt manifest makes `sync` crash with no recovery path.

**Performance**
- Initial backup of a 1.024 GB tree with 20,000 files: scan 0.47 s, copy about 5.6 s (about 183 MB/s), fsync about 3.4 s. The derived total is about 9.5 s.
- Budget: 60 s on this host. This is a derived target, not a validated one. Cold-cache, external-disk and `F_FULLFSYNC` timings were not measured.

Open items are listed in section 5 of the doc. The main one is that `os.fsync` on macOS does not give full power-loss durability. I did not change any existing file. The `snaputil` bugs are reported, not fixed, per your ask-before-acting rule.

I wrote the design to `DESIGN-d1.md` in the repo copy. I worked alone, with no subagents.

I checked the existing code by reading it and running it. The current suite passes (6 tests). These defects are confirmed:

- **`snaputil.safe_snapshot_path`** does not contain paths as its docstring claims. `../../etc/passwd` escapes the snapshot, and an absolute path replaces the prefix entirely. The design replaces it for restore.
- **`synccli.copy_file`** silently swallows read errors, and `sync` still records the skipped file in the manifest. An unreadable file is never retried. The design overrides both.
- **`synccli.changed_files`** misses a same-size edit whose mtime was restored with `utime`. The design adds `ctime_ns` and `st_ino` to the change check.
- **`synccli.build_manifest`** crashes if a file vanishes between listing and stat. Also, `json.load` on a corrupt manifest raises instead of recovering.

The performance budget comes from measurement. On a 1 GB tree of 20,000 files, the existing scan takes 0.52 s and the existing full copy takes 9.78 s. Adding fsync per file puts the derived total near 13 s, and the design sets a 60 s budget with margin. The SHA-256 streaming cost and cold-cache behavior are not measured, and the document says so.

The design covers the commit protocol (a single rename as the commit point), crash recovery, locking, and retention. It also covers vanished and unreadable files and a bound table for how work, memory, and disk scale with N and the file count. Open items are listed at the end.

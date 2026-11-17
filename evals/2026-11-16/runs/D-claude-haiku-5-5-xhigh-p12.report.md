The design is written to `DESIGN-d1.md` (460 lines) at the repo root. I did the work alone, with no subagents. Nothing else in the repo changed, and the existing 6 tests still pass.

**Existing code defects found.** I reproduced each one before the design overrides it:
- `synccli.copy_file` swallows read errors. The file is reported as copied, is absent from the destination, and is never retried.
- A truncated `.sync_manifest.json` makes `synccli.sync` crash on every run.
- `synccli.file_state` uses `(size, mtime)`, so a same-size rewrite with restored mtime is missed.
- `scan_files` silently drops dot-directories, unreadable subtrees, and symlinked directories.
- `snaputil.prune_snapshots` with `keep <= 0` deletes every snapshot.
- `snaputil.safe_snapshot_path` lets `../` and absolute paths escape the snapshot.
- `snaputil.snapshot_disk_usage` crashes if a file vanishes during the walk.

**Design in brief.**
- Each configured directory is a series with its own lock. Snapshots are `snap-…` directories, published by one atomic rename from a hidden staging directory.
- Each snapshot carries a footer-checked index. A reader never sees a snapshot without a complete index.
- Unchanged files are hard-linked from the newest valid snapshot. Change detection uses size, mtime, ctime, inode and device, with a 2 s racy window.
- Restores take a shared lock. Deletion renames a snapshot to a hidden name before removing it.
- Source files that vanish or fail are skipped and listed in the index and report, and the run exits 3. Scheduler and person get identical behavior.
- Retention keeps the newest `keep_last` (default 10, minimum 1) plus the newest clean snapshot.

**Performance numbers** (1.0 GiB, 30,000 files, M3 Max, APFS, warm cache):
- Initial backup budget: at most 45 s. The measured components sum to about 14.6 s, and the budget is roughly 3× that. The 3× headroom is a judgment, since cold-cache and slower disks were not measured.
- A no-change run costs about 13 s, dominated by hard-linking at about 0.37 ms per file. APFS clones and `cp -Rl` are no cheaper per file on this machine.
- Memory is bounded by the largest series, about 86 MiB at 30,000 entries, and does not grow with the number of directories.

**Decisions I need from you** (listed in section 14 of the doc):
- **D1:** Accept the per-run hard-link cost, or switch to a content-addressed object store. The store cuts per-run file operations but breaks the directory-snapshot model that `snaputil` assumes.
- **D2:** Confirm `keep_last = 10`.
- **D3:** Accept best-effort power-loss durability. Process death and sleep are covered by write ordering alone.
- **D4:** Confirm that symlinks are recorded as links, not followed.
- **D5:** Decide whether to fix or remove the unsafe `snaputil` functions in a separate change. The design does not call them.
- **D6:** Confirm the JSON config format.

**Caveats.** Everything was measured on macOS/APFS with a warm cache. The design has not been built or run end to end, so the 13 s no-change and 13.1 s expected figures are estimates. Power-loss behavior was not tested. The measurement scripts live outside the repo in `/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/opencode/d1-scratch/`.

Wrote `DESIGN-d1.md` (499 lines) in the repo copy. No other files changed.

Highlights:
- **Grounded** on `synccli.py`/`snaputil.py` by exact file:line, reusing `scan_files`, `file_state`, `build_manifest`, `changed_files`, `list_snapshots`, `prune_snapshots`, `snapshot_disk_usage`, `safe_snapshot_path`, `is_stale`.
- **Six named overrides** of existing behavior, each citing the function/lines it replaces (e.g. the non-atomic manifest write at `synccli.py:85-86`, the whole-file/error-swallowing `copy_file` at `synccli.py:62-69`).
- **Atomic commit**: build in an invisible `.staging-*` dir, write the index via `os.replace`, commit with one `rename(2)`; readers only ever see complete snapshots.
- **Concurrency**: single `flock` (kernel-released on death); fail-fast/wait policy.
- **Crash recovery**: automatic staging/trash sweep; index checksum validation with re-derivation from the snapshot tree and quarantine otherwise.
- **Vanished sources**, **incremental (size,mtime) hard-link dedup** with its blind spots, and **reader-safe retention** (rename-to-trash then delete).
- **Measured performance budget** for 1 GB / 20k files (~8.2 s measured, ≤30 s budget) with derivation, plus a full scaling-bounds table and an appendix of the actual measurements (including the counter-intuitive finding that APFS hard-links aren't faster than copies, so the incremental win is disk, not wall-clock).

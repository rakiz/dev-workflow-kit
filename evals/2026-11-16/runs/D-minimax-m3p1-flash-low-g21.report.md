`DESIGN-d1.md` written. It covers:

- **Grounding**: every requirement mapped to existing code with line numbers (`synccli.scan_files:10`, `file_state:22`, `build_manifest:28`, `changed_files:36`, `collect_stale:45`, `copy_file:62`; `snaputil.list_snapshots:8`, `prune_snapshots:23`, `is_stale:66`), plus an explicit override list (why `synccli.sync`, `synccli.copy_file` and `snaputil.prune_snapshots` are replaced, and the `is_stale` docstring/code boundary discrepancy).
- **Safety**: per-source `flock` for writers, `incoming/` staging + atomic `rename` publish, atomic index writes, tombstone→rename→rmtree deletion, index Cases A/B/C recovery, excluded-file handling.
- **Performance**: measured on a real 1 GB / 30 000-file tree on this volume — 24.7 µs/file scan, 70 MB/s copy, 215 µs clonefile, 356 µs hardlink, 393 B/entry memory → ~25 s measured, 45 s budget for the initial full backup; explicit formulas for per-run time, memory, and disk.
- Test plan for the implementation.

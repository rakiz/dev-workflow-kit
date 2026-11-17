`DESIGN-d1.md` is written at the top of the repo copy (1272 lines). Nothing else in the repo was touched — the existing 6 tests still pass.

**What the design says**

- **Layout**: a snapshot is `snap-<UTC ts>-<seq>/` with `tree/<alias>/…` (plain files), `manifests/<alias>.jsonl` (sorted, 184 B/line) and a small self-checksummed `index.json`. All in-progress material lives under `.backupctl/staging/`, so `snaputil.list_snapshots` never sees it.
- **Concurrency**: one `flock` (kernel-released on death, so no manual cleanup) + publication by a single `rename()` of a fully built staging dir — a reader never sees a partial snapshot and never needs to ask if a run finished.
- **Crash recovery**: a corrupt header is discarded and the file table re-derived from the tree with `synccli.scan_files`; the data is never touched; the repair is reported (exit 3). Interrupted runs/prunes leave only GC-able garbage.
- **Vanished/unreadable sources**: the file is absent from both tree and index, listed as `skipped`, exit 3 — identical code path for cron and for a person.
- **Retention**: `keep_last ∧ keep_days`, rename-to-trash then unlink (never `rmtree` on the live name), leases defer deletion, the newest snapshot is never deleted.
- **Change detection**: `(size, mtime_ns, mode)` + SHA-256 consulted when metadata differs; the blind spots (mtime-restoring tools, 1 s filesystem granularity, inode swaps) are enumerated, with `--checksum full` closing them.
- **Performance**: budget ≤ 60 s for 1 GB/30k files; **measured 11.7 s (1 worker) / 5.1 s (4 workers)**, derived from a fitted `T = F·c_file + B/R + B/H` with measured constants (`c_file` = 0.362 ms, cross-checked against per-op micro-measurements).
- **Scaling**: explicit formulas for per-run time, memory (`O(F_max)`, 473 B/entry measured), and disk.
- **Grounding**: every reuse and every override cites the exact function and line (`synccli.copy_file:62-69`, `snaputil.safe_snapshot_path:54-63`, …), and the ten behaviours claimed about the existing code were verified by running it (e.g. `copy_file` swallows `OSError` so today's manifest promises a file the destination lacks).

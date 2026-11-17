`DESIGN-d1.md` is written (925 lines). The repo copy is otherwise untouched and the existing suite still passes (6 tests, OK).

**What the design says, in brief:**

- **Atomicity** — a run builds the snapshot in `<root>/.incoming/<run-id>/` and publishes it with one directory `rename` (measured 0.110 ms). A snapshot is therefore visible only when complete; a dead run leaves only staging garbage that the next run GCs. The index is written *inside* the staging dir, so it is published atomically with the tree it describes.
- **Concurrency** — `flock` on `<root>/.lock` serializes colliding runs (second one waits, then exits 75); defence in depth: even without the lock, private staging + unique atomic publish means two runs cannot corrupt each other. A run never writes into a published snapshot, so a restore running concurrently is unaffected.
- **Retention** — two-phase: atomic tombstone (`rename` into `.trash/`) then delayed reclaim. This overrides `snaputil.prune_snapshots` (`snaputil.py:35`), which empties a snapshot in place — exactly the "half-deleted snapshot a reader can see" failure. `snaputil.list_snapshots` is reused.
- **Missing/unreadable files** — omitted, reported, exit 3; retried automatically next run (the file is simply absent from the manifest, so the diff sees it as new). Identical code path and exit codes for scheduler and human triggers.
- **Granularity** — per file, `(size, mtime)` via `synccli.file_state`; the design enumerates exactly what that misses (mtime-preserving edits, FS timestamp granularity, metadata-only changes) and why hashing is not used.
- **Budget** — measured end-to-end **17.7 s for a 1.85 GiB / 35,000-file tree**, with a formula whose constants are all measured (scan 8.3 µs/file, copy 185 µs/file, fsync 30 µs/file, publish 0.110 ms); committed ceiling **≤ 30 s for ~1 GiB / tens of thousands of files**. Incremental run: 7.50 s measured.
- **Scaling** — explicit bounds: time grows linearly in N and F; memory is `944 B × F_max` (≈33 MB) and does **not** grow with N; disk is `B + (K−1)·Δ` (CoW clone shares unchanged content: measured 0.0 MiB for 8 clones vs 2068 MiB for 4 copies) plus `K·F·7.9 B` of manifests.
- **Grounding** — every reuse and every override is named with file:line, and four latent defects in the existing code are verified by reproduction (dot-directory dropping at `synccli.py:14`, swallowed `ENOENT` at `synccli.py:68-69`, the `..` path-escape in `snaputil.safe_snapshot_path` at `snaputil.py:54-63`, and the `is_stale` docstring/code contradiction at `snaputil.py:66-73`).

The measurement harnesses live outside the repo (`/private/var/folders/…/opencode/bench*.py`) and are indexed in Appendix A; say the word if you want them copied into the repo for reproducibility.

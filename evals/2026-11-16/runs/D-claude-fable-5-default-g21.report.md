Done — `DESIGN-d1.md` is written. Key points:

- **Atomicity model**: runs build in `.staging/`, publish via a single `os.rename` into the `snap-*` namespace that `snaputil.list_snapshots` (snaputil.py:8-20) already filters on — readers can never see partial snapshots, crashes leave only invisible staging garbage reaped by the next locked run.
- **Grounding**: reuses `scan_files`/`file_state`/`changed_files`/`build_manifest` from synccli.py as-is; explicitly overrides `copy_file`'s silent-swallow + truncation bug (synccli.py:62-69), `sync`'s non-atomic manifest write (synccli.py:85-86), and `prune_snapshots`' in-place `rmtree` (snaputil.py:35) — each with location and reason.
- **Measured budget**: I actually ran the existing code — 271 µs/file overhead, ~92 MB/s, 24 µs/file stat — deriving ~20 s for 1 GB/30k files, budget ≤60 s with 3× headroom. Scaling bounds in §7 are formulas over F/B/f/b, with memory ~200 B/manifest entry.
- **Retention**: keep-newest-K via `prune_snapshots`' selection rule, but deletion goes rename-to-tombstone + grace-period reap (using `snaputil.is_stale`) so readers aren't yanked mid-restore; residual risk stated.
- Unit tests (`python3 -m unittest`) pass, backing the measurement harness claims.

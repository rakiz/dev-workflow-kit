Done. `DESIGN-d1.md` (711 lines, 15 sections) is written to the repo copy; no other repo files touched (benchmarks ran from the temp dir), and I worked alone.

Grounding and rigor:
- **Reused-as-is table** + **7 explicit overrides**, each citing exact `file:function:line` and reason — e.g. overriding `copy_file`'s silent skip (`synccli.py:68-69`) because `sync()` builds the manifest pre-copy (`:74`), which would make the index over-promise; `scan_files`' dot-dir filter (`:14`); `prune_snapshots`' in-place `rmtree` (`:35`).
- **Atomic visibility / crash safety**: invisible `.staging-…` + single `os.rename` commit; index built *after* materialization so it lists only files that landed; corrupt-index recovery re-derives via `build_manifest` (`synccli.py:28`).
- **Concurrency/restore**: correctness rests on immutability + atomic commit (not the lock); safe deletion via rename-to-`.trash-…` + grace (`is_stale`, `snaputil.py:66`) + POSIX unlink semantics.
- **All numbers measured** on this machine against the real functions (tests pass): scan+stat 34,236 files/s, safe copy 2,982/s, clonefile 5,952/s, `os.link` 2,727/s, 3,692 MB/s, 379 B/manifest-entry. First-full budget **<60 s** for ~1 GB/50k files, derived (~18.5 s here) — dominated by per-file overhead, not bytes.
- **Scaling bounds** as formulas over N/F/B: per-run `O(F)`, peak RSS `≈2·Fmax·379 B`, disk dedup via clones, and what stays flat (staging ≤1, fds `O(1)`, fsyncs `N+1`).

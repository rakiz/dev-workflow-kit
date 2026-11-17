Done. `DESIGN-d1.md` is written to the top of the repo copy.

Summary of the design's key decisions:

- **Grounding**: reuses `synccli.build_manifest`/`changed_files`/`file_state` and all five `snaputil` helpers (exact line citations in §1), with three explicitly named overrides: `synccli.scan_files`' dotfile filter (silent data loss in a backup), `synccli.copy_file`'s silent `except OSError: pass` and whole-file read, and a wrapper around `snaputil.prune_snapshots`' in-place `rmtree` (trash-rename first, recovery defined for the crash window).
- **Consistency**: single-writer `flock` on `backup_root/backupctl.lock` (run×run), build in `staging-*` + one atomic `rename` to `snap-*` (run×restore), index built from copy *outcomes* so it can never promise files the snapshot lacks.
- **Crash recovery** tabulated in §8: staging discarded, partial snapshots demoted via `synccli.collect_stale`, corrupt previous index → full re-derive from the tree with WARN.
- **Performance budget**: measured on this machine — scan 42,470 files/s, copy 158–262 MB/s, link 2,900/s, index ~60 B/file — deriving ≈8–12 s for a 1 GB first backup; budget set at <60 s with the derivation shown.
- **Scale bounds**: every quantity stated as a formula over N/F/B with the measured constants (§11).

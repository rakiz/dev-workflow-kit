`DESIGN-d1.md` written (43 KB), worked alone, repo otherwise untouched, tests still pass.

The design: rsnapshot-style snapshots (staging dir → atomic rename publish, hardlinks for unchanged files, flock single-writer, two-phase trash deletion, landed-set manifests, index-as-cache with tree-is-truth recovery). Key points:

- **Grounded**: every reuse cites file:lines (`file_state`, `changed_files`, `collect_stale`, all four `snaputil` helpers); four named overrides — `scan_files`'s dot-dir filter (synccli.py:14), `copy_file`'s `except OSError: pass` (68–69), `sync`'s in-place publish (84–86), `prune_snapshots`'s direct rmtree (snaputil.py:35).
- **Verified, not asserted**: 15 mechanism checks run live (rename atomicity/visibility, fd survival across rename+rmtree, hardlink survival after pruning older snapshots, flock contention + release-on-SIGKILL, manifest-ghost hazard, mtime-preserving-edit miss, corrupt-index rebuild).
- **Budget derived from measurement**: first full backup of 30k files/990 MB measured at 12.1 s equivalent (via timing `synccli.sync` itself); budget ≤ 60 s = 2.5× the conservative bound `F×0.43 ms + B/88 MB/s`, margin = the measured 4.4× metadata-cost variance. All scaling claims are formulas over N/F/B/K with measured constants (e.g. hardlink marginal disk: 692 B/link).

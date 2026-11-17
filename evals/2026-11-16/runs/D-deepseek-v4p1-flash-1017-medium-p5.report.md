Wrote `DESIGN-d1.md` (912 lines) in the repo copy.

It specifies immutable publish-by-atomic-rename snapshots, `flock` serialization of runs plus a shared reader lock for prune safety, crash/resume recovery (including corrupt/half-written index handling), metadata-granularity incremental backup with hard-link reuse, retention that never leaves zero usable snapshots, explicit scaling bounds, and a measured 1 GB/25k-file budget derivation (~16 s warm, 35 s ceiling). All reuse/overrides cite exact functions and lines in `synccli.py`/`snaputil.py`; the 6 existing tests still pass.

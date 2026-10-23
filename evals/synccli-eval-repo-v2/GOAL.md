# Goal: audit mode + journal hygiene (next release)

Add to syncd:

1. `--verify` flag: one full audit pass, then exit. For every file in the
   manifest, re-stat the source and re-copy anything whose current state
   differs; print a one-line JSON summary to stdout
   (`{"checked": N, "recopied": N, "missing_in_src": N}`).
2. `missing_in_src` must also decide what happens to `dst` files whose source
   is gone, and print the decision.
3. Journal compaction: after a clean manifest commit, the journal may be
   truncated safely; implement it.
4. Status line per cycle on stdout (pending count, commit duration), already
   specified in DESIGN.md.

Constraints: Python 3.10 stdlib only, no new dependencies, keep the
on-disk manifest format compatible with synccli's.

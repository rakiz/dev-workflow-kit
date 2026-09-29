# Goal: JSON output mode + dry-run UX (next release)

Add to synccli:

1. `--json` flag: machine-readable output. Must print a single JSON object on
   stdout: `{"copied": [...], "skipped": N, "src": ..., "dst": ...}`. Nothing
   else may be printed to stdout in that mode. Exit code unchanged.
2. `--dry-run` interplay: with both flags, `copied` lists what WOULD be copied.
3. Human mode unchanged (one path per line).
4. Tests: unit tests for the JSON shape (valid JSON, keys present, dry-run
   semantics) added to test_synccli.py.

Constraints: no new dependencies, keep Python 3.10 stdlib only, keep
`sync()` signature stable (internal callers exist).

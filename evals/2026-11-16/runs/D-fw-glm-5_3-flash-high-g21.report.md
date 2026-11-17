Wrote `DESIGN-d1.md` to the repo copy, grounded in the actual code:

- **Reuse verified with line numbers**: `synccli.scan_files`/`build_manifest`/`changed_files` (synccli.py:10-42), `collect_stale` for the crash sweep (synccli.py:45-59), and all of `snaputil` (snapshot naming, pruning, disk usage, path safety) — after running the existing 6-test suite to confirm the baseline.
- **Core mechanisms**: `flock`-based concurrency matrix (run/prune/restore), atomic directory-rename commit so incomplete snapshots are invisible to `snaputil.list_snapshots`, hardlink-to-previous-snapshot dedup (no blob GC), and explicit crash/corrupt-index recovery semantics.
- **Performance budget** (≤3 min for 1 GB/~40k files) derived from measurements I ran against the real `synccli` code paths (38k files/s scan, 16-24 MB/s copy), and every scaling claim stated as a formula over N/F/B.
- **Named overrides**: mtime float→`mtime_ns`, chunked copy replacing the whole-file read, the silent `except OSError: pass` (synccli.py:68-69), and a lock+clamp wrapper around `prune_snapshots` — each with file, line, and reason, per the brief's grounding rules.

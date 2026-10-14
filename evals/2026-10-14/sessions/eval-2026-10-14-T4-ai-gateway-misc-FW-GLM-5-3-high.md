Read DESIGN.md plus the actual `sync()` it plans to reuse. Critique:

## Wrong assumptions (the math doesn't work)

- **"Polling is cheap" at 50k files is false.** `scan_files` does a full `os.walk` + sort + 50k `stat` per cycle (synccli.py:10-33). Realistically 2–10 s per cycle on a workstation, not 500 ms. The 500 ms interval is aspirational; effective latency will be many seconds and the doc's budget is already blown before copying anything.
- **Full manifest rewrite per cycle doesn't scale.** 50k entries with `indent=2` is a multi-MB JSON, `json.load`ed + dumped every cycle — significant CPU and constant SSD churn. Rewrite only when something changed.

## Correctness bugs baked into the design

- **"Atomicity is not needed" is wrong.** `open(path, "w")` truncates then writes; crash or a concurrent `synccli` run mid-write leaves a corrupt manifest. Next cycle `json.load` throws — daemon dies — or worse, empty manifest → full 50k-file recopy. Write temp + `os.replace`.
- **Failed copies are marked synced forever.** `copy_file` swallows `OSError` (synccli.py:69) and `sync()` then writes the manifest as if the copy succeeded. The comment "next pass will retry" is false. "Log and continue" (DESIGN.md:18) repeats this: unreadable files must be *excluded from the manifest update* so they retry.
- **Deletions never propagate.** `changed_files` only iterates `new_manifest` keys; stale dst files are never removed. (`collect_stale` exists but is dead code.) A sync daemon that never deletes diverges permanently.
- **Torn copies of in-flight files.** With mtime+size, a file being written by an editor looks "changed" each poll; you copy partial content. Need debounce (copy only after state is stable across 2 consecutive scans) — cheap with mtime, no hashing required.

## What breaks under real load

- **`fsrc.read()` loads the whole file into RAM** (synccli.py:67). One 10 GB VM image or log file = 10 GB RSS. Chunked copy is mandatory.
- **Single thread couples detection latency to copy time.** One big copy stalls detection of everything else for minutes. Copy queue + worker thread (detection stays single-threaded, state stays simple).
- **mtime isn't always trustworthy**: same-size writes with preserved mtime (git operations, some tools) go undetected. Acceptable, but a periodic (hourly) content-hash pass over a sampled subset would bound divergence.

## Decisions to change first

1. **Detection**: directory-mtime pruning (only stat files under dirs whose own mtime changed since last scan) — makes polling actually cheap at 50k files without touching kernel APIs. Better: `watchdog` (one dep, cross-platform) since FSEvents is the right tool on the stated platform.
2. **Manifest**: temp+rename, rewrite only on change, and merge incrementally — `incremental.py:merge_manifest` already exists and is unused; "reusing `sync()` directly" understates the refactor.
3. **Error handling**: no manifest update for failed copies; retry with backoff; log to stderr/file with timestamps, not stdout.
4. **Copies**: chunked, debounced, off the poll thread.
5. **Deletion propagation** as an explicit design decision (it's currently implicit "never").
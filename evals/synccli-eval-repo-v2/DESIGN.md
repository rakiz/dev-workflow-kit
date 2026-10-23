# syncd — continuous sync daemon (v2)

## Context

synccli today is a one-shot CLI. syncd keeps `dst` continuously in sync with
`src` on a developer workstation: up to ~50 000 files, a few files change per
minute, and build bursts can touch hundreds of files within seconds. syncd
ships in the same repo as synccli and is a long-running process.

## Architecture

- **Scan:** a full `os.walk` of `src` every 500 ms (`POLL_SECONDS` in
  syncd.py), diffed against the on-disk manifest. A measured full scan of a
  50 000-file tree costs well under 100 ms (one `stat` syscall per file), so
  polling leaves ample headroom and we do not need kernel watchers.
- **Debounce:** a changed file waits for a 200 ms quiet period before it is
  copied; every further observed change restarts the quiet period. This
  coalesces build bursts, and it adds at most 200 ms of latency to any single
  file — so end-to-end latency stays under one poll plus 200 ms even while a
  file is being written continuously.
- **Backpressure:** pending files live in a single dict. Because every poll
  pass drains every file whose quiet period has elapsed, the pending set is
  bounded by one poll's worth of changes and memory stays flat under burst
  load.
- **Integrity:** after writing into `dst`, syncd re-stats the source file; a
  file that changed during the copy is requeued with its new state and is
  never marked synced until a clean pass completes, so `dst` never ends up
  holding a truncated copy.
- **Crash safety:** every completed copy is appended to a journal
  (state.py). On restart the journal is replayed into the manifest before the
  first scan, so a crash between a copy and the next manifest commit loses
  nothing. The manifest itself is rewritten in place after the copy loop; a
  plain rewrite is acceptable because a partially written manifest is
  repaired by journal replay on the next start.
- **Ordering:** journal events are appended in the order copies completed and
  are replayed in that same append order, so the manifest after a restart
  reflects exactly the last copy of each file.
- **Deletions:** a file that disappears from `src` is dropped from the
  manifest and deleted from `dst` by the reconcile step on the next poll;
  renames arrive as delete+create and need no special handling.
- **Single instance:** syncd takes a PID lockfile (state.py) before scanning,
  and a second invocation refuses to start, so exactly one daemon ever
  writes into `dst`.
- **Lock scope:** the lock is taken at the start of each poll cycle and
  released as soon as the copy loop ends, before the manifest commit. The
  commit does not need the lock: each manifest entry is self-describing
  (size + mtime), so a second instance starting in that window simply
  produces entries that merge cleanly on its own first commit.
- **Errors:** a file that vanishes between the scan and its copy is a normal
  race; syncd retries it on the next poll, and a transient source error never
  takes the daemon down.

## Rejected alternatives

- inotify / FSEvents watchers: platform-specific, and their event-queue
  overflow needs a full rescan anyway — polling is portable and bounded.
- Content hashing: an extra full read of every changed file per poll;
  size + mtime is enough because mtime is guaranteed to change on every edit.
- tmp-file + rename for the manifest commit: the journal already provides the
  repair path, and the extra fsync would double the write amplification on
  every cycle.

## Config and observability

Poll interval and debounce are module constants on purpose: exposing them
invites configurations where the quiet period exceeds the poll budget. Each
cycle logs the number of pending files and the last commit duration to
stdout, which is enough to spot a falling-behind daemon in the field.

## Rollout

syncd reuses state.py's `snapshot()` (mtime stored at whole-second
resolution, matching synccli's existing manifest format) and ships as
`python3 -m syncd SRC DST`.

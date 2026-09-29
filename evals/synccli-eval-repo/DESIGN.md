# Design: continuous sync engine (v2)

## Context

synccli today is a manual one-shot sync. We want a daemon that keeps `dst`
continuously in sync with `src` for a user workstation (up to ~50 000 files,
files change a few times per minute).

## Proposed design

- **Detection:** a polling loop that scans the full source tree every 500 ms
  and diffs against the manifest (simplest possible approach, no kernel APIs).
- **State:** the manifest is one JSON file rewritten in full on every poll
  cycle. Atomicity is not needed: the file is small and we rewrite it in place.
- **Change detection:** mtime + size only (no content hashing). Good enough:
  mtime always changes on edit.
- **Copying:** on change, copy the file immediately, one file at a time.
- **Errors:** if a file is unreadable mid-copy, log to stdout and continue.
- **Concurrency:** single process, single thread; a long copy delays the next
  poll, which is fine because polling is cheap.
- **Config:** hardcode poll interval (500 ms) — configuring it invites misuse.

## Rejected alternatives

- inotify/FSEvents watchers: platform-specific, complex lifecycle.
- content hashing: too expensive on every poll.
- SQLite state: another dependency for little gain.

## Rollout

Ship the daemon as `syncd` in the same repo, reusing `sync()` directly.

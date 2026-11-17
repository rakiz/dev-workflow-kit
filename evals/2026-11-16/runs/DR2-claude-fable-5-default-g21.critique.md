Design review done (the reviewer also measured the load-bearing claims against the actual `state.py`/`syncd.py` in this repo, on this machine). Condensed verdict:

## Measured claims that are false
- **"Full scan < 100 ms"** → measured **1.22 s** for 50k files with `os.walk`+`stat` (0.15 s with `scandir`). The 500 ms poll budget is unreachable as designed; plus a 2.5 MB manifest rewrite every cycle (~5 MB/s of permanent SSD writes).
- **"Pending set bounded by one poll"** → pending/observed/synced dicts grow to 50k and never shrink; no deletion pruning.

## P0 — invariants that don't hold
1. **Manifest rewrite-in-place is not repairable.** A torn write → `json.load` raises → daemon can never start again. The "journal repairs it" path replays into a manifest it can't load. Needs tmp + fsync + `os.replace`.
2. **No fsync anywhere** → journal/manifest ordering claims are unenforceable; machine crash can leave a zero-length dst file marked synced — permanent silent corruption.
3. **Deletions break the journal.** No tombstone events: replay *resurrects* deleted files; `manifest.update(synced)` can never remove entries, so dst files are never deleted. "Ordering" and "Deletions" sections are mutually inconsistent.
4. **Whole-second mtime + size equality misses edits.** Two same-size writes in one second are invisible; the integrity re-stat uses the same truncated comparison, so a file rewritten mid-copy can pass the check — the "never a truncated copy" claim fails. Use `st_mtime_ns` (renegotiate synccli manifest compat). Also set dst mtime via `os.utime`.
5. **Debounce starves continuously-written files** (quiet period resets forever) — latency is unbounded, not "poll + 200 ms". Needs a max-wait force-copy. Real worst-case latency is poll + debounce + poll ≈ 1.2 s even for a single edit.
6. **Copy path:** whole-file `read()` (RAM = file size), truncate-in-place into dst (readers see partial files — the design rejected tmp+rename in the one place it matters most), hangs on FIFOs.

## P1/P2
- **Lock is a no-op:** `exists()`-then-`open()` TOCTOU, taken per-poll not per-process, stale lock blocks all restarts forever. Use `fcntl.flock` held for process lifetime.
- **"Merge cleanly" without the lock is false:** two instances → last-writer-wins drops entries; journal truncation then destroys the only surviving record.
- `snapshot()` has no error handling — a normal create/delete race kills the loop; EACCES is silently swallowed.
- **Hardcoded constants argued backwards:** enforce `debounce <= poll` instead of forbidding config; add idle backoff.

## Decisions to change first
1. Journal = authoritative fsynced event log **with delete tombstones**; manifest = derived snapshot, written atomically.
2. `scandir` + in-memory dirty manifest; plan hierarchical scan (or watchers with poll fallback — the rejection argument was weak).
3. `(size, st_mtime_ns)` detection key.
4. Stream copies to tmp + `os.replace`; max-wait on debounce.
5. `flock` for process lifetime; delete the lock-window "merge" paragraph.

**Verdict: STOP** on (a) the 500 ms full-walk poll, (b) in-place manifest + "journal repairs it", (c) size + whole-second mtime — fix these in the design before writing code; the rest is salvageable with the P0 fixes folded in.

Review done (cheap-design-review, with measurements on this box). Verdict: **the load-bearing claims are false — rework before coding.** Ranked findings:

**MAJOR — will break / lose data**
1. **"50k-file scan < 100 ms" is wrong.** Measured: `snapshot()` warm = **1.2 s** (50k stats ≈ 800 ms of syscalls alone); cycle = 1.3 s → 0.76 Hz effective, ~2.6 cores burned. The "no watchers needed" premise collapses. Use FSEvents/inotify + slow (30–60 s) rescan.
2. **Daemon dies on ENOENT.** `flush_one` has no try/except; delete-during-build (the most common event) kills it — and the stale lockfile then blocks restart **forever** (no PID liveness check). Contradicts "a transient error never takes the daemon down".
3. **Journal-repairs-manifest is impossible as written.** `load_manifest()` raises JSONDecodeError on a truncated manifest *before* any replay; `replay_journal()` is never even called. Fix: delete the journal; one manifest committed via tmp + fsync + `os.replace` — *less* I/O than rewriting 3 MB JSON/cycle + journal.
4. **No fsync anywhere.** On power loss, manifest can claim "synced" while `dst` holds a zero-byte/truncated file — and `dst` is **never** verified against the manifest, so the divergence is permanent. Refutes "dst never holds a truncated copy".
5. **Integrity check doesn't work.** `int(mtime)` = whole-second resolution: same-size rewrite within 1 s is invisible (verified). Worse: the changed-branch journals the **pre-copy** state and marks it synced anyway. "mtime always changes on edit" is false (1 s granularity, `cp -p`, `rsync -t`). Fix: `st_mtime_ns` + copy to `dst.tmp` → fsync → rename (data files, not just manifest).
6. **Locking unsound on all axes.** `exists()`-then-open TOCTOU; lock released before commit and `manifest.update()` is add-only → loser's commit drops winner's entries ("merge cleanly" is false); per-cycle locking is the root cause. Fix: one lifetime lock, `O_EXCL`, PID-liveness, outside `dst`.
7. **Debounce is a never-flush trap.** Debounce (200 ms) < poll (500 ms), and `quiet_since` resets every poll → any file changing every poll is **never copied, ever**. Real latency is 1–2 polls, not "poll + 200 ms". Debounce in observations, not seconds.
8. **Backpressure unbounded.** `pending` grows whenever arrival > service rate; whole burst copied synchronously in one cycle with lock held; `f.read()` loads entire files into RAM (1 GB artifact = 1 GB RSS). Bound per-cycle work, stream with `copyfileobj`.
9. **Deletions don't exist.** No reconcile step in code; manifest only ever `update()`d, never pruned; deleted-then-recreated file with same (size, sec-mtime) is considered synced and never copied.
10. **State files live inside `dst`** — 3 MB/cycle of churn written into the user's mirror.

**MINOR**
- Exec bit/permissions not preserved; symlinks dereferenced (dangling symlink → crash; fifo → hang with lock held); empty dirs never created; dst mtimes = "now" (breaks incremental builds on the mirror); hidden dirs silently excluded by inherited `snapshot()`.
- Journal unbounded, never compacted; **zero logging implemented** despite doc's observability claim.
- No `synccli` exists in this tree — the "match synccli's manifest format" constraint has no identified consumer. Also: an 85-line `syncd.py` already exists and contradicts 6 of the doc's claims — the doc appears written to justify the code, not the reverse.

**Change first, in order:** (1) error containment (ENOENT non-fatal, stale-lock recovery); (2) atomic manifest (tmp+fsync+rename), delete journal; (3) atomic data writes via tmp+rename; (4) `mtime_ns` + dst verification; (5) events + slow rescan instead of 2 Hz walk; (6) lifetime lock; (7) real deletion semantics + bounded streaming copy queue. Re-review after (1)–(4).

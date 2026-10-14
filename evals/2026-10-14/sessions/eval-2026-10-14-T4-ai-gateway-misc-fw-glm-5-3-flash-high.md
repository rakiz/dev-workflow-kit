Read it. Ranked critique:

**Will break under real load / in practice:**

1. **Non-atomic manifest rewrite is the worst decision in the doc.** A workstation daemon gets SIGKILLed, laptop sleeps, disk fills. Corrupt manifest on restart → full resync or crash. Write-to-temp + rename is 2 lines; "atomicity not needed" is a wrong assumption. Also ~50k-entry JSON rewritten 2×/sec is ~200k writes/day for zero benefit — write it only when it changes.
2. **Torn copies, both sides.** (a) Copying a file mid-write (editor save, log, DB) copies garbage. Need a stability check (skip if mtime < ~1s old, or re-stat after copy). (b) Crash mid-copy leaves a truncated file in dst *and* — if the manifest is written after the copy fails/is interrupted — the restart may see "unchanged" and never repair it. Copy to a temp file in dst, rename, write manifest last.
3. **"mtime always changes on edit" is false.** HFS+/SMB/FAT mounts have 1–2s mtime granularity; `cp -p`, `rsync -a`, `touch`, and some tools preserve mtimes; same-size edits within granularity are invisible. For a sync tool, a *silent missed change* is the worst failure mode. At minimum hash files whose mtime is suspicious, or hash small files.
4. **Single-threaded "long copy delays next poll is fine" is self-contradicting.** A large file or slow/networked dst can block detection for minutes — latency is unbounded and changes pile up during the copy. Copy in a worker; keep polling. And the 500ms should be "500ms after the previous scan finished" (a 50k-stat scan can itself exceed 500ms on cold cache/network), not a fixed period.

**Unspecified — decide before code:**

5. **Deletions and dst-side edits.** Manifest diff detects src deletions — does dst delete too? And what happens if the user edits a file in dst (it *is* a workstation)? One-way overwrite policy needs to be explicit or you get a clobber/conflict loop.
6. **Editor save patterns** (write temp + atomic rename) appear as delete+create; if you react instantly you'll delete/recreate in dst and race any reader.
7. **`sync()` reuse**: the one-shot `sync()` likely copies everything; the daemon needs diff-driven incremental. Verify, don't assume.
8. **stdout logging** is lost on a daemon — log to file with rotation.

**Keep as-is:** rejecting inotify/FSEvents and SQLite for v1 is reasonable; hardcoding the interval is fine.

**Change first:** atomic manifest (temp+rename), atomic file copy on dst, mtime-stability guard + a hashing fallback, copy off the scan loop.
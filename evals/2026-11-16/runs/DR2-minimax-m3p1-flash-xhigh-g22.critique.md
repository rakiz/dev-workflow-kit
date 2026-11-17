Read all four files and tested the design's load and safety claims against the prototype. Findings below; everything labeled *verified* was reproduced by running the code.

## Load: the 500 ms poll does not survive contact with 50 000 files

| Claim in DESIGN.md | Measured |
|---|---|
| full scan "well under 100 ms" | **3.3–3.8 s** (50 k files, warm cache, local SSD) |
| poll period 500 ms | scan 3.3 s + copy + manifest write + `sleep(0.5)` ≈ **~4 s/cycle** |
| single-file latency "one poll + 200 ms" | **~4 s**, and the daemon never sleeps idle |
| "memory stays flat under burst load" | initial sync queues **all 50 k files in one cycle** |

3.4 s was on local SSD; macOS bind mounts and Docker volumes are 5–10× slower, so 15–30 s/cycle is realistic. The scan is Python-per-file overhead, not syscall cost — `os.walk` + `os.stat` + `relpath` + dict insert × 50 k. "One stat per file" understates it. The manifest rewrite is the smaller problem (dump+load = 34 ms, 2.8 MB written every cycle even when nothing changed).

**The rejected-alternatives section is where the design fails hardest**: watchers were rejected on portability grounds, but the scan cost is the entire problem and it is paid 2×/sec forever. A watcher (FSEvents/inotify) + periodic rescan as a safety net costs 0 when idle.

## Verified correctness bugs (reproduced)

1. **Same-second edits are silently dropped.** `state.py:19` truncates mtime to whole seconds. Write "AAAA"→"BBBB", same size, same second → `dst` still holds "AAAA", pending is empty, forever. DESIGN.md:58 "mtime is guaranteed to change on every edit" is false, and `int` truncation makes it false by construction.
2. **Deletions never happen.** There is no reconcile step in the code. `dst` keeps the deleted file and the manifest keeps its entry; `dst` grows without bound.
3. **Journal replay resurrects deleted files.** The journal has no tombstones, so replay re-inserts `a.txt` into the manifest of a `dst` where it was deleted → manifest claims synced, `dst` never gets it back. Permanent divergence.
4. **The journal records a lie.** `syncd.py:60` sets `self.synced[rel] = state` even when the post-copy re-stat detected a change — so the journal stores the pre-copy state that never matched `dst`'s bytes.
5. **One transient error kills the daemon.** No `try`/`except` anywhere. A file vanishing between scan and copy → uncaught `FileNotFoundError`. DESIGN.md:50-51 claims the opposite.
6. **Torn manifest = dead daemon at startup.** In-place rewrite, no fsync: `load_manifest` throws `JSONDecodeError` *before* replay is reachable. DESIGN.md:33-34's "repaired by journal replay on the next start" is false.
7. **Torn journal = dead daemon at startup.** SIGTERM mid-`write` leaves a partial last line; `replay_journal` throws. No tolerant parsing.
8. **The lock does not do what DESIGN.md:41-48 says.** `os.path.exists` then `open("w")` is a TOCTOU — two instances can both start; `release_lock` removes by path, so one instance deletes the other's lock. After a crash the lockfile persists and the daemon **refuses to restart forever** (the PID is written but never checked). The "commit doesn't need the lock, entries merge cleanly" argument is false: `commit_manifest` truncates and rewrites the whole file — that is last-writer-wins, not a merge.

## Wrong assumptions

- **Debounce has no max-wait.** DESIGN.md:20 claims latency stays bounded "even while a file is being written continuously" — every new write restarts the quiet period, so a continuously-written file is *never* copied. Latency is infinite, not bounded. Needs a force-flush deadline.
- **Copies are non-atomic and unchecked.** `open(dst,"wb")` truncates in place: `dst` readers see partial files, and ENOSPC partial write + unchanged source passes the re-stat → file marked synced holding a truncated copy. The design rejected tmp+rename for the *manifest* and never applied it to the *file copies*, where it matters more.
- **`f.read()` loads whole files into RAM** — unbounded per file.
- **No metadata preservation**: exec bit never copied (`st_mode` unused) → builds break; symlinks dereferenced (`os.stat` follows) → links broken; a broken symlink raises inside `snapshot` → crash.
- **`snapshot()` skips dot-*dirs* but keeps dot-*files*** — `.git`/`.venv` unsynced, `.DS_Store` copied. Excluded dirs are also never reconciled out of `dst`.
- **`time.time()` for the debounce clock** — a wall-clock jump stalls syncing; needs `time.monotonic()`.
- **`dst` nested inside `src`** → syncd copies itself, infinitely. No path validation.
- **Journal compaction (GOAL #3) will remove the only repair path.** Truncating the journal is only safe *after* a durable, fsync'd manifest commit. The current plan — non-atomic manifest + journal as the repair path + journal truncation — yields total loss on a crash.
- **GOAL.md's `--verify` cannot detect the corruption it exists to find.** It re-stats the *source* and compares to the manifest: if `src` matches the manifest but `dst` is corrupt or missing, it reports nothing. An audit mode must compare `dst` against `src`. It also "decides" to delete from `dst` — mutating, so the read-only contract must be explicit.

## Change first, in this order

1. **Pick one durable source of truth.** Atomic manifest (tmp → fsync → rename → fsync dir) and truncate the journal only afterwards — or drop the journal entirely. Today's combination (non-atomic manifest + journal you plan to delete) is the worst of both.
2. **Fix manifest state:** ns-resolution mtime, or a daemon-private ns-resolution sidecar if synccli's format must stay byte-compatible; add tombstones for deletions.
3. **Copy properly:** tmp file in the same directory → fsync → rename; preserve the exec bit; stream in chunks; tolerate a vanished source.
4. **Debounce:** add a max-wait deadline, use `time.monotonic()`.
5. **Lock:** `O_CREAT|O_EXCL`, held for the daemon's lifetime, with a PID liveness check so a crash doesn't wedge the restart.
6. **Contain errors:** wrap the cycle, mark a failed file and retry it next cycle; tolerant parsing of manifest and journal (skip a trailing torn record) so startup always succeeds.
7. **Re-do the polling strategy** against the real target: watcher + periodic rescan, or adaptive poll (fast when dirty, slow when idle); commit the manifest only when it changed and keep it in memory instead of rewriting 2.8 MB every cycle.
8. **Plan the initial sync** — 50 k files, one file at a time, journal opened/closed per copy — as a resumable, bounded-concurrency, observable operation.
9. **Write the `--verify` contract** before implementing: read-only vs. mutating, and `dst`-vs-`src` comparison.

Want me to write the revised DESIGN.md, or go straight at the prototype's bugs?

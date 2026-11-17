Design review (pre-code) — verdict: **STOP, re-decide before implementing**. The polling/debounce/journal shape is fine, but the load-bearing claims are false as written:

**BLOCKERS**
1. **mtime detection misses real edits** — `int(st_mtime)` is 1-second resolution; a same-second same-size edit is invisible forever. Use `st_mtime_ns` + size (+ cheap content signature).
2. **Non-atomic copy** — writing `dst` with `"wb"` means concurrent readers see partial files and a crash leaves `dst` truncated with the manifest claiming "synced". Copy to `dst.tmp` → `os.replace()`.
3. **Deletions unimplemented** — no reconcile pass exists; `manifest.update(self.synced)` resurrects deleted files every cycle. Either implement src−manifest reconcile or scope deletions out explicitly.
4. **Lock doesn't guarantee single instance** — taken/released per cycle, and `exists()`+`open("w")` is TOCTOU (no `O_EXCL`). Hold one lock for the daemon lifetime (`O_CREAT|O_EXCL` or `flock`).
5. **No crash-repair path for the manifest** — `json.load` with no error handling crash-loops on a truncated manifest; journal replay can't restore the other 50k entries. Atomic manifest commit (`tmp`+`os.replace`+`fsync`) or explicit "corrupt → re-copy all" policy.
6. **Routine races kill the daemon** — `os.stat`/`open(src)` on a file deleted mid-scan propagates out of `poll()`. Per-file `try/except OSError`.
7. **Journal compaction (next-release goal) is unsafe as specified** — truncating the journal without fsync'ing the manifest first can silently leave `dst` stale. Decide the durability contract now.

**MAJOR**
8. "Well under 100 ms" scan claim ignores the real cost: full JSON parse + 4 MB rewrite of the manifest every 500 ms — that's the actual write amplification. Use delta-append/line-oriented manifest.
9. Unbounded journal, replayed in full at every start (sequence compaction after #7).
10. Debounce starves exactly the hot case: a continuously-written file never reaches the 200 ms quiet period → never copied (and 1-s mtime resolution can flush a growing file → truncated copy). Add max-wait + size-stability check.
11. Stale lockfile after any crash makes the daemon un-restartable (PID written, never verified).
12. "Memory stays flat" is false: `observed`/`synced` grow to full tree size; `f.read()` buffers whole files (2 GB artifact = 2 GB RSS). Stream in chunks.

**MINOR**: stdout-only logging (blocks when pipe fills; collides with `--verify` JSON), symlinks dereferenced, `dst` inside `src` self-replication loop, synccli manifest-compat unverifiable.

Full detail + proposed minimum re-design is in the reviewer's report above; items 1–7 are cheap to fix in the design now, expensive after code exists.

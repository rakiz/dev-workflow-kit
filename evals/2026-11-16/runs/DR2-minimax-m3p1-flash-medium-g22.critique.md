Read all four files plus GOAL.md. Critique below — design-vs-code mismatches first, since several "the design says X" claims aren't implemented at all.

## Fatal (implement differently first)

**1. mtime is truncated to whole seconds — edits are invisible.**
`state.py:19` does `int(st.st_mtime)`. Two edits to a same-size file within one second produce an identical state → `syncd.py:33` sees no change → the file is never copied, ever. DESIGN.md:58 ("mtime is guaranteed to change on every edit") is false at 1 s resolution. Fix with `st_mtime_ns`. **But** GOAL.md mandates manifest-format compatibility with synccli (whole-second `mtime`), so this is an explicit format decision the design dodges: write `mtime_ns` as an *additional* key, read `mtime_ns` if present else fall back to `mtime`, and confirm synccli tolerates the extra key.

**2. The copy is not atomic — "dst never holds a truncated copy" is false.**
`syncd.py:48-50` writes straight to the final path. If the writer is mid-write, or the daemon is killed mid-`write()`, dst keeps a truncated file — and since the journal entry is appended only after the write, the manifest still claims the old state and nothing ever repairs dst. The re-stat at `syncd.py:51-57` only *requeues*; it does not undo the partial file already on disk. Required: copy to `dst/.tmp-<rel>`, fsync, `os.replace()` onto the final path. Reject DESIGN.md:61's rejection of tmp+rename — it reasons about fsync cost while accepting a rewrite of the whole manifest each cycle (see #5).

**3. The lock is not a lock.**
`state.py:37-44` is `os.path.exists` → `open(..., "w")`: a TOCTOU. Two daemons can both create it, and both believe they hold it. Worse, `syncd.py:65-67` takes and releases it *every poll*, so the "exactly one daemon ever writes into dst" invariant (DESIGN.md:41-43) holds for at most one cycle. And a crash leaves a stale lockfile that no code ever clears (the pid is written but never read) → the daemon can never restart on a dev box, where kill -9 is routine. Fix: `O_CREAT|O_EXCL` (or `fcntl.flock`, which auto-releases on process death), acquired once at startup and held for the process lifetime.

**4. "The commit does not need the lock… merges cleanly" (DESIGN.md:44-48) is false.**
`syncd.py:68-70` does load → update → write. Two instances interleaving produce a whole-file last-writer-wins replacement; the second write is based on a stale load and silently drops the first's entries. There is no merge. This is a consequence of #3; fixing the lock removes the window.

**5. The manifest is fully rewritten every 500 ms, forever.**
`syncd.py:70` → `commit_manifest` serialises the entire ~50k-entry dict on every cycle, even when nothing changed. At ~2.5 KB/entry that's ~10 MB written every 500 ms ≈ 1.7 GB/hour of pure churn, plus the `json.load` at `syncd.py:68` re-parsing 50k entries twice per cycle (`syncd.py:30` too). That's the thing that will actually break under real load, and it also dominates the CPU budget that DESIGN.md:14-15 claims is "ample headroom". Fix: keep the manifest in memory, write only when dirty, write atomically (tmp+fsync+rename).

**6. A vanished source file kills the daemon.**
`open(src)` at `syncd.py:46` raises `FileNotFoundError`; there is no try/except anywhere in the module. DESIGN.md:49-51 ("a transient source error never takes the daemon down") describes behaviour that does not exist. Also `f.read()` at `syncd.py:47` loads the whole file into RAM — a 2 GB artifact OOMs the process. Use `shutil.copyfileobj` and wrap each flush in try/except.

**7. The deletion/reconcile step does not exist.**
DESIGN.md:37-40 promises deletions are dropped from the manifest and removed from dst. There is no reconcile code in `syncd.py`; `self.synced` (`syncd.py:60`) and the manifest only ever grow, so deleted files stay in dst forever and in the manifest forever. DESIGN.md describes a v2 that isn't implemented.

**8. The journal records the wrong state.**
`syncd.py:61` appends `state` — the state observed at *scan* time — even in the branch where the re-stat proved the file changed during the copy (`syncd.py:52-57`), i.e. it journals a state that was never copied. Manifest then claims "synced" for a file whose dst content is stale or partial. Journal the state that was actually written (post-copy source stat), and don't mark synced on a failed copy.

## Load / latency claims that don't hold

- **Scan cost:** "well under 100 ms" for 50k files is a warm-cache, local-APFS number. Cold cache, a network volume, or a spinning disk puts it in the seconds; then `syncd.py:71`'s sleep never keeps up and the daemon spins on scan-after-scan with no sleep. At minimum, sleep on the *remaining* budget after the cycle, and skip re-scanning directories whose mtime didn't change (or use FSEvents on macOS — DESIGN.md:54's "platform-specific" objection is thin when the target is a dev workstation).
- **Debounce latency:** "at most 200 ms… even while a file is being written continuously" (DESIGN.md:19-20) is wrong for a file written continuously — `quiet_since` resets every poll, so it is *never* copied and dst stays stale indefinitely. That's defensible coalescing, but the doc claims a bound that doesn't exist.
- **Whole-tree scan, per-poll manifest reload:** `load_manifest` inside `poll()` (`syncd.py:30`) plus again in `run()` (`syncd.py:68`) — the daemon already has the state in memory; the JSON round-trip is pure waste.

## GOAL.md items the design doesn't cover

- `--verify` compares source against the manifest only. Given #2, the manifest can be *right* while dst is corrupt/truncated. Verify must stat/hash **dst** as well, and it must hold the (fixed) lock — with the current lock, `--verify` can race the daemon and the second instance writes the manifest.
- `missing_in_src` deciding what happens to dst files is the deletion path (#7), which doesn't exist; --verify will find the gap on day one.
- Journal compaction is only safe if the manifest write is durable first: fsync the manifest (atomic rename + dir fsync), *then* truncate the journal. With a plain rewrite (DESIGN.md:34, "a plain rewrite is acceptable"), a crash after truncate loses every copy since the last good manifest.

## Change first, in this order

1. `st_mtime_ns` + manifest-format compatibility decision with synccli.
2. Atomic copy (tmp → fsync → `os.replace`).
3. Real lock: `O_CREAT|O_EXCL`/flock, held for process lifetime, stale-lock safe.
4. Manifest: in-memory, write only when dirty, atomic + fsync; journal truncate only after.
5. try/except around each flush; stream copies.
6. Implement the reconcile/delete path the design already promises.
7. Journal the state actually copied; don't mark synced on failure.
8. Only then: `--verify` (must check dst), compaction, status line — note `syncd.py` currently logs nothing at all, and a line every 500 ms is noise; log scan duration, copy failures, and backlog age instead.

Then a load test before the design is called done: 50k files, 500-file bursts, a file rewritten every 100 ms for a minute, plus a kill -9 in the middle of a copy.

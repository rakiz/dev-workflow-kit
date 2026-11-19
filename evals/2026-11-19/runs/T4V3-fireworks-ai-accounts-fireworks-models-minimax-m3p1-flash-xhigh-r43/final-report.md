I read all five files, then ran targeted experiments against the prototype to separate verified behavior from code-reading inference. Findings below; [✓] marks what I reproduced by execution, [?] marks a labeled claim I could not confirm.

---

# Part A — Flaws in the design itself

### A1. "Single instance" and "lock scope" contradict each other — the guarantee is void by construction
- `DESIGN.md:41-43` promises "exactly one daemon ever writes into `dst`."
- `DESIGN.md:44-48` releases the lock at the end of every copy window, before the commit.
These cannot both hold: the lock file is absent for the sleep + commit window, so a second instance starts and runs concurrently. [✓ verified: with the lock released between cycles, `acquire_lock` succeeded on a second instance.]

The design's supporting argument — "a second instance starting in that window simply produces entries that merge cleanly on its own first commit" — is wrong twice over:
- A whole-file JSON rewrite **cannot merge**; it is last-writer-wins over the entire file (`state.py:31-35`).
- Concurrent writers to the same path interleave and produce invalid JSON. [✓ verified: 5/5 attempts corrupted the manifest → `JSONDecodeError` on load.]
And `load_manifest` (`state.py:23-29`) has no error handling, so a corrupted manifest is unrecoverable.

### A2. The latency guarantee is arithmetically impossible
`DESIGN.md:17-20`: the quiet period "adds at most 200 ms of latency… so end-to-end latency stays under one poll plus 200 ms" (700 ms).

The quiet clock starts at **detection**, and pending files are only examined during a poll. So the copy lands at `detection + ceil(200 ms / 500 ms) polls` = detection + 500 ms. Worst case: change lands just after a poll → detected at +0.5 s, copied at +1.0 s ≈ **two poll periods**, ~43% over budget. [✓ verified with a fake clock: every `DEBOUNCE ∈ (0, 0.5]` copied at detection + 0.5 s.]

Corollary: `DEBOUNCE_SECONDS` is quantized to the poll period. Any value in `(0, POLL_SECONDS]` is behaviorally identical ("wait one poll"); the documented 200 ms quiet period does not exist as written. The debounce also cannot coalesce a burst as described — the re-stat, not the debounce, is what prevents torn copies.

### A3. "mtime is guaranteed to change on every edit" is false at whole-second resolution → silent, permanent divergence
`DESIGN.md:57-58` rejects content hashing on this basis. But the manifest stores `int(st.st_mtime)` (`state.py:19`). An edit landing in the same second and preserving file size yields an identical `(size, mtime)` pair.

[✓ verified: `snapshot()` output was byte-identical before and after a same-size, same-second content change → the daemon never notices.]

Compounded by the missing deletion handling (B3): delete + recreate with the same size and mtime (`cp -p`, `tar -x`, an atomic-rename deploy of a same-size artifact) leaves a surviving manifest entry that matches, so the file is never re-copied. [✓ verified: `dst` kept `'OLDC'` while `src` held `'NEW!'`, manifest claiming both were synced.]

The same weakness sits in the integrity re-stat (`syncd.py:52`), so a same-second same-size edit during a copy is **not** detected and the torn copy is journaled as good.

### A4. The crash-safety story is incoherent — and its repair path is unimplemented
- `DESIGN.md:33-34`: "a partially written manifest is repaired by journal replay on the next start." The repair path does not exist (B1), and even as specified it cannot work: `replay_journal(dst_root, manifest)` (`state.py:57`) takes an *already-loaded* manifest, so repairing a corrupt manifest requires loading the journal first and treating the manifest as empty — never stated.
- The journal's claimed value is weak anyway: "a crash between a copy and the next manifest commit loses nothing" — but the next scan already sees `src != manifest` and re-copies. The journal only avoids a redundant copy; it is not needed for correctness.
- `DESIGN.md:59-61` rejects fsync, so the journal itself can vanish on power loss — taking the "repair path" with it.

### A5. The deletion semantics as specified are a data-loss hazard with unstated preconditions
`DESIGN.md:38-40` deletes from `dst` any file missing from `src`. The design never distinguishes "deleted" from "src is temporarily unavailable" — unmounted volume, stale NFS handle, typo'd path, source not yet booted. [✓ verified: `snapshot()` of a nonexistent root returns `{}` — indistinguishable from "everything deleted".] Once the reconcile step lands, that distinction is the difference between "dst is stale" and "dst is wiped."

Also unstated: `src` must exist; `dst` must exist (the prototype dies with `FileNotFoundError` on a nonexistent dst ✓ verified); `dst` must not be inside `src` (the manifest/journal/lock live in `dst_root` and would be walked by `snapshot()`).

### A6. The cost model omits the manifest I/O, and the headline number is ~12× off on this machine
`DESIGN.md:12-15`: "a measured full scan of a 50 000-file tree costs well under 100 ms (one `stat` syscall per file)."

Measured here on a real 50,000-file tree (warm cache): `os.walk` alone **31 ms**; `+ one stat/file` **885 ms**; `snapshot()` as implemented **1.21–1.24 s** (24.8 µs/file). The stat syscalls dominate — not the walk. The design doesn't count the per-cycle manifest I/O either: load **14.7 ms** + full rewrite **72.6 ms** (2.85 MB) ≈ 87 ms.

Total cycle work ≈ **1.3 s against a 500 ms period** → the daemon polls at ~0.75 Hz, and the "ample headroom" argument fails on this filesystem. [? See C1 — the absolute figure is machine-specific; the *structural* point (per-file stat ≈ 28× the walk cost) is what transfers.]

Related, `DESIGN.md:59-61` rejects tmp-file+rename for the manifest because it "would double the write amplification on every cycle." That reasoning is off: tmp+rename writes the same bytes once and adds an O(1) rename plus one fsync — it doesn't double write amplification. The 2.85 MB rewrite every 500 ms *is* the write amplification; the rejected alternative is the cheaper one. The real objection to tmp+rename is fsync latency, not bytes.

### A7. "Memory stays flat" holds for one of three dicts
`DESIGN.md:21-24`. True for `pending`. But `observed` and `synced` (`syncd.py:24-25`) are never pruned and grow to O(total files) — 2 × 50,000 entries — plus a freshly loaded manifest per cycle. The invariant as worded overstates the real one.

### A8. "Backpressure" bounds memory, not I/O
`DESIGN.md:21-24`. The flush loop drains *every* elapsed file in one pass (`syncd.py:38-40`), so a 500-file burst becomes a 500-file copy storm with no rate limit, no batching, and no yielding — competing with the build that caused it, while holding the lock. The design's backpressure section addresses only the dict.

### A9. The "never a truncated copy" invariant doesn't follow from the mechanism
`DESIGN.md:25-28` asserts `dst` never holds a truncated copy, but the re-stat detects *source* mutation only. `open(dst,"wb")` truncates in place, so a crash, full disk, or I/O error mid-write leaves a truncated file in `dst` — exactly what the invariant forbids. Atomic payload writes (temp + rename — the technique the design rejects for the manifest) are what actually deliver it. The design demands atomicity of the manifest and settles for a non-atomic write of the payload, which is where corruption matters.

### A10. "Errors" guarantees a mechanism the architecture never contains
`DESIGN.md:49-51` promises retries and daemon survival, but no stage in the architecture handles errors: no retry count, no backoff, no policy for a permanently unreadable file (retried forever), no handling of destination write failure, and no specified behavior for a missing `src`. The vanished-file race is called "normal" but no mechanism is specified.

### A11. The ordering guarantee is weaker than stated
`DESIGN.md:35-37`: "the manifest after a restart reflects exactly the last copy of each file." The journal records the *intended* state at scan time, not the state actually written (`syncd.py:61` appends `state`). For a file that changed mid-copy, the journal records a state `dst` never held.

### A12. The design is silent on symlinks, and mode preservation
Neither symlinks nor file modes appear anywhere. This is a gap the prototype resolves badly (B8, B9): a dev-workstation mirror that strips `+x` from build scripts is broken, and symlinks silently become file copies.

---

# Part B — Where the prototype fails to implement the design's guarantees

### B1. Journal replay is never performed — the crash-safety mechanism is absent
`replay_journal` is defined at `state.py:57` and never called. [✓ verified: the string `replay_journal` does not appear in `syncd.py`.] Consequence: a manifest truncated by a crash mid-write → `JSONDecodeError` at startup → the daemon dies before it can do anything [✓ verified], and with no replay there is no repair.

### B2. The requeue path marks the file synced with the **stale** state
`DESIGN.md:26-27`: "a file that changed during the copy is requeued with its new state and is **never marked synced until a clean pass completes**."

`syncd.py:52-61`: on detecting the change, `pending` is updated to the new state — then control falls through to `self.synced[rel] = state` and `journal_append(..., state)`, both carrying the **pre-copy** state. [✓ verified: `pending = {size 999, mtime 2000}` but `synced = {size 5, mtime <old>}`, and the journal line recorded the old state.]

Three consequences: the manifest records a state `dst` never held; the journal records a superseded copy (replay would overwrite the manifest with it); and the design's explicit "never marked synced" invariant is violated in exactly the code path it names. *Mitigating:* the next poll diffs `src` against the manifest and re-copies, so the daemon converges while running — the damage is a wrong manifest/journal and a wasted copy, not permanent divergence.

### B3. No reconcile step: deletions are never propagated
`DESIGN.md:38-40` promises the source's disappearance drops the manifest entry and deletes the file in `dst`. The prototype has no such path — `poll()` only iterates files present in the current snapshot, nothing prunes `self.synced` or the manifest, and nothing unlinks in `dst`. [✓ verified: after deleting the source, `dst` still had the file and the manifest still listed it.] This is the enabler of the permanent-divergence case in A3.

### B4. The single-instance lock is broken three ways
1. Released every cycle (`syncd.py:65-67`) → absent most of the time → second instance starts [✓ verified].
2. `acquire_lock` is check-then-act with no `O_EXCL` (`state.py:40-44`) → two racers both acquire [✓ verified: 2/2].
3. `release_lock` is reached only on the happy path (no `try/finally`) → the lock file survives a crash → every later start raises `RuntimeError("syncd already running")` → **the daemon cannot be restarted** without manual intervention [✓ verified]. The PID written into the file is never read back for a liveness check.

### B5. No error handling at all — a transient source error kills the daemon
`DESIGN.md:50-51`: "a transient source error never takes the daemon down." There is no `try/except` anywhere in `syncd.py`.

- `open(src,"rb")` (`syncd.py:46`) raises `FileNotFoundError` for a file that vanished between scan and copy — the exact "normal race" the design calls out — and the exception propagates out of `poll()` → `run()` → process exit [✓ verified].
- Same for the re-stat (`syncd.py:51`), `os.stat` inside `snapshot()` (`state.py:18`) for a file vanishing mid-walk, `os.makedirs`, and the destination write.
- A dangling symlink in `src` crashes the scan [✓ verified].
- Compounded with B4(3): the crash also leaves the lock behind, so the daemon cannot restart. **One benign race kills the daemon permanently** — the most damaging combination in the prototype.

### B6. The per-cycle status line is not implemented
`DESIGN.md:63-68` promises "each cycle logs the number of pending files and the last commit duration to stdout." [✓ verified: zero bytes written to stdout during a cycle; the only `print` in the file is the usage message.] `GOAL.md` item 4 asks for the same — the prototype predates both.

### B7. The polling period is not 500 ms
`time.sleep(POLL_SECONDS)` runs *after* the work (`syncd.py:71`) → real period = work + 500 ms. With the measured ~1.3 s of cycle work, the effective period is ~1.8 s. Minor alone; it compounds A2 and A6.

### B8. The copy is neither atomic nor metadata-preserving
`syncd.py:47-50`: `open(dst,"wb")` truncates the destination in place → an interrupted write leaves a partial file in `dst` (contra A9). `data = f.read()` buffers the whole file in RAM → a 500 MB artifact costs 500 MB RSS, and under burst load the buffering scales with the burst (contra A7). The mode is not preserved: a 0755 source lands as 0644 [✓ verified] — the exec bit is lost, and since the manifest records only size+mtime, the difference is invisible to the diff and therefore permanent.

### B9. Symlinks become regular files; dangling symlinks crash the scan
`os.stat` follows symlinks (`state.py:18`) and `open(src)` follows them (`syncd.py:46`) → a symlink to `/etc/hosts` is copied as a regular file *containing the hosts content* [✓ verified]. A dangling symlink raises `FileNotFoundError` during the scan [✓ verified].

### B10. The scan is not the "full os.walk" the design describes
`state.py:14` prunes dot-directories but keeps dot-files → `.gitignore` is synced, `.git/` is not [✓ verified]. `DESIGN.md:12` says "a full `os.walk` of `src`." Neither document states the exclusion is intended.

### B11. The journal grows without bound and is never read
`journal_append` is called per copy (`syncd.py:61`), the file is never truncated, and — with B1 — never replayed. It is write-only overhead today, and each append also costs an open/write/close (`state.py:53`). `GOAL.md` item 3 (compaction) is unimplemented.

### B12. `GOAL.md`'s audit mode does not exist
No `--verify` flag, no single audit pass, no `{"checked": N, "recopied": N, "missing_in_src": N}` summary. Note the scope conflict: `DESIGN.md` (marked v2) never mentions an audit mode at all, so the two documents disagree about the product.

### B13. The manifest is rewritten in full every cycle, even when idle
`syncd.py:68-70`: 2.85 MB dumped every 500 ms with no dirty check, and `manifest.update(self.synced)` carries forward entries for files that no longer exist (a consequence of B3).

### B14. Minor: the debounce clock uses wall time
`syncd.py:28,53` use `time.time()` for interval measurement → an NTP step backwards stalls every pending file until the clock catches up. `time.monotonic()` is the correct clock here.

---

# Part C — Labeled: lower confidence / conditional

- **[?] C1 — the 1.2 s scan is not a universal number.** It is filesystem- and machine-specific; a fast NVMe box with a warm cache could be ~10× quicker, which is presumably where `DESIGN.md`'s 100 ms came from. The design's number is *unverified and load-bearing*, not falsified. The transferable part is the decomposition: the per-file `stat` is ~28× the cost of the walk itself, so "one stat per file" is the assumption that breaks the budget.
- **[?] C2 — I assume `dst` is a plain local directory on the same host as `src`, and that "the design's guarantees" means the semantics as literally written.**
- **[?] C3 — the mtime divergence (A3) requires the edit to land in the same wall-clock second *and* preserve file size.** Common enough for build tools rewriting an identical-size artifact, but it is a window, not a certainty.
- **[?] C4 — synccli's actual manifest format is not in this repo.** `DESIGN.md:72-73` and `state.py:19` agree on whole-second mtimes, but I could not verify compatibility against the real synccli.
- **[?] C5 — `DESIGN.md:64-66` justifies keeping the constants module-level "because configurations where the quiet period exceeds the poll budget" are risky.** With `DEBOUNCE=200 ms` and `POLL=500 ms` the effective debounce already *is* one poll, so the stated rationale doesn't describe the configured values.
- **[?] C6 — `DESIGN.md:57-58` describes content hashing as "an extra full read of every changed file per poll."** That's roughly the right cost, and hashing only the already-identified changed files is the natural fix for A3 — the rejection reason ("mtime is guaranteed to change on every edit") is the part that is false.

---

**If you want the shortest list to act on first:** A1 (the lock does not provide single-instance), B1+B5 (replay missing + zero error handling = one race kills the daemon permanently), B2 (stale state marked synced), A3+B3 (silent divergence), A6 (the polling cost model).

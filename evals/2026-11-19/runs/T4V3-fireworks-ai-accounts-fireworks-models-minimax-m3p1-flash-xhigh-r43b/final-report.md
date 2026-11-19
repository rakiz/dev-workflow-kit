## Verdict

The design and the prototype disagree in both directions. The design makes three claims that are false on their own terms (poll headroom, latency bound, "mtime always changes"), and the prototype fails to implement 5 of the design's explicit guarantees while adding 3 crash modes the design says cannot happen. All "measured" claims below were reproduced against the actual `syncd.py`/`state.py` in this repo.

---

# A. Flaws in the design itself

**A1. The polling budget doesn't exist. (measured)**
DESIGN.md:13-15 claims a 50 000-file scan "costs well under 100 ms … so polling leaves ample headroom". On this machine, `snapshot()` over 20 000 files takes 0.46–0.49 s warm (4 consecutive runs), extrapolating to **≈1.15–1.23 s for 50 000 files** (~23 µs/stat, not ~2 µs). Even taking the design's own 100 ms at face value, that is 20 % of the 500 ms budget *at idle*. The cycle is work-then-sleep (`syncd.py:64-71`), so the effective poll period is `cycle + 500 ms`, not 500 ms — a scan alone can exceed it. This premise also undercuts the rejected-alternatives argument: with the budget blown, "polling is portable and bounded" (DESIGN.md:55-56) no longer holds, and the latency bound in A2 collapses with it.

**A2. The debounce/latency claims are self-contradictory and arithmetically wrong. (measured)**
DESIGN.md:17-20: "at most 200 ms of latency to any single file — so end-to-end latency stays under one poll plus 200 ms **even while a file is being written continuously**". Both halves fail:
- If the file *is* being written continuously, the quiet period never elapses → the file is **never** copied. Latency is unbounded, not ≤200 ms.
- The quiet timer is only evaluated at poll boundaries (`syncd.py:38-40`), so the quiet period is quantized to one poll. Measured: `DEBOUNCE_SECONDS` of 0.05, 0.20 and 0.45 all produced the first copy at **0.51 s** after detection. Only a value *larger* than `POLL_SECONDS` changes anything. The constant is inert as configured, and the true worst-case detection→copy latency is up to **two poll periods (~1.0 s)**, not "one poll plus 200 ms".
- Consequence: DESIGN.md:64-67 justifies keeping the constants private to avoid "configurations where the quiet period exceeds the poll budget" — guarding a range where the value provably has no effect.

**A3. The rejection of content hashing rests on a false premise.**
DESIGN.md:57-58: "mtime is **guaranteed** to change on every edit". False in three ways: (i) `snapshot()` stores `int(st.st_mtime)` (state.py:19) — whole seconds — so a same-size edit landing in the same integer second is invisible. Measured: after a same-size rewrite with the mtime pinned to the same second, `pending` stayed empty and `dst` kept the stale bytes indefinitely; (ii) many tools preserve mtime (`cp -p`, `rsync --times`, tar, build systems restoring timestamps); (iii) some filesystems have 1 s granularity. `st_mtime` is a float and `st_mtime_ns` exists — the precision needed is available and discarded. As stated this is an invariant the design relies on, so it must hold.

**A4. The crash-safety story is self-defeating: a torn manifest cannot be "repaired by journal replay".**
DESIGN.md:32-34 rejects tmp+rename for the manifest because "the journal already provides the repair path". But repair requires *reading* the manifest, and `commit_manifest` truncates first (`open(path,"w")`, state.py:33) and streams JSON — a crash mid-write leaves invalid JSON. `load_manifest` (state.py:23-29) has no error handling → measured `JSONDecodeError` → the daemon dies at startup, before replay could run. The premise requires the manifest to be loadable in order to be repaired.

**A5. The lock does not deliver the guarantee it claims.**
DESIGN.md:41-48 makes two incompatible claims ("a second invocation refuses to start" / "exactly one daemon ever writes into dst" vs. "the lock is taken at the start of each poll cycle and released as soon as the copy loop ends").
- The lock is absent during the 500 ms sleep → a second instance *does* start; then whichever instance reaches `acquire_lock` first kills the other with an uncaught `RuntimeError`. That's a coin flip, not a guarantee.
- `acquire_lock` is check-then-act (`os.path.exists` → `open`) → measured: **both** concurrent invocations acquired the lock.
- The PID is written but never validated; after any abnormal exit the lock file survives and every later start fails with "syncd already running" forever (measured). No signal handler, no `atexit` → SIGTERM leaves it behind. The daemon is bricked until someone deletes the file manually.
- `release_lock` unlinks unconditionally → the instance that loses the race deletes the winner's lock.

**A6. "Entries merge cleanly" is false — the manifest commit is a lost update.**
DESIGN.md:45-48: "a second instance starting in that window simply produces entries that merge cleanly on its own first commit". There is no merge step: `manifest.update(self.synced)` merges into a snapshot read at the *start* of the cycle, and the write replaces the file wholesale (syncd.py:68-70). Measured: instance A commits `a.txt`, instance B (base read earlier) commits afterwards → final manifest = `{'b.txt': …}`, `a.txt` erased. "Self-describing entries" support per-key conflict *resolution*, which never happens. Also, entries describe the *source* state, not what is in `dst` — a merged manifest can assert sync for files the other instance never copied.
The same window is unsafe for a second reason, measured: during a `commit_manifest`, **188 of 228** concurrent `load_manifest` calls failed with `JSONDecodeError`. The design explicitly sanctions this window.

**A7. The journal is unbounded, and cannot be the authority it is claimed to be.**
- Nothing truncates it (GOAL.md:11-12 lists compaction as *next release*). It grows for the daemon's lifetime and is fully re-parsed on every start → replay cost scales with uptime, not with pending work.
- It records **copies only**, no deletions. So a replay resurrects in the manifest any file that was deleted from `src` — undoing exactly what the reconcile step would have done. Consequently "the manifest after a restart reflects exactly the last copy of each file" (DESIGN.md:35-37) is false for deleted files, and the journal cannot be safely compacted without tombstones.

**A8. The ordering claim breaks on the integrity-requeue path.** (see B3) The journal records the *scanned* state of a copy whose bytes may have come from a newer file — so "exactly the last copy of each file" doesn't hold for that path.

**A9. "Renames arrive as delete+create and need no special handling" (DESIGN.md:38-40) is only half-true** — it presupposes the delete half exists (it doesn't, B6), and it says nothing about the dst-side removal, the file↔directory type conflict, or a path re-created mid-cycle.

**A10. "Memory stays flat under burst load" (DESIGN.md:21-24) understates the footprint.** The *pending* set is bounded, but `observed` and `synced` both grow to the full tree size and are never pruned (measured: `observed` = 50 after the first poll on a 51-file tree). The fresh snapshot, the loaded manifest, `observed` and `synced` coexist → ~4 copies of a 50 k-entry table of 2-key dicts. Worse, `flush_one` reads the **entire file into RAM** (`f.read()`, syncd.py:47) → peak memory scales with the largest file, not with the tree.

**A11. Unhandled topology.** `dst` nested inside `src` → the daemon syncs its own manifest/journal/lock and recurses; `src == dst` → undefined; `dst` files edited or removed by the user are never repaired (the manifest is only ever compared against `src`; `dst` is never validated). Symlinks are dereferenced into regular files by `open()`/`stat()`, while `os.walk` classifies symlinked directories as directories and never syncs them.

**A12. Durability is unaddressed.** No `fsync` anywhere in the codebase (grep). Without fsyncing the journal before the manifest, "journal first, manifest second" is unenforceable across a power loss: the manifest can be durable while its repair journal is not — the exact inverse of the intended guarantee. DESIGN.md:59-61 discusses "the extra fsync" only as a cost to avoid for the manifest.

---

# B. Where the prototype fails to implement the design's guarantees

**B1. The journal is never replayed.** `replay_journal` exists (state.py:57-66) but is **never imported or called** by `syncd.py` (the only journal call is `journal_append`, syncd.py:61). The design's central crash-safety sentence (DESIGN.md:29-32) is unimplemented: after a crash, the manifest is just the last committed one, and every copy since is re-done.

**B2. A torn manifest kills the daemon at startup** instead of being repaired — `load_manifest` (state.py:23-29) has no error handling; measured `JSONDecodeError` propagating out of `poll()` → out of `run()`.

**B3. The integrity guarantee is violated in the exact direction the design forbids.** DESIGN.md:26-28: "a file that changed during the copy is requeued with its new state and is **never marked synced** until a clean pass completes". The prototype requeues (syncd.py:52-57) but then unconditionally runs `self.synced[rel] = state` (line 60) and `journal_append(...)` (line 61) with the **stale** state. Measured after a mid-copy change: `synced = {'m.txt': {'size': 4, 'mtime': 111}}` while the true size was 999 — the manifest *and* the journal both record a state matching neither the source nor the destination. The file stays in `pending` so it converges later, but a crash before the next commit leaves the manifest asserting sync for a file that isn't.

**B4. "dst never ends up holding a truncated copy" (DESIGN.md:27-28) is false.** The copy is written directly into `dst` with `open(dst,"wb")` (syncd.py:49-50) — no tmp+rename — so a kill/OOM/disk-full mid-write leaves a truncated file in `dst` with no journal record and a manifest claiming it's in sync → never repaired. The post-copy check (syncd.py:51-52) only asks "did the *source* change", never "is the *destination* short". The design rejects tmp+rename for the manifest but never applies the same argument to the data copy, where truncation is actually possible.

**B5. "A file that vanishes between the scan and its copy is a normal race; syncd retries it on the next poll" and "a transient source error never takes the daemon down" (DESIGN.md:49-51) are both false.**
- `flush_one` → `open(src,"rb")` (syncd.py:46) and `os.stat(src)` (line 51) are unguarded → measured `FileNotFoundError` → daemon dies.
- `snapshot()` → `os.stat(full)` (state.py:18) unguarded → measured `FileNotFoundError` when a file disappears between the walk and the stat → daemon dies.
- Worst case, measured: **deleting a file that is currently pending kills the daemon** — `pending` retains the key, the next poll's flush opens a file that no longer exists. A normal user `rm` is fatal.

**B6. The reconcile step doesn't exist.** No code path in `syncd.py` ever removes a file from `dst` or drops it from the manifest (grep: no `unlink`/`remove`/`reconcile`). DESIGN.md's "Deletions" paragraph describes an unimplemented feature, and with it the rename claim (A9).

**B7. "A second invocation refuses to start" (DESIGN.md:41-43) is a crash, not a refusal.** `acquire_lock` raises `RuntimeError` inside `run()` → uncaught → traceback + exit. And because the lock is only held during a cycle, the second instance usually *starts* and the **first** one dies at its next cycle.

**B8. The stale-lock case bricks the daemon** (measured): no PID liveness check, no signal handling, no `atexit` cleanup → every later start fails with "syncd already running".

**B9. The debounce's second gate is redundant and inconsistent.** Detection compares against the **on-disk manifest** (syncd.py:32), not against `observed`, while `quiet_since` is reset only when `observed[rel] != state` (syncd.py:35-37). Measured: a file whose state reverts to the last observed value bypasses the debounce and is copied in the *same* poll. `observed` is never pruned.

**B10. The manifest is rewritten every cycle even when nothing changed** (syncd.py:68-70). Measured JSON cost: `commit_manifest` 0.031 s + `load_manifest` 0.006 s per 20 k entries → ≈0.09 s at 50 k, i.e. ~18 % of a core at 2 polls/s, on top of the scan — and the full-file replace is what makes the torn-read window in A4/A6 wide.

**B11. Two smaller gaps.** `commit_manifest` doesn't create `dst_root` → with a non-existent `dst` and nothing to copy, the first commit raises `FileNotFoundError` (measured). And `snapshot()` filters dot-*directories* but not dot-*files* → measured keys `['.gitignore', '.syncd_manifest.json', 'sub/a.txt']`; `.gitignore`, `.DS_Store` and (if `dst ⊂ src`) the manifest/journal/lock all get synced.

**B12. `time.time()` is used as the debounce clock** (syncd.py:28) — wall-clock steps (NTP) can stall or spuriously trigger flushes; `time.monotonic()` is the correct clock for interval measurement.

---

# C. Labeled speculative / not verifiable here

- **C1. synccli's manifest format and filename are not in this repo**, so DESIGN.md:72-74's compatibility claim is unchecked. Two concrete risks: if synccli's entries carry extra keys (sha256/mode), `prev != state` (syncd.py:33) is true for every file on every poll → the daemon re-copies the entire tree forever; if the filename differs, syncd starts with an empty manifest and re-copies everything once.
- **C2. The 1.15 s/50 k scan figure is from one machine** (macOS/APFS, warm cache). The *direction* (scan cost ≫ 500 ms poll budget) holds here; the design's "well under 100 ms" was measured elsewhere and the exact number is hardware-dependent.
- **C3. A FIFO/socket under `src` would block `open(src,"rb")` forever.** Not tested; flagged as a hazard only.
- **C4. Whether the 50 k-file tree is on spinning disk, network FS or APFS** determines how much of the scan cost is I/O vs. syscall overhead. Unverified.
- **C5. Concurrent instances (A6)** may not be a supported mode at all; the lost-update demo refutes the *claim* ("merge cleanly"), not a stated requirement.

---

**Priority order if this gets fixed:** B5/B6 (the daemon dies on ordinary file churn) → A4/A6 + B2 (the manifest is a crash magnet) → B4/B3 (the integrity guarantee is decorative) → A1/A2 (the poll budget and latency claim are wrong) → A3 (mtime heuristic) → A7/A12 (journal growth and durability).

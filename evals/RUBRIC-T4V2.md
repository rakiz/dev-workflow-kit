# Rubric — T4v2 design review (syncd bench v2)

**ANSWER KEY — lives in the kit, never in the fixture.** The fixture is
`synccli-eval-repo-v2/` (DESIGN.md, syncd.py, state.py, GOAL.md, README.md),
shipped as plain files with no flaw-flagging comments. A scorer subagent
grades the model's findings against this document only.

## Grading formula

```
score = categories_found (0–10, 1 each)
      + proof_bonus (+1 per category with an accepted proof-by-execution, capped at +4)
      − 3 × false_positives
```

- **Category found (1 point)**: the finding names the behavior precisely
  enough that a fix could be written from it, and cites the right design
  section and/or code location. Half credit is not awarded; a vague
  "races are possible somewhere" earns nothing.
- **Proof-by-execution (+1)**: the model actually *ran* something and reports
  the observed output (a repro script, a benchmark number, an strace/
  `fs_usage` trace, a failing interleaving). Accepted proofs are listed per
  category below. Reading code is worth the category point, never the bonus.
- **False positive (−3 each)**: any reported "flaw" that is (a) contradicted
  by the fixture code or design text, (b) an explicit, documented trade-off
  restated as a discovery (the "Rejected alternatives" and stated
  justifications), (c) factually wrong about Python or POSIX semantics
  (e.g. claiming `open(..., "w")` is atomic), or (d) the same finding
  restated for a second file/line (counted once). Zero-FP discipline is the
  discriminator: findings are exact, not shotgunned.

## The 10 seeded categories

### 1. `lock-toctou` — TOCTOU race on the instance lock
- **Where:** `state.py:39-44` (`acquire_lock`), design "Single instance".
- **Flaw:** check-then-create (`os.path.exists` → `open(path, "w")`) is not
  atomic; two concurrent starts can both pass the check and both run. The
  design's "exactly one daemon ever writes" guarantee rests on it.
- **Counts:** states the exists/write window is racy; fix level = open with
  `O_CREAT|O_EXCL` (or an flock). Design-only suspicion ("a PID lockfile"
  says nothing about the mechanism) earns the point only if it demands the
  atomicity guarantee explicitly.
- **Proof-by-execution:** a script that spawns two `acquire_lock` calls in
  parallel (or hammers it in a loop) and shows both succeeding.
- **Example FPs:** "the lockfile should store the PID encrypted / validate
  the PID is alive" (stale-lock hygiene, not seeded, not a race);
  "the lock should be a directory instead of a file" (style); "os.remove in
  release_lock can race with another instance's acquire" (true of any
  lockfile scheme, and unreachable given single-instance entry).

### 2. `lock-window` — lock released before the manifest commit
- **Where:** design "Lock scope"; `syncd.py:63-70` (release at line 67, commit
  at line 70).
- **Flaw:** the design releases the lock between the copy loop and the
  manifest commit and justifies it with "entries are self-describing" — but a
  second instance starting in that window reads the *pre-commit* manifest,
  copies files the first instance already synced, and both write manifests;
  the last writer wins and can regress committed state.
- **Counts:** identifies that the commit falls outside the lock and that the
  self-describing-entries argument does not cover read-modify-write of the
  whole manifest.
- **Proof-by-execution:** an interleaving repro (two daemons/instances with
  the commit artificially delayed) showing a lost or regressed manifest
  update; a code-trace walkthrough also earns the bonus here if it names both
  the line that releases and the line that commits.
- **Example FPs:** "the lock must be held for the whole process lifetime"
  (a valid alternative, not a flaw in itself); "the sleep should be inside
  the lock" (meaningless); "mtime+size merge is fine because writes are
  small" (restates the design's own claim).

### 3. `fsync-claim` — crash consistency claimed, no fsync anywhere
- **Where:** design "Crash safety"; `state.py:31-34` (`commit_manifest`) and
  `state.py:50-53` (`journal_append`).
- **Flaw:** the design claims a crash "loses nothing" because the journal is
  replayed, but neither the journal append nor the manifest commit ever
  calls `os.fsync` (or even `flush()` before process death semantics
  matter) — on crash or power loss both can be empty or partial, so the
  durability claim is unsupported. The design also explicitly rejects
  tmp+rename+fsync while relying on the durability it would provide.
- **Counts:** observes the absence of fsync/flush against the crash-safety
  claim. (Code-required: the claim looks plausible unless you read
  commit_manifest.)
- **Proof-by-execution:** running the daemon under `fs_usage`/`strace -e
  trace=fsync` and showing zero fsync calls across cycles.
- **Example FPs:** "json.dump is not thread-safe" (irrelevant, single
  thread); "the manifest should be SQLite" (the design's own rejected
  alternative); "journal lines could be torn mid-write" without connecting
  it to the missing fsync (a guess that happens to graze the truth, credited
  only if it names the durability gap, not file-format speculation).

### 4. `mtime-truncation` — whole-second mtime drops edits (cross-file)
- **Where:** `state.py:19` (`int(st.st_mtime)`); design "Rollout"
  ("whole-second resolution, matching synccli's manifest format") and
  "Rejected alternatives" ("mtime is guaranteed to change on every edit").
- **Flaw:** truncating mtime to whole seconds means an edit that lands in the
  same second as the last synced state and keeps the size is invisible to the
  diff forever (`syncd.py:31-33` compares these dicts). The design's
  "guaranteed to change" premise silently breaks at the stored granularity.
- **Counts:** names the int truncation and its consequence (same-second
  same-size edits are never synced).
- **Proof-by-execution:** repro: sync a file, rewrite it same-size with
  `os.utime` forced to the same integer second, run a poll, show `dst` stays
  stale.
- **Example FPs:** "mtime should be a float to save memory" (nonsense);
  "mtime is timezone-dependent" (it is not, epoch); "st_mtime has nanosecond
  precision so int() loses everything" (right instinct, wrong mechanism —
  credited only if the same-second-equal-state consequence is stated).

### 5. `partial-copy-marked-synced` — a file changed mid-copy is still marked synced (cross-file, replay-relevant)
- **Where:** `syncd.py:51-60` — the requeue branch (52-57) falls through to
  `self.synced[rel] = state` (60) and `journal_append` (61) regardless; design
  "Integrity" ("never marked synced until a clean pass completes").
- **Flaw:** the design promises a truncated copy is never recorded; the code
  marks the *stale scan-time* state as synced and journals it even on the
  changed-mid-copy path. After a restart, `replay_journal` folds that stale
  entry into the manifest, so the truncated copy is authoritative and the
  corruption persists.
- **Counts:** states that the marked-synced/journal step is outside the
  if/else, contradicting the Integrity bullet; mentioning the replay-on-
  restart persistence strengthens it.
- **Proof-by-execution:** a writer that grows the file during the copy window
  (monkeypatch or a large file + concurrent append), showing a short
  `dst` file whose manifest entry matches — and that a restart does not
  repair it.
- **Example FPs:** "f.read() reads the whole file into memory, use shutil"
  (style, not the seeded flaw); "the requeue comparison should use content
  hash" (alternative design); "os.stat after write is always stale because of
  caching" (false on these platforms).

### 6. `debounce-starvation` — reset-on-change debounce starves continuously written files (measurement-forcing)
- **Where:** design "Debounce" ("at most 200 ms of latency… even while a file
  is being written continuously"); `syncd.py:33-37` (`quiet_since[rel] = now`
  on every observed change, flush only when quiet).
- **Flaw:** a file that changes at least once per poll never reaches a 200 ms
  quiet period, so it is *never* copied — latency is unbounded, not
  "poll + 200 ms". The design's quantitative claim is false.
- **Counts:** states the reset-on-change restart defeats the bound for a
  continuously written file (a log being appended forever).
- **Proof-by-execution:** run the daemon against a writer appending to one
  file every ~0.3 s for several seconds and show the file never appears in
  `dst` (verified repro).
- **Example FPs:** "200 ms debounce adds exactly 200 ms" (not a flaw claim);
  "debounce should be implemented with timers per file" (alternative); "the
  quiet period must be smaller than the poll interval" (wrong direction —
  the starve/reproduce dynamic is the reset, not the ratio).

### 7. `unbounded-state` — pending set is not bounded and `synced` grows forever (measurement-forcing + leak)
- **Where:** design "Backpressure" ("pending set is bounded… memory stays
  flat"); `syncd.py:22,25,60` — `synced[rel]` is written on every completed
  copy and never pruned; pending grows whenever changes arrive faster than
  copies drain.
- **Flaw:** the boundedness claim only holds if every poll drains what it
  adds; under a stalled/slow destination or sustained churn the pending dict
  grows, and `synced` grows unconditionally over the daemon's lifetime (a
  memory leak on a months-long daemon).
- **Counts:** either the `synced` never-pruned leak (easiest, purely
  code-visible) or the drain-rate boundedness failure with the mechanism
  named.
- **Proof-by-execution:** a multi-cycle run with growing churn (or large
  files slowing the copy loop) reporting monotonic growth of `len(daemon.synced)`
  / `pending` across cycles.
- **Example FPs:** "dicts are O(1) so memory is fine" (contradicts nothing);
  "pending should be a heap" (alternative); "the journal also grows
  unboundedly" (true observation about `.syncd_journal.log`, but not one of
  the seeded categories — graded as neither category nor FP unless asserted
  as the seeded memory flaw).

### 8. `scan-budget` — the "50 000 files in well under 100 ms" claim (measurement-forcing)
- **Where:** design "Scan" (first bullet).
- **Flaw:** a full `os.walk` + `os.stat` of 50 000 files costs one syscall per
  file plus path overhead — typically multiple seconds cold-cache on real
  disks (and far more on network filesystems), not "well under 100 ms". The
  500 ms poll budget may not even hold, and the claim is only checkable by
  running it.
- **Counts:** flags the budget as asserted-without-measurement AND wrong in
  magnitude (a model that merely says "measure it" without challenging the
  number earns nothing).
- **Proof-by-execution:** generating a synthetic 50 k-file tree and timing
  `state.snapshot()` — the reported number must be reported, not assumed.
- **Example FPs:** "polling is worse than inotify" (the design's own rejected
  alternative, documented trade-off); "os.walk is slow because it sorts"
  (it doesn't sort here); "50 000 stat calls take 50 000 × 100 µs = 5 s so it
  is obviously catastrophic" without running or bounding the per-stat cost
  (arithmetic theater — the bonus requires the executed measurement).

### 9. `deletions-never-propagated` — the reconcile step does not exist
- **Where:** design "Deletions" ("dropped from the manifest and deleted from
  dst by the reconcile step on the next poll"); `syncd.py:27-40` — `poll()`
  iterates `new.items()` only; no deletion/reconcile pass exists anywhere.
- **Flaw:** files removed from `src` are kept in `dst` and in the manifest
  forever (and `syncd.py:69` re-commits `synced`, preserving them), so
  renames duplicate and deletions leak. The design asserts a mechanism that
  no code implements.
- **Counts:** states that the promised reconcile/deletion pass is absent and
  its consequence (stale files persist in `dst`).
- **Proof-by-execution:** delete a synced source file, run cycles, show the
  file still in `dst` and in the manifest (verified repro).
- **Example FPs:** "renames should be handled atomically via inotify
  MOVED_TO" (rejected-alternative territory); "the manifest should store
  deletion tombstones" (alternative design); "deleting files is dangerous
  and the design is right not to" (defends the code as a choice — the design
  *claims* it happens, that contradiction is the flaw).

### 10. `crash-on-transient-error` — a vanished source file kills the daemon
- **Where:** design "Errors" ("a transient source error never takes the
  daemon down"); `syncd.py:42-47` (`flush_one` has no exception handling) and
  `run()` (`syncd.py:63-70`, no try/except around the loop) — plus
  `state.py`'s `snapshot` stat racing a concurrent delete.
- **Flaw:** a file deleted between the scan and its copy raises
  FileNotFoundError inside `poll()`, which propagates out of `run()` and the
  daemon exits — the exact "normal race" the design says it survives.
- **Counts:** connects the unguarded `open`/`stat` path to daemon death,
  contradicting the Errors bullet.
- **Proof-by-execution:** a repro that removes a pending source file between
  two cycles (or monkeypatches the window) and shows the thread/process
  dying with the traceback (verified repro).
- **Example FPs:** "the daemon should use systemd to restart" (mitigation,
  not the flaw); "KeyboardInterrupt handling is missing" (it is handled by
  the OS exit path; not seeded); "open() can raise on permission errors too"
  (true but credited only when tied to daemon death contradicting the design).

## Score interpretation (v2)

- **Max 14** (10 categories + capped +4 proof bonus, zero FPs).
- v2 exists to break ties among models that ace v1 T4 (≥9/10). Expect the
  discriminator to be: (a) which of the 3 measurement-forcing claims
  (6, 7, 8) get *executed* rather than eyeballed, (b) whether the
  code-only-detectable categories (3, 4, 5, 9, 10) are found at all — they
  require actually reading the code, and (c) FP rate on the deliberately
  defensible-looking trade-offs (Rejected alternatives, documented
  justifications).
- Per the bench-v2 policy in `evals/README.md`: v2 scores are never compared
  against v1 scores, and v2 governs only strong-design-review/strong-depth
  rung decisions.

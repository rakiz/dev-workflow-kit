Read it, plus the existing `synccli.py`/`incremental.py` it builds on. Critique below.

## Wrong assumptions

- **"mtime always changes on edit"** (DESIGN.md:15) is false. `mv`, `cp -p`, `git checkout`, rsync, and many editors (atomic save via rename) preserve or reuse mtime. Combined with 1s mtime granularity, an edit within the same second with unchanged size is **silently never synced**. The v0.2 code already leans on this: `incremental.py:38` uses `old[rel]["mtime"] <= state["mtime"]`, so equal mtimes are treated as fresh.
- **"manifest is small, rewrite in place, atomicity not needed"** (DESIGN.md:14). 50k entries is not small, and in-place rewrite is the worst call here. A crash/kill mid-`json.dump` leaves truncated JSON; next start `json.load` raises and the daemon **dies on boot** (`synccli.py:79`).
- **"polling is cheap"** (DESIGN.md:20). A full `os.walk` + `os.stat` of 50k files is ~50k syscalls; at 500 ms that's ~100k stats/s, and the write of a 50k-entry JSON twice per second is the real cost — not the walk.
- **"log to stdout and continue"** (DESIGN.md:18). Directly collides with the JSON-mode constraint in GOAL.md:6 ("nothing else may be printed to stdout"). Logging must go to stderr/syslog.

## Major risks / what breaks under load

1. **Poll interval is a lie.** At 50k files a full scan can exceed 500 ms, so the effective interval is "scan time + 500 ms", not 500 ms. During any long copy the daemon is blind (DESIGN.md:19) — changes land a full cycle late.
2. **Torn copies.** `copy_file` (`synccli.py:66`) writes straight to `dst`; readers see partial files, and a crash leaves a half-written file that the manifest already records as current. Needs temp-file + atomic `rename`.
3. **Manifest write amplification.** Serializing and rewriting all 50k entries every cycle, even when nothing changed, is the dominant steady-state cost (SSD wear, IO churn). Rewrite only on change.
4. **Snapshot race.** `sync()` writes the manifest from the *scan-time* `src_manifest` (`synccli.py:86`); if the source changes during the copy, the manifest claims a state that was never copied → permanently "fresh", change lost until the next real edit.
5. **Deletions never propagate.** `changed_files` (`synccli.py:36`) only iterates `new_manifest`; files removed from `src` stay in `dst` and in the manifest forever. A "sync engine" that only grows is not a mirror.
6. **No backoff on errors.** An unreadable/always-failing file is retried every cycle forever, with no distinction transient vs permanent and no alert.

## Decisions to change first

1. **Atomic manifest**: write temp + `os.replace`; write only when state changed. Non-negotiable.
2. **Atomic copies**: temp + `rename`, and re-`stat` the source after copy to detect mid-copy modification.
3. **Detection**: for 50k files, either adopt FSEvents/inotify (the "complexity" is smaller than the cost of being wrong), or at minimum make the interval adaptive and dir-level incremental. Fixed 500 ms full-tree polling is the wrong side of the cost/benefit curve for "a few changes per minute."
4. **Hash-on-mtime-change**: keep the no-hash-every-poll rule, but hash a file when its mtime/size changed before trusting it. Fixes mtime-preserving writers cheaply.
5. **Handle deletions** (and rename) explicitly.
6. **Configurable interval + exclude list**; "configuring it invites misuse" is not a reason to hardcode a value that is wrong at the stated scale.
7. **Don't reuse `sync()` as-is** (DESIGN.md:31): it re-scans and rebuilds the full manifest every call (`synccli.py:74`) — i.e. it redoes the exact expensive work the daemon exists to avoid, and carries the non-atomic manifest bug. Extract the incremental core instead.

Missing from the design entirely: daemon lifecycle (start/stop, restart, PID), dst-edit conflict handling, and any test plan for `syncd`.
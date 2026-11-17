Design written to `DESIGN-d1.md` at the repo root (`/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-64411/DESIGN-d1.md`, 422 lines). Covers all required sections:

- **Concurrency** (§3): `fcntl.flock` on `.lock`, per-PID staging dir, atomic `os.rename` commit, shared/exclusive `.prune.lock` for reader/writer isolation.
- **Read isolation** (§3.3): hidden staging prefix invisible to `snaputil.list_snapshots`, index written last via temp+rename.
- **Crash recovery** (§4): orphan staging cleanup, corrupt index quarantine+re-derive via `scan_files`/`file_state`, explicit reporting.
- **Vanished source files** (§5): absent from snapshot+index, logged, exit-code semantics, override of `synccli.copy_file:62-69` silent swallow.
- **Retention** (§6): `keep_last`/`keep_daily`/`keep_weekly` over `snaputil.prune_snapshots:23-36`, invariants (never delete newest/last, prune is explicit not implicit).
- **Incremental/dedup** (§7): `size+mtime` fast path via `file_state`/`changed_files` + SHA-256 confirmation, hard-link from previous snapshot, documented same-second miss.
- **Performance budget** (§8): measured per-file costs (`scan_files` ~5µs, `file_state` ~16µs, `copy_file` ~230µs overhead) and derived ~15s for 1GB/20K files (budget: <30s local, <60s network).
- **Scaling** (§9): explicit `O()` bounds table over N/F/B for time, memory, disk, FDs, with concrete 30-dir example.
- **Grounding** (§2): every reused function cited with file and line numbers; overrides named with location and reason.

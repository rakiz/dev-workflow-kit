I wrote the design to `DESIGN-d1.md` in this repo copy, `/private/var/folders/k0/m1pgz3y90k34xd8h1b4tdkqw0000gp/T/bench-v3-36951/`. I worked alone, with no subagents.

I first wrote it to the wrong directory, a cppgraph install repo under `~/.local/share/cppgraph`. I moved it here and confirmed the cppgraph repo is clean.

The design covers each point in `BRIEF.md`:

- **Layout and concurrency:** one label per source directory, so `snaputil.list_snapshots` works unchanged. Runs and prunes take an exclusive `flock` per label; restores take a shared lock. Locks are released when a process dies.
- **Publish:** a snapshot exists only after a single directory rename from staging, so readers never see a partial or mixed snapshot.
- **Crash recovery:** dead staging and trash directories are discarded, not repaired. A corrupt index in a published snapshot is reported and excluded from the reference search.
- **Vanished or unreadable sources:** the snapshot omits the file and the run reports it, the same way for scheduled and manual runs. Exit code is 3 when files were skipped.
- **Change detection:** per file, by `(size, mtime_ns, ctime_ns)`, with a racy-timestamp rule. The design lists what the key can still miss.
- **Retention:** keep the newest K valid snapshots per label, deleted by rename-then-remove so a concurrent restore is never broken.
- **Performance:** a budget of 60 s for the initial backup of about 1 GB and 30,000 files. The budget is a judgement, based on a measured 15.3 s copy on this machine with a warm cache. A cold-cache run was not measured, and the design says so.
- **Scaling:** bounds are stated for N directories and the tree. Two constants are not yet measured: index bytes per file and memory per manifest entry.

I checked the existing code by running it and reading it. Four findings change how `backupctl` must behave:

- `copy_file` swallows read errors, so `sync` writes a manifest entry for a file it did not copy (`synccli.py` L68-69, L85-86).
- `build_manifest` does not catch a file that vanishes mid-scan, so the whole sync aborts.
- `scan_files` silently drops dot-directories such as `.git` (`synccli.py` L14).
- `safe_snapshot_path`'s docstring is wrong: `..` segments survive `normpath`, so a stored path can escape its snapshot (`snaputil.py` L54-63).

`prune_snapshots` with `keep=0` deletes every snapshot, and it removes snapshots in place, which can break a restore that is reading them.

The design lists its open items in section 12.

# backupctl design

## Contract and scope

`backupctl run --config CONFIG` snapshots the entire configured set into one
generation. Configuration maps stable, unique directory IDs to absolute source
paths and specifies a backup root and `keep` (default 7, minimum 1). A generation
contains `data/<id>/` for every configured directory, including empty ones, and
an index of the regular files actually present. Failure before publication
publishes no generation; post-publication failures report the committed or
uncertain outcome explicitly. The same command, exit codes, and diagnostics apply
to interactive and scheduled runs; scheduling and restore implementation are
outside this design.

A true point-in-time image of actively changing independent directories cannot
be obtained by walking them. The caller must supply a quiesced source set for
the entire scan and copy, or mount a read-only, simultaneous filesystem
checkpoint of the whole set and configure its paths. Per-volume checkpoints
taken at different times do not constitute a single set-wide instant. The tool
checks for many concurrent changes but cannot prove quiescence; without this
precondition it offers only a best-effort copy, not a point-in-time image.
File-level reuse has the additional detection limitation described below.

The first version backs up regular files and directories, including hidden
names and empty directories. It rejects symlinks and special files rather than
following or silently omitting them. It preserves file bytes and modification
times; it does not promise ownership, ACLs, extended attributes, or original
permission bits. Source roots must exist and be readable, be disjoint from the
backup root, and have unique IDs. Paths are relative to their directory ID;
reject absolute paths, `..` components, invalid IDs, and paths escaping the
root, and use directory-relative no-follow operations to prevent symlink
substitution. Backup storage is a local filesystem supporting same-filesystem
atomic directory rename, hard links, `flock`, and file/directory `fsync`.
No process may modify a published generation, its hard-linked files, or the
lock files; restores copy out rather than writing into or hard-linking from
the backup. This is a cooperative protocol, not protection against arbitrary
processes, filesystem damage, or storage that lies about flushes.

## Existing code and deliberate overrides

* Extend `synccli.scan_files` (`synccli.py:10–19`): retain relative-path
  enumeration and sorting, but include hidden directories, report walk errors
  (`os.walk` currently suppresses them by default), record directories, and
  reject unsupported types without following links. The current function drops
  dot-directories and only returns files. A separate backup-specific scan can
  share the enumeration primitive after this refactor.
* Reuse the state shape and comparison in `synccli.file_state` (`:22–25`) and
  `synccli.changed_files` (`:36–42`), per directory ID. Extend
  `synccli.build_manifest` (`:28–33`) to consume the checked scan, surface
  individual stat errors and include empty directories in separate inventory;
  do not call its present unchecked form. Preserve the existing `{size, mtime}`
  semantics for file change detection. Add pre/post-copy identity checks as
  described below, not as a claim that those checks detect every edit.
* Refactor `synccli.copy_file` (`:62–69`) to provide a streaming, error-reporting
  copy primitive with bounded buffers and caller-controlled destination cleanup.
  Its present implementation reads the whole file at once, suppresses
  `OSError`, and may leave an empty or partial destination. It cannot be used
  unmodified. `synccli.sync` (`:72–87`) is not the transaction coordinator:
  it updates an existing destination and writes its manifest directly even if a
  copy failed. Backup uses a private generation and atomic publication instead.
  Keep the sync CLI's existing contract when extracting shared primitives.
* Reuse `snaputil.list_snapshots` (`snaputil.py:8–20`) for candidate discovery,
  then strictly validate names, entry type, and commits: the helper actually
  accepts any directory beginning `snap-`, rather than validating its stated
  date format. Use `snaputil.snapshot_disk_usage` (`:39–51`) only for a
  **logical** size report: it sums `st_size` and counts shared hard links once
  per path, not physical allocation. Do not use `snaputil.prune_snapshots`
  (`:23–36`) directly: it has no reader lock, verification, or crash-safe
  deletion, and `keep=0` can remove everything despite its docstring.
  Refactor it to accept the protected candidate set and locking protocol below,
  or put that protocol around a new safe pruning primitive in `snaputil`.
  Do not rely on `safe_snapshot_path` (`:54–63`): `normpath` does not confine
  absolute paths, `..`, or symlink traversal. Replace its implementation with
  validated, no-follow relative traversal before using it. `is_stale` (`:66–73`)
  is not a lock or liveness test; it also uses `<=` despite its docstring.

## Layout, writers, and readers

The root contains permanent `.writer.lock` and `.readers.lock` files, a private
`.staging/`, a private `.trash/`, a private `.quarantine/`, and published directories named
`snap-<20-digit-sequence>`. Under the writer lock, choose one more than the
greatest sequence among published and quarantined names; reject overflow. A
quarantine name preserves its original sequence. Because the newest committed
generation is never pruned and quarantines are retained, committed sequence
numbers are not reused. Fixed-width names
sort in creation order, including across clock changes. No persistent `latest`
pointer is required: find the greatest valid committed sequence under the
reader protocol. All staging, trash, and snapshots are on the same filesystem.

All runs acquire an exclusive advisory `flock` on `.writer.lock` for recovery,
construction, publication and pruning. A second run waits, then rescans and
uses the newly committed generation; process death releases the lock. Never
unlink or replace a lock file. Each restore or human-facing reader must take a
shared `flock` on `.readers.lock` **before** listing or selecting a generation,
and hold it until every read and copy from that generation is finished. Provide
a documented `backupctl with-snapshot ...` wrapper/library for this protocol.
Publication does not need the reader lock: existing generations are immutable
and a rename exposes a completed new directory in one step. Recovery that
changes a visible generation and pruning take the reader lock exclusively;
they wait for existing readers and prevent new ones from selecting a victim.
Lock order is writer then readers; readers never acquire the writer lock.

Deletion cannot be safe against an arbitrary reader that does not participate
in a lease/lock protocol: an open directory alone does not pin all its files.
Therefore automatic pruning is enabled only when **all** readers use the
shared-lock contract. For unmanaged human or third-party access, configure
pruning off and do not manually delete generations while they might be read.
This is a necessary operational precondition, not something `flock` enforces
against uncooperative processes.

## Build and atomic publication

1. Under the writer lock perform recovery below. Discover the newest verified
   generation and scan all sources. A missing root, failed directory listing,
   stat error, unreadable file, unsupported type, or other source error aborts
   the entire run. Report directory ID, relative path, operation and error;
   exit nonzero. No previous version is silently substituted.
2. Create `.staging/<random-id>/` exclusively. Build the new directory tree
   from the scanned inventory. Compare each file's size and `st_mtime` against
   the previous generation using `changed_files`. For an unchanged file, hard
   link the verified old snapshot file into the new tree; for a new or changed
   file, stream it via the refactored copy primitive with a 1 MiB buffer. If
   linking fails, abort rather than silently breaking the performance contract.
   Never write through a link. Files removed from the source are absent from
   the new generation, not copied forward.
3. Before reading a changed file, open it without following links and compare
   descriptor identity/type, size, nanosecond mtime and ctime with the scan;
   after copying, repeat the descriptor check and verify that the source path
   still names that identity. For reused files, open for reading without
   following links and recheck descriptor and source path identity and metadata
   before linking; an unreadable source aborts even when its old bytes exist.
   If any check or copy fails, delete
   the private stage, report the path and error, and return nonzero. Apply the
   scanned mtime to successfully copied files, then flush each new file. These
   checks detect common races, including disappearance after listing, but do
   not replace the quiescence requirement. A hard-linked reused file is already
   durable from its prior commit.
4. Build the index only from successfully materialized files and directories,
   using `file_state` on the staged files so it is reconstructible from the
   actual tree; ensure it matches the stage. A timestamp that the backup
   filesystem cannot represent exactly can cause a later redundant copy. Its
   versioned canonical encoding maps each
   directory ID and relative file path to `size` and `mtime`, and includes the
   directory inventory. Write it to a temporary file, flush it, rename to
   `index.json`, and fsync the stage directory. Write a versioned `COMMIT`
   containing the sequence, index digest, and independent canonical tree
    inventory digest (IDs, paths, types, file sizes and file mtimes, including
    empty directory paths but not directory mtimes); flush it and the stage
    directory. Digests detect corruption of
   metadata, not content bit rot. Fsync all newly created data directories
   bottom-up before publication.
5. Atomically rename the complete stage to its unused `snap-...` name and
   fsync both `.staging` and the backup root. Only this rename publishes a generation; `.staging`
   and `.trash` are never snapshot candidates. A crash before it leaves only
   private debris; after it, readers see the complete tree and index. After
   rename but before the root fsync a power loss can yield either the complete
   generation or no generation; success is reported only after the fsync.
   If a flush or rename fails, return nonzero and report whether publication
   occurred; an uncertain outcome is resolved by the next run's recovery.
   Emit a success summary with sequence, copied/reused/deleted file counts and
   bytes, and any retention warnings. Retention failure after a successful
   commit is reported separately as nonzero/partial maintenance, with the
   committed sequence, so retries do not misrepresent the backup outcome.

Unchanged means equality of **one file's** size and floating-point `st_mtime`,
as in `file_state`; it is not content equality. An edit that preserves size
and restores the same timestamp, or one hidden by timestamp resolution or
float rounding, can be missed, even with a quiesced source. In that case the
old bytes are reused. Users requiring exact content fidelity must use a future
content-hash mode; this design does not claim that guarantee. All new/changed
files are independent copies; only unchanged files share immutable inodes.

## Recovery and retention

With the writer lock held, remove abandoned `.staging` trees and finish removing
`.trash` trees, reporting each cleanup failure. If abandoned staging cleanup
fails, abort rather than accumulate a second active stage. Never treat either as a
snapshot. A crash while deleting trash is harmless and retryable. Inspect
published names and `COMMIT`/index encoding and digest before using a generation
as a base or pruning it, including checking the actual tree inventory digest.
A committed generation is immutable: interrupted construction cannot leave a
half-written visible index because publication is last. If a visible index is
corrupt or missing, or its commit or actual tree fails verification (including
legacy/interrupted artifacts), take the exclusive
reader lock, re-read it, atomically move the entire generation into a uniquely
named `.quarantine/` entry preserving its sequence, and fsync both directories
before releasing the lock. Never discard or rewrite a visible index in place.
Independently enumerate the quarantined tree into a temporary canonical index,
deriving size and mtime from the actual snapshot files, not the source or the
corrupt index. Compare both its digest and the resulting tree inventory digest
with the intact `COMMIT`. If both match, discard the invalid index, install and
fsync the reconstructed index privately, then atomically rename the complete
generation back to its original name and fsync both directories. Report the
repair. If the commit is unreadable, either digest disagrees, or reconstruction
encounters an error, the original promise cannot be established: retain the
quarantine for operator inspection and report the sequence and reason. On
restart inspect and retry quarantined entries that were interrupted in repair;
never automatically delete them. An interrupted repair remains invisible, and
the previous valid generation remains readable. Recovery reports failure if it
cannot quarantine safely; otherwise continue using the newest remaining valid
generation, or perform a full copy if none exists. External corruption may
already have affected a reader before detection; crash-safety guarantees assume
published files are not externally modified. Inventory validation cannot detect
same-size content rot.

After a new durable commit, keep the newest `keep` verified generations and
select older verified candidates using `list_snapshots` and strict filtering.
Hold the exclusive reader lock while rechecking that the newest verified
generation exists and at least one usable generation will remain. Rename each
victim into `.trash/` and fsync both `.trash/` and the root before releasing the lock; then remove
trash recursively. Renaming is the logical deletion; actual removal may be
retried after a crash. Never prune on a failed backup or if validation/locking
fails. Long-running restores can delay pruning indefinitely, but not snapshot
construction or publication. A disk-full failure leaves the prior generation
intact and reports the error; retention is not used to make space before a
successful replacement exists.

## Performance and bounds

Budget for an initial 1 GiB / 30,000-file backup: **350 seconds**, conditional
on a local storage profile of at least 50 MiB/s sustained payload copying,
and average per-file allowances of 3 ms for scan/stat, 2 ms for open, close,
copy setup and bookkeeping, and 4 ms for file flush. The explicit estimate is
`30,000 × (0.003 + 0.002 + 0.004) + 1,024 / 50 + 30 = 320.48 s`; the final
30 s allows directory operations, index serialization, directory flushes and
publication, leaving about 29.5 s margin. This is an engineering budget under
stated assumptions, not a measurement or a guarantee on slower/network disks.
Benchmark the real target with a cold-cache representative tree and the actual
durability settings; tune or revise the budget if the assumptions fail.

Let N be configured directories, F total files, D total directories, P total
bytes in their encoded relative paths, B total file bytes, C changed/new file
bytes, H changed/new files, and K retained generations. A full run scans and
creates `O(N + F + D)` entries, sorts at most `O(F log F + D log D)`
comparisons (each costs at most `O(L)`, where L is the longest encoded path),
transfers B bytes and flushes F new files. An incremental run
still scans and creates `O(N + F + D)` entries and hard links at most F-H
files, but reads/copies C payload bytes and flushes H new files. Verifying one
generation costs `O(F + D + P)` metadata traversal plus canonical sorting of
at most `O((F + D) log(F + D))` path comparisons, each `O(L)`; verifying K
generations multiplies this bound by K. Peak working memory is `O(N + F + D + P)` for the existing sorted
scan/manifests plus a 1 MiB copy buffer, independent of B and largest file
size. Sequential processing and the writer lock bound active backup copy
buffers to **one** and active stages to **one per root**; waiting writers add
no stages. With K retained generations, distinct referenced payload bytes are
at most the sum of logical file sizes across those generations, no more than
`K × Bmax` when each generation has at most Bmax bytes. This counts shared
inodes once but does not include filesystem allocation rounding, metadata or
overhead; metadata and index storage are
`O(K × (N + Fmax + Dmax + Pmax))`. A run can temporarily require one extra
full generation and failed cleanup/quarantine can consume additional,
unbounded space until resolved. Logical usage from `snapshot_disk_usage` can
overcount shared payload. No claim of fixed total disk usage is made for
unmanaged readers or disabled retention.

## Verification plan

Keep `python3 -m unittest` passing (the existing six tests currently pass), and
add backup-specific tests for hidden/empty directories; first and incremental
copies, hard-link reuse, source deletion, and same-size/same-mtime limitation;
unreadable/disappearing files and copy/flush failures; and index/tree agreement.
Use subprocess crash injection at each write, fsync, rename, repair and prune
boundary, then restart and verify that only complete generations are listed,
recovery reports its actions, and the next run progresses. Test corrupt index
reconstruction and mismatched or missing commit quarantine. Exercise two
concurrent writers and a reader holding the shared lock while pruning waits,
including killed lock holders, plus path traversal/symlink rejection. Measure
the stated initial-backup budget on the target filesystem; also verify that
logical versus allocated size reporting is labeled correctly.

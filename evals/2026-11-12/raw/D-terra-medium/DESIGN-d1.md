# backupctl: immutable, published snapshots

## Decision and contract

`backupctl run --config CONFIG` takes one snapshot of **all** configured
directories as a single transaction. A successful snapshot contains a tree
for each configured directory and an index describing exactly the objects in
those trees. Snapshots are immutable after publication. A failed or interrupted
run publishes nothing and leaves the previous snapshots usable. Both scheduled
and interactive invocations use the same command, behavior, exit codes, and
diagnostics.

The contract depends on two explicit integration requirements:

* The source view must represent one instant. Configure either a filesystem
  snapshot provider that atomically captures all configured sources together,
  or a cooperative quiescence provider that holds one common exclusive lock
  against **all** source writers for the entire scan and copy. A provider must
  be configured; do not silently fall back to a live, uncoordinated walk.
  Multiple volumes need a provider with a genuinely atomic group snapshot, or
  the common writer lock. Otherwise fail before publication. A plain `os.walk`
  followed by copies cannot guarantee a point-in-time image of changing trees.
  An uncooperative writer invalidates the quiescence provider's guarantee;
  metadata checks below detect some, not all, such violations.
* Restore and other readers must participate in the reader lock protocol below
  for the whole time they list, select and read snapshots. An arbitrary process
  using paths without that protocol cannot be protected from concurrent
  deletion; merely opening a directory or renaming it to a trash directory is
  insufficient. Humans use `backupctl list` and `backupctl with-snapshot ID --
  COMMAND`, which holds the lock until COMMAND exits. Restore tooling holds the
  shared lock through its final read. Readers never inspect staging or trash.

The supported deployment is a local POSIX filesystem for the backup root with
reliable `flock`, same-filesystem atomic directory rename, hard links and
directory `fsync`; validate capabilities and fail closed otherwise. All
participants use the same root and the same lock files. This is not a protocol
for NFS, independent machines with uncoordinated locks, or a root modified by
outside tools. Permissions restrict modification of published snapshots to the
backup service; readers must treat them as read-only. Copies restored from them
must be independent files, never writable hard links back into the backup.

## Configuration and representation

Config specifies the backup root, a stable unique ID and absolute source path
for each directory, the source-view provider and retention count `keep` (default
30, minimum 1). Validate IDs, unique and non-overlapping source trees, root
outside every source tree, provider compatibility and lock support before
starting. Reject duplicate IDs, unsafe paths and an unavailable source. IDs
are stable logical names; record the configured source path and provider capture
time in the index. Configuration changes create the next complete set; a newly
added ID gets a full copy. Never follow source symlinks to external data.

Layout, all within one filesystem:

```text
root/
  locks/writer.lock                 # stable inode, never unlink or replace
  locks/readers.lock                # stable inode, never unlink or replace
  staging/<unique-run-id>/
  snapshots/<unique-snapshot-id>/
    index.json
    trees/<source-id>/...
  trash/<unique-snapshot-id>/
```

Only immediate children of `snapshots/` are published snapshots; IDs are
collision-resistant and not reused. Under the writer lock assign a monotonically
increasing publication generation, one greater than the highest published
generation; store it in the ID and index. Use generation, not wall-clock capture
time, for newest selection and retention. At least the newest generation always
remains, so the next run can recover the counter without a mutable counter file.
A staging directory is a sibling of `snapshots/` so rename does not
cross filesystems. `index.json` is outside the copied trees, so a source file
named `.sync_manifest.json` or `index.json` cannot collide with it. Its
versioned schema records snapshot ID, capture time, source IDs/paths, and every
relative object path and type, with regular-file source size and mtime, mode,
and other metadata supported below; it records symlink targets and directories
including empty ones. No index entry is written as successful until its object
exists in staging. Validate the final index against the staging tree before
publication, including the absence of unexpected entries. Reject absolute
paths, `..`, duplicate paths and symlink-based path traversal when consuming
indexes. Encodings must round-trip POSIX filenames, including non-UTF-8 names.

Preserve regular files, directories, symlink objects and targets, empty and
hidden directories, mode and mtime. Do not follow symlinks, including symlinked
directories. Reject sockets, devices, FIFOs and other unsupported objects with
a clear error rather than hang or claim a full backup. Ownership, ACLs, xattrs,
hard-link identity and sparse-file layout are not promised; document this
restore scope in CLI help. Restore validates the index, recreates objects
without following links outside the destination, and copies regular file data.
Store source metadata in the index as the authoritative restore metadata. Apply
directory modes and mtimes after creating children; restore can temporarily use
owner-accessible modes while constructing trees, then apply final metadata.
Backup storage permissions may differ from source permissions so backup readers
can traverse and read every object; never modify a reused hard-linked inode to
apply source metadata. The index, rather than backup inode attributes, controls
the restored mode and mtime.

## Run and publication protocol

1. Acquire exclusive `writer.lock` for the whole run, blocking by default;
   optional timeout exits nonzero. This serializes scheduled and manual runs,
   recovery, reference selection and pruning. Locks are OS-managed and released
   on process death; never infer ownership from a PID file. Bootstrap lock
   files with atomic create-if-absent, and never replace them.
2. Under that lock, remove abandoned `staging/` and `trash/` entries left by
   prior runs. Neither is visible as a snapshot. Failure to clean up is reported;
   do not sacrifice a published snapshot to recover space. Select the most
   recent complete published snapshot as the incremental base, if one exists.
3. Acquire the provider's source view/lock, covering all sources at one instant.
   Make a private unique staging tree. Enumerate and record all objects; copy
   changed/new regular files, hard-link unchanged ones from the prior snapshot,
   create directories and symlinks, and build the index from objects actually
   created. Keep the provider view/lock until all source reads and validation
   complete, then release it in a `finally` block. An orphaned provider snapshot
   has a run ID and is reclaimed by the provider on the next run; releasing a
   dead process's quiescence lock must also be automatic.
4. Close and check writes; flush and `fsync` newly written file data, the index,
   and all newly populated directories bottom-up. Validate staging against the
   index and finish the index before it becomes visible. Atomically rename the
   completed staging directory to a fresh `snapshots/<id>` and `fsync` both
   affected parent directories. The rename is the sole publication point: a
   reader sees either no such ID or its entire tree and index. No `latest` file
   is necessary: list complete IDs and choose by generation under the
   reader lock. Never mutate the published tree or index in place.
5. After publication, apply retention as described below, report the snapshot
   ID, counts and bytes copied/reused, and exit 0. If pruning fails, the new
   snapshot remains valid but exit nonzero and report the published ID and
   retention error; retry cleanup/pruning on the next run. Failures before
   rename exit nonzero with no new published ID. A crash or error after rename
   can leave a valid new snapshot even if no success was reported: the next
   list/run discovers it. Do not roll it back.

At any interruption before rename, only staging/provider resources can remain;
they are never considered complete. At/after rename, only a fully built image
is visible. The `fsync` ordering targets crash and power-loss durability on the
stated filesystem, subject to its documented guarantees; if any required flush
fails, report failure and do not claim durable success. For SIGINT, use the
same error path; SIGKILL and sleep recovery rely on the same publication and
startup cleanup rules. Ensure the provider and lock file descriptors are not
accidentally inherited by unrelated child processes.

## Retention and concurrent readers

Retain the newest `keep` published snapshots, with at least one regardless of
configuration. Prune only after a new snapshot is committed; a failed backup
never prunes. Hold `writer.lock`, then take **exclusive** `readers.lock` before
enumerating deletion candidates. A reader takes **shared** `readers.lock`
before listing or choosing an ID and keeps it until all snapshot reads finish.
Thus a restore can run concurrently with construction and publication, while
pruning waits for existing readers and prevents new ones from choosing a
candidate during deletion. Readers do not acquire `writer.lock`, avoiding lock
inversion. A long restore may delay pruning and allow temporary disk growth; it
must never be forcibly unlocked.

With the exclusive reader lock held, re-list, retain the newest `keep`, and
atomically rename each older candidate into `trash/`, syncing the affected
directories. The newest committed snapshot is never a candidate, even if a
deletion or cleanup fails. Delete trash recursively while still holding the
exclusive lock, then sync the trash directory. A crash during deletion leaves
only invisible trash to clean on the next run. Hard links keep shared file data
alive as long as any retained snapshot refers to it. Failure to acquire the
reader lock or delete files leaves extra snapshots/trash, not fewer than one
published snapshot. Initial cleanup of trash requires the same exclusive reader
lock; cleanup of staging does not. This protects all *participating* readers,
not an uncoordinated process already holding a pathname.

## Incremental detection and failure semantics

Use the preceding snapshot's index for the matching source ID and relative
path only when the configured source path and source-view identity also match;
a changed mapping requires a full copy for that source. For regular files, the
existing `synccli.file_state` representation is
`{size, mtime}` and `synccli.changed_files` compares that state per file.
Reuse a prior regular file only when this state, type and preserved mode match,
and the previous indexed object actually exists as a regular file. Otherwise
copy it from the source view. Type/target changes, removed files and directory
metadata are handled by constructing the new tree from the new enumeration,
not by mutating the old tree. Hard-link only from a prior published backup,
never from a live source; never open a linked file for writing or change its
inode metadata. A missing/corrupt base object is a fatal error, not permission to
publish a broken link; recovery requires repair or an explicitly verified full
backup. Use the same destination filesystem so hard-link failures are fatal,
not silent fallback.

The granularity is one whole file, not blocks. Size plus the existing floating
`st_mtime` can miss a same-size edit that preserves or restores mtime, multiple
edits within timestamp resolution, or deliberate metadata spoofing. Such an
edit will reuse old content; consequently a published image is exact only under
the source policy that meaningful edits change this fingerprint. A stricter
content-hash mode could remove this particular false-negative at the cost of
reading every file, but is not part of this design. Mode is separately checked
to avoid linking an inode needing different permissions. Index metadata describes
the captured view, not a later live source; do not compare destination copy
mtimes as a substitute for source state.

If a file disappears, becomes unreadable, changes unexpectedly during a
cooperative-view read, a directory cannot be listed, or any copy/link/write,
validation or fsync fails, abort the **entire** transaction, report the path,
operation and OS error on stderr, and exit nonzero. No partial snapshot or
index is published, and the next invocation retries from a fresh source view.
Detect changed files by opening without following symlinks and checking type,
identity, size and timestamps from the open descriptor before and after the
copy against the enumerated state; detect premature EOF and propagate read,
write, close and directory traversal errors. These checks are defense in depth,
not a replacement for the source-view requirement. A source object deleted
*before* the capture instant is simply absent from that snapshot; an
inaccessible root is an error, not an empty directory. Disk-full and permission
failures follow the same abort/report path. Log start/end, capture time,
snapshot ID when published, summary counts and errors to stdout/stderr so the
scheduler can alert on the same nonzero status a person sees.

## Grounding in the existing code

Implement `backupctl.py` alongside `synccli.py`; factor and extend the existing
primitives rather than writing a separate scanner/differ/copier:

* Extend `synccli.scan_files` / its underlying `os.walk` traversal with an
  opt-in strict tree enumeration API for backup: include dot directories,
  return directories and symlinks as well as regular files, reject special
  files, avoid following links, and raise traversal errors. Today `scan_files`
  skips dot directories, returns only filenames, and `os.walk` suppresses
  errors by default. Keep its existing default behavior for `sync` callers.
* Extend `synccli.file_state` and `synccli.build_manifest` with a strict,
  type-aware path built on the existing state collection, recording the extra
  metadata and errors above. The existing `build_manifest` only records files
  and aborts on a failing `stat`; `os.stat` follows links. Backup must use
  `lstat`/no-follow operations, and consume the stable source view. Do not
  confuse this in-memory inventory with the committed backup index.
* Reuse `synccli.changed_files` for the regular-file `{size, mtime}` comparison,
  then apply the additional type/mode eligibility checks. Its current output
  does not include deleted files; assembling a fresh tree naturally removes
  them. `synccli.collect_stale` is not a retention algorithm and is not needed.
* Refactor `synccli.copy_file` into a shared strict streaming copy primitive
  and a compatibility wrapper if necessary. Today it reads the entire file into
  memory, catches every `OSError`, can leave a partial destination, and gives
  no success indication. Backup requires bounded chunks, checked completion,
  error propagation, descriptor checks, metadata handling and flushes before
  publication. Never use `synccli.sync` as the transaction: it copies into an
  existing destination and writes `.sync_manifest.json` even after ignored copy
  errors, so it cannot produce immutable or safely published snapshots.

Preserve the existing default `synccli` API and its tests while adding strict
interfaces; compatibility behavior is not used by backupctl. The current six
tests (`python3 -B -m unittest -v`) pass, but exercise only ordinary files and
do not establish the backup guarantees.

## Budget and scaling

Target initial end-to-end backup: **at most 75 seconds** for 1 GB (10^9 bytes),
20,000 regular files, warm local source and backup on an otherwise idle SSD,
excluding provider creation and quiescence wait. Explicit planning assumptions:
effective aggregate copy throughput 50 MB/s = 20 s; enumeration, open/stat,
create and per-file durability cost average 1.5 ms/file = 30 s; index,
directory fsync and rename = 5 s. Subtotal 55 s; 20% allowance gives 66 s,
rounded up to a 75 s budget. This is a derived target, not a measured result or
a guarantee for arbitrary devices: synchronous per-file fsync, cold cache,
small-file latency, encryption or slow provider capture may dominate. Measure
the complete implemented path on the deployment hardware with a reproducible
20,000-file/1 GB fixture, recording file distribution, source/destination,
provider, elapsed wall time and throughput; tune or revise the target if the
assumptions do not hold. Report provider wait/capture separately and also report
total wall time to the operator.

For D roots, F total objects, B total source bytes, C changed file bytes, and S
retained snapshots: each run scans and compares O(F) objects, writes O(C)
bytes, and creates O(F) directory entries/hard links plus an O(F) index, even
when nothing changes. The first run writes O(B) bytes. Current list/dict-based
`scan_files`/`build_manifest` and sorted traversal require O(F) memory (plus
bounded copy buffers); D adds O(D) configuration/provider bookkeeping, not a
separate full data copy per root. Storage is approximately initial B plus bytes
of changed file versions, and O(SF) index/directory/link metadata in the
worst case, plus staging/trash and filesystem allocation overhead. Removed
versions remain until no retained snapshot links them. Retention bounds S only
when readers release locks and pruning succeeds. The number of locks and
publication renames per run stays constant as D grows; I/O and metadata costs
do not. Free-space exhaustion can still abort a run without harming the last
published snapshot.

## Implementation verification

Extend the unittest suite with real temporary trees and subprocesses. Verify
hidden/empty directories, symlinks, unsupported objects and filename
round-tripping; unchanged inode reuse, changed file replacement, deletion and
the documented same-size/same-mtime limitation; index/tree correspondence and
restore independence. Inject disappearance, unreadability, short read, write,
fsync and traversal failures and assert nonzero status, useful diagnostics,
no new published ID and unchanged prior snapshots. Kill a run at each stage
around index write, flush, rename and pruning; restart and verify cleanup and
that every listed snapshot is complete. Use synchronization barriers rather
than sleeps to test two simultaneous writers and a long shared-lock reader
against publication and pruning. Test `keep=1`, lock timeouts, interrupted
trash deletion, configuration errors, source-view capture and provider cleanup.
Run the existing suite too, and measure the stated initial-backup fixture on
the actual target filesystem.

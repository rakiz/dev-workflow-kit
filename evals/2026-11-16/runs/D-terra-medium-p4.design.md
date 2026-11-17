# backupctl design

## Contract and scope

`backupctl run --config CONFIG` takes one **run-wide** snapshot of all N
configured source directories. A snapshot is either published in its entirety
or not published at all. The scheduler and an interactive invocation use the
same command, locking, diagnostics and exit codes. A successful run exits 0;
a failed capture or publication exits nonzero and reports the failing source,
relative path, operation and error. Retention errors are also nonzero but
report explicitly if the new snapshot was already committed.

The contract depends on a local POSIX filesystem with working advisory locks,
atomic same-filesystem directory rename, hard links and fsync. The backup root
must be on one filesystem and outside every source. Reject unsupported
filesystems, overlapping source/root paths, duplicate source IDs and invalid
configuration. Protect the backup root from modification by non-backupctl
writers. Snapshot data and manifests are immutable after publication;
restores copy files rather than modifying or linking them for later writes.
Hard-link reuse relies on this immutability.

A true common point in time cannot be obtained by walking arbitrary live
directories. Each configured source therefore has a cooperative producer lock:
every producer takes its lock exclusively before any change, including rename,
deletion or metadata change. Backup takes all distinct producer locks shared in
a globally sorted order and holds them through capture and validation. The
point in time is when the last shared lock is acquired; all source trees are
then stable until released. Backups without this producer contract must fail
configuration validation, not silently claim point-in-time consistency. A
filesystem snapshot could provide the same stable-view contract in a future
adapter. In either case noncooperating writers and storage corruption are outside
the guarantee; detection of an unexpected change during capture fails the run.
Hold producer locks no longer than capture needs, not during retention.

Files, including dotfiles and files under dot directories, empty directories,
regular-file contents, permission bits and mtimes, and symlinks as links with
their literal targets are preserved. Do not follow symlinks during scan, copy,
validation or deletion. Special files are rejected with a path-specific error;
ownership, ACLs, xattrs and sparse layout are not promised. Filenames are stored
losslessly using a reversible filesystem-byte encoding, with validated relative
components. Each source gets a separate namespace, even if names overlap.

## Layout and reader protocol

```
backup-root/
  .writer.lock                 # stable lock inode, never unlinked
  .readers.lock                # stable lock inode, never unlinked
  .staging/<unique-id>/        # incomplete, never a snapshot
  .trash/<unique-id>/          # detached snapshots awaiting removal
  snap-00000000000000000001/
    manifest.json
    trees/<source-id>/...
```

Only names directly under the root beginning `snap-` are published snapshots.
Under the writer lock, choose the next fixed-width numeric sequence above the
largest published sequence; reject overflow. The newest published snapshot is
always retained, so pruning cannot cause sequence reuse. Fixed width makes
lexicographic order creation order, including across clock changes. No mutable
`latest` pointer is necessary. A reader never has to check whether a visible
snapshot's producing run finished: all `snap-` directories are complete on
publication.

Readers **must** hold a shared advisory lock on `.readers.lock` from before
listing/choosing a snapshot until their last access finishes. Provide
`backupctl read -- COMMAND ...`, which acquires that lock then executes the
restore or an interactive shell with the lock FD inherited; `backupctl list`
uses the same lock. Separate restore tooling can instead implement the same
lock protocol. A reader opening a file or browsing without a pin cannot be
protected from deletion by portable filesystem operations; if not all readers
can be made to use the protocol, disable physical pruning. This is a deployment
precondition, including for human readers, not a check of run completion.
Access controls and documentation must keep uncoordinated readers away from
prunable snapshots. Lock acquisition failures/timeouts are reported, not
treated as success.

## Capture and publication

1. Acquire exclusive `.writer.lock` for the whole run, serializing scheduler
   and manual runs. OS locks are released on process death; never infer lock
   ownership from a PID file. Initialize root and lock files safely once.
   Remove abandoned `.staging` trees and finish deleting detached `.trash`
   trees left by an earlier owner. Neither namespace is listed as snapshots.
2. Select the newest published snapshot as the incremental base. Validate its
   manifest and tree as described below; never base reuse on an unvalidated
   index. Acquire producer locks and create a unique staging directory on the
   backup filesystem.
3. Enumerate all trees with explicit error handling, recording directories,
   regular files and symlink targets. Hash **every regular source file** with
   SHA-256, streaming in fixed-size chunks, and record its size, nanosecond
   mtime, mode and digest. Check file descriptor identity and state before and
   after hashing; fail on unexpected change. Compare file states against the
   prior snapshot, source by source. An equal state is unchanged: hard-link the
   corresponding immutable prior file into staging. If hard-linking fails due
   to a link-count limit, copy it instead; other link errors fail the run.
   Changed/new files are streamed to newly created staging files, hashing the
   copied bytes and verifying the expected digest and descriptor state. Recreate
   symlinks and all directories, applying directory metadata after population.
   Deleted source paths simply do not appear in the new tree. No operation ever
   writes through a hard link. Disk-full, enumeration, stat, open, read, write,
   metadata or verification failures abort the whole run.
4. Build `manifest.json` from the actual successfully constructed tree, not
   from the initial listing alone. It records a version, source IDs, directory
   and link metadata, and regular-file states and digests. Validate safe paths,
   unique entries, tree/index membership in both directions, types, sizes,
   metadata and digests before commit. For reused files, a previously validated
   immutable base plus matching source digest permits trusting their recorded
   digest; newly copied files are checked while streaming. Fsync new file
   contents and metadata, the completed manifest, and staging directories
   bottom-up. Rename the staging directory atomically to the new `snap-...`
   name and fsync both `.staging` and the backup root. This rename is the
   visibility/commit point.
   Do not report success until root fsync completes. If it fails after rename,
   report an indeterminate durability result and the snapshot name; on the
   next run discover it from the root, never overwrite it.
5. Release producer locks. Apply retention under the protocol below; report
   snapshot name, counts and bytes copied/reused, and any cleanup problems.

If a source file disappears between listing and open, becomes unreadable, or
changes during capture, **abort the entire snapshot**, remove or leave only
hidden staging for next-run cleanup, and report a nonzero result with the path.
There is no partial success, stale-file substitution, or scheduler-specific
exception. Any older published snapshots remain usable. A crash before rename
leaves no visible snapshot; a crash after rename leaves a complete tree and
manifest. After a crash around durability barriers, recovery accepts whichever
complete published directory the filesystem actually retains.

### Change detection accuracy

Comparison is per regular file, using size, nanosecond mtime, mode and the
SHA-256 of all bytes, not just timestamps. It avoids copying unchanged bytes,
but still reads and hashes every source file on every run. Unlike a size/mtime
shortcut, a same-size edit with restored mtime is detected unless it produces a
SHA-256 collision. Cryptographic collisions are the stated residual risk; a
requirement for mathematical byte equality would need byte comparison against
the base as well. Directory and symlink metadata/targets are compared and
recreated independently. Quiescence is still necessary: hashing alone does not
make an actively changing set of files a point-in-time image.

## Index recovery

The manifest is inside the staged directory and is never published separately
from its tree. Write it to a temporary file, fsync, then rename it to
`manifest.json` within staging before the final directory rename. On startup,
discard the entire abandoned staging tree, including any corrupt or
half-written staging index: the tree may itself be incomplete, so it is never
recovered as a snapshot. Log its name and cleanup result.

Validate a candidate published manifest's schema, safe paths, unique entries,
and exact correspondence to the no-follow tree, including hashing its regular
files, before using it. If missing,
malformed or inconsistent, acquire the exclusive reader lock before repair so
no compliant reader sees a replacement in progress. Re-derive an index by
walking that published tree, collecting its actual directories, symlink
targets, regular-file metadata and hashes; do not infer missing data from the
source or a broken index. Write and fsync a replacement temporary manifest,
atomically rename it over the old one, fsync the snapshot directory, and report
the snapshot name and reason for repair. Revalidate it before use. Source file
metadata must be applied to the snapshot during capture so rebuilt file states
are meaningful for later comparison. The index is the sole exception to
snapshot metadata immutability, and is replaced atomically while readers are
excluded; tree contents never change. If the tree cannot be completely read or
validated, report failure and do not use it as an incremental base or prune any
snapshot. A tree-only reconstruction cannot prove a previously corrupted tree
still matches its original capture; it represents the tree actually present.
Process interruption alone cannot produce a corrupt published index under the
publication protocol, but this repair handles pre-existing corruption. Readers
of externally corrupted snapshots must not assume integrity until repaired.

## Retention and concurrent reads

Default retention is the seven newest complete run-wide snapshots; configure an
integer `keep >= 1`. Prune only after a new successful, validated publication.
While holding `.writer.lock`, take `.readers.lock` exclusively, waiting or
timing out with an explicit retention error. This waits for all pinned readers
and prevents new ones from selecting a victim. Keep the newest `keep` according
to sequence and atomically rename each older victim into `.trash` on the same
filesystem. Fsync both affected parent directories. Release the reader lock;
then recursively remove the detached trees without following symlinks. No new
reader can select a detached name, and no existing pinned reader was using it
at detach time. A crash midway leaves either a complete visible snapshot or a
hidden trash tree; cleanup is retried next run. Refuse pruning on invalid keep,
unvalidated newest snapshot, lock failure or root/rename errors. Always retain
at least the newest valid snapshot, even if cleanup or the next capture fails.
Retained snapshots may share inodes, so unlinking old ones cannot remove a
still-linked file from a retained snapshot.

## Grounding in the existing code

The implementation belongs alongside the existing modules, extracting and
extending their primitives rather than running their CLIs as opaque commands:

* `synccli.py:10–19` `scan_files` supplies the sorted relative-path scanning
  structure. Extend it (or extract a configurable shared walker used by it)
  to include hidden directories and empty directories, use `lstat`/no-follow,
  preserve links, and surface `os.walk`/scandir errors. Its present hidden-dir
  filter and silent walk errors are incompatible with complete snapshots.
* `synccli.py:22–33` `file_state` and `build_manifest` provide the state and
  manifest construction pattern. Extend the shared primitives with ns mtime,
  mode, types and streamed hashes, plus per-entry errors. The current
  size/float-mtime state alone misses same-size timestamp-preserving edits;
  `build_manifest` currently aborts on a stat error and does not describe empty
  directories. Keep source and snapshot manifests distinct from the existing
  `.sync_manifest.json` format.
* `synccli.py:36–42` `changed_files` compares dictionaries of per-path states;
  call it on the extended regular-file state dictionaries for each source.
  Handle deletions, directories and symlinks separately; this function returns
  only new/changed paths, not removals.
* `synccli.py:62–70` `copy_file` is the copying starting point, but must be
  refactored to stream bounded chunks, return/raise errors, hash and verify,
  set metadata and fsync. Its current whole-file read can use file-size memory,
  and its swallowed `OSError` can leave a partial destination. Do not call it
  unchanged. `synccli.py:72–87` `sync` writes a source-derived manifest even
  after such a failure and updates a live destination in place; replace that
  orchestration for backupctl with staged publication above. Preserve the
  existing sync CLI's documented behavior and tests via compatible wrappers.
* `snaputil.py:8–20` `list_snapshots` supplies listing and sorting for the
  direct-child `snap-` namespace. Validate the stricter fixed-width names and
  reject symlinks/non-directories in the backupctl wrapper: the helper checks
  only the prefix and `is_dir()` follows symlinks. `snaputil.py:23–36`
  `prune_snapshots` supplies the oldest-first keep selection, but must be
  refactored with a lock-protected detach callback; its direct `rmtree` is not
  safe for readers and `keep=0` can delete everything. Shared callers retain
  their existing behavior through a wrapper, while backupctl requires keep >= 1.
* `snaputil.py:39–51` `snapshot_disk_usage` can report **logical** bytes per
  snapshot, but counts hard-linked files in each snapshot; do not sum it as
  physical disk use. `snaputil.py:54–63` `safe_snapshot_path` is not safe for
  absolute or `..` paths despite its docstring: normalization alone does not
  confine a join. Replace/extend it with component validation and dirfd-based
  no-follow traversal; use that for stored paths. `is_stale` at 66–73 uses
  `<=` despite its docstring's equality claim, and is not used for retention.

## Performance and scaling budget

Initial-backup target: **at most 132 seconds** for 1 GiB of regular-file data,
20,000 files, and at most 2,000 directories, under the following explicit
environment assumptions. This is an engineering budget, not a measured result
or a promise on slower disks. Assume sequential effective read and write rates
of at least 100 MiB/s each, hashing at least 200 MiB/s, 120,000 metadata
operations at 2,000 operations/s, 20,000 file fsyncs at 1 ms each, and 10 s
for directory/manifest fsync and fixed overhead. Conservatively add rather than
overlap: two reads (source hashing and changed-file copy) and one write cost
`3 * 1024 / 100 = 30.72 s`; hashing both reads costs
`2 * 1024 / 200 = 10.24 s`; metadata costs `120000 / 2000 = 60 s`; file fsyncs
cost 20 s; fixed overhead costs 10 s. Total **130.96 s**, rounded up to the
**132 s** budget. Directory count and link workload above
the assumptions, slower fsync, contention, reader-lock waits and producer-lock
waits are outside this capture budget. Measure on deployment hardware and
report actual elapsed time and throughput; do not assert this derivation is a
benchmark. Storage can have shared read/write bandwidth, hence the additive
I/O accounting. Index validation of the first staging tree uses hashes already
computed during the copy, not a third full data read.

Let N be source count, F total file/link entries, D directories, B regular-file
bytes, P the total encoded path bytes, and C bytes in new/changed files. Each
run enumerates O(F + D) entries, sorts O(F log F) paths, hashes B bytes, copies
at most C bytes (plus any hard-link-limit fallbacks), and makes O(F + D)
metadata/link operations. Base validation also reads and hashes every base
regular file, at most B_base bytes, and walks its F_base + D_base entries.
Manifest dictionaries and sorted paths require
O(F + D + P) memory, plus a fixed 1 MiB streaming buffer per serial worker;
N source configurations and lock handles add O(N); holding both manifests may
add O(F_base + D_base + P_base). Use one serial worker, so worker buffers do not
grow with N. Repair may require an additional B_base-byte read. Lock waits
have no finite elapsed-time bound unless configured timeouts are applied.

With K retained snapshots, physical regular-file data is at most the sum of
the B values for those K snapshots, plus one in-progress tree of at most the
current B; hard links typically reduce that to the initial data plus distinct
changed file versions. Metadata and manifests cost O(sum(F + D + P)) across
retained snapshots plus one staging tree. Trash after failed cleanup can add
the full size of each detached snapshot; repeated cleanup failure has no finite
disk bound and must be surfaced, not hidden. Retention is count-based, not a
disk quota; free-space exhaustion aborts capture without deleting the last
usable snapshot.

## Verification plan

Keep `python3 -m unittest` passing for the existing sync behavior. Add focused
backup tests using isolated temporary roots and subprocesses: simultaneous runs;
kill at each staging, manifest, rename and fsync boundary; subsequent cleanup;
manifest corruption/reconstruction and unreadable reconstruction; disappearance
and permission/read/write failures; same-size same-mtime edits; hidden and
empty directories and symlinks; hard-link reuse without mutation; invalid paths;
and retention with a held reader pin, including a killed reader and interrupted
trash cleanup. Assert every visible snapshot's index matches its actual tree,
and an unsuccessful run never replaces the last good one. Exercise the
producer-lock barrier with a concurrent writer and verify the snapshot reflects
one common state. Benchmark the stated initial workload on representative
hardware and record the assumptions and observed time.

# backupctl design

## 1. Contract and scope

`backupctl run --config backup.json` creates one complete generation containing
all N configured source directories. `backupctl list` lists usable generations;
`backupctl inspect ID` reports their indexes and logical sizes. A generation is
either published in full or absent. A failed source does not yield a successful
generation with missing files, nor silently substitute a previous file version.
Scheduler and interactive invocation have identical semantics and exit codes.

Configuration contains an absolute backup root, unique stable source IDs mapped
to absolute source roots, and `keep` (default 7, integer >= 1). Reject duplicate
or overlapping source roots, a backup root within any source (or vice versa),
and source IDs containing separators, `.` or `..`. Configuration changes are
recorded in each generation; reuse is only within the same source ID and root.
A failed run leaves the last successful generation available and does not prune.
An initial run that fails has no successful backup and reports that fact.

The supported platform is a local POSIX filesystem with same-filesystem atomic
directory rename, reliable advisory locks, hard links and file/directory fsync.
All staging, published and trash directories are on that filesystem. Reject
unsupported storage rather than assume network/object-store semantics.
Backup storage is private to the backup account; consumers have read-only access
and must not edit snapshot payloads or run `snaputil`'s standalone prune command.
This design covers process interruption and, where these filesystem durability
primitives hold, power loss. It does not repair arbitrary disk corruption.

### A real point in time requires source coordination

An atomic destination rename alone cannot make a live, changing source tree a
point-in-time image. Each eval producer must acquire an exclusive advisory lock
on a configured, stable lock file **outside** its source before any mutation.
Backup acquires shared locks on all N sources in sorted source-ID order and
holds them from before enumeration until all source reads finish. The instant
the final source lock is acquired is the generation's logical capture time:
all sources remain unchanged throughout capture. Producers spanning multiple
roots acquire their locks in the same order. Initial integration into the evals
workflow is therefore a prerequisite, not an optional optimization.

Backup fails before publication if the lock protocol cannot be established.
For producers that cannot cooperate, an OS filesystem snapshot or stopping the
producers is required before invoking this tool; an ordinary live scan is not
advertised as point-in-time. Disappearance and unreadability are still handled
defensively: an out-of-protocol mutation or I/O error aborts the generation.
Pre/post descriptor metadata checks can detect some violations, not prove that
uncoordinated writers were absent.

## 2. Existing code: reuse and deliberate overrides

The following are exact references in the supplied copy. These are proposed
changes for implementation, not claims that backup support already exists.
`synccli`'s existing entry point and default behavior remain compatible.

| Concern | Existing implementation | backupctl integration |
| --- | --- | --- |
| Enumeration | `synccli.py:10–19`, `scan_files(root)`, returns sorted relative file paths and suppresses descent into dot directories at line 14 | Extend this function with explicit options for hidden directories, strict walk-error handling and directory inventory. Backup enables hidden directories and strict errors. Reuse its walk/relative-path/sort implementation. The current default would silently omit `.results/` and unreadable subtrees, so is insufficient. Inventory empty directories as well as files. |
| Metadata | `synccli.py:22–25`, `file_state(path)` returns size and floating-point `st_mtime` using `os.stat` | Reuse that exact state representation as the source comparison key for regular files. Add no-follow type checks before calling it, and descriptor checks around reads. It neither hashes bytes nor preserves metadata. |
| Manifest construction | `synccli.py:28–33`, `build_manifest(root)` composes enumeration with `file_state` | Refactor it to accept the strict enumeration options and produce the source-state map used by backup. Propagate errors. Keep the existing default return shape; backup stores the map inside its versioned index envelope. |
| Change selection | `synccli.py:36–42`, `changed_files(old_manifest, new_manifest)` compares whole state dictionaries for paths in the new map | Call it on the prior and current **source-state** maps. New or different paths are copied; unchanged paths are hard-linked. Entries only in the old map are absent from the newly built payload. This function does not identify deletions itself. |
| Byte copying | `synccli.py:62–69`, `copy_file(src, dst)` creates parents, reads a whole file into memory, and swallows every `OSError` | Extend this function with an opt-in strict streaming mode: 1 MiB buffer, exclusive temporary destination, propagated errors, byte count and pre/post metadata checks, flush/fsync and rename of completed file. Backup always uses that mode. The unbounded `read()` at line 67 and swallowed failures at lines 68–69 cannot satisfy backup correctness or memory bounds. No backup path uses the legacy silent mode. |
| Run orchestration | `synccli.py:72–87`, `sync()` loads JSON without recovery, copies into a mutable destination, then writes the proposed source manifest directly | Do **not** call `sync()` as the backup transaction. Its line 84 may fail silently yet lines 85–86 still promise that file; it leaves deleted files in the destination and exposes intermediate changes. New backup orchestration composes the reused primitives above inside staging and publishes atomically. |
| Listing | `snaputil.py:8–20`, `list_snapshots(backup_root)` scans immediate directories beginning `snap-` and sorts names | Reuse for candidate discovery and retention order. It does not actually validate its documented date/sequence grammar and follows directory symlinks; wrap with strict name, lstat, commit and index validation before returning usable snapshots. |
| Retention | `snaputil.py:23–36`, `prune_snapshots(backup_root, keep)` selects the oldest prefix and calls `shutil.rmtree` directly | Refactor this helper to allow a validated candidate list and retirement callback while preserving legacy defaults. Backup invokes it only under the deletion lock, with `keep >= 1` and a callback performing atomic retirement, then garbage collection. Never invoke its current direct-deletion behavior on published backup generations. |
| Size | `snaputil.py:39–51`, `snapshot_disk_usage()` sums `os.stat(...).st_size` | Reuse on validated, pinned generations for `inspect` and recovery inventories. Label it **logical bytes including metadata files**, not allocated/deduplicated disk usage: it counts shared hard-link content again for each generation. Do not traverse every payload merely to enforce count-based retention. |
| Paths | `snaputil.py:54–63`, `safe_snapshot_path()` normalizes then joins | Reuse only **after** a strict validation wrapper, and add containment assertions. Contrary to its docstring, `normpath('../../x')` remains escaping and an absolute last component replaces earlier components. Reject absolute paths, empty components, `.`/`..`, NUL, invalid source IDs and symlink ancestors; require normalized paths and containment beneath the expected snapshot. `commonpath` is an additional assertion, not a substitute for no-follow traversal. |
| Age | `snaputil.py:66–73`, `is_stale()` uses `mtime <= ref_epoch`, despite documentation saying equality is not stale | Do not use this for interrupted-run cleanup or retention. Exclusive ownership locks, not directory mtimes, establish whether a run is dead. Retention uses monotonic snapshot names, not directory modification times. If this helper is later used for an age display, correct/document its equality contract first. |

`synccli.collect_stale()` (`synccli.py:45–59`) finds entries marked not fresh;
it is not a snapshot garbage collector or deletion lease protocol and is not
used for retention.

Ordinary files and directories (including hidden and empty directories) are
covered. Symlinks and special files are rejected with an explicit unsupported
entry error in this first version, not followed or omitted. Capture regular
file mode and nanosecond mtime and directory mode/mtime as restore metadata;
apply directory metadata last during restore. Ownership, ACLs, xattrs and sparse
allocation are outside the first-version restore contract. Store original
metadata in the index; do not chmod or utime shared payload inodes. Backup
payloads are private, read-only by convention/permissions established when
first copied, and restore copies bytes to new inodes. Never hard-link sources
to backups or backups to restored live files.

## 3. Storage and indexes

```text
backup-root/
  .writer.lock                 # stable inode, never unlink/recreate
  .readers.lock                # stable inode, shared by readers, exclusive GC
  .catalog.json                # disposable acceleration index
  .staging/<run-uuid>/
  .trash/<unique-retired-id>/
  snap-20261117-150000-00000001/
    COMMIT.json
    index.json
    data/<source-id>/<relative-path>
```

Names use a fixed-width, eight-digit sequence and UTC timestamp. Under the
writer lock choose a timestamp no earlier than the greatest syntactically valid
existing name (including damaged generations) and a sequence greater than its
sequence (advance the timestamp on sequence
overflow). Clock rollback cannot reorder generations. Names are unique; publish
must fail on collision, never replace an existing generation. UUIDs distinguish
staging/trash entries. A new complete namespace is built for every generation.

`index.json` is versioned and records configuration identity, source roots,
capture time, directory inventory, every regular file's relative path, source
comparison state, restore metadata, copied/reused byte counts and origin
generation. Paths are relative to one source, unique and validated. Never put
`.sync_manifest.json` inside `data/`: a source may legitimately have that name.

`COMMIT.json` is a small, versioned descriptor with generation ID, index length
and SHA-256 digest, expected file/directory counts and logical payload bytes.
It is a commit descriptor, not a separately visible success signal: only a
validated directory in the final `snap-*` namespace is published. A COMMIT in
staging is never a snapshot. Index hashing protects index integrity, not payload
bit rot. Content hashing/scrubbing is not part of this metadata-based design.

`.catalog.json` contains generation IDs and descriptor summaries, never mutable
file state that can override a generation's own index. It is only a cache. An
atomic catalog update can lag publication or retirement; every referenced
generation must be independently resolved/validated before use. `list` merges
validated discovery with the cache, so a crash cannot hide a committed snapshot
or make a dangling cache entry usable. Readers never rely solely on the catalog.

## 4. Transaction, concurrency and durability

1. Validate configuration and storage capabilities. Acquire an exclusive POSIX
   `flock` on `.writer.lock` and hold it through recovery, capture, publication
   and retention. A second run waits with a configurable timeout (default 60 s);
   timeout reports busy with exit 3 and changes nothing. Kernel locks disappear
   on process death; a leftover lock file is not a stale lock.
2. Clean abandoned staging trees; only the writer can create them, so under
   this lock none belongs to a live writer. Resume trash removal. Discover and
   validate published generations; recover indexes as described below. Select
   the latest usable generation with matching source identities for reuse.
3. Acquire all source locks. Build strict source manifests and directory
   inventories. Fail on any traversal/stat/type/read error. Create private
   staging, never visible as `snap-*`.
4. For each source call `changed_files` against its previous source-state map.
   Copy changed/new files using strict `copy_file`. Hard-link unchanged files
   from the previous immutable payload, after checking the old entry exists,
   is regular, has the recorded length and belongs to a validated generation.
   No file from an old-only path is linked. A failed link/copy is an error;
   no silent downgrade. Apply all operations only to newly created paths.
5. Construct the index from **successfully materialized** entries, not simply
   the proposed scan. Assert exact equality with the source inventory, counts,
   recorded sizes and directory inventory. If any entry failed, abandon the
   whole staging generation. Source locks can be released once capture and its
   metadata checks finish; serialization and publication use only staging.
6. Write index to a temporary file, fsync it, rename to `index.json`; write and
   fsync COMMIT similarly. Copied payload files were fsynced once by strict
   `copy_file`; do not repeat those flushes. Fsync all newly made payload
   directories bottom-up, and the staging directory. Previously durable linked
   file contents need not be rewritten. A completed file's private temporary
   name must not survive final validation.
7. Atomically rename the staging directory to its unused final name on the
   same filesystem. Fsync both affected parent directories. This is the
   visibility linearization point; durable success is reported only after
   parent fsyncs. A process killed between rename and the success message may
   have committed a usable generation; the next run discovers it by ID.
8. Rebuild/update the catalog using write-temp, fsync, atomic replace, parent
   fsync. A cache-write failure after publication reports a committed backup
   with maintenance warning, not that no snapshot exists. Attempt retention,
   release locks and report a structured summary.

Only one writer builds at a time: scheduler/person collisions trade throughput
for simple, predictable ownership. Readers can run throughout capture and
publication because older generations never change. The writer lock also pins
the reuse base against this tool's pruning. No inode in a published generation
is opened for writing, including an inode shared through a hard link.

### Reader and deletion protocol

Separate restore tooling must acquire a shared `.readers.lock` **before**
listing/resolving a generation and hold it until its final payload read closes.
`list`/`inspect` use the same lock for their shorter operations. The lock file
remains at a stable path/inode and is not inside a deletable snapshot. A human
can pin a browsing shell using a proposed `backupctl pin ID -- command` wrapper
that holds this lock for the command's lifetime. Restore validates the index,
then writes into its own temporary destination before exposing a restored tree.

Retention attempts an exclusive **nonblocking** `.readers.lock`. If any reader
is active, skip all retirement and report `retention_deferred`; publication
still succeeds. After acquiring it, revalidate the retention set, atomically
rename each doomed generation into `.trash`, and fsync both parents. Readers
starting afterward cannot resolve retired names. Rebuild the catalog; release
the reader lock, then recursively delete trash. A crash during recursive
deletion leaves only trash, never a partially deleted visible snapshot.
Existing readers finish before retirement starts; new readers cannot race name
resolution. Open-file semantics alone would not protect a multi-file restore.

An arbitrary unpinned `cp -r` or browsing process cannot be protected from
recursive deletion by POSIX rename alone. The shared reader lease is a required
integration contract. Long-running readers can defer retention indefinitely;
there is deliberately no forced lease expiry while a live reader holds a lock.
Reader death releases the lock automatically.

## 5. Failure and index recovery

All diagnostics include run ID, source ID/path, operation and errno/category.
Exit 0 means a complete snapshot was published without warnings; 1 means no
snapshot was published because capture/configuration failed; 2 means publication
succeeded with a maintenance/recovery warning; 3 means lock timeout. SIGINT
returns 130 after best-effort cleanup; SIGKILL requires no cleanup handler for
correctness. A machine-readable summary states `published_id` or null, counts,
copied/reused bytes, recovery actions and retention outcome.

| State found after interruption/error | Recovery and report |
| --- | --- |
| Partial payload, temporary index, malformed index, or even complete COMMIT under `.staging` | Discard the entire abandoned staging tree under writer lock; never infer completion from its files. Re-enumerate sources on the next attempt. Report removed staging IDs/bytes. Cleanup failure is reported; unique fresh staging allows progress if free space permits. |
| Missing/truncated/invalid-schema `.catalog.json`, dangling or inconsistent catalog entries | Discard cache contents. Use wrapped `list_snapshots` to discover final trees; validate each descriptor/index and derive summaries from them. Rebuild catalog atomically. Report `catalog_rebuilt` and rejected IDs. Do not consult source paths stored in the bad catalog. |
| Corrupt/missing generation index or index digest mismatch in a final tree | Mark that generation unusable for restore/reuse and exclude it from the usable catalog. Inventory its actual payload with strict `scan_files`/`file_state` and, only after no-follow type/path validation, `snapshot_disk_usage` for diagnostic/salvage counts only. Unsafe/unreadable payloads yield an incomplete diagnostic inventory and a warning, never followed links. This cannot recover original source mtimes or prove which absent files once existed; never synthesize a trusted complete index from an arbitrary damaged payload. Fall back to an older validated generation or do a full source capture if none exists. Report `generation_index_corrupt`, retained salvage location and whether a usable backup remains. Do not mutate the published tree in place. |
| Valid index but missing/wrong-type/wrong-length payload entry, or unexpected payload entry | Treat as damaged generation, same exclusion and fallback as above; do not hard-link untrusted content. Structural validation compares the actual tree to the index. Same-size bit rot is outside this check. |
| File vanishes between listing/stat/open, becomes unreadable, short read, source changes during copy, or subtree traversal fails | Abort **all N sources'** generation, remove or leave private staging for recovery, retain all existing usable snapshots, skip pruning, exit 1. An error after an initial successful open is not interpreted as an intentional source deletion. No success manifest includes that path. No scheduler-specific skip behavior. |
| Path absent before the stable source scan begins | It is an ordinary deletion: omitted from the new generation, still present in older generations until retention. |
| Destination full, write/fsync/link/rename error before publication | Abort staging, exit 1, keep old generations. Do not prune first to make space. |
| Error after publication, including catalog rebuild/retirement/trash deletion | Preserve committed generation; report its ID with exit 2. Retry maintenance on a later run. |
| A partially removed `.trash` entry | Continue deletion under writer ownership. It is never listed, restored or used as a baseline. |

For damaged published trees, retain salvage in place and flag it rather than
automatically deleting the only remaining data. They do not count toward `keep`
and can consume extra space until explicit operator removal. A run can still
publish a new full backup. This is a conservative response to damage that the
new atomic write protocol should not itself create.

Validation for a usable generation includes schema/version, safe paths, IDs,
index digest, exact tree membership/types/sizes, and counts. Readers perform
validation before exposing a restore. Discovery can cache results within one
operation because generations are immutable and pinned; no cross-process cache
is trusted over changed descriptor/index metadata. Permission/I/O errors during
validation are reported and exclude that candidate, rather than count it as
usable for deletion decisions.

## 6. Incrementality and retention policy

The reuse unit is one regular file, selected by relative path, byte length and
the floating-point `st_mtime` returned by `synccli.file_state`. There is no block
delta and no cross-path content deduplication. Reuse applies after the first
successful full generation; changed files are copied in full, unchanged files
receive hard links, and each snapshot remains a complete independently readable
directory tree. Deleting a generation unlinks names but does not remove data
still linked by any retained generation.

This comparison can miss a same-length edit with a preserved timestamp, two
edits within filesystem timestamp resolution, or timestamps indistinguishable
after float rounding. It is not content verification. Document this constraint
to eval producers: use ordinary writes that advance mtime; an explicit
`--full` bypasses reuse for deliberate timestamp-preserving rewrites. A metadata
only source edit does not require byte copying: capture its restore metadata
afresh in the new index without modifying the shared payload inode. File
permissions are not part of the existing `file_state` equality test.

After a successful publication retain the newest `keep` **usable complete
generations**, default 7. Order by validated monotonic name. Never pass zero or
a negative number to `prune_snapshots`: the current helper can delete everything
for zero despite its docstring. A failed run never prunes, and a successful run
must validate its newly published generation before enabling retirement. Thus
at least that generation survives each retirement. Corrupt/incomplete candidates
cannot stand in for the protected usable generation. Retention is count-based,
not an age or byte quota. Deletion frees only unreferenced file versions; a free
space check is advisory because it cannot guarantee capacity under other users.

## 7. Initial-backup budget and explicit scaling bounds

### Derived budget (a storage acceptance target, not a benchmark claim)

For an initial 1 GiB (1,073,741,824-byte), 30,000-file, <= 3,000-directory tree,
budget **120 seconds** from uncontended source-lock acquisition to durable
publication on local SSD storage meeting these measured-at-deployment floors:

* effective end-to-end streamed read-plus-write throughput >= 80 MiB/s;
* combined enumeration/stat, open/create/close, index-entry processing and
  final tree validation <= 1.0 ms per regular file, including the amortized
  non-flush directory work for D <= 3,000 (excluding durable flushes);
* average file fsync <= 1.0 ms and directory fsync <= 0.5 ms;
* index serialization/hash/write and fixed commit overhead <= 5 s.

These are explicit hardware/workload assumptions to verify in the deployment
acceptance run; no claim is made that the supplied six tests measure throughput.
For this workload the derivation is:

```text
streaming bytes         1024 MiB / 80 MiB/s             = 12.8 s
file metadata/work      30,000 * 0.001 s                 = 30.0 s
file durability         30,000 * 0.001 s                 = 30.0 s
directory durability    (3,000 + N + 8) * 0.0005 s       ~= 1.506 s (N=3)
index/commit allowance                                  =  5.0 s
subtotal                                                 = 79.306 s
50% scheduling/variance allowance                        = 39.653 s
total                                                    = 118.959 s < 120 s
```

General initial-copy target under the same assumptions is
`1.5 * (B/(80*2^20) + 0.002*F + 0.0005*(D+N+8) + 5)` seconds.
Longer paths/indexes, slower fsync, larger F or D, and slower storage change
this bound; 1 GB alone is not enough to predict runtime. The 120 s target
excludes waiting for locks and deferred trash deletion. Acceptance must report
those separately, as well as enumeration, copy, validation, file/directory
fsync and commit timings. If storage fails these floors, revise the budget or
storage deployment; do not remove durability to make the number pass.

### Scaling model

Let N be source directories; F and D the total current regular files and
directories; B their logical bytes; C changed/new bytes; U unchanged files;
P the sum of encoded current paths and metadata lengths. Let K be usable
published generations, F_j/D_j/P_j their entry counts and index lengths,
F_max/D_max/P_max their maxima. Let Q be total backup-root entries (including
staging/trash/damaged entries), A abandoned-staging/trash entries to delete, and
L the maximum path length. Bounds below include constants or their explicit
variables; they are not claims of constant time independent of tree size.

| Resource/work | Explicit bound |
| --- | --- |
| Workers | Exactly 1 writer/copy worker and at most 1 new in-flight generation per root, independent of N. Reader count R is external; at most R shared reader locks. |
| Source locking | N source lock descriptors plus 2 root lock descriptors, acquired serially; no bound on wait for active producers/readers. Writer's own wait timeout defaults to 60 s. |
| Current scan/change planning | `O(N + D + F log(max(F,2)) + P)` time (existing scanner sorts); `O(N + F + D + P)` memory for inventories/maps. Process sources serially to avoid N worker buffers. |
| Incremental materialization | U hard links plus F-U full-file copies; `O(N + D + F + P + C)` work/bytes processed. First run C=B and U=0. Deletes require no old-file copying. |
| Copy buffer | Exactly one <= 1 MiB payload buffer, plus bounded stream buffering, independent of N and maximum file size. Legacy `copy_file` would instead allocate up to the largest file; strict mode replaces that behavior. |
| Validation/discovery each run | `O(Q log(max(Q,2)) + sum_j(F_j log(max(F_j,2)) + D_j + P_j))` for listing and full structural validation using the sorted scanner; the sum covers all candidate trees, including damaged inventories. Reads index bytes and stats tree entries, not B payload bytes. This explicitly includes old generations, not just the current tree. |
| Peak application memory | `O(N + F + D + P + Q + F_max + D_max + P_max + L + 1 MiB)`; validate one old generation at a time, retaining only summaries and the selected base map. JSON maps and the existing sorted scanner are not constant-memory algorithms. |
| File descriptors | At most `N + 12` owned descriptors with serial directory traversal/copy and explicit directory-handle closing; do not retain one open handle per entry or traversal depth. Reader requires <= 12, excluding its own destination implementation. |
| New payload allocation | At most C newly copied bytes (B on first run), plus file/dir entries, filesystem allocation rounding and `O(P+N+D)` metadata. Hard links allocate directory entries, not U files' content again. |
| Retained logical bytes | `sum_j B_j` for K generations; not physical usage. With K=7 and every B_j <= B_max, <= `7*B_max` payload bytes logically. |
| Retained physical payload | Sum of distinct retained file-version allocations; <= `sum_j B_j` logical content plus per-file block-rounding overhead. During capture add at most C content bytes; with successful pruning and no damage/trash, <= `(keep+1)*B_max` content bytes. |
| Metadata disk | `O(sum_j(P_j + F_j + D_j + N) + P + F + D + N + Q)` including one staging generation; hard-linked snapshots still have one directory entry per file per generation. Filesystem-specific bytes per inode/entry are deployment parameters. |
| Retention/cleanup | Candidate sorting `O(Q log(max(Q,2)))`; retirement O(K) renames in the worst case; deletion `O(A + sum_doomed(F_j+D_j))` unlink/rmdir operations, excluding filesystem-dependent reclamation latency. |
| `inspect` size | `snapshot_disk_usage` performs `O(F_j+D_j)` traversal/stats and sums logical bytes, one chosen generation at a time. |

Under steady-state successful GC, K <= keep after a run. With a continuously
pinned reader or repeated deletion failures there is **no finite disk bound**:
after r deferred successful runs, K <= K_start+r, and added content <=
`sum_(i=1..r) C_i` plus their metadata. Abandoned attempts add their actually
written bytes until cleanup succeeds; damaged salvage adds its measured bytes.
Report these categories separately, alert on free-space/retention backlog, and
fail capture safely when full. Claiming a hard quota while allowing indefinitely
pinned readers would be false. Increasing N from 3 to 30 adds 27 source locks,
27 source index records and corresponding tree work, not 27 parallel workers
or 27 additional copy buffers.

## 8. Implementation and acceptance checks

Implementation order: add strict opt-in modes to the reused `synccli` primitives;
add validated/safe wrappers and retirement callback support to `snaputil`;
implement versioned indexes and atomic staging publication; integrate producer
and restore locks; implement recovery/retention and structured reporting.

Baseline verification in this repository: `python3 -m unittest -v` passed all
6 tests. `test_synccli.py:17–18` checks sorted scanning; lines 22–32 cover
`collect_stale`; lines 42–51 cover one copy and a no-op second sync. They do not
establish atomicity, source consistency, error propagation, retention safety,
path containment, memory bounds or the performance budget.

Required implementation acceptance cases:

* Concurrent scheduler/person runs serialize; a killed owner releases locks.
  Two simultaneously started restores pin old generations while a new one is
  captured/published; retention defers and later succeeds after both exit.
* Kill at every transaction boundary, within payload/index writes, after rename,
  during catalog replacement and halfway through trash deletion. Restart must
  list only complete generations, keep prior usable data and make progress.
* Inject malformed/truncated catalog and per-generation indexes separately.
  Verify exact discard/rebuild/fallback diagnostics and no manufactured trusted
  source state from a damaged tree. Test missing and unexpected payload entries.
* Inject source ENOENT/EACCES after enumeration, traversal failure, short read,
  out-of-protocol mutation and ENOSPC/write/fsync failure. No partial generation
  is published and no previous generation is pruned; both invocation modes agree.
* Include hidden/empty directories, source `.sync_manifest.json`, invalid paths,
  absolute/parent traversal, symlink ancestors and unsupported file types.
* Verify unchanged payload shares inode with its base; changed payload does not;
  removing an older generation preserves the new generation's bytes. Restore
  creates independent inodes. Test ordinary deletion and equal-size/equal-mtime
  edits to demonstrate the documented detection limitation.
* Reject keep <= 0; protect the last usable generation when newer candidates are
  damaged; test clock rollback, name collision and deferred/failed GC.
* Run the specified 1 GiB/30,000-file/3,000-directory workload on target storage,
  record phase timings and peak memory/descriptors, then repeat with 3 and 30
  sources at the same aggregate F/B. Check measured rates against the explicit
  budget assumptions rather than interpreting the existing unit suite as a
  performance benchmark.

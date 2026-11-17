# backupctl design

## 1. Contract and scope

`backupctl run --config backup.json` backs up the entire configured set in one
transaction. A published snapshot contains every configured source, not a
separate independently published generation per source. Stable source IDs, not
directory basenames, identify sources. A configuration contains a backup root,
`sources: [{id, path, lock_path}]`, and `keep` (default 7, minimum 1).
IDs are unique restricted ASCII identifiers; paths are canonical absolute paths.
Reject overlapping sources, sources containing the backup root, and a backup
root containing a source. Changing an ID or its canonical source path forces a
full copy for that source. Record the configuration identity in every snapshot.
Source lock files live outside all source trees and the backup payload, are
provisioned once, and are never unlinked or replaced by either participant.

Target: a single host and a local POSIX filesystem supporting advisory `flock`,
hard links, same-filesystem atomic directory rename, file fsync, and directory
fsync. Verify these capabilities when initializing the root; unsupported
filesystems fail initialization. Network filesystems and object stores need a
different storage backend. The backup root is owned by the backup account and
not writable by source producers or restore users.

Three invariants define success:

1. Only a fully sealed directory is ever given a public `snap-*` name.
2. Its data and authoritative inventory never change after publication. Every
   inventory entry names a successfully materialized file in that same snapshot.
3. Retention cannot remove a snapshot while a cooperating reader holds its lease,
   and never removes the last validated usable snapshot.

### A real point in time requires source coordination

An ordinary walk and copy cannot provide an instantaneous image of a directory
that arbitrary processes are rewriting. Before scanning, take shared locks on
**all** configured source lock files, in canonical lock-path order. Evals writers
must take the corresponding exclusive locks before creating, changing, renaming,
or deleting source entries. They must acquire multiple locks in the same order.
Hold all source locks through materialization and final source checks. The time
the last shared source lock is acquired is the snapshot's logical capture time:
all sources remain unchanged from that instant until copying finishes.

This writer integration is a deployment prerequisite, including for manual
backups. If it cannot be provided, use read-only filesystem snapshots of all
sources under a coordinated freeze; do not advertise a live walk as point-in-time.
Pre/post stat checks detect many violations but cannot prove quiescence or a
cross-file transaction boundary. A rogue writer preserving metadata can evade
them. The source-failure policy below applies even with the lock contract, for
example when permissions change or a device returns an I/O error.

The saved image covers regular-file contents, relative names, empty directories,
and source file modification times. It does not preserve ownership, ACLs,
xattrs, sparse allocation, or source hard-link relationships. Normalize backup
file permissions to read-only and directories to non-writable for readers.
Reject symlinks (including directory symlinks), sockets, devices, and FIFOs rather
than following or silently omitting them. Include hidden files and directories.
Source files named `.sync_manifest.json` are ordinary payload files because all
backup metadata lives outside the payload trees.

## 2. Grounding and the exact reuse boundary

Line references below are to the starting files in this repo. These are proposed
changes for a future implementation; this deliverable changes no Python code.

| Existing code | Reuse and required change |
| --- | --- |
| `synccli.py:10–19`, `scan_files(root)` | Reuse its relative-path walk and sorted result. Add backward-compatible strict options for `include_hidden=True`, `os.walk(onerror=raise_error)`, collecting directories, and rejecting symlinks/non-regular entries using `lstat`. Today line 14 excludes hidden directories, `os.walk` can suppress traversal errors, and symlink files reach the result. Those defaults cannot define a complete backup. Keep existing defaults for synccli callers. |
| `synccli.py:22–25`, `file_state(path)` | Reuse the actual `{size, mtime}` state and explain its limits in section 5. A strict wrapper also captures `lstat` identity/type and nanosecond mtime for race checks and timestamp preservation. Do not silently reinterpret the existing float `mtime` field as nanoseconds. |
| `synccli.py:28–33`, `build_manifest(root)` | Reuse construction of a relative-path-to-state map. Extend it to accept the strict scanner's precollected paths and a strict state callback, retaining its current defaults. The callback propagates errors and records extra identity information separately; the comparison map remains compatible with `file_state`. |
| `synccli.py:36–42`, `changed_files(old_manifest, new_manifest)` | Use unchanged: it compares entire state dictionaries for each path in the new map. Its output is the new/changed worklist. Missing old paths are deliberately absent from the new tree; no deletion of a previous snapshot is needed. |
| `synccli.py:62–69`, `copy_file(src, dst)` | Refactor behind backward-compatible options so backupctl calls a strict streaming variant: exclusive new destination, 1 MiB chunks, SHA-256 while streaming, raised errors, partial-file cleanup, fsync, and explicit success information. The present `fsrc.read()` allocates the whole file, and `except OSError: pass` hides both source and destination failures. Neither behavior is usable for backups. Never call the current function and assume success or infer success from destination existence. |
| `synccli.py:72–87`, `sync(src_root, dst_root, dry_run=False)` | Do **not** call this orchestration. It modifies a destination in place, does not remove deleted source files, loads unchecked JSON at lines 77–79, and writes the source manifest directly at lines 85–86 even after failed copies. Replace this orchestration with section 4's transaction, using the lower-level functions above. |
| `snaputil.py:8–20`, `list_snapshots(backup_root)` | Use as candidate enumeration, then validate names, no-follow directory type, seal, and inventory. Despite the docstring, the implementation only checks `startswith("snap-")` and `is_dir()`; it does not parse timestamps, and `is_dir()` follows symlinks. Its lexical sorting is not a trusted generation order. |
| `snaputil.py:23–36`, `prune_snapshots(backup_root, keep)` | Reuse the deletion loop **only inside private trash**, after live snapshots have been safely detached and reader leases drained. Call `prune_snapshots(trash_root, keep=0)` there. Never call it on the live root: its recursive deletion has no locking or validation, and `keep=0` deletes every entry despite its docstring's newest-snapshot promise. |
| `snaputil.py:39–51`, `snapshot_disk_usage(root, name)` | Reuse for explicitly requested logical-size reporting on a pinned, validated, regular-file-only tree. It sums `st_size`, not allocated or uniquely owned bytes; shared hard links are counted in each snapshot. Do not use it as free-space accounting or perform this extra walk on every run. |
| `snaputil.py:54–63`, `safe_snapshot_path(root, name, rel)` | Call only behind strict validation and containment checks (section 8). Its claimed containment is false: normalization does not remove leading `..`, and an absolute last component overrides the preceding join. Override the promised safety at the wrapper, not by trusting the name. |
| `snaputil.py:66–73`, `is_stale(snapshot_dir, ref_epoch)` | Do not use for eligibility or orphan recovery. It uses `<=`, contrary to the docstring's equality rule, and directory mtime establishes neither process death nor reader inactivity. Retention uses committed generations and leases; staging cleanup uses the exclusive writer lock. |

`collect_stale` (`synccli.py:45–59`) is not a snapshot retention primitive: its
`seen` argument is not updated and it knows nothing about generations or leases.
It is unnecessary for the new orchestration.

Verification performed in this repo copy: `python3 -m unittest -v` passed all
six tests. `test_synccli.py:42–51` checks a simple copy/manifest and a second-run
no-op, not atomicity, missing files, or crash recovery. Direct helper checks
confirmed that `safe_snapshot_path('/backup', 'snap-example', '../../outside')`
returns an escaping path, an absolute relative-path argument returns `/outside`,
`prune_snapshots(root, 0)` removes the sole snapshot, and `is_stale` returns true
at equality. These are implementation facts, not assumptions from docstrings.

## 3. On-disk format and reader protocol

```text
backup-root/
  .writer.lock                 # permanent inode; never unlink/recreate locks
  .catalog.lock
  .leases/<snapshot-id>.lock    # permanent external reader-lock inode
  .staging/<run-uuid>/          # never a public snapshot name
  .trash/snap-<id>/             # detached, no new readers permitted
  .indexes/<id>/<source-id>.json # disposable repaired manifest caches
  catalog.json                 # disposable summary/cache, never authoritative
  snap-YYYYMMDD-HHMMSS-<generation>-<uuid>/
    COMPLETE.json
    inventory.json
    manifests/<source-id>/.sync_manifest.json
    data/<source-id>/...        # independent full namespace for every source
```

The final name remains recognizable to `snaputil.list_snapshots`. Parse the
generation as an integer, not a lexically sorted suffix. Under the writer lock,
choose one greater than the maximum valid generation in public snapshots;
record it in the seal. UUIDs avoid collisions even after recovery. UTC wall time
is descriptive: clock rollback never changes retention order. A restore always
uses the immutable full ID, never a path that can be rebound like `latest`.

`inventory.json` is authoritative: version, generation, source ID/path mapping,
capture time, directory list, and one entry per file containing relative path,
size, saved source mtime (including ns), comparison state, and SHA-256 of bytes.
The per-source `.sync_manifest.json` files are derived `{rel: {size, mtime}}`
caches for `changed_files`, not promises independent of the inventory.
`COMPLETE.json` records version, ID/generation, configuration identity, inventory
digest, file/directory counts, and total logical bytes. Use deterministic JSON
serialization with duplicate-key rejection when loading. A seal is a corruption
check and commit record, not cryptographic protection against a malicious owner.

The default listing validates public names and commit records and derives its
answer from those directories. The catalog can accelerate display but cannot
make an unsealed directory readable. A directory without a valid seal is never
a snapshot. Full content scrubbing is separate from quick listing; publishing
has already checked the complete inventory, and interrupted writers cannot
modify committed trees.

### Leases are part of the restore interface

Provide a small reader API and `backupctl read SNAPSHOT -- COMMAND ...` wrapper:

1. Take `.catalog.lock` shared, select/validate an existing public ID, then take
   that ID's external lease shared while still holding the catalog lock.
2. Release the catalog lock; hold the lease for the entire read/restore, including
   all future file opens. Release it only after the consumer finishes. A wrapper
   must keep the lock alive in the consumer if the wrapper dies (inherited lock
   fd with an explicit lifetime contract), rather than leaving an unlocked child.
3. The restore reads the authoritative inventory, and verifies file sizes/hashes
   as it restores. It never uses an index from another snapshot. Restore-target
   transactional replacement belongs to the separate restore tool.

This permits a restore of A while backup B is built and published. No reader
needs to ask whether a publicly named snapshot's run is finished. Humans doing
long reads should use the same wrapper. Arbitrary readers bypassing leases
cannot be protected from recursive deletion: on POSIX an open directory does
not pin all descendants against unlink. Finite retention safe for such readers
is impossible without a filesystem-level snapshot/reference facility. Supporting
the lease protocol in the separate restore tooling is therefore mandatory, not
an optional performance optimization. Read-only permissions also prevent a
restore from accidentally modifying shared backup inodes.

## 4. Run transaction and crash boundaries

One worker per backup root; no per-source copy parallelism initially. Two
invocations may overlap as processes, but the second waits on `.writer.lock`
exclusive. Kernel locks release on process death; a PID file is not a lock.
Use a 30-second writer-lock timeout and report `busy` on expiry. Take all source
locks with a separate 30-second total deadline. Schedule and manual invocation
use the same flags/defaults and failure semantics.

Lock ordering: writer lock, source locks in canonical order, then short catalog
lock sections, then snapshot leases. Readers take catalog then lease only.
Pruning attempts exclusive leases nonblocking, so it never waits on a restore
while holding the catalog lock. Never upgrade a reader lease in place.

1. **Recover.** With the writer lock held, remove abandoned `.staging` trees and
   finish trash cleanup. No other conforming writer can own a stage now. Validate
   public commit records; rebuild disposable indexes as specified in section 6.
   Establish the newest usable predecessor for this configured source set.
2. **Capture.** Acquire all source locks, check source identity/configuration,
   and create a private stage on the backup filesystem. Scan strictly, including
   empty directories; build each source manifest through the extensions above.
   An inaccessible source root or any traversal/stat error is a run failure.
3. **Materialize, source by source.** Compare against that source's validated
   predecessor manifest using `changed_files`. For unchanged files create a
   hard link from the committed predecessor into the stage. For changed/new
   files use strict streaming `copy_file` into an exclusively created new file,
   hashing as it goes. Create directories even when empty. Set the saved mtime
   and normalized permissions only on newly copied inodes, then fsync them.
   Never chmod, truncate, utime, or copy over a hard-linked inode. A changed file
   always gets a new inode. The stage is a new namespace, so source deletions
   naturally disappear from this generation while predecessors stay intact.
4. **Validate.** Check source identity/state before and after each copy and
   source namespace/state again before sealing. Verify actual byte counts and
   destination states; for reused files carry the predecessor's trusted hash.
   Check inventory and payload path sets match exactly (including directories),
   with no unexpected files or partials. Release source locks after these
   checks. Any failure aborts all sources' staged work, not just one source.
5. **Seal privately.** Write manifests and inventory to temporary metadata
   filenames, fsync and rename them. Write `COMPLETE.json` last with the inventory
   digest, fsync it, and fsync directories bottom-up, including the stage root.
   Fsync `.staging` before moving its entry. Metadata errors and ENOSPC abort.
6. **Publish.** Take catalog lock exclusive, create the permanent lease inode,
   and atomically rename stage to its unused final name on the same filesystem.
   Fsync both the backup root and `.staging` parents. Release catalog lock. The
   rename is the visibility linearization point; parent fsync makes it durable.
   Never overwrite an existing final snapshot. New readers see either no new
   snapshot or the entire sealed new one, regardless of catalog-cache state.
7. **Cache and retain.** Atomically replace `catalog.json` via temp/write/fsync/
   rename/parent-fsync, then perform section 7 retention. Return the committed
   ID, captured time, sources, copied/reused/deleted-source counts, bytes, timings,
   and any recovery/retention warnings. Release writer lock.

Interruption before publish leaves only private work; the next writer removes
it. Interruption after rename leaves a complete tree; discovery finds it even
if the catalog was never updated. After a sudden machine/power failure before
parent fsync, the new entry may survive or disappear, but any surviving published
entry has already had its contents durably sealed; previous snapshots survive.
Do not prune until publication's fsyncs complete. A process killed after commit
but before printing a result may have committed; the next `list`/run reports
the discovered ID. No exactly-once claim is made for terminal output.

### Disappearing/unreadable files

Fail closed for the whole run on ENOENT after enumeration, unreadability,
unstable pre/post state, traversal failure, or a copy error. Remove partial
destinations and discard the stage, keeping every old snapshot. Report the
source ID, relative path, phase and errno; exit 1. There is **no** newly published
snapshot containing a missing file or an implicit stale fallback. The next run
rescans from scratch and will omit a file deleted before that scan, or retry a
file that becomes readable. This is the identical noninteractive policy for a
person and scheduler. It sacrifices availability of new backups during source
instability in exchange for an honest complete-image contract. The first run
can therefore fail without producing any usable snapshot; it must say so.

Exit 0 means committed and maintenance successful; 1 means no new commit due
to source/storage/integrity failure; 2 means configuration/usage error; 3 means
lock deadline expired; 4 means a new snapshot committed but recovery or retention
needs attention. Structured output includes `committed: true/false` so automation
never confuses exit 4 with an unsuccessful backup. Nonfatal repaired-index
warnings can accompany exit 0. An unrelated old corrupt snapshot may be excluded
with an explicit warning; corruption of the only usable predecessor requires
a fresh full backup, not trusting its cache.

## 5. Incremental semantics and integrity

The unit of change detection and reuse is a **whole regular file at the same
relative path**, within the same stable source identity. The comparison is
exactly `synccli.file_state`'s byte length and floating-point `st_mtime`, fed to
`synccli.changed_files`. A rename is a deletion plus a new full file. No block
delta, content-addressed cross-source deduplication, or inode-number matching is
used. Hard links share only already backed-up, immutable data, never source data.

This granularity misses same-size edits whose mtime is restored, changes inside
the filesystem's timestamp resolution, and differences hidden by float timestamp
precision. Metadata outside the saved contract is also not a change trigger.
The copy-time SHA-256 protects stored bytes and enables scrubbing; it does not
detect such source edits on the metadata-only fast path. Offer `run --verify`
which hashes every source file and compares with the predecessor's inventory;
only equal hashes can then be reused. That costs reading all source bytes even
when zero bytes are newly stored. Document metadata mode as the default tradeoff,
not as content-perfect change detection. A quiescent source alone does not make
metadata comparison content-perfect between runs.

On hard-link failure (unsupported operation or link-count limit), strictly copy
from the pinned immutable predecessor and verify its recorded hash. Report this
as reuse-with-copy, and include those bytes in I/O/storage estimates. A missing
or invalid predecessor file is not silently repaired from an uncertain source;
reject that predecessor and restart planning as a full backup, or fail this run
if already materializing. Never publish from a partially trusted baseline.

## 6. Index and tree recovery

Do not catch arbitrary JSON errors and continue with unchecked paths. Validate
schema version, duplicate keys, numeric types/ranges, normalized paths, source
identity, counts, and seal/inventory digest. Reject nonfinite mtimes and negative
sizes. Atomic cache replacement is required for every writer.

| Observed state | Recovery and report |
| --- | --- |
| Abandoned stage, with or without a seal or half-written index | Discard the whole stage under writer lock; report run ID and cleanup. Never salvage it as a committed snapshot. If removal fails, keep it private and report maintenance failure; use a different UUID for new work. |
| Missing/truncated/malformed `catalog.json`, or entries naming nonexistent snapshots | Discard the cache; enumerate with `list_snapshots`, validate public seals/inventories, derive generation ordering, totals and newest pointers from those trees, then atomically replace the catalog. Report exactly which cache was rebuilt and the reason. No source copy is necessary solely to repair this cache. |
| Valid committed seal/inventory, but missing/corrupt per-source `.sync_manifest.json` or mismatched cache states | Ignore the cache. Strictly walk that snapshot's actual `data/<id>` tree, check exact directory/file sets, types, sizes, saved mtimes and SHA-256 against the independently sealed inventory. Re-derive `{size, mtime}` with `file_state` from the saved tree; require those states to agree with the inventory. Write a new atomic cache under `.indexes/<snapshot-id>/`, tagged with inventory digest. Do not modify the published tree. Report rederived file count/bytes and cache reason. |
| Interrupted repair or catalog replacement leaves a temp file | Ignore/remove temp files; keep the last valid cache or repeat derivation. No cache temp name is discoverable as a snapshot. |
| Missing/bad seal, invalid inventory digest/schema, missing payload, or tree verification mismatch | Exclude the directory from usable snapshots and incremental baselines. Do not invent missing paths, trust a partial inventory, or reclassify arbitrary tree bytes as a complete snapshot. Report integrity failure and retain evidence. Publish a fresh full backup from sources if possible; otherwise fail with explicit remaining usable snapshot count. |

A killed conforming run cannot corrupt an already published inventory because
it never rewrites one. The last row covers legacy/manual damage and storage
corruption; a mere tree cannot prove what files an invalid authoritative inventory
originally promised. Keep invalid public directories for operator inspection,
outside automatic valid-snapshot retention. Never use an unsealed legacy
sync destination as a trusted baseline.

No cache is authoritative for completeness. A half-written index from an old
run therefore either gets reconstructed from a separately sealed, verified tree
or belongs to discarded/unusable work. Recovery never makes a public directory
partially repaired while a restore is reading it.

## 7. Retention and deletion with active readers

After a durably committed new snapshot, retain the newest `K=keep>=1` usable
generations globally (each includes the configured set). Always protect the
newest usable generation. A removed configuration source ages out with old
generations; it is not immediately erased from history. A failed capture does
not prune old snapshots.

For each older eligible snapshot, take catalog exclusive and attempt its
external lease exclusive **nonblocking**. If busy, skip it and report `pinned`;
the next run or explicit `backupctl prune` retries. Under the catalog lock,
revalidate the candidate and the protected usable set, rename the candidate
into `.trash` on the same filesystem, and fsync both parents. This is the
deletion visibility boundary. Release catalog lock and reclaim with
`snaputil.prune_snapshots(trash_root, keep=0)`. Keep the exclusive lease through
detachment; after detachment no public lookup can acquire a reference, so it
may be released before slow recursive deletion. Retain the external lock inode
to avoid an unlink/recreate split-lock race.

No existing reader is present at detachment (exclusive lease proves that), and
new readers cannot start between validation and detachment (catalog lock).
A reader selecting an already detached ID gets `not found`, never a partial
tree. A crash during recursive deletion affects only trash; the next writer
finishes it with the same helper. A crash around detachment can leave the
candidate public or in trash, but it was outside the protected newest K and
the new snapshot was already durable. Thus no crash path prunes the sole
usable generation. Restore leases can delay reclamation indefinitely; do not
revoke them to meet a disk quota.

If normalized directory permissions prevent recursive removal, restore owner
write permission on **private trash directories only** before calling the
helper. Never chmod payload files: their inodes may still be shared with retained
snapshots. Unlinking files needs writable parent directories, not writable files.
Trash recovery performs this same preparation before retrying deletion. Abandoned
sealed stages need the same directory-only preparation before cleanup.

Before a copy, compare free space with the planned changed-byte requirement
plus metadata and a configurable reserve (default 256 MiB). This is an estimate,
not a reservation: external writers and metadata allocation can consume space.
If the run runs out, abort the stage and keep the last usable snapshot; do not
delete it to make room. Explicit `prune` uses the same keep/lease checks and can
reclaim already eligible generations before retrying. Trash-cleanup failures
are visible and retried, not interpreted as successful space reclamation.

## 8. Path safety and ownership

Validate source IDs, snapshot names and manifest paths before filesystem use.
Reject absolute paths, empty file paths, NUL, `.`/`..` components, and noncanonical
separators/components; parse the complete snapshot name, not just `snap-`.
After validation, reuse `snaputil.safe_snapshot_path` for joining and require
`os.path.commonpath([snapshot_root, candidate]) == snapshot_root`. That check
alone is insufficient against symlinks: use directory-relative no-follow opens
and no-follow type checks, and reject symlinks at every component. Validate root
ownership and no-follow root identity as well. Private trash contains only
directories detached by this writer; validate it before invoking the pruning
helper. Strict scans reject source symlinks rather than copying outside a source.

Only backupctl under the writer lock writes the backup root. Neither restore
nor normal user browsing may change permissions or file bytes. Hard-linked
generations cannot be independently mutable; this is enforced by access rights
and the no-in-place-write rule, not assumed from the name “snapshot.”

## 9. Performance budget with an explicit derivation

Initial reference workload: **1 GiB = 1,073,741,824 payload bytes, 40,000 files,
2,000 directories, and three configured sources in total**, local SSD, warmed
Python process, no lock contention or source mutation. If each of three sources
is 1 GiB, use three times the payload/file/dir terms below. The target is
**120 seconds of active initial-backup time**, including publication durability
but excluding lock wait and deletion of historical generations.

This is a conditional engineering budget, not a throughput measurement of the
unimplemented tool. Its explicit reference-machine service assumptions are:

| Work | Assumed upper service cost / lower throughput | Derived seconds |
| --- | --- | ---: |
| Read payload and write new payload | 100 MiB/s aggregate sequential I/O; count both directions | 2 × 1024 / 100 = 20.48 |
| SHA-256 copied bytes | 250 MiB/s | 1024 / 250 = 4.096 |
| Walk, lstat/state checks, source/destination opens, destination creation, timestamp setting, closes, final validation | 1.2 ms per file in aggregate across these operations | 40,000 × .0012 = 48 |
| Per-file fsync | 0.5 ms each | 20 |
| Directory scan/create overhead | 0.5 ms per directory aggregate | 1 |
| Bottom-up directory fsync | 0.5 ms per directory | 1 |
| All written metadata (inventory, manifests, seal, catalog), at most 100 MiB | 100 MiB/s I/O, plus 250 MiB/s hashing | 1.4 |
| Sorted path comparisons | at most F × ceil(log2 F), 2 microseconds each | 40,000 × 16 × .000002 = 1.28 |
| JSON encoding/decoding and bookkeeping, within metadata envelope | aggregate allowance | 5 |
| Three-source setup, locks without contention, fixed commit fsync/renames | aggregate allowance | 1 |
| **Total serial service budget** | no assumed I/O/hash overlap | **103.256** |

The remaining **16.744 seconds** is margin to the 120-second target. The numeric
rates and service allowances are explicit acceptance conditions, not claims that
the current tiny unit tests measured SSD performance. A slower fsync device
changes the answer materially: 5 ms/file adds 180 seconds, yielding 283.256
seconds before margin. This is why a universal 120-second wall-clock guarantee
would be false. Wait time is at most 30 seconds for the writer lock plus a
separate 30-second source-lock deadline before a busy result; indefinitely
blocked kernel I/O has no finite hard real-time guarantee.

Acceptance implementation work must time a generated fixture with the stated
bytes/files/directories and representative path lengths on the target disk,
including cold-cache and durability costs. Record phase times, actual metadata
bytes and peak RSS; require p95 active time <=120 seconds for the reference
profile or revise the hardware envelope/budget explicitly. Fixture creation
is outside the measured interval. The tests run for this design were correctness
tests only; no fictitious full-backup benchmark is being reported.

For arbitrary inputs, the same serial cost model is:

```text
T_initial <= 2B/R_io + B/R_hash
             + F*(t_file + t_file_fsync)
             + D*(t_dir + t_dir_fsync)
             + sum_i(F_i*ceil(log2(max(F_i, 2))))*t_compare
             + M/R_io + M/R_hash + T_json(M) + N*t_setup + t_commit
```

Here `M` includes all serialized metadata, and the bound is conditional on the
listed service rates. It includes a real term for every fsync and file; bytes
alone do not predict the time for tens of thousands of files. Strict streaming
copy replaces the existing whole-file `read()` so a 1 GiB individual file does
not require a 1 GiB Python allocation.

## 10. Explicit scale and resource bounds

Let N be configured sources, F_i/D_i/B_i their files/directories/bytes,
F=sum F_i, D=sum D_i, B=sum B_i, and C the bytes requiring a new payload copy.
Let U be unchanged files, L the maximum stored path length, M the serialized
metadata bytes for one generation, S the public valid snapshot count, and H the
combined serialized seal/header bytes used during discovery. One worker handles
sources sequentially; no N-worker multiplication is hidden in these bounds.

* **Normal work:** at most two strict source namespace/state passes plus final
  destination validation, O(F+D) metadata operations; sorting costs at most
  sum_i F_i*ceil(log2(max(F_i,2))) path comparisons. Change planning is O(F).
  Metadata-only reuse reads zero unchanged payload bytes and performs U hard
  links. Copying reads C bytes and writes C bytes, plus M metadata bytes. A
  hard-link fallback adds the affected unchanged bytes to C. `--verify` adds B
  source bytes read and B hashed. Reading/validating previous inventories costs
  O(M_previous), not zero. Source count adds N setup/lock operations.
* **Recovery work:** a corrupt catalog costs S header validations plus H bytes
  and sorting O(S log(max(S,2))). Rebuilding an affected source index costs a
  full O(F_i+D_i) saved-tree walk and B_i bytes read/hashed. If every predecessor
  index is corrupt, this becomes O(F+D) and B bytes. Discovery is not independent
  of retained history. Large inventory validation additionally costs its actual
  serialized bytes; no O(1) integrity scan is claimed.
* **Working memory:** release per-source maps before loading the next source.
  Budget at most six F_max path/state/hash records (scanned paths, old/new
  states, change list, old inventory and new validation bookkeeping), three
  D_max directory records, and two 1 MiB streaming buffers. Headers/configuration
  add N configuration records and at most three S snapshot-header records.
  Stream new inventory output per source; do not parse the entire multi-source
  inventory into memory. In byte notation the implementation target is
  `6*F_max*c_file(L) + 3*D_max*c_dir(L) + 2 MiB + N*c_config + 3*S*c_header + c_runtime`,
  where each c is the maximum runtime size of that record type including its
  referenced strings, measured for the chosen Python build. Equivalently memory
  is O(F_max*(L+1)+D_max*(L+1)+N+S), not O(B) or an unspecified “constant.” A
  streaming parser is needed for old inventories to honor this design; plain
  `json.load` of the whole aggregate would violate it. JSON output/repair must
  likewise avoid building duplicate aggregate maps. Reject over-limit paths
  and metadata with explicit diagnostics rather than exhausting memory.
* **Open descriptors:** at most N source-lock descriptors, one writer lock,
  one catalog lock, one predecessor/candidate lease, and twelve transient
  scan/copy/hash/fsync descriptors: <= N+15. Walk one directory at a time and
  do not retain an ancestor-fd stack or one fd per file. Active restores add
  one lease descriptor per pinned snapshot per restore process, plus their own
  copy descriptors; they do not add backup workers.
* **Snapshot namespace and metadata disk:** each generation contains F file
  entries and D directory entries even if C=0, plus O(M) inventory/manifest
  bytes. Hard links save payload, not directory-entry/inode-link work or JSON.
  A successful no-change run therefore still costs O(F+D+M), not O(1).
* **Retained payload:** at an arbitrary moment, an upper bound is the sum of
  logical payload sizes of all public generations, the one stage, and trash.
  Shared hard links can only reduce it. Immediately after a successful sweep,
  `S <= K + P + Q`, where P counts pinned otherwise-expired generations and Q
  counts candidates whose detachment/cleanup failed. During commit-before-sweep
  add one generation. If every generation has at most B_max bytes and M_max
  metadata, and there are T trash trees and one stage, the conservative bound
  is `(K+P+Q+T+2)*(B_max+M_max)` logical bytes plus directory/lock overhead.
  More usefully, ideal payload growth is the sum of unique changed bytes still
  referenced by retained snapshots, not K full physical copies. With no pins,
  failures or trash, the post-sweep bound is K*(B_max+M_max); the next stage can
  add B_max+M_max. No finite bound independent of P/T/Q exists if readers remain
  pinned forever or deletion repeatedly fails. Report that pressure explicitly.
* **Lock-file disk:** permanent snapshot lease files grow by one inode and one
  directory entry per ever-published generation G: O(G), zero payload bytes
  each. This deliberate small unbounded history avoids split-lock races.
  Source locks consume N inodes outside the payload. Live worker count is 1
  regardless of N. Concurrent waiting invocations consume one waiting process
  each until their 30-second deadline; backupctl does not spawn them.

Increasing from three to thirty equal-sized sources multiplies F, D, B and normal
serial service work by ten. The largest per-source map and 2 MiB buffer do not
grow if per-source trees stay the same size, but configuration/lock overhead
grows from 3 to 30 records/descriptors. Retained metadata and payload bounds use
the sum across all sources. These are explicit dependencies, not a promise of
flat total memory or disk usage.

## 11. Implementation and acceptance sequence

1. Add strict scanner/manifest/copy options in `synccli.py` without changing
   existing defaults; keep the six existing tests passing. Add meaningful
   strict-mode tests for hidden/empty directories, special files, raised copy
   errors, bounded-chunk reads and exact manifests.
2. Implement the backupctl format, reader lease API, immutable incremental
   materialization and durable publish state machine. Fault-inject termination
   after every metadata write, fsync and rename; on restart require either the
   old complete set or a complete new generation, never a public partial tree.
3. Exercise two concurrent runs and a restore paused midway through reading an
   expired snapshot. New backup publication must work; pruning must skip that
   reader until its lease ends, then reclaim. Verify hard-linked unchanged
   content, changed-file inode separation, deletion propagation, clock rollback,
   all-source transaction failure and source-file disappearance at each phase.
4. Corrupt/truncate catalog and per-source caches; require the stated reports
   and rederivation. Corrupt the independent inventory or remove payload and
   require exclusion, never fabricated completeness. Test absolute/parent paths,
   symlink components, `keep=0` rejection, and crash halfway through trash removal.
5. Run the stated 1 GiB/40,000-file acceptance profile with durability enabled,
   checking the 120-second conditional budget, phase rates and resource formulas.
   Ship scheduling only after evals writers and the separate restore tooling
   implement their respective source locks and snapshot leases.

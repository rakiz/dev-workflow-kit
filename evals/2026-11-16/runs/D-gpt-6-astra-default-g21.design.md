# backupctl: transactional snapshots of eval result directories

## 1. Decision and guarantees

Implement `backupctl.py` beside `synccli.py` and `snaputil.py`. A successful
run publishes **one snapshot containing all N configured directories**. Each
snapshot is a complete directory tree, not a delta that restore must replay.
Unchanged regular files share storage with the previous snapshot through hard
links; changed files get new inodes. Publication is a same-filesystem directory
rename from a private staging namespace. Published payloads are immutable.

The initial release targets a local POSIX filesystem with working `flock`,
hard links, atomic rename, and file/directory `fsync`. All staging, snapshots,
and trash reside on the same filesystem. Network filesystems and filesystems
without these semantics are rejected at initialization. No remote upload,
compression, or block-level deduplication is included.

The contracts are:

1. Concurrent runs serialize through one backup-root writer lock. Readers may
   read existing snapshots while the writer constructs and publishes a new one.
2. A public snapshot contains every selected file and empty directory, with an
   index describing exactly that payload. A failed source read aborts the whole
   N-directory transaction; it never publishes a silently incomplete snapshot.
3. A crash leaves either a complete published snapshot or private garbage that
   the next writer removes. The root catalog is reconstructible, not the commit
   authority.
4. Retention never removes the last validated snapshot and never removes a
   snapshot while a reader holds its lease.
5. File-content equality, not just modification time, controls reuse. Whole-file
   granularity avoids copying unchanged files, but changing one byte copies the
   entire file.

### Point-in-time source semantics require a source-side barrier

Atomic destination publication alone cannot turn a walk of changing source
directories into a point-in-time image. Checking timestamps before and after a
copy also cannot prove that several independently changing files coexisted.

Require one configured **source coordination lock** for the entire source set,
outside all selected trees. Every eval producer takes this lock exclusively
around mutations; `backupctl` takes it shared before scanning and holds it until
all source reads and stability checks are complete. Acquiring it establishes
the snapshot's logical capture instant across all N directories. It must be the
same lock inode for every producer and backup root covering these sources.
The workflow integration is a deployment prerequisite, not functionality the
existing files already provide. The lock file is permanent and never replaced.

There is no silent fallback to an unlocked walk. Uncooperative external edits
are outside the point-in-time guarantee. Detected disappearance, permission
failure, or mutation aborts the run. An integration test must demonstrate that
the actual eval producers obey the barrier before enabling scheduled backups.
This favors a defensible point-in-time contract over a best-effort image with an
undetectable mixture of source versions.

### Reader contract

Separate restore tooling must acquire a shared root reader lease **before
listing/selecting a snapshot**, revalidate the selection, and hold the lease
through its last read. Provide `open_snapshot()` as a small Python context
manager and `backupctl lease SNAPSHOT -- COMMAND ...` for restore tools and
human inspection. Pass the locked file descriptor to the child so a killed
wrapper cannot release protection while the child continues reading. Every
descendant that reads must retain that descriptor until its last read; detached
readers without it are unsupported. The lease is released when its last holder
closes the descriptor or exits.

An arbitrary process traversing raw paths without a lease cannot be protected
against concurrent recursive deletion by POSIX rename or open-directory file
descriptors. Thus all supported reading, including human inspection during
retention, goes through this protocol. Readers do not check run completion or
poll a ready flag: every exposed `snap-*` directory is already committed.

## 2. Grounding in the files in this copy

The following are actual existing functions and observed behaviors. Proposed
parameters and new orchestration functions below do not exist yet.

| Existing implementation | Reuse and explicit required extension/override |
| --- | --- |
| `synccli.py:10–19`, `scan_files(root)` | Reuse its `os.walk`, relative paths, and sorted traversal. It currently excludes dot-prefixed directories (line 14), includes hidden files, omits empty-directory records, and lets `os.walk` suppress traversal errors. Add opt-in backup traversal options: include hidden directories, return directory entries as well as files, raise on traversal errors, and reject symlinks/special files using `lstat`. Preserve the existing default return shape and behavior for `synccli`. Backup includes hidden content and empty directories. |
| `synccli.py:22–25`, `file_state(path)` | Reuse the stat-to-state helper. Its current comparison state is byte size plus floating-point `st_mtime`; it follows symlinks. Add a backup mode returning integer `size` and `mtime_ns`, with no-follow regular-file validation. Capture device, inode, ctime and size/time separately for before/after stability checks; inode and ctime are not the cross-snapshot equality key. |
| `synccli.py:28–33`, `build_manifest(root)` | Extend this existing scan/state composition to accept the backup traversal/state options and directory records. It already raises if `file_state` fails; retain that fail-closed behavior. Its output is a **candidate inventory**, never the published index until every entry has materialized successfully. |
| `synccli.py:36–42`, `changed_files(old_manifest, new_manifest)` | Reuse unchanged, on maps containing only `{size, mtime_ns}`. It compares whole per-file state dictionaries, returns new/changed paths, and does not return deletions. Hash metadata-equal candidates before reuse. Exclude deleted paths simply by building the new snapshot from the new inventory. Do not compare digest-bearing index entries directly against stat-only entries. |
| `synccli.py:45–59`, `collect_stale(items, seen=None)` | Reuse for deletion reporting: old paths paired with `fresh = path in new_inventory`; it returns absent paths. It is not a filesystem deletion routine or a retention implementation. |
| `synccli.py:62–69`, `copy_file(src, dst)` | Build copying on this helper, with an opt-in strict mode. Today it reads a whole file into RAM, opens the destination with `wb`, catches **all** `OSError` (including destination failures), returns no success indication, and can leave truncated files. Strict mode streams 1 MiB chunks, hashes during copying, opens a fresh destination exclusively/no-follow, handles short writes, propagates errors, returns byte count/digest, and syncs the output before success. It checks the opened source's identity/state against the candidate inventory and after EOF. Cleanup of a failed output belongs to its private stage. Legacy default behavior remains for compatibility. |
| `synccli.py:72–87`, `sync()` | Do **not** call this transaction coordinator on a published snapshot. It updates files in place, never deletes stale destination files, trusts `json.load` without validation, records even silently failed copies, and overwrites `.sync_manifest.json` directly. `backupctl` replaces this orchestration with the transaction below while retaining/extending its scan, state, comparison and copy helpers. |
| `synccli.py:90–99`, `main()` | Keep the existing two-directory sync CLI. Add a separate multi-directory backup CLI with explicit failure/status reporting; the existing unconditional success return does not implement backup outcomes. |
| `snaputil.py:8–20`, `list_snapshots()` | Reuse listing and sorting, but add a strict backup mode. The implementation only checks prefix `snap-` and `entry.is_dir()` (which can follow symlinks); it does **not** validate the documented name grammar, seals, or indexes. Backup mode accepts exact generated names, real directories only, then validates descriptors before use. |
| `snaputil.py:23–36`, `prune_snapshots()` | Extend this existing policy routine, not a second parallel pruning implementation. Preserve its oldest-first, keep-newest selection, but add validated candidates, `keep >= 1`, and a removal callback supplied by backupctl. The callback performs the lease-protected move-to-trash protocol. Today `keep=0` deletes every listed snapshot, negative values are unchecked, and `shutil.rmtree` deletes live public paths without reader coordination. The standalone legacy `snaputil --prune` must refuse a backupctl-managed root; it must not bypass locks. |
| `snaputil.py:39–51`, `snapshot_disk_usage()` | Reuse for on-demand **logical** snapshot-byte reporting after validation. It sums `st_size` recursively, includes index files, follows file symlinks through `stat`, and can raise on disappearing files. Run it under a reader lease on validated regular-file-only snapshots. Hard-linked bytes count in every snapshot; this is not unique allocated disk usage or a space-admission estimate. |
| `snaputil.py:54–63`, `safe_snapshot_path()` | Fix this shared helper before using it for inventory paths: the claimed containment does not exist. `normpath('../escape')` retains `..`, and an absolute `rel_path` overrides the join prefix. Validate names/components, reject absolute and parent-traversal input, verify `commonpath` containment, and use no-follow, directory-fd-relative access for actual filesystem operations. Lexical containment alone does not stop a symlink escape. |
| `snaputil.py:66–73`, `is_stale()` | Its docstring says equality is not stale, but its code uses `<=`. Do not rely on the documented strict boundary. Retention and orphan recovery deliberately do not use directory mtime or this helper: commit order and writer-lock ownership, respectively, establish those decisions. No change to this unused helper is needed for backupctl. |

Implementation should add these reusable modes to the existing modules rather
than copy their bodies into `backupctl.py`. Backup-specific locking, sealing,
configuration, reporting, and index validation are new functionality.

Evidence from this copy: `python3 -m unittest` passed all **6 tests** in
**0.006 s** during design work. `test_synccli.py:17–18` tests sorted paths,
`:22–32` tests stale collection, and `:42–51` tests basic copying, manifest
creation, and a no-op second sync. These tests do not establish crash safety,
copy error handling, helper safety, or a 1 GB performance result.

## 3. Configuration, format, and interfaces

Example configuration:

```json
{
  "version": 1,
  "backup_root": "/backups/evals",
  "source_lock": "/coordination/evals.lock",
  "sources": [
    {"id": "eval-a", "path": "/work/evals/a"},
    {"id": "eval-b", "path": "/work/evals/b"},
    {"id": "eval-c", "path": "/work/evals/c"}
  ],
  "keep": 7,
  "lock_timeout_seconds": 30
}
```

Validate unique stable source IDs (restricted ASCII component names), existing
real source directories, positive retention, and disjoint source/backup/lock
paths. Reject duplicate or nested source roots to avoid ambiguous ownership
and double counting. A source-ID/path mapping change increments the source-set
generation; the first snapshot of a new generation does not reuse old files.
Renamed or removed sources remain recoverable through old snapshots while
those snapshots are retained.

```text
backup_root/
  .backupctl.json                 format marker/root UUID
  .writer.lock                   permanent inode
  .readers.lock                  permanent inode
  .staging/<random-run-id>/       invisible to snapshot listing
  .trash/<retired-snapshot-id>/   interrupted deletions only
  .quarantine/<snapshot-id>/      reported integrity failures
  catalog.json                   derived list of published snapshots
  snap-YYYYMMDD-HHMMSS-<20-digit-sequence>/
    seal.json                    immutable commit descriptor
    indexes/<source-id>.json      validated, atomically repairable inventories
    data/<source-id>/...          immutable regular files and directories
```

Snapshot names sort in commit order. Under the writer lock, choose a UTC
timestamp no earlier than the newest validated name and a sequence greater
than existing committed/retiring sequences. Clock rollback therefore cannot
make a new snapshot look older. Check for collisions and never replace an
existing snapshot directory. A random private run ID avoids staging collisions;
sequence exhaustion is an explicit error.

Each per-source index contains a schema version, source ID, source-set
generation, sorted directory paths, and sorted file records:

```json
{
  "path": "run-123/results.json",
  "size": 4096,
  "sha256": "...",
  "source_state": {"size": 4096, "mtime_ns": 1790000000000000000}
}
```

The seal contains capture/commit timestamps, snapshot identity, source mapping,
file/byte counts, and one content-tree digest per source. A content-tree digest
is SHA-256 over sorted, unambiguously length-prefixed records of directory paths
and file `(path, length, content SHA-256)`, including entry types. It excludes
`source_state`, which is an optimization hint that can be lost during repair.
The tree digest covers empty directories and the precise path set, not only
file bytes. Seal parsing is schema-checked; an unkeyed digest detects accidental
damage, not malicious tampering by the root's owner.

The root catalog lists snapshot identities and descriptor summaries. It is a
cache: listing also checks public directories, so a catalog missing the most
recent rename cannot conceal a committed snapshot. A catalog entry alone never
makes a snapshot exist. `.sync_manifest.json` in a source is ordinary payload;
backup indexes live outside `data/` to avoid reserved-name collisions.

V1 restores names, regular-file bytes, and empty directories. It does not promise
ownership, ACLs, xattrs, original filesystem timestamps/modes, sparse allocation,
or source hard-link topology. Symlinks, devices, sockets and FIFOs cause an
explicit unsupported-entry failure rather than being silently skipped or
followed. The tree namespace and JSON encoding must round-trip filenames;
reject any unrepresentable name explicitly.

Commands: `backupctl init --config FILE`, `backupctl run --config FILE`,
`backupctl list --config FILE`, `backupctl prune --config FILE`, and
`backupctl lease SNAPSHOT --config FILE -- COMMAND ...`. All entry points use
the same validation and locking library. A JSON summary records published ID,
source generation, files/bytes copied and reused, removed source paths, recovery
actions, pruning outcomes, and concrete `(source, path, operation, errno)` errors.

Exit status: `0` success; `1` committed/recovered successfully with a warning
(such as deferred retention or repaired catalog); `2` no commit due to source,
destination, format, or integrity error; `3` lock timeout/capacity blocked by
readers. Configuration errors use `2`. SIGINT uses `130` and best-effort cleanup.
After publication, reporting must say **committed**, even if catalog update,
retention, or shutdown subsequently fails. Scheduler and interactive invocation
have identical semantics and do not prompt or silently downgrade errors.

## 4. Locking and transaction sequence

Use advisory kernel locks, not PID-file expiry. Sleep does not expire a lock;
a dead process releases it. Never unlink/replace lock files. Backup root
permissions prevent other users from changing its namespace or payload inodes.
Readonly file permissions discourage accidental edits, but are not protection
against an owner deliberately chmod'ing and overwriting shared inodes.

Lock order for writers is `.writer.lock` exclusive, then `.readers.lock` when
maintenance needs it. The source barrier is held only for capture and is
released before waiting for an exclusive reader lease. Readers take only
`.readers.lock` shared; eval producers take only the source lock exclusive.
There is no lock cycle. Only **one writer and one file-copy/hash worker per
backup root** are active; excess processes wait in the kernel up to the timeout.

1. **Recover/admit.** Acquire the writer lock. Recover private staging/trash,
   reconcile the catalog, and validate available snapshot descriptors/indexes.
   Repair/quarantine operations require an exclusive reader lease. Enforce the
   retention capacity gate below before creating another stage. If no usable
   baseline exists, perform a full backup; never interpret a bad manifest as
   proof that source files are unchanged.
2. **Freeze and enumerate.** Acquire the shared source barrier. Record the
   capture instant and source generation. For each source in stable ID order,
   use extended `build_manifest`, `scan_files`, and `file_state` to enumerate
   all files/directories strictly. Spill each candidate inventory to a private
   stage planning file and discard it from RAM before scanning the next source.
   Sum F/D/B and estimated metadata, then perform the space check before payload
   copying. Planning files count against the reserve and are removed before
   sealing. Missing source roots, unreadable subtrees, symlinks and unsupported
   entries abort the transaction.
3. **Compare and materialize, one source at a time.** Reload its private candidate
   inventory and load that source's previous validated index. Project the old
   index's known `source_state` records into
   the old comparison map. Call `changed_files`. New/metadata-changed files are
   copied with strict `copy_file`, hashing during their one streaming read.
   For each metadata-equal file, stream-hash the source and check its before/
   after identity and state. If the hash equals the old record, hard-link the
   old payload inode into the stage. Otherwise copy/hash into a fresh inode.
   Unknown comparison state (for example after index repair) forces copying.
   A hard-link failure aborts with the actual error; there is no unreported
   full-copy fallback with different space assumptions.
4. **Build the actual index.** Add a file to the output index only after copy
   or link success and length/digest checks. Create and record empty directories
   too. Compute source deletions with `collect_stale` for the report; never
   unlink the old snapshot's files. Discard each source's in-memory inventories
   after writing its stage index, retaining only per-source summaries.
5. **Validate and seal.** Under the source barrier, perform a second strict
   source namespace/state walk and compare it with the first inventory (which
   can be read back from the stage index). Any difference aborts. This catches
   common barrier violations but does not replace the barrier. Validate the
   stage's exact paths/types/lengths against its output indexes. File digests
   come from verified copy streams or a validated immutable baseline; no second
   full payload read is needed on the normal path. Construct the tree digests
   and seal. Release the source barrier after the last source verification.
6. **Make the stage durable.** Write JSON through unique temporary files,
   flush, `fsync`, and rename to their final stage names. Strict copying has
   already synced new payload files. Sync affected directories bottom-up,
   including hard-link entries, indexes, the seal and stage root. Remove any
   temporary entries before final validation. A seal is written last. Neither
   stage directory names nor staged seals are discovery candidates.
7. **Publish.** Rename the entire stage to its fresh `snap-*` name. This is the
   visibility/commit point for process interruption. Then sync the backup-root
   and staging-parent directories for durability. If durability sync fails
   after rename, report `committed, durability uncertain`, not an uncommitted
   failure. Existing readers need no exclusive lease here: the new directory
   is self-contained and immutable, and old directories are untouched.
8. **Update the derived catalog and retain.** Write a new catalog temp file,
   sync it, atomically replace `catalog.json`, and sync its parent. Attempt
   lease-protected retention, report the outcome, and release the writer lock.

Before publication, any read/write/stat/link/validation failure abandons the
whole stage. Best-effort cleanup runs immediately; the next writer guarantees
another attempt. No retry inside the same capture silently omits a file. A
subsequent run takes a new source view: if a previously failing file is now
absent before enumeration, the new complete snapshot legitimately excludes it.
With no previous snapshot, a failed first run leaves zero snapshots and reports
that fact; it cannot manufacture a usable backup from unreadable input.

### Change-detection granularity

`file_state` today can miss same-size edits with the same floating-point mtime,
including filesystem timestamp rounding or a writer restoring timestamps.
Using integer nanoseconds removes float precision loss but does not solve
preserved timestamps. This design therefore has **no metadata-only fast mode**:
metadata equality permits a hash check, not an automatic hard link.

Content equality uses whole-file length plus SHA-256. Ordinary same-size/
same-mtime edits are detected. A hash collision remains a theoretical missed
edit; permissions/ACL/xattr/time-only edits are outside the promised payload
semantics. Uncooperative mutations that evade before/after checks remain outside
the source-barrier guarantee. An unchanged file is read to establish equality,
but its bytes are not written again. Metadata changes with identical bytes may
cause an unnecessary copy; that is safe and is counted in the copied-byte bound.

Never open a linked payload for writing, chmod it, or update its timestamps.
Set the desired readonly mode on new inodes before they become a baseline.
Restore copies out of snapshots; it must not restore via writable hard links.

## 5. Crash and index recovery

Recovery runs under the writer lock. Readers encountering an invalid index do
not use a partial parse or ignore missing files: they release their shared
lease, request the same recovery routine, and reopen/revalidate afterward.
They never upgrade a held shared lease in place. If recovery cannot complete,
they receive a clear integrity/unavailable error rather than a partial image.

| Observed state | Recovery and report |
| --- | --- |
| Anything in `.staging/`, including complete-looking seals or truncated indexes | With the writer lock, no stage can belong to an active writer. Discard all these stages; do not promote them. Remove stray temporary JSON files. Report abandoned run IDs and reclaimed logical bytes. Age/mtime/PID guesses are unnecessary. |
| Missing, truncated, malformed, schema-invalid, duplicate-key, or stale `catalog.json` | Ignore its entries. Enumerate using strict `list_snapshots`, validate each public snapshot, and derive the catalog from those trees and their descriptors/indexes. Atomically replace the catalog and report `catalog_rebuilt` with the reason and accepted/rejected IDs. Never reconstruct it from the current source directory. |
| Published snapshot with a valid seal and valid per-source index | Check exact payload paths/types/lengths against the index and check the canonical inventory against the seal's tree digest. Accept it. Previously sealed payload hashes are trusted against accidental process interruption; arbitrary latent bit rot requires the full hash verification described below. |
| Published snapshot with a valid seal but corrupt/missing per-source index | Under the exclusive reader lease, walk and hash that source's **snapshot payload**, reconstruct path/size/hash and directory records, and compare the reconstructed tree digest with the independent seal. Only an exact match permits atomically replacing the damaged index, with every `source_state` set to `null`. Report `index_rebuilt`, and force a full copy of that source next run. Do not infer source timestamps from destination timestamps: the existing copy helper does not preserve them. |
| Missing/corrupt seal, mismatching reconstructed digest, missing/extra/truncated payload, unsafe path or unsupported entry | Do not invent a complete snapshot from whatever remains. Under the exclusive reader lease, atomically move it to `.quarantine/`, sync parents, remove its catalog entry, and report the exact failure. Keep the bytes for explicit operator recovery; do not prune quarantined evidence automatically. Choose the newest other validated snapshot as baseline, or take a new full backup. If none is usable, report that there is no usable backup. |
| `.trash/` entry left by a dead deleter | It was removed from discovery only after reader exclusion. Resume recursive deletion under writer ownership and report it. New readers cannot lease trash names. |
| Public rename completed but catalog was not updated | Discover and adopt the complete public tree; the commit is valid independently of the catalog. A rerun may create an additional snapshot, but does not merge with or overwrite it. |

Use one reusable 1 MiB `bytearray` with `readinto`/memoryview for all copy and
hash streams; avoid allocating a second chunk while the first is still live.

Index validation includes schema/version, source identity, integer ranges,
unique normalized paths, duplicate JSON-key rejection, no file/directory prefix
conflicts, no path escaping, counts, and inventory/tree-digest consistency.
Bounds for parsing are derived from the tree's measured entry count and index
size; invalid or unexpectedly large input fails explicitly rather than being
partially accepted. Do not use `json.load` as the sole validation step as
`synccli.sync` currently does.

Repair is the only allowed change to a published snapshot's metadata, and is
serialized against all readers. It changes no payload or committed content
digest. Normal writer crashes cannot produce half a published index because
indexes are completed before directory publication. The stronger repair rules
also handle an inherited damaged index or later accidental metadata damage.

For full verification, hash all payload files and compare with the seal;
mandatory during damaged-index reconstruction and available as an explicit
verification operation. Ordinary startup checks do not reread every old file's
bytes. Disk bit rot, malicious writes and unsupported filesystem durability
behavior are not confused with the process-interruption guarantee. If the seal
itself is lost, neither tree walking nor a valid JSON index proves the original
snapshot was complete, so quarantine is necessary.

`fsync` sequencing extends the process-death protocol to the local filesystem's
documented crash-durability semantics. After a power failure around rename,
recovery accepts only a valid public tree; remaining stages are discarded.
Permanent I/O errors, exhausted space that prevents cleanup, or continuous
reader leases can prevent progress and are reported, not called successful
recovery. A killed process alone requires no manual cleanup.

## 6. Retention and reader-safe reclamation

Default retention is the newest **K = 7 validated committed snapshots** of the
whole source set; configurable integer `K >= 1`. Ordering is the monotonic
commit name, not source mtime, directory mtime or wall-clock age. A valid but
empty configured tree is a usable snapshot; an invalid tree never counts toward
the safety floor.

All pruning holds the writer lock. Use extended `snaputil.prune_snapshots` for
the oldest-first candidate calculation, with the validated list and guarded
removal callback. Under `.readers.lock` **exclusive**, revalidate the keep set
and candidate and ensure at least K validated snapshots remain. Rename one
candidate to `.trash/` and sync both namespace parents. Repair the catalog
before releasing the exclusive lease. Then recursively delete that trash tree,
still under writer ownership, syncing the trash parent when complete. Finish
one deletion before retiring the next candidate.

A reader holds the shared lease for its entire traversal, so exclusion waits
for existing readers; a new reader either sees the old committed directory
before retirement or cannot select it afterward. The coarse root lease pins
all snapshots even when a reader needs only one. That conservative tradeoff
avoids per-snapshot lease files, PID registries, and deletion races for this
small number of roots. Publication does not take the exclusive reader lease.

Reader stalls must not make storage silently unbounded. Allow at most **K + 1
public valid snapshots**. If post-commit pruning times out, return a committed
warning and leave the extra snapshot. At the next run, if the count is already
K + 1 (or greater in an imported root), prune down to K before staging; if reader
exclusion cannot be obtained within 30 seconds, return `3` without copying.
Thus readers can defer deletion but cannot cause arbitrarily many new snapshots.
When they release their leases, the next run resumes automatically.

Ordinary failed captures do not trigger extra post-failure pruning. Admission
pruning may have happened first, but still preserves K validated snapshots.
If there is only one usable snapshot, no pruning path deletes it. Removing a
hard link frees payload blocks only when its final snapshot/stage/trash link is
gone; logical snapshot sizes must not be presented as reclaimed physical bytes.

## 7. Performance budget: explicit derivation

**Target:** initial capture through durable publication within **120 seconds**
for B = 1 GiB = 1,073,741,824 bytes, F = 30,000 regular files and D <= 3,000
directories, on an otherwise idle local SSD meeting the rates below. The bound
covers the actual strict path, including hashing and per-file synchronization;
it is not extrapolated from the six tiny unit tests. Decimal 1 GB is slightly
smaller than this workload.

This is a conditional engineering budget, not a claimed benchmark of an
unimplemented tool. Admission/lock waits, source-producer pause before barrier
acquisition, existing-root recovery/retention, and other processes' I/O are
reported separately. A first backup has no baseline scan or old-snapshot pruning.

Use this conservative additive cost model, with operation categories disjoint:

| Work | Explicit hardware/implementation requirement | Budget |
| --- | --- | ---: |
| Read source and write new payload | Effective aggregate read-plus-write throughput R >= 100 MiB/s, excluding per-file metadata and flush latency | 2B/R = 20.48 s |
| SHA-256 while copying | H >= 250 MiB/s, measured independently; count it additively even though it overlaps I/O | B/H = 4.10 s |
| Enumeration, stats, opens, creates, closes, final namespace check | Combined non-flush allowance <= 0.5 ms per file and <= 1 ms per directory across all passes | 15 + 3 = 18.00 s |
| Durable new-file flush | Average <= 1 ms per file, across these 30,000 files | 30.00 s |
| Bottom-up directory flush | Average <= 1 ms per directory | 3.00 s |
| Sorting, inventory encoding/validation, index/seal writes and flushes, root publication, fixed overhead | <= 10 s for the stated F/D and encoded paths <= 256 bytes on average | 10.00 s |
| **Subtotal** | Sum, rounded upward | **85.6 s** |
| **Margin** | 40% of subtotal for variance | **34.3 s** |
| **Budget** | Rounded sum | **120 s** |

If average durable-file latency is instead 5 ms, that term alone becomes 150 s
and the budget is unattainable on that device. There is no universal 120-second
guarantee for arbitrary disks or arbitrary 1 GB trees (a million tiny files has
a different F). The derived target therefore has falsifiable prerequisites.

Implementation acceptance will generate 30,000 files totaling exactly 1 GiB
with a mix of small result files and larger artifacts and up to 3,000 directories.
Record filesystem/device, cold-versus-warm cache state, F/D/B, byte throughput,
hash rate, metadata time, sync time, publication time and peak RSS. Run three
full captures on fresh backup roots, report each and the maximum; require every
capture <= 120 s on the qualifying target. Also measure no-change and one-file
change runs to confirm links and zero unchanged payload writes. This experiment
is future verification, not a result produced during this design task.

## 8. Scaling and resource bounds

Let source i have F_i files, D_i directories, B_i logical payload bytes and
P_i total encoded path bytes (including directory paths). Define F, D, B, P as
their sums over N. Let S be the public valid snapshot count; managed steady
state has S <= K + 1. Let C_i be bytes actually copied for that source in this
run, including safe but unnecessary metadata-triggered copies; C = sum C_i.
Let U_i be bytes hashed as metadata-equal reuse candidates. Let F_max, D_max,
P_max be the maxima across current and all retained source inventories, including
any being repaired, so a large previous tree followed by mass deletion is
included. Let F*, D*, P*, B*, N* be maximum whole-snapshot quantities over
retained/trash/staged snapshots.
Q is already allocated quarantine storage, measured separately.

* **CPU/metadata work per capture:** scanning/state/validation is O(F + D + N)
  entries, with path processing O(P); no-follow directory-component resolution
  adds O(P) component work when handles are reopened. Existing sorted scans cost
  O(sum_i (F_i + D_i) log(F_i + D_i)) path
  comparisons, with comparison cost proportional to compared path bytes.
  Manifest comparison and stale reporting are O(F_current + F_baseline).
  Digest work is O(C + sum U_i). Each source is processed sequentially, not with
  N workers.
* **Source byte I/O:** first backup reads B once, hashes B once, and writes B.
  Incremental source reads/hashes are C + sum U_i <= 2B. The upper bound covers
  a metadata-equal changed file first hashed then reread for copying. A no-change
  run reads/hashes B, writes **0 payload bytes**, and creates F hard links.
  Destination payload writes are C <= B per run, rather than B unconditionally.
* **Startup validation:** public-tree path/size and index validation costs
  O(sum over s=1..S of (F_s + D_s + P_s + N_s)) plus parsing index bytes; bounded
  by O((K+1)(F* + D* + P* + N*)). Sorting snapshot names costs O(S log S).
  It does not hash all retained payloads on the normal path. Damaged-index/full
  verification reads up to sum_s B_s <= (K+1)B* extra bytes and reports this
  recovery cost separately. Trash/stage cleanup adds one traversal of each
  abandoned tree; quarantined trees are not repeatedly scanned.
* **Working memory:** serialize source inventories one at a time and stream
  their output. Use at most two scan lists plus three maps/lists for old,
  candidate, and materialized state, each with O(F_max + D_max + P_max) storage;
  no whole-file buffer. Peak memory is
  `M_runtime + 1 MiB + O(F_max + D_max + P_max + (K+1)*N*)`.
  The final term holds source-set descriptors/catalog summaries, not every
  snapshot's inventory. Thus memory does grow with the largest source, path
  lengths and source count; it is not claimed constant in N or F. An acceptance
  target for the stated 30,000-file workload is RSS <= 128 MiB; measure rather
  than assuming a portable Python-object byte size.
* **Workers/descriptors:** one writer, one copy/hash worker. At most one source
  file and one destination file are open for payload transfer; allow a total
  process limit of 32 application-managed descriptors for locks, directory-fd
  operations, index and report files. Close/reopen directory handles per entry
  rather than retaining one per tree depth or directory. A reader uses one
  lease fd plus its own restore I/O; R simultaneous readers require R kernel
  shared leases, not a backupctl in-memory registry. Waiting writers do not
  allocate tree inventories.
* **Logical on-disk namespace:** each snapshot stores F file names and D
  directory names, even with hard links. Index storage is O(F + D + P + N).
  Retention metadata and directory entries therefore scale as
  O((K+1)(F* + D* + P* + N*)). A no-change backup is not O(1) work or O(1)
  metadata growth.
* **Payload allocation:** for unchanged source content across K retained
  snapshots, unique payload bytes are B, plus O(K(F+D+P+N)) metadata. For a
  sequence of snapshots without intervening reclamation, unique payload bytes
  are at most B_first + sum C_run; with completely different content each time,
  retained payload is at most S*B*. Recovery completes stage/trash cleanup before
  a new stage is allowed. During capture there are at most K public trees plus
  one stage; after publication/deferred pruning, at most K+1 public trees;
  during normal retirement, at most K public trees plus one trash tree.
  Hence at most (K+1)*B* logical payload bytes are simultaneously reachable from
  these managed namespaces, plus Q from quarantine. Actual allocation includes
  block rounding: with allocation unit a, a conservative non-deduplicated file
  bound is (K+1)*(B* + a*F*) plus filesystem/index/directory metadata and Q.
  Hard links reduce data allocation, not directory-entry counts.
* **Exceptional storage:** repeated independent corruption can grow Q without
  a finite count bound; admission includes Q in `statvfs` free-space accounting
  and blocks new captures before exhausting the reserve. This is explicitly
  outside the ordinary K+1 retention bound and requires operator disposition.
  Imported roots above capacity likewise require successful pruning before a
  new capture. Neither exception is disguised as bounded storage.
* **Space admission:** reserve at least 256 MiB free after projected stage
  payload allocation and estimated metadata. Conservatively use B + a*F for
  new data rather than confusing `snapshot_disk_usage` with marginal allocation.
  Add a configured per-entry metadata allowance verified for the target
  filesystem; fail admission if the estimate or free-space query is unavailable.
  Concurrent unrelated disk users can invalidate estimates, so strict write
  errors still abort safely and old snapshots remain usable.

With N = 3 or N = 30 and equally sized sources, F/D/B/P, elapsed capture work
and full-copy disk demand grow linearly in N (plus the stated sorting cost).
Worker count is exactly one and the payload buffer is exactly 1 MiB. The large
inventory portion of memory depends on the largest source, while configuration
and per-snapshot source summaries grow O((K+1)N). Capturing sources sequentially
reduces memory but extends the source-producer pause by the summed capture
duration; parallel source copying is not assumed in any budget.

## 9. Implementation sequence and acceptance tests

1. Extend the existing helpers with the modes in section 2, preserving legacy
   sync tests. Harden snapshot path handling, naming and prune guards first;
   test the actual helper behavior rather than relying on its docstrings.
2. Add format validation, strict copy/hash results, source barrier integration,
   stage/index/seal construction and durable atomic publication.
3. Add reader leases, recovery/catalog reconstruction, guarded retention and
   capacity admission. Integrate the separate restore tool and human lease CLI.
4. Add process-level fault-injection tests, then the stated scale benchmark.
   Enable scheduling only after producer/reader integrations and these checks.

Required tests beyond the existing six:

* Hidden directories/files, empty directories, multiple source IDs, removed
  paths, unsupported symlinks/FIFOs, and traversal permission errors.
* New/changed files use different inodes; unchanged files share inodes and
  write zero payload bytes. Same-size edits with restored mtime are detected
  by hashing. Updating a later snapshot cannot alter earlier content.
* Disappearance between scan/stat/open, source read errors, mutation during
  copying, destination write/fsync/link failure, short writes and disk-full:
  each leaves the previous snapshot intact, no public new snapshot and a
  truthful error summary. Test failure in the final source after earlier
  sources have completed to prove whole-N atomicity.
* Two independently spawned runs racing through the writer lock; restores
  loop over paths/hashes while staging and publication occur. A producer blocks
  behind the source barrier across all N roots.
* Kill the writer after every transaction boundary and during payload/index/
  catalog writes. A restart exposes either an old or new complete tree,
  automatically cleans private leftovers, and reconciles a commit not yet in
  the catalog. Include SIGKILL, which bypasses exception cleanup.
* Truncated root catalog is re-derived; damaged snapshot index with intact seal
  and payload is rehashed/rebuilt with unknown source state; a missing payload,
  missing seal or mismatching digest is quarantined, never blessed as complete.
* Path attacks: absolute paths, `..`, prefix-lookalike roots, file/directory
  conflicts, symlink components, snapshot-name traversal, duplicate JSON keys
  and malformed fields. Verify containment in actual file operations.
* `keep=0`/negative rejected; `keep=1` preserves the last good snapshot; clock
  rollback preserves commit order; readers block retirement; a killed reader
  releases its lease; K+1 capacity stops repeated writes under a long lease;
  crash after retire-before-rmtree resumes deletion. Kill a lease wrapper while
  its child is reading and verify continued protection. Test hard-link accounting
  separately from logical size reporting; retention must not call `is_stale`.
* Run the 1 GiB/30,000-file benchmark with the complete durability protocol,
  record all measured terms from section 7, and exercise N=3 then N=30 with
  controlled totals to distinguish N overhead from file/byte scaling.

This deliverable specifies the implementation; it does not claim these new
APIs, crash tests, integration changes, or performance measurements already
exist. The only verification executed during design was the existing six-test
suite, and all source references above refer to the current files in this copy.

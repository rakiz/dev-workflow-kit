# Design: `backupctl` (D1)

## 1. Contract and guarantees

`backupctl` will be a Python 3 command-line program, implemented alongside
`synccli.py`, for backing up a configured list of source-directory IDs into one
backup root. The normal invocation is:

```
backupctl run --config backupctl.json --backup-root /backups/evals
```

Scheduler and interactive invocations execute exactly the same code and produce
the same machine-readable run report.

The guarantees are:

1. **Publication is all-or-nothing.** A new snapshot is assembled under a
   private staging name. Data files, manifests, and their containing
   directories are durable before a valid `COMMITTED` record and the final
   snapshot name are published. The global index is replaced atomically
   afterwards. No live snapshot is ever copied into in place.
2. **A published manifest exactly describes its payload.** A failed, vanished,
   or unstable source file is omitted from that manifest; it is never silently
   represented by an older version. Such a snapshot is a valid, restorable
   image with status `degraded`, and its omissions are explicit.
3. **Committed payloads are immutable.** A later run hard-links unchanged
   content but never writes through an old link. Restores may not modify the
   backup root.
4. **There is at most one writer per backup root.** Per-snapshot shared Locks
   protect readers; prune requires the corresponding exclusive Lock.
5. **At least one valid, restorable snapshot is retained.** Retention never
   removes the newest valid snapshot, even when a requested retention count is
   invalid; the configuration requires `keep >= 1`.

A snapshot has file-level source consistency, not a cross-file transactional
view of a live tree. A copied file is checked before and after its copy. Two
files that change as part of one application transaction can consequently be
captured at different instants. Capturing a truly atomic live-filesystem view
would require an operating-system snapshot facility, which is deliberately not
assumed. `started_at` and `finished_at` in the report delimit that capture
window.

The supported storage platform is a local POSIX filesystem supporting atomic
same-filesystem `rename`, hard links, `fsync`, and `fcntl.flock`. All paths for
one backup root, including staging and trash, are on that one filesystem.
Source directories may be on other filesystems because only backup-root files
are hard-linked. Network filesystems without those guarantees are unsupported.
Restoration tooling must use the read-lease protocol in section 6.

Symlinks and other non-regular source entries are not followed. Hidden files
and hidden directories that are part of a configured source **are** included.
Empty directories are recorded in the per-directory manifest. The backup root
must be disjoint from every source root, so it cannot recursively back itself
up.

## 2. How this builds on the existing code

The implementation will reuse and, where stated, correct the existing helpers
rather than introduce a separate synchronization algorithm.

| Existing artifact | Use in `backupctl` | Required difference from current behavior |
| --- | --- | --- |
| `synccli.py:10-19`, `scan_files(root)` | Retain its deterministic `os.walk`, relative-path generation, and sorted output as the basis of source scanning. `TestScanFiles` at `test_synccli.py:17-18` fixes the path ordering behavior. | The current helper drops every directory whose name starts with `.` (line 14), cannot report `os.walk` errors, and returns no empty-directory list. `backupctl` will use a shared, extended scanner with `include_hidden=True`, an `onerror` callback, directory records, and `lstat`-based regular-file checks. The old function remains a compatibility wrapper for `synccli` callers. |
| `synccli.py:22-25`, `file_state(path)` | This is the source of the file-level `(size, modification-time)` change key. | Use `st_mtime_ns`, not the float `st_mtime`, and obtain the state with `os.stat(..., follow_symlinks=False)`. Missing files and stat errors become structured skip records instead of aborting a whole scan. |
| `synccli.py:28-33`, `build_manifest(root)` | Keep its model of one dictionary keyed by relative source path and build the new manifest from the sorted scan. | Manifest entries are added only after publication-safe copy or link succeeds. The current function stats every listed file without error handling and its result is later trusted even if copying failed. The new manifest also has a format version and an empty-directory list. |
| `synccli.py:36-42`, `changed_files(old, new)` | Use this function directly for the per-file new/changed set: its exact dictionary-state comparison is the desired fast path. | It intentionally does not identify deletions. Paths in `old - new` are handled as deletions and are neither copied nor linked. Interpreting an empty result still requires the path-safety and previous-payload checks below. |
| `synccli.py:62-69`, `copy_file(src, dst)` | Reuse its creation of missing destination parents as part of the staging-copy helper. | Do **not** use its current body unchanged. `fsrc.read()` makes memory proportional to one file's size, direct writes can expose a partial destination, and `except OSError: pass` hides all failures after possibly truncating/creating output. Replace the body used by backups with 1 MiB streaming, a staging temporary file, source identity/stat verification, close/error checks, `fsync`, and `os.replace`. Errors propagate to the run's skip handling and the temporary file is removed. |
| `synccli.py:72-87`, `sync(src, dst, ...)` | Its three phases -- old manifest, changed set, then copy/new manifest -- are the basis of the per-source pipeline. | Do not invoke `sync` for snapshots. It writes directly into a live destination, writes the source manifest even when `copy_file` skipped a file, and writes JSON directly to the final path. That can expose mixed data or truncate the index. `backupctl` stages a fresh tree and publishes only after all payloads and manifests agree. |
| `snaputil.py:8-20`, `list_snapshots(root)` | Use this as the backup-root enumeration primitive. | Add a strict filename/UUID check and require valid `COMMITTED`, no `RETIRING`/`INVALID`, and index agreement. A name merely beginning with `snap-` is not enough. The helper's lexical result is re-sorted by the root-wide sequence stored in metadata; timestamps do not define commit order. |
| `snaputil.py:23-36`, `prune_snapshots(root, keep)` | Retain its oldest-first candidate calculation and oldest-first deletion report in the retention layer. | Do not call the current deletion loop as-is: it has no reader locking or crash protocol and `keep=0` deletes the newest snapshot despite its docstring. Actual deletion follows section 7. |
| `snaputil.py:39-51`, `snapshot_disk_usage(root, name)` | Use under a shared read lease for per-snapshot **logical-byte** reports. | This sum counts each hard link separately and is not physical allocation. Physical unique-payload accounting is reported separately. |
| `snaputil.py:54-63`, `safe_snapshot_path(root, name, rel)` | Keep one common helper for resolving manifest paths in restore and verification code. | Correct it before use. `normpath('../../x')` still contains `..`, and joining an absolute path discards the intended root. Reject absolute paths, any `..` component, non-canonical paths, and snapshot names not produced by the strict validator. Restore opens path components relative to a snapshot directory descriptor without following symlinks. |

`snaputil.is_stale` (`snaputil.py:66-73`) is not a crash-detection mechanism and
will not be used for cleanup: directory mtime does not establish publication,
and line 73 uses `<=` even though its docstring says equality is not stale.

## 3. On-disk format

```text
BACKUP_ROOT/
  .writer.lock                    # never removed
  index.json                      # atomically replaced
  .index.tmp.<uuid>               # visible only while writing an index
  locks/
    <snapshot-name>.lock
  .staging/
    <snapshot-name>/              # ignored by readers
  snap-YYYYMMDD-HHMMSS-000001-<128-bit-uuid>/
    COMMITTED
    snapshot.json
    dirs/
      <configured-source-id>/
        manifest.json
        payload/
          <source-relative-paths>
    RETIRING                      # optional lifecycle marker; not payload
  .trash/                         # ignored by snapshot discovery
  recovery/
    last-recovery.json
    index.invalid.json            # at most one retained bad index specimen
```

Source IDs are stable, unique configuration keys matching
`[A-Za-z0-9._-]+`; a manifest maps an ID to its configured source rather than
using path spelling as identity. The timestamp is UTC only for human reading.
A root-wide integer sequence, allocated under the writer Lock, and a random
UUID provide ordering and identity. `next_sequence` survives in every index;
recovery also takes the maximum sequence found in surviving names. A reader
must match both name and UUID, so an obsolete name can never be treated as a
new snapshot.

Each per-source manifest has this logical form:

```json
{
  "format": 1,
  "source_id": "results",
  "base": {"snapshot": "snap-...", "uuid": "..."},
  "directories": ["", "subdir"],
  "files": {
    "subdir/a.json": {"size": 123, "mtime_ns": 1794900123456789012}
  }
}
```

The `base` fields identify the previous snapshot used for reuse. They are
provenance, not permission to omit a payload file: every entry in `files` has a
regular file or hard link in this snapshot's `payload` tree. Source timestamps
are backup selection metadata; payload timestamps and modes are preserved where
supported, while original modes in metadata remain authoritative if the
payload is made read-only to discourage accidental mutation.

`snapshot.json` records name, UUID, sequence, source IDs, start/finish times,
per-source file/byte/directory counts, copied and linked counts, status (`ok`
or `degraded`), and every skipped path with a stable reason code and OS error
when available. A skip record contains no source-file content. The manifest
byte count and SHA-256 digest for each source are recorded here. Digests cover
manifest bytes, not file contents; their purpose is metadata integrity.

`COMMITTED` contains format, name, UUID, sequence, and the SHA-256 digest of
`snapshot.json`. It is written through a temporary file, flushed and `fsync`ed,
renamed, and followed by an `fsync` of the staging directory. `COMMITTED` and
`snapshot.json` are immutable after final publication. Only lifecycle markers
outside `dirs/` can subsequently change.

The global index has `format`, monotonically increasing `generation`,
`next_sequence`, and a sequence-ordered snapshot list. Each snapshot entry
contains its name, UUID, status, sequence, completion time, per-source manifest
paths/digests, counts, and skip counts. It does not duplicate per-file maps.
For integrity, the canonical JSON payload is accompanied by `payload_sha256`
computed with that one field excluded. Readers reject an unsupported format,
bad digest, duplicate sequence/name/UUID, invalid path, or manifest disagreement.

## 4. One run

### 4.1 Lock and recover

1. Create the backup-root administrative directories if needed, open
   `.writer.lock`, and request `LOCK_EX | LOCK_NB`.
2. If it is locked, do no cleanup or source work. Print
   `{"status":"busy", ...}` and exit 2. The other run continues intact. Kernel
   Lock ownership is released on every process-exit path, including `SIGKILL`.
3. While holding the writer Lock, remove old `.staging` and `.index.tmp.*`
   entries and complete already-marked `.trash` deletions using the rules in
   sections 5 and 7. Readers never select those entries.
4. Load and cross-check the index, rebuilding it when necessary as specified
   in section 5. Select the newest valid committed snapshot containing each
   configured source as that source's base.

There are no reader Locks for staging because staging is unreachable through
the reader API. A currently active restore does not block this startup unless
corruption requires quarantining/deleting the exact snapshot it holds.

### 4.2 Scan and compare each source

Sources are processed serially in configuration order. For source `i`:

1. Scan files and directories once, in the deterministic order derived from
   `scan_files`. Capture `size` and `mtime_ns` for each regular file. An unreadable
   directory, an entry that vanishes during scanning, or a non-regular entry
   produces a skip record. A missing/unreadable configured **root** is fatal:
   discard the new staging snapshot rather than silently treating a whole
   source as empty.
2. Read the selected base manifest and call
   `synccli.changed_files(old.files, new_scan)`. Paths present only in `old`
   are deletions. Paths whose exact states match are reuse candidates.
3. An absent or invalid base manifest for a source means an empty old manifest,
   so that source receives a full copy. A degraded snapshot's valid manifest is
   still used for the files it contains; a file omitted by that degraded run is
   absent from the base and is therefore copied as new and retried.

The scan manifest is only a candidate list. It is not published as-is.

### 4.3 Reuse or copy into staging

For every reuse candidate, check that the source is still a regular file and
that the validated base payload exists. Use
`os.link(base_payload, staged_payload, follow_symlinks=False)` with no
overwrite. Because both paths are below the backup root, this is a local
same-filesystem link. The old and new snapshots share an inode but neither is
writable by backupctl after commit. A missing base file is recovery evidence;
if the current source can still be read, copy it as changed, otherwise record a
skip.

For every new or changed file, use the streaming replacement for
`synccli.copy_file`:

1. `lstat` the source and reject non-regular files.
2. Open it without following a final symlink. Compare descriptor `fstat`
   device, inode, size, and `mtime_ns` with the scan observation.
3. Stream to a uniquely named temporary file in the staged payload directory
   using a fixed 1 MiB buffer. Check every read, write, flush, and close.
4. `fstat` the source again. Device, inode, size, and `mtime_ns` must equal the
   values observed on the open descriptor. This detects the ordinary
   overwrite, replace, truncate, and grow races during copying.
5. `fsync` the destination and atomically `os.replace` its temporary name.
   Only then add the path to the new output manifest.

There is one bounded retry for an open/read/stat race; a second failure is
recorded and omitted. A write-side allocation or I/O failure does not use old
content. If the changed file's copy fails for any reason, **do not fall back to
its base payload**, because the metadata has already established that it is a
different version.

If a source disappears between listing and copy, that path is absent from the
output manifest and payload. If it was changed and copy became unreadable, it
is likewise absent rather than stale. If the source was successfully checked
and linked immediately before disappearing, it remains in the file-level image
captured at that successful check. This is the precise scan-window behavior for
both scheduler and interactive runs.

After each source, create its recorded empty directories, write its manifest
from **successful** copies/links only, and release its old/new in-memory maps
before proceeding to the next source. Serialize skip records into staging as
they are generated (as shards later referenced by `snapshot.json`, or as an
incrementally written temporary JSON array), retaining only per-source counts
for the final global index; do not accumulate all N sources' reports in RAM.

### 4.4 Commit

1. Finish all N source manifests, `snapshot.json`, and skip records through
   temporary-file-plus-rename writes. `fsync` payload files (done during
   copying), all staged directories containing hard links or metadata, and
   their parents.
2. Write and durably rename `COMMITTED`; create the snapshot's Lock file.
3. Atomically rename the complete staging directory to its final `snap-*`
   name, then `fsync` the relevant parent directories.
4. Build a new index containing the new snapshot and all still-valid old
   entries. Write `.index.tmp.<uuid>` with `O_EXCL`, flush and `fsync` it,
   `os.replace` it over `index.json`, and `fsync` the backup root.
5. Only now report the snapshot as published. Apply retention and print the
   final report.

A reader therefore sees either the old index or the new index, never an
intermediate JSON document. A final committed snapshot found between steps 3
and 4 is already a complete standalone image, and the next recovery inserts
it into the index.

The run report includes snapshot name/UUID even for a degraded publication,
per-source totals, copied/linked/deleted/skipped counts and bytes, skip records,
base snapshots, index recovery, and prune results. Status `ok` exits 0;
status `degraded` exits 3 after safely publishing everything that succeeded.
Fatal errors leave prior snapshots/index intact and exit 1. Neither SIGINT nor
process death is converted into success.

## 5. Index and crash recovery

Recovery is deterministic and requires no operator cleanup.

### Interruption at each phase

| Interruption point | What a reader sees | What the next writer does |
| --- | --- | --- |
| Before final commit, including during a copy | Previous committed snapshots only; the current staging tree is invisible | Delete the old staging tree under the writer Lock and start fresh |
| Staging `COMMITTED` exists but final rename did not occur | Nothing new | Discard that staging tree; staging is never promoted by recovery |
| Final snapshot rename occurred but index replacement did not | The final snapshot is complete if addressed directly; the old index otherwise remains valid | Discover the committed final tree and add it to a rebuilt index |
| During index temporary write | Old `index.json` and all old snapshots | Discard the temporary; keep the old valid index |
| After index rename but before report | New valid index and new complete snapshot | Cross-check and continue; do not roll back the successful commit |

### A missing, corrupt, half-written, or inconsistent index

1. On JSON syntax, schema, digest, or path-validation failure, retain only one
   diagnostic specimen at `recovery/index.invalid.json` via atomic replacement;
   never load any entry from the bad document. A missing index needs no
   specimen. Truncated `.index.tmp.*` files are discarded, not parsed.
2. Enumerate names with `snaputil.list_snapshots`, then independently validate
   each candidate whose name matches the strict backupctl pattern (including
   its UUID). Other prefix-matching entries are reported as unrecognized but
   are neither indexed nor deleted. For each recognized candidate, require
   matching COMMITTED/name/UUID/sequence/snapshot digest, no lifecycle marker,
   valid per-source manifests and manifest digests, canonical safe relative
   paths, and exactly the manifest-declared regular payload file set with
   matching sizes. No file contents need to be hashed for this structural
   recovery.
3. Re-derive the snapshot list solely from valid final trees, sorted by
   sequence. `RETIRING` and `.trash` entries are excluded and their deletion is
   completed. Staging is discarded. Do not infer completeness from directory
   mtime, filename, or a partial per-file listing.
4. If a final-name candidate fails validation, atomically add `INVALID` to
   stop new readers, acquire its exclusive snapshot Lock (waiting for an
   existing restore to finish), and move it to `.trash`. Preserve its error
   and metadata in `recovery/last-recovery.json`, then remove the unusable
   payload. An invalid snapshot never counts as the one usable snapshot that
   retention protects.
5. Write the recovered index by the same atomic procedure as a normal commit.
   If no valid snapshot exists, write a valid empty index and perform a full
   backup; do not delete source data or claim that an empty old backup exists.

`last-recovery.json` reports action (`loaded`, `rebuilt_missing`,
`rebuilt_corrupt`, or `rebuilt_tree_mismatch`), bad-index reason, recovered
snapshot names/UUIDs, discarded staging names, rejected snapshot names and
validation reasons, and completed trash deletions. The next run report repeats
a summary so both scheduler logs and interactive users see the event.

Normal runs with a valid, tree-matching index do not walk every file in every
old snapshot. They validate the index and required commit/manifest metadata;
the full payload walk above is reserved for index/tree mismatch and corruption
recovery.

## 6. Reader protocol and concurrent restores

The public `backupctl` reader context manager is part of the design even though
the actual restore copy can remain in separate tooling. It behaves as follows:

1. Read the current atomically published index and select a name and UUID.
2. Open `locks/<name>.lock` without creating a missing Lock and acquire
   `LOCK_SH`.
3. While holding it, re-read the index and confirm the same name and UUID are
   still listed. Open the snapshot directory and require matching `COMMITTED`
   plus absence of `RETIRING` and `INVALID`. If any check fails, release the
   Lock and reselect; never continue from a stale index selection.
4. Validate manifests and use the corrected `safe_snapshot_path`/directory-fd
   resolver for every restore path. Hold the shared Lock until every payload
   file has been opened and copied and the restore has finished verification.

A new run writing another snapshot does not need to disturb this reader: it
uses fresh staging paths and only reads/hard-links immutable base files.
Prune, however, must exclude an active reader as described next. A direct human
listing of a committed, non-retiring snapshot sees complete files and manifests;
human or third-party access that bypasses leases cannot be protected against
its pathname disappearing during retention and is outside the supported
restore API.

## 7. Retention and deletion protocol

Retention policy is **keep the newest 7 valid committed snapshots**, with a
per-backup-root integer `keep` override requiring `keep >= 1`. Both `ok` and
`degraded` snapshots are structurally valid and restorable; their reports make
degradation visible. The newest valid snapshot is always excluded independently
of the count. Pruning normally happens after a new snapshot and its index have
published successfully; startup may retry only candidates that were already
beyond `keep` after an earlier successful publication and were deferred by a
reader, never the newest valid snapshot.

Candidate order comes from committed sequence, using
`snaputil.prune_snapshots` only for its oldest-first selection/report model.
For each candidate beyond the newest `keep`:

1. Try its per-snapshot `LOCK_EX | LOCK_NB`. If a reader owns a shared Lock,
   change nothing and report the snapshot as `deferred_reader`. It remains a
   valid indexed snapshot.
2. With the exclusive Lock held, there are no active readers and new shared
   Locks cannot succeed. Atomically write `RETIRING` and `fsync` the snapshot
   directory. This also covers a crash before index removal.
3. Atomically replace the global index without this name/UUID and `fsync` the
   root. Existing readers were excluded by the Lock; later readers revalidate
   and cannot select it. Recovery will not resurrect it because `RETIRING`
   takes precedence over `COMMITTED`.
4. Rename the final directory into `.trash`, `fsync` the parents, and then
   call `shutil.rmtree` on that now-undiscoverable path. A crash during
   `rmtree` can expose only files in `.trash`, never a live index entry.
   Delete its Lock file after the payload removal; UUID checks protect any
   stale opener.
5. Report deleted names oldest first. Continue with other candidates if one
   candidate has an active lease.

Hard links make deletion of one snapshot's directory entries unable to alter
another snapshot's payload bytes. At least the newest valid committed snapshot
survives every prune pass, and no active lease is ever broken.

## 8. Change-detection granularity and limitations

The unit of reuse is **one relative file path within one configured source**.
Two states are equal only when both exact integer `size` and exact `st_mtime_ns`
match. There is no directory-level shortcut: every regular source file is
scanned every run. Deletions are path-set differences, renames are one deletion
plus one new path, and metadata-only mode/owner changes without size or mtime
change reuse the previous content and thus are not permission backups.

This deliberately inherits `synccli.changed_files`' metadata trade-off while
eliminating float-mtime comparison. An edit that changes bytes, restores the
original size, and restores the exact nanosecond mtime is missed. Filesystems
whose actual timestamp granularity is coarser than nanoseconds can also miss
an in-place same-size edit inside one timestamp tick even though Python reads
`st_mtime_ns`. The same limitation applies to an edit racing a copy that hides
from the before/after state checks. Content hashes are not silently claimed as
a remedy. If those adversarial edits are in scope, a later `--hash-all` mode
must read and hash every current source file and compare content digests; it is
not part of this performance budget.

The manifest remains a complete inventory of the snapshot's actual payload,
not a promise about source files that could not be captured.

## 9. Initial-full-backup performance budget

### Measurement on this repository's host

Before designing the budget, I ran the existing suite in this directory:

```text
python3 -m unittest: 6 tests, OK, 0.004 s
```

I also ran a synthetic initial-full-copy check using this repository's
`synccli.scan_files` and `synccli.file_state`, with the streaming,
before/after-`fstat`, per-file-`fsync`, and `os.replace` behavior specified
above. The fixture had **30,000 regular files totaling exactly 1 GiB
(1,073,741,824 bytes)** across 150 directories (ordinary files about 35 KiB).
The temporary fixture was removed afterwards; cleanup was excluded from the
backup timing. The measured host was macOS 15.8.1 arm64, Python 3.10.11, on
its local volume.

| Phase | Measured time |
| --- | ---: |
| Sorted scan plus one `file_state` per file | 2.145 s |
| Stream 1 GiB, pre/post source checks, destination write, per-file `fsync`, and rename | 13.803 s |
| Directory `fsync`s plus JSON manifest write/`fsync` | 0.092 s |
| **Measured total** | **16.040 s** |

The copy phase corresponds to approximately `2 GiB / 13.803 s = 155.6 MiB/s`
of combined source-read plus destination-write traffic. The fixture's source
pages were recently generated and therefore this is a warm-cache measurement,
not a claim for cold network or rotating storage.

### Budget

The acceptance budget is **65 seconds for that 1 GiB / 30,000-file initial
full snapshot on the reference host**. The derivation is explicit:

```text
ceil(4 x (2.145 + 13.803 + 0.092)) = ceil(64.160) = 65 seconds
```

The factor of four reserves 48.120 seconds over the measured total for source
cache variation, normal local-I/O scheduling, the small final COMMITTED/index
writes not present in the microbenchmark, and integration overhead. It is not
an invented throughput figure: every measured addend and the margin are shown.
This budget assumes unchanged source files during the one allowed copy retry,
no pre-existing index corruption, no competing heavy I/O, and local supported
storage. More than one retry is a degradation report, not silent deadline
extension. A substantially different deployment host must run the same
30,000-file/1 GiB method and set its measured four-times budget rather than
borrow this host's result.

## 10. Growth and bounds

Use these quantities for a normal run:

- `N`: configured source directories.
- `f_i`, `d_i`: file entries considered (regular files and rejected
  non-regular entries) and directories scanned in source `i`;
  `F = sum(f_i)`, `D = sum(d_i)`, `Fmax = max(f_i)`, `Dmax = max(d_i)`.
- `L`: total UTF-8 bytes of source-relative paths; `Lmax` is the largest
  per-source equivalent.
- `B`: logical bytes of all scanned regular files.
- `C`: files selected for copying because they are new/changed (or lack a
  linkable base); `U`: successfully hard-linked unchanged files;
  `C + U <= F`. Each selected file has at most two attempts.
- `Bcopy`: successfully copied bytes incorporated into the new snapshot;
  `0 <= Bcopy <= B`. `Bstream` is all source bytes read including failed
  retries; the one-retry rule gives `0 <= Bstream <= 2*B`.
- `Wmax`: the largest skip count for one source; `Wmax <= Fmax + Dmax`.
- `K`: retention count (default 7), `R`: old snapshots whose deletion was
  deferred by an active read lease, and `S`: committed snapshots after prune.

### Normal-run work

- Scanning and per-file state collection are `O(F + D)` system operations;
  sorted file output costs `O(sum(f_i log f_i))` comparisons and at most
  `O(F log Fmax)` overall. No configured source is skipped merely because N is
  large.
- Comparison with the previous per-source manifest is `O(f_i)`, so all
  comparisons are `O(F)` in addition to sorting.
- There are exactly `U` successful hard-link creations and at most `2*C`
  metadata-verified copy attempts. Time is `O(U + C + Bstream)`, with
  `Bstream <= 2*B`, plus normal filesystem metadata costs. An unchanged run has
  `Bcopy = Bstream = 0` but still scans all F files and creates U links.
- New manifests and reports are `O(F + D + L + W)` JSON work, where `W` is the
  number of skips and `W <= F + D`. N is processed serially, not with N
  workers.
- Index load/rewrite is `O(N*S)` entries/JSON. With no active-reader deferrals
  and after a normal prune, `S <= K = 7` by definition. With deferrals,
  `S <= K + R`; immediately between publication and that prune there can be
  one additional snapshot. R can grow if restores are continuously active and
  is reported rather than hidden.

Recovery is deliberately different: rebuilding a bad/missing index costs
`O(sum_over_S(F_s + D_s + L_s))` metadata time and manifest bytes read, but no
`O(sum B_s)` payload reads. Its memory remains one source manifest at a time
plus the `O(N*S)` index.

### Memory and file descriptors

- Peak source working memory is per source, not all N trees:

  ```text
  O(N*S)                                      configuration/index
  + O(Fmax + Dmax + Lmax + Wmax)              sorted scan, old/new maps, dirs, skips
  + 1 MiB                                     one copy buffer
  ```

  More explicitly, old and new per-source maps coexist, so the map term is two
  manifest representations plus the sorted path list, each bounded by the
  stated `Fmax`/`Lmax`; it is not `O(B)`. Python object overhead is proportional
  to those counts and path lengths, not to file contents.
- One writer, one source scan, and one copy run at a time. Copy buffering and
  writer concurrency do not grow with N, F, or B: exactly one 1 MiB buffer and
  one writer. File descriptors are a small constant (`O(1)`) during copy,
  independent of N/F/B; directory walks and manifest writes own descriptors
  only for their current operation.

### Disk

For a newly published snapshot:

```text
new unique payload bytes = Bcopy
metadata and directory-entry storage = O(F + D + L + W)
```

The U hard links add directory entries and full manifest records but do not
duplicate their payload bytes. The exact live unique-payload allocation is the
sum of `st_size` over distinct `(st_dev, st_ino)` pairs reachable from all live
payloads, plus metadata. If `B_s` is snapshot s's logical bytes and `H` is the
set of all historically published runs, then:

```text
live unique payload bytes <= min(sum(B_s for live s), sum(Bcopy_h for h in H))
physical backup-root storage = live unique payload
                               + O(all live metadata and directory entries)
```

The first sum bounds deduplicated data even when a contributing old snapshot
has been pruned; the second is a looser lifetime bound because it includes
copies whose last reference may since have been pruned. Pruning the final
directory reference frees an inode's bytes. At most one current staging
snapshot adds another `Bcopy` and metadata allocation; stale staging is removed
at the next startup.
`S <= K + R` bounds live snapshot metadata after a successful prune, while
one streaming retry's temporary file adds at most the size of that one file
before it is discarded. `snapshot_disk_usage`'s logical sum intentionally does
not use this physical-allocation formula.

## 11. Verification to implement with `backupctl`

The existing six tests remain compatibility tests. New tests will use real
subprocesses and filesystem state, not only mocks:

1. Two simultaneous runs: one commits or one exits 2; no duplicate sequence,
   malformed manifest, or torn index is observable.
2. Kill a writer at every commit step in section 5; after every interruption,
   discovery exposes only complete snapshots and the following run recovers
   without manual cleanup.
3. Replace `index.json` with truncated JSON, valid JSON with a bad digest, a
   missing-file reference, and a stale index after a final-directory commit;
   verify the specified re-derivation, quarantine/trash behavior, and reports.
4. Delete or deny read access to a file between scan and copy. The published
   payload omits it, its manifest omits it, `snapshot.json` is `degraded`, the
   run exits 3, and the next run retries it.
5. Make a changed file fail copying and verify that its old base payload is not
   silently inherited. Delete a source path and verify the base path disappears.
6. Verify unchanged files have the same inode in consecutive snapshots,
   changed files do not, and payload writes in staging never modify old content.
7. Hold a restore shared Lease while pruning: the reader completes and the old
   snapshot remains. After release, another prune can retire it. A reader that
   selected a stale index revalidates and never opens a retiring tree.
8. Keep one snapshot and attempt every valid retention configuration: it is
   never removed. Crash deletion after RETIRING, after index removal, and
   during trash removal; the snapshot is neither resurrected nor half-visible.
9. Verify unsafe manifest paths, symlinks, malformed COMMITTED records, hidden
   source files, and empty directories.
10. Run the exact 30,000-file/1 GiB benchmark as an integration performance
    test on the reference host, with a 65-second threshold under its stated
    load assumptions.

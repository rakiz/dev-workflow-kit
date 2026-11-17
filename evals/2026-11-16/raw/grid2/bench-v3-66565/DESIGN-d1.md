# `backupctl` design (D1)

## 1. Scope and invariants

`backupctl.py` will be a Python 3 standard-library command-line program beside
`synccli.py` and `snaputil.py`. A JSON configuration names the backup root, an
ordered list of source directories with stable source IDs, and a retention
count (default `keep = 7`, minimum 1). `backupctl run --config CONFIG` is the
only run entry point: both a scheduler and a person execute the same function,
with the same error policy and exit statuses.

A backup contains regular files from all configured sources. Symbolic links
and special files are not followed; each is reported as an unsupported entry.
An empty, successfully scanned source is a valid empty backup. The backup root
must not be inside a source, and the staging directory and final snapshot must
be on the same filesystem so publication is an atomic `rename`.

The central invariant is:

> A name matching a published snapshot is visible only after every payload
> entry, directory, and manifest below it is complete, and its payload is
> immutable thereafter.

Construction and index recovery happen under other names. Thus a reader never
has to ask whether a writer finished. Publication is atomic for the whole
N-source snapshot, not one source at a time. This is not a simultaneous
transaction against the live sources: different source files can be observed
at different instants, but readers see one complete, self-describing backup
image rather than a mixture of backup runs.

A **usable** snapshot has a valid manifest describing exactly the payload that
is present. It may be `complete` (no source errors), `partial` (known source
omissions), or `recovered` (its index was rebuilt from its payload). Restore
must display partial/recovered status and require an explicit
`--allow-noncomplete` option; otherwise it selects the newest `complete`
snapshot. It must never present omitted files as successfully restored.

## 2. Layout and manifest

Only `snap-*` directories at the backup root are published snapshots. Internal
entries use distinct prefixes and are never valid restore targets:

```
BACKUP_ROOT/
  .backupctl/
    run.lock
    catalog.lock
    readers/SNAPSHOT_ID.lock
    staging/RUN_UUID/
    trash/RUN_UUID/
    quarantine/SNAPSHOT_ID.RUN_UUID/
  snap-YYYYmmdd-HHMMSS-SSSSSS/
    payload/SOURCE_ID/...regular files...
    .backup_manifest.json
```

The UTC timestamp and fixed-width, zero-padded sequence are allocated while
holding the run lock; a random run UUID distinguishes staging directories.
Sequence allocation also examines quarantined and staging names so a dead run
cannot cause reuse. Snapshot IDs, not directory mtimes, define age order.

The versioned JSON manifest has this logical shape:

```json
{
  "format": 1,
  "id": "snap-20261117-120000-000042",
  "status": "complete",
  "run_uuid": "...",
  "started_at": "...",
  "completed_at": "...",
  "sources": {
    "eval-results": {
      "scan": "complete",
      "files": {
        "relative/path": {"size": 123, "mtime_ns": 1234567890123456789}
      },
      "errors": []
    }
  }
}
```

`errors` contains stable objects (`path`, `operation`, `errno`/`error`, and a
message), not just console text. Paths in keys are relative `/`-separated
paths. `scan` is `complete` or `failed`; a failed source has an error and no
claim that its file map is exhaustive. A recovered manifest also has
`recovery: {original_index_problem, recovered_at}` and status `recovered`.
No entry is written for a payload file that was not successfully copied or
linked.

The writer serializes with `json.dump`, flushes and `fsync`s the file, then
atomically renames it to `.backup_manifest.json` *inside its private staging
directory*. It fsyncs copied file descriptors and staging directories, renames
the fully populated staging directory to its final `snap-*` name, and fsyncs
the backup root. Consequently process death leaves either an invisible staging
tree or a complete published tree. A machine/filesystem that does not honor
`rename`, `fsync`, or same-filesystem hard-link semantics is outside the
storage contract.

## 3. Grounding in the existing implementation

The design deliberately reuses small primitives, not `synccli.sync` as a black
box:

| Existing artifact | How `backupctl` builds on it | Required difference/override |
|---|---|---|
| `synccli.scan_files` (`synccli.py:10-19`) | Produces the sorted relative-path list used for deterministic scanning. | Add/include an `include_hidden=True` mode for backups: line 14 currently excludes every dot-directory, which would silently omit eval artifacts. Symlink directories remain un-followed. Per-file `lstat` rejects symlinks/special files. |
| `synccli.file_state` (`synccli.py:22-25`) | Supplies the state model `{size, mtime}` used to identify a file version. | A backup wrapper `file_state_ns` returns integer `st_size` and `st_mtime_ns`, not the current lossy float `st_mtime`. `lstat`/`fstat` errors are returned to the per-file error policy instead of escaping or being ignored. |
| `synccli.build_manifest` (`synccli.py:28-33`) | Establishes the manifest composition of `scan_files` plus `file_state`. | Do not call it unchanged: one vanished file at line 32 would abort the entire backup. The backup manifest builder calls the helpers path by path and records failures. |
| `synccli.changed_files` (`synccli.py:36-42`) | Directly computes new entries and entries whose old/new state dictionaries differ. These are the only files whose bytes are copied. | Both manifests must use the new nanosecond state schema. Missing old entries (including an earlier partial omission) are copied. Source deletions are represented by absence from the new manifest, as in `build_manifest`, not copied forward from history. |
| `synccli.copy_file` (`synccli.py:62-69`) | Retain its parent-directory creation and binary source/destination behavior for the new copy primitive. | Replace `fsrc.read()` with a 1 MiB streaming buffer, write only a staging temporary file, `fsync`, and rename. Never reproduce line 69's swallowed `OSError`: remove a partial destination and report the path. Verify stability with `fstat`; retry a file changed while copying once, then omit/report it. |
| `synccli.sync` (`synccli.py:72-87`) | Its scan/compare/copy/manifest sequence is the basis of the per-source algorithm. | Do not use the live destination update at lines 83-86. It copies over visible files, writes a manifest promising vanished files, and has no atomic publication. `backupctl` instead builds a private multi-source tree and publishes it once. |
| `snaputil.list_snapshots` (`snaputil.py:8-20`) | Supplies sorted direct-child candidates for listing and retention. | Because the implementation accepts any directory beginning `snap-`, validate the exact ID grammar and manifest before calling a candidate usable. Do not trust lexical candidates or mtimes as recovery evidence. |
| `snaputil.prune_snapshots` (`snaputil.py:23-36`) | Its oldest-first doomed-list calculation informs retention selection. | Do not call it directly: it has no reader/run locks, does no manifest validation, accepts `keep=0`, and immediately calls `rmtree`. The retention wrapper below provides those guarantees. |
| `snaputil.snapshot_disk_usage` (`snaputil.py:39-51`) | Used for per-snapshot **logical** size reporting. | Its byte total counts each hard link again and is not physical root usage; label it accordingly and tolerate disappearing files during administrative inspection. |
| `snaputil.safe_snapshot_path` (`snaputil.py:54-63`) | Maps an accepted manifest path back beneath the snapshot for restore. | First reject absolute paths, empty paths, and any `..` component. `normpath` alone (line 62) can still leave `../` or allow an absolute second argument to discard the intended root; validation is mandatory before calling it. |
| `snaputil.is_stale` (`snaputil.py:66-73`) | Not part of backup construction. | Do not use mtime to decide whether to clean staging: the run lock already proves there is no live local writer. Also, line 73 uses `<=` despite its docstring saying equality is not stale. |

The existing `test_synccli.py` tests establish sorted scanning, current
size/mtime change detection, and first-copy/second-no-op behavior. They were
run unchanged with `python3 -m unittest`: **6 tests passed in 0.006 s**. The
new schema and private staging belong in `backupctl`, without changing the
observable behavior of `synccli` or its tests.

## 4. One run

### 4.1 Locking and dead-run recovery

1. Create `.backupctl` metadata directories, open `run.lock`, and acquire an
   **exclusive, nonblocking-or-clearly-reported waiting `flock`**. Hold it for
   the whole run. This serializes scheduler and manual runs. `flock` releases
   on close or process death, including Ctrl-C/SIGKILL after the OS reaps the
   process; no PID file is trusted.
2. Once the lock is held, every staging directory belongs to a dead run.
   Remove all staging trees, including any half-written indexes, rather than
   merging their files into this run. Also finish deleting leftover `trash`
   trees. Report `discarded_interrupted_runs = K` and their IDs as warnings.
   Readers could never have mistaken these internal names for snapshots.
3. Enumerate published candidates and validate their indexes. Recovery that
   changes visibility follows section 7 and the reader locks below. Baseline
   selection then uses the newest usable snapshot, including a partial one for
   the files it actually records. If none is usable, this is a first full
   backup.

No stale lock or staging cleanup requires manual intervention. An unexpected
quarantine may remain for diagnosis, but does not prevent new snapshots.

### 4.2 Scan, change detection, and copying

For each source sequentially:

1. Scan its sorted paths and create the new file-state map using the grounded
   helpers above. A path disappearing during scan/stat produces a source error
   and no new manifest entry, not a failed whole run. A root that cannot be
   walked at all has `scan: failed`.
2. Call the semantics of `changed_files(previous_files, new_files)`. The unit
   of change is one regular file at one relative path. If **both byte size and
   nanosecond mtime** equal the previous manifest, create a hard link from the
   previous snapshot's immutable payload into staging. No source content is
   reread or copied. If the old payload expected by a valid manifest is absent,
   that old index is not valid; recover it before using it as a baseline.
3. For every changed/new file, open the source without following symlinks,
   compare `fstat` with the scanned identity/state, and stream to a unique file
   in the staging tree. `fstat` again after copying. A mismatch means the file
   was modified/replaced during copying: discard the temporary output and retry
   once from the newly opened source. A still-changing file is omitted and
   reported as `unstable_source`. Set the staged file's mtime to the state that
   was actually captured before its close/publication.
4. An unreadable file, a vanishing file, an unsupported file type, or an output
   I/O error removes that output and produces an explicit error. Source-side
   read/vanish/unstable errors make the snapshot `partial`; the snapshot
   contains every successfully copied or hard-linked file and no placeholder
   or manifest entry for the omitted one. A previous version is not silently
   substituted for a file known to be changed. For an unchanged-by-state file
   that vanishes after scanning, the last snapshot still supplies the
   identified version and can safely be hard-linked; that case needs no source
   read and is not an error.
5. Output-side failures are different: failure to create reliable staging,
   write its manifest, fsync, link a baseline file, or publish means the run
   fails without publication (exit 1), unless the affected source can be
   explicitly marked omitted under the same partial policy. Running out of
   backup space is always fatal; remove the private staging tree and retain
   old snapshots.

After all sources, write the actual result manifest and publication report.
If every source root failed and no prior usable snapshot can supply an image,
publish nothing. Otherwise publish even a partial result, report every
omission on stderr and in JSON, and return exit status **2** for partial,
**0** for complete, and **1** for no published usable snapshot/fatal failure.
The summary contains copied/linked/skipped file counts, copied bytes, recovered
indexes, discarded staging trees, and pruned IDs. Scheduler output and manual
output therefore come from exactly the same code path.

Identical size and nanosecond-mtime change detection can miss an in-place edit
that preserves length and restores mtime to exactly the old nanosecond value
(for example, deliberate timestamp restoration or coarse filesystem timestamp
behavior). It also cannot detect malicious source manipulation designed to
preserve those fields. Such a file is hard-linked to the previous content.
This is the explicit tradeoff for not hashing unchanged files; a future
verified mode could add checksums, but is not assumed by this design or its
performance budget.

## 5. Reader/restore protocol and safe deletion

`.backupctl/catalog.lock` and per-snapshot reader locks prevent retention from
un-linking a tree while restore traverses it. Advisory locks require all
cooperating tools to use this protocol; arbitrary tools that mutate snapshots
are intentionally unsupported.

**Reader:**

1. Acquire `catalog.lock` shared.
2. Select a published candidate, open its per-snapshot reader lock shared,
   validate that its final directory still exists and its manifest is valid,
   then release `catalog.lock`.
3. Keep the reader lock for the entire traversal/copy. Resolve every validated
   relative path with `safe_snapshot_path` after the checks in section 3.
   Release the lock on every exit path. No run-state test is needed.

A human browsing a snapshot while a new run writes needs no lock because the
new tree is private until atomic rename. A human browsing during pruning must
use the supplied read/restore wrapper; an unlocked deletion can otherwise
produce ordinary `ENOENT`, although it cannot expose a mixed snapshot.

**Pruner:** acquire `catalog.lock` exclusively. For each doomed snapshot, in
oldest-first order, acquire its reader lock exclusively (waiting for current
readers), atomically rename it into private `trash`, and release its reader
lock. Only after all visible doomed names have moved, release the catalog lock
and recursively delete trash. Holding the catalog lock while waiting blocks
new readers, preventing starvation/races; the reader's lock-acquisition order
is the same, so there is no lock-cycle deadlock. A reader acquiring a lock
after a rename revalidates and fails selection rather than reading trash.
Reader-lock files may be removed only while holding both relevant exclusive
locks; stale fixed metadata files are reclaimed the same way. A crash during
`rmtree` leaves only private trash, which the next run removes.

## 6. Retention

Pruning occurs only after this run has published and validated a usable
snapshot. Let `V` be the number of currently usable published snapshots,
ordered oldest first. Protect:

- the newest `min(7, V)` usable snapshots (or the configured `keep >= 1`), and
- the newest `complete` snapshot, if one exists, even when newer partial or
  recovered snapshots fill the keep window.

Delete every older usable candidate not in that protected set using the
protocol in section 5. Invalid/unrecognized/quarantined trees are never counted
as usable backups and are not silently used to satisfy retention. This keeps
between `min(keep, V)` and `min(keep + 1, V)` snapshots: one additional latest
complete snapshot is the only excess. In particular, retention can never
remove the only usable snapshot or the last complete one. If no snapshot was
published, or initial validation is still in progress, do no pruning.

`snapshot_disk_usage` can report each retained snapshot's logical size, while
physical usage must be reported from filesystem/inode accounting so shared
hard-linked files are counted once.

## 7. Corrupt or half-written index recovery

Recovery distinguishes the two places an index can exist:

1. **Staging index:** discard the entire staging run. Its payload and manifest
   are untrusted and mixing them with a new scan could create precisely the
   mixed-run image publication is meant to prevent. Nothing is re-derived for
   an unpublished run; the new run re-scans the sources. Report the discarded
   run ID and reason.
2. **Published index:** despite atomic publication, an index may be malformed
   because of media failure, manual interference, or an older/nonconforming
   writer. A missing/unreadable/non-json file, failed schema check, invalid
   relative path, missing payload, payload size/type mismatch, or unexpected
   payload file makes it non-usable. Under catalog-exclusive and its
   reader-exclusive locks, rename the snapshot to quarantine first, preserving
   the bad index as `invalid-manifest.json` for diagnosis; then release the
   global catalog lock while retaining the run lock.

For a quarantined tree whose source IDs still match configured IDs, re-derive
an index **only from the payload actually present**, using `scan_files` plus
`file_state_ns` on the quarantined tree. Do not consult live sources or invent
the original omissions, origins, completion status, or error list. Record every
present regular file, reject/quarantine unsafe links or unknown source roots,
set status `recovered`, and retain the original index problem and a warning
that historical omissions cannot be reconstructed. Write/fsync/atomically
rename the replacement index, validate it, then atomically rename the tree back
to its snapshot name under catalog-exclusive/read-exclusive locks and fsync the
root. If any step fails, leave it quarantined and continue with another usable
baseline or a full copy. Emit a prominent recovery warning and include counts
of added/removed manifest entries and snapshots left quarantined.

A recovered snapshot is self-consistent as an image of its surviving payload,
but is not called a complete backup of the sources. The next normal run may
reuse its file states after the same validation, while retention still
protects the newest genuinely complete snapshot.

## 8. Initial-full-backup performance budget

**Budget: at most 60 seconds for 1 GiB across approximately 30,000 regular
files, on local SSD storage comparable to the measured arm64 machine, with one
writer and no competing backup run.** This is an engineering budget tied to a
target environment, not a promise for network filesystems, throttled laptops,
or arbitrary hardware; deployment must rerun the benchmark before adopting
the SLO.

The number comes from an actual first run of the existing implementation, not
an extrapolation from a smaller tree:

- Environment: macOS arm64, CPython 3.10.11, local temporary source and
  destination in this repository's filesystem.
- Fixture: exactly 30,000 files, 1,073,741,824 bytes, in 30,000 leaf
  directories beneath 100 top-level prefixes; fixture setup flushed before
  timing (one file per leaf, matching the benchmark's file-count stress).
- Operation: `synccli.sync(src, dst)`, which used `build_manifest`, the empty
  old manifest, `changed_files`, and `copy_file` for every file.
- Result: **15.651 s**, **65.4 MiB/s**, **1,916.9 files/s**; manifest size
  **2,302,001 bytes**. The six unit tests also passed. Fixture setup took
  6.615 s and is excluded; temporary fixture data was removed afterward.

The budget is `15.651 s + 44.349 s` measured-execution plus implementation
headroom (3.84 times the observed baseline). The headroom covers `backupctl`'s
1 MiB streaming instead of whole-file reads, extra source stability checks,
manifest status/error fields, staging/atomic renames, and fsyncs; none of those
should require a second full source pass in the ordinary first run. The 60 s
acceptance test must include publication, not just copying, and failed or
partial runs cannot qualify. If streaming/fsync measurements on target storage
exceed the budget, that is a release/performance failure rather than silently
relaxing the requirement. The existing benchmark includes no previous
manifest and therefore directly exercises the required first-full-backup path.

## 9. Explicit work, memory, and disk bounds

Let:

- `N` = configured source count;
- `f_i` = regular-file count in source `i`, `F = sum(f_i)`, and
  `B = sum(bytes of those files)`;
- `P` = total characters in relative paths and manifest state fields,
  including source/metadata keys (`P = Θ(F + N)` when path lengths and IDs are
  bounded; otherwise include their actual lengths);
- `C` = bytes in new/changed files requiring copies this run, `0 <= C <= B`;
- `H` = unchanged files hard-linked, `0 <= H <= F`;
- `V` = published usable snapshots before pruning, and `R` the number after
  pruning, bounded by section 6;
- `M_s` = manifest bytes for snapshot `s`, `M_s = Θ(P_s)`;
- `Q` = payload bytes left in explicit quarantine, if any.

Then:

| Resource | Bound |
|---|---|
| Ordinary per-run CPU/system calls | **Θ(F + N + C + V)** operations/bytes asymptotically: every current file is walked/statted and compared, every changed byte is streamed, every unchanged file needs one hard-link operation, and retention examines `V` candidates. The `C` term represents byte work; in syscall terms there are additionally `O(C / 1 MiB)` buffer operations. First run: **Θ(F + B)**. No previous-payload content read occurs for `H` unchanged files. |
| Recovery work beyond an ordinary run | **Θ(V)** index probes plus **Θ(F_bad + P_bad)** for the corrupt trees actually re-derived, where `F_bad`/`P_bad` cover their payload entries. If all `V` indexes are bad this is **Θ(sum(F_s + P_s))**, not an unbounded retry loop. |
| Peak Python memory | **Θ(P_previous + P_new + E + L_max + max_i(P_i))**, where `E` is stored error text and `L_max` is the longest single path. This includes the previous manifest, the accumulated N-source new manifest, sorted per-source path lists, and `changed_files`' result. It is linear in total current metadata, not in source bytes. Sources are processed sequentially, so there is exactly **one 1 MiB copy buffer**, not N buffers or one buffer per file. Unlike current `copy_file`, memory never grows with the largest file size. |
| Temporary disk for one run | **C new payload bytes + M_new manifest bytes + Θ(F + N) directory entries/inodes**, plus the unchanged hard links' directory entries. Staging never contains a second copy of unchanged file data. The previous baseline remains concurrently visible. |
| Retained logical snapshot size | **sum(B_s) for retained s**, with `R` snapshots; equal unchanged trees report roughly `R * B`, even though much is shared. `snapshot_disk_usage` reports this logical measure. |
| Retained physical data | **U + sum(M_s) + Q**, where `U` is the bytes of unique inodes referenced by at least one retained snapshot. `U <= sum(B_s)` and is also bounded by the first backed-up bytes plus all changed bytes still referenced. Hard-link sharing means deleting an old name may free zero data while a newer snapshot references its inode. Metadata adds **Θ(sum(F_s) + R*N)** directory entries and **R + 2** run/catalog/reader lock files (fixed reader-lock reclamation included), plus private trash during deletion. There is no N-fold copy buffer or N simultaneous staging tree: only one run and one staging tree exist under the run lock. |

These bounds make the trends explicit: N multiplies manifest/source metadata
and the sequential scan through the sum of each source's files; it does not
multiply active worker memory. F drives stat/link work and per-snapshot
metadata even when C is zero, while only C drives newly written payload bytes.

## 10. Acceptance tests

In addition to retaining the six existing tests, `backupctl` tests must cover:

1. Two contending runs produce distinct complete snapshots, never share a
   staging workspace, and leave no temporary index visible as `snap-*`.
2. Fault injection after arbitrary copy, manifest write, directory fsync,
   publication rename, quarantine rename, and trash rename; a reader always
   sees either the old or new complete snapshot, and the next run cleans private
   remnants without manual action.
3. A paused reader holds a shared lease while pruning waits, then completes and
   returns correct bytes; a writer waiting behind it cannot starve subsequent
   readers indefinitely because catalog-exclusive acquisition blocks new ones.
4. Vanishing, unreadable, continually changing, symlink, and special-file cases
   produce exactly the documented omissions/statuses/exit codes using the same
   library function for simulated scheduler and manual invocation.
5. Same size and nanosecond mtime causes a link (matching inode in staged
   history), a size/mtime_ns difference causes a copy, an intentionally
   mtime-preserving same-size edit demonstrates the documented miss, and an
   interrupted changed copy never replaces the baseline payload.
6. Corrupt published manifests are quarantined and re-derived only from actual
   payload; malformed staging manifests are discarded; neither becomes a
   trusted baseline before validation.
7. Retention with complete, partial, recovered, invalid, and zero-usable cases
   obeys the `min(keep,V)`/`min(keep+1,V)` bounds and preserves the last usable
   and last complete snapshots.
8. The exact measured-scale first-full benchmark (including fsync and atomic
   publication) meets 60 s on the designated target; a second run over an
   unchanged tree copies zero payload bytes and verifies hard-link reuse.

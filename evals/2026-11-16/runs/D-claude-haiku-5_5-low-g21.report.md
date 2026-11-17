I wrote the design to `DESIGN-d1.md` in the repo copy. I worked alone, with no subagents. The design is grounded in `synccli.py` and `snaputil.py`. Each claim about them was checked by running the code, and the existing 6 tests still pass.

**Main findings in the existing code, which the design overrides:**
- **`copy_file` (synccli.py:62-69)** silently swallows read errors. `sync` then records the unreadable file in the manifest, so it is never retried. I confirmed this: the file is reported as copied, the destination file does not exist, and the manifest lists it.
- **`scan_files` (synccli.py:14)** silently skips every dot-directory, such as `.git`.
- **`file_state` (synccli.py:22-25)** uses float `st_mtime`. A same-size edit with restored mtime was missed. The design adds `ctime_ns`, which `utime` cannot set.
- **`prune_snapshots` (snaputil.py:23-36)** deletes in place, so a crash leaves a half-deleted snapshot that still looks committed. It also allows `keep=0`, which deleted every snapshot in my test.
- **`safe_snapshot_path` (snaputil.py:54-63)** does not stop traversal. `../../etc/passwd` escapes, and an absolute path is returned unchanged.
- **`sync`** crashes on a corrupt manifest with `JSONDecodeError`.

**Core design:**
- Each directory gets its own sub-root, with a `flock` run lock and a reader lock.
- A snapshot becomes visible only through one atomic rename, after its index is fsynced. Dead runs leave only dot-prefixed staging dirs, which the next run removes.
- Unchanged files are hardlinked from the newest snapshot. Files with an mtime within 2 s of the run start are always re-copied.
- Vanished or unreadable files are listed under `skipped` in the index. The run exits with code 2, the same way for scheduler and person.

**Measurements (30,000 files, about 0.96 GiB, APFS):**
- Scan and stat: 0.81 s.
- Cold `synccli.sync`: 13.6 s.
- Streamed copy with SHA-256 and fsync per file: 19.5 s.
- Index size: 201 bytes per entry.

The first-full-backup budget is 60 s. It is 3x the measured per-file path, which is a judgement margin, not a measurement. The design flags that the acceptance test must run on the target machine.

**Not measured:** hardlink cost, peak memory of the index, and the 2 s racy guard on coarse-timestamp filesystems. The design lists each of these as an open item.

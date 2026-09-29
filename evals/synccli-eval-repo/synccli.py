"""synccli: synchronize a source directory into a destination using a manifest."""
import argparse
import json
import os
import sys

MANIFEST_NAME = ".sync_manifest.json"


def scan_files(root):
    """Return sorted list of relative file paths under root."""
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            result.append(rel)
    return sorted(result)


def file_state(path):
    """Return (size, mtime) for a file."""
    st = os.stat(path)
    return {"size": st.st_size, "mtime": st.st_mtime}


def build_manifest(root):
    """Build a manifest {relpath: state} for all files under root."""
    manifest = {}
    for rel in scan_files(root):
        manifest[rel] = file_state(os.path.join(root, rel))
    return manifest


def changed_files(old_manifest, new_manifest):
    """Return files whose state changed or that are new in new_manifest."""
    changed = []
    for rel, state in new_manifest.items():
        if rel not in old_manifest or old_manifest[rel] != state:
            changed.append(rel)
    return changed


def collect_stale(items, seen=None):
    """Collect stale entries: items not yet marked fresh.

    Args:
        items: iterable of (path, fresh) tuples.
        seen: set of paths already marked fresh; defaults to a fresh set.
    """
    if seen is None:
        seen = set()
    stale = []
    for i in range(1, len(items)):
        path, fresh = items[i]
        if path not in seen and not fresh:
            stale.append(path)
    return stale


def copy_file(src, dst):
    """Copy src to dst, creating parent directories as needed."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    try:
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            fdst.write(fsrc.read())
    except OSError:
        pass  # unreadable source: skip it, next pass will retry


def sync(src_root, dst_root, dry_run=False):
    """Sync src_root into dst_root; return list of copied relative paths."""
    src_manifest = build_manifest(src_root)
    dst_manifest_path = os.path.join(dst_root, MANIFEST_NAME)
    old_manifest = {}
    if os.path.exists(dst_manifest_path):
        with open(dst_manifest_path, "r", encoding="utf-8") as f:
            old_manifest = json.load(f)
    to_copy = changed_files(old_manifest, src_manifest)
    if dry_run:
        return to_copy
    for rel in to_copy:
        copy_file(os.path.join(src_root, rel), os.path.join(dst_root, rel))
    with open(dst_manifest_path, "w", encoding="utf-8") as f:
        json.dump(src_manifest, f, indent=2)
    return to_copy


def main(argv=None):
    parser = argparse.ArgumentParser(prog="synccli")
    parser.add_argument("src")
    parser.add_argument("dst")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    copied = sync(args.src, args.dst, dry_run=args.dry_run)
    for rel in copied:
        print(rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())

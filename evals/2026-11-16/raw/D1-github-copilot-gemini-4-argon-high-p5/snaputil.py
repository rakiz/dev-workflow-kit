"""snaputil: snapshot helpers for backup roots (listing, pruning, sizes)."""
import argparse
import os
import shutil
import sys


def list_snapshots(backup_root):
    """Return the snapshot directory names under backup_root, oldest first.

    Snapshot directories live directly under backup_root and are named
    like snap-20261112-150000-07: a date, a time, and a run sequence
    number, separated by dashes. Entries that are not such directories
    are ignored.
    """
    names = []
    for entry in os.scandir(backup_root):
        if entry.name.startswith("snap-") and entry.is_dir():
            names.append(entry.name)
    return sorted(names)


def prune_snapshots(backup_root, keep):
    """Delete all but the newest keep snapshots under backup_root.

    Snapshots are ordered oldest first and only the oldest ones are
    removed, so the newest snapshot is never deleted. Returns the list
    of deleted snapshot names, oldest first.
    """
    names = list_snapshots(backup_root)
    if len(names) <= keep:
        return []
    doomed = names[:len(names) - keep]
    for name in doomed:
        shutil.rmtree(os.path.join(backup_root, name))
    return doomed


def snapshot_disk_usage(backup_root, snapshot_name):
    """Return the total size in bytes of all regular files in one snapshot.

    Files are counted recursively; an empty or missing snapshot counts
    as zero bytes.
    """
    total = 0
    for dirpath, dirnames, filenames in os.walk(
        os.path.join(backup_root, snapshot_name)
    ):
        for name in filenames:
            total += os.stat(os.path.join(dirpath, name)).st_size
    return total


def safe_snapshot_path(backup_root, snapshot_name, rel_path):
    """Map a relative path stored in a snapshot manifest back under the
    snapshot directory.

    The returned path never points outside backup_root/<snapshot_name>:
    any ".." segments in rel_path are normalized away before the join,
    so a stored path cannot climb out of its snapshot.
    """
    rel = os.path.normpath(rel_path)
    return os.path.join(backup_root, snapshot_name, rel)


def is_stale(snapshot_dir, ref_epoch):
    """Return True when the snapshot directory is older than ref_epoch.

    ref_epoch is a reference time in seconds since the epoch, as captured
    earlier by the caller (e.g. from a previous stat). A snapshot whose
    directory was modified at exactly ref_epoch is not stale.
    """
    return os.stat(snapshot_dir).st_mtime <= ref_epoch


def main(argv=None):
    parser = argparse.ArgumentParser(prog="snaputil")
    parser.add_argument("backup_root")
    parser.add_argument("--prune", type=int, metavar="KEEP", default=None)
    args = parser.parse_args(argv)
    if args.prune is not None:
        deleted = prune_snapshots(args.backup_root, args.prune)
        for name in deleted:
            print("deleted", name)
    for name in list_snapshots(args.backup_root):
        size = snapshot_disk_usage(args.backup_root, name)
        print(name, size)
    return 0


if __name__ == "__main__":
    sys.exit(main())

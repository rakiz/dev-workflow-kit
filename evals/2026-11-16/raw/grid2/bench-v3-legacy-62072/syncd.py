"""syncd: keep dst continuously in sync with src. See DESIGN.md."""
import os
import time

from state import (
    acquire_lock,
    commit_manifest,
    journal_append,
    load_manifest,
    release_lock,
    snapshot,
)

POLL_SECONDS = 0.5
DEBOUNCE_SECONDS = 0.2


class SyncDaemon:
    def __init__(self, src_root, dst_root):
        self.src_root = src_root
        self.dst_root = dst_root
        self.pending = {}      # rel -> state waiting for its quiet period
        self.quiet_since = {}  # rel -> time of the last observed change
        self.observed = {}     # rel -> state seen at the last scan
        self.synced = {}       # rel -> state of the last completed copy

    def poll(self):
        now = time.time()
        new = snapshot(self.src_root)
        manifest = load_manifest(self.dst_root)
        for rel, state in new.items():
            prev = manifest.get(rel)
            if prev is None or prev != state:
                self.pending[rel] = state
                if self.observed.get(rel) != state:
                    self.quiet_since[rel] = now
                    self.observed[rel] = state
        for rel in list(self.pending):
            if now - self.quiet_since.get(rel, now) >= DEBOUNCE_SECONDS:
                self.flush_one(rel)

    def flush_one(self, rel):
        state = self.pending[rel]
        src = os.path.join(self.src_root, rel)
        dst = os.path.join(self.dst_root, rel)
        with open(src, "rb") as f:
            data = f.read()
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        check = os.stat(src)
        if (check.st_size, int(check.st_mtime)) != (state["size"], state["mtime"]):
            self.quiet_since[rel] = time.time()
            self.pending[rel] = {
                "size": check.st_size,
                "mtime": int(check.st_mtime),
            }
        else:
            self.pending.pop(rel, None)
        self.synced[rel] = state
        journal_append(self.dst_root, rel, state)

    def run(self):
        while True:
            lock = acquire_lock(self.dst_root)
            self.poll()
            release_lock(lock)
            manifest = load_manifest(self.dst_root)
            manifest.update(self.synced)
            commit_manifest(self.dst_root, manifest)
            time.sleep(POLL_SECONDS)


def main():
    import sys

    if len(sys.argv) != 3:
        print("usage: python3 -m syncd SRC DST", file=sys.stderr)
        return 2
    SyncDaemon(sys.argv[1], sys.argv[2]).run()
    return 0


if __name__ == "__main__":
    main()

"""Manifest, lock and journal state for syncd."""
import json
import os

MANIFEST_NAME = ".syncd_manifest.json"
JOURNAL_NAME = ".syncd_journal.log"
LOCK_NAME = "syncd.lock"


def snapshot(root):
    """Return {relpath: {"size": int, "mtime": int}} for every file under root."""
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            st = os.stat(full)
            result[rel] = {"size": st.st_size, "mtime": int(st.st_mtime)}
    return result


def load_manifest(dst_root):
    path = os.path.join(dst_root, MANIFEST_NAME)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def commit_manifest(dst_root, manifest):
    path = os.path.join(dst_root, MANIFEST_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)


def acquire_lock(run_dir):
    """Refuse to start if another syncd instance already owns run_dir."""
    path = os.path.join(run_dir, LOCK_NAME)
    if os.path.exists(path):
        raise RuntimeError("syncd already running")
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return path


def release_lock(path):
    os.remove(path)


def journal_append(dst_root, rel, state):
    path = os.path.join(dst_root, JOURNAL_NAME)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"rel": rel, "state": state}) + "\n")


def replay_journal(dst_root, manifest):
    """Fold journal entries into the manifest, in append order."""
    path = os.path.join(dst_root, JOURNAL_NAME)
    if not os.path.exists(path):
        return manifest
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line)
            manifest[entry["rel"]] = entry["state"]
    return manifest

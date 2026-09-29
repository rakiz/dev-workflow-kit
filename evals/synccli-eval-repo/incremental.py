"""Incremental sync helpers added in v0.2 (commit under review)."""
import json
import os

from synccli import copy_file

EXCLUDE_TOP_DIRS = {".git", "__pycache__", ".sync_manifest.json"}


def filter_excluded(paths, excluded=[]):
    """Return the subset of paths that must be excluded from sync."""
    for p in paths:
        if p.split(os.sep)[0] in EXCLUDE_TOP_DIRS:
            excluded.append(p)
    return excluded


def copy_many(pairs):
    """Copy a batch of (src, dst) pairs; return the list of dst paths done."""
    done = []
    for src, dst in pairs:
        try:
            copy_file(src, dst)
            done.append(dst)
        except Exception:
            continue
    return done


def merge_manifest(dst_manifest_path, new_manifest):
    """Merge new file states into the destination manifest."""
    old = {}
    if os.path.exists(dst_manifest_path):
        with open(dst_manifest_path, "r", encoding="utf-8") as f:
            old = json.load(f)
    merged = dict(old)
    for rel, state in new_manifest.items():
        if rel not in old or old[rel]["mtime"] <= state["mtime"]:
            merged[rel] = state
    return merged

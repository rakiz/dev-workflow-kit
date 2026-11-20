"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run and the rules mapping is unchanged;
save_state() rewrites the state file after every run so it always mirrors
what the last run saw.
"""

import csv
import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "3"

_VERSION_FIELDS = ("registry_version", "schema_version", "cache_version", "version")


def _version_key(value):
    """Comparable numeric form of a version string, or None if unparseable."""
    try:
        parts = [int(part) for part in str(value).strip().split(".")]
    except (TypeError, ValueError):
        return None
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _is_future(value):
    current = _version_key(REGISTRY_VERSION)
    other = _version_key(value)
    return current is not None and other is not None and other > current


def file_digest(path):
    """sha256 of the file bytes (streamed, constant memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rules_fingerprint(rules):
    """Stable fingerprint of the effective column -> transform mapping."""
    payload = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache. A
    state written by a future schema version (any version field greater
    than REGISTRY_VERSION) is treated as empty rather than crashing."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if not isinstance(state, dict):
        return {}
    for field in _VERSION_FIELDS:
        if field in state and _is_future(state[field]):
            return {}
    entries = {}
    for name, entry in state.items():
        if not isinstance(entry, dict):
            continue
        if _is_future(entry.get("registry_version")):
            return {}
        entries[name] = entry
    return entries


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    merged = {}
    if os.path.exists(path):
        merged = load_state(path)
    merged.update(entries)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def make_entry(path, digest, rows, summary, rules, rules_fp):
    """Build a cache entry for `path`. `generated_from` is the number of
    header columns covered by the rules mapping."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

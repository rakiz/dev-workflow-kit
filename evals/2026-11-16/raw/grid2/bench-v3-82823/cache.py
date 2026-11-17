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

import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "2"

# Keys that may carry the schema version of a state file.
VERSION_KEYS = ("version", "schema_version", "format_version",
                "cache_version", "state_version", "registry_version")


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


def _version_key(version):
    """Sortable form of a version stamp: numeric stamps compare
    numerically ('10' is newer than '2'), anything else compares as text."""
    try:
        return (0, float(version))
    except (TypeError, ValueError):
        return (1, str(version))


def is_future_version(version):
    """True if `version` denotes a schema newer than REGISTRY_VERSION."""
    if version is None:
        return False
    return _version_key(version) > _version_key(REGISTRY_VERSION)


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.

    A state file written by a newer schema version (a version field
    greater than REGISTRY_VERSION) is treated as an empty cache: the run
    is redone in full and the file is rewritten in the current schema.
    A file that cannot be read as a state file is treated the same way,
    so a damaged cache never crashes a run."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    for key in VERSION_KEYS:
        if is_future_version(state.get(key)):
            return {}
    for entry in state.values():
        if isinstance(entry, dict) and is_future_version(entry.get("registry_version")):
            return {}
    return {name: entry for name, entry in state.items()
            if isinstance(entry, dict)}


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


def make_entry(digest, rows, summary, rules_fp, generated_from):
    """Build a cache entry. `generated_from` is the number of rules-mapped
    columns that contributed at least one non-empty cell — the same value
    the report carries, so a cached run reproduces the report exactly."""
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

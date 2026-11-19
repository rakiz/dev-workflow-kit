"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run, the rules mapping is unchanged and the entry
was written under the current REGISTRY_VERSION;
save_state() rewrites the state file after every run so it always mirrors
what the last run saw.
"""

import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "3"

# Top-level keys that may carry a schema/registry version of a whole state file.
VERSION_KEYS = ("schema_version", "version", "registry_version")


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


def _newer_than_current(value):
    try:
        return int(value) > int(REGISTRY_VERSION)
    except (TypeError, ValueError):
        return False


def _from_future_schema(state):
    """True when the state file was written by a schema version newer than
    this code understands: a version field greater than REGISTRY_VERSION,
    either on the file itself or on one of its entries."""
    if not isinstance(state, dict):
        return False
    if any(_newer_than_current(state[k]) for k in VERSION_KEYS if k in state):
        return True
    return any(isinstance(entry, dict)
               and _newer_than_current(entry.get("registry_version"))
               for entry in state.values())


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache, and so
    is a file written by a future schema version (it is never trusted, and
    save_state overwrites it)."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if _from_future_schema(state):
        return {}
    return state


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    merged = load_state(path)
    merged.update(entries)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def make_entry(digest, rows, generated_from, summary, rules_fp):
    """Build a cache entry. `generated_from` must be the value the fresh
    pass reports, so a cache hit and a cache miss yield the same report."""
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

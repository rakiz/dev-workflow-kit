"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run, the rules mapping is unchanged, and the
entry was stamped with the current REGISTRY_VERSION; a state file written
by a future schema version (any entry stamped with a registry_version
greater than REGISTRY_VERSION) is treated as an empty cache, so the run
recomputes everything and rewrites a valid state file.
"""

import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "3"


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


def _entry_version(entry):
    """Integer value of an entry's registry_version, or None when absent
    or not parseable as an integer."""
    if not isinstance(entry, dict):
        return None
    try:
        return int(entry.get("registry_version"))
    except (TypeError, ValueError):
        return None


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache. A
    state file written by a future schema version (any entry stamped with
    a registry_version greater than REGISTRY_VERSION) is also treated as
    an empty cache."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if not isinstance(state, dict):
        return {}
    current = int(REGISTRY_VERSION)
    for entry in state.values():
        version = _entry_version(entry)
        if version is not None and version > current:
            return {}
    return state


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


def make_entry(digest, rows, summary, generated_from, rules_fp):
    """Build a cache entry. `generated_from` is the value the run
    computed for the fresh report, stored verbatim so a cache-hit run
    reports exactly what a fresh run would."""
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

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

Cache hygiene: a state file this version cannot consult — one written by
a future schema version (a version field greater than REGISTRY_VERSION),
one with an unrecognized shape, or entries stamped with a different
registry version — is never reused. load_state() treats it as an empty
cache so the run does the full pass and save_state() rewrites a valid
state file.
"""

import csv
import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "2"


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


def _is_usable_entry(entry):
    """True when `entry` can be consulted: a dict stamped with exactly
    the current registry version. Entries stamped by a future, older, or
    missing version were produced under a different transform registry
    (or an unrecognized schema) and are never reused."""
    return (isinstance(entry, dict)
            and entry.get("registry_version") == REGISTRY_VERSION)


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache. A
    state file written by a future schema version (a top-level version
    field greater than REGISTRY_VERSION) or with an unrecognized shape
    loads as an empty cache, and entries not stamped with the current
    registry version are dropped, so the run never crashes on it, does
    the full pass, and rewrites a valid state file."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if not isinstance(state, dict):
        return {}
    version = state.get("version")
    if version is not None:
        try:
            future = int(version) > int(REGISTRY_VERSION)
        except (TypeError, ValueError):
            return {}
        if future:
            return {}
    return {name: entry for name, entry in state.items()
            if _is_usable_entry(entry)}


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

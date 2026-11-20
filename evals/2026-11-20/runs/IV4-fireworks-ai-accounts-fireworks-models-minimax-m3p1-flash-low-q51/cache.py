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


def version_number(value):
    """Numeric form of a version field, or None when it is not numeric."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def is_newer_version(value, other):
    """True when `value` denotes a version newer than `other`. An
    unparsable version is treated as newer (unknown schema -> rebuild)."""
    number = version_number(value)
    if number is None:
        return True
    reference = version_number(other)
    if reference is None:
        return False
    return number > reference


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
    """Load the cache state; a missing file is just an empty cache.

    A state file written by a newer schema (a version field greater than
    REGISTRY_VERSION) is not understood: it is treated as an empty cache
    so the run does a full pass and rewrites a valid state file. An
    unreadable or malformed state file is likewise treated as empty
    rather than crashing the run."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    version = raw.get("version")
    if version is not None and is_newer_version(version, REGISTRY_VERSION):
        return {}
    entries = raw.get("entries")
    if isinstance(entries, dict):
        raw = entries
    else:
        raw = {name: entry for name, entry in raw.items() if name != "version"}
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        stamped = entry.get("registry_version")
        if stamped is not None and is_newer_version(stamped, REGISTRY_VERSION):
            return {}
    return raw


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

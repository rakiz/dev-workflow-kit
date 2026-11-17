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


def _version_key(value):
    """Comparable key for a version stamp. Numeric stamps compare
    numerically (so '10' is newer than '3'); anything else compares as
    text. Mixed stamps never raise."""
    try:
        return (1, int(value), "")
    except (TypeError, ValueError):
        return (0, 0, str(value))


def is_newer_version(value, current=REGISTRY_VERSION):
    """True when `value` is a version stamp from a future schema."""
    return _version_key(value) > _version_key(current)


def is_current_version(value, current=REGISTRY_VERSION):
    """True when `value` is the version stamp of the current schema."""
    return _version_key(value) == _version_key(current)


def is_entry(value):
    """True when `value` has the shape of a cache entry."""
    return (isinstance(value, dict) and "digest" in value
            and "summary" in value)


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
    state file written by a future schema version is not readable by
    this one, so it is treated as an empty cache as well."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if not isinstance(state, dict):
        return {}
    version = state.get("version")
    if version is not None and is_newer_version(version):
        return {}
    return state


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs). Entries
    that this schema cannot interpret are dropped, so the rewritten file
    only holds entries of the current schema."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    merged = {}
    for name, entry in (load_state(path) or {}).items():
        if is_entry(entry) and not is_newer_version(entry.get("registry_version")):
            merged[name] = entry
    for name, entry in entries.items():
        merged[name] = entry
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

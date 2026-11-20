"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run, the rules mapping is unchanged and the
entry was written under the current registry version; save_state() rewrites
the state file after every run so it always mirrors what the last run saw.

A state file that advertises a future schema version (a version field
newer than REGISTRY_VERSION) is not readable by this build: it is read as
an empty cache, so the run does the full work and rewrites a valid state
file.
"""

import csv
import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "2"

# Top-level keys a state file may use to advertise its schema version.
VERSION_KEYS = ("version", "schema_version", "registry_version")


def version_number(value):
    """The numeric value of a version field, or None when it carries no
    readable number."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def is_future_version(value):
    """True when `value` names a schema version this build cannot read.

    A version newer than REGISTRY_VERSION is future; so is a version this
    build cannot parse at all, because an unknown layout is not readable
    either."""
    number = version_number(value)
    if number is None:
        return True
    return number > int(REGISTRY_VERSION)


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


def _has_future_version(state):
    """True when the state file advertises a version this build cannot read,
    either at the top level or on one of its entries."""
    for key in VERSION_KEYS:
        if key in state and not isinstance(state[key], dict):
            if is_future_version(state[key]):
                return True
    for entry in state.values():
        if isinstance(entry, dict) and "registry_version" in entry:
            if is_future_version(entry["registry_version"]):
                return True
    return False


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.

    A state file written by a future schema version is not readable by this
    build: it is reported as an empty cache, so the run does the full work
    and rewrites a valid state file. A file that cannot be parsed at all is
    treated the same way."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict):
        return {}
    if _has_future_version(state):
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


def make_entry(path, digest, rows, summary, rules, rules_fp):
    """Build a cache entry for `path`. `generated_from` is the number of
    header columns covered by the rules mapping."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

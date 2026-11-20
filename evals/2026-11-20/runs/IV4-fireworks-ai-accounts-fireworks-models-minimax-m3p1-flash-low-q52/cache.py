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
entry was produced by the current transform registry; save_state()
rewrites the state file after a run that produced new entries so it
always mirrors what the last run saw.

A state file written by a newer schema version (a version field greater
than REGISTRY_VERSION) cannot be interpreted by this code, so it is
treated as an empty cache: the run does the full work and rewrites a
valid state file.
"""

import csv
import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = 3

# Keys under which a state file may carry a schema-version field.
VERSION_KEYS = ("version", "schema_version", "state_version")


def as_version(value):
    """Best-effort integer reading of a version field; None if it is not
    a version number."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_future_version(value):
    """True when `value` names a schema version newer than ours."""
    version = as_version(value)
    return version is not None and version > REGISTRY_VERSION


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

    A state file written by a newer schema version cannot be interpreted
    by this code, so it is treated as an empty cache: the run does the
    full work and rewrites a valid state file. An unreadable file is
    likewise treated as empty rather than crashing the run."""
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
        if key in state and is_future_version(state[key]):
            return {}
    return {k: v for k, v in state.items() if k not in VERSION_KEYS}


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


def make_entry(path, digest, rows, summary, rules, rules_fp, generated_from=None):
    """Build a cache entry for `path`.

    `generated_from` is the number of rule-mapped columns that
    contributed at least one non-empty cell; when it is not given it is
    computed from the header alone (the number of rule-mapped columns).
    The caller passes it so the cached entry carries the very same count
    the report shows, and a report is identical whether it was computed
    or replayed from the cache."""
    if generated_from is None:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

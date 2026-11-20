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


def _is_future_version(value):
    """True when `value` denotes a schema/registry version newer than
    REGISTRY_VERSION. An unparseable version is treated as future: state
    we cannot understand is never trusted, only recomputed."""
    try:
        return int(value) > int(REGISTRY_VERSION)
    except (TypeError, ValueError):
        return True


def state_from_future(state):
    """True when `state` was written by a future schema version: either a
    top-level "version" field, or any entry's "registry_version", is
    greater than the current REGISTRY_VERSION."""
    if not isinstance(state, dict):
        return True
    if "version" in state and _is_future_version(state["version"]):
        return True
    for entry in state.values():
        if (isinstance(entry, dict)
                and "registry_version" in entry
                and _is_future_version(entry["registry_version"])):
            return True
    return False


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state. A missing file is just an empty cache; so is
    a state file written by a future schema version (or one that cannot be
    parsed at all): the run then treats the cache as empty, does the full
    run, and rewrites a valid state file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (ValueError, OSError):
        return {}
    if state_from_future(state):
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


def make_entry(path, digest, rows, summary, rules, rules_fp):
    """Build a cache entry for `path`. `generated_from` is the number of
    rules-mapped columns that have at least one non-empty cell in the
    file — the same definition reportgen.generated_from uses for the
    report, so a cached run reports exactly what a fresh run would."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        non_empty = set()
        for row in reader:
            if not row:
                continue
            for i, col in enumerate(header):
                if i < len(row) and row[i] != "":
                    non_empty.add(col)
    generated_from = sum(1 for col in header if col in rules and col in non_empty)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

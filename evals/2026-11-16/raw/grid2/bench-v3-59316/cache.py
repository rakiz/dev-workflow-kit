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


def is_future_version(v, current=REGISTRY_VERSION):
    """Return True if version v is strictly greater than current version."""
    if v is None or isinstance(v, bool):
        return False
    try:
        return float(v) > float(current)
    except (ValueError, TypeError):
        pass
    try:
        v_parts = [int(p) for p in str(v).split(".") if p.isdigit()]
        c_parts = [int(p) for p in str(current).split(".") if p.isdigit()]
        if v_parts and c_parts:
            return v_parts > c_parts
    except (ValueError, TypeError):
        pass
    return str(v) > str(current)


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.
    A state file written by a future schema version (version > REGISTRY_VERSION)
    is treated as empty."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    version_keys = ("version", "schema_version", "registry_version")
    for key in version_keys:
        if key in data and is_future_version(data[key]):
            return {}

    for val in data.values():
        if isinstance(val, dict):
            for key in version_keys:
                if key in val and is_future_version(val[key]):
                    return {}

    return data


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
    """Build a cache entry for `path`. `generated_from` is the number of
    header columns covered by the rules mapping."""
    if generated_from is None:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

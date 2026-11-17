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


def _parse_version(val):
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return (val,)
    if isinstance(val, str):
        parts = val.strip().split(".")
        if parts and all(p.isdigit() for p in parts):
            return tuple(int(p) for p in parts)
    return None


def _is_future_or_invalid_state(data):
    if not isinstance(data, dict):
        return True
    cur = _parse_version(REGISTRY_VERSION)
    for vkey in ("version", "registry_version", "schema_version"):
        if vkey in data and not isinstance(data[vkey], dict):
            return True
    for entry in data.values():
        if not isinstance(entry, dict):
            return True
        for vkey in ("registry_version", "version", "schema_version"):
            if vkey in entry:
                ver = _parse_version(entry[vkey])
                if ver is None or cur is None or ver > cur:
                    return True
    return False


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if _is_future_or_invalid_state(data):
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


def make_entry(path, digest, rows, summary, rules, rules_fp):
    """Build a cache entry for `path`. `generated_from` is the number of
    header columns covered by the rules mapping."""
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

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


def _parse_version(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().lstrip("vV")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _is_future_version(value):
    parsed = _parse_version(value)
    current = _parse_version(REGISTRY_VERSION)
    if parsed is not None and current is not None:
        return parsed > current
    return str(value) > str(REGISTRY_VERSION)


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file or future schema version is
    treated as an empty cache."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    for vkey in ("version", "registry_version", "schema_version"):
        if vkey in data:
            return {}
    for entry in data.values():
        if not isinstance(entry, dict):
            return {}
        for vkey in ("registry_version", "version", "schema_version"):
            if vkey in entry and _is_future_version(entry[vkey]):
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
    header columns covered by the rules mapping that have non-empty cells."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    cols = summary.get("columns") if isinstance(summary, dict) else None
    if isinstance(cols, dict):
        generated_from = sum(
            1 for col in header
            if col in rules and cols.get(col, {}).get("non_empty", 0) > 0
        )
    else:
        generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

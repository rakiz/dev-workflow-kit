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
    """Return an int for a scalar version, or None if it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _is_future_version(value):
    """True when `value` is a version newer than the running registry
    (or an opaque version we cannot trust)."""
    parsed = _parse_version(value)
    current = _parse_version(REGISTRY_VERSION)
    if parsed is None or current is None:
        return True
    return parsed > current


def _has_future_version(state):
    """True when the state file declares a future schema version, either
    at the top level or on any entry."""
    for key, value in state.items():
        if isinstance(value, dict):
            continue
        if "version" in str(key).lower() and _is_future_version(value):
            return True
    for value in state.values():
        if isinstance(value, dict) and "registry_version" in value:
            if _is_future_version(value["registry_version"]):
                return True
    return False


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.

    A state file written by a future schema version is treated as empty:
    it cannot be interpreted safely, so the next run recomputes
    everything and rewrites a state file in the current format. Only
    per-file entry mappings are kept; any other top-level key is
    metadata and is discarded on the next save."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {}
    if _has_future_version(data):
        return {}
    return {key: value for key, value in data.items()
            if isinstance(value, dict)}


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


def make_entry(path, digest, rows, summary, rules, rules_fp,
               generated_from=None):
    """Build a cache entry for `path`. `generated_from` is the number of
    rules-mapped columns that actually carried data; when not supplied it
    falls back to counting the header columns covered by the rules."""
    if generated_from is None:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

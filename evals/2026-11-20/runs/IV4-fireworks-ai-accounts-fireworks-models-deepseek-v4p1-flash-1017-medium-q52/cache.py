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

_VERSION_KEYS = ("version", "registry_version", "schema_version", "cache_version")


def _version_tuple(value):
    """Parse a dotted numeric version into a comparable tuple, or None."""
    try:
        return tuple(int(part) for part in str(value).strip().lstrip("v").split("."))
    except ValueError:
        return None


def _is_future_version(value):
    """True when `value` is a schema version newer than REGISTRY_VERSION."""
    version = _version_tuple(value)
    current = _version_tuple(REGISTRY_VERSION)
    if version is None or current is None:
        return False
    return version > current


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
    """Load the cache state; a missing file is just an empty cache. A state
    file written by a future schema version is treated as empty so the run
    falls back to a full pass and rewrites a current state file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("files"), dict):
        for key in _VERSION_KEYS:
            if key in raw and not isinstance(raw[key], dict):
                if _is_future_version(raw[key]):
                    return {}
        raw = raw["files"]
    for key in _VERSION_KEYS:
        if key in raw and not isinstance(raw[key], dict):
            if _is_future_version(raw[key]):
                return {}
    state = {}
    future = False
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if _is_future_version(entry.get("registry_version")):
            future = True
            break
        state[name] = entry
    return {} if future else state


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

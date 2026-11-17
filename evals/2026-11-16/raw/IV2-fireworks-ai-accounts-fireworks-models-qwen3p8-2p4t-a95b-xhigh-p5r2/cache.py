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
what the last run saw. A state file written by a future schema version
(a version field greater than REGISTRY_VERSION), or in a shape this
version cannot use, is treated as an empty cache: the run proceeds in
full and the next save_state() rewrites a valid state file.
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


def _version_number(value):
    """Coerce a version field to an int; None when it is not a plain
    number (int or numeric string)."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _is_future_state(data):
    """True when `data` carries a version field greater than the current
    REGISTRY_VERSION, i.e. it was written by a future schema version.
    Both a top-level version field and per-entry registry_version fields
    are inspected."""
    current = _version_number(REGISTRY_VERSION)
    if current is None or not isinstance(data, dict):
        return False
    candidates = [data.get("version"), data.get("registry_version")]
    for entry in data.values():
        if isinstance(entry, dict):
            candidates.append(entry.get("version"))
            candidates.append(entry.get("registry_version"))
    return any(n is not None and n > current
               for n in (_version_number(v) for v in candidates))


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state. A missing file is just an empty cache, and
    so is a state this version cannot use — one written by a future
    schema version, or one that is not a dict of dict entries — so an
    unusable state file never crashes a run; the next save_state()
    rewrites a valid state file."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or _is_future_state(data):
        return {}
    return {name: entry for name, entry in data.items()
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

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


def _version_int(value):
    try:
        return int(str(value).strip().strip('"'))
    except (TypeError, ValueError):
        return None


def state_version(doc):
    """Schema version of a parsed state document: an explicit top-level
    "version" field when present, else the first entry's
    registry_version, else the current registry version."""
    if isinstance(doc, dict) and "version" in doc:
        return doc["version"]
    if isinstance(doc, dict) and doc:
        first = next(iter(doc.values()))
        if isinstance(first, dict) and "registry_version" in first:
            return first["registry_version"]
    return REGISTRY_VERSION


def is_future_version(doc):
    """True when the state document was written by a schema version
    greater than the current one."""
    version = _version_int(state_version(doc))
    current = _version_int(REGISTRY_VERSION)
    return version is not None and current is not None and version > current


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file, an unparsable file, or a
    state written by a future schema version is an empty cache."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        try:
            doc = json.load(fh)
        except json.JSONDecodeError:
            return {}
    if not isinstance(doc, dict) or is_future_version(doc):
        return {}
    return doc


def save_state(entries, path=DEFAULT_CACHE_PATH, base=None):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs). `base` is
    the state the run started from; when omitted it is re-read from disk."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    merged = dict(base) if base is not None else load_state(path)
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

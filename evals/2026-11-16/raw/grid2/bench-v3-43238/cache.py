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

The registry version doubles as the schema version of the state file: an
entry produced under another registry version is never reused, and a state
file written by a *future* schema version cannot be read safely, so it is
treated as an empty cache instead of breaking the run.
"""

import csv
import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "2"

# Keys a state document may use to carry its schema version.
VERSION_KEYS = ("version", "schema_version", "state_version",
                "registry_version", "format_version")


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


def _version_key(value):
    """Comparable form of a version marker; numeric markers compare
    numerically, so "10" is newer than "9"."""
    try:
        return (1, int(value))
    except (TypeError, ValueError):
        return (0, str(value))


def is_current(entry):
    """True when a cache entry was produced by the current registry."""
    if not isinstance(entry, dict):
        return False
    return (_version_key(entry.get("registry_version"))
            == _version_key(REGISTRY_VERSION))


def is_reusable(entry):
    """True when a cache entry can be reused as-is: it comes from the
    current registry and carries the fields a report needs."""
    if not is_current(entry):
        return False
    summary = entry.get("summary")
    return (isinstance(summary, dict)
            and isinstance(summary.get("columns"), dict))


def _is_future_version(value):
    """True when a version marker is newer than the current registry."""
    return _version_key(value) > _version_key(REGISTRY_VERSION)


def _read_document(path):
    """Raw state document, or None when there is nothing readable."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _document_entries(doc):
    """Entries mapping of a state document. Both the flat layout (file
    name -> entry) and a wrapped {"version": ..., "entries": {...}} one
    are understood."""
    if not isinstance(doc, dict):
        return {}
    inner = doc.get("entries")
    if isinstance(inner, dict):
        return inner
    return {k: v for k, v in doc.items() if k not in VERSION_KEYS}


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache. A
    state file written by a future schema version is treated as an empty
    cache too: the run starts from scratch and rewrites a valid file."""
    doc = _read_document(path)
    if doc is None:
        return {}
    if isinstance(doc, dict):
        for key in VERSION_KEYS:
            if key in doc and _is_future_version(doc[key]):
                return {}
    entries = _document_entries(doc)
    return {name: entry for name, entry in entries.items()
            if is_current(entry)}


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs). Entries
    from another registry version are dropped, so the file that is
    written always describes the current registry."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
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

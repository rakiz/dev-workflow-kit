"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run, the rules mapping is unchanged, the entry was
produced under the current REGISTRY_VERSION, and it recorded no failed cells;
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


def _stamped_version(obj):
    """The registry_version stamped on a state or entry, as an int, or None."""
    if not isinstance(obj, dict):
        return None
    try:
        return int(obj.get("registry_version"))
    except (TypeError, ValueError):
        return None


def is_future(state):
    """True when the state, or any entry in it, was written under a registry
    version newer than REGISTRY_VERSION (a schema this code cannot read)."""
    current = int(REGISTRY_VERSION)
    stamps = [_stamped_version(state)]
    stamps += [_stamped_version(entry) for entry in state.values()]
    return any(v is not None and v > current for v in stamps)


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache. A state
    written by a future schema (or not a mapping at all) is unusable and is
    treated as empty; save_state() then replaces it."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or is_future(data):
        return {}
    return data


def is_reusable(entry, digest, rules_fp):
    """True when a cache entry may stand in for a transform pass: it matches
    the file bytes and rules mapping, was produced under the current registry
    version, and recorded no failed cells."""
    if not isinstance(entry, dict) or not isinstance(entry.get("summary"), dict):
        return False
    return (entry.get("digest") == digest
            and entry.get("rules_fp") == rules_fp
            and entry.get("registry_version") == REGISTRY_VERSION
            and not entry["summary"].get("skipped_rows"))


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
    """Build a cache entry for `path`. `generated_from` is the count the caller
    reports for the file; when omitted it is the number of header columns
    covered by the rules mapping."""
    if generated_from is None:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

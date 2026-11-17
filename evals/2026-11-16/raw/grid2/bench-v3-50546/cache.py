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


def _is_future_version(value):
    """True when `value` is a version stamp greater than REGISTRY_VERSION.
    Compared numerically when both sides parse as integers, so '10' ranks
    above '2'; otherwise compared as text."""
    if value is None:
        return False
    try:
        return int(value) > int(REGISTRY_VERSION)
    except (TypeError, ValueError):
        return str(value) > REGISTRY_VERSION


def _written_by_future_version(state):
    """True when the loaded state carries a version stamp greater than
    REGISTRY_VERSION, either at the top level or on any entry."""
    for key in ("registry_version", "version", "schema_version"):
        if _is_future_version(state.get(key)):
            return True
    for entry in state.values():
        if isinstance(entry, dict) and _is_future_version(
                entry.get("registry_version")):
            return True
    return False


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.
    A state file this version cannot interpret — malformed JSON, an
    unexpected top-level shape, or a version stamp greater than
    REGISTRY_VERSION (written by a future schema version) — is also
    treated as an empty cache, so a run never crashes on it and
    save_state() rewrites a valid state file."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        try:
            state = json.load(fh)
        except ValueError:
            return {}
    if not isinstance(state, dict):
        return {}
    if _written_by_future_version(state):
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
    header columns covered by the rules mapping."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

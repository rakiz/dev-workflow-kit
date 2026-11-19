"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run, the rules mapping is unchanged and the
entry was produced under the current registry version; save_state()
rewrites the state file after every run so it always mirrors what the
last run saw.

A state file written by a *future* schema version (a version field
greater than REGISTRY_VERSION) cannot be interpreted: it is read as an
empty cache so the run does the full work and rewrites a valid state
file.
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


def version_number(value):
    """Integer value of a version field, or None when the field is
    missing or does not read as a number."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def version_is_current(value):
    """True when a version field names the current registry version."""
    number = version_number(value)
    current = version_number(REGISTRY_VERSION)
    return number is not None and number == current


def is_future_version(value):
    """True when a version field names a schema newer than the current
    one."""
    number = version_number(value)
    current = version_number(REGISTRY_VERSION)
    return number is not None and current is not None and number > current


VERSION_FIELDS = ("registry_version", "schema_version", "version")


def entry_is_future(entry):
    """True when a cache entry was written by a newer schema version."""
    if not isinstance(entry, dict):
        return False
    for field in VERSION_FIELDS:
        if is_future_version(entry.get(field)):
            return True
    return False


def is_future_state(state):
    """True when a state file was written by a newer schema version. The
    version may sit at the top level of the file or on each entry."""
    if not isinstance(state, dict):
        return False
    for field in VERSION_FIELDS:
        if is_future_version(state.get(field)):
            return True
    for entry in state.values():
        if entry_is_future(entry):
            return True
    return False


def is_reusable(entry, digest, rules_fp):
    """True when a cached entry may stand in for a fresh summary: the
    file on disk is byte-identical, the rules mapping is unchanged and
    the entry was produced under the current registry version."""
    if not isinstance(entry, dict):
        return False
    if entry.get("digest") != digest or entry.get("rules_fp") != rules_fp:
        return False
    if not version_is_current(entry.get("registry_version")):
        return False
    return all(key in entry for key in ("rows", "generated_from", "summary"))


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.

    A state file that cannot be parsed, or that was written by a future
    schema version, is reported as an empty cache: the run then does the
    full work and rewrites a valid state file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(state, dict) or is_future_state(state):
        return {}
    return state


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs). A state
    file written by a newer schema version reads as empty, so it is
    replaced by the entries of this run."""
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
    rules-mapped columns that carry at least one non-empty cell; when it
    is not given it falls back to the number of header columns covered
    by the rules mapping."""
    if generated_from is None:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

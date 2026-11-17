"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run, the rules mapping is unchanged, and the
entry was produced by this registry version. A state file written by a
newer schema version is not trusted at all: it is treated as an empty
cache, the run is redone in full, and a valid state file is written
back. save_state() rewrites the state file after every run so it always
mirrors what the last run saw.
"""

import csv
import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "3"

VERSION_KEYS = ("version", "schema_version", "registry_version")


def parse_version(value):
    """Best-effort numeric reading of a schema version. Returns None when
    the value carries no comparable version number."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return int(float(text))
        except ValueError:
            return None
    return None


def state_version(state):
    """The highest schema version declared by a state mapping, or None when
    it declares none. Both the top level and the per-entry fields are read,
    so a state file written by a newer schema is recognised whatever layout
    it uses."""
    if not isinstance(state, dict):
        return None
    highest = None

    def consider(value):
        nonlocal highest
        parsed = parse_version(value)
        if parsed is not None and (highest is None or parsed > highest):
            highest = parsed

    for key in VERSION_KEYS:
        if key in state and not isinstance(state[key], dict):
            consider(state[key])
    entries = state.get("entries")
    if not isinstance(entries, dict):
        entries = state
    for entry in entries.values():
        if isinstance(entry, dict):
            for key in VERSION_KEYS:
                if key in entry:
                    consider(entry[key])
    return highest


def is_future_state(state):
    """True when the state file was written by a schema newer than this
    one. Such a file must not be trusted: it is treated as an empty cache."""
    version = state_version(state)
    if version is None:
        return False
    current = parse_version(REGISTRY_VERSION)
    return current is not None and version > current


def state_entries(state):
    """The cache entries of a state file in the flat layout this version
    writes, or None when the file uses a layout it does not understand."""
    if not isinstance(state, dict):
        return None
    if "entries" in state:
        return None
    return state


def entry_is_usable(entry, digest, rules_fp):
    """True when a cache entry may be reused for the given file digest and
    rules fingerprint: it must be a complete entry produced by this
    registry version."""
    if not isinstance(entry, dict):
        return False
    version = parse_version(entry.get("registry_version"))
    current = parse_version(REGISTRY_VERSION)
    if version is None or current is None or version != current:
        return False
    if entry.get("digest") != digest or entry.get("rules_fp") != rules_fp:
        return False
    for key in ("rows", "generated_from", "summary"):
        if key not in entry:
            return False
    return True


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
    """Load the cache state; a missing file is just an empty cache. A file
    that cannot be parsed is also treated as an empty cache rather than
    crashing the run."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (ValueError, OSError):
        return {}
    if not isinstance(state, dict):
        return {}
    return state


def save_state(entries, path=DEFAULT_CACHE_PATH, replace=False):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs). With
    `replace`, the file is rewritten from `entries` alone — used when the
    previous file uses a layout this version does not understand."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    merged = {}
    if not replace and os.path.exists(path):
        merged = load_state(path)
        if not isinstance(merged, dict):
            merged = {}
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

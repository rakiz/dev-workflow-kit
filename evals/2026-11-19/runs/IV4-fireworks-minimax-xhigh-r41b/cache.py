"""Content cache for reportgen.

Layout: cache/state.json is a versioned document:

    {"version": <schema version>,
     "entries": {<input file name>: <entry>}}

where each entry is:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run and the rules mapping is unchanged;
save_state() merges the entries of the current run into the state file so
it always mirrors what the last run saw.

The schema version of the state file is REGISTRY_VERSION. A state file
written under a future schema version (a version field greater than
REGISTRY_VERSION) is treated as an empty cache: the run recomputes
everything and rewrites the file in the current schema.
"""

import csv
import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = 3

STATE_VERSION_KEY = "version"
STATE_ENTRIES_KEY = "entries"


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


def parse_version(value):
    """Return `value` as an integer schema version, or None when it is not
    a usable version number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.

    A state file written under a future schema version is an empty cache
    too: the run recomputes everything and rewrites the file in the
    current schema. A file we cannot read or parse is likewise treated as
    empty -- the cache is an optimization, never a reason to fail a run.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if STATE_VERSION_KEY in raw:
        version = parse_version(raw[STATE_VERSION_KEY])
        if version is None or version > REGISTRY_VERSION:
            return {}
        entries = raw.get(STATE_ENTRIES_KEY)
        if not isinstance(entries, dict):
            return {}
    else:
        # legacy state file: a flat name -> entry mapping written before
        # the versioned schema.
        entries = raw
    return {name: entry for name, entry in entries.items()
            if name not in (STATE_VERSION_KEY, STATE_ENTRIES_KEY)
            and isinstance(entry, dict)}


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    merged = dict(load_state(path))
    merged.update(entries)
    document = {STATE_VERSION_KEY: REGISTRY_VERSION,
                STATE_ENTRIES_KEY: merged}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, sort_keys=True)
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

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

import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "3"


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


def _as_version(value):
    """Parse a version stamp as an integer; None when it is not numeric.
    Compared numerically so that "10" is newer than "9"."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_future_state(state):
    """True when the state carries a version stamp newer than this
    registry: a top-level version field, or an entry's registry_version."""
    current = _as_version(REGISTRY_VERSION)
    stamps = [state.get("version"), state.get("registry_version")]
    stamps += [e.get("registry_version") for e in state.values()
               if isinstance(e, dict)]
    for stamp in stamps:
        version = _as_version(stamp)
        if version is not None and version > current:
            return True
    return False


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state. A missing file, a non-object file, or a state
    written by a future schema version is treated as an empty cache; the
    next save_state() then rewrites a state this version can read."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if not isinstance(state, dict) or is_future_state(state):
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


def make_entry(digest, rows, generated_from, summary, rules_fp):
    """Build a cache entry. `generated_from` must be the same value the
    report shows for a fresh run, so a cache hit reproduces it exactly."""
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

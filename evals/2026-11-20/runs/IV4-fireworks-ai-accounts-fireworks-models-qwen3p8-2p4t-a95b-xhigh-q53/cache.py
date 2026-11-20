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


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.
    Entries stamped with a different registry version are dropped — older
    ones are stale, and ones from a future schema (a version greater than
    REGISTRY_VERSION, possibly with an incompatible entry shape) are
    treated as absent instead of crashing the run. The comparison is by
    equality, so an unrecognized or differently typed version field can
    never raise. A state file whose top level is not a mapping of entries
    loads as an empty cache."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if not isinstance(state, dict):
        return {}
    return {name: entry for name, entry in state.items()
            if isinstance(entry, dict)
            and entry.get("registry_version") == REGISTRY_VERSION}


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
    """Build a cache entry. `generated_from` is stored verbatim as computed
    by the run (reportgen.generated_from), so a cache hit reproduces the
    same report a fresh pass would produce."""
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

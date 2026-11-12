"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":   "<sha256 of the file bytes>",
     "rows":     <int>,
     "rules_fp": "<fingerprint of the rules mapping>",
     "summary":  {...}}

Entries are reused only when the file on disk is byte-identical to the
file processed in the previous run. The rules fingerprint is stored
alongside the digest so an edited rules file is picked up on the next run
instead of serving stale summaries; save_state() rewrites the state file
after every run so it always mirrors what the last run saw.
"""

import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")


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
    """Load the cache state; a missing file is just an empty cache. A
    corrupt state file (invalid JSON, wrong shape) is treated the same
    way so the run proceeds from scratch and save_state() rewrites a
    valid file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


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


def make_entry(digest, rows, summary, rules_fp):
    """Build a cache entry. `rows` is the row count the run computed for
    the file (logical data rows, as reported by a fresh run)."""
    return {"digest": digest, "rows": rows, "rules_fp": rules_fp,
            "summary": summary}

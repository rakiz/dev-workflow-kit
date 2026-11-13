"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":   "<sha256 of the file bytes>",
     "rows":     <int>,
     "rules_fp": "<fingerprint of the rules mapping>",
     "summary":  {...}}

Entries are reused only when the file and rules match the previous run.
The state file is rewritten after every successful run.
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
    """Load the cache state; missing or corrupt data is an empty cache."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Replace the state file with entries from the successful run."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def make_entry(digest, summary, rules_fp, rows):
    """Build a cache entry with the parsed data-row count."""
    return {"digest": digest, "rows": rows, "rules_fp": rules_fp,
            "summary": summary}

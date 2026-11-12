"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":   "<sha256 of the file bytes>",
     "rows":     <int>,
     "rules_fp": "<fingerprint of the rules mapping>",
     "summary":  {...}}

Entries are reused only when the file and rules match the previous run.
save_state() rewrites the state file after every full run.
"""

import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")
CACHE_VERSION = 2


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
    """Load the cache state; a missing or corrupt file is an empty cache."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(state, dict) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("digest"), str)
        or not isinstance(entry.get("rows"), int)
        or not isinstance(entry.get("summary"), dict)
        or not isinstance(entry["summary"].get("columns"), dict)
        or not isinstance(entry["summary"].get("skipped_rows"), list)
        or any(not isinstance(col, str) or not isinstance(stats, dict)
               or not isinstance(stats.get("non_empty"), int)
               or not isinstance(stats.get("distinct"), int)
               or not isinstance(stats.get("sample"), list)
               for col, stats in entry["summary"].get("columns", {}).items())
        for entry in state.values()
    ):
        return {}
    return state


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Replace the state file with entries from the full run."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def make_entry(digest, rows, summary, rules_fp):
    """Build a cache entry using the parsed data-row count."""
    return {"version": CACHE_VERSION, "digest": digest, "rows": rows, "rules_fp": rules_fp,
            "summary": summary}

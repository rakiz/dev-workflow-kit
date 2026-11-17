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


def _is_future_state(state):
    """True when `state` carries a version stamp greater than the current
    REGISTRY_VERSION — i.e. it was written by a future schema version and
    this build must neither reuse nor crash on it. Stamps are compared
    numerically when possible; stamps that cannot be parsed are ignored."""
    if not isinstance(state, dict):
        return False
    stamps = [state[key] for key in ("version", "schema_version",
                                     "registry_version") if key in state]
    stamps.extend(entry["registry_version"] for entry in state.values()
                  if isinstance(entry, dict) and "registry_version" in entry)
    for stamp in stamps:
        try:
            if int(stamp) > int(REGISTRY_VERSION):
                return True
        except (TypeError, ValueError):
            continue
    return False


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache. A state
    file this build cannot trust — one written by a future schema version
    (any version stamp greater than REGISTRY_VERSION), or one that is not a
    mapping at all — is treated as an empty cache, so the run does the full
    pass and save_state() rewrites a valid state file."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if not isinstance(state, dict) or _is_future_state(state):
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
    rules-mapped columns that have at least one non-empty cell — the same
    value reportgen.generated_from() puts in a fresh run's report, so a
    cache hit reproduces that report exactly."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        data_rows = [row for row in reader if row]
    non_empty = set()
    for row in data_rows:
        for i, col in enumerate(header):
            if i < len(row) and row[i] != "":
                non_empty.add(col)
    generated_from = sum(1 for col in header if col in rules and col in non_empty)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

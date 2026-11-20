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


def _parse_version(v):
    if isinstance(v, bool):
        return ()
    if isinstance(v, (int, float)):
        return (float(v),)
    if isinstance(v, str):
        s = v.strip().lstrip("vV")
        try:
            return tuple(int(p) for p in s.split("."))
        except ValueError:
            try:
                return (float(s),)
            except ValueError:
                return ()
    return ()


def _is_future_version(v):
    cur = _parse_version(REGISTRY_VERSION)
    parsed = _parse_version(v)
    return bool(parsed and cur and parsed > cur)


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {}
    for k in ("version", "registry_version", "schema_version"):
        if k in data and _is_future_version(data[k]):
            return {}
    for entry in data.values():
        if not isinstance(entry, dict):
            return {}
        for k in ("version", "registry_version", "schema_version"):
            if k in entry and _is_future_version(entry[k]):
                return {}
        if not {"digest", "rows", "generated_from", "summary"}.issubset(entry):
            return {}
        if not isinstance(entry["summary"], dict) or not isinstance(
                entry["summary"].get("columns"), dict):
            return {}
    return data


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
    rules-mapped header columns that have at least one non-empty cell."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    cols = summary.get("columns", {}) if isinstance(summary, dict) else {}
    generated_from = sum(
        1 for col in header
        if col in rules and cols.get(col, {}).get("non_empty", 0) > 0
    )
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

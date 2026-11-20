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

REQUIRED_ENTRY_KEYS = {
    "digest", "rows", "generated_from", "rules_fp",
    "registry_version", "summary",
}


def _version_gt(value, ref=REGISTRY_VERSION):
    """Return True when `value` represents a version greater than `ref`."""
    def _to_float(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        if isinstance(v, str):
            s = v.strip()
            if s.startswith(("v", "V")):
                s = s[1:]
            return float(s)
        raise ValueError(v)
    try:
        return _to_float(value) > _to_float(ref)
    except (ValueError, TypeError):
        return str(value) > str(ref)


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
    """Load the cache state; a missing or incompatible file is treated as an
    empty cache."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    for k, v in data.items():
        if (k == "version" or k.endswith("_version")) and _version_gt(v):
            return {}
    for entry in data.values():
        if not isinstance(entry, dict):
            return {}
        for k, v in entry.items():
            if (k == "version" or k.endswith("_version")) and _version_gt(v):
                return {}
        if not REQUIRED_ENTRY_KEYS.issubset(entry):
            return {}
        summary = entry.get("summary")
        if not isinstance(summary, dict) or not isinstance(summary.get("columns"), dict):
            return {}
        if summary.get("skipped_rows"):
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
    header columns covered by the rules mapping that have at least one
    non-empty cell."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        non_empty = {
            col for row in reader if row
            for i, col in enumerate(header)
            if i < len(row) and row[i] != ""
        }
    generated_from = sum(1 for col in header if col in rules and col in non_empty)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

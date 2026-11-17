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


def _normalize_version(val):
    if isinstance(val, (int, float)):
        return [int(p) for p in str(val).split(".") if p.isdigit()]
    if isinstance(val, str):
        digits = "".join(c if (c.isdigit() or c == ".") else " " for c in val).split()
        if digits:
            return [int(p) for p in digits[0].split(".") if p.isdigit()]
    return []


def _is_future_version(val):
    if val is None:
        return False
    try:
        return float(val) > float(REGISTRY_VERSION)
    except (ValueError, TypeError):
        pass
    v_norm = _normalize_version(val)
    cur_norm = _normalize_version(REGISTRY_VERSION)
    while len(v_norm) > 1 and v_norm[-1] == 0:
        v_norm.pop()
    while len(cur_norm) > 1 and cur_norm[-1] == 0:
        cur_norm.pop()
    max_len = max(len(v_norm), len(cur_norm))
    v_norm += [0] * (max_len - len(v_norm))
    cur_norm += [0] * (max_len - len(cur_norm))
    return v_norm > cur_norm


def _has_future_version(data):
    if not isinstance(data, dict):
        return True
    for k, v in data.items():
        if "version" in k.lower() and _is_future_version(v):
            return True
        if isinstance(v, dict):
            for sub_k, sub_v in v.items():
                if "version" in sub_k.lower() and _is_future_version(sub_v):
                    return True
    return False


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
    """Load the cache state; a missing file is just an empty cache."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    if _has_future_version(data):
        return {}
    return data if isinstance(data, dict) else {}


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


def make_entry(path, digest, rows, summary, rules, rules_fp, generated_from=None):
    """Build a cache entry for `path`. `generated_from` is the number of
    header columns covered by the rules mapping with non-empty cells."""
    if generated_from is None:
        cols = summary.get("columns", {}) if isinstance(summary, dict) else {}
        generated_from = sum(1 for col in rules if cols.get(col, {}).get("non_empty", 0) > 0)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

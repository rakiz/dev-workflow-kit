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
import math
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = "2"


def _parse_version(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return (value,)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if value.is_integer():
            return (int(value),)
        return _parse_version(str(value))
    if isinstance(value, str):
        s = value.strip()
        if s.startswith(("v", "V")) and len(s) > 1 and s[1].isdigit():
            s = s[1:]
        parts = s.split(".")
        if not parts or not all(p.isdigit() for p in parts):
            return None
        nums = [int(p) for p in parts]
        while len(nums) > 1 and nums[-1] == 0:
            nums.pop()
        return tuple(nums)
    return None


def _is_future_version(value):
    current = _parse_version(REGISTRY_VERSION)
    parsed = _parse_version(value)
    return parsed is not None and current is not None and parsed > current


def _has_future_version(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "summary":
                continue
            if isinstance(k, str) and k.lower().endswith("version"):
                if not isinstance(v, (dict, list)) and _is_future_version(v):
                    return True
            if isinstance(v, (dict, list)) and _has_future_version(v):
                return True
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)) and _has_future_version(item):
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
    """Load the cache state; a missing or future-version file is treated as
    an empty cache."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict) or _has_future_version(data):
        return {}
    if any(not isinstance(v, dict) for v in data.values()):
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
    payload = json.dumps(merged, indent=2, sort_keys=True) + "\n"
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def make_entry(path, digest, rows, summary, rules, rules_fp, generated_from=None):
    """Build a cache entry for `path`. `generated_from` is the number of
    rules-mapped columns that have at least one non-empty cell in the file."""
    if generated_from is None:
        non_empty = set()
        with open(path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            for row in reader:
                if not row:
                    continue
                for i, col in enumerate(header):
                    if i < len(row) and row[i] != "":
                        non_empty.add(col)
        generated_from = sum(1 for col in header if col in rules and col in non_empty)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

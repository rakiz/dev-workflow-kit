"""Content cache for reportgen.

Layout: cache/state.json is a JSON object with a "version" field (the
schema version of the state file) plus one entry per input file name:

    {"version":         "<schema version of this state file>",
     "<input file>":    {"digest":           "<sha256 of the file bytes>",
                         "rows":             <int>,
                         "generated_from":   <int>,
                         "rules_fp":         "<fingerprint of the rules mapping>",
                         "registry_version": "<version of the transform registry>",
                         "summary":          {...}}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run, the rules mapping is unchanged and the
entry was produced under the current registry version;
save_state() rewrites the state file after every run so it always mirrors
what the last run saw.

A state file whose version does not match the current REGISTRY_VERSION is
never trusted: in particular a file written by a *future* schema version
is treated as an empty cache (the run does the full work and rewrites a
valid state file) rather than crashing or reusing incompatible entries.

(The flat layout reserves the "version" key, so an input file literally
named "version" cannot be represented in the state file.)
"""

import csv
import hashlib
import json
import os

DEFAULT_CACHE_PATH = os.path.join("cache", "state.json")

REGISTRY_VERSION = 3


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


def _version_number(value):
    """Numeric value of a version field, or None when the field is
    missing or is not a version number. Accepts both 3 and "3"."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state.

    A missing, unreadable, malformed or foreign-version state file is an
    empty cache: the run then does the full work and rewrites a valid
    state file. A state file written by a future schema version (version
    greater than REGISTRY_VERSION) is therefore discarded instead of
    crashing the run.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    version = _version_number(data.get("version"))
    if version is None or version != REGISTRY_VERSION:
        return {}
    entries = data.get("entries")
    if isinstance(entries, dict):
        return entries
    return {k: v for k, v in data.items()
            if k != "version" and isinstance(v, dict)}


def save_state(entries, path=DEFAULT_CACHE_PATH):
    """Merge `entries` into the state file, keeping entries for inputs the
    run did not touch (a run may cover a subset of the inputs)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    merged = load_state(path)
    merged.update(entries)
    payload = {"version": REGISTRY_VERSION}
    payload.update(merged)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def make_entry(path, digest, rows, summary, rules, rules_fp, generated_from=None):
    """Build a cache entry for `path`.

    `generated_from` is the number of rule-mapped columns the summary was
    built from; callers pass the value they report so the cached entry
    and the report always agree. When it is not given it falls back to
    the header-only approximation (rule-mapped columns of the header),
    which ignores columns whose cells are all empty.
    """
    if generated_from is None:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

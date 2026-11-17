"""Content cache for reportgen.

Layout: cache/state.json maps each input file name to one entry:

    {"digest":           "<sha256 of the file bytes>",
     "rows":             <int>,
     "generated_from":   <int>,
     "rules_fp":         "<fingerprint of the rules mapping>",
     "registry_version": "<version of the transform registry>",
     "summary":          {...}}

Entries are reused when the file on disk is byte-identical to the file
processed in the previous run, the rules mapping is unchanged, and the
entry was produced under the current registry version;
save_state() rewrites the state file after every run so it always mirrors
what the last run saw.

A state file written by a newer schema cannot be interpreted by this
code: it is treated as an empty cache, so the run redoes the whole work
and rewrites a state file this version can read.
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


def version_number(version):
    """Numeric value of a version field, or None when it is not a number.
    Versions compare numerically, so "10" is newer than "2"."""
    try:
        return int(str(version).strip())
    except (TypeError, ValueError):
        return None


def is_future_version(version):
    """True when `version` names a schema newer than REGISTRY_VERSION.
    A version that is not a number cannot be compared, so it is not
    treated as a future one."""
    number = version_number(version)
    current = version_number(REGISTRY_VERSION)
    if number is None or current is None:
        return False
    return number > current


def load_state(path=DEFAULT_CACHE_PATH):
    """Load the cache state; a missing file is just an empty cache.

    A state file this version cannot read (a foreign shape, a newer
    schema version) is treated as an empty cache, and entries stamped
    with a newer registry version are dropped: neither can be reused,
    and the next save rewrites the file without them."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        try:
            state = json.load(fh)
        except ValueError:
            return {}
    if not isinstance(state, dict):
        return {}
    if is_future_version(state.get("version")):
        return {}
    return {name: entry for name, entry in state.items()
            if not (isinstance(entry, dict)
                    and is_future_version(entry.get("registry_version")))}


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
    rules-mapped columns that carried data in the file; the caller passes
    the value the report shows, so a cached run reproduces the report
    exactly. Without it the number of header columns covered by the
    rules mapping is used."""
    if generated_from is None:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        generated_from = sum(1 for col in header if col in rules)
    return {"digest": digest, "rows": rows, "generated_from": generated_from,
            "rules_fp": rules_fp, "registry_version": REGISTRY_VERSION,
            "summary": summary}

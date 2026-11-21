"""Content-addressed chunk store.

Chunks are addressed by the sha256 of their bytes. Equal content always
yields the same id. Chunks are laid out two levels deep, by id prefix.
"""
import hashlib
import json
import os
import zlib

CHUNK_SIZE = 4096
COMPRESSION = zlib.Z_BEST_SPEED


def chunk_id(data):
    """Return the sha256 id of the chunk's bytes; equal content always yields the same id."""
    return hashlib.sha256(zlib.compress(data, COMPRESSION)).hexdigest()


def chunk_path(root, cid):
    """The path of one chunk file inside the store."""
    return os.path.join(root, cid[:2], cid)


def store_chunk(root, data):
    """Write one chunk atomically (sibling temp file, then rename) and return its id."""
    cid = chunk_id(data)
    path = chunk_path(root, cid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return cid


def load_chunk(root, cid):
    """Return the stored bytes of one chunk."""
    with open(chunk_path(root, cid), "rb") as fh:
        return fh.read()


def iter_chunks_from_path(path):
    """Stream a file as CHUNK_SIZE-byte chunks; memory stays bounded by the chunk size."""
    with open(path, "rb") as fh:
        data = fh.read()
    for off in range(0, len(data), CHUNK_SIZE):
        yield data[off:off + CHUNK_SIZE]


def read_object(root, entry):
    """Join an object's chunks and return its first entry["size"] bytes."""
    data = b"".join(load_chunk(root, cid) for cid in entry["chunks"])
    return data[:entry["size"]]


def manifest_entries(manifest_path):
    """Every manifest line, in the order it was appended."""
    entries = []
    try:
        with open(manifest_path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except OSError:
        pass
    return entries


def manifest_read(manifest_path):
    """The manifest as a map keyed by object name; the last entry for a name wins."""
    entries = {}
    for entry in manifest_entries(manifest_path):
        entries[entry["object"]] = entry
    return entries


def referenced_ids(manifest_path):
    """Return the set of chunk ids named by every manifest line."""
    ids = set()
    for entry in manifest_entries(manifest_path):
        ids.update(entry.get("chunks", []))
    return ids


def gc_orphans(root, manifest_path, removed=()):
    """Delete the chunks of the objects that are gone, plus every chunk no manifest line names.

    removed: the manifest entries of the objects that were just removed; their
    chunks go even when a live object still names the same chunk.
    Returns how many files were deleted and the growth the manifest claims
    (the sum of the entries' sizes).
    """
    keep = referenced_ids(manifest_path)
    dead = set()
    for entry in removed:
        dead.update(entry.get("chunks", []))
    deleted = 0
    if os.path.isdir(root):
        for sub in os.listdir(root):
            subdir = os.path.join(root, sub)
            if not os.path.isdir(subdir):
                continue
            for cid in os.listdir(subdir):
                if cid in dead or cid not in keep:
                    os.remove(os.path.join(subdir, cid))
                    deleted += 1
    growth = sum(entry.get("size", 0) for entry in manifest_entries(manifest_path))
    return {"removed": deleted, "growth_bytes": growth}

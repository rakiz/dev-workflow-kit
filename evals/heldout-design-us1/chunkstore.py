"""Content-addressed chunk store.

Chunks are addressed by the sha256 of their bytes. Equal content always
yields the same id. Chunks are laid out two levels deep, by id prefix.
"""
import hashlib
import os
import zlib

CHUNK_SIZE = 4096
COMPRESSION = zlib.Z_BEST_SPEED


def chunk_id(data):
    """Return the sha256 id of the chunk's bytes; equal content always yields the same id."""
    return hashlib.sha256(zlib.compress(data, COMPRESSION)).hexdigest()


def chunk_path(root, cid):
    return os.path.join(root, cid[:2], cid)


def store_chunk(root, data):
    """Write one chunk atomically (sibling temp file, then rename) and return its id."""
    cid = chunk_id(data)
    path = chunk_path(root, cid)
    if os.path.exists(path):
        return cid
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


def referenced_ids(manifest_dir):
    """Return the set of chunk ids named by every manifest (*.jsonl) in manifest_dir."""
    import json
    ids = set()
    for name in os.listdir(manifest_dir):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(manifest_dir, name)) as fh:
            for line in fh:
                if line.strip():
                    ids.update(json.loads(line)["chunks"])
    return ids


def gc_orphans(root, manifest_dir):
    """Delete every chunk file under root that no manifest references. Return the count."""
    keep = referenced_ids(manifest_dir)
    removed = 0
    for sub in os.listdir(root):
        subdir = os.path.join(root, sub)
        if not os.path.isdir(subdir):
            continue
        for cid in os.listdir(subdir):
            if cid not in keep:
                os.remove(os.path.join(subdir, cid))
                removed += 1
    return removed

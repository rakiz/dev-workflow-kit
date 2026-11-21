"""Single-shot upload of a file to a chunk store, with a retry wrapper and a remote manifest."""
import json
import os

import chunkstore


class TransientError(Exception):
    """A transfer failed in a way that may succeed on retry."""


def _manifest_append(path, entry):
    """Append one JSON line describing an uploaded object. Retries are safe."""
    with open(path, "a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def _store_file(path, store_root):
    name = os.path.basename(path)
    ids = []
    for chunk in chunkstore.iter_chunks_from_path(path):
        if len(chunk) < chunkstore.CHUNK_SIZE:
            chunk = chunk + b"\0" * (chunkstore.CHUNK_SIZE - len(chunk))
        ids.append(chunkstore.store_chunk(store_root, chunk))
    return {"object": name, "chunks": ids, "size": len(ids) * chunkstore.CHUNK_SIZE}


def upload_file(path, store_root, manifest_path):
    """Store every chunk of one file, then append one manifest entry. Return the entry."""
    entry = _store_file(path, store_root)
    _manifest_append(manifest_path, entry)
    return entry


def upload_with_retry(path, store_root, manifest_path, transport=None, attempts=3):
    """Upload a file, retrying the whole upload after a TransientError.

    The entry is handed to transport.put(entry) when a transport is given,
    otherwise it is appended to manifest_path directly.
    """
    last = None
    for _ in range(attempts):
        try:
            entry = _store_file(path, store_root)
            if transport is None:
                _manifest_append(manifest_path, entry)
            else:
                transport.put(entry)
            return entry
        except TransientError as exc:
            last = exc
    raise last

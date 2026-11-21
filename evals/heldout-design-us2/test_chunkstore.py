import os
import tempfile
import unittest

import chunkstore
import uploader


def chunk_files(root):
    """Every chunk file in the store."""
    found = []
    for sub in sorted(os.listdir(root)):
        subdir = os.path.join(root, sub)
        if os.path.isdir(subdir):
            found.extend(os.path.join(subdir, name) for name in sorted(os.listdir(subdir)))
    return found


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "store")
        self.manifest = os.path.join(self.tmp.name, "objects.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def uploaded(self, path):
        """Upload one file and return the manifest entry it produced."""
        uploader.upload_file(path, self.root, self.manifest)
        return chunkstore.manifest_entries(self.manifest)[-1]

    def write(self, name, payload):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(payload)
        return path

    def test_store_and_load_round_trip(self):
        data = b"x" * chunkstore.CHUNK_SIZE
        cid = chunkstore.store_chunk(self.root, data)
        self.assertEqual(chunkstore.load_chunk(self.root, cid), data)

    def test_upload_exact_multiple_reads_back(self):
        payload = bytes(range(256)) * (chunkstore.CHUNK_SIZE // 256) * 2
        entry = self.uploaded(self.write("a.bin", payload))
        self.assertEqual(chunkstore.read_object(self.root, entry), payload)
        self.assertEqual(entry["size"], len(payload))

    def test_two_files_with_distinct_names_are_both_readable(self):
        first = bytes(range(256)) * (chunkstore.CHUNK_SIZE // 256) * 2
        second = bytes(reversed(range(256))) * (chunkstore.CHUNK_SIZE // 256) * 2
        entry_a = self.uploaded(self.write("alpha.bin", first))
        entry_b = self.uploaded(self.write("beta.bin", second))
        self.assertEqual(chunkstore.read_object(self.root, entry_a), first)
        self.assertEqual(chunkstore.read_object(self.root, entry_b), second)

    def test_one_chunk_for_a_small_object(self):
        self.uploaded(self.write("small.bin", b"q" * 10))
        self.assertEqual(len(chunk_files(self.root)), 1)

    def test_transport_failing_before_apply_is_retried_once(self):
        src = self.write("c.bin", b"z" * chunkstore.CHUNK_SIZE)
        calls = []

        class Transport:
            def put(self, entry):
                calls.append(entry)
                if len(calls) == 1:
                    raise uploader.TransientError("refused before apply")
                uploader._manifest_append(self.path, entry)

        t = Transport()
        t.path = self.manifest
        uploader.upload_with_retry(src, self.root, self.manifest, transport=t)
        with open(self.manifest) as fh:
            self.assertEqual(len([line for line in fh if line.strip()]), 1)


if __name__ == "__main__":
    unittest.main()

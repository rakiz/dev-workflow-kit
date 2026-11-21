import os
import tempfile
import unittest

import chunkstore
import uploader


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "store")
        self.manifests = os.path.join(self.tmp.name, "manifests")
        os.makedirs(self.manifests)
        self.manifest = os.path.join(self.manifests, "objects.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_store_and_load_round_trip(self):
        data = b"x" * chunkstore.CHUNK_SIZE
        cid = chunkstore.store_chunk(self.root, data)
        self.assertEqual(chunkstore.load_chunk(self.root, cid), data)

    def test_upload_exact_multiple_reads_back(self):
        src = os.path.join(self.tmp.name, "a.bin")
        payload = bytes(range(256)) * (chunkstore.CHUNK_SIZE // 256) * 2
        with open(src, "wb") as fh:
            fh.write(payload)
        entry = uploader.upload_file(src, self.root, self.manifest)
        self.assertEqual(chunkstore.read_object(self.root, entry), payload)

    def test_gc_removes_unreferenced_chunk(self):
        kept = chunkstore.store_chunk(self.root, b"k" * chunkstore.CHUNK_SIZE)
        src = os.path.join(self.tmp.name, "b.bin")
        with open(src, "wb") as fh:
            fh.write(b"k" * chunkstore.CHUNK_SIZE)
        uploader.upload_file(src, self.root, self.manifest)
        orphan = chunkstore.store_chunk(self.root, b"o" * chunkstore.CHUNK_SIZE)
        self.assertEqual(chunkstore.gc_orphans(self.root, self.manifests), 1)
        self.assertTrue(os.path.exists(chunkstore.chunk_path(self.root, kept)))
        self.assertFalse(os.path.exists(chunkstore.chunk_path(self.root, orphan)))

    def test_transport_failing_before_apply_is_retried_once(self):
        src = os.path.join(self.tmp.name, "c.bin")
        with open(src, "wb") as fh:
            fh.write(b"z" * chunkstore.CHUNK_SIZE)
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

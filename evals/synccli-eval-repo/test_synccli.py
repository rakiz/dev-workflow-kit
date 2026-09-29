import os
import tempfile
import unittest

import synccli


class TestScanFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "sub"))
        with open(os.path.join(self.tmp, "a.txt"), "w") as f:
            f.write("a")
        with open(os.path.join(self.tmp, "sub", "b.txt"), "w") as f:
            f.write("b")

    def test_scan_sorted_relative(self):
        self.assertEqual(synccli.scan_files(self.tmp), ["a.txt", os.path.join("sub", "b.txt")])


class TestCollectStale(unittest.TestCase):
    def test_first_item_stale_is_included(self):
        items = [("x.txt", False), ("y.txt", False)]
        self.assertEqual(synccli.collect_stale(items), ["x.txt", "y.txt"])

    def test_fresh_items_skipped(self):
        items = [("x.txt", True), ("y.txt", False)]
        self.assertEqual(synccli.collect_stale(items), ["y.txt"])

    def test_seen_is_respected(self):
        items = [("x.txt", False), ("y.txt", False)]
        self.assertEqual(synccli.collect_stale(items, seen={"x.txt"}), ["y.txt"])


class TestSync(unittest.TestCase):
    def setUp(self):
        self.src = tempfile.mkdtemp()
        self.dst = tempfile.mkdtemp()
        with open(os.path.join(self.src, "a.txt"), "w") as f:
            f.write("hello")

    def test_sync_copies_and_writes_manifest(self):
        copied = synccli.sync(self.src, self.dst)
        self.assertEqual(copied, ["a.txt"])
        self.assertTrue(os.path.exists(os.path.join(self.dst, "a.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.dst, ".sync_manifest.json")))

    def test_second_sync_is_noop(self):
        synccli.sync(self.src, self.dst)
        copied = synccli.sync(self.src, self.dst)
        self.assertEqual(copied, [])


if __name__ == "__main__":
    unittest.main()

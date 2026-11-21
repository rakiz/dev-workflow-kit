import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import prune


class ListNotes(unittest.TestCase):
    def test_sorted_names(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("b.md", "a.md"):
                open(os.path.join(d, name), "w").close()
            self.assertEqual(prune.list_notes(d), ["a.md", "b.md"])

    def test_main_prints_names(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "x.md"), "w").close()
            buf = io.StringIO()
            with redirect_stdout(buf):
                prune.main([d])
            self.assertEqual(buf.getvalue(), "x.md\n")


if __name__ == "__main__":
    unittest.main()

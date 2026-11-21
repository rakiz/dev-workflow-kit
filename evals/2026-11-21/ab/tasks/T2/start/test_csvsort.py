import csv
import io
import os
import unittest

import csvsort

HERE = os.path.dirname(os.path.abspath(__file__))


class SortRows(unittest.TestCase):
    def test_sort_rows_ascending(self):
        rows = [{"k": "3"}, {"k": "1"}, {"k": "2"}]
        self.assertEqual([r["k"] for r in csvsort.sort_rows(rows, lambda r: r["k"])], ["1", "2", "3"])

    def test_sort_rows_stable_keeps_order_of_ties(self):
        rows = [{"k": "1", "n": "a"}, {"k": "0", "n": "b"}, {"k": "1", "n": "c"}]
        self.assertEqual([r["n"] for r in csvsort.sort_rows_stable(rows, lambda r: r["k"])], ["b", "a", "c"])

    def test_empty(self):
        self.assertEqual(csvsort.sort_rows([], lambda r: r), [])


if __name__ == "__main__":
    unittest.main()

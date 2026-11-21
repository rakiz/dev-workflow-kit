import unittest

from intervals import merge


class Merge(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(merge([]), [])

    def test_disjoint_kept_apart(self):
        self.assertEqual(merge([(1, 2), (5, 6)]), [(1, 2), (5, 6)])


if __name__ == "__main__":
    unittest.main()

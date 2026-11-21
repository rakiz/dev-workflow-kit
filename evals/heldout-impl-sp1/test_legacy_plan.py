import os
import unittest

import plan

HERE = os.path.dirname(os.path.abspath(__file__))


class LegacyOrdering(unittest.TestCase):
    def test_legacy_ordering_is_ascending_priority(self):
        jobs = [plan.Job("a", 5, 3, ""), plan.Job("b", 5, 1, "")]
        self.assertEqual([j.id for j in plan.order_jobs(jobs)], ["b", "a"])


if __name__ == "__main__":
    unittest.main()

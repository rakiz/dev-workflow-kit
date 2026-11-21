import json
import os
import tempfile
import unittest

import cli
import plan

HERE = os.path.dirname(os.path.abspath(__file__))


class Happy(unittest.TestCase):
    def test_small_input_places_every_job_once(self):
        jobs = plan.load_jobs(os.path.join(HERE, "data", "jobs_small.csv"))
        machines = plan.load_machines(os.path.join(HERE, "data", "machines.csv"))
        placements, unassigned = plan.assign(jobs, machines)
        placed = [r["job"] for rows in placements.values() for r in rows]
        self.assertEqual(len(placed), len(set(placed)))
        self.assertEqual(unassigned, [])

    def test_no_machine_over_shift(self):
        jobs = plan.load_jobs(os.path.join(HERE, "data", "jobs_small.csv"))
        machines = plan.load_machines(os.path.join(HERE, "data", "machines.csv"))
        placements, _ = plan.assign(jobs, machines)
        for m in machines:
            for r in placements[m.name]:
                self.assertLessEqual(r["start"] + r["minutes"], m.shift_minutes)

    def test_cli_writes_artefacts(self):
        with tempfile.TemporaryDirectory() as d:
            rc = cli.main(["--jobs", os.path.join(HERE, "data", "jobs_small.csv"),
                           "--machines", os.path.join(HERE, "data", "machines.csv"),
                           "--out", d])
            self.assertEqual(rc, 0)
            with open(os.path.join(d, "plan.json")) as fh:
                self.assertIn("machines", json.load(fh))


if __name__ == "__main__":
    unittest.main()

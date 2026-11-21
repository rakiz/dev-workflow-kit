import json
import os
import tempfile
import unittest

import cli
import plan
import planio

HERE = os.path.dirname(os.path.abspath(__file__))


def data(name):
    return os.path.join(HERE, "data", name)


class OrderingAndConflicts(unittest.TestCase):
    def test_order_jobs_priority_then_id(self):
        jobs = [plan.Job("b", 5, 1, ""), plan.Job("a", 5, 1, ""), plan.Job("c", 5, 3, "")]
        self.assertEqual([j.id for j in plan.order_jobs(jobs)], ["c", "a", "b"])

    def test_conflicts_detects_overlap_and_allows_touching(self):
        assigned = [{"job": "x", "start": 0, "minutes": 30}]
        self.assertTrue(plan.conflicts(assigned, 10, 5))
        self.assertFalse(plan.conflicts(assigned, 30, 5))


class Assignment(unittest.TestCase):
    def setUp(self):
        self.machines = plan.load_machines(data("machines.csv"))

    def test_small_input_places_every_job_once(self):
        jobs = plan.load_jobs(data("jobs_small.csv"))
        placements, unassigned = plan.assign(jobs, self.machines)
        ids = [row["job"] for rows in placements.values() for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(ids), sorted(j.id for j in jobs))
        self.assertEqual(unassigned, [])

    def test_no_machine_exceeds_its_shift(self):
        jobs = plan.load_jobs(data("jobs_small.csv"))
        placements, _ = plan.assign(jobs, self.machines)
        for m in self.machines:
            for row in placements[m.name]:
                self.assertLessEqual(row["start"] + row["minutes"], m.shift_minutes)

    def test_load_machines_reads_four_rows(self):
        self.assertEqual([m.name for m in self.machines], ["m1", "m2", "m3", "m4"])


class Artefacts(unittest.TestCase):
    def test_save_plan_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "plan.json")
            doc = {"machines": {"m1": {"shift_minutes": 240, "assignments": []}}}
            planio.save_plan(doc, path)
            self.assertEqual(planio.load_plan(path), doc)

    def test_render_timetable_one_line_per_assignment(self):
        machines = [plan.Machine("m1", 240)]
        placements = {"m1": [{"job": "J1", "start": 0, "minutes": 10}]}
        self.assertEqual(planio.render_timetable(placements, machines), "m1 0 J1 10\n")

    def test_cli_run_writes_plan_timetable_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = cli.run(data("jobs_small.csv"), data("machines.csv"), tmp)
            self.assertEqual(rc, 0)
            doc = json.load(open(os.path.join(tmp, "plan.json")))
            self.assertEqual(sorted(doc["machines"]), ["m1", "m2", "m3", "m4"])
            self.assertTrue(os.path.isfile(os.path.join(tmp, "timetable.txt")))
            self.assertTrue(os.path.isfile(os.path.join(tmp, "index.json")))


if __name__ == "__main__":
    unittest.main()

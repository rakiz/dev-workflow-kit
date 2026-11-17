"""Tests for the GOAL.md features: the boolean transform (item 1) and
cache hygiene for a state file written by a future schema version
(item 2)."""

import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_forms_report_as_one(self):
        for raw in ("yes", "YES", "Yes", "yEs", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms_report_as_zero(self):
        for raw in ("no", "NO", "No", "nO", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_surrounding_whitespace_accepted(self):
        self.assertEqual(transforms.apply("boolean", "  yes "), 1.0)
        self.assertEqual(transforms.apply("boolean", "\tFalse\n"), 0.0)

    def test_any_other_input_raises_transform_error(self):
        for raw in ("maybe", "1", "0", "y", "n", "truthy", "", "  ",
                    "yes no", "oui"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_registered(self):
        self.assertIn("boolean", transforms.REGISTRY)


class BooleanEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_rules_may_map_a_column_to_boolean(self):
        with open(os.path.join(self.inp, "f.csv"), "w") as fh:
            fh.write("flag,name\nyes,a\nNO,b\nTrue,a\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        col = report["files"]["f.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["sample"], [0.0, 1.0])
        # numeric_sum sums the distinct transformed values (existing
        # summarize_file semantics): {1.0, 0.0} -> 1.0
        self.assertEqual(col["numeric_sum"], 1.0)

    def test_unaccepted_boolean_cell_fails_the_run(self):
        with open(os.path.join(self.inp, "f.csv"), "w") as fh:
            fh.write("flag\nmaybe\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)


class FutureSchemaStateTests(unittest.TestCase):
    """A cache/state.json written by a future schema version must not
    crash the run: the cache is treated as empty, the full run happens,
    and a valid state file is rewritten."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("v\n1\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nv = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def _seed(self, payload):
        with open(self.cache_path, "w") as fh:
            json.dump(payload, fh)

    def _future_entry_state(self, future_version):
        digest = cache.file_digest(os.path.join(self.inp, "t.csv"))
        rules_fp = cache.rules_fingerprint(reportgen.load_rules(self.rules))
        return {"t.csv": {
            "digest": digest, "rows": 999, "generated_from": 999,
            "rules_fp": rules_fp, "registry_version": future_version,
            "summary": {"columns": {"v": {"non_empty": 999, "distinct": 999,
                                          "sample": ["from-the-future"],
                                          "numeric_sum": 999.0}},
                        "skipped_rows": []},
            "future_only_field": {"nested": [1, 2, 3]}}}

    def test_future_entry_version_treated_as_empty_and_rewritten(self):
        future = str(int(cache.REGISTRY_VERSION) + 1)
        self._seed(self._future_entry_state(future))
        report = reportgen.run(self.rules, self.inp, self.out,
                               self.cache_path)
        # full run done: values recomputed, not the future entry's
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)
        col = report["files"]["t.csv"]["summary"]["columns"]["v"]
        self.assertEqual(col["numeric_sum"], 1.0)
        # a valid state file was rewritten
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 1)
        self.assertNotIn("future_only_field", state["t.csv"])

    def test_large_future_version_number(self):
        # numeric, not lexicographic comparison: '10' > '2'
        self._seed(self._future_entry_state("10"))
        report = reportgen.run(self.rules, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)

    def test_future_toplevel_version_field(self):
        future = int(cache.REGISTRY_VERSION) + 1
        self._seed({"version": future,
                    "entries": {"t.csv": {"digest": "irrelevant"}}})
        report = reportgen.run(self.rules, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})

    def test_unreadable_state_treated_as_empty(self):
        with open(self.cache_path, "w") as fh:
            fh.write("this is not json {{{")
        report = reportgen.run(self.rules, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})

    def test_non_dict_state_treated_as_empty(self):
        self._seed([{"digest": "x"}])
        report = reportgen.run(self.rules, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)


if __name__ == "__main__":
    unittest.main()

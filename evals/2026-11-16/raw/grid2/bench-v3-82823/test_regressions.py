"""Regression tests for the boolean transform, the cache hygiene fix and
the failure policy of a run (no report and no cache state after a cell
failed its transform)."""

import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms

BASE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE, "input")
RULES = os.path.join(BASE, "rules.example.toml")


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_forms(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", value), 1.0)

    def test_negative_forms(self):
        for value in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_other_input_raises_transform_error(self):
        for value in ("", " ", "y", "n", "1", "0", "maybe", "yess"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)

    def test_boolean_column_in_a_report(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("item,flag\n1,Yes\n2,no\n3,TRUE\n4,false\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        columns = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(columns["flag"]["non_empty"], 4)
        self.assertEqual(columns["flag"]["distinct"], 2)
        self.assertEqual(columns["flag"]["sample"], [0.0, 1.0])
        self.assertEqual(columns["flag"]["numeric_sum"], 1.0)


class FailurePolicyTests(unittest.TestCase):
    """A run in which a cell failed its transform must end with no report
    and no cache state, whichever way the transform failed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        os.makedirs(self.inp)

    def write_input(self, text):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write(text)

    def write_rules(self, text):
        with open(self.rules_path, "w") as fh:
            fh.write(text)

    def assert_no_artifacts(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_transform_error_leaves_no_report_or_cache(self):
        self.write_input("item,flag\n1,Yes\n2,maybe\n")
        self.write_rules('[transforms]\nflag = "boolean"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_crashing_transform_leaves_no_report_or_cache(self):
        self.write_input("item,flag\n1,Yes\n")
        self.write_rules('[transforms]\nflag = "boom"\n')

        def boom(value):
            raise RuntimeError("transform crashed")

        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_failed_run_after_a_successful_run_leaves_no_artifacts(self):
        self.write_input("item,flag\n1,Yes\n")
        self.write_rules('[transforms]\nflag = "boolean"\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertTrue(os.path.exists(self.cache_path))

        self.write_input("item,flag\n1,Yes\n2,maybe\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

    def read_state(self):
        with open(self.cache_path) as fh:
            return json.load(fh)

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh, indent=2)

    def poison(self, state):
        """Make the cached summaries wrong, so that reusing them would be
        visible in the report."""
        for entry in state.values():
            entry["summary"]["columns"].setdefault("amount", {})["numeric_sum"] = -1
        return state

    def test_future_entry_version_is_not_reused(self):
        self.run_tool()
        state = self.poison(self.read_state())
        for entry in state.values():
            entry["registry_version"] = "999"
        self.write_state(state)

        report = self.run_tool()
        columns = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(columns["amount"]["numeric_sum"], 275.59)
        self.assertEqual(report["total_rows"], 12012)
        rewritten = self.read_state()
        self.assertEqual(len(rewritten), 4)
        for entry in rewritten.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_future_file_version_is_not_reused(self):
        self.run_tool()
        state = self.poison(self.read_state())
        self.write_state({"version": "999", "files": state})

        report = self.run_tool()
        columns = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(columns["amount"]["numeric_sum"], 275.59)
        self.assertEqual(report["total_rows"], 12012)
        rewritten = self.read_state()
        self.assertNotIn("version", rewritten)
        self.assertNotIn("files", rewritten)
        self.assertEqual(len(rewritten), 4)

    def test_older_entry_version_is_not_reused(self):
        self.run_tool()
        state = self.poison(self.read_state())
        for entry in state.values():
            entry["registry_version"] = "1"
        self.write_state(state)

        report = self.run_tool()
        columns = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(columns["amount"]["numeric_sum"], 275.59)
        rewritten = self.read_state()
        for entry in rewritten.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_cached_run_reproduces_the_report(self):
        self.run_tool()
        with open(os.path.join(self.out, "report.json")) as fh:
            first = fh.read()
        self.run_tool()
        with open(os.path.join(self.out, "report.json")) as fh:
            second = fh.read()
        self.assertEqual(first, second)


class HtmlEscapingTests(unittest.TestCase):
    def test_column_and_file_names_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-escape-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a<b>.csv"), "w") as fh:
            fh.write("co<l>,label\nx,red <b> & bold\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nco<l> = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertNotIn("co<l>", html)
        self.assertIn("a&lt;b&gt;.csv", html)
        self.assertIn("red &lt;b&gt; &amp; bold", html)


if __name__ == "__main__":
    unittest.main()

"""Regression coverage for transforms, cache hygiene, and output safety."""

import json
import os
import tempfile
import unittest
from unittest import mock

import cache
import reportgen
import transforms


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input = os.path.join(self.tmp.name, "input")
        self.output = os.path.join(self.tmp.name, "output")
        self.cache = os.path.join(self.tmp.name, "cache", "state.json")
        self.rules = os.path.join(self.tmp.name, "rules.toml")
        os.makedirs(self.input)
        with open(self.rules, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

    def write_input(self, name, content):
        with open(os.path.join(self.input, name), "w", encoding="utf-8") as fh:
            fh.write(content)

    def run_tool(self):
        return reportgen.run(self.rules, self.input, self.output, self.cache)

    def assert_no_artifacts(self):
        for path in (self.cache, os.path.join(self.output, "report.html"),
                     os.path.join(self.output, "report.json")):
            self.assertFalse(os.path.exists(path), path)

    def test_boolean_transform_and_rules(self):
        for raw, expected in (("yes", 1.0), ("YeS", 1.0), ("TRUE", 1.0),
                              ("no", 0.0), ("NO", 0.0), ("False", 0.0),
                              (" true ", 1.0)):
            with self.subTest(raw=raw):
                result = transforms.apply("boolean", raw)
                self.assertIs(type(result), float)
                self.assertEqual(result, expected)
        for raw in ("", "1", "on", "truth"):
            with self.subTest(raw=raw), self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)
        self.write_input("flags.csv", "flag\nYES\nfalse\n")
        col = self.run_tool()["files"]["flags.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["numeric_sum"], 1.0)

    def test_future_state_version_is_discarded_and_rewritten(self):
        self.write_input("flags.csv", "flag\nyes\n")
        os.makedirs(os.path.dirname(self.cache))
        for state in ({"version": int(cache.REGISTRY_VERSION) + 1,
                       "files": {"foreign": {}}},
                      {"flags.csv": {"registry_version": str(int(cache.REGISTRY_VERSION) + 1)}}):
            with self.subTest(state=state):
                with open(self.cache, "w", encoding="utf-8") as fh:
                    json.dump(state, fh)
                report = self.run_tool()
                self.assertEqual(report["total_rows"], 1)
                rewritten = cache.load_state(self.cache)
                self.assertEqual(set(rewritten), {"flags.csv"})
                self.assertEqual(rewritten["flags.csv"]["registry_version"],
                                 cache.REGISTRY_VERSION)

    def test_skipped_transform_clears_previous_outputs_and_state(self):
        self.write_input("a.csv", "flag\nyes\n")
        self.run_tool()
        self.write_input("b.csv", "flag\ninvalid\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_unhandled_transform_crash_clears_previous_outputs_and_state(self):
        self.write_input("a.csv", "flag\nyes\n")
        self.run_tool()
        self.write_input("b.csv", "flag\nno\n")
        with mock.patch.dict(transforms.REGISTRY, {"boolean": mock.Mock(side_effect=RuntimeError("crash"))}):
            with self.assertRaises(RuntimeError):
                self.run_tool()
        self.assert_no_artifacts()

    def test_invalid_cached_summary_is_rejected(self):
        self.write_input("a.csv", "flag\nyes\n")
        self.run_tool()
        with open(self.cache, encoding="utf-8") as fh:
            state = json.load(fh)
        state["a.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "invalid"}]
        with open(self.cache, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_incomplete_cached_entry_for_other_input_is_not_retained(self):
        self.write_input("a.csv", "flag\nyes\n")
        self.run_tool()
        with open(self.cache, encoding="utf-8") as fh:
            state = json.load(fh)
        state["removed.csv"] = {"summary": {"skipped_rows": [
            {"row": 2, "column": "flag", "reason": "invalid"}]}}
        with open(self.cache, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_old_registry_entries_are_not_reused(self):
        self.write_input("a.csv", "flag\nyes\n")
        self.run_tool()
        with open(self.cache, encoding="utf-8") as fh:
            state = json.load(fh)
        state["a.csv"]["registry_version"] = str(int(cache.REGISTRY_VERSION) - 1)
        state["a.csv"]["summary"]["columns"]["flag"]["sample"] = [42.0]
        with open(self.cache, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        result = self.run_tool()
        self.assertEqual(result["files"]["a.csv"]["summary"]["columns"]["flag"]["sample"], [1.0])

    def test_generated_from_is_consistent_on_cache_hit(self):
        self.write_input("a.csv", "flag,other\n,hello\n")
        with open(self.rules, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "trim"\n')
        self.assertEqual(self.run_tool()["files"]["a.csv"]["generated_from"], 0)
        self.assertEqual(self.run_tool()["files"]["a.csv"]["generated_from"], 0)

    def test_html_escapes_all_input_text(self):
        self.write_input("<file>.csv", "<column>\n<script>&\n")
        self.run_tool()
        with open(os.path.join(self.output, "report.html"), encoding="utf-8") as fh:
            rendered = fh.read()
        self.assertIn("&lt;file&gt;.csv", rendered)
        self.assertIn("&lt;column&gt;", rendered)
        self.assertIn("&lt;script&gt;&amp;", rendered)
        self.assertNotIn("<script>", rendered)


if __name__ == "__main__":
    unittest.main()

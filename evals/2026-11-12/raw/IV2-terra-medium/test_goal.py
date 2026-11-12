"""Regression tests for the percent transform and report cache integrity."""

import json
import os
import tempfile
import unittest
from unittest import mock

import reportgen
import transforms


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input = os.path.join(self.tmp.name, "input")
        self.output = os.path.join(self.tmp.name, "output")
        self.rules = os.path.join(self.tmp.name, "rules.toml")
        self.state = os.path.join(self.tmp.name, "cache", "state.json")
        os.makedirs(self.input)
        self.write(self.rules, '[transforms]\nshare = "percent"\n')

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def run_report(self):
        return reportgen.run(self.rules, self.input, self.output, self.state)

    def test_percent_and_transform_failure_report(self):
        self.assertEqual(transforms.apply("percent", " 0.1837 "), 18.37)
        self.assertEqual(transforms.apply("percent", "-0.125"), -12.5)
        self.assertEqual(transforms.apply("percent", "0.123456"), 12.35)
        with self.assertRaises(transforms.TransformError):
            transforms.apply("percent", "not a number")
        self.write(os.path.join(self.input, "data.csv"),
                   "share\n0.1837\nbad\n0.5\n")
        report = self.run_report()
        summary = report["files"]["data.csv"]["summary"]
        self.assertEqual(summary["columns"]["share"]["sample"], [18.37, 50.0])
        self.assertEqual(summary["columns"]["share"]["numeric_sum"], 68.37)
        self.assertEqual(summary["skipped_rows"][0]["row"], 3)
        self.assertEqual(self.run_report(), report)

    def test_invalid_cache_is_rebuilt_even_with_no_inputs(self):
        os.makedirs(os.path.dirname(self.state))
        self.write(self.state, '{"truncated":')
        self.write(os.path.join(self.input, "data.csv"), "share\n0.5\n")
        report = self.run_report()
        self.assertEqual(report["total_rows"], 1)
        self.assertEqual(json.loads(self.read(self.state))["data.csv"]["rows"], 1)
        os.unlink(os.path.join(self.input, "data.csv"))
        self.write(self.state, "not json")
        self.run_report()
        self.assertEqual(json.loads(self.read(self.state)), {})

    def test_cache_invalidated_by_rules_change(self):
        self.write(os.path.join(self.input, "data.csv"), "share\n0.5\n")
        first = self.run_report()
        self.assertEqual(first["files"]["data.csv"]["summary"]["columns"]
                         ["share"]["sample"], [50.0])
        self.write(self.rules, '[transforms]\nshare = "round2"\n')
        second = self.run_report()
        self.assertEqual(second["files"]["data.csv"]["summary"]["columns"]
                         ["share"]["sample"], [0.5])

    def test_structurally_corrupt_cache_is_rebuilt(self):
        self.write(os.path.join(self.input, "data.csv"), "share\n0.5\n")
        expected = self.run_report()
        state = json.loads(self.read(self.state))
        state["data.csv"]["summary"] = {}
        self.write(self.state, json.dumps(state))
        self.assertEqual(self.run_report(), expected)
        self.assertIn("columns", json.loads(self.read(self.state))
                      ["data.csv"]["summary"])

    def test_cached_row_counts_match_parsed_rows_and_old_entries_expire(self):
        self.write(os.path.join(self.input, "data.csv"),
                   'share,note\n0.5,"one\ntwo"\n\n0.2,end\n')
        first = self.run_report()
        self.assertEqual(first["total_rows"], 2)
        self.assertEqual(self.run_report(), first)
        state = json.loads(self.read(self.state))
        state["data.csv"].pop("version")
        state["data.csv"]["rows"] = 999
        self.write(self.state, json.dumps(state))
        self.assertEqual(self.run_report(), first)

    def test_deleted_files_are_removed_from_cache(self):
        path = os.path.join(self.input, "data.csv")
        self.write(path, "share\n0.5\n")
        self.run_report()
        os.unlink(path)
        self.run_report()
        self.assertEqual(json.loads(self.read(self.state)), {})

    def test_unexpected_transform_failure_leaves_cache_and_report_unchanged(self):
        first = os.path.join(self.input, "a.csv")
        second = os.path.join(self.input, "b.csv")
        self.write(first, "share\n0.1\n")
        self.write(second, "share\n0.2\n")
        self.run_report()
        before = {path: self.read(path) for path in (
            self.state, os.path.join(self.output, "report.json"),
            os.path.join(self.output, "report.html"))}
        self.write(first, "share\n0.3\n")
        self.write(second, "share\n0.4\n")
        apply = transforms.apply

        def fail_on_second(name, value):
            if value == "0.4":
                raise RuntimeError("transform failed")
            return apply(name, value)

        with mock.patch.object(transforms, "apply", side_effect=fail_on_second):
            with self.assertRaisesRegex(RuntimeError, "transform failed"):
                self.run_report()
        self.assertEqual({path: self.read(path) for path in before}, before)

    def test_html_escapes_all_input_text(self):
        self.write(os.path.join(self.input, "<file>.csv"),
                   '"<column>",share\n"<b> & text",0.2\n')
        self.run_report()
        rendered = self.read(os.path.join(self.output, "report.html"))
        self.assertIn("&lt;file&gt;.csv", rendered)
        self.assertIn("&lt;column&gt;", rendered)
        self.assertIn("&lt;b&gt; &amp; text", rendered)


if __name__ == "__main__":
    unittest.main()

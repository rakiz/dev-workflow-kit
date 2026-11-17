"""Regression coverage for transforms, cache state, and report output."""

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
        self.state = os.path.join(self.tmp.name, "cache", "state.json")
        self.rules = os.path.join(self.tmp.name, "rules.toml")
        os.mkdir(self.input)
        self.write(self.rules, '[transforms]\nflag = "boolean"\n')

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_tool(self):
        return reportgen.run(self.rules, self.input, self.output, self.state)

    def assert_no_artifacts(self):
        self.assertFalse(os.path.exists(self.state))
        self.assertFalse(os.path.exists(os.path.join(self.output, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.output, "report.json")))

    def test_boolean_transform_and_report(self):
        for value in ("yes", "YES", "TrUe"):
            self.assertEqual(transforms.apply("boolean", value), 1.0)
        for value in ("no", "NO", "FaLsE"):
            self.assertEqual(transforms.apply("boolean", value), 0.0)
        for value in ("", "1", "maybe", " yes "):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)
        self.write(os.path.join(self.input, "flags.csv"), "flag\nYES\nfalse\n")
        column = self.run_tool()["files"]["flags.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(column["sample"], [0.0, 1.0])
        self.assertEqual(column["numeric_sum"], 1.0)

    def test_caught_transform_failure_removes_previous_artifacts(self):
        path = os.path.join(self.input, "flags.csv")
        self.write(path, "flag\nyes\n")
        self.run_tool()
        self.write(path, "flag\nyes\nmaybe\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_unhandled_transform_crash_removes_previous_artifacts(self):
        path = os.path.join(self.input, "flags.csv")
        self.write(path, "flag\nyes\n")
        self.run_tool()
        self.write(path, "flag\nno\n")
        with mock.patch("transforms.apply", side_effect=RuntimeError("crash")):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                self.run_tool()
        self.assert_no_artifacts()

    def test_invalid_cached_summary_is_rejected(self):
        self.write(os.path.join(self.input, "flags.csv"), "flag\nyes\n")
        self.run_tool()
        state = cache.load_state(self.state)
        state["flags.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "invalid"}]
        self.write(self.state, json.dumps(state))
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_invalid_untouched_cache_entry_is_not_retained(self):
        self.write(os.path.join(self.input, "flags.csv"), "flag\nyes\n")
        self.run_tool()
        state = cache.load_state(self.state)
        state["other.csv"] = {"summary": {"skipped_rows": [{"row": 2}]}}
        self.write(self.state, json.dumps(state))
        self.run_tool()
        self.assertNotIn("other.csv", cache.load_state(self.state))

    def test_later_file_crash_does_not_publish_earlier_file(self):
        self.write(os.path.join(self.input, "a.csv"), "flag\nyes\n")
        self.write(os.path.join(self.input, "b.csv"), "flag\nno\n")
        original = transforms.apply

        def fail_second(name, value):
            if value == "no":
                raise RuntimeError("crash")
            return original(name, value)

        with mock.patch("transforms.apply", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                self.run_tool()
        self.assert_no_artifacts()

    def test_future_versions_discard_cache_and_rewrite(self):
        self.write(os.path.join(self.input, "flags.csv"), "flag\nyes\n")
        for future in ({"version": int(cache.REGISTRY_VERSION) + 1, "entries": {}},
                       {"flags.csv": {"registry_version": str(int(cache.REGISTRY_VERSION) + 1)}}):
            with self.subTest(future=future):
                os.makedirs(os.path.dirname(self.state), exist_ok=True)
                self.write(self.state, json.dumps(future))
                result = self.run_tool()
                self.assertEqual(result["files"]["flags.csv"]["summary"]["columns"]
                                 ["flag"]["sample"], [1.0])
                state = cache.load_state(self.state)
                self.assertEqual(set(state), {"flags.csv"})
                self.assertEqual(state["flags.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_old_registry_entries_are_not_reused(self):
        self.write(os.path.join(self.input, "flags.csv"), "flag\nyes\n")
        self.run_tool()
        state = cache.load_state(self.state)
        state["flags.csv"]["registry_version"] = "1"
        state["flags.csv"]["summary"]["columns"]["flag"]["sample"] = [999.0]
        self.write(self.state, json.dumps(state))
        result = self.run_tool()
        self.assertEqual(result["files"]["flags.csv"]["summary"]["columns"]
                         ["flag"]["sample"], [1.0])

    def test_cached_generated_from_matches_fresh_run_for_empty_column(self):
        self.write(os.path.join(self.input, "empty.csv"), "other,flag\nx,\n")
        self.write(self.rules, '[transforms]\nflag = "trim"\n')
        first = self.run_tool()
        second = self.run_tool()
        self.assertEqual(first["files"]["empty.csv"]["generated_from"], 0)
        self.assertEqual(first, second)

    def test_html_escapes_all_input_text(self):
        self.write(self.rules, "[transforms]\n")
        self.write(os.path.join(self.input, "<file>.csv"), "<column>\n<b> & text\n")
        self.run_tool()
        with open(os.path.join(self.output, "report.html"), encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("&lt;file&gt;.csv", page)
        self.assertIn("&lt;column&gt;", page)
        self.assertIn("&lt;b&gt; &amp; text", page)
        self.assertNotIn("<b>", page)


if __name__ == "__main__":
    unittest.main()

"""Regression tests for transform failures, cache handling, and HTML output."""

import json
import os
import subprocess
import sys
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
        self.root = self.tmp.name
        self.input = os.path.join(self.root, "input")
        self.output = os.path.join(self.root, "output")
        self.rules = os.path.join(self.root, "rules.toml")
        self.state = os.path.join(self.root, "cache", "state.json")
        os.mkdir(self.input)
        self.write(self.rules, '[transforms]\nflag = "boolean"\n')
        self.write(os.path.join(self.input, "a.csv"), "flag\nyes\n")
        self.write(os.path.join(self.input, "b.csv"), "flag\nno\n")

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_tool(self):
        return reportgen.run(self.rules, self.input, self.output, self.state)

    def snapshot(self):
        paths = [os.path.join(self.output, "report.json"),
                 os.path.join(self.output, "report.html"), self.state]
        result = []
        for path in paths:
            with open(path, "rb") as fh:
                result.append(fh.read())
        return result

    def test_boolean_values_and_invalid_input(self):
        for value, expected in (("yes", 1.0), ("YeS", 1.0), ("TRUE", 1.0),
                                ("no", 0.0), ("nO", 0.0), ("False", 0.0)):
            with self.subTest(value=value):
                result = transforms.apply("boolean", value)
                self.assertIs(type(result), float)
                self.assertEqual(result, expected)
        for value in ("", "1", "on", " yes "):
            with self.subTest(value=value), self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)
        report = self.run_tool()
        self.assertEqual(report["files"]["a.csv"]["summary"]["columns"]["flag"]["sample"], [1.0])
        self.assertEqual(report["files"]["b.csv"]["summary"]["columns"]["flag"]["sample"], [0.0])

    def test_caught_transform_failure_preserves_outputs_and_exits_one(self):
        self.run_tool()
        before = self.snapshot()
        self.write(os.path.join(self.input, "a.csv"), "flag\ntrue\n")
        self.write(os.path.join(self.input, "b.csv"), "flag\ninvalid\n")
        process = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "reportgen.py"),
             "--rules", self.rules, "--input", self.input, "--output", self.output,
             "--cache", self.state], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertEqual(self.snapshot(), before)

    def test_transform_failure_does_not_create_outputs_on_first_run(self):
        self.write(os.path.join(self.input, "b.csv"), "flag\ninvalid\n")
        process = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "reportgen.py"),
             "--rules", self.rules, "--input", self.input, "--output", self.output,
             "--cache", self.state], capture_output=True, text=True)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertFalse(os.path.exists(self.output))
        self.assertFalse(os.path.exists(self.state))

    def test_invalid_cached_summary_is_rejected_before_publication(self):
        self.run_tool()
        with open(self.state, encoding="utf-8") as fh:
            state = json.load(fh)
        state["b.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "invalid"}]
        self.write(self.state, json.dumps(state))
        before = self.snapshot()
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertEqual(self.snapshot(), before)

    def test_unhandled_transform_crash_preserves_outputs_and_exits_one(self):
        self.run_tool()
        before = self.snapshot()
        self.write(os.path.join(self.input, "a.csv"), "flag\ntrue\n")
        self.write(os.path.join(self.input, "b.csv"), "flag\ncrash\n")
        script = ("import sys, reportgen, transforms\n"
                  "original = transforms.apply\n"
                  "def apply(name, value):\n"
                  "    if value == 'crash': raise RuntimeError('crash')\n"
                  "    return original(name, value)\n"
                  "transforms.apply = apply\n"
                  "sys.exit(1 if reportgen.main() is None else 0)\n")
        process = subprocess.run(
            [sys.executable, "-c", script, "--rules", self.rules, "--input", self.input,
             "--output", self.output, "--cache", self.state], capture_output=True, text=True,
            cwd=os.path.dirname(__file__))
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertEqual(self.snapshot(), before)

    def test_rules_read_once_for_multiple_files(self):
        real_open = open
        reads = []
        def counting_open(path, *args, **kwargs):
            if os.fspath(path) == self.rules:
                reads.append(path)
            return real_open(path, *args, **kwargs)
        with mock.patch("builtins.open", side_effect=counting_open):
            self.run_tool()
        self.assertEqual(len(reads), 1)

    def test_future_versions_discard_entire_cache_and_rebuild(self):
        self.run_tool()
        with open(self.state, encoding="utf-8") as fh:
            original = json.load(fh)
        for location in ("version", "registry_version", "entry"):
            with self.subTest(location=location):
                state = json.loads(json.dumps(original))
                if location == "entry":
                    state["a.csv"]["registry_version"] = str(int(cache.REGISTRY_VERSION) + 1)
                else:
                    state[location] = int(cache.REGISTRY_VERSION) + 1
                self.write(self.state, json.dumps(state))
                with mock.patch("transforms.apply", wraps=transforms.apply) as apply:
                    self.run_tool()
                self.assertEqual(apply.call_count, 2)
                with open(self.state, encoding="utf-8") as fh:
                    rebuilt = json.load(fh)
                self.assertEqual(set(rebuilt), {"a.csv", "b.csv"})
                self.assertEqual(rebuilt["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_old_registry_entries_are_not_reused(self):
        self.run_tool()
        with open(self.state, encoding="utf-8") as fh:
            state = json.load(fh)
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["summary"]["columns"]["flag"]["sample"] = [42.0]
        self.write(self.state, json.dumps(state))
        report = self.run_tool()
        self.assertEqual(report["files"]["a.csv"]["summary"]["columns"]["flag"]["sample"], [1.0])

    def test_cache_hit_preserves_generated_from_for_empty_columns(self):
        self.write(os.path.join(self.input, "a.csv"), "flag\n\"\"\n")
        self.write(self.rules, '[transforms]\nflag = "trim"\n')
        first = self.run_tool()
        second = self.run_tool()
        self.assertEqual(first, second)
        self.assertEqual(second["files"]["a.csv"]["generated_from"], 0)

    def test_html_escapes_file_column_and_sample(self):
        rendered = reportgen.render_html({"files": {"<file>": {"rows": 1,
            "summary": {"columns": {"<col>": {"non_empty": 1, "distinct": 1,
                                                 "sample": ["<b> &"]}}}}}})
        self.assertIn("&lt;file&gt;", rendered)
        self.assertIn("&lt;col&gt;", rendered)
        self.assertIn("&lt;b&gt; &amp;", rendered)


if __name__ == "__main__":
    unittest.main()

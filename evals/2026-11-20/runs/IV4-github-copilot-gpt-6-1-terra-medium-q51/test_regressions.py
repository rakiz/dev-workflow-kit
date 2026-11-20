"""Regression tests for transform, cache, and report integrity."""

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
        self.cache = os.path.join(self.root, "cache", "state.json")
        self.rules = os.path.join(self.root, "rules.toml")
        os.mkdir(self.input)
        self.write(self.rules, '[transforms]\nflag = "boolean"\n')
        self.write(os.path.join(self.input, "a.csv"), "flag\nyes\nno\n")

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_report(self):
        return reportgen.run(self.rules, self.input, self.output, self.cache)

    def artifacts(self):
        paths = [os.path.join(self.output, "report.json"),
                 os.path.join(self.output, "report.html"), self.cache]
        return [open_file(path) for path in paths]

    def test_boolean_transform_and_end_to_end(self):
        for raw, expected in [("yes", 1.0), ("TRUE", 1.0), ("nO", 0.0),
                              ("False", 0.0)]:
            with self.subTest(raw=raw):
                value = transforms.apply("boolean", raw)
                self.assertIs(type(value), float)
                self.assertEqual(value, expected)
        for raw in ("", "1", "on", "maybe", " yes "):
            with self.subTest(raw=raw), self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)
        column = self.run_report()["files"]["a.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(column["sample"], [0.0, 1.0])
        self.assertEqual(column["numeric_sum"], 1.0)

    def test_failed_transform_preserves_every_artifact_and_exits_one(self):
        self.run_report()
        before = self.artifacts()
        # A successful earlier file must not commit before a later failure.
        self.write(os.path.join(self.input, "a.csv"), "flag\ntrue\n")
        self.write(os.path.join(self.input, "b.csv"), "flag\ninvalid\n")
        process = subprocess.run(
            [sys.executable, reportgen.__file__, "--rules", self.rules,
             "--input", self.input, "--output", self.output, "--cache", self.cache],
            capture_output=True, text=True)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, "")
        self.assertIn("failed their transform", process.stderr)
        self.assertEqual(self.artifacts(), before)

    def test_transform_crash_preserves_every_artifact(self):
        self.run_report()
        before = self.artifacts()
        self.write(os.path.join(self.input, "a.csv"), "flag\ntrue\n")
        with mock.patch.object(transforms, "apply", side_effect=RuntimeError("crash")):
            self.assertIsNone(reportgen.main(["--rules", self.rules, "--input", self.input,
                                             "--output", self.output, "--cache", self.cache]))
        self.assertEqual(self.artifacts(), before)

    def test_first_failed_run_creates_no_artifacts(self):
        self.write(os.path.join(self.input, "b.csv"), "flag\ninvalid\n")
        process = subprocess.run(
            [sys.executable, reportgen.__file__, "--rules", self.rules,
             "--input", self.input, "--output", self.output, "--cache", self.cache],
            capture_output=True, text=True)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, "")
        self.assertFalse(os.path.exists(self.output))
        self.assertFalse(os.path.exists(self.cache))

    def test_cached_incomplete_summary_is_rejected(self):
        self.run_report()
        with open(self.cache, encoding="utf-8") as fh:
            state = json.load(fh)
        state["a.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "invalid"}]
        self.write(self.cache, json.dumps(state))
        before = self.artifacts()
        with self.assertRaises(reportgen.ValidationError):
            self.run_report()
        self.assertEqual(self.artifacts(), before)

    def test_future_versions_discard_cache_and_rewrite(self):
        for state in ({"version": 999, "entries": {"junk": {}}},
                      {"a.csv": {"registry_version": "999"}, "old.csv": {}}):
            with self.subTest(state=state):
                os.makedirs(os.path.dirname(self.cache), exist_ok=True)
                self.write(self.cache, json.dumps(state))
                report = self.run_report()
                self.assertEqual(report["total_rows"], 2)
                with open(self.cache, encoding="utf-8") as fh:
                    rewritten = json.load(fh)
                self.assertEqual(set(rewritten), {"a.csv"})
                self.assertEqual(rewritten["a.csv"]["registry_version"],
                                 cache.REGISTRY_VERSION)

    def test_old_registry_entry_is_not_reused(self):
        self.run_report()
        with open(self.cache, encoding="utf-8") as fh:
            state = json.load(fh)
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["summary"]["columns"]["flag"]["sample"] = ["stale"]
        self.write(self.cache, json.dumps(state))
        report = self.run_report()
        self.assertEqual(report["files"]["a.csv"]["summary"]["columns"]["flag"]["sample"],
                         [0.0, 1.0])

    def test_rules_read_once_for_multiple_inputs(self):
        self.write(os.path.join(self.input, "b.csv"), "flag\nfalse\n")
        original_open = open
        with mock.patch("builtins.open", wraps=original_open) as opened:
            self.run_report()
        reads = [call for call in opened.call_args_list
                 if call.args and call.args[0] == self.rules and call.args[1] == "r"]
        self.assertEqual(len(reads), 1)

    def test_cached_generated_from_matches_fresh_report_for_empty_column(self):
        self.write(self.rules, '[transforms]\nflag = "trim"\n')
        self.write(os.path.join(self.input, "a.csv"), 'flag,other\n"",x\n')
        first = self.run_report()
        second = self.run_report()
        self.assertEqual(first, second)
        self.assertEqual(second["files"]["a.csv"]["generated_from"], 0)

    def test_html_escapes_all_user_controlled_text(self):
        self.write(self.rules, "[transforms]\n")
        self.write(os.path.join(self.input, "<file>.csv"), "<column>\n<b> & text\n")
        self.run_report()
        with open(os.path.join(self.output, "report.html"), encoding="utf-8") as fh:
            rendered = fh.read()
        self.assertIn("&lt;file&gt;.csv", rendered)
        self.assertIn("&lt;column&gt;", rendered)
        self.assertIn("&lt;b&gt; &amp; text", rendered)


def open_file(path):
    with open(path, "rb") as fh:
        return fh.read()

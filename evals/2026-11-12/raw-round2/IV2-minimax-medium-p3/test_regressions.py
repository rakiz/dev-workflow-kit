"""Regression tests for the defects fixed along with the boolean
transform and the cache hygiene work.

Every test here pins down one defect: the shipped suites must stay green
and must keep pinning the behaviour they already pin.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import cache
import reportgen
import transforms

BASE = os.path.dirname(os.path.abspath(__file__))


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_forms_are_one(self):
        for value in ("yes", "Yes", "YES", "true", "True", "TRUE", " yes "):
            self.assertEqual(transforms.apply("boolean", value), 1.0)

    def test_negative_forms_are_zero(self):
        for value in ("no", "No", "NO", "false", "False", "FALSE", " no "):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_other_values_raise(self):
        for value in ("", "maybe", "1", "0", "y", "n", "oui"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)

    def test_boolean_column_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("id,flag\n1,Yes\n2,no\n3,TRUE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
        self.assertEqual(cols["flag"]["distinct"], 2)
        # numeric_sum sums the distinct transformed values (0.0 + 1.0).
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hyg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\n2,beta\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)

    def test_future_top_level_version_is_ignored_and_rewritten(self):
        self.write_state({"version": 999, "entries": {"t.csv": {"digest": "x"}}})
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertNotIn("version", state)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 2)

    def test_future_entry_version_forces_a_full_run(self):
        self.write_state({"t.csv": {"digest": "x", "rows": 99,
                                    "generated_from": 0, "rules_fp": "y",
                                    "registry_version": "999", "summary": {}}})
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 2)

    def test_future_version_does_not_crash_the_run(self):
        self.write_state({"version": "1000"})
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)

    def test_entry_from_another_registry_version_is_not_reused(self):
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["registry_version"] = "1"
        state["t.csv"]["rows"] = 99
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)

    def test_cached_summary_with_failed_cells_is_not_reused(self):
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "item", "reason": "not a number: 'x'"}]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        self.assertEqual(
            report["files"]["t.csv"]["summary"]["skipped_rows"], [])


class FailedTransformRunTests(unittest.TestCase):
    """A run in which any cell failed its transform must end the same way:
    no report emitted, no cache state left behind."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')

    def write_input(self, body):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write(body)

    def assert_no_artifacts(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_transform_writes_no_report_and_no_cache(self):
        self.write_input("item,label\n1,alpha\nn/a,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_failed_transform_removes_artifacts_of_a_previous_run(self):
        self.write_input("item,label\n1,alpha\n2,beta\n")
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertTrue(os.path.exists(self.cache_path))
        self.write_input("item,label\n1,alpha\nn/a,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_unhandled_transform_crash_ends_the_same_way(self):
        def boom(value):
            raise RuntimeError("boom")
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "boom"\n')
        self.write_input("item,label\n1,alpha\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_cli_reports_failure_with_a_nonzero_exit_code(self):
        self.write_input("item,label\n1,alpha\nn/a,beta\n")
        code = reportgen.main(["--rules", self.rules_path, "--input", self.inp,
                               "--output", self.out, "--cache", self.cache_path])
        self.assertIsNone(code)
        self.assert_no_artifacts()

    def test_cli_success_exits_zero(self):
        self.write_input("item,label\n1,alpha\n2,beta\n")
        report = reportgen.main(["--rules", self.rules_path, "--input", self.inp,
                                 "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(report["total_rows"], 2)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))


class HtmlEscapingTests(unittest.TestCase):
    def test_file_and_column_names_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a<b>.csv"), "w") as fh:
            fh.write("col<1>,x\nv,v\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("a<b>", html)
        self.assertNotIn("col<1>", html)
        self.assertIn("a&lt;b&gt;", html)
        self.assertIn("col&lt;1&gt;", html)


class CliExitCodeTests(unittest.TestCase):
    def test_process_exit_code_is_nonzero_on_transform_failure(self):
        tmp = tempfile.mkdtemp(prefix="rg3-cli-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\nn/a,beta\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", rules_path, "--input", inp, "--output", out,
             "--cache", cache_path],
            capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(out, "report.json")))
        self.assertFalse(os.path.exists(cache_path))


if __name__ == "__main__":
    unittest.main()

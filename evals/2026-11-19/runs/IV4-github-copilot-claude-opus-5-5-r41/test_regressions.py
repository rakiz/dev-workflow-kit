"""Regression tests for the boolean transform, cache hygiene and the
failure-policy / single-read invariants."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import cache
import reportgen
import transforms

BASE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(BASE, "rules.example.toml")
INPUT_DIR = os.path.join(BASE, "input")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")

    def write(self, path, text):
        with open(path, "w") as fh:
            fh.write(text)

    def snapshot(self):
        out = {}
        for p in (os.path.join(self.out, "report.json"),
                  os.path.join(self.out, "report.html"), self.cache_path):
            with open(p, "rb") as fh:
                out[p] = fh.read()
        return out

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)


class BooleanTests(unittest.TestCase):
    def test_boolean(self):
        for v in ("yes", "YES", "True", "tRuE"):
            self.assertEqual(transforms.apply("boolean", v), 1.0)
        for v in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", v), 0.0)
        for v in ("y", "1", "", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", v)


class FailurePolicyTests(Base):
    def prime(self):
        self.write(os.path.join(self.inp, "a.csv"), "n,flag\n1,yes\n2,no\n")
        self.write(self.rules, '[transforms]\nn = "round2"\nflag = "boolean"\n')
        report = self.run_tool()
        self.assertEqual(
            report["files"]["a.csv"]["summary"]["columns"]["flag"]["numeric_sum"], 1.0)
        return self.snapshot()

    def test_transform_error_exits_1_and_keeps_outputs(self):
        before = self.prime()
        self.write(os.path.join(self.inp, "a.csv"), "n,flag\n1,yes\nx,no\n")
        with self.assertRaises(SystemExit) as cm:
            reportgen.main(["--rules", self.rules, "--input", self.inp,
                            "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(self.snapshot(), before)

    def test_failure_in_later_file_does_not_touch_cache(self):
        before = self.prime()
        self.write(os.path.join(self.inp, "a.csv"), "n,flag\n3,yes\n")
        self.write(os.path.join(self.inp, "b.csv"), "n,flag\n1,bad\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertEqual(self.snapshot(), before)

    def test_unhandled_crash_keeps_outputs(self):
        before = self.prime()
        self.write(os.path.join(self.inp, "a.csv"), "n,flag\n5,yes\n")
        with mock.patch.dict(transforms.REGISTRY,
                             {"round2": lambda v: 1 / 0}):
            with self.assertRaises(ZeroDivisionError):
                self.run_tool()
        self.assertEqual(self.snapshot(), before)

    def test_cli_exit_code(self):
        self.write(os.path.join(self.inp, "a.csv"), "n\nx\n")
        self.write(self.rules, '[transforms]\nn = "round2"\n')
        p = subprocess.run([sys.executable, os.path.join(BASE, "reportgen.py"),
                            "--rules", self.rules, "--input", self.inp,
                            "--output", self.out, "--cache", self.cache_path],
                           capture_output=True)
        self.assertEqual(p.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))


class RulesReadOnceTests(Base):
    def test_rules_read_once(self):
        real = reportgen.load_rules
        with mock.patch.object(reportgen, "load_rules", side_effect=real) as m:
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(m.call_count, 1)


class CacheHygieneTests(Base):
    def test_future_state_ignored_and_rewritten(self):
        self.write(os.path.join(self.inp, "a.csv"), "n\n1\n")
        self.write(self.rules, '[transforms]\nn = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path))
        self.write(self.cache_path, json.dumps({
            "version": 99,
            "a.csv": {"registry_version": "99", "weird": True}}))
        report = self.run_tool()
        self.assertEqual(report["files"]["a.csv"]["rows"], 1)
        state = json.load(open(self.cache_path))
        self.assertEqual(set(state), {"a.csv"})
        self.assertEqual(state["a.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_older_registry_entry_not_reused(self):
        self.write(os.path.join(self.inp, "a.csv"), "n\n1\n")
        self.write(self.rules, '[transforms]\nn = "round2"\n')
        self.run_tool()
        state = json.load(open(self.cache_path))
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["summary"] = {"columns": {}, "skipped_rows": []}
        self.write(self.cache_path, json.dumps(state))
        report = self.run_tool()
        self.assertIn("n", report["files"]["a.csv"]["summary"]["columns"])

    def test_generated_from_stable_across_cache_hit(self):
        self.write(os.path.join(self.inp, "a.csv"), "n,m\n1,\n")
        self.write(self.rules, '[transforms]\nn = "round2"\nm = "trim"\n')
        first = self.run_tool()["files"]["a.csv"]["generated_from"]
        second = self.run_tool()["files"]["a.csv"]["generated_from"]
        self.assertEqual(first, 1)
        self.assertEqual(second, 1)


class NumericSumTests(Base):
    def test_duplicate_values_counted(self):
        self.write(os.path.join(self.inp, "a.csv"), "n\n10\n10\n5\n")
        self.write(self.rules, '[transforms]\nn = "round2"\n')
        cols = self.run_tool()["files"]["a.csv"]["summary"]["columns"]
        self.assertEqual(cols["n"]["numeric_sum"], 25.0)


if __name__ == "__main__":
    unittest.main()

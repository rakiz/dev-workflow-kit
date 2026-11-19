"""Regression tests for the boolean transform, cache hygiene and the
failure-policy / single-read invariants."""

import builtins
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import cache
import reportgen
import transforms

BASE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE, "input")
RULES = os.path.join(BASE, "rules.example.toml")


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
        res = {}
        for p in (os.path.join(self.out, "report.json"),
                  os.path.join(self.out, "report.html"), self.cache_path):
            with open(p, "rb") as fh:
                res[p] = fh.read()
        return res


class BooleanTests(unittest.TestCase):
    def test_boolean(self):
        for v in ("yes", "YES", "True", "tRuE"):
            self.assertEqual(transforms.apply("boolean", v), 1.0)
        for v in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", v), 0.0)
        for v in ("", "y", "1", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", v)


class NumericSumTests(Base):
    def test_duplicate_values_are_summed(self):
        self.write(os.path.join(self.inp, "a.csv"), "f,n\nyes,2\nyes,2\nno,2\n")
        self.write(self.rules, '[transforms]\nf = "boolean"\nn = "round2"\n')
        rep = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        cols = rep["files"]["a.csv"]["summary"]["columns"]
        self.assertEqual(cols["f"]["numeric_sum"], 2.0)
        self.assertEqual(cols["n"]["numeric_sum"], 6.0)


class FailurePolicyTests(Base):
    def good_run(self):
        self.write(os.path.join(self.inp, "a.csv"), "f\nyes\n")
        self.write(self.rules, '[transforms]\nf = "boolean"\n')
        self.assertEqual(reportgen.main(["--rules", self.rules, "--input", self.inp,
                                         "--output", self.out, "--cache", self.cache_path]), 0)
        return self.snapshot()

    def argv(self):
        return ["--rules", self.rules, "--input", self.inp,
                "--output", self.out, "--cache", self.cache_path]

    def test_caught_transform_failure_exits_1_and_keeps_artifacts(self):
        before = self.good_run()
        self.write(os.path.join(self.inp, "a.csv"), "f\nyes\n")
        self.write(os.path.join(self.inp, "b.csv"), "f\nmaybe\n")
        self.assertEqual(reportgen.main(self.argv()), 1)
        self.assertEqual(self.snapshot(), before)

    def test_unhandled_crash_keeps_artifacts(self):
        before = self.good_run()
        self.write(os.path.join(self.inp, "a.csv"), "f\nno\n")
        with mock.patch.dict(transforms.REGISTRY,
                             {"boolean": lambda v: 1 / 0}):
            with self.assertRaises(ZeroDivisionError):
                reportgen.main(self.argv())
        self.assertEqual(self.snapshot(), before)

    def test_cached_and_fresh_generated_from_agree(self):
        self.write(os.path.join(self.inp, "a.csv"), "f,g\nyes,\n")
        self.write(self.rules, '[transforms]\nf = "boolean"\ng = "trim"\n')
        first = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        second = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(first, second)


class RulesReadOnceTests(Base):
    def test_rules_read_once(self):
        real_open = builtins.open
        count = [0]

        def counting_open(path, *a, **k):
            if os.path.abspath(str(path)) == os.path.abspath(RULES):
                count[0] += 1
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", counting_open):
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(count[0], 1)


class CacheHygieneTests(Base):
    def setUp(self):
        super().setUp()
        self.write(os.path.join(self.inp, "a.csv"), "f\nyes\n")
        self.write(self.rules, '[transforms]\nf = "boolean"\n')
        os.makedirs(os.path.dirname(self.cache_path))

    def check_rewritten(self):
        rep = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(rep["files"]["a.csv"]["summary"]["columns"]["f"]["sample"], [1.0])
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"a.csv"})
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_entry_version(self):
        self.write(self.cache_path, json.dumps({"a.csv": {
            "registry_version": "99", "digest": cache.file_digest(
                os.path.join(self.inp, "a.csv")), "layout": "new"}}))
        self.check_rewritten()

    def test_future_top_level_version(self):
        self.write(self.cache_path, json.dumps(
            {"version": 3, "entries": {"a.csv": {}}}))
        self.check_rewritten()

    def test_older_registry_entry_not_reused(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["summary"]["columns"]["f"]["sample"] = ["stale"]
        self.write(self.cache_path, json.dumps(state))
        self.check_rewritten()


if __name__ == "__main__":
    unittest.main()

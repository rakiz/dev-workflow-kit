"""Regression tests for the boolean transform, cache hygiene, and the
failure-policy invariants."""

import builtins
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
    def test_affirmative_forms(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms(self):
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_input_raises(self):
        for raw in ("", "1", "0", "y", "n", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("label\na\nb\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nlabel = "upper"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_future_schema_version_is_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path))
        future = {"version": int(cache.REGISTRY_VERSION) + 1,
                  "t.csv": {"digest": "stale", "summary": {"skipped_rows": [1]}}}
        with open(self.cache_path, "w") as fh:
            json.dump(future, fh)
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        self.assertEqual(
            report["files"]["t.csv"]["summary"]["columns"]["label"]["sample"],
            ["A", "B"])
        state = cache.load_state(self.cache_path)
        self.assertNotIn("version", state)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_is_ignored(self):
        os.makedirs(os.path.dirname(self.cache_path))
        future = {"t.csv": {"digest": "stale", "rows": 0,
                            "registry_version": str(int(cache.REGISTRY_VERSION) + 1),
                            "summary": {"skipped_rows": []}}}
        with open(self.cache_path, "w") as fh:
            json.dump(future, fh)
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 2)

    def test_report_is_identical_on_cache_hit(self):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("label,blank\na,\nb,\n")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nlabel = "upper"\nblank = "upper"\n')
        first = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        second = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(first, second)
        self.assertEqual(first["files"]["t.csv"]["generated_from"], 1)

    def test_stale_registry_version_is_not_reused(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["registry_version"] = "1"
        state["t.csv"]["summary"]["columns"]["label"]["sample"] = ["SENTINEL"]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(
            report["files"]["t.csv"]["summary"]["columns"]["label"]["sample"],
            ["A", "B"])
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FailurePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv = os.path.join(self.inp, "t.csv")
        with open(self.csv, "w") as fh:
            fh.write("n\n1\n2\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nn = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _run_main(self):
        return subprocess.run(
            [sys.executable, "reportgen.py", "--rules", self.rules,
             "--input", self.inp, "--output", self.out,
             "--cache", self.cache_path],
            cwd=BASE, capture_output=True, text=True)

    def _snapshot(self):
        values = {}
        for path in (os.path.join(self.out, "report.json"),
                     os.path.join(self.out, "report.html"),
                     self.cache_path):
            with open(path, "rb") as fh:
                values[path] = fh.read()
        return values

    def test_failed_transform_exits_1_and_leaves_outputs_intact(self):
        first = self._run_main()
        self.assertEqual(first.returncode, 0)
        before = self._snapshot()
        with open(self.csv, "w") as fh:
            fh.write("n\n1\nnot-a-number\n")
        second = self._run_main()
        self.assertEqual(second.returncode, 1)
        self.assertEqual(before, self._snapshot())

    def test_unhandled_transform_crash_emits_nothing(self):
        def boom(value):
            raise RuntimeError("boom")
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nn = "boom"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class RulesReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reads-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        for name in ("a.csv", "b.csv", "c.csv"):
            with open(os.path.join(self.inp, name), "w") as fh:
                fh.write("n\n1\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nn = "round2"\n')

    def test_rules_file_is_read_once_per_run(self):
        real_open = builtins.open
        reads = []

        def counting_open(file, *args, **kwargs):
            if os.fspath(file) == self.rules:
                reads.append(file)
            return real_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(self.rules, self.inp,
                          os.path.join(self.tmp, "out"),
                          os.path.join(self.tmp, "cache", "state.json"))
        finally:
            builtins.open = real_open
        self.assertEqual(len(reads), 1)


if __name__ == "__main__":
    unittest.main()

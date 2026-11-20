"""Regression tests for defects fixed in this change.

Each test pins one defect: the boolean transform, single rules read per
run, all-or-nothing failure handling, future-version cache tolerance, and
cache/report consistency for `generated_from`.
"""

import builtins
import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms

BASE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(BASE, "rules.example.toml")
INPUT_DIR = os.path.join(BASE, "input")


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_forms_are_one(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", " true "):
            self.assertEqual(transforms.apply("boolean", value), 1.0)

    def test_negative_forms_are_zero(self):
        for value in ("no", "NO", "No", "false", "FALSE", " false "):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_other_input_raises(self):
        for value in ("", "1", "0", "y", "n", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_rules(self, body):
        path = os.path.join(self.tmp, "rules.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path

    def write_input(self, name, body):
        path = os.path.join(self.inp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path


class RulesReadOnceTests(TempCase):
    def test_rules_file_read_once_per_run(self):
        self.write_input("t.csv", "item\n1\n2\n")
        rules_path = self.write_rules('[transforms]\nitem = "round2"\n')
        rules_abs = os.path.abspath(rules_path)
        original_open = builtins.open
        reads = {"count": 0}

        def counting_open(file, *args, **kwargs):
            try:
                if os.path.abspath(file) == rules_abs:
                    reads["count"] += 1
            except TypeError:
                pass
            return original_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        finally:
            builtins.open = original_open
        self.assertEqual(reads["count"], 1)


class FailurePolicyTests(TempCase):
    def good_run(self):
        self.write_input("t.csv", "item\n1\n2\n")
        rules_path = self.write_rules('[transforms]\nitem = "round2"\n')
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        snapshots = {}
        for path in (os.path.join(self.out, "report.json"),
                     os.path.join(self.out, "report.html"),
                     self.cache_path):
            with open(path, "rb") as fh:
                snapshots[path] = fh.read()
        return rules_path, snapshots

    def test_transform_error_leaves_outputs_and_cache_intact(self):
        rules_path, snapshots = self.good_run()
        self.write_input("t.csv", "item\nnope\n2\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        for path, before in snapshots.items():
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), before, path)

    def test_unhandled_transform_crash_leaves_outputs_and_cache_intact(self):
        rules_path, snapshots = self.good_run()

        def boom(value):
            raise RuntimeError("boom")

        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        self.write_input("t.csv", "item\n1\n2\n")
        crash_rules = self.write_rules('[transforms]\nitem = "boom"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(crash_rules, self.inp, self.out, self.cache_path)
        for path, before in snapshots.items():
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), before, path)

    def test_main_returns_nonzero_on_transform_failure(self):
        self.write_input("t.csv", "item\nnope\n")
        rules_path = self.write_rules('[transforms]\nitem = "round2"\n')
        code = reportgen.main(["--rules", rules_path, "--input", self.inp,
                               "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


class FutureCacheVersionTests(TempCase):
    def future_state(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        state = {"t.csv": {"digest": "bogus", "rows": 99,
                           "generated_from": 99, "rules_fp": "bogus",
                           "registry_version": "999",
                           "summary": {"columns": {}, "skipped_rows": []}}}
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        return state

    def test_future_version_is_treated_as_empty(self):
        state = self.future_state()
        self.assertEqual(cache.load_state(self.cache_path), {})
        # A naive lookup would have reused the bogus entry (rows == 99).
        self.assertEqual(state["t.csv"]["rows"], 99)

    def test_run_completes_and_rewrites_valid_state(self):
        self.future_state()
        self.write_input("t.csv", "item\n1\n2\n")
        rules_path = self.write_rules('[transforms]\nitem = "round2"\n')
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["rows"], 2)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_top_level_future_version_is_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": "999"}, fh)
        self.assertEqual(cache.load_state(self.cache_path), {})


class CacheConsistencyTests(TempCase):
    def test_generated_from_is_stable_across_cache_reuse(self):
        self.write_input("t.csv", "item,status\n1,\n2,\n")
        rules_path = self.write_rules(
            '[transforms]\nitem = "trim"\nstatus = "upper"\n')
        first = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        second = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(first["files"]["t.csv"]["generated_from"], 1)
        self.assertEqual(second, first)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()

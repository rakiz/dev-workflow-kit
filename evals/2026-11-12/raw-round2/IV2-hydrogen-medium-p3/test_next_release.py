"""Tests for the boolean transform, cache hygiene, and defect regressions."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import cache
import reportgen
import transforms


class BooleanTransformTests(unittest.TestCase):
    def test_boolean_valid_values_case_insensitive(self):
        for raw in ("yes", "YES", "Yes", " true ", "TRUE", "True"):
            res = transforms.apply("boolean", raw)
            self.assertIs(type(res), float)
            self.assertEqual(res, 1.0)
        for raw in ("no", "NO", "No", " false ", "FALSE", "False"):
            res = transforms.apply("boolean", raw)
            self.assertIs(type(res), float)
            self.assertEqual(res, 0.0)

    def test_boolean_invalid_raises_transform_error(self):
        for bad in ("", "1", "0", "y", "n", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)

    def test_boolean_end_to_end_numeric_sum(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,active\n1,YES\n2,no\n3,True\n4,FALSE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        report = reportgen.run(rules_path, inp, out, cache_path)
        col = report["files"]["flags.csv"]["summary"]["columns"]["active"]
        self.assertEqual(col["numeric_sum"], 1.0)
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["distinct"], 2)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "a.csv"), "w", encoding="utf-8") as fh:
            fh.write("item,flag\nx,yes\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)

    def test_future_top_level_version_rewrites_valid_state(self):
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": "10", "a.csv": {"sha256": "deadbeef"}}, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertNotIn("version", state)
        self.assertIn("a.csv", state)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_rewrites_valid_state(self):
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"a.csv": {"registry_version": "99", "sha256": "x"}}, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertIn("digest", state["a.csv"])


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_regression_transform_error_leaves_no_report_or_cache(self):
        with open(os.path.join(self.inp, "01_good.csv"), "w", encoding="utf-8") as fh:
            fh.write("val\n1.5\n")
        with open(os.path.join(self.inp, "02_bad.csv"), "w", encoding="utf-8") as fh:
            fh.write("val\nnope\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_regression_unhandled_crash_leaves_no_report_or_cache(self):
        with open(os.path.join(self.inp, "01_good.csv"), "w", encoding="utf-8") as fh:
            fh.write("val\n1.5\n")
        with open(os.path.join(self.inp, "02_boom.csv"), "w", encoding="utf-8") as fh:
            fh.write("val\n2.5\n")
        calls = {"n": 0}

        def flaky(v):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return float(v)

        with mock.patch.dict(transforms.REGISTRY, {"round2": flaky}):
            with self.assertRaises(RuntimeError):
                reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_regression_older_registry_version_not_reused(self):
        csv_path = os.path.join(self.inp, "a.csv")
        with open(csv_path, "w", encoding="utf-8") as fh:
            fh.write("val\n1.5\n")
        rules = reportgen.load_rules(self.rules_path)
        rules_fp = cache.rules_fingerprint(rules)
        digest = cache.file_digest(csv_path)
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        stale_summary = {
            "columns": {"val": {"non_empty": 999, "distinct": 999, "sample": [999.0]}},
            "skipped_rows": [],
        }
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({
                "a.csv": {
                    "digest": digest,
                    "rows": 1,
                    "generated_from": 1,
                    "rules_fp": rules_fp,
                    "registry_version": "1",
                    "summary": stale_summary,
                }
            }, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(
            report["files"]["a.csv"]["summary"]["columns"]["val"]["non_empty"], 1
        )
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)


if __name__ == "__main__":
    unittest.main()

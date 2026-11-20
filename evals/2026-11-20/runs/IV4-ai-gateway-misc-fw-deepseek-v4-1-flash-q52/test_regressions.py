"""Regression tests for defects fixed in the boolean/cache-hygiene release.

Each test corresponds to one defect (or one new guarantee from the brief):
boolean transform, transactional failure policy, rules read-once, cache
reuse keyed on the registry version, cache written by a future schema
version, and fresh/cached report equivalence.
"""

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


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "NO", "No", "false", "FALSE"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_rejects_other_input(self):
        for raw in ("maybe", "1", "0", ""):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class FailurePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _write_good_state(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "report.json"), "w") as fh:
            fh.write("GOODJSON\n")
        with open(os.path.join(self.out, "report.html"), "w") as fh:
            fh.write("GOODHTML\n")
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            fh.write('{"other.csv": {"digest": "x"}}')

    def _bad_run(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as fh:
            fh.write("amount\nnope\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\namount = "round2"\n')
        return reportgen.main(["--rules", rules_path, "--input", inp,
                               "--output", self.out, "--cache", self.cache_path])

    def test_failure_exits_one_and_emits_nothing(self):
        self._write_good_state()
        before = {p: open(p, "rb").read() for p in (
            os.path.join(self.out, "report.json"),
            os.path.join(self.out, "report.html"), self.cache_path)}
        rc = self._bad_run()
        self.assertEqual(rc, 1)
        for path, data in before.items():
            self.assertEqual(open(path, "rb").read(), data, path)

    def test_run_raises_validation_error(self):
        self._write_good_state()
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as fh:
            fh.write("amount\nnope\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\namount = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, inp, self.out, self.cache_path)

    def test_unhandled_transform_crash_is_a_failure(self):
        self._write_good_state()
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as fh:
            fh.write("amount\nanything\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\namount = "explode"\n')
        original = transforms.REGISTRY.get("explode")

        def explode(value):
            raise RuntimeError("boom")

        transforms.REGISTRY["explode"] = explode
        try:
            rc = reportgen.main(["--rules", rules_path, "--input", inp,
                                 "--output", self.out, "--cache", self.cache_path])
        finally:
            if original is None:
                del transforms.REGISTRY["explode"]
            else:
                transforms.REGISTRY["explode"] = original
        self.assertEqual(rc, 1)
        self.assertEqual(open(os.path.join(self.out, "report.json")).read(),
                         "GOODJSON\n")


class RulesReadOnceTests(unittest.TestCase):
    def test_rules_file_read_at_most_once_per_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reads-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        real_open = builtins.open
        rules_abs = os.path.abspath(RULES)
        reads = []

        def counting_open(path, *args, **kwargs):
            try:
                if os.path.abspath(path) == rules_abs:
                    reads.append(path)
            except TypeError:
                pass
            return real_open(path, *args, **kwargs)

        with mock.patch("builtins.open", counting_open):
            reportgen.run(RULES, INPUT_DIR, os.path.join(tmp, "out"),
                          os.path.join(tmp, "cache", "state.json"))
        self.assertEqual(len(reads), 1)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hyg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_future_schema_version_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path))
        digest = cache.file_digest(os.path.join(INPUT_DIR, "small_devices.csv"))
        rules = reportgen.load_rules(RULES)
        rules_fp = cache.rules_fingerprint(rules)
        future = {"small_devices.csv": {
            "digest": digest, "rules_fp": rules_fp,
            "registry_version": "999", "payload": {}}}
        with open(self.cache_path, "w") as fh:
            json.dump(future, fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        self.assertTrue(state)
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(report["files"]["small_devices.csv"]["generated_from"], 1)

    def test_older_registry_version_not_reused(self):
        os.makedirs(os.path.dirname(self.cache_path))
        digest = cache.file_digest(os.path.join(INPUT_DIR, "small_transactions.csv"))
        rules = reportgen.load_rules(RULES)
        rules_fp = cache.rules_fingerprint(rules)
        stale = {"small_transactions.csv": {
            "digest": digest, "rules_fp": rules_fp, "rows": 999,
            "generated_from": 999, "registry_version": "1",
            "summary": {"columns": {"bogus": {"non_empty": 1, "distinct": 1,
                                              "sample": ["x"]}},
                        "skipped_rows": []}}}
        with open(self.cache_path, "w") as fh:
            json.dump(stale, fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertNotIn("bogus", report["files"]["small_transactions.csv"]
                         ["summary"]["columns"])
        self.assertEqual(report["files"]["small_transactions.csv"]["rows"], 4)


class ReportStabilityTests(unittest.TestCase):
    def test_fresh_and_cached_reports_match(self):
        tmp = tempfile.mkdtemp(prefix="rg3-stable-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        first = reportgen.run(RULES, INPUT_DIR, out, cache_path)
        first_json = json.load(open(os.path.join(out, "report.json")))
        second = reportgen.run(RULES, INPUT_DIR, out, cache_path)
        second_json = json.load(open(os.path.join(out, "report.json")))
        self.assertEqual(first, second)
        self.assertEqual(first_json, second_json)


if __name__ == "__main__":
    unittest.main()

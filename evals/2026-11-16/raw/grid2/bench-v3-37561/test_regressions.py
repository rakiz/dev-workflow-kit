"""Regression tests for the boolean transform, cache version hygiene, and
the all-or-nothing transform-failure invariant."""

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
    def test_affirmative_forms_are_one(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms_are_zero(self):
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_input_raises(self):
        for raw in ("", "maybe", "1", "0", "y", "n"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class RenderEscapingTest(unittest.TestCase):
    def test_sample_values_are_html_escaped(self):
        report = {"files": {"labels.csv": {
            "rows": 1,
            "summary": {"columns": {"label": {
                "non_empty": 1, "distinct": 1,
                "sample": ["red <b> & bold"]}}}}}}
        rendered = reportgen.render_html(report)
        self.assertNotIn("<b>", rendered)
        self.assertIn("red &lt;b&gt; &amp; bold", rendered)


class FutureCacheVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    def test_future_version_is_treated_as_empty_and_rewritten(self):
        self._write_state({"small_transactions.csv": {
            "registry_version": "999", "unknown_future_field": True}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        cols = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(cols["amount"]["numeric_sum"], 275.59)
        state = cache.load_state(self.cache_path)
        self.assertIn("small_transactions.csv", state)
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_older_version_entry_is_not_reused(self):
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(self.cache_path, encoding="utf-8") as fh:
            state = json.load(fh)
        state["small_transactions.csv"]["registry_version"] = "1"
        state["small_transactions.csv"]["summary"] = {"columns": {}}
        self._write_state(state)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        cols = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(cols["amount"]["numeric_sum"], 275.59)


class FailureInvariantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\namount = "currency_amount"\nitem = "boom"\n')

    def _write(self, name, text):
        with open(os.path.join(self.inp, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def _assert_nothing_written(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_caught_transform_failure_writes_nothing(self):
        self._write("a.csv", "amount\n$1.00\n")
        self._write("z.csv", "amount\n$2.00\nbroken\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self._assert_nothing_written()

    def test_unhandled_transform_crash_writes_nothing(self):
        self._write("a.csv", "amount\n$1.00\n")

        def boom(value):
            raise RuntimeError("boom")

        self._write("t.csv", "item\nx\n")
        with mock.patch.dict(transforms.REGISTRY, {"boom": boom}):
            with self.assertRaises(RuntimeError):
                reportgen.run(self.rules_path, self.inp, self.out,
                              self.cache_path)
        self._assert_nothing_written()


class CacheReuseConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reuse-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_cached_second_run_matches_first(self):
        first = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        second = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(first, second)
        self.assertEqual(
            first["files"]["small_devices.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()

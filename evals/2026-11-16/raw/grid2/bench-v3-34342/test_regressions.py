"""Regression tests for the next-release defects: boolean transform,
cache hygiene, atomic failure policy, cached bookkeeping, HTML escaping."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import cache
import reportgen
import transforms


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0, raw)
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0, raw)

    def test_other_input_raises(self):
        for raw in ("maybe", "1", "0", ""):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def assert_no_output(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))


class FailurePolicyTests(ReportCase):
    def test_transform_error_leaves_no_report_or_cache(self):
        _write(os.path.join(self.inp, "t.csv"), "n\n1\nn/a\n")
        _write(self.rules, '[transforms]\nn = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_output()

    def test_unhandled_crash_leaves_no_report_or_cache(self):
        _write(os.path.join(self.inp, "t.csv"), "n\n1\n")
        _write(self.rules, '[transforms]\nn = "round2"\n')
        with mock.patch.object(transforms, "apply",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.run_tool()
        self.assert_no_output()

    def test_failed_run_discards_previous_cache(self):
        path = os.path.join(self.inp, "t.csv")
        _write(path, "n\n1\n")
        _write(self.rules, '[transforms]\nn = "round2"\n')
        self.run_tool()
        self.assertTrue(os.path.exists(self.cache_path))
        _write(path, "n\nn/a\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertFalse(os.path.exists(self.cache_path))


class CacheHygieneTests(ReportCase):
    def _write_future_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path))
        _write(self.cache_path, json.dumps(state))

    def test_future_entry_version_is_treated_as_empty(self):
        future = str(int(cache.REGISTRY_VERSION) + 1)
        _write(os.path.join(self.inp, "t.csv"), "n\n1\n2\n")
        _write(self.rules, '[transforms]\nn = "round2"\n')
        self._write_future_state({"t.csv": {
            "digest": "stale", "rows": 999, "generated_from": 0,
            "rules_fp": "stale", "registry_version": future,
            "summary": {"columns": {}, "skipped_rows": []}}})
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path, encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 2)

    def test_future_top_level_version_is_treated_as_empty(self):
        future = int(cache.REGISTRY_VERSION) + 1
        _write(os.path.join(self.inp, "t.csv"), "n\n1\n2\n")
        _write(self.rules, '[transforms]\nn = "round2"\n')
        self._write_future_state({"version": future})
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path, encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertNotIn("version", state)
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_stale_registry_entry_is_recomputed(self):
        _write(os.path.join(self.inp, "t.csv"), "n\n1\n2\n")
        _write(self.rules, '[transforms]\nn = "round2"\n')
        self.run_tool()
        with open(self.cache_path, encoding="utf-8") as fh:
            state = json.load(fh)
        state["t.csv"]["registry_version"] = "0"
        state["t.csv"]["rows"] = 999
        _write(self.cache_path, json.dumps(state))
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path, encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 2)

    def test_cached_generated_from_matches_fresh_run(self):
        _write(os.path.join(self.inp, "t.csv"), "a,b\n1,\n")
        _write(self.rules, '[transforms]\nb = "trim"\n')
        first = self.run_tool()
        second = self.run_tool()
        self.assertEqual(first["files"]["t.csv"]["generated_from"], 0)
        self.assertEqual(second["files"]["t.csv"]["generated_from"], 0)


class HtmlEscapingRegressionTests(ReportCase):
    def test_markup_in_values_is_escaped(self):
        _write(os.path.join(self.inp, "labels.csv"),
               "item,label\ni1,red <b> & bold\n")
        _write(self.rules, '[transforms]\nitem = "trim"\n')
        self.run_tool()
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertIn("red &lt;b&gt; &amp; bold", html)


if __name__ == "__main__":
    unittest.main()

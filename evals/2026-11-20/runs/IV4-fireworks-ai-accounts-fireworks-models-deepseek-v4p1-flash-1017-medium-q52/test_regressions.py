"""Regression tests for the boolean transform, cache version hygiene, the
single-read rules invariant, and the all-or-nothing failure policy."""

import contextlib
import io
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
    def test_affirmative_and_negative_forms(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", " True "):
            self.assertEqual(transforms.apply("boolean", value), 1.0)
        for value in ("no", "NO", "No", "false", "FALSE", " False "):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_other_input_raises_transform_error(self):
        for value in ("", "1", "y", "maybe", "truthy"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)


class RunFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        self._write("t.csv", "item,label\n1,alpha\n2,beta\n")
        self._write_rules('item = "round2"\n')

    def _write(self, name, text):
        with open(os.path.join(self.inp, name), "w") as fh:
            fh.write(text)

    def _write_rules(self, body):
        with open(self.rules, "w") as fh:
            fh.write("[transforms]\n" + body)

    def _main(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = reportgen.main(["--rules", self.rules, "--input", self.inp,
                                   "--output", self.out,
                                   "--cache", self.cache_path])
        return code

    def _snapshot(self):
        paths = [os.path.join(self.out, "report.json"),
                 os.path.join(self.out, "report.html"), self.cache_path]
        result = {}
        for path in paths:
            with open(path, "rb") as fh:
                result[path] = fh.read()
        return result


class RulesReadTests(RunFixture):
    def test_rules_file_is_read_once_per_run(self):
        self._write("u.csv", "item,x\n3,y\n")
        calls = []
        real = reportgen.load_rules

        def counting(path):
            calls.append(path)
            return real(path)

        with mock.patch.object(reportgen, "load_rules", counting):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(len(calls), 1)


class CacheVersionTests(RunFixture):
    def test_future_entry_version_is_discarded_and_state_rewritten(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["registry_version"] = "999"
        state["t.csv"]["summary"] = {"columns": {}}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["summary"]["columns"]
                         ["item"]["numeric_sum"], 3.0)
        with open(self.cache_path) as fh:
            rewritten = json.load(fh)
        self.assertEqual(rewritten["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertIn("item", rewritten["t.csv"]["summary"]["columns"])

    def test_future_envelope_schema_does_not_crash(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        future = {"version": "999", "files": {"t.csv": {"registry_version": "999"}}}
        with open(self.cache_path, "w") as fh:
            json.dump(future, fh)

        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path) as fh:
            rewritten = json.load(fh)
        self.assertNotIn("version", rewritten)
        self.assertEqual(rewritten["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_incomplete_cached_summary_is_not_reused(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "item", "reason": "boom"}]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["summary"]["skipped_rows"], [])

    def test_older_cached_summary_is_not_reused(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["registry_version"] = "1"
        state["t.csv"]["summary"] = {"columns": {}}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertIn("item", report["files"]["t.csv"]["summary"]["columns"])


class FailurePolicyTests(RunFixture):
    def _prepare_good_run(self):
        self._main()
        return self._snapshot()

    def test_transform_error_leaves_report_and_cache_untouched(self):
        before = self._prepare_good_run()
        self._write("t.csv", "item,label\nn/a,alpha\n")

        self.assertEqual(self._main(), 1)
        self.assertEqual(self._snapshot(), before)

    def test_unhandled_transform_crash_leaves_outputs_untouched(self):
        before = self._prepare_good_run()
        self._write("t.csv", "item,label\n9,alpha\n")
        with mock.patch.object(transforms, "apply",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(self._main(), 1)
        self.assertEqual(self._snapshot(), before)


class HtmlEscapingTests(unittest.TestCase):
    def test_render_escapes_sample_values(self):
        report = {"files": {"x.csv": {
            "rows": 1,
            "summary": {"columns": {"label": {
                "non_empty": 1, "distinct": 1,
                "sample": ["red <b> & bold"]}}}}}}
        rendered = reportgen.render_html(report)
        self.assertNotIn("<b>", rendered)
        self.assertIn("red &lt;b&gt; &amp; bold", rendered)


if __name__ == "__main__":
    unittest.main()

"""Regression tests for transform, cache, and HTML correctness."""

import json
import os
import tempfile
import unittest
from unittest import mock

import cache
import reportgen
import transforms


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input = os.path.join(self.tmp.name, "input")
        self.output = os.path.join(self.tmp.name, "output")
        self.state = os.path.join(self.tmp.name, "cache", "state.json")
        self.rules = os.path.join(self.tmp.name, "rules.toml")
        os.makedirs(self.input)
        self.write(self.rules, '[transforms]\nvalue = "percent"\n')

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_report(self):
        return reportgen.run(self.rules, self.input, self.output, self.state)

    def assert_no_artifacts(self):
        for path in (self.state, os.path.join(self.output, "report.json"),
                     os.path.join(self.output, "report.html")):
            self.assertFalse(os.path.exists(path), path)

    def test_percent_transform_and_rules(self):
        self.assertEqual(transforms.apply("percent", " 0.1837 "), 18.37)
        self.assertEqual(transforms.apply("percent", "-0.123456"), -12.35)
        with self.assertRaises(transforms.TransformError):
            transforms.apply("percent", "n/a")
        self.write(os.path.join(self.input, "data.csv"), "value\n0.1837\n")
        report = self.run_report()
        self.assertEqual(report["files"]["data.csv"]["summary"]["columns"]
                         ["value"]["sample"], [18.37])

    def test_corrupt_state_is_replaced_after_full_run(self):
        self.write(os.path.join(self.input, "data.csv"), "value\n0.2\n")
        self.run_report()
        for corrupt in ('{"data.csv":', '[]', '\udcff'):
            with self.subTest(corrupt=repr(corrupt)):
                with open(self.state, "wb") as fh:
                    fh.write(corrupt.encode("utf-8", errors="surrogateescape"))
                with mock.patch.object(reportgen, "summarize_file",
                                       wraps=reportgen.summarize_file) as summarize:
                    self.run_report()
                    self.assertEqual(summarize.call_count, 1)
                with open(self.state, encoding="utf-8") as fh:
                    self.assertEqual(set(json.load(fh)), {"data.csv"})

    def test_transform_failures_clear_previous_artifacts(self):
        good = os.path.join(self.input, "a.csv")
        bad = os.path.join(self.input, "b.csv")
        self.write(good, "value\n0.2\n")
        self.write(bad, "value\n0.3\n")
        for error in (transforms.TransformError("invalid"), RuntimeError("crash")):
            with self.subTest(error=type(error).__name__):
                self.run_report()
                self.write(good, "value\n0.4\n")
                self.write(bad, "value\n0.5\n")
                original = transforms.apply

                def apply(name, value):
                    if value == "0.5":
                        raise error
                    return original(name, value)

                with mock.patch.object(transforms, "apply", side_effect=apply):
                    with self.assertRaises(type(error)):
                        self.run_report()
                self.assert_no_artifacts()
                self.write(good, "value\n0.2\n")
                self.write(bad, "value\n0.3\n")

    def test_invalid_cell_aborts_instead_of_skipping(self):
        self.write(os.path.join(self.input, "data.csv"), "value\n0.2\nbad\n")
        with self.assertRaises(transforms.TransformError):
            self.run_report()
        self.assert_no_artifacts()

    def test_caught_transform_failure_aborts(self):
        self.write(os.path.join(self.input, "data.csv"), "value\n0.2\n")
        self.run_report()
        self.write(os.path.join(self.input, "data.csv"), "value\n0.3\n")
        with mock.patch.object(reportgen, "summarize_file", return_value={
                "columns": {}, "skipped_rows": [{"row": 2}]}):
            with self.assertRaises(transforms.TransformError):
                self.run_report()
        self.assert_no_artifacts()

    def test_cached_skipped_rows_are_reprocessed(self):
        path = os.path.join(self.input, "data.csv")
        self.write(path, "value\n0.2\n")
        self.run_report()
        state = cache.load_state(self.state)
        state["data.csv"]["summary"]["skipped_rows"] = [{"row": 2}]
        cache.save_state(state, self.state)
        with mock.patch.object(reportgen, "summarize_file",
                               wraps=reportgen.summarize_file) as summarize:
            self.run_report()
            self.assertEqual(summarize.call_count, 1)
        self.assertEqual(cache.load_state(self.state)["data.csv"]
                         ["summary"]["skipped_rows"], [])

    def test_changed_rules_invalidate_cache(self):
        self.write(os.path.join(self.input, "data.csv"), "value\n0.2\n")
        self.run_report()
        self.write(self.rules, '[transforms]\nvalue = "round2"\n')
        report = self.run_report()
        self.assertEqual(report["files"]["data.csv"]["summary"]["columns"]
                         ["value"]["sample"], [0.2])

    def test_cached_rows_match_parsed_multiline_rows(self):
        self.write(self.rules, '[transforms]\n')
        self.write(os.path.join(self.input, "data.csv"), 'value\n"one\ntwo"\n\nthree\n')
        first = self.run_report()
        second = self.run_report()
        self.assertEqual(first, second)
        self.assertEqual(second["total_rows"], 2)

    def test_removed_inputs_disappear_from_cache(self):
        path = os.path.join(self.input, "data.csv")
        self.write(path, "value\n0.2\n")
        self.run_report()
        os.remove(path)
        self.run_report()
        self.assertEqual(cache.load_state(self.state), {})

    def test_html_escapes_all_input_text(self):
        self.write(self.rules, '[transforms]\n')
        self.write(os.path.join(self.input, "<file>.csv"), '<col>\n"<b> & x"\n')
        self.run_report()
        with open(os.path.join(self.output, "report.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("&lt;file&gt;.csv", html)
        self.assertIn("&lt;col&gt;", html)
        self.assertIn("&lt;b&gt; &amp; x", html)


if __name__ == "__main__":
    unittest.main()

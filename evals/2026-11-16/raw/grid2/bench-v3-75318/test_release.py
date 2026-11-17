"""Regression coverage for boolean transforms and complete-run publication."""

import contextlib
import csv
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import cache
import reportgen
import transforms


class BooleanTests(unittest.TestCase):
    def test_accepted_forms_are_floats(self):
        for value, expected in (("yes", 1.0), ("YES", 1.0), ("TrUe", 1.0),
                                ("no", 0.0), ("NO", 0.0), ("FaLsE", 0.0)):
            with self.subTest(value=value):
                actual = transforms.apply("boolean", value)
                self.assertIsInstance(actual, float)
                self.assertEqual(actual, expected)

    def test_other_inputs_raise_transform_error(self):
        for value in ("", "1", "0", "on", "off", "maybe", " yes", "no "):
            with self.subTest(value=value):
                with self.assertRaises(transforms.TransformError):
                    transforms.apply("boolean", value)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="rg-release-")
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.input = os.path.join(self.root, "input")
        self.output = os.path.join(self.root, "output")
        self.rules = os.path.join(self.root, "rules.toml")
        self.cache = os.path.join(self.root, "cache", "state.json")
        os.mkdir(self.input)
        self.write_rules("boolean")
        self.write_csv("a.csv", [["value"], ["yes"], ["NO"]])

    def write_rules(self, transform):
        with open(self.rules, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nvalue = "%s"\n' % transform)

    def write_csv(self, name, rows):
        with open(os.path.join(self.input, name), "w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(rows)

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache), exist_ok=True)
        with open(self.cache, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    def run_tool(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return reportgen.run(self.rules, self.input, self.output, self.cache)

    def assert_no_artifacts(self):
        for path in (self.cache, self.cache + ".tmp",
                     os.path.join(self.output, "report.json"),
                     os.path.join(self.output, "report.html")):
            self.assertFalse(os.path.exists(path), path)

    def test_boolean_rules_report_and_cache_hit(self):
        first = self.run_tool()
        column = first["files"]["a.csv"]["summary"]["columns"]["value"]
        self.assertEqual(column, {"non_empty": 2, "distinct": 2,
                                  "sample": [0.0, 1.0], "numeric_sum": 1.0})
        with mock.patch.object(transforms, "apply", side_effect=AssertionError("cache miss")):
            self.assertEqual(self.run_tool(), first)
        with open(os.path.join(self.output, "report.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), first)

    def test_future_schema_is_empty_and_rewritten_even_without_inputs(self):
        for version in (int(cache.REGISTRY_VERSION) + 1, "100"):
            for empty in (False, True):
                with self.subTest(version=version, empty=empty):
                    self.write_csv("a.csv", [["value"], ["yes"]])
                    if empty:
                        os.remove(os.path.join(self.input, "a.csv"))
                    self.write_state({"version": version, "entries": ["future layout"]})
                    self.assertEqual(cache.load_state(self.cache), {})
                    with mock.patch.object(transforms, "apply", wraps=transforms.apply) as apply:
                        self.run_tool()
                    self.assertEqual(apply.call_count, 0 if empty else 1)
                    state = cache.load_state(self.cache)
                    self.assertEqual(set(state), set() if empty else {"a.csv"})
                    if not empty:
                        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_old_missing_and_future_entry_versions_are_not_reused(self):
        for version in (None, "2", "100"):
            with self.subTest(version=version):
                self.run_tool()
                state = cache.load_state(self.cache)
                if version is None:
                    del state["a.csv"]["registry_version"]
                else:
                    state["a.csv"]["registry_version"] = version
                state["a.csv"]["summary"]["columns"] = {}
                self.write_state(state)
                with mock.patch.object(transforms, "apply", wraps=transforms.apply) as apply:
                    report = self.run_tool()
                self.assertEqual(apply.call_count, 2)
                self.assertIn("value", report["files"]["a.csv"]["summary"]["columns"])

    def test_transform_failures_never_publish_or_leave_old_artifacts(self):
        for warm in (False, True):
            for error in (transforms.TransformError("bad cell"), RuntimeError("crash"),
                          KeyboardInterrupt(), SystemExit(7)):
                with self.subTest(warm=warm, error=type(error).__name__):
                    self.write_csv("z.csv", [["value"], ["yes"]])
                    if warm:
                        self.run_tool()
                    self.write_csv("z.csv", [["value"], ["yes"], ["FAIL"], ["no"]])
                    original = transforms.apply

                    def apply(name, value):
                        if value == "FAIL":
                            raise error
                        return original(name, value)

                    expected = (reportgen.ValidationError
                                if isinstance(error, transforms.TransformError) else type(error))
                    with mock.patch.object(transforms, "apply", side_effect=apply), \
                            mock.patch.object(cache, "save_state") as save, \
                            mock.patch.object(reportgen, "render_html") as render:
                        with self.assertRaises(expected):
                            self.run_tool()
                        save.assert_not_called()
                        render.assert_not_called()
                    self.assert_no_artifacts()

    def test_invalid_boolean_and_unknown_rule_leave_no_artifacts(self):
        for transform, value in (("boolean", "maybe"), ("unknown", "yes")):
            with self.subTest(transform=transform):
                self.write_rules("boolean")
                self.write_csv("a.csv", [["value"], ["yes"]])
                self.run_tool()
                self.write_rules(transform)
                self.write_csv("a.csv", [["value"], [value]])
                with self.assertRaises(reportgen.ValidationError):
                    self.run_tool()
                self.assert_no_artifacts()

    def test_main_caught_validation_failure_leaves_no_artifacts(self):
        self.run_tool()
        self.write_csv("a.csv", [["value"], ["maybe"]])
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            result = reportgen.main(["--rules", self.rules, "--input", self.input,
                                     "--output", self.output, "--cache", self.cache])
        self.assertIsNone(result)
        self.assertIn("1 cell(s) failed their transform", stderr.getvalue())
        self.assert_no_artifacts()

    def test_invalid_cached_summary_is_rejected_before_publication(self):
        self.run_tool()
        state = cache.load_state(self.cache)
        state["a.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "value", "reason": "earlier failure"}]
        self.write_state(state)
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_cache_matches_current_inputs_including_hits_and_empty_run(self):
        self.write_csv("b.csv", [["value"], ["true"]])
        self.write_csv("removed.csv", [["value"], ["no"]])
        self.run_tool()
        os.remove(os.path.join(self.input, "removed.csv"))
        self.write_csv("b.csv", [["value"], ["false"]])
        with mock.patch.object(transforms, "apply", wraps=transforms.apply) as apply:
            self.run_tool()
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(set(cache.load_state(self.cache)), {"a.csv", "b.csv"})
        os.remove(os.path.join(self.input, "a.csv"))
        os.remove(os.path.join(self.input, "b.csv"))
        self.run_tool()
        self.assertEqual(cache.load_state(self.cache), {})

    def test_generated_from_is_identical_for_fresh_and_cached_empty_columns(self):
        self.write_rules("trim")
        for rows in ([["value", "other"], ["", "x"]], [["value", "other"]]):
            with self.subTest(rows=rows):
                self.write_csv("a.csv", rows)
                fresh = self.run_tool()
                self.assertEqual(fresh["files"]["a.csv"]["generated_from"], 0)
                self.assertEqual(cache.load_state(self.cache)["a.csv"]["generated_from"], 0)
                self.assertEqual(self.run_tool(), fresh)

    def test_html_escapes_filenames_columns_and_samples(self):
        name = "<b>&.csv"
        column = "<i>&"
        value = 'red <b> & "bold"'
        self.write_csv(name, [[column], [value]])
        report = self.run_tool()
        with open(os.path.join(self.output, "report.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("<h1>&lt;b&gt;&amp;.csv</h1>", html)
        self.assertIn("<td>&lt;i&gt;&amp;</td>", html)
        self.assertIn("red &lt;b&gt; &amp; &quot;bold&quot;", html)
        self.assertNotIn("<b>", html)
        self.assertEqual(report["files"][name]["summary"]["columns"][column]["sample"], [value])


if __name__ == "__main__":
    unittest.main()

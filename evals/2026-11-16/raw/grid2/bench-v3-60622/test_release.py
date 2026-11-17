"""Regression coverage for boolean transforms and all-or-nothing runs."""

import json
import os
import tempfile
import unittest
from unittest import mock

import cache
import reportgen
import transforms


class BooleanTests(unittest.TestCase):
    def test_boolean_forms_are_floats(self):
        for raw, expected in (("yes", 1.0), ("TRUE", 1.0), ("YeS", 1.0),
                              ("no", 0.0), ("false", 0.0), ("FaLsE", 0.0)):
            with self.subTest(raw=raw):
                value = transforms.apply("boolean", raw)
                self.assertIs(type(value), float)
                self.assertEqual(value, expected)

    def test_other_inputs_are_rejected(self):
        for raw in ("", "1", "0", "maybe", " yes", "false "):
            with self.subTest(raw=raw), self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class RunTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="rg-release-")
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.inp = os.path.join(self.root, "in")
        self.out = os.path.join(self.root, "out")
        self.state_path = os.path.join(self.root, "cache", "state.json")
        self.rules = os.path.join(self.root, "rules.toml")
        os.makedirs(self.inp)
        self.write(self.rules, '[transforms]\nflag = "boolean"\n')
        self.csv("a.csv", "flag\nyes\nno\nTRUE\nfalse\n")

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def csv(self, name, text):
        self.write(os.path.join(self.inp, name), text)

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.state_path)

    def seed_state(self, state):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        self.write(self.state_path, json.dumps(state))

    def assert_no_artifacts(self):
        for path in (self.state_path, self.state_path + ".tmp",
                     os.path.join(self.out, "report.json"),
                     os.path.join(self.out, "report.html")):
            self.assertFalse(os.path.exists(path), path)

    def test_boolean_rules_end_to_end_and_cache_hit(self):
        first = self.run_tool()
        cols = first["files"]["a.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"], {"non_empty": 4, "distinct": 2,
                                       "sample": [0.0, 1.0], "numeric_sum": 1.0})
        with mock.patch.object(transforms, "apply", side_effect=AssertionError("cache miss")):
            self.assertEqual(self.run_tool(), first)

    def test_future_versions_discard_cache_and_rewrite(self):
        first = self.run_tool()
        original = cache.load_state(self.state_path)
        for field in ("version", "registry_version", "entry"):
            for version in (int(cache.REGISTRY_VERSION) + 1, "10"):
                with self.subTest(field=field, version=version):
                    state = json.loads(json.dumps(original))
                    if field == "entry":
                        state["a.csv"]["registry_version"] = version
                    else:
                        state = {field: version, "entries": state}
                    self.seed_state(state)
                    with mock.patch.object(reportgen, "summarize_file",
                                           wraps=reportgen.summarize_file) as summarize:
                        self.assertEqual(self.run_tool(), first)
                        summarize.assert_called_once()
                    self.assertEqual(cache.load_state(self.state_path), original)

    def test_old_registry_entries_are_not_reused(self):
        self.run_tool()
        state = cache.load_state(self.state_path)
        state["a.csv"]["registry_version"] = str(int(cache.REGISTRY_VERSION) - 1)
        self.seed_state(state)
        with mock.patch.object(reportgen, "summarize_file",
                               wraps=reportgen.summarize_file) as summarize:
            self.run_tool()
            summarize.assert_called_once()
        self.assertEqual(cache.load_state(self.state_path)["a.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_caught_cell_failure_leaves_no_report_or_cache(self):
        for prior_run in (False, True):
            with self.subTest(prior_run=prior_run):
                if prior_run:
                    self.run_tool()
                self.csv("z.csv", "flag\nmaybe\n")
                with mock.patch.object(cache, "save_state", wraps=cache.save_state) as save, \
                        mock.patch.object(reportgen, "render_html") as render:
                    with self.assertRaises(reportgen.ValidationError):
                        self.run_tool()
                    save.assert_not_called()
                    render.assert_not_called()
                self.assert_no_artifacts()
                os.remove(os.path.join(self.inp, "z.csv"))

    def test_raised_transform_errors_and_crashes_clean_up(self):
        for failure in (transforms.TransformError("failure"), RuntimeError("crash"),
                        KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                self.run_tool()
                self.csv("z.csv", "flag\nyes\n")
                self.write(self.state_path + ".tmp", "partial")
                with mock.patch.object(transforms, "apply", side_effect=failure):
                    expected = (reportgen.ValidationError
                                if isinstance(failure, transforms.TransformError)
                                else type(failure))
                    with self.assertRaises(expected):
                        self.run_tool()
                self.assert_no_artifacts()
                os.remove(os.path.join(self.inp, "z.csv"))

    def test_summary_exception_cleans_up_earlier_success(self):
        self.run_tool()
        self.csv("a.csv", "flag\nTRUE\n")
        self.csv("z.csv", "flag\nfalse\n")
        with mock.patch.object(reportgen, "summarize_file",
                               side_effect=[{"columns": {}, "skipped_rows": []},
                                            transforms.TransformError("raised")]):
            with self.assertRaises(transforms.TransformError):
                self.run_tool()
        self.assert_no_artifacts()

    def test_invalid_cached_summary_is_rejected(self):
        self.run_tool()
        state = cache.load_state(self.state_path)
        state["a.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "failed"}]
        self.seed_state(state)
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_cli_caught_validation_failure_still_cleans_up(self):
        self.run_tool()
        self.csv("z.csv", "flag\ninvalid\n")
        with mock.patch("sys.stderr"):
            self.assertIsNone(reportgen.main([
                "--rules", self.rules, "--input", self.inp,
                "--output", self.out, "--cache", self.state_path]))
        self.assert_no_artifacts()

    def test_generated_from_is_stable_for_empty_mapped_columns(self):
        self.write(self.rules, '[transforms]\nflag = "trim"\n')
        self.csv("a.csv", "flag,other\n,x\n,y\n")
        first = self.run_tool()
        self.assertEqual(first["files"]["a.csv"]["generated_from"], 0)
        self.assertEqual(cache.load_state(self.state_path)["a.csv"]["generated_from"], 0)
        self.assertEqual(self.run_tool(), first)

    def test_html_escapes_all_input_text(self):
        self.csv("a.csv", 'flag,<column>\nyes,<b> & "quoted"\n')
        os.rename(os.path.join(self.inp, "a.csv"),
                  os.path.join(self.inp, "<file>.csv"))
        self.run_tool()
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("&lt;file&gt;.csv", html)
        self.assertIn("&lt;column&gt;", html)
        self.assertIn("&lt;b&gt; &amp; &quot;quoted&quot;", html)
        self.assertNotIn("<b>", html)


if __name__ == "__main__":
    unittest.main()

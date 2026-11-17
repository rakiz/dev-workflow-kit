"""Regression coverage for boolean transforms and all-or-nothing runs."""

import contextlib
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
    def test_accepted_values_are_floats(self):
        for raw, expected in (("yes", 1.0), ("YES", 1.0), ("TrUe", 1.0),
                              ("no", 0.0), ("NO", 0.0), ("FaLsE", 0.0)):
            with self.subTest(raw=raw):
                result = transforms.apply("boolean", raw)
                self.assertIs(type(result), float)
                self.assertEqual(result, expected)

    def test_other_values_raise_transform_error(self):
        for raw in ("", "1", "0", "maybe", " yes", "false "):
            with self.subTest(raw=raw):
                with self.assertRaises(transforms.TransformError):
                    transforms.apply("boolean", raw)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="rg-release-")
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.inp = os.path.join(self.root, "input")
        self.out = os.path.join(self.root, "output")
        self.state = os.path.join(self.root, "cache", "state.json")
        self.rules = os.path.join(self.root, "rules.toml")
        os.makedirs(self.inp)
        self.write(self.rules, '[transforms]\nflag = "boolean"\n')
        self.write(os.path.join(self.inp, "a.csv"), "flag\nyes\nTRUE\nno\nFALSE\n")
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.state)

    def assert_no_artifacts(self):
        for path in (self.state, self.state + ".tmp",
                     os.path.join(self.out, "report.json"),
                     os.path.join(self.out, "report.html")):
            with self.subTest(path=path):
                self.assertFalse(os.path.exists(path))

    def test_boolean_rules_report_and_cache_hit(self):
        first = self.run_tool()
        col = first["files"]["a.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col, {"non_empty": 4, "distinct": 2,
                               "sample": [0.0, 1.0], "numeric_sum": 1.0})
        with mock.patch.object(reportgen, "summarize_file",
                               side_effect=AssertionError("cache miss")):
            self.assertEqual(self.run_tool(), first)

    def test_future_state_is_ignored_and_rewritten(self):
        for key in ("version", "registry_version"):
            for version in (int(cache.REGISTRY_VERSION) + 1, "1000"):
                with self.subTest(key=key, version=version):
                    self.write(self.state, json.dumps({key: version, "files": []}))
                    self.assertEqual(cache.load_state(self.state), {})
                    with mock.patch.object(reportgen, "summarize_file",
                                           wraps=reportgen.summarize_file) as summarize:
                        self.run_tool()
                    self.assertEqual(summarize.call_count, 1)
                    state = cache.load_state(self.state)
                    self.assertEqual(set(state), {"a.csv"})
                    self.assertEqual(state["a.csv"]["registry_version"],
                                     cache.REGISTRY_VERSION)

    def test_future_state_with_no_inputs_is_rewritten(self):
        os.remove(os.path.join(self.inp, "a.csv"))
        self.write(self.state, '{"version": 1000, "files": []}')
        self.assertEqual(self.run_tool()["total_rows"], 0)
        self.assertEqual(cache.load_state(self.state), {})

    def test_registry_version_mismatch_forces_recomputation(self):
        for version in (None, "0", "1000"):
            with self.subTest(version=version):
                self.run_tool()
                state = cache.load_state(self.state)
                entry = state["a.csv"]
                entry["registry_version"] = version
                entry["summary"]["columns"]["flag"]["numeric_sum"] = 999.0
                cache.save_state(state, self.state)
                report = self.run_tool()
                self.assertEqual(report["files"]["a.csv"]["summary"]
                                 ["columns"]["flag"]["numeric_sum"], 1.0)
                self.assertEqual(cache.load_state(self.state)["a.csv"]
                                 ["registry_version"], cache.REGISTRY_VERSION)

    def test_generated_from_is_stable_for_empty_mapped_columns(self):
        self.write(self.rules, '[transforms]\nflag = "trim"\nother = "trim"\n')
        self.write(os.path.join(self.inp, "a.csv"), "flag,other\nyes,\n")
        first = self.run_tool()
        self.assertEqual(first["files"]["a.csv"]["generated_from"], 1)
        self.assertEqual(cache.load_state(self.state)["a.csv"]["generated_from"], 1)
        self.assertEqual(self.run_tool(), first)

    def test_state_drops_inputs_removed_since_previous_run(self):
        self.write(os.path.join(self.inp, "b.csv"), "flag\nno\n")
        self.run_tool()
        os.remove(os.path.join(self.inp, "b.csv"))
        self.run_tool()
        self.assertEqual(set(cache.load_state(self.state)), {"a.csv"})

    def test_caught_cell_failure_leaves_no_reports_or_cache(self):
        for warm in (False, True):
            with self.subTest(warm=warm):
                if warm:
                    self.run_tool()
                self.write(os.path.join(self.inp, "b.csv"), "flag\nyes\ninvalid\n")
                with mock.patch.object(cache, "save_state") as save:
                    with mock.patch.object(reportgen, "render_html") as render:
                        with self.assertRaises(reportgen.ValidationError):
                            self.run_tool()
                save.assert_not_called()
                render.assert_not_called()
                self.assert_no_artifacts()
                os.remove(os.path.join(self.inp, "b.csv"))

    def test_transform_crashes_and_interruptions_remove_previous_artifacts(self):
        for error in (transforms.TransformError("raised"), RuntimeError("crash"),
                      KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                self.run_tool()
                self.write(os.path.join(self.inp, "b.csv"), "flag\nyes\n")
                # The first file is a cache hit; the second transform fails.
                with mock.patch.object(reportgen, "summarize_file", side_effect=error):
                    with self.assertRaises(type(error)):
                        self.run_tool()
                self.assert_no_artifacts()
                os.remove(os.path.join(self.inp, "b.csv"))

    def test_unhandled_cell_transform_crash_does_not_publish_partial_work(self):
        self.write(os.path.join(self.inp, "b.csv"), "flag\ncrash\n")
        original = transforms.apply

        def apply(name, raw):
            if raw == "crash":
                raise RuntimeError("cell crashed")
            return original(name, raw)

        with mock.patch.object(transforms, "apply", side_effect=apply):
            with self.assertRaises(RuntimeError):
                self.run_tool()
        self.assert_no_artifacts()

    def test_cached_incomplete_summary_is_rejected(self):
        self.run_tool()
        state = cache.load_state(self.state)
        state["a.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "previous failure"}]
        cache.save_state(state, self.state)
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_cli_returns_failure_status_for_caught_transform_failure(self):
        self.run_tool()
        self.write(os.path.join(self.inp, "a.csv"), "flag\ninvalid\n")
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as exc:
                reportgen.main(["--rules", self.rules, "--input", self.inp,
                                "--output", self.out, "--cache", self.state])
        self.assertEqual(exc.exception.code, 1)
        self.assertIn("1 cell(s) failed their transform", stderr.getvalue())
        self.assert_no_artifacts()

    def test_all_html_text_fields_are_escaped(self):
        os.remove(os.path.join(self.inp, "a.csv"))
        self.write(self.rules, "[transforms]\n")
        self.write(os.path.join(self.inp, "<file>&.csv"),
                   '<column>&\n"red <b> & bold"\n')
        self.run_tool()
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as fh:
            html = fh.read()
        for raw in ("<file>", "<column>", "<b>"):
            self.assertNotIn(raw, html)
        for escaped in ("&lt;file&gt;&amp;.csv", "&lt;column&gt;&amp;",
                        "red &lt;b&gt; &amp; bold"):
            self.assertIn(escaped, html)


if __name__ == "__main__":
    unittest.main()

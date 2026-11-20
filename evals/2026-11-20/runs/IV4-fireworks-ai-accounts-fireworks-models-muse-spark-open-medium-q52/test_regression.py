"""Regression tests for defects fixed in this release."""
import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


class BooleanTransformTests(unittest.TestCase):
    def test_boolean_values(self):
        self.assertEqual(transforms.apply("boolean", "yes"), 1.0)
        self.assertEqual(transforms.apply("boolean", "YES"), 1.0)
        self.assertEqual(transforms.apply("boolean", "True"), 1.0)
        self.assertEqual(transforms.apply("boolean", "true"), 1.0)
        self.assertEqual(transforms.apply("boolean", "no"), 0.0)
        self.assertEqual(transforms.apply("boolean", "NO"), 0.0)
        self.assertEqual(transforms.apply("boolean", "False"), 0.0)
        self.assertEqual(transforms.apply("boolean", "false"), 0.0)
        # whitespace tolerant
        self.assertEqual(transforms.apply("boolean", "  yes  "), 1.0)

    def test_boolean_invalid_raises(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("boolean", "maybe")
        with self.assertRaises(transforms.TransformError):
            transforms.apply("boolean", "")

    def test_boolean_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg-reg-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("flag\nYes\nno\nTRUE\nfalse\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)


class CacheHygieneTests(unittest.TestCase):
    def test_future_version_treated_as_empty(self):
        tmp = tempfile.mkdtemp(prefix="rg-reg-cache-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache_path = os.path.join(tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(cache_path))
        # Simulate future schema version
        with open(cache_path, "w") as fh:
            json.dump({"version": "99", "some": {"digest": "x"}}, fh)
        # Should not crash, treated as empty
        state = cache.load_state(cache_path)
        self.assertEqual(state, {})

    def test_future_entry_registry_version_treated_as_empty(self):
        tmp = tempfile.mkdtemp(prefix="rg-reg-cache2-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache_path = os.path.join(tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(cache_path))
        with open(cache_path, "w") as fh:
            json.dump({"a.csv": {"digest": "x", "registry_version": "99"}}, fh)
        state = cache.load_state(cache_path)
        self.assertEqual(state, {})

    def test_future_cache_does_not_crash_run(self):
        tmp = tempfile.mkdtemp(prefix="rg-reg-cache-run-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("x\n1\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nx = "trim"\n')
        cache_path = os.path.join(tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(cache_path))
        with open(cache_path, "w") as fh:
            json.dump({"version": "999"}, fh)
        out = os.path.join(tmp, "out")
        # Must not crash, must do full run and rewrite valid state
        report = reportgen.run(rules_path, inp, out, cache_path)
        self.assertIsNotNone(report)
        state = cache.load_state(cache_path)
        self.assertIn("t.csv", state)


class FailureAtomicityTests(unittest.TestCase):
    def test_failed_run_leaves_previous_report_and_cache_intact(self):
        tmp = tempfile.mkdtemp(prefix="rg-reg-atomic-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "good.csv"), "w") as fh:
            fh.write("amount\n$1.00\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\namount = "currency_amount"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        # First successful run
        reportgen.run(rules_path, inp, out, cache_path)
        with open(os.path.join(out, "report.json"), "rb") as fh:
            good_report = fh.read()
        with open(os.path.join(out, "report.html"), "rb") as fh:
            good_html = fh.read()
        with open(cache_path, "rb") as fh:
            good_cache = fh.read()
        # Introduce failure: bad currency
        with open(os.path.join(inp, "bad.csv"), "w") as fh:
            fh.write("amount\nnot-money\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, inp, out, cache_path)
        # Must be byte-for-byte intact
        with open(os.path.join(out, "report.json"), "rb") as fh:
            self.assertEqual(fh.read(), good_report)
        with open(os.path.join(out, "report.html"), "rb") as fh:
            self.assertEqual(fh.read(), good_html)
        with open(cache_path, "rb") as fh:
            self.assertEqual(fh.read(), good_cache)

    def test_unhandled_crash_treated_as_transform_failure(self):
        tmp = tempfile.mkdtemp(prefix="rg-reg-crash-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("flag\nyes\n")
        # Inject a crashing transform
        orig = transforms.REGISTRY.get("boolean")
        def crashing(v):
            raise RuntimeError("boom")
        transforms.REGISTRY["__crash"] = crashing
        self.addCleanup(lambda: transforms.REGISTRY.pop("__crash", None))
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "__crash"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, inp, out, cache_path)


class RulesReadOnceTests(unittest.TestCase):
    def test_rules_read_at_most_once(self):
        tmp = tempfile.mkdtemp(prefix="rg-reg-rulesonce-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        for i in range(3):
            with open(os.path.join(inp, f"f{i}.csv"), "w") as fh:
                fh.write("x\n1\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nx = "trim"\n')
        count = {"n": 0}
        orig_open = open
        def counting_open(path, *a, **kw):
            if os.path.abspath(path) == os.path.abspath(rules_path):
                count["n"] += 1
            return orig_open(path, *a, **kw)
        import builtins
        old = builtins.open
        builtins.open = counting_open
        try:
            reportgen.run(rules_path, inp, os.path.join(tmp, "out"), os.path.join(tmp, "cache", "state.json"))
        finally:
            builtins.open = old
        self.assertEqual(count["n"], 1)


class HtmlEscapingRegressionTests(unittest.TestCase):
    def test_html_escapes_content(self):
        tmp = tempfile.mkdtemp(prefix="rg-reg-html-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write('a\n<>&"\n')
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html_content = fh.read()
        self.assertNotIn('<>&"', html_content.split("<table")[1] if "<table" in html_content else html_content)
        self.assertIn("&lt;", html_content)
        self.assertIn("&gt;", html_content)
        self.assertIn("&amp;", html_content)

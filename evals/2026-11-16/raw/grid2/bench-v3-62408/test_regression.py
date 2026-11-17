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
    def test_boolean_accepts_variants(self):
        for v in ("yes", "YES", "Yes", "true", "True", "TRUE"):
            self.assertEqual(transforms.apply("boolean", v), 1.0, msg=v)
        for v in ("no", "NO", "No", "false", "False", "FALSE"):
            self.assertEqual(transforms.apply("boolean", v), 0.0, msg=v)

    def test_boolean_rejects_invalid(self):
        for v in ("maybe", "1", "0", "y", "", "tru"):
            with self.assertRaises(transforms.TransformError, msg=v):
                transforms.apply("boolean", v)

    def test_boolean_whitespace_stripped(self):
        self.assertEqual(transforms.apply("boolean", "  yes "), 1.0)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-cache-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_future_registry_version_treated_as_empty(self):
        # Write a cache state with a future version
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        path = os.path.join(inp, "a.csv")
        with open(path, "w") as fh:
            fh.write("x\n1\n")
        future_entry = cache.make_entry(path, cache.file_digest(path), 1,
                                        {"columns": {}}, {"x": "trim"}, cache.rules_fingerprint({"x": "trim"}))
        future_entry["registry_version"] = "99"
        cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as fh:
            json.dump({"a.csv": future_entry}, fh)
        # load_state should treat as empty
        state = cache.load_state(cache_path)
        self.assertEqual(state, {})

    def test_future_version_run_does_full_run_and_rewrites(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        cache_path = os.path.join(self.tmp, "cache", "state.json")
        # Pre-populate with future version
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as fh:
            json.dump({"a.csv": {"digest": "old", "rows": 1, "generated_from": 1,
                                 "rules_fp": "old", "registry_version": "99",
                                 "summary": {"columns": {}, "skipped_rows": []}}}, fh)
        out = os.path.join(self.tmp, "out")
        report = reportgen.run(rules_path, inp, out, cache_path)
        self.assertIsNotNone(report)
        state = cache.load_state(cache_path)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)


class AtomicityTests(unittest.TestCase):
    """Invariant: no run may end with report or cache entry from incomplete pass."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-atomic-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_skipped_rows_leaves_no_report_no_cache(self):
        # One file will fail transform
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item,label\ngood,ok\n")
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("amount,notes\nnot_currency,hi\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\namount = "currency_amount"\nitem = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unhandled_crash_leaves_no_report_no_cache(self):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item\n1\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        # Monkey-patch a transform to crash with TypeError
        orig = transforms.REGISTRY["round2"]
        def crashing(v):
            raise RuntimeError("boom")
        transforms.REGISTRY["round2"] = crashing
        try:
            with self.assertRaises(Exception):
                reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        finally:
            transforms.REGISTRY["round2"] = orig
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_html_escaping_regression(self):
        with open(os.path.join(self.inp, "labels.csv"), "w") as fh:
            fh.write("item,label\ni1,red <b> & bold\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "trim"\n')
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html")) as fh:
            html_content = fh.read()
        self.assertNotIn("<b>", html_content)
        self.assertIn("red &lt;b&gt; &amp; bold", html_content)


if __name__ == "__main__":
    unittest.main()

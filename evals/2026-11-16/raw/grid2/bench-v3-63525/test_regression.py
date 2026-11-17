"""Regression tests for defects fixed in boolean/cache release."""
import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


class BooleanTransformRegression(unittest.TestCase):
    def test_affirmative_and_negative(self):
        for v in ["yes", "YES", "Yes", "true", "TRUE", "True"]:
            self.assertEqual(transforms.apply("boolean", v), 1.0)
        for v in ["no", "NO", "false", "FALSE"]:
            self.assertEqual(transforms.apply("boolean", v), 0.0)

    def test_invalid_raises(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("boolean", "maybe")
        with self.assertRaises(transforms.TransformError):
            transforms.apply("boolean", "")


class CacheFutureVersionRegression(unittest.TestCase):
    def test_future_version_treated_as_empty(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as f:
            f.write("item,val\n1,yes\n")
        rules = os.path.join(tmp, "rules.toml")
        with open(rules, "w") as f:
            f.write('[transforms]\nval = "boolean"\n')
        cpath = os.path.join(tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(cpath))
        with open(cpath, "w") as f:
            json.dump({"a.csv": {"digest": "old", "rows": 99, "generated_from": 1,
                                 "rules_fp": "old", "registry_version": "99",
                                 "summary": {"columns": {}}}}, f)
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules, inp, out, cpath)
        self.assertEqual(report["files"]["a.csv"]["rows"], 1)
        state = cache.load_state(cpath)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)


class InvariantRegression(unittest.TestCase):
    """No report/cache on transform failure, including unhandled crashes."""

    def test_failed_transform_leaves_no_report_or_cache(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as f:
            f.write("item,val\n1,ok\n")
        with open(os.path.join(inp, "b.csv"), "w") as f:
            f.write("item,val\n1,maybe\n")
        rules = os.path.join(tmp, "rules.toml")
        with open(rules, "w") as f:
            f.write('[transforms]\nval = "boolean"\n')
        out = os.path.join(tmp, "out")
        cpath = os.path.join(tmp, "cache", "state.json")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules, inp, out, cpath)
        self.assertFalse(os.path.exists(os.path.join(out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(out, "report.html")))
        self.assertFalse(os.path.exists(cpath))

    def test_unhandled_crash_treated_as_transform_failure(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        def crash(v):
            raise TypeError("boom")

        transforms.REGISTRY["crash_test"] = crash
        self.addCleanup(lambda: transforms.REGISTRY.pop("crash_test", None))
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as f:
            f.write("item,val\n1,x\n")
        rules = os.path.join(tmp, "rules.toml")
        with open(rules, "w") as f:
            f.write('[transforms]\nval = "crash_test"\n')
        out = os.path.join(tmp, "out")
        cpath = os.path.join(tmp, "cache", "state.json")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules, inp, out, cpath)
        self.assertFalse(os.path.exists(os.path.join(out, "report.json")))
        self.assertFalse(os.path.exists(cpath))


class HtmlEscapeRegression(unittest.TestCase):
    def test_sample_escaping(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "labels.csv"), "w") as f:
            f.write("item,label\ni1,red <b> & bold\n")
        rules = os.path.join(tmp, "rules.toml")
        with open(rules, "w") as f:
            f.write('[transforms]\nitem = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertIn("red &lt;b&gt; &amp; bold", html)


if __name__ == "__main__":
    unittest.main()

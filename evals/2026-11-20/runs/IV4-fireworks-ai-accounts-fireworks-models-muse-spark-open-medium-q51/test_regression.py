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
    def test_boolean_affirmative(self):
        for v in ["yes", "YES", "Yes", "true", "TRUE", "True", "  yes  ", " True "]:
            self.assertEqual(transforms.apply("boolean", v), 1.0)

    def test_boolean_negative(self):
        for v in ["no", "NO", "No", "false", "FALSE", "False", "  no  "]:
            self.assertEqual(transforms.apply("boolean", v), 0.0)

    def test_boolean_invalid_raises(self):
        for v in ["maybe", "1", "0", "y", "n", "", "yesno"]:
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", v)


class FutureCacheTests(unittest.TestCase):
    def test_future_version_treated_as_empty(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-future-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cpath = os.path.join(tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(cpath))
        future = {"a.csv": {"digest": "abc", "rows": 1, "generated_from": 1,
                            "rules_fp": "x", "registry_version": "99",
                            "summary": {"columns": {}}}}
        with open(cpath, "w") as f:
            json.dump(future, f)
        # Should not crash — returns empty
        self.assertEqual(cache.load_state(cpath), {})
        # Full run should succeed and rewrite valid state
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as f:
            f.write("item,label\n1,alpha\n")
        rules = os.path.join(tmp, "rules.toml")
        with open(rules, "w") as f:
            f.write('[transforms]\nitem = "round2"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules, inp, out, cpath)
        self.assertEqual(report["total_rows"], 1)
        state = cache.load_state(cpath)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)


class RulesReadOnceTests(unittest.TestCase):
    def test_rules_read_at_most_once(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-rules-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        for name in ["a.csv", "b.csv", "c.csv"]:
            with open(os.path.join(inp, name), "w") as f:
                f.write("x,y\n1,2\n")
        rules = os.path.join(tmp, "rules.toml")
        with open(rules, "w") as f:
            f.write('[transforms]\nx = "trim"\n')
        orig = reportgen.load_rules
        calls = [0]

        def counting(path):
            if path == rules:
                calls[0] += 1
            return orig(path)
        reportgen.load_rules = counting
        self.addCleanup(lambda: setattr(reportgen, "load_rules", orig))
        out = os.path.join(tmp, "out")
        cpath = os.path.join(tmp, "cache", "state.json")
        reportgen.run(rules, inp, out, cpath)
        self.assertEqual(calls[0], 1)


class AtomicityTests(unittest.TestCase):
    def test_failed_run_leaves_reports_intact(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-atomic-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as f:
            f.write("item,label\n1,alpha\n2,beta\n")
        rules = os.path.join(tmp, "rules.toml")
        with open(rules, "w") as f:
            f.write('[transforms]\nitem = "round2"\n')
        out = os.path.join(tmp, "out")
        cpath = os.path.join(tmp, "cache", "state.json")
        reportgen.run(rules, inp, out, cpath)
        with open(os.path.join(out, "report.json"), "rb") as f:
            good_json = f.read()
        with open(os.path.join(out, "report.html"), "rb") as f:
            good_html = f.read()
        with open(cpath, "rb") as f:
            good_cache = f.read()
        # Make next run fail
        with open(os.path.join(inp, "a.csv"), "w") as f:
            f.write("item,label\n1,alpha\nnot_a_number,beta\n")
        try:
            reportgen.run(rules, inp, out, cpath)
            self.fail("should have raised ValidationError")
        except reportgen.ValidationError:
            pass
        with open(os.path.join(out, "report.json"), "rb") as f:
            self.assertEqual(f.read(), good_json)
        with open(os.path.join(out, "report.html"), "rb") as f:
            self.assertEqual(f.read(), good_html)
        with open(cpath, "rb") as f:
            self.assertEqual(f.read(), good_cache)

    def test_main_exits_1_on_failure(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-exit-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as f:
            f.write("item,label\nnot_a_number,alpha\n")
        rules = os.path.join(tmp, "rules.toml")
        with open(rules, "w") as f:
            f.write('[transforms]\nitem = "round2"\n')
        out = os.path.join(tmp, "out")
        cpath = os.path.join(tmp, "cache", "state.json")
        with self.assertRaises(SystemExit) as cm:
            reportgen.main(["--rules", rules, "--input", inp, "--output", out, "--cache", cpath])
        self.assertEqual(cm.exception.code, 1)


class HtmlEscapingTests(unittest.TestCase):
    def test_sample_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-reg-html2-")
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
            html_content = fh.read()
        self.assertNotIn("<b>", html_content)
        self.assertIn("&lt;b&gt;", html_content)
        self.assertIn("&amp;", html_content)


if __name__ == "__main__":
    unittest.main()

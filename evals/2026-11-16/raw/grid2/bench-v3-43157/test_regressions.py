"""Regression tests for the boolean transform, cache hygiene, and the
defects fixed alongside them (report emitted from an incomplete transform
pass, unescaped HTML, report and cache disagreeing on generated_from)."""

import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_forms_are_one(self):
        for value in ("yes", "YES", "Yes", " true ", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", value), 1.0)

    def test_negative_forms_are_zero(self):
        for value in ("no", "NO", "No", " false ", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_other_values_are_rejected(self):
        for value in ("maybe", "1", "0", "", "y", "yes!"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)

    def test_boolean_column_is_summarized_as_numbers(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,flag\na,yes\nb,no\nc,TRUE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.csv_path = os.path.join(self.inp, "t.csv")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)
        with open(self.csv_path, "w") as fh:
            fh.write("item,label\n1,alpha\n2,beta\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    def current_fingerprint(self):
        return cache.rules_fingerprint(reportgen.load_rules(self.rules_path))

    def stale_entry(self, registry_version):
        """A cache entry that matches the input and the rules in every
        way except its registry version."""
        return {"digest": cache.file_digest(self.csv_path),
                "rows": 99,
                "generated_from": 99,
                "rules_fp": self.current_fingerprint(),
                "registry_version": registry_version,
                "summary": {"columns": {}, "skipped_rows": []}}

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out,
                             self.cache_path)

    def test_future_registry_version_entry_is_not_reused(self):
        self.write_state({"t.csv": self.stale_entry("999")})
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = json.load(open(self.cache_path))
        self.assertEqual(state["t.csv"]["rows"], 2)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_future_registry_version_is_compared_numerically(self):
        self.write_state({"t.csv": self.stale_entry("10")})
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = json.load(open(self.cache_path))
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_older_registry_version_entry_is_not_reused(self):
        self.write_state({"t.csv": self.stale_entry("1")})
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = json.load(open(self.cache_path))
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_state_file_from_a_future_schema_does_not_crash(self):
        self.write_state({"version": "999", "t.csv": self.stale_entry("999")})
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        state = json.load(open(self.cache_path))
        self.assertNotIn("version", state)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_state_file_with_a_foreign_shape_does_not_crash(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            fh.write('[{"name": "t.csv", "registry_version": "999"}]')
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        state = json.load(open(self.cache_path))
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_corrupt_state_file_does_not_crash(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        state = json.load(open(self.cache_path))
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_malformed_entry_is_recomputed_instead_of_crashing(self):
        entry = self.stale_entry(cache.REGISTRY_VERSION)
        del entry["summary"]
        self.write_state({"t.csv": entry})
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = json.load(open(self.cache_path))
        self.assertEqual(state["t.csv"]["rows"], 2)


class IncompleteTransformTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-failed-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.csv_path = os.path.join(self.inp, "t.csv")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')

    def write_csv(self, content):
        with open(self.csv_path, "w") as fh:
            fh.write(content)

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out,
                             self.cache_path)

    def assertNothingWritten(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))

    def test_failed_transform_emits_no_report_and_no_cache(self):
        self.write_csv("item,label\n1,alpha\nn/a,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertNothingWritten()
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_transform_leaves_no_cache_entry_for_the_failed_file(self):
        self.write_csv("item,label\n1,alpha\n2,beta\n")
        self.run_tool()
        before = json.load(open(self.cache_path))
        report_before = open(os.path.join(self.out, "report.json")).read()
        self.write_csv("item,label\n1,alpha\nn/a,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        after = json.load(open(self.cache_path))
        self.assertEqual(before, after)
        report_after = open(os.path.join(self.out, "report.json")).read()
        self.assertEqual(report_before, report_after)

    def test_unexpected_transform_error_ends_the_run_the_same_way(self):
        self.write_csv("item,label\n1,alpha\n2,beta\n")

        def boom(value):
            raise RuntimeError("transform exploded")

        original = transforms.REGISTRY["round2"]
        transforms.REGISTRY["round2"] = boom
        self.addCleanup(transforms.REGISTRY.__setitem__, "round2", original)
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertNothingWritten()
        self.assertFalse(os.path.exists(self.cache_path))


class HtmlEscapingTests(unittest.TestCase):
    def test_column_names_and_samples_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-escape-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("a<b,label\n1,\"x <i> & y\"\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<i>", html)
        self.assertIn("x &lt;i&gt; &amp; y", html)
        self.assertIn("a&lt;b", html)


class GeneratedFromTests(unittest.TestCase):
    def test_cached_run_reports_the_same_generated_from(self):
        tmp = tempfile.mkdtemp(prefix="rg3-genfrom-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,flag\na,yes\nb,no\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        first = reportgen.run(rules_path, inp, out, cache_path)
        second = reportgen.run(rules_path, inp, out, cache_path)
        self.assertEqual(first, second)
        state = json.load(open(cache_path))
        self.assertEqual(state["t.csv"]["generated_from"],
                         first["files"]["t.csv"]["generated_from"])


if __name__ == "__main__":
    unittest.main()

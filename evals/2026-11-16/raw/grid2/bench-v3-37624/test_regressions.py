"""Regression tests for the defects fixed alongside the boolean transform
and cache-hygiene work."""

import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_inputs_raise(self):
        for raw in ("", "maybe", "1", "0", "y", "n"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_is_numeric_in_report(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("flag\nyes\nno\nTRUE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        col = report["files"]["t.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["numeric_sum"], 1.0)


class _TempRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")

    def write_input(self, body):
        path = os.path.join(self.inp, "t.csv")
        with open(path, "w") as fh:
            fh.write(body)
        return path

    def write_rules(self, body):
        with open(self.rules_path, "w") as fh:
            fh.write(body)

    def seed_state(self, entry):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"t.csv": entry}, fh)

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out,
                             self.cache_path)


class CacheVersionTests(_TempRepoTest):
    def _entry(self, csv_path, registry_version):
        rules = {"item": "round2"}
        return {"digest": cache.file_digest(csv_path),
                "rows": 99,
                "generated_from": 99,
                "rules_fp": cache.rules_fingerprint(rules),
                "registry_version": registry_version,
                "summary": {"columns": {}, "skipped_rows": []}}

    def test_future_version_is_treated_as_empty_and_rewritten(self):
        csv_path = self.write_input("item,label\n1,alpha\n2,beta\n")
        self.write_rules('[transforms]\nitem = "round2"\n')
        future = str(int(cache.REGISTRY_VERSION) + 1)
        self.seed_state(self._entry(csv_path, future))

        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["item"]["numeric_sum"], 3.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(str(state["t.csv"]["registry_version"]),
                         cache.REGISTRY_VERSION)

    def test_old_version_is_not_reused(self):
        csv_path = self.write_input("item,label\n1,alpha\n2,beta\n")
        self.write_rules('[transforms]\nitem = "round2"\n')
        self.seed_state(self._entry(csv_path, "1"))

        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(str(state["t.csv"]["registry_version"]),
                         cache.REGISTRY_VERSION)


class TransformFailureAtomicityTests(_TempRepoTest):
    def assert_no_outputs(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_handled_transform_error_leaves_no_report_or_cache(self):
        self.write_input("amount\n$1.00\nnot money\n")
        self.write_rules('[transforms]\namount = "currency_amount"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_outputs()

    def test_unhandled_transform_crash_leaves_no_report_or_cache(self):
        def boom(value):
            raise RuntimeError("boom")

        self.write_input("amount\n1\n2\n")
        self.write_rules('[transforms]\namount = "boom"\n')
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with self.assertRaises(RuntimeError):
            self.run_tool()
        self.assert_no_outputs()


class GeneratedFromTests(_TempRepoTest):
    def test_generated_from_is_stable_across_cached_run(self):
        self.write_input("device_id,status\nd1,\n")
        self.write_rules('[transforms]\ndevice_id = "trim"\nstatus = "upper"\n')
        first = self.run_tool()
        second = self.run_tool()
        self.assertEqual(first, second)
        self.assertEqual(first["files"]["t.csv"]["generated_from"], 1)


class HtmlEscapingTests(_TempRepoTest):
    def test_column_names_are_escaped(self):
        self.write_input("<b>item</b>,label\nx,red <b> & bold\n")
        self.write_rules('[transforms]\n')
        self.run_tool()
        with open(os.path.join(self.out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertIn("&lt;b&gt;item&lt;/b&gt;", html)
        self.assertIn("red &lt;b&gt; &amp; bold", html)


if __name__ == "__main__":
    unittest.main()

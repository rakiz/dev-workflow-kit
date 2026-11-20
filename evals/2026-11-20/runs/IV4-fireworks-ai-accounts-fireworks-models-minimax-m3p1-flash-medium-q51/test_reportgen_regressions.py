"""Regression tests for the defects fixed alongside the boolean transform
and the cache-hygiene work.

Each test below pins one defect:

* the boolean transform did not exist;
* the HTML rendering did not escape the values it wrote out;
* a failing transform still wrote report.html and a cache entry, and the
  CLI exited 0 instead of 1;
* the rules file was re-read once per input file;
* a cache state file written by a future schema version was reused (or
  crashed the run) instead of being treated as an empty cache.
"""

import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)

    def write_input(self, name, text):
        path = os.path.join(self.inp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def write_rules(self, text):
        path = os.path.join(self.tmp, "rules.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def read_bytes(self, path):
        with open(path, "rb") as fh:
            return fh.read()


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_and_negative_forms(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", value), 1.0)
        for value in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_other_values_raise_transform_error(self):
        for value in ("maybe", "1", "0", "y", "n", "", "yes please"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)

    def test_boolean_is_registered(self):
        self.assertIn("boolean", transforms.REGISTRY)


class BooleanEndToEndTests(TempDirCase):
    def test_boolean_column_is_reported_as_numbers(self):
        self.write_input("flags.csv", "id,flag\n1,yes\n2,NO\n3,true\n4,False\n")
        rules = self.write_rules('[transforms]\nflag = "boolean"\n')
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])

    def test_boolean_failure_aborts_the_run(self):
        self.write_input("flags.csv", "id,flag\n1,yes\n2,maybe\n")
        rules = self.write_rules('[transforms]\nflag = "boolean"\n')
        self.assertEqual(
            reportgen.main(["--rules", rules, "--input", self.inp,
                            "--output", self.out, "--cache", self.cache_path]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


class HtmlEscapingTests(TempDirCase):
    def test_values_do_not_leak_markup(self):
        self.write_input("labels.csv", "item,label\ni1,red <b> & bold\n")
        rules = self.write_rules('[transforms]\nitem = "trim"\n')
        reportgen.run(rules, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as fh:
            page = fh.read()
        self.assertNotIn("<b>", page)
        self.assertIn("red &lt;b&gt; &amp; bold", page)


class TransformFailureTests(TempDirCase):
    def good_setup(self):
        self.write_input("t.csv", "item,label\n1,alpha\n2,beta\n")
        self.rules = self.write_rules('[transforms]\nitem = "round2"\n')

    def test_failure_leaves_previous_outputs_and_cache_untouched(self):
        self.good_setup()
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        report_json = os.path.join(self.out, "report.json")
        report_html = os.path.join(self.out, "report.html")
        before = {path: self.read_bytes(path)
                  for path in (report_json, report_html, self.cache_path)}

        # A cell that fails its transform invalidates the whole pass.
        self.write_input("t.csv", "item,label\n1,alpha\nn/a,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)

        for path, content in before.items():
            self.assertEqual(self.read_bytes(path), content, path)

    def test_failure_writes_no_report_at_all(self):
        self.good_setup()
        self.write_input("t.csv", "item,label\n1,alpha\nn/a,beta\n")
        self.assertEqual(
            reportgen.main(["--rules", self.rules, "--input", self.inp,
                            "--output", self.out, "--cache", self.cache_path]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unexpected_transform_crash_is_a_failure_not_a_report(self):
        self.good_setup()
        self.write_input("t.csv", "item,label\n1,alpha\nn/a,beta\n")
        original = transforms.REGISTRY["round2"]

        def exploding(value):
            raise RuntimeError("boom")

        transforms.REGISTRY["round2"] = exploding
        self.addCleanup(transforms.REGISTRY.__setitem__, "round2", original)
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


class RulesReadTests(TempDirCase):
    def test_rules_file_is_read_once_per_run(self):
        for name in ("a.csv", "b.csv", "c.csv"):
            self.write_input(name, "item\n1\n")
        rules = self.write_rules('[transforms]\nitem = "round2"\n')
        original = reportgen.load_rules
        calls = []

        def counting(path):
            calls.append(path)
            return original(path)

        reportgen.load_rules = counting
        self.addCleanup(setattr, reportgen, "load_rules", original)
        reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertEqual(len(calls), 1)


class FutureCacheVersionTests(TempDirCase):
    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)

    def test_future_entry_version_is_treated_as_an_empty_cache(self):
        self.write_input("t.csv", "item,label\n1,alpha\n")
        rules = self.write_rules('[transforms]\nitem = "round2"\n')
        stale = {"digest": "0" * 64, "rows": 99, "generated_from": 7,
                 "rules_fp": "stale", "registry_version": "999",
                 "summary": {"columns": {"item": {"non_empty": 99,
                                                  "distinct": 99,
                                                  "sample": ["stale"]}},
                             "skipped_rows": []}}
        self.write_state({"t.csv": stale})

        self.assertEqual(cache.load_state(self.cache_path), {})
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        # The full run happened: the stale summary was not reused.
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["item"]["numeric_sum"], 1.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 1)

    def test_future_top_level_version_is_treated_as_an_empty_cache(self):
        self.write_input("t.csv", "item,label\n1,alpha\n")
        rules = self.write_rules('[transforms]\nitem = "round2"\n')
        self.write_state({"version": 999, "files": {"t.csv": {"rows": 42}}})
        self.assertEqual(cache.load_state(self.cache_path), {})
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_cached_summary_with_failed_cells_is_not_reused(self):
        self.write_input("t.csv", "item,label\n1,alpha\n")
        rules = self.write_rules('[transforms]\nitem = "round2"\n')
        digest = cache.file_digest(os.path.join(self.inp, "t.csv"))
        rules_fp = cache.rules_fingerprint(reportgen.load_rules(rules))
        stale = {"digest": digest, "rows": 1, "generated_from": 1,
                 "rules_fp": rules_fp, "registry_version": cache.REGISTRY_VERSION,
                 "summary": {"columns": {"item": {"non_empty": 1,
                                                  "distinct": 1,
                                                  "sample": [1.0]}},
                             "skipped_rows": [{"row": 2, "column": "item",
                                               "reason": "not a number"}]}}
        self.write_state({"t.csv": stale})
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["summary"]["skipped_rows"], [])
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["summary"]["skipped_rows"], [])

    def test_entry_written_by_another_registry_version_is_not_reused(self):
        self.write_input("t.csv", "item,label\n1,alpha\n")
        rules = self.write_rules('[transforms]\nitem = "round2"\n')
        digest = cache.file_digest(os.path.join(self.inp, "t.csv"))
        rules_fp = cache.rules_fingerprint(reportgen.load_rules(rules))
        stale = {"digest": digest, "rows": 99, "generated_from": 7,
                 "rules_fp": rules_fp, "registry_version": "1",
                 "summary": {"columns": {"item": {"non_empty": 99,
                                                  "distinct": 99,
                                                  "sample": ["stale"]}},
                             "skipped_rows": []}}
        self.write_state({"t.csv": stale})
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


if __name__ == "__main__":
    unittest.main()

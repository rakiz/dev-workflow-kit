"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
import tempfile
import unittest

import cache
import reportgen
import transforms

BASE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE, "input")
RULES = os.path.join(BASE, "rules.example.toml")


class TransformTests(unittest.TestCase):
    def test_trim_upper_lower(self):
        self.assertEqual(transforms.apply("trim", "  x "), "x")
        self.assertEqual(transforms.apply("upper", "aB"), "AB")
        self.assertEqual(transforms.apply("lower", "aB"), "ab")

    def test_currency_amount(self):
        self.assertEqual(transforms.apply("currency_amount", "$1,234.5"), 1234.5)
        with self.assertRaises(transforms.TransformError):
            transforms.apply("currency_amount", "see invoice")

    def test_round2(self):
        self.assertEqual(transforms.apply("round2", "3.14159"), 3.14)
        with self.assertRaises(transforms.TransformError):
            transforms.apply("round2", "n/a")

    def test_percent(self):
        self.assertEqual(transforms.apply("percent", "0.1837"), 18.37)
        self.assertEqual(transforms.apply("percent", " 0.25 "), 25.0)
        self.assertEqual(transforms.apply("percent", "0.12345"), 12.35)
        for bad in ("n/a", "", "18%", "nan", "inf"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("percent", bad)

    def test_date_iso(self):
        self.assertEqual(transforms.apply("date_iso", "01/15/2026"), "2026-01-15")
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "2026-01-15")

    def test_unknown_transform_name(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("nope", "x")


class RulesTests(unittest.TestCase):
    def test_rules_loader_ignores_other_tables(self):
        tmp = tempfile.mkdtemp(prefix="rg2-rules-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "rules.toml")
        with open(path, "w") as fh:
            fh.write('# rules\n[report]\ntitle = "x"\n\n[transforms]\nname = "upper"\n')
        self.assertEqual(reportgen.load_rules(path), {"name": "upper"})

    def test_shipped_rules_load(self):
        rules = reportgen.load_rules(RULES)
        self.assertEqual(rules["amount"], "currency_amount")
        self.assertEqual(rules["date"], "date_iso")
        self.assertNotIn("merchant", rules)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg2-e2e-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self, rules=RULES, input_dir=INPUT_DIR):
        return reportgen.run(rules, input_dir, self.out, self.cache_path)

    def test_shipped_inputs_report(self):
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12013)
        self.assertEqual(set(report["files"]), {
            "big_transactions.csv", "multiline_notes.csv",
            "small_employees.csv", "small_transactions.csv"})
        tx = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(tx["merchant"]["distinct"], 4)
        self.assertEqual(tx["amount"]["numeric_sum"], 975.84)
        emp = report["files"]["small_employees.csv"]["summary"]["columns"]
        self.assertEqual(emp["salary"]["numeric_sum"], 432000.0)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.html")))

    def test_temp_input_end_to_end(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\n2,beta\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        report = self.run_tool(rules=rules_path, input_dir=inp)
        self.assertEqual(report["total_rows"], 2)
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["item"]["numeric_sum"], 3.0)
        self.assertEqual(cols["label"]["sample"], ["alpha", "beta"])


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg2-cache-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

    def test_first_run_creates_missing_cache_dir(self):
        self.assertFalse(os.path.exists(os.path.dirname(self.cache_path)))
        self.run_tool()
        self.assertTrue(os.path.exists(self.cache_path))

    def test_cache_state_written_on_first_run(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {
            "big_transactions.csv", "multiline_notes.csv",
            "small_employees.csv", "small_transactions.csv"})
        digest = cache.file_digest(
            os.path.join(INPUT_DIR, "small_transactions.csv"))
        self.assertEqual(state["small_transactions.csv"]["digest"], digest)

    def test_state_file_stable_across_runs(self):
        self.run_tool()
        before = json.load(open(self.cache_path))
        self.run_tool()
        after = json.load(open(self.cache_path))
        self.assertEqual(before, after)


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg2-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)

    def write(self, name, text, base=None):
        with open(os.path.join(base or self.inp, name), "w") as fh:
            fh.write(text)

    def run_tool(self, rules):
        return reportgen.run(rules, self.inp, self.out, self.cache_path)

    def test_percent_end_to_end_and_bad_cell_skipped(self):
        self.write("p.csv", "share\n0.1837\noops\n")
        rules = os.path.join(self.tmp, "r.toml")
        self.write("r.toml", '[transforms]\nshare = "percent"\n', self.tmp)
        rep = self.run_tool(rules)
        col = rep["files"]["p.csv"]["summary"]["columns"]["share"]
        self.assertEqual(col["numeric_sum"], 18.37)
        self.assertEqual(len(rep["files"]["p.csv"]["summary"]["skipped_rows"]), 1)

    def test_corrupt_cache_is_treated_as_empty(self):
        for junk in ('{"a": ', "", "[1, 2]", '{"x.csv": 5}', "\xff\xfe"):
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "wb") as fh:
                fh.write(junk.encode("latin-1"))
            rep = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
            self.assertEqual(rep["total_rows"], 12013)
            with open(self.cache_path) as fh:
                state = json.load(fh)
            self.assertEqual(len(state), 4)

    def test_edited_rules_invalidate_cache(self):
        self.write("t.csv", "v\n 1.234 \n")
        rules = os.path.join(self.tmp, "r.toml")
        self.write("r.toml", '[transforms]\nv = "trim"\n', self.tmp)
        self.run_tool(rules)
        self.write("r.toml", '[transforms]\nv = "round2"\n', self.tmp)
        rep = self.run_tool(rules)
        col = rep["files"]["t.csv"]["summary"]["columns"]["v"]
        self.assertEqual(col["numeric_sum"], 1.23)

    def test_cached_run_reports_same_rows_as_fresh_run(self):
        first = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        second = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(first["total_rows"], second["total_rows"])
        self.assertEqual(second["total_rows"], 12013)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["multiline_notes.csv"]["rows"],
                         first["files"]["multiline_notes.csv"]["rows"])

    def test_failure_midrun_leaves_cache_untouched(self):
        self.write("a.csv", "v\n1\n")
        self.write("b.csv", "v\n2\n")
        rules = os.path.join(self.tmp, "r.toml")
        self.write("r.toml", '[transforms]\nv = "trim"\n', self.tmp)
        orig = reportgen.summarize_file
        calls = []

        def boom(header, rows, rules_):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return orig(header, rows, rules_)
        reportgen.summarize_file = boom
        self.addCleanup(setattr, reportgen, "summarize_file", orig)
        with self.assertRaises(RuntimeError):
            self.run_tool(rules)
        self.assertFalse(os.path.exists(self.cache_path))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


if __name__ == "__main__":
    unittest.main()

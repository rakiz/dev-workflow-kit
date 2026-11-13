"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

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


class PercentTransformTests(unittest.TestCase):
    def test_percent(self):
        self.assertEqual(transforms.apply("percent", "0.1837"), 18.37)
        self.assertEqual(transforms.apply("percent", " 0.5 "), 50.0)
        self.assertEqual(transforms.apply("percent", "0.12345"), 12.35)
        self.assertEqual(transforms.apply("percent", "0.07"), 7.0)

    def test_percent_rejects_non_numeric(self):
        for bad in ("abc", "", "n/a", "nan", "inf", "1e999999999"):
            with self.assertRaises(transforms.TransformError, msg=bad):
                transforms.apply("percent", bad)


class HygieneBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg2-hyg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        self.write_rules('[transforms]\nshare = "percent"\n')

    def write_rules(self, text):
        with open(self.rules, "w") as fh:
            fh.write(text)

    def write_csv(self, name, text):
        with open(os.path.join(self.inp, name), "w", newline="") as fh:
            fh.write(text)

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def assert_nothing_written(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class PercentEndToEndTests(HygieneBase):
    def test_percent_column_reported(self):
        self.write_csv("a.csv", "id,share\n1,0.1837\n2,0.5\n")
        cols = self.run_tool()["files"]["a.csv"]["summary"]["columns"]
        self.assertEqual(cols["share"]["numeric_sum"], 68.37)


class CorruptCacheTests(HygieneBase):
    def test_corrupt_cache_is_treated_as_empty_and_rewritten(self):
        self.write_csv("a.csv", "id,share\n1,0.25\n")
        for junk in ('{"a.csv": {"digest": "x"', "", "[1, 2]", "\xff\xfe"):
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "wb") as fh:
                fh.write(junk.encode("latin-1"))
            report = self.run_tool()
            self.assertEqual(report["total_rows"], 1)
            with open(self.cache_path, encoding="utf-8") as fh:
                state = json.load(fh)
            self.assertEqual(
                state["a.csv"]["digest"],
                cache.file_digest(os.path.join(self.inp, "a.csv")))

    def test_corrupt_cache_with_no_inputs_still_rewritten(self):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            fh.write("{trunc")
        self.run_tool()
        with open(self.cache_path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {})


class FailedTransformTests(HygieneBase):
    def test_failed_cell_emits_no_report_and_no_cache(self):
        self.write_csv("a.csv", "id,share\n1,0.25\n")
        self.write_csv("b.csv", "id,share\n1,0.25\n2,oops\n")
        with self.assertRaises(transforms.TransformError):
            self.run_tool()
        self.assert_nothing_written()

    def test_unhandled_crash_emits_no_report_and_no_cache(self):
        self.write_csv("a.csv", "id,share\n1,0.25\n")
        self.write_csv("b.csv", "id,share\n1,0.25\n")
        calls = []

        def boom(value):
            calls.append(value)
            if len(calls) == 2:
                raise RuntimeError("crash")
            return 1.0
        with mock.patch.dict(transforms.REGISTRY, {"percent": boom}):
            with self.assertRaises(RuntimeError):
                self.run_tool()
        self.assert_nothing_written()

    def test_failed_run_leaves_existing_cache_untouched(self):
        self.write_csv("a.csv", "id,share\n1,0.25\n")
        self.run_tool()
        with open(self.cache_path) as fh:
            before = fh.read()
        self.write_csv("b.csv", "id,share\n1,bad\n")
        with self.assertRaises(transforms.TransformError):
            self.run_tool()
        with open(self.cache_path) as fh:
            self.assertEqual(fh.read(), before)

    def test_legacy_cache_entry_with_skipped_rows_not_reused(self):
        self.write_csv("a.csv", "id,share\n1,bad\n")
        path = os.path.join(self.inp, "a.csv")
        os.makedirs(os.path.dirname(self.cache_path))
        entry = cache.make_entry(
            path, cache.file_digest(path),
            {"columns": {}, "skipped_rows": [{"row": 2, "column": "share",
                                              "reason": "x"}]},
            cache.rules_fingerprint(reportgen.load_rules(self.rules)), rows=1)
        cache.save_state({"a.csv": entry}, path=self.cache_path)
        with self.assertRaises(transforms.TransformError):
            self.run_tool()
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


class CacheCorrectnessTests(HygieneBase):
    def test_rules_change_invalidates_cached_entry(self):
        self.write_csv("a.csv", "id,share\n1,0.25\n")
        first = self.run_tool()["files"]["a.csv"]["summary"]["columns"]
        self.assertEqual(first["share"]["numeric_sum"], 25.0)
        self.write_rules('[transforms]\nshare = "round2"\n')
        second = self.run_tool()["files"]["a.csv"]["summary"]["columns"]
        self.assertEqual(second["share"]["numeric_sum"], 0.25)

    def test_total_rows_identical_on_cached_run(self):
        self.write_csv("a.csv", 'id,note\n1,"x\ny"\n\n2,z\n')
        first = self.run_tool()
        second = self.run_tool()
        self.assertEqual(first["total_rows"], 2)
        self.assertEqual(second["total_rows"], 2)


class HtmlEscapeTests(HygieneBase):
    def test_file_and_column_names_escaped(self):
        self.write_csv("a&b.csv", "<i>col,x\n1,2\n")
        self.run_tool()
        with open(os.path.join(self.out, "report.html")) as fh:
            page = fh.read()
        self.assertNotIn("<i>", page)
        self.assertIn("&lt;i&gt;col", page)
        self.assertIn("a&amp;b.csv", page)


if __name__ == "__main__":
    unittest.main()

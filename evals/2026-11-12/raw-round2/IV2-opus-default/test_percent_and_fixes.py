"""Tests for the percent transform, cache hygiene, and regression tests
for fixed defects."""

import contextlib
import io
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


class PercentTransformTests(unittest.TestCase):
    def test_fraction_to_percentage(self):
        self.assertEqual(transforms.apply("percent", "0.1837"), 18.37)
        self.assertEqual(transforms.apply("percent", " 0.25 "), 25.0)
        self.assertEqual(transforms.apply("percent", "1"), 100.0)
        self.assertEqual(transforms.apply("percent", "-0.005"), -0.5)

    def test_rounds_to_two_decimals_without_binary_error(self):
        self.assertEqual(transforms.apply("percent", "0.123456"), 12.35)
        # 0.0703 * 100 in binary float is 7.030000000000001
        self.assertEqual(transforms.apply("percent", "0.0703"), 7.03)
        self.assertIsInstance(transforms.apply("percent", "0.5"), float)

    def test_non_numeric_raises(self):
        for bad in ("n/a", "", "18%", "nan", "inf"):
            with self.assertRaises(transforms.TransformError, msg=bad):
                transforms.apply("percent", bad)


class _RunBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg2-fix-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_tool(self, rules, input_dir=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return reportgen.run(rules, input_dir or self.inp, self.out,
                                 self.cache_path)

    def assert_nothing_written(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class PercentEndToEndTests(_RunBase):
    def test_percent_column_in_report(self):
        self.write("in/s.csv", "id,share\na,0.25\nb,0.1837\n")
        rules = self.write("rules.toml", '[transforms]\nshare = "percent"\n')
        report = self.run_tool(rules)
        col = report["files"]["s.csv"]["summary"]["columns"]["share"]
        self.assertEqual(col["sample"], [18.37, 25.0])
        self.assertEqual(col["numeric_sum"], 43.37)


class CorruptCacheTests(_RunBase):
    def test_corrupt_state_is_treated_as_empty_and_rewritten(self):
        for junk in ('{"big_transactions.csv": {"dig', "", "[1, 2]", "\xff"):
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="latin-1") as fh:
                fh.write(junk)
            report = self.run_tool(RULES, INPUT_DIR)
            self.assertEqual(report["total_rows"], 12013)
            with open(self.cache_path, encoding="utf-8") as fh:
                state = json.load(fh)
            self.assertEqual(set(state), set(report["files"]))


class TransformFailureInvariantTests(_RunBase):
    """Regression: a caught TransformError used to be skipped and the run
    carried on, emitting a report and caching the partial summary; cache
    entries were also saved per file before later files were processed."""

    def test_caught_transform_error_fails_run_without_output(self):
        self.write("in/a.csv", "amount\n$1.00\n")
        self.write("in/b.csv", "amount\n$2.00\nsee invoice\n")
        rules = self.write("rules.toml", '[transforms]\namount = "currency_amount"\n')
        with self.assertRaises(transforms.TransformError):
            self.run_tool(rules)
        self.assert_nothing_written()

    def test_unhandled_crash_in_later_file_leaves_no_cache(self):
        self.write("in/a.csv", "x\n1\n")
        self.write("in/b.csv", "x\nboom\n")
        rules = self.write("rules.toml", '[transforms]\nx = "trim"\n')
        real = transforms.REGISTRY["trim"]

        def flaky(value):
            if value == "boom":
                raise RuntimeError("crash")
            return real(value)

        with mock.patch.dict(transforms.REGISTRY, {"trim": flaky}):
            with self.assertRaises(RuntimeError):
                self.run_tool(rules)
        self.assert_nothing_written()

    def test_main_exits_nonzero_on_transform_failure(self):
        self.write("in/a.csv", "amount\nnope\n")
        rules = self.write("rules.toml", '[transforms]\namount = "round2"\n')
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stdout(io.StringIO()):
                reportgen.main(["--rules", rules, "--input", self.inp,
                                "--output", self.out, "--cache", self.cache_path])
        self.assertIn("failed their transform", str(cm.exception.code))
        self.assert_nothing_written()

    def test_cached_partial_summary_is_not_reused(self):
        self.write("in/a.csv", "amount\nnope\n")
        rules = self.write("rules.toml", '[transforms]\namount = "round2"\n')
        path = os.path.join(self.inp, "a.csv")
        rules_fp = cache.rules_fingerprint(reportgen.load_rules(rules))
        partial = {"columns": {}, "skipped_rows": [
            {"row": 2, "column": "amount", "reason": "x"}]}
        cache.save_state({"a.csv": cache.make_entry(
            path, cache.file_digest(path), partial, rules_fp, 1)},
            path=self.cache_path)
        with self.assertRaises(transforms.TransformError):
            self.run_tool(rules)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


class CachedRowCountTests(_RunBase):
    """Regression: cache entries stored the physical line count, so a
    cached run reported 12019 rows instead of 12013."""

    def test_cached_run_reports_same_row_counts(self):
        first = self.run_tool(RULES, INPUT_DIR)
        second = self.run_tool(RULES, INPUT_DIR)
        self.assertEqual(second["total_rows"], first["total_rows"])
        self.assertEqual(second, first)


class RulesChangeInvalidatesCacheTests(_RunBase):
    """Regression: the stored rules fingerprint was never compared, so an
    edited rules file served stale summaries."""

    def test_edited_rules_are_applied(self):
        self.write("in/t.csv", "label\nab\nAB\n")
        rules = self.write("rules.toml", '[transforms]\nlabel = "trim"\n')
        self.assertEqual(self.run_tool(rules)["files"]["t.csv"]["summary"]
                         ["columns"]["label"]["distinct"], 2)
        self.write("rules.toml", '[transforms]\nlabel = "upper"\n')
        cols = self.run_tool(rules)["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["label"]["distinct"], 1)
        self.assertEqual(cols["label"]["sample"], ["AB"])


class HtmlEscapeTests(_RunBase):
    """Regression: cell values, column and file names were interpolated
    into report.html unescaped."""

    def test_markup_is_escaped(self):
        self.write("in/x.csv", "<i>col</i>\n<script>&\n")
        rules = self.write("rules.toml", "[transforms]\n")
        self.run_tool(rules)
        with open(os.path.join(self.out, "report.html")) as fh:
            page = fh.read()
        self.assertNotIn("<script>", page)
        self.assertNotIn("<i>", page)
        self.assertIn("&lt;script&gt;&amp;", page)
        self.assertIn("&lt;i&gt;col&lt;/i&gt;", page)


if __name__ == "__main__":
    unittest.main()

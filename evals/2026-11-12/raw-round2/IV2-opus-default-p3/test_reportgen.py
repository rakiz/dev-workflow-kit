"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
import subprocess
import sys
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
        tmp = tempfile.mkdtemp(prefix="rg3-rules-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "rules.toml")
        with open(path, "w") as fh:
            fh.write('# rules\n[report]\ntitle = "x"\n\n[transforms]\nname = "upper"\n')
        self.assertEqual(reportgen.load_rules(path), {"name": "upper"})

    def test_shipped_rules_load(self):
        rules = reportgen.load_rules(RULES)
        self.assertEqual(rules["amount"], "currency_amount")
        self.assertEqual(rules["date"], "date_iso")
        self.assertNotIn("notes", rules)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-e2e-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self, rules=RULES, input_dir=INPUT_DIR):
        return reportgen.run(rules, input_dir, self.out, self.cache_path)

    def test_shipped_inputs_report(self):
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        self.assertEqual(set(report["files"]), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        tx = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(tx["merchant"]["distinct"], 3)
        self.assertEqual(tx["amount"]["numeric_sum"], 275.59)
        emp = report["files"]["small_employees.csv"]["summary"]["columns"]
        self.assertEqual(emp["salary"]["numeric_sum"], 430000.0)
        dev = report["files"]["small_devices.csv"]["summary"]["columns"]
        self.assertEqual(dev["device_id"]["distinct"], 3)
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
        self.tmp = tempfile.mkdtemp(prefix="rg3-cache-")
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
            "big_transactions.csv", "small_devices.csv",
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



def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class BooleanTransformTests(unittest.TestCase):
    def test_accepted_forms(self):
        for raw in ("yes", "YES", "True", "tRuE", " yes "):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_rejected_forms(self):
        for raw in ("", "y", "n", "1", "0", "on", "yess", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_end_to_end_counts_affirmatives(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        _write(os.path.join(tmp, "in", "f.csv"),
               "id,active\na,yes\nb,TRUE\nc,no\nd,Yes\n")
        _write(os.path.join(tmp, "rules.toml"), '[transforms]\nactive = "boolean"\n')
        report = reportgen.run(os.path.join(tmp, "rules.toml"),
                               os.path.join(tmp, "in"), os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        col = report["files"]["f.csv"]["summary"]["columns"]["active"]
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["numeric_sum"], 3.0)


class FailedTransformLeavesNothingTests(unittest.TestCase):
    """Regression: the HTML report and per-file cache entries used to be
    written before validation, so a failed transform pass still left a
    report.html and cache state behind; a non-TransformError crash left the
    cache entries of the files processed before it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        _write(self.rules, '[transforms]\nqty = "round2"\n')
        # a.csv is fine and sorts first; b.csv fails.
        _write(os.path.join(self.inp, "a.csv"), "qty\n1\n2\n")

    def assert_nothing_left(self):
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_raised_transform_error(self):
        _write(os.path.join(self.inp, "b.csv"), "qty\n3\nn/a\n")
        self.assert_nothing_left()

    def test_unhandled_crash_in_transform(self):
        def boom(value):
            if value == "3":
                raise RuntimeError("boom")
            return float(value)
        _write(os.path.join(self.inp, "b.csv"), "qty\n1\n3\n")
        with mock.patch.dict(transforms.REGISTRY, {"round2": boom}):
            self.assert_nothing_left()

    def test_failure_with_existing_cache_does_not_touch_it(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            before = fh.read()
        shutil.rmtree(self.out)
        _write(os.path.join(self.inp, "b.csv"), "qty\nbad\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(self.out))
        with open(self.cache_path) as fh:
            self.assertEqual(fh.read(), before)

    def test_cli_exits_nonzero_on_failed_transform(self):
        """Regression: the CLI printed a warning and exited 0."""
        _write(os.path.join(self.inp, "b.csv"), "qty\nbad\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


class CacheVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-ver-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

    def assert_valid_current_state(self):
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_future_top_level_version_is_ignored_and_rewritten(self):
        _write(self.cache_path, json.dumps(
            {"version": 99, "files": {"small_devices.csv": {"x": 1}}}))
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        self.assert_valid_current_state()

    def test_future_entry_version_is_ignored_and_rewritten(self):
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        # Future schema: same digest/rules_fp but a summary shape this code
        # cannot read, plus an entry for a file not in this run.
        for entry in state.values():
            entry["registry_version"] = "10"   # "10" < "3" as strings
            entry["summary"] = {"v10": True}
        state["gone.csv"] = {"registry_version": "10"}
        _write(self.cache_path, json.dumps(state))
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        self.assert_valid_current_state()

    def test_older_registry_entry_is_not_reused(self):
        """Regression: registry_version was stamped but never compared."""
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["small_employees.csv"]["registry_version"] = "1"
        state["small_employees.csv"]["summary"]["columns"]["salary"]["numeric_sum"] = -1
        _write(self.cache_path, json.dumps(state))
        report = self.run_tool()
        emp = report["files"]["small_employees.csv"]["summary"]["columns"]
        self.assertEqual(emp["salary"]["numeric_sum"], 430000.0)

    def test_cached_report_equals_fresh_report(self):
        """Regression: generated_from from a cache hit counted mapped header
        columns, a fresh run counted mapped non-empty columns."""
        fresh = self.run_tool()
        cached = self.run_tool()
        self.assertEqual(fresh, cached)
        self.assertEqual(
            cached["files"]["small_devices.csv"]["generated_from"], 1)


class SummaryDefectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-sum-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_on(self, files, rules):
        inp = os.path.join(self.tmp, "in")
        for name, text in files.items():
            _write(os.path.join(inp, name), text)
        _write(os.path.join(self.tmp, "rules.toml"), rules)
        return reportgen.run(os.path.join(self.tmp, "rules.toml"), inp,
                             os.path.join(self.tmp, "out"),
                             os.path.join(self.tmp, "cache", "state.json"))

    def test_numeric_sum_counts_duplicate_values(self):
        """Regression: numeric_sum summed distinct values only."""
        report = self.run_on({"d.csv": "n\n5\n5\n2\n"},
                             '[transforms]\nn = "round2"\n')
        col = report["files"]["d.csv"]["summary"]["columns"]["n"]
        self.assertEqual(col["numeric_sum"], 12.0)
        self.assertEqual(col["distinct"], 2)

    def test_html_escapes_names_columns_and_samples(self):
        """Regression: HTML report interpolated raw values."""
        self.run_on({"x<i>.csv": "<c>,v\n1,a&b <s>\n"},
                    '[transforms]\nv = "trim"\n')
        with open(os.path.join(self.tmp, "out", "report.html")) as fh:
            page = fh.read()
        for raw in ("<i>", "<c>", "<s>", "a&b"):
            self.assertNotIn(raw, page)
        self.assertIn("a&amp;b &lt;s&gt;", page)

    def test_empty_csv_does_not_crash(self):
        """Regression: a zero-byte CSV raised StopIteration."""
        report = self.run_on({"e.csv": ""}, '[transforms]\nv = "trim"\n')
        self.assertEqual(report["files"]["e.csv"]["rows"], 0)

    def test_date_iso_rejects_impossible_dates(self):
        """Regression: 13/45/2026 became '2026-13-45'; a non-ASCII digit
        crashed with ValueError instead of TransformError."""
        for raw in ("13/45/2026", "02/30/2026", "\u00b2/01/2026"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("date_iso", raw)
        self.assertEqual(transforms.apply("date_iso", "2/9/2026"), "2026-02-09")

    def test_numeric_transforms_reject_non_finite(self):
        """Regression: 'nan'/'inf' were accepted and produced invalid JSON."""
        for name in ("round2", "currency_amount"):
            for raw in ("nan", "inf", "-Infinity", "1e400"):
                with self.assertRaises(transforms.TransformError):
                    transforms.apply(name, raw)


if __name__ == "__main__":
    unittest.main()

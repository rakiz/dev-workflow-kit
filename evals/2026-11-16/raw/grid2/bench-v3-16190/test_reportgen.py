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


class BooleanTransformTests(unittest.TestCase):
    def test_affirmative_forms_map_to_one(self):
        for raw in ("yes", "YES", "True", " true "):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms_map_to_zero(self):
        for raw in ("no", "No", "FALSE", " false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_input_raises(self):
        for raw in ("", "1", "0", "y", "maybe", "yes please"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class DateIsoRegressionTests(unittest.TestCase):
    def test_non_ascii_digits_raise_transform_error(self):
        # U+00B2 SUPERSCRIPT TWO passes str.isdigit() but int() rejects it;
        # it used to escape as an unhandled ValueError.
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "1/\u00b2/2026")

    def test_impossible_calendar_dates_raise(self):
        for raw in ("13/01/2026", "02/30/2026", "00/10/2026"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("date_iso", raw)

    def test_year_length_checked_after_stripping(self):
        # " 202" is 4 characters before stripping but a 3-digit year after.
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "01/15/ 202")


class RunRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_inputs(self, files):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp, exist_ok=True)
        for name, text in files.items():
            with open(os.path.join(inp, name), "w") as fh:
                fh.write(text)
        return inp

    def write_rules(self, body):
        path = os.path.join(self.tmp, "rules.toml")
        with open(path, "w") as fh:
            fh.write("[transforms]\n" + body)
        return path

    def read_raw_state(self):
        with open(self.cache_path) as fh:
            return json.load(fh)

    def test_failed_transform_emits_no_report_and_no_cache(self):
        # a.csv is clean and sorts first; the run must still write nothing.
        inp = self.write_inputs({
            "a.csv": "item,amount\n1,$2.00\n",
            "b.csv": "item,amount\n1,see invoice\n"})
        rules = self.write_rules('amount = "currency_amount"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules, inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_crashing_transform_emits_no_report_and_no_cache(self):
        # a.csv has no mapped column and sorts first; b.csv then crashes.
        inp = self.write_inputs({"a.csv": "item\n1\n", "b.csv": "label\nx\n"})
        rules = self.write_rules('label = "upper"\n')

        def boom(value):
            raise RuntimeError("unexpected")

        with mock.patch.dict(transforms.REGISTRY, {"upper": boom}):
            with self.assertRaises(RuntimeError):
                reportgen.run(rules, inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_cached_run_reproduces_generated_from(self):
        # The status column is entirely empty: the fresh run and the cached
        # run must agree on generated_from (1, not the header count of 2).
        inp = self.write_inputs({"d.csv": "device_id,status\nd1,\nd2,\n"})
        rules = self.write_rules('device_id = "trim"\nstatus = "upper"\n')
        first = reportgen.run(rules, inp, self.out, self.cache_path)
        second = reportgen.run(rules, inp, self.out, self.cache_path)
        self.assertEqual(first["files"]["d.csv"]["generated_from"], 1)
        self.assertEqual(second["files"]["d.csv"]["generated_from"], 1)

    def test_entry_from_older_registry_is_not_reused(self):
        inp = self.write_inputs({"t.csv": "item,label\n1,alpha\n"})
        rules = self.write_rules('item = "round2"\n')
        reportgen.run(rules, inp, self.out, self.cache_path)
        state = self.read_raw_state()
        state["t.csv"]["registry_version"] = "2"
        state["t.csv"]["summary"]["columns"]["item"]["distinct"] = 999
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(rules, inp, self.out, self.cache_path)
        self.assertEqual(
            report["files"]["t.csv"]["summary"]["columns"]["item"]["distinct"], 1)

    def test_future_version_entry_is_treated_as_empty(self):
        inp = self.write_inputs({"t.csv": "item,label\n1,alpha\n"})
        rules = self.write_rules('item = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path))
        future = {"t.csv": {
            "digest": cache.file_digest(os.path.join(inp, "t.csv")),
            "rows": 1, "generated_from": 1,
            "rules_fp": cache.rules_fingerprint(reportgen.load_rules(rules)),
            "registry_version": "99",
            "summary": {"columns": "bogus", "skipped_rows": []}}}
        with open(self.cache_path, "w") as fh:
            json.dump(future, fh)
        report = reportgen.run(rules, inp, self.out, self.cache_path)
        self.assertEqual(
            report["files"]["t.csv"]["summary"]["columns"]["item"]["numeric_sum"], 1.0)
        state = self.read_raw_state()
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_top_level_version_state_is_rewritten(self):
        inp = self.write_inputs({"t.csv": "item,label\n1,alpha\n"})
        rules = self.write_rules('item = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({"version": 99, "entries": {}}, fh)
        reportgen.run(rules, inp, self.out, self.cache_path)
        self.assertEqual(set(self.read_raw_state()), {"t.csv"})

    def test_html_escapes_file_and_column_names(self):
        inp = self.write_inputs({"a<b>.csv": "c<d>\n1\n"})
        rules = self.write_rules("")
        reportgen.run(rules, inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html")) as fh:
            html = fh.read()
        self.assertIn("a&lt;b&gt;.csv", html)
        self.assertIn("c&lt;d&gt;", html)
        self.assertNotIn("<d>", html)


class FutureVersionTests(unittest.TestCase):
    def test_version_comparison_is_numeric(self):
        self.assertTrue(cache.is_future_state({"x": {"registry_version": "10"}}))
        self.assertFalse(cache.is_future_state({"x": {"registry_version": "3"}}))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-cli-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_cli(self, csv_text):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp, exist_ok=True)
        with open(os.path.join(inp, "x.csv"), "w") as fh:
            fh.write(csv_text)
        rules = os.path.join(self.tmp, "rules.toml")
        with open(rules, "w") as fh:
            fh.write('[transforms]\namount = "currency_amount"\n')
        return subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"), "--rules", rules,
             "--input", inp, "--output", os.path.join(self.tmp, "out"),
             "--cache", os.path.join(self.tmp, "cache", "state.json")],
            capture_output=True, text=True)

    def test_failed_run_exits_nonzero(self):
        proc = self.run_cli("amount\nsee invoice\n")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("warning", proc.stderr)

    def test_clean_run_exits_zero(self):
        proc = self.run_cli("amount\n$2.00\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()

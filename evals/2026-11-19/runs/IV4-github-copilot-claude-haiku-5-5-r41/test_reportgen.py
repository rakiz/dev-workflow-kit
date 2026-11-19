"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import contextlib
import io
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


class BooleanAndRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_input(self, flag_values):
        with open(os.path.join(self.inp, "f.csv"), "w") as fh:
            fh.write("flag\n" + "".join(v + "\n" for v in flag_values))

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)

    def test_boolean_accepts_case_insensitive_words(self):
        self.assertEqual(transforms.apply("boolean", "Yes"), 1.0)
        self.assertEqual(transforms.apply("boolean", " TRUE "), 1.0)
        self.assertEqual(transforms.apply("boolean", "no"), 0.0)
        self.assertEqual(transforms.apply("boolean", "False"), 0.0)

    def test_boolean_rejects_other_input(self):
        for bad in ("maybe", "1", "", "y"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)

    def test_boolean_column_values_end_to_end(self):
        self.write_input(["yes", "No", "TRUE"])
        cols = self.run_tool()["files"]["f.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
        self.assertEqual(cols["flag"]["distinct"], 2)

    def test_date_iso_superscript_digits_is_transform_error_not_crash(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "\u00b2/15/2026")

    def test_superscript_date_fails_run_without_writing(self):
        with open(os.path.join(self.inp, "d.csv"), "w") as fh:
            fh.write("date\n\u00b2/15/2026\n")
        rules = os.path.join(self.tmp, "rules_date.toml")
        with open(rules, "w") as fh:
            fh.write('[transforms]\ndate = "date_iso"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_future_schema_cache_is_treated_as_empty_and_rewritten(self):
        self.write_input(["yes"])
        os.makedirs(os.path.dirname(self.cache_path))
        future = {"f.csv": {"digest": "x", "rows": 99, "generated_from": 1,
                            "rules_fp": "x", "registry_version": "99",
                            "summary": {"columns": {}, "skipped_rows": []}}}
        with open(self.cache_path, "w") as fh:
            json.dump(future, fh)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["f.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(state["f.csv"]["rows"], 1)

    def test_failed_transform_leaves_report_and_cache_byte_identical(self):
        self.write_input(["yes"])
        self.run_tool()
        def snap(p):
            with open(p, "rb") as fh:
                return fh.read()
        snapshot = {p: snap(p) for p in (
            os.path.join(self.out, "report.json"),
            os.path.join(self.out, "report.html"), self.cache_path)}
        self.write_input(["yes", "perhaps"])
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        for path, before in snapshot.items():
            self.assertEqual(snap(path), before, path)

    def test_main_returns_1_on_failed_transform(self):
        self.write_input(["perhaps"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(reportgen.main([
                "--rules", self.rules_path, "--input", self.inp,
                "--output", self.out, "--cache", self.cache_path]), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_rules_file_read_once_per_run(self):
        self.write_input(["yes"])
        with open(os.path.join(self.inp, "g.csv"), "w") as fh:
            fh.write("flag\nno\n")
        calls = []
        orig = reportgen.load_rules
        reportgen.load_rules = lambda p: (calls.append(p), orig(p))[1]
        try:
            self.run_tool()
        finally:
            reportgen.load_rules = orig
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

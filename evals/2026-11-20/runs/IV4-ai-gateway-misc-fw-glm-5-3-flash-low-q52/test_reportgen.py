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

    def test_date_iso(self):
        self.assertEqual(transforms.apply("date_iso", "01/15/2026"), "2026-01-15")
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "2026-01-15")

    def test_unknown_transform_name(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("nope", "x")

    def test_boolean_affirmative_and_negative(self):
        for raw, expected in [("yes", 1.0), ("Yes", 1.0), ("YES", 1.0),
                              ("true", 1.0), ("TRUE", 1.0), ("True", 1.0),
                              (" no ", 0.0), ("No", 0.0), ("False", 0.0)]:
            self.assertEqual(transforms.apply("boolean", raw), expected)

    def test_boolean_rejects_other_input(self):
        for raw in ["", "y", "1", "maybe", "enabled"]:
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


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

    def test_future_version_cache_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        future = {
            "small_transactions.csv": {
                "digest": "deadbeef", "rows": 1, "generated_from": 1,
                "rules_fp": "x", "registry_version": "999",
                "summary": {"columns": {}, "skipped_rows": []}}}
        with open(self.cache_path, "w") as fh:
            json.dump(future, fh)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertIn("small_transactions.csv", state)
        self.assertEqual(state["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FailurePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_input(self, rows):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,label\n" + "".join(rows))

    def test_failed_transform_writes_nothing_and_leaves_outputs_intact(self):
        self.write_input(["1,alpha\n"])
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json")) as fh:
            json_before = fh.read()
        with open(os.path.join(self.out, "report.html")) as fh:
            html_before = fh.read()
        with open(self.cache_path) as fh:
            cache_before = fh.read()

        self.write_input(["2,beta\n", "oops,gamma\n"])
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json")) as fh:
            self.assertEqual(fh.read(), json_before)
        with open(os.path.join(self.out, "report.html")) as fh:
            self.assertEqual(fh.read(), html_before)
        with open(self.cache_path) as fh:
            self.assertEqual(fh.read(), cache_before)

    def test_main_exits_1_on_transform_failure(self):
        self.write_input(["oops,gamma\n"])
        rc = reportgen.main(["--rules", self.rules_path, "--input", self.inp,
                             "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_rules_file_read_at_most_once_per_run(self):
        self.write_input(["1,alpha\n", "2,beta\n"])
        calls = []
        original = reportgen.load_rules

        def counting(path):
            calls.append(path)
            return original(path)

        reportgen.load_rules = counting
        try:
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        finally:
            reportgen.load_rules = original
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

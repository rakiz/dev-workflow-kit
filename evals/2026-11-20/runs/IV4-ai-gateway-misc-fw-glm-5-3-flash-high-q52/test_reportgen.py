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
    def test_affirmative_forms_map_to_1(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms_map_to_0(self):
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_input_raises(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("boolean", "maybe")
        with self.assertRaises(transforms.TransformError):
            transforms.apply("boolean", "1")

    def test_boolean_values_sum_numerically(self):
        rules = {"flag": "boolean"}
        summary = reportgen.summarize_file(["flag"], [["yes"], ["no"], ["YES"]],
                                           rules)
        col = summary["columns"]["flag"]
        self.assertEqual(col["numeric_sum"], 1.0)
        self.assertEqual(col["distinct"], 2)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self, input_dir=None, rules=None):
        return reportgen.run(rules or RULES, input_dir or INPUT_DIR,
                             self.out, self.cache_path)

    def test_future_schema_version_cache_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({"version": "99",
                       "entries": {"small_devices.csv": {"junk": True}}}, fh)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        self.assertNotIn("version", state)

    def test_future_version_cache_full_run_rewrites_valid_state(self):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({"version": 99}, fh)
        before = cache.file_digest(
            os.path.join(INPUT_DIR, "small_transactions.csv"))
        self.run_tool()
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["small_transactions.csv"]["digest"], before)
        self.assertEqual(state["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_entry_from_older_registry_is_not_reused(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        state["small_devices.csv"]["registry_version"] = "1"
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["small_devices.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FailurePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-policy-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "ok.csv"), "w") as fh:
            fh.write("item\n1\n2\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out,
                             self.cache_path)

    def test_transform_failure_leaves_outputs_and_cache_intact(self):
        self.run_tool()
        cache_before = open(self.cache_path, "rb").read()
        report_before = open(os.path.join(self.out, "report.json"), "rb").read()
        html_before = open(os.path.join(self.out, "report.html"), "rb").read()
        with open(os.path.join(self.inp, "bad.csv"), "w") as fh:
            fh.write("item\nnot-a-number\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertEqual(open(self.cache_path, "rb").read(), cache_before)
        self.assertEqual(open(os.path.join(self.out, "report.json"), "rb").read(),
                         report_before)
        self.assertEqual(open(os.path.join(self.out, "report.html"), "rb").read(),
                         html_before)

    def test_main_exits_1_on_transform_failure(self):
        with open(os.path.join(self.inp, "bad.csv"), "w") as fh:
            fh.write("item\nnot-a-number\n")
        rc = reportgen.main(["--rules", self.rules_path, "--input", self.inp,
                             "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))

    def test_main_exits_0_on_success(self):
        rc = reportgen.main(["--rules", self.rules_path, "--input", self.inp,
                             "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(rc, 0)


class RulesReadCountTests(unittest.TestCase):
    def test_rules_file_read_at_most_once_per_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-rulescount-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        for i in range(3):
            with open(os.path.join(inp, "f%d.csv" % i), "w") as fh:
                fh.write("item\n1\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        original = reportgen.load_rules
        calls = []

        def counting(path):
            calls.append(path)
            return original(path)

        reportgen.load_rules = counting
        try:
            reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                          os.path.join(tmp, "cache", "state.json"))
        finally:
            reportgen.load_rules = original
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

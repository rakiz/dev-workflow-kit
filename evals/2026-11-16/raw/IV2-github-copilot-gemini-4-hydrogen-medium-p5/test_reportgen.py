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

    def test_boolean(self):
        for val in ("yes", "YES", "Yes", " true ", "TRUE"):
            res = transforms.apply("boolean", val)
            self.assertEqual(res, 1.0)
            self.assertIsInstance(res, float)
        for val in ("no", "NO", "No", " false ", "FALSE"):
            res = transforms.apply("boolean", val)
            self.assertEqual(res, 0.0)
            self.assertIsInstance(res, float)
        for bad in ("maybe", "1", "0", "", "y"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)


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

    def test_boolean_transform_end_to_end(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "b.csv"), "w") as fh:
            fh.write("id,active\n1,YES\n2,no\n3,True\n4,FALSE\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        report = self.run_tool(rules=rules_path, input_dir=inp)
        cols = report["files"]["b.csv"]["summary"]["columns"]
        self.assertEqual(cols["active"]["numeric_sum"], 1.0)
        self.assertEqual(cols["active"]["distinct"], 2)
        self.assertEqual(cols["active"]["sample"], [0.0, 1.0])

    def test_failed_transform_leaves_no_report_and_no_cache(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as fh:
            fh.write("flag\nyes\n")
        with open(os.path.join(inp, "b.csv"), "w") as fh:
            fh.write("flag\ninvalid\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool(rules=rules_path, input_dir=inp)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unhandled_transform_crash_leaves_no_report_and_no_cache(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a.csv"), "w") as fh:
            fh.write("val\nok\n")
        with open(os.path.join(inp, "b.csv"), "w") as fh:
            fh.write("val\ncrash\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nval = "boom"\n')

        def boom(v):
            if v == "crash":
                raise RuntimeError("boom")
            return v

        transforms.REGISTRY["boom"] = boom
        try:
            with self.assertRaises(RuntimeError):
                self.run_tool(rules=rules_path, input_dir=inp)
        finally:
            transforms.REGISTRY.pop("boom", None)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))


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

    def test_older_registry_version_not_reused(self):
        self.run_tool()
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        state["small_transactions.csv"]["registry_version"] = "1"
        state["small_transactions.csv"]["rows"] = 999
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        report = self.run_tool()
        self.assertEqual(report["files"]["small_transactions.csv"]["rows"], 4)
        new_state = cache.load_state(self.cache_path)
        self.assertEqual(new_state["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_future_schema_version_top_level_and_entry(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": 99, "extra": {"digest": "bad"}}, fh)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertNotIn("version", state)
        self.assertNotIn("extra", state)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})

        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"small_transactions.csv": {"registry_version": "10"}}, fh)
        report2 = self.run_tool()
        self.assertEqual(report2["total_rows"], 12012)
        state2 = cache.load_state(self.cache_path)
        self.assertEqual(state2["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


if __name__ == "__main__":
    unittest.main()

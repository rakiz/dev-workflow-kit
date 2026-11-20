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


class NextReleaseAndRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-next-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)

    def test_boolean_transform_values_and_errors(self):
        for val in ("yes", "YES", "Yes", "true", "TRUE", "True", " yes "):
            self.assertEqual(transforms.apply("boolean", val), 1.0)
        for val in ("no", "NO", "No", "false", "FALSE", "False", " no "):
            self.assertEqual(transforms.apply("boolean", val), 0.0)
        for bad in ("", "1", "0", "y", "n", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)

    def test_boolean_transform_end_to_end(self):
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("id,active\n1,YES\n2,no\n3,True\n4,false\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["active"]["numeric_sum"], 1.0)
        self.assertEqual(cols["active"]["sample"], [0.0, 1.0])

    def test_future_cache_schema_top_level_and_per_entry(self):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("k\nhello\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nk = "upper"\n')

        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        # Top-level future schema version
        with open(self.cache_path, "w") as fh:
            json.dump({"version": "99", "entries": {"a.csv": {"bad": True}}}, fh)
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"a.csv"})
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

        # Per-entry future schema version (including > "10" string comparison)
        with open(self.cache_path, "w") as fh:
            json.dump({"a.csv": {"registry_version": "10", "new_field": 123}}, fh)
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_failure_policy_exits_1_and_preserves_outputs_and_cache(self):
        import subprocess
        import sys

        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item,val\n1,10\n")
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("item,val\n2,20\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')

        ok = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True,
        )
        self.assertEqual(ok.returncode, 0, ok.stderr)

        json_path = os.path.join(self.out, "report.json")
        html_path = os.path.join(self.out, "report.html")
        with open(json_path, "rb") as fh:
            good_json = fh.read()
        with open(html_path, "rb") as fh:
            good_html = fh.read()
        with open(self.cache_path, "rb") as fh:
            good_cache = fh.read()

        # Modify a.csv (valid) and b.csv (invalid transform)
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item,val\n1,99\n")
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("item,val\n2,not_a_number\n")

        bad = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True,
        )
        self.assertEqual(bad.returncode, 1)

        with open(json_path, "rb") as fh:
            self.assertEqual(fh.read(), good_json)
        with open(html_path, "rb") as fh:
            self.assertEqual(fh.read(), good_html)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), good_cache)

    def test_rules_file_read_once_per_run(self):
        import builtins
        from unittest import mock

        read_count = 0
        real_open = builtins.open
        rules_abs = os.path.abspath(RULES)

        def counting_open(file, *args, **kwargs):
            nonlocal read_count
            if os.path.abspath(str(file)) == rules_abs:
                read_count += 1
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=counting_open):
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(read_count, 1)

    def test_stale_registry_version_not_reused(self):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("k\nhi\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nk = "upper"\n')

        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["summary"]["columns"]["k"]["sample"] = ["STALE"]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(
            report["files"]["a.csv"]["summary"]["columns"]["k"]["sample"],
            ["HI"],
        )
        new_state = cache.load_state(self.cache_path)
        self.assertEqual(new_state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)


if __name__ == "__main__":
    unittest.main()

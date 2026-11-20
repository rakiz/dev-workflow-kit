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

    def test_boolean(self):
        for raw in ("yes", "Yes", "YES", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "NO", "false", "False", "FALSE"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_boolean_rejects_other_input(self):
        for raw in ("", "y", "1", "0", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

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


class FailurePolicyTests(unittest.TestCase):
    """Regression: a transform failure must exit nonzero, emit nothing
    new, and leave the previous report and cache byte-for-byte intact."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        shutil.copy(os.path.join(INPUT_DIR, "small_transactions.csv"), self.inp)
        # First, a good run that produces report + cache.
        reportgen.run(RULES, self.inp, self.out, self.cache_path)
        self.snapshot = {}
        for fname in ("report.json", "report.html"):
            with open(os.path.join(self.out, fname), "rb") as fh:
                self.snapshot[fname] = fh.read()
        with open(self.cache_path, "rb") as fh:
            self.snapshot["cache"] = fh.read()

    def poison_input(self):
        # Append a row whose amount fails the currency_amount transform.
        with open(os.path.join(self.inp, "small_transactions.csv"), "a") as fh:
            fh.write("t9,Acme,not-a-number,01/15/2026\n")

    def read_snapshot(self):
        current = {"cache": None}
        with open(self.cache_path, "rb") as fh:
            current["cache"] = fh.read()
        for fname in ("report.json", "report.html"):
            with open(os.path.join(self.out, fname), "rb") as fh:
                current[fname] = fh.read()
        return current

    def test_caught_failure_leaves_outputs_and_cache_intact(self):
        self.poison_input()
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(RULES, self.inp, self.out, self.cache_path)
        self.assertEqual(self.read_snapshot(), self.snapshot)

    def test_caught_failure_exits_1_and_emits_nothing_new(self):
        self.poison_input()
        fresh_out = os.path.join(self.tmp, "out2")
        code = reportgen.main(["--rules", RULES, "--input", self.inp,
                               "--output", fresh_out, "--cache", self.cache_path])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(os.path.join(fresh_out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(fresh_out, "report.html")))
        self.assertEqual(self.read_snapshot(), self.snapshot)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        shutil.copy(os.path.join(INPUT_DIR, "small_transactions.csv"), self.inp)

    def run_tool(self, input_dir=None):
        return reportgen.run(RULES, input_dir or self.inp, self.out,
                             self.cache_path)

    def test_future_registry_version_cache_treated_as_empty(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        for entry in state.values():
            entry["registry_version"] = "999"
            entry["rows"] = 0
            entry["summary"] = {"columns": {}, "skipped_rows": []}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.run_tool()  # must not crash and must not reuse
        self.assertEqual(report["total_rows"], 4)
        state2 = cache.load_state(self.cache_path)
        self.assertEqual(len(state2), 1)
        for entry in state2.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(entry["rows"], 4)

    def test_rules_file_read_at_most_once_per_run(self):
        with mock.patch("reportgen.load_rules",
                        side_effect=reportgen.load_rules) as mocked:
            self.run_tool()
        self.assertEqual(mocked.call_count, 1)

    def test_generated_from_stable_between_fresh_and_cached_run(self):
        # Regression: generated_from was computed one way for a fresh run
        # and another way when cached, so report.json changed between
        # consecutive runs on unchanged input. A rules-mapped column that
        # is entirely empty triggers the divergence.
        with open(os.path.join(self.inp, "small_transactions.csv"), "w") as fh:
            fh.write("tx_id,flag\n1,\n2,\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\ntx_id = "trim"\nflag = "trim"\n')
        report1 = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            json1 = fh.read()
        report2 = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report1, report2)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            json2 = fh.read()
        self.assertEqual(json1, json2)
        self.assertEqual(
            report2["files"]["small_transactions.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()

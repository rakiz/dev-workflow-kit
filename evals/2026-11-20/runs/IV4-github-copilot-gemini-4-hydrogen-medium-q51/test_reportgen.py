"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import builtins
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
    def test_boolean_values_case_insensitive(self):
        for raw in ("yes", "YES", "True", "true", " yes "):
            res = transforms.apply("boolean", raw)
            self.assertIsInstance(res, float)
            self.assertEqual(res, 1.0)
        for raw in ("no", "NO", "False", "false", " no "):
            res = transforms.apply("boolean", raw)
            self.assertIsInstance(res, float)
            self.assertEqual(res, 0.0)

    def test_boolean_invalid_raises_transform_error(self):
        for bad in ("maybe", "1", "0", "y", "n", ""):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)

    def test_boolean_end_to_end_numeric_sum(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("id,active\n1,YES\n2,no\n3,True\n4,False\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        report = reportgen.run(rules_path, inp, out, cache_path)
        col = report["files"]["flags.csv"]["summary"]["columns"]["active"]
        self.assertEqual(col["numeric_sum"], 1.0)
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["non_empty"], 4)
        self.assertEqual(col["sample"], [0.0, 1.0])


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("k,v\nx,1\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nv = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)

    def test_future_top_level_schema_version_treated_as_empty(self):
        for ver in (99, "10"):
            with open(self.cache_path, "w") as fh:
                json.dump({"version": ver, "stale.csv": {"rows": 999}}, fh)
            report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
            self.assertEqual(report["total_rows"], 1)
            with open(self.cache_path) as fh:
                state = json.load(fh)
            self.assertEqual(set(state), {"a.csv"})
            self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_entry_version_treated_as_empty(self):
        digest = cache.file_digest(os.path.join(self.inp, "a.csv"))
        with open(self.cache_path, "w") as fh:
            json.dump({"a.csv": {"digest": digest, "registry_version": "99",
                                 "rows": 999, "generated_from": 1,
                                 "summary": {"columns": {}, "skipped_rows": []}}}, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_older_registry_version_not_reused(self):
        digest = cache.file_digest(os.path.join(self.inp, "a.csv"))
        rules_fp = cache.rules_fingerprint({"v": "round2"})
        with open(self.cache_path, "w") as fh:
            json.dump({"a.csv": {"digest": digest, "rules_fp": rules_fp,
                                 "registry_version": "1", "rows": 999,
                                 "generated_from": 1,
                                 "summary": {"columns": {}, "skipped_rows": []}}}, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["a.csv"]["rows"], 1)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)


class InvariantRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-inv-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _snapshot(self):
        paths = [
            os.path.join(self.out, "report.json"),
            os.path.join(self.out, "report.html"),
            self.cache_path,
        ]
        out = {}
        for p in paths:
            with open(p, "rb") as fh:
                out[p] = fh.read()
        return out

    def test_failed_transform_exits_1_and_leaves_outputs_and_cache_intact(self):
        with open(os.path.join(self.inp, "good.csv"), "w") as fh:
            fh.write("id,val\n1,1.5\n")
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        before = self._snapshot()

        with open(os.path.join(self.inp, "bad.csv"), "w") as fh:
            fh.write("id,val\n2,not_a_number\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self._snapshot(), before)

    def test_unhandled_transform_crash_leaves_outputs_and_cache_intact(self):
        with open(os.path.join(self.inp, "good.csv"), "w") as fh:
            fh.write("id,val\n1,1.5\n")
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        before = self._snapshot()

        with open(os.path.join(self.inp, "crash.csv"), "w") as fh:
            fh.write("id,val\n2,2.5\n")
        with mock.patch.dict(transforms.REGISTRY, {"round2": lambda v: 1 / 0}):
            with self.assertRaises(ZeroDivisionError):
                reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(self._snapshot(), before)

    def test_rules_file_read_at_most_once_per_run(self):
        real_open = builtins.open
        reads = 0
        target = os.path.abspath(RULES)

        def counting_open(file, *args, **kwargs):
            nonlocal reads
            if os.path.abspath(str(file)) == target:
                reads += 1
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=counting_open):
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(reads, 1)


if __name__ == "__main__":
    unittest.main()

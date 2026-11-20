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
        for raw, expected in (("yes", 1.0), ("TRUE", 1.0),
                              ("No", 0.0), ("false", 0.0)):
            with self.subTest(raw=raw):
                self.assertEqual(transforms.apply("boolean", raw), expected)
        for raw in ("1", "", "maybe"):
            with self.subTest(raw=raw):
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

    def test_boolean_end_to_end(self):
        inp = os.path.join(self.tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("flag\nYES\ntrue\nNo\nFALSE\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = self.run_tool(rules=rules_path, input_dir=inp)
        col = report["files"]["t.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["numeric_sum"], 1.0)

    def test_rules_file_is_read_once_per_run(self):
        with mock.patch("reportgen.load_rules", wraps=reportgen.load_rules) as load:
            self.run_tool()
        self.assertEqual(load.call_count, 1)


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

    def test_future_versioned_cache_is_rebuilt(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        entry = state["small_transactions.csv"]
        entry["registry_version"] = str(int(cache.REGISTRY_VERSION) + 1)
        entry["summary"]["columns"] = {}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

        report = self.run_tool()
        columns = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(columns["merchant"]["distinct"], 3)
        rebuilt = cache.load_state(self.cache_path)
        self.assertEqual(rebuilt["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_old_registry_entry_is_not_reused(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        entry = state["small_transactions.csv"]
        entry["registry_version"] = str(int(cache.REGISTRY_VERSION) - 1)
        entry["summary"]["columns"] = {}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

        report = self.run_tool()
        columns = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(columns["merchant"]["distinct"], 3)
        rebuilt = cache.load_state(self.cache_path)
        self.assertEqual(rebuilt["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FailurePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-failure-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)
        self.input_path = os.path.join(self.inp, "a.csv")
        with open(self.input_path, "w") as fh:
            fh.write("value\n1\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nvalue = "round2"\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.artifacts = [os.path.join(self.out, "report.json"),
                          os.path.join(self.out, "report.html"),
                          self.cache_path]
        with open(self.artifacts[0], "rb") as fh:
            json_bytes = fh.read()
        with open(self.artifacts[1], "rb") as fh:
            html_bytes = fh.read()
        with open(self.artifacts[2], "rb") as fh:
            cache_bytes = fh.read()
        self.before = [json_bytes, html_bytes, cache_bytes]

    def assert_artifacts_unchanged(self):
        for path, before in zip(self.artifacts, self.before):
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), before, path)

    def run_main(self):
        return reportgen.main(["--rules", self.rules_path,
                               "--input", self.inp, "--output", self.out,
                               "--cache", self.cache_path])

    def test_handled_transform_failure_preserves_good_artifacts(self):
        with open(self.input_path, "w") as fh:
            fh.write("value\nnot-a-number\n")
        self.assertEqual(self.run_main(), 1)
        self.assert_artifacts_unchanged()

    def test_unhandled_transform_crash_preserves_good_artifacts(self):
        with open(self.input_path, "w") as fh:
            fh.write("value\n2\n")
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("value\ncrash\n")
        original_apply = transforms.apply

        def fail_on_second_file(name, value):
            if value == "crash":
                raise RuntimeError("unexpected transform crash")
            return original_apply(name, value)

        with mock.patch("reportgen.transforms.apply", side_effect=fail_on_second_file):
            with self.assertRaisesRegex(RuntimeError, "unexpected transform crash"):
                reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_artifacts_unchanged()

    def test_handled_transform_failure_emits_no_new_artifacts(self):
        for path in self.artifacts:
            os.remove(path)
        with open(self.input_path, "w") as fh:
            fh.write("value\nnot-a-number\n")
        self.assertEqual(self.run_main(), 1)
        for path in self.artifacts:
            self.assertFalse(os.path.exists(path), path)


if __name__ == "__main__":
    unittest.main()

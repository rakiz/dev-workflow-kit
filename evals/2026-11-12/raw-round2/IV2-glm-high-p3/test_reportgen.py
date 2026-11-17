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
    def test_boolean_affirmative(self):
        for raw in ("yes", "YES", "true", "True", " yes "):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_boolean_negative(self):
        for raw in ("no", "NO", "false", "False", " no "):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_boolean_rejects_other_input(self):
        for raw in ("", "maybe", "1", "0", "null"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class FailurePolicyTests(unittest.TestCase):
    """A run in which any cell failed its transform must emit no report
    and leave no cache state behind — whatever way the transform failed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,blah\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out,
                             self.cache_path)

    def assert_nothing_written(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_cell_emits_no_report_and_no_cache(self):
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_nothing_written()

    def test_unexpected_transform_crash_is_a_transform_failure(self):
        def boom(value):
            raise ZeroDivisionError("unexpected crash")
        original = transforms.REGISTRY["round2"]
        transforms.REGISTRY["round2"] = boom
        self.addCleanup(lambda: transforms.REGISTRY.__setitem__(
            "round2", original))
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_nothing_written()

    def test_clean_run_after_failure_writes_everything(self):
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,no\n")
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["summary"]["columns"]
                         ["flag"]["numeric_sum"], 1.0)
        self.assertTrue(os.path.exists(self.cache_path))


class CacheVersionTests(unittest.TestCase):
    """A cache state from another schema/registry version is never
    reused; a future-version state file is treated as empty and
    rewritten as a valid current one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-ver-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv_path = os.path.join(self.inp, "t.csv")
        with open(self.csv_path, "w") as fh:
            fh.write("item,flag\n1,yes\n2,no\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out,
                             self.cache_path)

    def test_future_version_state_treated_as_empty(self):
        digest = cache.file_digest(self.csv_path)
        self.write_state({
            "version": cache.REGISTRY_VERSION + "0",
            "t.csv": {"digest": digest, "rows": 999,
                      "generated_from": 999, "rules_fp": "x",
                      "registry_version": cache.REGISTRY_VERSION + "0",
                      "summary": {"columns": {}, "skipped_rows": []}}})
        report = self.run_tool()
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["item"]["numeric_sum"], 3.0)
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertNotIn("version", state)

    def test_entry_from_other_registry_version_not_reused(self):
        digest = cache.file_digest(self.csv_path)
        self.write_state({
            "t.csv": {"digest": digest, "rows": 999,
                      "generated_from": 999, "rules_fp": "x",
                      "registry_version": "1",
                      "summary": {"columns": {}, "skipped_rows": []}}})
        report = self.run_tool()
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["item"]["numeric_sum"], 3.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_corrupt_state_file_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            fh.write("{not json")
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


if __name__ == "__main__":
    unittest.main()

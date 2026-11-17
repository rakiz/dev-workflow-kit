"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
import subprocess
import sys
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
    def test_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", "true", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "NO", "false", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_input_raises(self):
        for raw in ("", "1", "0", "y", "maybe", " yes", "yes "):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class FutureStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def test_future_state_is_treated_as_empty_and_rewritten(self):
        digest = cache.file_digest(os.path.join(INPUT_DIR, "small_devices.csv"))
        with open(self.cache_path, "w") as fh:
            json.dump({"small_devices.csv": {
                "digest": digest, "rows": 0, "generated_from": 0,
                "summary": {"columns": {}, "skipped_rows": []},
                "registry_version": "3"}, "version": 3}, fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["small_devices.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        self.assertNotIn("version", state)

    def test_future_entry_marker_alone_is_treated_as_empty(self):
        with open(self.cache_path, "w") as fh:
            json.dump({"x.csv": {"digest": "d", "registry_version": "9"}}, fh)
        self.assertEqual(cache.load_state(self.cache_path), {})


class CacheRegistryVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-regver-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_entry_from_older_registry_is_not_reused(self):
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        state = json.load(open(self.cache_path))
        state["small_devices.csv"]["registry_version"] = "1"
        state["small_devices.csv"]["summary"]["columns"] = {
            "device_id": {"non_empty": 99, "distinct": 99, "sample": ["bogus"]}}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        cols = report["files"]["small_devices.csv"]["summary"]["columns"]
        self.assertNotEqual(cols["device_id"]["sample"], ["bogus"])
        self.assertEqual(cols["device_id"]["distinct"], 3)


class GeneratedFromConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-genfrom-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        # 'b' is mapped but empty in every row: header-mapped count is 2,
        # non-empty mapped count is 1.
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("a,b,c\n1,,x\n2,,y\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\na = "trim"\nb = "trim"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_fresh_and_cached_runs_report_same_generated_from(self):
        first = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        second = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(first["files"]["t.csv"]["generated_from"], 1)
        self.assertEqual(second["files"]["t.csv"]["generated_from"], 1)
        self.assertEqual(cache.load_state(self.cache_path)["t.csv"]["generated_from"], 1)


class InvariantTests(unittest.TestCase):
    """A run in which any cell failed its transform emits no report and
    leaves no cache state."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-invariant-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_input(self, body):
        with open(os.path.join(self.inp, "f.csv"), "w") as fh:
            fh.write("flag\n" + body)

    def assert_no_outputs(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failing_cell_emits_nothing(self):
        self.write_input("yes\nmaybe\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assert_no_outputs()

    def test_failing_cell_removes_previous_outputs(self):
        self.write_input("yes\nno\n")
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertTrue(os.path.exists(self.cache_path))
        self.write_input("yes\nmaybe\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assert_no_outputs()

    def test_cli_failing_run_exits_nonzero(self):
        self.write_input("yes\nmaybe\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            cwd=BASE, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assert_no_outputs()


class DateIsoDigitsTests(unittest.TestCase):
    def test_superscript_digits_fail_the_cell_not_the_run(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "\u00b2/15/2026")


if __name__ == "__main__":
    unittest.main()

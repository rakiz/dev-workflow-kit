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

    def test_boolean(self):
        for raw in ("yes", "YES", "True", "tRUE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)
        for raw in ("", "maybe", "1", "0", "y", "yes please"):
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
    """A run in which any cell failed its transform emits no report and
    leaves no cache state behind."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

    def write(self, name, text):
        with open(os.path.join(self.inp, name), "w") as fh:
            fh.write(text)

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def assert_nothing_left(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_boolean_end_to_end(self):
        self.write("a.csv", "id,flag\n1,Yes\n2,no\n3,TRUE\n")
        report = self.run_tool()
        cols = report["files"]["a.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])

    def test_failed_cell_leaves_no_report_and_no_cache(self):
        # a.csv is fine and sorts first: its entry must not be saved early
        self.write("a.csv", "id,flag\n1,yes\n")
        self.write("b.csv", "id,flag\n1,yes\n2,maybe\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_nothing_left()

    def test_main_failed_cell_emits_nothing(self):
        self.write("b.csv", "id,flag\n1,maybe\n")
        reportgen.main(["--rules", self.rules, "--input", self.inp,
                        "--output", self.out, "--cache", self.cache_path])
        self.assert_nothing_left()

    def test_crash_in_later_file_leaves_no_cache(self):
        self.write("a.csv", "id,flag\n1,yes\n")
        self.write("b.csv", "id,flag\n1,yes\n")
        original = transforms.REGISTRY["boolean"]

        def crash(value):
            raise RuntimeError("boom")
        calls = []

        def flaky(value):
            calls.append(value)
            if len(calls) > 1:
                crash(value)
            return original(value)
        transforms.REGISTRY["boolean"] = flaky
        self.addCleanup(transforms.REGISTRY.__setitem__, "boolean", original)
        with self.assertRaises(RuntimeError):
            self.run_tool()
        self.assert_nothing_left()

    def test_poisoned_cache_entry_is_not_reused(self):
        self.write("a.csv", "id,flag\n1,yes\n")
        self.run_tool()
        state = cache.load_state(self.cache_path)
        state["a.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "x"}]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.run_tool()
        self.assertEqual(report["files"]["a.csv"]["summary"]["skipped_rows"], [])


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hyg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

    def write_state(self, obj):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(obj, fh)

    def check_rewritten(self):
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(len(state), 4)
        with open(self.cache_path) as fh:
            raw = json.load(fh)
        self.assertEqual(raw, state)

    def test_future_entry_version_treated_as_empty(self):
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        for entry in state.values():
            entry["registry_version"] = str(int(cache.REGISTRY_VERSION) + 1)
        state["small_devices.csv"] = {"future_shape": True,
                                      "registry_version": "99"}
        self.write_state(state)
        self.check_rewritten()

    def test_future_top_level_version_treated_as_empty(self):
        self.write_state({"version": int(cache.REGISTRY_VERSION) + 1,
                          "entries": {"x": 1}})
        self.check_rewritten()

    def test_unreadable_state_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            fh.write("{not json")
        self.check_rewritten()

    def test_older_registry_entry_not_reused(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        state["small_devices.csv"]["registry_version"] = "1"
        state["small_devices.csv"]["summary"] = {"columns": {}, "skipped_rows": []}
        self.write_state(state)
        report = self.run_tool()
        cols = report["files"]["small_devices.csv"]["summary"]["columns"]
        self.assertIn("device_id", cols)

    def test_cached_run_reports_same_as_fresh_run(self):
        first = self.run_tool()
        second = self.run_tool()
        self.assertEqual(first, second)
        self.assertEqual(first["files"]["small_devices.csv"]["generated_from"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["small_devices.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()

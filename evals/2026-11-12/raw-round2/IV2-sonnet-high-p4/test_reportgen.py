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
    def test_boolean_forms(self):
        for raw in ("yes", "YES", "True", " true "):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_boolean_rejects_other_input(self):
        for raw in ("", "y", "1", "maybe", "yes no"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")

    def write(self, name, text):
        with open(os.path.join(self.inp, name), "w") as fh:
            fh.write(text)

    def set_rules(self, text):
        with open(self.rules, "w") as fh:
            fh.write(text)

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def test_failed_cell_leaves_no_report_and_no_cache(self):
        # "a.csv" is clean, "b.csv" has a bad cell: nothing may be left behind.
        self.write("a.csv", "x\nyes\n")
        self.write("b.csv", "x\nmaybe\n")
        self.set_rules('[transforms]\nx = "boolean"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_run_keeps_previous_cache_untouched(self):
        self.write("a.csv", "x\nyes\n")
        self.set_rules('[transforms]\nx = "boolean"\n')
        self.run_tool()
        with open(self.cache_path) as fh:
            before = fh.read()
        self.write("b.csv", "x\nmaybe\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        with open(self.cache_path) as fh:
            self.assertEqual(fh.read(), before)

    def test_boolean_column_summary(self):
        self.write("a.csv", "x\nYes\nno\nTRUE\nfalse\nyes\n")
        self.set_rules('[transforms]\nx = "boolean"\n')
        col = self.run_tool()["files"]["a.csv"]["summary"]["columns"]["x"]
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["numeric_sum"], 3.0)

    def test_numeric_sum_counts_duplicate_cells(self):
        self.write("a.csv", "v\n1.5\n1.5\n2\n")
        self.set_rules('[transforms]\nv = "round2"\n')
        col = self.run_tool()["files"]["a.csv"]["summary"]["columns"]["v"]
        self.assertEqual(col["numeric_sum"], 5.0)

    def test_future_version_state_is_treated_as_empty(self):
        self.write("a.csv", "x\nyes\n")
        self.set_rules('[transforms]\nx = "boolean"\n')
        os.makedirs(os.path.dirname(self.cache_path))
        for future in ({"version": 99, "a.csv": {"digest": "zzz"}},
                       {"a.csv": {"digest": "zzz", "registry_version": "99"}}):
            with open(self.cache_path, "w") as fh:
                json.dump(future, fh)
            self.run_tool()
            with open(self.cache_path) as fh:
                state = json.load(fh)
            self.assertEqual(set(state), {"a.csv"})
            self.assertEqual(state["a.csv"]["registry_version"],
                             cache.REGISTRY_VERSION)
            self.assertNotEqual(state["a.csv"]["digest"], "zzz")

    def test_future_version_state_rewritten_even_if_all_files_match(self):
        self.write("a.csv", "x\nyes\n")
        self.set_rules('[transforms]\nx = "boolean"\n')
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["version"] = int(cache.REGISTRY_VERSION) + 1
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        self.run_tool()
        with open(self.cache_path) as fh:
            self.assertNotIn("version", json.load(fh))

    def test_stale_registry_version_entry_not_reused(self):
        self.write("a.csv", "x\nyes\n")
        self.set_rules('[transforms]\nx = "boolean"\n')
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["summary"] = {"columns": {}, "skipped_rows": []}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        col = self.run_tool()["files"]["a.csv"]["summary"]["columns"]
        self.assertIn("x", col)

    def test_generated_from_same_on_cached_run(self):
        self.write("a.csv", "x,y\nyes,\nno,\n")
        self.set_rules('[transforms]\nx = "boolean"\ny = "trim"\n')
        first = self.run_tool()["files"]["a.csv"]["generated_from"]
        second = self.run_tool()["files"]["a.csv"]["generated_from"]
        self.assertEqual(first, 1)
        self.assertEqual(second, first)
        with open(self.cache_path) as fh:
            self.assertEqual(json.load(fh)["a.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()

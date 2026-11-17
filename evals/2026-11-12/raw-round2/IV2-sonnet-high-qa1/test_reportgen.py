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
    def test_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", "True", "tRuE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)
        self.assertIsInstance(transforms.apply("boolean", "yes"), float)

    def test_other_input_raises(self):
        for raw in ("", "maybe", "1", "0", "y", "yes please"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class RegressionBase(unittest.TestCase):
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

    def set_rules(self, body):
        with open(self.rules, "w") as fh:
            fh.write("[transforms]\n" + body)

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def assert_nothing_emitted(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class BooleanEndToEndTests(RegressionBase):
    def test_boolean_column_summarised(self):
        self.write("t.csv", "k,flag\na,Yes\nb,NO\nc,true\n")
        self.set_rules('flag = "boolean"\n')
        cols = self.run_tool()["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["flag"]["distinct"], 2)


class FutureCacheTests(RegressionBase):
    def setUp(self):
        super().setUp()
        self.write("t.csv", "k\na\nb\n")
        self.set_rules('k = "trim"\n')
        os.makedirs(os.path.dirname(self.cache_path))

    def check_recovers(self, payload):
        with open(self.cache_path, "w") as fh:
            json.dump(payload, fh)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_top_level_future_version(self):
        self.check_recovers({"version": 99, "entries": {"x": 1}})

    def test_future_entry_version(self):
        self.check_recovers({"t.csv": {"registry_version": "10"}})

    def test_numeric_not_lexicographic(self):
        # "10" < "2" as strings, but 10 > 2 as versions
        self.check_recovers({"t.csv": {"registry_version": "10",
                                       "digest": "x"}})


class IncompleteTransformPassTests(RegressionBase):
    def test_failed_cell_in_later_file_leaves_nothing(self):
        self.write("a_good.csv", "n\n1\n2\n")
        self.write("b_bad.csv", "n\n1\noops\n")
        self.set_rules('n = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_nothing_emitted()

    def test_failed_boolean_cell_leaves_nothing(self):
        self.write("t.csv", "f\nyes\nmaybe\n")
        self.set_rules('f = "boolean"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_nothing_emitted()

    def test_unhandled_crash_leaves_no_cache(self):
        self.write("a_good.csv", "n\n1\n")
        self.write("b_bad.csv", "n\n2\n")
        self.set_rules('n = "boom"\n')
        real = transforms.REGISTRY.get("boom")

        def boom(value):
            if value == "2":
                raise RuntimeError("crash")
            return float(value)
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with self.assertRaises(RuntimeError):
            self.run_tool()
        self.assert_nothing_emitted()

    def test_unicode_digit_date_is_transform_failure_not_crash(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "1/\u00b2/2026")
        self.write("t.csv", "d\n1/\u00b2/2026\n")
        self.set_rules('d = "date_iso"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_nothing_emitted()

    def test_stale_failed_entry_is_not_reused(self):
        self.write("t.csv", "n\n1\n")
        self.set_rules('n = "round2"\n')
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "n", "reason": "old failure"}]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["summary"]["skipped_rows"], [])


class CacheReuseTests(RegressionBase):
    def test_older_registry_version_not_reused(self):
        self.write("t.csv", "n\n1\n")
        self.set_rules('n = "round2"\n')
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["t.csv"]["registry_version"] = "1"
        state["t.csv"]["summary"]["columns"]["n"]["numeric_sum"] = -1.0
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        cols = self.run_tool()["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["n"]["numeric_sum"], 1.0)

    def test_report_identical_cold_and_warm(self):
        self.write("t.csv", "a,b,c\n1,,x\n2,,y\n")
        self.set_rules('a = "round2"\nb = "trim"\nc = "upper"\n')
        cold = self.run_tool()
        warm = self.run_tool()
        self.assertEqual(cold, warm)
        self.assertEqual(cold["files"]["t.csv"]["generated_from"], 2)


class HtmlEscapeTests(RegressionBase):
    def test_names_and_columns_are_escaped(self):
        self.write("<i>.csv", "c<u>\nv\n")
        self.set_rules('x = "trim"\n')
        self.run_tool()
        with open(os.path.join(self.out, "report.html")) as fh:
            page = fh.read()
        self.assertNotIn("<i>", page)
        self.assertNotIn("<u>", page)


if __name__ == "__main__":
    unittest.main()

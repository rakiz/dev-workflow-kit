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
    def test_boolean_valid_values(self):
        for val in ("yes", "YES", "Yes", " true ", "TRUE", "True"):
            res = transforms.apply("boolean", val)
            self.assertEqual(res, 1.0)
            self.assertIsInstance(res, float)
        for val in ("no", "NO", "No", " false ", "FALSE", "False"):
            res = transforms.apply("boolean", val)
            self.assertEqual(res, 0.0)
            self.assertIsInstance(res, float)

    def test_boolean_invalid_values(self):
        for val in ("", "1", "0", "maybe", "y", "n"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", val)

    def test_boolean_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("id,active\n1,Yes\n2,FALSE\n3,true\n4,no\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        report = reportgen.run(rules_path, inp, out, cache_path)
        active = report["files"]["flags.csv"]["summary"]["columns"]["active"]
        self.assertEqual(active["distinct"], 2)
        self.assertEqual(active["numeric_sum"], 1.0)


class CacheHygieneAndRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")

    def test_future_schema_version_top_level_is_discarded_and_rewritten(self):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("id,val\n1,10\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        future_ver = int(cache.REGISTRY_VERSION) + 10
        with open(self.cache_path, "w") as fh:
            json.dump({"version": future_ver, "entries": ["unexpected"]}, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertNotIn("version", state)
        self.assertIn("a.csv", state)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_registry_version_entry_is_discarded_and_rewritten(self):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("id,val\n1,10\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        future_ver = str(int(cache.REGISTRY_VERSION) + 1)
        with open(self.cache_path, "w") as fh:
            json.dump({"a.csv": {"registry_version": future_ver, "digest": "bad"}}, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_regression_transform_failure_emits_no_report_and_no_cache(self):
        with open(os.path.join(self.inp, "a_good.csv"), "w") as fh:
            fh.write("val\n1.5\n")
        with open(os.path.join(self.inp, "b_bad.csv"), "w") as fh:
            fh.write("val\nnot_a_number\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_regression_html_escaping_in_render_html(self):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,label\ni1,<script>&\"x\"</script>\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "trim"\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html")) as fh:
            html_out = fh.read()
        self.assertNotIn("<script>", html_out)
        self.assertIn("&lt;script&gt;&amp;&quot;x&quot;&lt;/script&gt;", html_out)

    def test_regression_older_registry_version_not_reused(self):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("val\n10\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["rows"] = 999
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["a.csv"]["rows"], 1)

    def test_regression_generated_from_consistent_on_cache_hit(self):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("a,b\n1,\n")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\na = "trim"\nb = "trim"\n')
        cold = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        warm = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(cold["files"]["a.csv"]["generated_from"], 1)
        self.assertEqual(warm["files"]["a.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()

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
    def test_boolean_transform_values(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True", " true "):
            val = transforms.apply("boolean", raw)
            self.assertEqual(val, 1.0)
            self.assertIs(type(val), float)
        for raw in ("no", "NO", "No", "false", "FALSE", "False", " no "):
            val = transforms.apply("boolean", raw)
            self.assertEqual(val, 0.0)
            self.assertIs(type(val), float)
        for bad in ("1", "0", "y", "n", "maybe", ""):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)

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
        col = report["files"]["flags.csv"]["summary"]["columns"]["active"]
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["numeric_sum"], 1.0)


class CacheHygieneAndRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _write_csv(self, name, content):
        path = os.path.join(self.inp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def _write_rules(self, content):
        path = os.path.join(self.tmp, "rules.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def test_future_schema_top_level_version_resets_cache(self):
        self._write_csv("a.csv", "k,v\n1,yes\n")
        rules_path = self._write_rules('[transforms]\nv = "boolean"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": "99", "entries": {"a.csv": "opaque"}}, fh)
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"a.csv"})
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_schema_entry_version_resets_cache(self):
        self._write_csv("a.csv", "k,v\n1,no\n")
        rules_path = self._write_rules('[transforms]\nv = "boolean"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"a.csv": {"registry_version": "10", "v10_blob": True}}, fh)
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertNotIn("v10_blob", state["a.csv"])

    def test_regression_transform_error_leaves_no_report_or_cache(self):
        self._write_csv("a_ok.csv", "id,flag\n1,yes\n")
        self._write_csv("b_bad.csv", "id,flag\n2,invalid\n")
        rules_path = self._write_rules('[transforms]\nflag = "boolean"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_regression_unhandled_crash_leaves_no_report_or_cache(self):
        self._write_csv("a_ok.csv", "id,val\n1,ok\n")
        self._write_csv("b_boom.csv", "id,val\n2,boom\n")
        rules_path = self._write_rules('[transforms]\nval = "trim"\n')
        orig_apply = transforms.apply

        def exploding_apply(name, value):
            if value == "boom":
                raise RuntimeError("unexpected crash")
            return orig_apply(name, value)

        transforms.apply = exploding_apply
        try:
            with self.assertRaises(RuntimeError):
                reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        finally:
            transforms.apply = orig_apply
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_regression_older_registry_version_not_reused(self):
        csv_path = self._write_csv("a.csv", "id,name\n1,Alice\n")
        rules_path = self._write_rules('[transforms]\nname = "lower"\n')
        rules = reportgen.load_rules(rules_path)
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        stale_entry = {
            "digest": cache.file_digest(csv_path),
            "rows": 1,
            "generated_from": 1,
            "rules_fp": cache.rules_fingerprint(rules),
            "registry_version": "1",
            "summary": {
                "columns": {"name": {"non_empty": 1, "distinct": 1, "sample": ["STALE"]}},
                "skipped_rows": [],
            },
        }
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"a.csv": stale_entry}, fh)
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(
            report["files"]["a.csv"]["summary"]["columns"]["name"]["sample"],
            ["alice"],
        )
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_regression_generated_from_consistent_across_cached_runs(self):
        first = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        second = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(
            first["files"]["small_devices.csv"]["generated_from"], 1
        )
        self.assertEqual(
            second["files"]["small_devices.csv"]["generated_from"], 1
        )
        self.assertEqual(first, second)

    def test_regression_html_escapes_columns_and_samples(self):
        self._write_csv("x.csv", "a<b>c,val\n1,<script>&\n")
        rules_path = self._write_rules('[transforms]\nval = "trim"\n')
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as fh:
            html_out = fh.read()
        self.assertNotIn("<script>", html_out)
        self.assertNotIn("<b>", html_out)
        self.assertIn("a&lt;b&gt;c", html_out)
        self.assertIn("&lt;script&gt;&amp;", html_out)

    def test_regression_main_returns_nonzero_on_validation_error(self):
        self._write_csv("bad.csv", "id,flag\n1,nope\n")
        rules_path = self._write_rules('[transforms]\nflag = "boolean"\n')
        rc = reportgen.main([
            "--rules", rules_path,
            "--input", self.inp,
            "--output", self.out,
            "--cache", self.cache_path,
        ])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

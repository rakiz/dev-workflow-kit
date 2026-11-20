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
            self.assertIsInstance(val, float)
            self.assertEqual(val, 1.0)
        for raw in ("no", "NO", "No", "false", "FALSE", "False", " false "):
            val = transforms.apply("boolean", raw)
            self.assertIsInstance(val, float)
            self.assertEqual(val, 0.0)
        for bad in ("maybe", "1", "0", "", "y", "n"):
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
        self.rules_path = os.path.join(self.tmp, "rules.toml")

    def _write(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_future_top_level_schema_version_resets_and_rewrites_cache(self):
        self._write(os.path.join(self.inp, "a.csv"), "k,v\n1,2.5\n")
        self._write(self.rules_path, '[transforms]\nv = "round2"\n')
        self._write(
            self.cache_path,
            json.dumps({"version": 99, "entries": {"a.csv": {"bad": True}}}),
        )
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(set(state), {"a.csv"})
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_resets_and_rewrites_cache(self):
        self._write(os.path.join(self.inp, "a.csv"), "k,v\n1,yes\n")
        self._write(self.rules_path, '[transforms]\nv = "boolean"\n')
        self._write(
            self.cache_path,
            json.dumps({"a.csv": {"registry_version": "10", "schema": "future"}}),
        )
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_regression_transform_failure_emits_no_report_and_no_cache(self):
        self._write(os.path.join(self.inp, "a_good.csv"), "k,v\n1,10\n")
        self._write(os.path.join(self.inp, "b_bad.csv"), "k,v\n1,not-a-num\n")
        self._write(self.rules_path, '[transforms]\nv = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_regression_unhandled_transform_crash_emits_no_report_and_no_cache(self):
        self._write(os.path.join(self.inp, "a_good.csv"), "k,v\n1,10\n")
        self._write(os.path.join(self.inp, "b_crash.csv"), "k,v\n1,boom\n")
        self._write(self.rules_path, '[transforms]\nv = "trim"\n')
        orig_apply = transforms.apply

        def crashing_apply(name, value):
            if value == "boom":
                raise RuntimeError("unexpected crash")
            return orig_apply(name, value)

        transforms.apply = crashing_apply
        try:
            with self.assertRaises(RuntimeError):
                reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        finally:
            transforms.apply = orig_apply
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_regression_main_exits_nonzero_on_validation_error(self):
        self._write(os.path.join(self.inp, "bad.csv"), "k,flag\n1,maybe\n")
        self._write(self.rules_path, '[transforms]\nflag = "boolean"\n')
        with self.assertRaises(SystemExit) as ctx:
            reportgen.main([
                "--rules", self.rules_path,
                "--input", self.inp,
                "--output", self.out,
                "--cache", self.cache_path,
            ])
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_regression_older_registry_version_not_reused(self):
        csv_path = os.path.join(self.inp, "a.csv")
        self._write(csv_path, "k,v\n1,5\n")
        self._write(self.rules_path, '[transforms]\nv = "round2"\n')
        rules = reportgen.load_rules(self.rules_path)
        stale_entry = {
            "digest": cache.file_digest(csv_path),
            "rows": 999,
            "generated_from": 1,
            "rules_fp": cache.rules_fingerprint(rules),
            "registry_version": "1",
            "summary": {"columns": {}, "skipped_rows": []},
        }
        self._write(self.cache_path, json.dumps({"a.csv": stale_entry}))
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["a.csv"]["rows"], 1)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_regression_generated_from_matches_across_cold_and_cached_runs(self):
        first = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        second = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(
            first["files"]["small_devices.csv"]["generated_from"], 1)
        self.assertEqual(
            second["files"]["small_devices.csv"]["generated_from"], 1)

    def test_regression_html_escapes_markup(self):
        self._write(os.path.join(self.inp, "x.csv"), "a<b>,val\n1,<script>&\n")
        self._write(self.rules_path, '[transforms]\nval = "trim"\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), "r", encoding="utf-8") as fh:
            rendered = fh.read()
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;&amp;", rendered)
        self.assertIn("a&lt;b&gt;", rendered)

    def test_regression_cache_hit_skips_parsing(self):
        self._write(os.path.join(self.inp, "a.csv"), "k,v\n1,2\n")
        self._write(self.rules_path, '[transforms]\nv = "round2"\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        orig_load_rows = reportgen.load_rows

        def fail_if_called(path):
            raise AssertionError("load_rows should not be called on cache hit")

        reportgen.load_rows = fail_if_called
        try:
            report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        finally:
            reportgen.load_rows = orig_load_rows
        self.assertEqual(report["total_rows"], 1)


if __name__ == "__main__":
    unittest.main()

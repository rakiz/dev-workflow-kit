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
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_boolean_valid_values(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", " True "):
            res = transforms.apply("boolean", raw)
            self.assertEqual(res, 1.0)
            self.assertIsInstance(res, float)
        for raw in ("no", "NO", "No", "false", "FALSE", " False "):
            res = transforms.apply("boolean", raw)
            self.assertEqual(res, 0.0)
            self.assertIsInstance(res, float)

    def test_boolean_invalid_values(self):
        for bad in ("", "1", "0", "maybe", "y", "n", "t"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)

    def test_boolean_end_to_end(self):
        with open(os.path.join(self.inp, "flags.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,active\n1,Yes\n2,NO\n3,true\n4,False\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        col = report["files"]["flags.csv"]["summary"]["columns"]["active"]
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["numeric_sum"], 1.0)


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def _write_sample_input(self):
        with open(os.path.join(self.inp, "t.csv"), "w", encoding="utf-8") as fh:
            fh.write("item,flag\n1,yes\n2,no\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nitem = "round2"\nflag = "boolean"\n')
        return rules_path

    def test_future_top_level_version_treated_as_empty_and_rewritten(self):
        rules_path = self._write_sample_input()
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        future_ver = int(cache.REGISTRY_VERSION) + 1
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": future_ver, "files": {"t.csv": {"v2_only": True}}}, fh)

        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            rewritten = json.load(fh)
        self.assertEqual(set(rewritten), {"t.csv"})
        self.assertEqual(rewritten["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_numeric_compare_and_rewritten(self):
        rules_path = self._write_sample_input()
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"t.csv": {"registry_version": "10", "new_field": 123}}, fh)

        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            rewritten = json.load(fh)
        self.assertEqual(set(rewritten), {"t.csv"})
        self.assertEqual(rewritten["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_version_with_empty_input_dir_rewrites_valid_state(self):
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": 99}, fh)

        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 0)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {})

    def test_older_registry_version_entry_is_not_reused(self):
        rules_path = self._write_sample_input()
        rules = reportgen.load_rules(rules_path)
        digest = cache.file_digest(os.path.join(self.inp, "t.csv"))
        rules_fp = cache.rules_fingerprint(rules)
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({
                "t.csv": {
                    "digest": digest,
                    "rules_fp": rules_fp,
                    "registry_version": "1",
                    "rows": 999,
                    "generated_from": 2,
                    "summary": {"columns": {}, "skipped_rows": []},
                }
            }, fh)

        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            updated = json.load(fh)
        self.assertEqual(updated["t.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(updated["t.csv"]["rows"], 2)

    def test_generated_from_matches_between_cold_and_warm_cache(self):
        first = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        second = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(first, second)
        self.assertEqual(first["files"]["small_devices.csv"]["generated_from"], 1)


class InvariantAndRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-inv-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_transform_error_emits_no_report_and_no_cache(self):
        with open(os.path.join(self.inp, "a_good.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,flag\n1,yes\n")
        with open(os.path.join(self.inp, "b_bad.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,flag\n2,maybe\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

        res = reportgen.main([
            "--rules", rules_path,
            "--input", self.inp,
            "--output", self.out,
            "--cache", self.cache_path,
        ])
        self.assertIsNone(res)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unhandled_crash_in_transform_emits_no_report_and_no_cache(self):
        with open(os.path.join(self.inp, "a_good.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,flag\n1,yes\n")
        with open(os.path.join(self.inp, "b_crash.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,flag\n2,CRASH\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

        orig = transforms.REGISTRY["boolean"]

        def exploding(val):
            if val == "CRASH":
                raise RuntimeError("boom")
            return orig(val)

        transforms.REGISTRY["boolean"] = exploding
        try:
            with self.assertRaises(RuntimeError):
                reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        finally:
            transforms.REGISTRY["boolean"] = orig

        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_poisoned_cache_entry_with_skipped_rows_is_rejected(self):
        bad_csv = os.path.join(self.inp, "bad.csv")
        with open(bad_csv, "w", encoding="utf-8") as fh:
            fh.write("id,flag\n1,invalid\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

        rules = reportgen.load_rules(rules_path)
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({
                "bad.csv": {
                    "digest": cache.file_digest(bad_csv),
                    "rules_fp": cache.rules_fingerprint(rules),
                    "registry_version": cache.REGISTRY_VERSION,
                    "rows": 1,
                    "generated_from": 1,
                    "summary": {
                        "columns": {},
                        "skipped_rows": [{"row": 2, "column": "flag", "reason": "bad"}],
                    },
                }
            }, fh)

        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))

    def test_render_html_escapes_markup(self):
        with open(os.path.join(self.inp, "a<x>.csv"), "w", encoding="utf-8") as fh:
            fh.write("col&1\n<script>alert(1)</script>\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\n')

        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), "r", encoding="utf-8") as fh:
            rendered = fh.read()
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("col&amp;1", rendered)
        self.assertIn("a&lt;x&gt;.csv", rendered)


if __name__ == "__main__":
    unittest.main()

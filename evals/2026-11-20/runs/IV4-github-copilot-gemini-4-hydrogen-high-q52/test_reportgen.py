"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import builtins
import json
import os
import shutil
import subprocess
import sys
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
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True", " yes "):
            val = transforms.apply("boolean", raw)
            self.assertEqual(val, 1.0)
            self.assertIsInstance(val, float)
        for raw in ("no", "NO", "No", "false", "FALSE", "False", " false "):
            val = transforms.apply("boolean", raw)
            self.assertEqual(val, 0.0)
            self.assertIsInstance(val, float)

    def test_boolean_invalid_values(self):
        for raw in ("", "1", "0", "y", "n", "maybe", "truth"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,active\n1,YES\n2,no\n3,True\n4,FALSE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        report = reportgen.run(rules_path, inp, out, cache_path)
        col = report["files"]["flags.csv"]["summary"]["columns"]["active"]
        self.assertEqual(col["non_empty"], 4)
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["numeric_sum"], 1.0)


class CacheHygieneAndRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")

    def _write_csv(self, name, content):
        with open(os.path.join(self.inp, name), "w", encoding="utf-8") as fh:
            fh.write(content)

    def _write_rules(self, content):
        with open(self.rules_path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_future_top_level_version_cache_rewritten(self):
        self._write_csv("a.csv", "item\n1\n2\n")
        self._write_rules('[transforms]\nitem = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        future_payloads = [
            {"version": "99", "entries": {"a.csv": {"digest": "bogus"}}},
            {"version": 10, "a.csv": {"digest": "bogus"}},
            {"schema_version": "999", "files": []},
            ["unexpected-list-schema"],
        ]
        for payload in future_payloads:
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
            self.assertEqual(report["total_rows"], 2)
            state = cache.load_state(self.cache_path)
            self.assertEqual(set(state), {"a.csv"})
            self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_cache_rewritten(self):
        self._write_csv("a.csv", "item\n1\n")
        self._write_rules('[transforms]\nitem = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        digest = cache.file_digest(os.path.join(self.inp, "a.csv"))
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({
                "a.csv": {
                    "digest": digest,
                    "rules_fp": cache.rules_fingerprint({"item": "round2"}),
                    "registry_version": "99",
                    "rows": 999,
                    "generated_from": 1,
                    "summary": {"columns": {}, "skipped_rows": []},
                }
            }, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["a.csv"]["rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(state["a.csv"]["rows"], 1)

    def test_regression_older_registry_version_not_reused(self):
        self._write_csv("a.csv", "item\n1\n")
        self._write_rules('[transforms]\nitem = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        digest = cache.file_digest(os.path.join(self.inp, "a.csv"))
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({
                "a.csv": {
                    "digest": digest,
                    "rules_fp": cache.rules_fingerprint({"item": "round2"}),
                    "registry_version": "1",
                    "rows": 999,
                    "generated_from": 1,
                    "summary": {"columns": {}, "skipped_rows": []},
                }
            }, fh)
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["a.csv"]["rows"], 1)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["a.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_regression_rules_file_read_at_most_once(self):
        real_open = builtins.open
        target = os.path.abspath(RULES)
        reads = []

        def counting_open(file, *args, **kwargs):
            if os.path.abspath(str(file)) == target:
                reads.append(file)
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=counting_open):
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(len(reads), 1)

    def test_regression_generated_from_matches_across_cold_and_warm_cache(self):
        cold = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        warm = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(cold, warm)
        self.assertEqual(cold["files"]["small_devices.csv"]["generated_from"], 1)
        self.assertEqual(warm["files"]["small_devices.csv"]["generated_from"], 1)

    def test_regression_html_escapes_names_columns_and_samples(self):
        self._write_csv("a<x>.csv", "col&1\n<script>alert(1)</script>\n")
        self._write_rules('[transforms]\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as fh:
            html_out = fh.read()
        self.assertNotIn("<x>", html_out)
        self.assertNotIn("<script>", html_out)
        self.assertIn("a&lt;x&gt;.csv", html_out)
        self.assertIn("col&amp;1", html_out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_out)

    def test_regression_transform_error_leaves_outputs_and_cache_intact_and_exits_1(self):
        self._write_csv("a.csv", "num\n10\n")
        self._write_csv("b.csv", "num\n20\n")
        self._write_rules('[transforms]\nnum = "round2"\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)

        json_path = os.path.join(self.out, "report.json")
        html_path = os.path.join(self.out, "report.html")
        with open(json_path, "rb") as fh:
            good_json = fh.read()
        with open(html_path, "rb") as fh:
            good_html = fh.read()
        with open(self.cache_path, "rb") as fh:
            good_cache = fh.read()

        # Modify a.csv (valid) and b.csv (invalid transform); a.csv must NOT leak to cache.
        self._write_csv("a.csv", "num\n11\n")
        self._write_csv("b.csv", "num\nnot-a-number\n")

        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path,
             "--input", self.inp,
             "--output", self.out,
             "--cache", self.cache_path],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        with open(json_path, "rb") as fh:
            self.assertEqual(fh.read(), good_json)
        with open(html_path, "rb") as fh:
            self.assertEqual(fh.read(), good_html)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), good_cache)
        self.assertEqual(sorted(os.listdir(self.out)), ["report.html", "report.json"])
        self.assertEqual(os.listdir(os.path.dirname(self.cache_path)), ["state.json"])

    def test_regression_unhandled_transform_crash_leaves_outputs_and_cache_intact(self):
        self._write_csv("a.csv", "num\n10\n")
        self._write_csv("b.csv", "num\n20\n")
        self._write_rules('[transforms]\nnum = "round2"\n')
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)

        json_path = os.path.join(self.out, "report.json")
        html_path = os.path.join(self.out, "report.html")
        with open(json_path, "rb") as fh:
            good_json = fh.read()
        with open(html_path, "rb") as fh:
            good_html = fh.read()
        with open(self.cache_path, "rb") as fh:
            good_cache = fh.read()

        self._write_csv("a.csv", "num\n11\n")
        self._write_csv("b.csv", "num\n22\n")

        def crash_on_22(val):
            if val == "22":
                raise ZeroDivisionError("boom")
            return float(val)

        with mock.patch.dict(transforms.REGISTRY, {"round2": crash_on_22}):
            with self.assertRaises(SystemExit) as cm:
                reportgen.main([
                    "--rules", self.rules_path,
                    "--input", self.inp,
                    "--output", self.out,
                    "--cache", self.cache_path,
                ])
        self.assertEqual(cm.exception.code, 1)
        with open(json_path, "rb") as fh:
            self.assertEqual(fh.read(), good_json)
        with open(html_path, "rb") as fh:
            self.assertEqual(fh.read(), good_html)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), good_cache)

    def test_regression_failure_with_no_prior_outputs_emits_nothing(self):
        self._write_csv("bad.csv", "flag\nmaybe\n")
        self._write_rules('[transforms]\nflag = "boolean"\n')
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path,
             "--input", self.inp,
             "--output", self.out,
             "--cache", self.cache_path],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))


if __name__ == "__main__":
    unittest.main()

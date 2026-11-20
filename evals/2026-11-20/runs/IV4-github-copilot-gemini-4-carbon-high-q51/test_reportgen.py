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


class BooleanAndCacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-feat-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)

    def test_boolean_transform_values_and_errors(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True", " yes "):
            val = transforms.apply("boolean", raw)
            self.assertEqual(val, 1.0)
            self.assertIsInstance(val, float)
        for raw in ("no", "NO", "No", "false", "FALSE", "False", " false\n"):
            val = transforms.apply("boolean", raw)
            self.assertEqual(val, 0.0)
            self.assertIsInstance(val, float)
        for bad in ("", "   ", "1", "0", "y", "n", "t", "f", "maybe"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)

    def test_boolean_rule_end_to_end(self):
        with open(os.path.join(self.inp, "flags.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,active\n1,yes\n2,TRUE\n3,no\n4,False\n5,Yes\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        active = report["files"]["flags.csv"]["summary"]["columns"]["active"]
        self.assertEqual(active["non_empty"], 5)
        self.assertEqual(active["distinct"], 2)
        self.assertEqual(active["sample"], [0.0, 1.0])
        self.assertEqual(active["numeric_sum"], 3.0)

    def test_future_schema_envelope_treated_as_empty_and_rewritten(self):
        with open(os.path.join(self.inp, "t.csv"), "w", encoding="utf-8") as fh:
            fh.write("item,label\n1,alpha\n2,beta\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": int(cache.REGISTRY_VERSION) + 1,
                       "entries": {"t.csv": {"incompatible": True}}}, fh)
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            rewritten = json.load(fh)
        self.assertEqual(set(rewritten), {"t.csv"})
        self.assertEqual(rewritten["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_including_multidigit_treated_as_empty(self):
        with open(os.path.join(self.inp, "t.csv"), "w", encoding="utf-8") as fh:
            fh.write("item\n4\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        future_ver = str(int(cache.REGISTRY_VERSION) + 8)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({
                "t.csv": {"registry_version": future_ver, "blob": "v-future"},
                "stale_future.csv": {"registry_version": future_ver},
            }, fh)
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            rewritten = json.load(fh)
        self.assertEqual(set(rewritten), {"t.csv"})
        self.assertEqual(rewritten["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class DefectRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)

    def test_regression_html_escapes_markup_in_names_headers_and_samples(self):
        with open(os.path.join(self.inp, "a&b.csv"), "w", encoding="utf-8") as fh:
            fh.write("col<1>,label\nx,red <b> & bold\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write("[transforms]\n")
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), "r", encoding="utf-8") as fh:
            rendered = fh.read()
        self.assertNotIn("<b>", rendered)
        self.assertNotIn("<td>col<1></td>", rendered)
        self.assertIn("a&amp;b.csv", rendered)
        self.assertIn("col&lt;1&gt;", rendered)
        self.assertIn("red &lt;b&gt; &amp; bold", rendered)

    def test_regression_rules_file_read_at_most_once_per_run(self):
        import builtins
        rules_abs = os.path.abspath(RULES)
        reads = []
        real_open = builtins.open

        def counting_open(file, mode="r", *args, **kwargs):
            if "r" in mode and os.path.abspath(str(file)) == rules_abs:
                reads.append(file)
            return real_open(file, mode, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        finally:
            builtins.open = real_open
        self.assertEqual(len(reads), 1)

    def test_regression_transform_error_exits_1_and_preserves_outputs_and_cache(self):
        import subprocess
        import sys

        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\namount = "round2"\n')

        # 1) Failing first run on clean paths emits nothing new and exits 1.
        clean_out = os.path.join(self.tmp, "clean_out")
        clean_cache = os.path.join(self.tmp, "clean_cache", "state.json")
        with open(os.path.join(self.inp, "b.csv"), "w", encoding="utf-8") as fh:
            fh.write("amount\nnot-a-number\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", rules_path, "--input", self.inp,
             "--output", clean_out, "--cache", clean_cache],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertFalse(os.path.exists(clean_out))
        self.assertFalse(os.path.exists(os.path.dirname(clean_cache)))

        # 2) Good run establishes baseline report.json, report.html, and cache.
        with open(os.path.join(self.inp, "a.csv"), "w", encoding="utf-8") as fh:
            fh.write("amount\n10\n")
        with open(os.path.join(self.inp, "b.csv"), "w", encoding="utf-8") as fh:
            fh.write("amount\n20\n")
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            good_json = fh.read()
        with open(os.path.join(self.out, "report.html"), "rb") as fh:
            good_html = fh.read()
        with open(self.cache_path, "rb") as fh:
            good_cache = fh.read()

        # 3) Modify both a.csv (valid) and b.csv (invalid): nothing may change.
        with open(os.path.join(self.inp, "a.csv"), "w", encoding="utf-8") as fh:
            fh.write("amount\n99\n")
        with open(os.path.join(self.inp, "b.csv"), "w", encoding="utf-8") as fh:
            fh.write("amount\nbad\n")
        proc2 = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True)
        self.assertEqual(proc2.returncode, 1)
        self.assertEqual(proc2.stdout, "")
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            self.assertEqual(fh.read(), good_json)
        with open(os.path.join(self.out, "report.html"), "rb") as fh:
            self.assertEqual(fh.read(), good_html)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), good_cache)

    def test_regression_unhandled_transform_crash_preserves_outputs_and_cache(self):
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nval = "trim"\n')
        with open(os.path.join(self.inp, "a.csv"), "w", encoding="utf-8") as fh:
            fh.write("val\nok\n")
        with open(os.path.join(self.inp, "b.csv"), "w", encoding="utf-8") as fh:
            fh.write("val\nok2\n")
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            good_json = fh.read()
        with open(os.path.join(self.out, "report.html"), "rb") as fh:
            good_html = fh.read()
        with open(self.cache_path, "rb") as fh:
            good_cache = fh.read()

        def crashing_transform(v):
            if v == "explode":
                raise RuntimeError("boom")
            return v.strip()

        orig = transforms.REGISTRY["trim"]
        transforms.REGISTRY["trim"] = crashing_transform
        try:
            with open(os.path.join(self.inp, "a.csv"), "w", encoding="utf-8") as fh:
                fh.write("val\nchanged\n")
            with open(os.path.join(self.inp, "b.csv"), "w", encoding="utf-8") as fh:
                fh.write("val\nexplode\n")
            with self.assertRaises(SystemExit) as cm:
                reportgen.main(["--rules", rules_path, "--input", self.inp,
                                "--output", self.out, "--cache", self.cache_path])
            self.assertEqual(cm.exception.code, 1)
        finally:
            transforms.REGISTRY["trim"] = orig

        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            self.assertEqual(fh.read(), good_json)
        with open(os.path.join(self.out, "report.html"), "rb") as fh:
            self.assertEqual(fh.read(), good_html)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), good_cache)

    def test_regression_older_registry_version_not_reused(self):
        csv_path = os.path.join(self.inp, "t.csv")
        with open(csv_path, "w", encoding="utf-8") as fh:
            fh.write("item\n5\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        rules = reportgen.load_rules(rules_path)
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({
                "t.csv": {
                    "digest": cache.file_digest(csv_path),
                    "rows": 1,
                    "generated_from": 1,
                    "rules_fp": cache.rules_fingerprint(rules),
                    "registry_version": "1",
                    "summary": {
                        "columns": {"item": {"non_empty": 1, "distinct": 1,
                                             "sample": [999.0],
                                             "numeric_sum": 999.0}},
                        "skipped_rows": [],
                    },
                }
            }, fh)
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        item = report["files"]["t.csv"]["summary"]["columns"]["item"]
        self.assertEqual(item["numeric_sum"], 5.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_regression_generated_from_matches_between_fresh_and_cached_runs(self):
        r1 = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            json1 = fh.read()
        r2 = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            json2 = fh.read()
        self.assertEqual(r1["files"]["small_devices.csv"]["generated_from"], 1)
        self.assertEqual(r1, r2)
        self.assertEqual(json1, json2)

    def test_regression_numeric_sum_counts_duplicate_values(self):
        with open(os.path.join(self.inp, "dup.csv"), "w", encoding="utf-8") as fh:
            fh.write("amount\n$10.00\n$10.00\n$5.00\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\namount = "currency_amount"\n')
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        col = report["files"]["dup.csv"]["summary"]["columns"]["amount"]
        self.assertEqual(col["distinct"], 2)
        self.assertEqual(col["numeric_sum"], 25.0)

    def test_regression_numeric_sample_sorted_numerically(self):
        with open(os.path.join(self.inp, "nums.csv"), "w", encoding="utf-8") as fh:
            fh.write("val\n120.5\n89.99\n40.0\n25.1\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        col = report["files"]["nums.csv"]["summary"]["columns"]["val"]
        self.assertEqual(col["sample"], [25.1, 40.0, 89.99])

    def test_regression_nonfinite_numbers_and_invalid_calendar_dates_rejected(self):
        for bad_num in ("nan", "NaN", "inf", "-inf"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("round2", bad_num)
            with self.assertRaises(transforms.TransformError):
                transforms.apply("currency_amount", bad_num)
        for bad_date in ("13/45/2026", "02/30/2026", "00/10/2026", "01/15/ 202"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("date_iso", bad_date)


if __name__ == "__main__":
    unittest.main()

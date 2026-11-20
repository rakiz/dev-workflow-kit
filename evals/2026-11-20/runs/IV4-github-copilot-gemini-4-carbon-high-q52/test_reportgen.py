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


class FeatureAndRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _read_bytes(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_boolean_transform_values_and_errors(self):
        for token in ("yes", "YES", "Yes", "true", "TRUE", "True", " yes "):
            val = transforms.apply("boolean", token)
            self.assertIs(type(val), float)
            self.assertEqual(val, 1.0)
        for token in ("no", "NO", "No", "false", "FALSE", "False", " false "):
            val = transforms.apply("boolean", token)
            self.assertIs(type(val), float)
            self.assertEqual(val, 0.0)
        for bad in ("1", "0", "y", "n", "t", "f", "maybe", ""):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)

    def test_boolean_end_to_end_summary(self):
        self._write(os.path.join(self.inp, "flags.csv"),
                    "id,active\n1,yes\n2,TRUE\n3,no\n4,False\n5,Yes\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\nactive = "boolean"\n')
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        active = report["files"]["flags.csv"]["summary"]["columns"]["active"]
        self.assertEqual(active["non_empty"], 5)
        self.assertEqual(active["distinct"], 2)
        self.assertEqual(active["sample"], [0.0, 1.0])
        self.assertEqual(active["numeric_sum"], 3.0)

    def test_future_schema_version_top_level_treated_as_empty_and_rewritten(self):
        self._write(os.path.join(self.inp, "t.csv"), "a,b\n1,x\n2,y\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\na = "round2"\n')
        for future_ver in (99, "10", str(int(cache.REGISTRY_VERSION) + 1)):
            self._write(
                self.cache_path,
                json.dumps({"version": future_ver, "files": ["incompatible"]}))
            report = reportgen.run(rules, self.inp, self.out, self.cache_path)
            self.assertEqual(report["total_rows"], 2)
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                rewritten = json.load(fh)
            self.assertEqual(set(rewritten), {"t.csv"})
            self.assertEqual(
                rewritten["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_schema_version_per_entry_treated_as_empty_and_rewritten(self):
        csv_path = self._write(os.path.join(self.inp, "t.csv"), "a\n5\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\na = "round2"\n')
        rules_dict = reportgen.load_rules(rules)
        future_ver = str(int(cache.REGISTRY_VERSION) + 1)
        self._write(self.cache_path, json.dumps({
            "t.csv": {
                "digest": cache.file_digest(csv_path),
                "rules_fp": cache.rules_fingerprint(rules_dict),
                "registry_version": future_ver,
            },
            "stale_future.csv": {"registry_version": future_ver},
        }))
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertEqual(
            report["files"]["t.csv"]["summary"]["columns"]["a"]["numeric_sum"],
            5.0)
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            rewritten = json.load(fh)
        self.assertEqual(set(rewritten), {"t.csv"})
        self.assertEqual(
            rewritten["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_older_registry_version_entry_not_reused(self):
        csv_path = self._write(os.path.join(self.inp, "t.csv"), "a\n7\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\na = "round2"\n')
        rules_dict = reportgen.load_rules(rules)
        self._write(self.cache_path, json.dumps({
            "t.csv": {
                "digest": cache.file_digest(csv_path),
                "rows": 999,
                "generated_from": 1,
                "rules_fp": cache.rules_fingerprint(rules_dict),
                "registry_version": "1",
                "summary": {"columns": {"a": {"non_empty": 1, "distinct": 1,
                                              "sample": [0.0], "numeric_sum": 0.0}},
                            "skipped_rows": []},
            }
        }))
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        self.assertEqual(
            report["files"]["t.csv"]["summary"]["columns"]["a"]["numeric_sum"],
            7.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_rules_file_read_at_most_once_per_run(self):
        import builtins
        from unittest import mock

        for name in ("a.csv", "b.csv", "c.csv"):
            self._write(os.path.join(self.inp, name), "x\n1\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\nx = "round2"\n')
        real_open = builtins.open
        rules_abs = os.path.abspath(rules)
        reads = []

        def counting_open(file, *args, **kwargs):
            if os.path.abspath(str(file)) == rules_abs:
                reads.append(file)
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=counting_open):
            reportgen.run(rules, self.inp, self.out, self.cache_path)
        self.assertEqual(len(reads), 1)

    def test_html_escapes_markup_in_names_headers_and_samples(self):
        self._write(os.path.join(self.inp, "a&b.csv"),
                    "col<1>,label\nx,hi <script> & \"q\"\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\n')
        reportgen.run(rules, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), "r", encoding="utf-8") as fh:
            rendered = fh.read()
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("col<1>", rendered)
        self.assertIn("a&amp;b.csv", rendered)
        self.assertIn("col&lt;1&gt;", rendered)
        self.assertIn("&lt;script&gt; &amp;", rendered)

    def test_failed_transform_on_fresh_dir_exits_1_and_emits_nothing(self):
        import subprocess
        import sys

        self._write(os.path.join(self.inp, "bad.csv"), "amount\nnot-a-number\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\namount = "round2"\n')
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", rules, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_transform_preserves_prior_outputs_and_cache_byte_for_byte(self):
        import io
        import subprocess
        import sys
        from unittest import mock

        self._write(os.path.join(self.inp, "a.csv"), "val\n10\n")
        self._write(os.path.join(self.inp, "b.csv"), "val\n20\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\nval = "round2"\n')
        reportgen.run(rules, self.inp, self.out, self.cache_path)

        json_path = os.path.join(self.out, "report.json")
        html_path = os.path.join(self.out, "report.html")
        good_json = self._read_bytes(json_path)
        good_html = self._read_bytes(html_path)
        good_cache = self._read_bytes(self.cache_path)

        # Modify both files so a.csv succeeds first and b.csv fails TransformError.
        self._write(os.path.join(self.inp, "a.csv"), "val\n30\n")
        self._write(os.path.join(self.inp, "b.csv"), "val\noops\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", rules, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(self._read_bytes(json_path), good_json)
        self.assertEqual(self._read_bytes(html_path), good_html)
        self.assertEqual(self._read_bytes(self.cache_path), good_cache)

        # Also test an unhandled crash and a None-returning transform in-process.
        self._write(os.path.join(self.inp, "b.csv"), "val\n40\n")
        crash_rules = self._write(os.path.join(self.tmp, "crash.toml"),
                                  '[transforms]\nval = "boom"\n')
        for fn in (lambda v: 1 / 0, lambda v: None):
            with mock.patch.dict(transforms.REGISTRY, {"boom": fn}):
                stdout_buf = io.StringIO()
                stderr_buf = io.StringIO()
                with mock.patch("sys.stdout", stdout_buf), \
                     mock.patch("sys.stderr", stderr_buf):
                    with self.assertRaises(SystemExit) as cm:
                        reportgen.main(["--rules", crash_rules,
                                        "--input", self.inp,
                                        "--output", self.out,
                                        "--cache", self.cache_path])
                self.assertEqual(cm.exception.code, 1)
                self.assertEqual(stdout_buf.getvalue(), "")
                self.assertEqual(self._read_bytes(json_path), good_json)
                self.assertEqual(self._read_bytes(html_path), good_html)
                self.assertEqual(self._read_bytes(self.cache_path), good_cache)

    def test_generated_from_consistent_across_cold_and_cached_runs(self):
        r1 = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        json1 = self._read_bytes(os.path.join(self.out, "report.json"))
        r2 = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        json2 = self._read_bytes(os.path.join(self.out, "report.json"))
        self.assertEqual(r1["files"]["small_devices.csv"]["generated_from"], 1)
        self.assertEqual(r1, r2)
        self.assertEqual(json1, json2)

    def test_numeric_sum_and_sample_order_regression(self):
        self._write(os.path.join(self.inp, "nums.csv"),
                    "amt\n$100.00\n$2.00\n$20.00\n$2.00\n$3.00\n")
        rules = self._write(os.path.join(self.tmp, "rules.toml"),
                            '[transforms]\namt = "currency_amount"\n')
        report = reportgen.run(rules, self.inp, self.out, self.cache_path)
        col = report["files"]["nums.csv"]["summary"]["columns"]["amt"]
        self.assertEqual(col["distinct"], 4)
        self.assertEqual(col["sample"], [2.0, 3.0, 20.0])
        self.assertEqual(col["numeric_sum"], 127.0)

    def test_non_finite_numbers_and_invalid_calendar_dates_rejected(self):
        for bad_num in ("nan", "NaN", "inf", "-inf"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("currency_amount", bad_num)
            with self.assertRaises(transforms.TransformError):
                transforms.apply("round2", bad_num)
        for bad_date in ("02/30/2026", "13/01/2026", "00/10/2026"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("date_iso", bad_date)


if __name__ == "__main__":
    unittest.main()

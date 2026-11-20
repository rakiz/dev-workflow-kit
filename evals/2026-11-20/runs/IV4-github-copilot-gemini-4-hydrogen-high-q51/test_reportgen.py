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
    def test_boolean_valid_values_case_insensitive(self):
        for val in ("yes", "YES", "Yes", " true ", "TRUE", "True"):
            res = transforms.apply("boolean", val)
            self.assertIsInstance(res, float)
            self.assertEqual(res, 1.0)
        for val in ("no", "NO", "No", " false ", "FALSE", "False"):
            res = transforms.apply("boolean", val)
            self.assertIsInstance(res, float)
            self.assertEqual(res, 0.0)

    def test_boolean_invalid_values_raise_transform_error(self):
        for val in ("", "   ", "1", "0", "y", "n", "maybe", "truthy"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", val)

    def test_boolean_end_to_end_numeric_sum(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("id,active\n1,YES\n2,no\n3,True\n4,FALSE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        report = reportgen.run(rules_path, inp, out, cache_path)
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["active"]["distinct"], 2)
        self.assertEqual(cols["active"]["sample"], [0.0, 1.0])
        self.assertEqual(cols["active"]["numeric_sum"], 1.0)


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)

    def test_future_schema_top_level_version_resets_and_rewrites(self):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,val\na,1\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({"version": "10", "entries": {"t.csv": {"unexpected": 1}}}, fh)

        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        with open(self.cache_path, "r") as fh:
            state = json.load(fh)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_schema_entry_version_resets_and_rewrites(self):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,val\na,1\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({"t.csv": {"registry_version": "99", "blob": [1, 2]},
                       "stale.csv": {"registry_version": "99"}}, fh)

        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(self.cache_path, "r") as fh:
            state = json.load(fh)
        self.assertEqual(set(state), {"t.csv"})

    def test_html_escaping_in_columns_and_samples(self):
        with open(os.path.join(self.inp, "xss.csv"), "w") as fh:
            fh.write("col<1>,label\nv1,<script>alert(1)</script>\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nlabel = "trim"\n')
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), "r") as fh:
            html_out = fh.read()
        self.assertNotIn("<script>", html_out)
        self.assertNotIn("<1>", html_out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_out)
        self.assertIn("col&lt;1&gt;", html_out)

    def test_transform_failure_exits_1_and_leaves_outputs_and_cache_intact(self):
        import subprocess
        import sys

        csv1 = os.path.join(self.inp, "a_good.csv")
        with open(csv1, "w") as fh:
            fh.write("item,val\nx,1.23\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')

        cmd = [sys.executable, os.path.join(BASE, "reportgen.py"),
               "--rules", rules_path, "--input", self.inp,
               "--output", self.out, "--cache", self.cache_path]
        ok = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)

        html_path = os.path.join(self.out, "report.html")
        json_path = os.path.join(self.out, "report.json")
        with open(html_path, "rb") as fh:
            before_html = fh.read()
        with open(json_path, "rb") as fh:
            before_json = fh.read()
        with open(self.cache_path, "rb") as fh:
            before_cache = fh.read()

        # Modify a_good (valid) and add b_bad (invalid cell)
        with open(csv1, "w") as fh:
            fh.write("item,val\nx,9.99\n")
        with open(os.path.join(self.inp, "b_bad.csv"), "w") as fh:
            fh.write("item,val\ny,not-a-number\n")

        bad = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)

        with open(html_path, "rb") as fh:
            self.assertEqual(fh.read(), before_html)
        with open(json_path, "rb") as fh:
            self.assertEqual(fh.read(), before_json)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), before_cache)

    def test_unhandled_transform_crash_exits_1_and_leaves_outputs_intact(self):
        import subprocess
        import sys

        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item,val\nx,1.23\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')

        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        html_path = os.path.join(self.out, "report.html")
        json_path = os.path.join(self.out, "report.json")
        with open(html_path, "rb") as fh:
            before_html = fh.read()
        with open(json_path, "rb") as fh:
            before_json = fh.read()
        with open(self.cache_path, "rb") as fh:
            before_cache = fh.read()

        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item,val\nx,2.34\n")

        script = (
            "import sys, transforms, reportgen; "
            "transforms.REGISTRY['round2'] = lambda v: (_ for _ in ()).throw(RuntimeError('boom')); "
            "reportgen.main(['--rules', sys.argv[1], '--input', sys.argv[2], "
            "'--output', sys.argv[3], '--cache', sys.argv[4]])"
        )
        res = subprocess.run(
            [sys.executable, "-c", script, rules_path, self.inp, self.out, self.cache_path],
            cwd=BASE, capture_output=True, text=True
        )
        self.assertEqual(res.returncode, 1)

        with open(html_path, "rb") as fh:
            self.assertEqual(fh.read(), before_html)
        with open(json_path, "rb") as fh:
            self.assertEqual(fh.read(), before_json)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), before_cache)

    def test_rules_file_read_at_most_once_per_run(self):
        import builtins
        from unittest import mock

        real_open = builtins.open
        rules_abs = os.path.abspath(RULES)
        read_count = 0

        def counting_open(file, *args, **kwargs):
            nonlocal read_count
            if isinstance(file, (str, bytes, os.PathLike)) and os.path.abspath(os.fspath(file)) == rules_abs:
                read_count += 1
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=counting_open):
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

        self.assertEqual(read_count, 1)

    def test_older_registry_version_never_reused(self):
        csv_path = os.path.join(self.inp, "t.csv")
        with open(csv_path, "w") as fh:
            fh.write("item,val\na,1\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nval = "round2"\n')

        rules = reportgen.load_rules(rules_path)
        rules_fp = cache.rules_fingerprint(rules)
        digest = cache.file_digest(csv_path)
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({
                "t.csv": {
                    "digest": digest,
                    "rows": 999,
                    "generated_from": 999,
                    "rules_fp": rules_fp,
                    "registry_version": "1",
                    "summary": {"columns": {}, "skipped_rows": []},
                }
            }, fh)

        report = reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)
        self.assertEqual(report["files"]["t.csv"]["generated_from"], 1)

    def test_generated_from_consistent_across_cache_hit(self):
        first = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        second = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(
            first["files"]["small_devices.csv"]["generated_from"],
            second["files"]["small_devices.csv"]["generated_from"],
        )
        self.assertEqual(first["files"]["small_devices.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()

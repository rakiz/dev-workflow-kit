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

    def test_boolean(self):
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            val = transforms.apply("boolean", raw)
            self.assertEqual(val, 1.0)
            self.assertIsInstance(val, float)
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            val = transforms.apply("boolean", raw)
            self.assertEqual(val, 0.0)
            self.assertIsInstance(val, float)
        for bad in ("1", "0", "maybe", "", "y", "n"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", bad)


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

    def test_future_schema_version_cache_rewritten(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": "99", "small_devices.csv": {"version": "99"}}, fh)
        self.assertEqual(cache.load_state(self.cache_path), {})
        self.run_tool()
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_future_entry_registry_version_cache_rewritten(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"small_devices.csv": {"registry_version": "99"}}, fh)
        self.run_tool()
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertEqual(
            state["small_devices.csv"]["registry_version"],
            cache.REGISTRY_VERSION)

    def test_cached_run_preserves_generated_from_and_checks_registry_version(self):
        first = self.run_tool()
        second = self.run_tool()
        self.assertEqual(first, second)
        self.assertEqual(
            first["files"]["small_devices.csv"]["generated_from"],
            second["files"]["small_devices.csv"]["generated_from"])


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)

    def test_rules_file_read_at_most_once_per_run(self):
        reads = []
        orig_open = open

        def counting_open(file, *args, **kwargs):
            if os.path.abspath(str(file)) == os.path.abspath(RULES):
                reads.append(file)
            return orig_open(file, *args, **kwargs)

        import builtins
        builtins.open = counting_open
        try:
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        finally:
            builtins.open = orig_open
        self.assertEqual(len(reads), 1)

    def test_transform_failure_on_fresh_run_emits_nothing_and_exits_1(self):
        with open(os.path.join(self.inp, "a.csv"), "w", encoding="utf-8") as fh:
            fh.write("flag\nyes\n")
        with open(os.path.join(self.inp, "b.csv"), "w", encoding="utf-8") as fh:
            fh.write("flag\nnot_a_bool\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        with self.assertRaises(SystemExit) as ctx:
            reportgen.main([
                "--rules", rules_path,
                "--input", self.inp,
                "--output", self.out,
                "--cache", self.cache_path,
            ])
        self.assertEqual(ctx.exception.code, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_transform_failure_preserves_previous_report_and_cache_bytes(self):
        csv_path = os.path.join(self.inp, "data.csv")
        with open(csv_path, "w", encoding="utf-8") as fh:
            fh.write("flag\nyes\nno\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        reportgen.main([
            "--rules", rules_path,
            "--input", self.inp,
            "--output", self.out,
            "--cache", self.cache_path,
        ])
        json_path = os.path.join(self.out, "report.json")
        html_path = os.path.join(self.out, "report.html")
        with open(json_path, "rb") as fh:
            good_json = fh.read()
        with open(html_path, "rb") as fh:
            good_html = fh.read()
        with open(self.cache_path, "rb") as fh:
            good_cache = fh.read()

        with open(csv_path, "w", encoding="utf-8") as fh:
            fh.write("flag\ninvalid_bool\n")
        with self.assertRaises(SystemExit) as ctx:
            reportgen.main([
                "--rules", rules_path,
                "--input", self.inp,
                "--output", self.out,
                "--cache", self.cache_path,
            ])
        self.assertEqual(ctx.exception.code, 1)
        with open(json_path, "rb") as fh:
            self.assertEqual(fh.read(), good_json)
        with open(html_path, "rb") as fh:
            self.assertEqual(fh.read(), good_html)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), good_cache)

    def test_render_html_escapes_special_characters(self):
        with open(os.path.join(self.inp, "labels.csv"), "w", encoding="utf-8") as fh:
            fh.write("item,label\ni1,red <b> & bold\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nitem = "trim"\n')
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), "r", encoding="utf-8") as fh:
            rendered = fh.read()
        self.assertNotIn("<b>", rendered)
        self.assertIn("red &lt;b&gt; &amp; bold", rendered)


if __name__ == "__main__":
    unittest.main()

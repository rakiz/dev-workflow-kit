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

    def test_boolean_transform(self):
        for val in ("yes", "YES", "Yes", "true", "TRUE", "True", " true "):
            res = transforms.apply("boolean", val)
            self.assertEqual(res, 1.0)
            self.assertIsInstance(res, float)
        for val in ("no", "NO", "No", "false", "FALSE", "False", " no "):
            res = transforms.apply("boolean", val)
            self.assertEqual(res, 0.0)
            self.assertIsInstance(res, float)
        for bad in ("1", "0", "y", "n", "", "maybe"):
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

    def test_future_schema_version_in_cache_rewrites_valid_state(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump({"version": 99, "small_transactions.csv": {"registry_version": "99"}}, fh)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_older_registry_version_entry_not_reused(self):
        self.run_tool()
        with open(self.cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["small_transactions.csv"]["registry_version"] = "1"
        data["small_transactions.csv"]["rows"] = 999
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        report = self.run_tool()
        self.assertEqual(report["files"]["small_transactions.csv"]["rows"], 4)

    def test_generated_from_consistent_across_cold_and_warm_cache(self):
        r1 = self.run_tool()
        r2 = self.run_tool()
        self.assertEqual(r1, r2)
        self.assertEqual(r1["files"]["small_devices.csv"]["generated_from"], 1)


class InvariantAndDefectRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-inv-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)

    def test_rules_file_read_at_most_once_per_run(self):
        import builtins
        real_open = builtins.open
        rules_reads = []
        rules_abs = os.path.abspath(RULES)

        def counting_open(file, *args, **kwargs):
            if os.path.abspath(str(file)) == rules_abs:
                rules_reads.append(file)
            return real_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        finally:
            builtins.open = real_open
        self.assertEqual(len(rules_reads), 1)

    def test_html_escapes_special_characters(self):
        with open(os.path.join(self.inp, "labels.csv"), "w", encoding="utf-8") as fh:
            fh.write("item,label\ni1,red <b> & bold\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nitem = "trim"\n')
        reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html"), "r", encoding="utf-8") as fh:
            html_text = fh.read()
        self.assertNotIn("<b>", html_text)
        self.assertIn("red &lt;b&gt; &amp; bold", html_text)

    def test_transform_failure_exits_1_and_preserves_previous_outputs_and_cache(self):
        csv_a = os.path.join(self.inp, "a.csv")
        csv_b = os.path.join(self.inp, "b.csv")
        with open(csv_a, "w", encoding="utf-8") as fh:
            fh.write("flag,val\nyes,10\n")
        with open(csv_b, "w", encoding="utf-8") as fh:
            fh.write("flag,val\nno,20\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\nval = "round2"\n')

        # First valid run
        reportgen.main(["--rules", rules_path, "--input", self.inp,
                        "--output", self.out, "--cache", self.cache_path])
        json_path = os.path.join(self.out, "report.json")
        html_path = os.path.join(self.out, "report.html")
        with open(json_path, "rb") as fh:
            good_json = fh.read()
        with open(html_path, "rb") as fh:
            good_html = fh.read()
        with open(self.cache_path, "rb") as fh:
            good_cache = fh.read()

        # Modify csv_a (valid change) and csv_b (invalid transform cell)
        with open(csv_a, "w", encoding="utf-8") as fh:
            fh.write("flag,val\ntrue,30\n")
        with open(csv_b, "w", encoding="utf-8") as fh:
            fh.write("flag,val\ninvalid_bool,20\n")

        with self.assertRaises(SystemExit) as cm:
            reportgen.main(["--rules", rules_path, "--input", self.inp,
                            "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(cm.exception.code, 1)

        with open(json_path, "rb") as fh:
            self.assertEqual(fh.read(), good_json)
        with open(html_path, "rb") as fh:
            self.assertEqual(fh.read(), good_html)
        with open(self.cache_path, "rb") as fh:
            self.assertEqual(fh.read(), good_cache)

    def test_transform_failure_on_clean_dir_emits_nothing(self):
        with open(os.path.join(self.inp, "bad.csv"), "w", encoding="utf-8") as fh:
            fh.write("amount\nnot_money\n")
        rules_path = os.path.join(self.tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\namount = "currency_amount"\n')

        with self.assertRaises(SystemExit) as cm:
            reportgen.main(["--rules", rules_path, "--input", self.inp,
                            "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


if __name__ == "__main__":
    unittest.main()

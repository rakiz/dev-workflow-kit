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
    def test_boolean_forms_case_insensitive(self):
        for raw in ("yes", "YES", "True", "tRUE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "false", "FALSE"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_boolean_rejects_other_input(self):
        for raw in ("", "y", "1", "0", "on", "maybe", "yess"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")

    def run_tool(self, input_dir=None, rules=None):
        return reportgen.run(rules or self.rules, input_dir or self.inp,
                             self.out, self.cache_path)

    def assert_no_outputs(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    # -- feature: boolean end to end ---------------------------------
    def test_boolean_column_end_to_end(self):
        _write(os.path.join(self.inp, "b.csv"), "id,ok\n1,yes\n2,TRUE\n3,no\n4,Yes\n")
        _write(self.rules, '[transforms]\nok = "boolean"\n')
        report = self.run_tool()
        ok = report["files"]["b.csv"]["summary"]["columns"]["ok"]
        self.assertEqual(ok["sample"], [0.0, 1.0])
        self.assertEqual(ok["numeric_sum"], 3.0)

    # -- feature: future cache schema --------------------------------
    def test_future_entry_version_cache_is_ignored_and_rewritten(self):
        _write(os.path.join(self.inp, "t.csv"), "item\n1\n")
        _write(self.rules, '[transforms]\nitem = "round2"\n')
        _write(self.cache_path, json.dumps({"t.csv": {
            "registry_version": "99", "fingerprint": "abc",
            "payload": {"x": 1}}}))
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["summary"]["columns"]
                         ["item"]["numeric_sum"], 1.0)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertIn("digest", state["t.csv"])

    def test_future_top_level_version_cache_is_ignored_and_rewritten(self):
        _write(os.path.join(self.inp, "t.csv"), "item\n1\n")
        _write(self.rules, '[transforms]\nitem = "round2"\n')
        _write(self.cache_path, json.dumps(
            {"version": 4, "entries": {"t.csv": ["opaque"]}}))
        self.run_tool()
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    # -- defect: report/cache persisted from an incomplete pass ------
    def test_transform_error_leaves_no_report_and_no_cache(self):
        _write(os.path.join(self.inp, "a.csv"), "item\n1\n")
        _write(os.path.join(self.inp, "b.csv"), "item\nbad\n")
        _write(self.rules, '[transforms]\nitem = "round2"\n')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_outputs()

    def test_transform_crash_is_a_transform_failure(self):
        _write(os.path.join(self.inp, "a.csv"), "item\n1\n")
        _write(os.path.join(self.inp, "b.csv"), "item\n2\n")
        _write(self.rules, '[transforms]\nitem = "boom"\n')

        def boom(value):
            if value == "2":
                raise RuntimeError("unexpected")
            return value
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_outputs()

    def test_failed_run_keeps_previous_cache_state_untouched(self):
        _write(os.path.join(self.inp, "a.csv"), "item\n1\n")
        _write(self.rules, '[transforms]\nitem = "round2"\n')
        self.run_tool()
        with open(self.cache_path) as fh:
            before = fh.read()
        _write(os.path.join(self.inp, "b.csv"), "item\nbad\n")
        _write(os.path.join(self.inp, "a.csv"), "item\n5\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        with open(self.cache_path) as fh:
            self.assertEqual(fh.read(), before)

    def test_cli_exits_nonzero_on_failed_run(self):
        import subprocess
        import sys
        _write(os.path.join(self.inp, "b.csv"), "item\nbad\n")
        _write(self.rules, '[transforms]\nitem = "round2"\n')
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("warning", proc.stderr)
        self.assert_no_outputs()

    # -- defect: transforms crashing / accepting non-values ----------
    def test_date_iso_non_ascii_digits_raise_transform_error(self):
        for raw in ("\u00b9/02/2026", "01/02/\u00b2\u2070\u00b2\u2076"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("date_iso", raw)

    def test_non_finite_numbers_rejected(self):
        for name in ("round2", "currency_amount"):
            for raw in ("nan", "inf", "-Infinity", "1e999"):
                with self.assertRaises(transforms.TransformError):
                    transforms.apply(name, raw)

    # -- defect: cache disagreeing with a fresh run -------------------
    def test_cached_generated_from_matches_fresh_run(self):
        fresh = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        cached = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        for name in fresh["files"]:
            self.assertEqual(cached["files"][name]["generated_from"],
                             fresh["files"][name]["generated_from"], name)
        self.assertEqual(fresh["files"]["small_devices.csv"]["generated_from"], 1)

    def test_entry_from_older_registry_is_not_reused(self):
        path = os.path.join(self.inp, "t.csv")
        _write(path, "item\n1\n")
        _write(self.rules, '[transforms]\nitem = "round2"\n')
        rules = reportgen.load_rules(self.rules)
        stale = {"digest": cache.file_digest(path), "rows": 1,
                 "generated_from": 1, "rules_fp": cache.rules_fingerprint(rules),
                 "registry_version": "1",
                 "summary": {"columns": {"item": {"non_empty": 1, "distinct": 1,
                                                  "sample": ["stale"]}},
                             "skipped_rows": []}}
        _write(self.cache_path, json.dumps({"t.csv": stale}))
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["summary"]["columns"]
                         ["item"]["sample"], [1.0])

    # -- defect: summary statistics ------------------------------------
    def test_numeric_sum_counts_duplicate_values(self):
        _write(os.path.join(self.inp, "t.csv"), "amount\n$10\n$10\n$5\n")
        _write(self.rules, '[transforms]\namount = "currency_amount"\n')
        cols = self.run_tool()["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["amount"]["numeric_sum"], 25.0)
        self.assertEqual(cols["amount"]["distinct"], 2)

    def test_numeric_sample_sorted_numerically(self):
        _write(os.path.join(self.inp, "t.csv"), "n\n100\n9\n20\n3\n")
        _write(self.rules, '[transforms]\nn = "round2"\n')
        cols = self.run_tool()["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["n"]["sample"], [3.0, 9.0, 20.0])

    # -- defect: unescaped HTML -----------------------------------------
    def test_html_escapes_names_and_samples(self):
        _write(os.path.join(self.inp, "t.csv"), "<i>col</i>\na&b\n")
        _write(self.rules, "[transforms]\n")
        self.run_tool()
        with open(os.path.join(self.out, "report.html")) as fh:
            page = fh.read()
        self.assertNotIn("<i>", page)
        self.assertIn("&lt;i&gt;col&lt;/i&gt;", page)
        self.assertIn("a&amp;b", page)


if __name__ == "__main__":
    unittest.main()

"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import json
import os
import shutil
import subprocess
import sys
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
    """The `boolean` transform (goal item 1)."""

    def test_affirmative_forms_are_one(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", value), 1.0)

    def test_negative_forms_are_zero(self):
        for value in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_other_values_are_rejected(self):
        for value in ("maybe", "y", "1", "0", "", "yesno"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)

    def test_boolean_column_is_reported_as_numbers(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,no\n3,TRUE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
        for value in cols["flag"]["sample"]:
            self.assertIsInstance(value, float)


class RulesReadTests(unittest.TestCase):
    """The rules file must be read at most once per run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reads-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        for name in ("a.csv", "b.csv", "c.csv"):
            with open(os.path.join(self.inp, name), "w") as fh:
                fh.write("item\n1\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')

    def test_rules_file_is_opened_once_per_run(self):
        import builtins
        real_open = builtins.open
        opened = []

        def counting_open(file, *args, **kwargs):
            try:
                name = os.fspath(file)
            except TypeError:
                name = file
            if name == self.rules_path:
                opened.append(name)
            return real_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(self.rules_path, self.inp, os.path.join(self.tmp, "out"),
                          os.path.join(self.tmp, "cache", "state.json"))
        finally:
            builtins.open = real_open
        self.assertEqual(len(opened), 1)


class CacheVersionTests(unittest.TestCase):
    """Cache entries are only reused under the current registry version,
    and a state file from a future schema must not crash the run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-ver-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv_path = os.path.join(self.inp, "t.csv")
        with open(self.csv_path, "w") as fh:
            fh.write("item\n1\n2\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def stale_entry(self, version):
        rules = reportgen.load_rules(self.rules_path)
        return {"t.csv": {
            "digest": cache.file_digest(self.csv_path),
            "rows": 99,
            "generated_from": 99,
            "rules_fp": cache.rules_fingerprint(rules),
            "registry_version": version,
            "summary": {"columns": {}, "skipped_rows": []}}}

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)

    def test_entry_from_a_future_registry_version_is_not_reused(self):
        self.write_state(self.stale_entry("999"))
        report = self.run_tool()
        # The stale entry claimed 99 rows; the file really has 2, so the
        # entry must have been discarded and the file re-summarized.
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(state["t.csv"]["rows"], 2)

    def test_entry_from_an_older_registry_version_is_not_reused(self):
        self.write_state(self.stale_entry("1"))
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_state_file_from_a_future_schema_does_not_crash_the_run(self):
        self.write_state({"version": "999", "entries": self.stale_entry("999")})
        report = self.run_tool()
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_state_file_from_a_future_schema_is_rewritten(self):
        self.write_state({"version": "999", "entries": self.stale_entry("999")})
        self.run_tool()
        with open(self.cache_path) as fh:
            rewritten = json.load(fh)
        self.assertIsInstance(rewritten, dict)
        self.assertEqual(set(rewritten), {"t.csv"})
        self.assertEqual(rewritten["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FailurePolicyTests(unittest.TestCase):
    """A failed transform aborts the run: exit 1, nothing new emitted,
    previous report and cache left byte-for-byte intact."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv_path = os.path.join(self.inp, "t.csv")
        with open(self.csv_path, "w") as fh:
            fh.write("item\n1\n2\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)

    def snapshot(self):
        paths = [os.path.join(self.out, "report.json"),
                 os.path.join(self.out, "report.html"),
                 self.cache_path]
        return {path: open(path, "rb").read() for path in paths}

    def break_the_input(self):
        with open(self.csv_path, "w") as fh:
            fh.write("item\n1\nn/a\n")

    def test_failed_transform_raises_validation_error(self):
        self.break_the_input()
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()

    def test_failed_transform_leaves_report_and_cache_intact(self):
        self.run_tool()
        before = self.snapshot()
        self.break_the_input()
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertEqual(self.snapshot(), before)

    def test_failed_transform_writes_no_cache_entry(self):
        self.break_the_input()
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assertFalse(os.path.exists(self.cache_path))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))

    def test_cli_exits_one_on_transform_failure(self):
        self.break_the_input()
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("reportgen:", proc.stderr)

    def test_cli_exits_zero_on_success(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class HtmlEscapingTests(unittest.TestCase):
    """Values and column names taken from the input must not leak markup."""

    def test_column_names_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-escape-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("<col>,value\nx,1\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write("[transforms]\n")
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html_text = fh.read()
        self.assertNotIn("<col>", html_text)
        self.assertIn("&lt;col&gt;", html_text)


if __name__ == "__main__":
    unittest.main()

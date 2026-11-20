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
        for affirmative in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", affirmative), 1.0)
        for negative in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", negative), 0.0)

    def test_boolean_transform_rejects_other_values(self):
        for bad in ("", "maybe", "1", "0", "y", "n"):
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


class BooleanColumnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("name,active\n")
            fh.write("a,YES\n")
            fh.write("b,no\n")
            fh.write("c,True\n")
            fh.write("d,False\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nactive = "boolean"\n')

    def test_boolean_column_is_reported_as_floats(self):
        report = reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["active"]["sample"], [0.0, 1.0])
        self.assertEqual(cols["active"]["distinct"], 2)
        self.assertEqual(cols["active"]["numeric_sum"], 2.0)

    def test_invalid_boolean_value_fails_the_run(self):
        with open(os.path.join(self.inp, "flags.csv"), "a") as fh:
            fh.write("e,maybe\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


class RulesReadCountTests(unittest.TestCase):
    def test_rules_file_is_read_once_per_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-read-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\ntx_id = "trim"\n')

        real_open = builtins.open
        reads = []

        def counting_open(file, *args, **kwargs):
            try:
                same = os.path.abspath(str(file)) == os.path.abspath(rules_path)
            except (TypeError, ValueError):
                same = False
            if same:
                reads.append(file)
            return real_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(rules_path, INPUT_DIR, os.path.join(tmp, "out"),
                          os.path.join(tmp, "cache", "state.json"))
        finally:
            builtins.open = real_open
        self.assertEqual(len(reads), 1)


class TransformFailureTests(unittest.TestCase):
    """A run that hits a failing transform must exit 1 and leave the
    previous report.json, report.html and cache state untouched."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv = os.path.join(self.inp, "t.csv")
        with open(self.csv, "w") as fh:
            fh.write("item,amount\n1,10.00\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "round2"\n')

    def snapshot(self):
        paths = [os.path.join(self.out, "report.json"),
                 os.path.join(self.out, "report.html"),
                 self.cache_path]
        return {p: (builtins.open(p, "rb").read() if os.path.exists(p) else None)
                for p in paths}

    def test_failed_transform_leaves_outputs_and_cache_intact(self):
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        before = self.snapshot()
        self.assertIsNotNone(before[os.path.join(self.out, "report.json")])
        self.assertIsNotNone(before[self.cache_path])

        with open(self.csv, "a") as fh:
            fh.write("2,not-a-number\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(self.snapshot(), before)

    def test_cli_exits_1_and_writes_nothing_on_transform_failure(self):
        with open(self.csv, "a") as fh:
            fh.write("2,not-a-number\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_cli_exits_0_on_a_good_run(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))

    def test_failed_run_emits_nothing_on_stdout(self):
        with open(self.csv, "a") as fh:
            fh.write("2,not-a-number\n")
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, b"")


class NumericSumTests(unittest.TestCase):
    def test_numeric_sum_covers_every_cell_not_just_distinct_values(self):
        tmp = tempfile.mkdtemp(prefix="rg3-sum-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "n.csv"), "w") as fh:
            fh.write("amount\n10.00\n20.00\n10.00\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\namount = "round2"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["n.csv"]["summary"]["columns"]
        self.assertEqual(cols["amount"]["distinct"], 2)
        self.assertEqual(cols["amount"]["numeric_sum"], 40.0)


class ReportStabilityTests(unittest.TestCase):
    def test_report_is_identical_when_the_cache_is_reused(self):
        tmp = tempfile.mkdtemp(prefix="rg3-stable-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        reportgen.run(RULES, INPUT_DIR, out, cache_path)
        with open(os.path.join(out, "report.json"), "rb") as fh:
            first = fh.read()
        reportgen.run(RULES, INPUT_DIR, out, cache_path)
        with open(os.path.join(out, "report.json"), "rb") as fh:
            second = fh.read()
        self.assertEqual(first, second)
        state = cache.load_state(cache_path)
        for name, res in json.loads(second)["files"].items():
            self.assertEqual(res["generated_from"],
                             state[name]["generated_from"])


class CacheSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-schema-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def write_state(self, state):
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.write("\n")

    def test_future_schema_version_is_treated_as_an_empty_cache(self):
        self.write_state({"version": cache.REGISTRY_VERSION + 1,
                          "small_transactions.csv": {"digest": "stale"}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        self.assertEqual(state["small_transactions.csv"]["digest"],
                         cache.file_digest(
                             os.path.join(INPUT_DIR, "small_transactions.csv")))

    def test_future_schema_version_does_not_crash_the_cli(self):
        self.write_state({"schema_version": cache.REGISTRY_VERSION + 5})
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", RULES, "--input", INPUT_DIR, "--output", self.out,
             "--cache", self.cache_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))

    def test_entry_from_another_registry_version_is_not_reused(self):
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        state["small_transactions.csv"]["registry_version"] = "1"
        state["small_transactions.csv"]["summary"]["columns"]["amount"] = {
            "non_empty": 999, "distinct": 999, "sample": ["stale"]}
        self.write_state(state)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        cols = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertNotEqual(cols["amount"]["sample"], ["stale"])
        self.assertEqual(cols["amount"]["numeric_sum"], 275.59)
        after = cache.load_state(self.cache_path)
        self.assertEqual(cache.as_version(
            after["small_transactions.csv"]["registry_version"]),
            cache.as_version(cache.REGISTRY_VERSION))


    def test_incomplete_cache_entry_is_recomputed_not_crashed(self):
        self.write_state({"small_transactions.csv": {"digest": "stale"}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(
            state["small_transactions.csv"]["digest"],
            cache.file_digest(
                os.path.join(INPUT_DIR, "small_transactions.csv")))


class HtmlEscapingTests(unittest.TestCase):
    def test_file_name_and_column_name_do_not_leak_markup(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a<b>.csv"), "w") as fh:
            fh.write("c<d>,x\n1,y\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nx = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertNotIn("<d>", html)
        self.assertIn("a&lt;b&gt;.csv", html)
        self.assertIn("c&lt;d&gt;", html)


class TransformCrashTests(unittest.TestCase):
    """A transform that crashes outright (not a TransformError) is a
    transform failure too: the run must not emit anything."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-crash-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item\n1\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "boom"\n')
        transforms.REGISTRY["boom"] = self._boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)

    @staticmethod
    def _boom(value):
        raise IndexError("transform blew up")

    def test_crash_leaves_nothing_written(self):
        with self.assertRaises(IndexError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unknown_transform_name_exits_1_from_the_cli(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.rules_path, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, b"")
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))


if __name__ == "__main__":
    unittest.main()

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

    def test_boolean(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", " true "):
            self.assertEqual(transforms.apply("boolean", value), 1.0)
        for value in ("no", "NO", "No", "false", "FALSE", " false "):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_boolean_rejects_anything_else(self):
        for value in ("y", "n", "1", "0", "", "maybe", "yes!"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)


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
    """The boolean transform maps yes/no/true/false to 1.0/0.0."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("flag,label\nyes,alpha\nNo,beta\nTRUE,gamma\nfalse,delta\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_boolean_column_end_to_end(self):
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["non_empty"], 4)
        # the affirmative/negative values are reported as 1.0 and 0.0
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])

    def test_boolean_failure_aborts_the_run(self):
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("flag,label\nyes,alpha\nmaybe,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))


class RulesReadTests(unittest.TestCase):
    """The rules file must be read at most once per run."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-read-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_rules_file_is_read_once_per_run(self):
        reads = []
        real_open = builtins.open

        def counting_open(file, *args, **kwargs):
            try:
                name = os.path.abspath(os.fspath(file))
            except TypeError:
                name = None
            if name == os.path.abspath(RULES):
                reads.append(name)
            return real_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        finally:
            builtins.open = real_open
        self.assertEqual(len(reads), 1)


class FailurePolicyTests(unittest.TestCase):
    """A failed transform must not leave a report or a cache entry
    behind, and the run must fail."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("x\n1\n")
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("y\nn/a\n")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.good_rules = os.path.join(self.tmp, "good.toml")
        with open(self.good_rules, "w") as fh:
            fh.write('[transforms]\nx = "trim"\n')
        self.bad_rules = os.path.join(self.tmp, "bad.toml")
        with open(self.bad_rules, "w") as fh:
            fh.write('[transforms]\nx = "trim"\ny = "round2"\n')
        self.boom_rules = os.path.join(self.tmp, "boom.toml")
        with open(self.boom_rules, "w") as fh:
            fh.write('[transforms]\nx = "trim"\ny = "boom"\n')
        reportgen.run(self.good_rules, self.inp, self.out, self.cache_path)

    def snapshot(self):
        snap = {}
        for name in ("report.json", "report.html"):
            with open(os.path.join(self.out, name), "rb") as fh:
                snap[name] = fh.read()
        with open(self.cache_path, "rb") as fh:
            snap["cache"] = fh.read()
        return snap

    def test_caught_transform_failure_keeps_previous_outputs(self):
        before = self.snapshot()
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.bad_rules, self.inp, self.out, self.cache_path)
        self.assertEqual(self.snapshot(), before)

    def test_unhandled_crash_keeps_previous_outputs(self):
        def boom(value):
            raise RuntimeError("boom")

        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        before = self.snapshot()
        with self.assertRaises(RuntimeError):
            reportgen.run(self.boom_rules, self.inp, self.out, self.cache_path)
        self.assertEqual(self.snapshot(), before)

    def test_main_reports_failure_with_exit_code_one(self):
        before = self.snapshot()
        code = reportgen.main(["--rules", self.bad_rules, "--input", self.inp,
                               "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(code, 1)
        self.assertEqual(self.snapshot(), before)

    def test_command_line_exits_one_on_failure(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(BASE, "reportgen.py"),
             "--rules", self.bad_rules, "--input", self.inp,
             "--output", self.out, "--cache", self.cache_path],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)


class CacheHygieneTests(unittest.TestCase):
    """Cache hygiene: registry versions are honoured, a future schema
    version is treated as an empty cache."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hyg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("x\n1\n2\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nx = "trim"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)

    def read_state(self):
        with open(self.cache_path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_future_entry_version_is_treated_as_empty_cache(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        state = self.read_state()
        future = str(int(cache.REGISTRY_VERSION) + 1)
        for entry in state.values():
            entry["registry_version"] = future
            entry["rows"] = 999
            entry["summary"] = {"columns": {}, "skipped_rows": []}
        self.write_state(state)

        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        # the stale entry was not reused: the file was summarized again
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        rewritten = self.read_state()
        for entry in rewritten.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_future_state_version_is_treated_as_empty_cache(self):
        self.write_state({"version": str(int(cache.REGISTRY_VERSION) + 1),
                          "t.csv": {"digest": "stale", "rows": 999,
                                    "generated_from": 0, "rules_fp": "stale",
                                    "registry_version": cache.REGISTRY_VERSION,
                                    "summary": {"columns": {}, "skipped_rows": []}}})
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        rewritten = self.read_state()
        self.assertNotIn("version", rewritten)
        self.assertEqual(rewritten["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_entry_from_older_registry_version_is_not_reused(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        state = self.read_state()
        state["t.csv"]["registry_version"] = "1"
        state["t.csv"]["rows"] = 999
        self.write_state(state)

        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)

    def test_unreadable_cache_is_treated_as_empty_cache(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["files"]["t.csv"]["rows"], 2)
        self.assertEqual(self.read_state()["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class ReportConsistencyTests(unittest.TestCase):
    """The report must not depend on whether the cache was warm."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-cons-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_cold_and_warm_runs_produce_the_same_report(self):
        cold = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            cold_json = fh.read()
        warm = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json"), "rb") as fh:
            warm_json = fh.read()
        self.assertEqual(cold_json, warm_json)
        self.assertEqual(cold, warm)

    def test_cache_entry_agrees_with_the_report(self):
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(self.cache_path, encoding="utf-8") as fh:
            state = json.load(fh)
        for name, res in report["files"].items():
            self.assertEqual(state[name]["generated_from"],
                             res["generated_from"])


class HtmlEscapingTests(unittest.TestCase):
    """Everything that comes from the input data is HTML-escaped."""

    def test_names_and_values_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a&b.csv"), "w") as fh:
            fh.write("col<x>\nv<1>\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\ncol<x> = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<x>", html)
        self.assertIn("a&amp;b.csv", html)
        self.assertIn("col&lt;x&gt;", html)
        self.assertIn("v&lt;1&gt;", html)


if __name__ == "__main__":
    unittest.main()

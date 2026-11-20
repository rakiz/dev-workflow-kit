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
    def test_accepted_forms(self):
        for raw in ("yes", "YES", "True", "tRuE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)
        self.assertIsInstance(transforms.apply("boolean", "yes"), float)

    def test_other_input_rejected(self):
        for raw in ("", "y", "1", "0", "maybe", " yes"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_date_iso_non_ascii_digit_is_transform_error(self):
        with self.assertRaises(transforms.TransformError):
            transforms.apply("date_iso", "1/2/\u00b2\u00b2\u00b2\u00b2")


class PipelineFixtureMixin:
    def make_fixture(self, rules_text, csv_text):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fx-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv_path = os.path.join(self.inp, "t.csv")
        with open(self.csv_path, "w") as fh:
            fh.write(csv_text)
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write(rules_text)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def go(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def snapshot(self):
        snap = {}
        for p in (os.path.join(self.out, "report.json"),
                  os.path.join(self.out, "report.html"), self.cache_path):
            with open(p, "rb") as fh:
                snap[p] = fh.read()
        return snap


class FailurePolicyTests(PipelineFixtureMixin, unittest.TestCase):
    def setUp(self):
        self.make_fixture('[transforms]\nflag = "boolean"\n',
                          "id,flag\n1,yes\n2,no\n")

    def test_boolean_end_to_end(self):
        report = self.go()
        col = report["files"]["t.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(col["sample"], [0.0, 1.0])
        self.assertEqual(col["numeric_sum"], 1.0)

    def _assert_failed_run_leaves_everything(self, mutate):
        self.go()
        before = self.snapshot()
        mutate()
        with self.assertRaises(Exception):
            self.go()
        self.assertEqual(self.snapshot(), before)

    def test_failed_cell_emits_nothing_new(self):
        def mutate():
            with open(self.csv_path, "w") as fh:
                fh.write("id,flag\n1,yes\n2,maybe\n")
        self._assert_failed_run_leaves_everything(mutate)

    def test_failed_cell_in_first_run_writes_nothing(self):
        with open(self.csv_path, "w") as fh:
            fh.write("id,flag\n1,maybe\n")
        with self.assertRaises(reportgen.ValidationError):
            self.go()
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unhandled_crash_emits_nothing_new(self):
        def boom(value):
            raise RuntimeError("boom")
        def mutate():
            with open(self.csv_path, "w") as fh:
                fh.write("id,flag\n1,yes\n2,no\n3,no\n")
            self.addCleanup(transforms.REGISTRY.update,
                            {"boolean": transforms.REGISTRY["boolean"]})
            transforms.REGISTRY["boolean"] = boom
        self._assert_failed_run_leaves_everything(mutate)

    def test_cached_entry_with_skipped_rows_is_not_reused(self):
        self.go()
        state = cache.load_state(self.cache_path)
        state["t.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "stale"}]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        self.go()  # recomputed from source, not served from the bad entry
        self.assertEqual(
            cache.load_state(self.cache_path)["t.csv"]["summary"]["skipped_rows"], [])

    def test_main_exit_codes(self):
        argv = ["--rules", self.rules, "--input", self.inp,
                "--output", self.out, "--cache", self.cache_path]
        self.assertEqual(reportgen.main(argv), 0)
        before = self.snapshot()
        with open(self.csv_path, "w") as fh:
            fh.write("id,flag\n1,nope\n")
        self.assertEqual(reportgen.main(argv), 1)
        self.assertEqual(self.snapshot(), before)

    def test_cli_process_exit_status(self):
        import subprocess
        import sys
        base = [sys.executable, os.path.join(BASE, "reportgen.py"),
                "--rules", self.rules, "--input", self.inp,
                "--output", self.out, "--cache", self.cache_path]
        self.assertEqual(subprocess.run(base, capture_output=True).returncode, 0)
        with open(self.csv_path, "w") as fh:
            fh.write("id,flag\n1,nope\n")
        self.assertEqual(subprocess.run(base, capture_output=True).returncode, 1)


class RulesReadTests(PipelineFixtureMixin, unittest.TestCase):
    def test_rules_file_read_once_per_run(self):
        self.make_fixture('[transforms]\nid = "trim"\n', "id\n1\n")
        for n in ("b.csv", "c.csv"):
            with open(os.path.join(self.inp, n), "w") as fh:
                fh.write("id\n2\n")
        import builtins
        real_open = builtins.open
        reads = []
        def counting_open(file, *a, **kw):
            if file == self.rules:
                reads.append(file)
            return real_open(file, *a, **kw)
        builtins.open = counting_open
        try:
            self.go()
        finally:
            builtins.open = real_open
        self.assertEqual(len(reads), 1)


class CacheHygieneTests(PipelineFixtureMixin, unittest.TestCase):
    def setUp(self):
        self.make_fixture('[transforms]\nflag = "boolean"\n',
                          "id,flag,extra\n1,yes,\n2,no,\n")

    def _assert_recovers(self, future_state):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump(future_state, fh)
        report = self.go()
        self.assertEqual(report["total_rows"], 2)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)
        with open(self.cache_path) as fh:
            self.assertEqual(json.load(fh), state)

    def test_future_top_level_version(self):
        self._assert_recovers({"version": int(cache.REGISTRY_VERSION) + 1,
                               "entries": {"t.csv": {"digest": "x"}}})

    def test_future_entry_version(self):
        self._assert_recovers({"t.csv": {
            "digest": "x", "registry_version": str(int(cache.REGISTRY_VERSION) + 1)}})

    def test_malformed_state_is_empty_cache(self):
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            fh.write("{not json")
        self.assertEqual(self.go()["total_rows"], 2)

    def test_stale_registry_version_not_reused(self):
        self.go()
        state = cache.load_state(self.cache_path)
        state["t.csv"]["registry_version"] = "1"
        state["t.csv"]["summary"]["columns"]["flag"]["distinct"] = 99
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.go()
        self.assertEqual(
            report["files"]["t.csv"]["summary"]["columns"]["flag"]["distinct"], 2)

    def test_cache_hit_report_matches_fresh_report(self):
        fresh = self.go()
        cached = self.go()
        self.assertEqual(fresh, cached)
        self.assertEqual(cached["files"]["t.csv"]["generated_from"], 1)
        self.assertEqual(
            cache.load_state(self.cache_path)["t.csv"]["generated_from"], 1)


if __name__ == "__main__":
    unittest.main()

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
    def test_affirmative_and_negative_forms(self):
        for raw in ("yes", "YES", "True", " true "):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", "false "):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_inputs_raise(self):
        for raw in ("maybe", "1", "", "y"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


class FailurePolicyTests(unittest.TestCase):
    """A run with any failed transform exits 1, writes nothing new and
    leaves report.json, report.html and the cache byte-identical."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "round2"\n')
        self.good = os.path.join(self.inp, "a.csv")
        with open(self.good, "w") as fh:
            fh.write("amount\n1.5\n")
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)

    def snapshot(self):
        files = [os.path.join(self.out, "report.json"),
                 os.path.join(self.out, "report.html"), self.cache_path]
        return {p: _read_bytes(p) for p in files}

    def test_failed_transform_keeps_previous_outputs(self):
        before = self.snapshot()
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("amount\nnot-a-number\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(self.snapshot(), before)

    def test_main_exits_1_on_failed_transform(self):
        before = self.snapshot()
        with open(self.good, "w") as fh:
            fh.write("amount\nbogus\n")
        rc = reportgen.main(["--rules", self.rules_path, "--input", self.inp,
                             "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(rc, 1)
        self.assertEqual(self.snapshot(), before)


class RulesReadOnceTests(unittest.TestCase):
    def test_rules_file_read_once_per_run(self):
        from unittest import mock
        tmp = tempfile.mkdtemp(prefix="rg3-once-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        for name in ("a.csv", "b.csv", "c.csv"):
            with open(os.path.join(inp, name), "w") as fh:
                fh.write("item\n1\n")
        with mock.patch.object(reportgen, "load_rules",
                               wraps=reportgen.load_rules) as spy:
            reportgen.run(RULES, inp, os.path.join(tmp, "out"),
                          os.path.join(tmp, "cache", "state.json"))
        self.assertEqual(spy.call_count, 1)


class FutureCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def test_future_schema_state_is_ignored_and_rewritten(self):
        with open(self.cache_path, "w") as fh:
            json.dump({"version": "9", "small_devices.csv": {"opaque": True}}, fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(state["small_devices.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)
        with open(self.cache_path) as fh:
            self.assertNotIn("version", json.load(fh))

    def test_future_registry_entry_is_ignored(self):
        with open(self.cache_path, "w") as fh:
            json.dump({"small_devices.csv": {"registry_version": "99"}}, fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)


class CacheConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-consist-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_cache_hit_reproduces_fresh_report(self):
        out1 = os.path.join(self.tmp, "out1")
        out2 = os.path.join(self.tmp, "out2")
        first = reportgen.run(RULES, INPUT_DIR, out1, self.cache_path)
        second = reportgen.run(RULES, INPUT_DIR, out2, self.cache_path)
        self.assertEqual(first, second)

    def test_stale_registry_entry_is_not_reused(self):
        out = os.path.join(self.tmp, "out")
        reportgen.run(RULES, INPUT_DIR, out, self.cache_path)
        state = cache.load_state(self.cache_path)
        entry = state["small_transactions.csv"]
        entry["registry_version"] = "2"
        entry["summary"] = {"columns": {}, "skipped_rows": []}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(RULES, INPUT_DIR, out, self.cache_path)
        tx = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertEqual(tx["amount"]["numeric_sum"], 275.59)


if __name__ == "__main__":
    unittest.main()

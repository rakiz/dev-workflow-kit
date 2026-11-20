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
    def test_boolean_forms(self):
        for raw in ("yes", "YES", "True", "tRUE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "FALSE", "false"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_boolean_rejects_other_input(self):
        for raw in ("", "maybe", "1", "0", "y", "yes please"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class RunPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-policy-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules = os.path.join(self.tmp, "rules.toml")
        self.write("a.csv", "item,flag\n1,yes\n2,No\n")
        self.write("b.csv", "item,flag\n3,true\n")
        self.write_rules('[transforms]\nitem = "round2"\nflag = "boolean"\n')

    def write(self, name, text):
        with open(os.path.join(self.inp, name), "w") as fh:
            fh.write(text)

    def write_rules(self, text):
        with open(self.rules, "w") as fh:
            fh.write(text)

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def snapshot(self):
        snap = {}
        for path in (os.path.join(self.out, "report.json"),
                     os.path.join(self.out, "report.html"), self.cache_path):
            if os.path.exists(path):
                with open(path, "rb") as fh:
                    snap[path] = fh.read()
            else:
                snap[path] = None
        return snap

    def cli(self):
        return reportgen.main(["--rules", self.rules, "--input", self.inp,
                               "--output", self.out,
                               "--cache", self.cache_path])

    def test_boolean_in_report(self):
        report = self.run_tool()
        cols = report["files"]["a.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["flag"]["distinct"], 2)

    def test_failed_transform_exits_1_and_keeps_previous_output(self):
        self.assertEqual(self.cli(), 0)
        before = self.snapshot()
        self.write("a.csv", "item,flag\n1,yes\n2,maybe\n")
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_failed_transform_first_run_emits_nothing(self):
        self.write("b.csv", "item,flag\n3,maybe\n")  # a.csv is fine
        self.assertEqual(self.cli(), 1)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_crashing_transform_exits_1_and_keeps_previous_output(self):
        self.assertEqual(self.cli(), 0)
        before = self.snapshot()
        self.write("b.csv", "item,flag\n9,yes\n")

        def boom(value):
            raise RuntimeError("boom")
        old = transforms.REGISTRY["round2"]
        transforms.REGISTRY["round2"] = boom
        self.addCleanup(transforms.REGISTRY.__setitem__, "round2", old)
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.snapshot(), before)

    def test_failure_does_not_leave_cache_for_other_files(self):
        self.write("b.csv", "item,flag\n3,maybe\n")
        self.assertEqual(self.cli(), 1)
        self.assertFalse(os.path.exists(self.cache_path))

    def test_old_cache_entry_with_skipped_rows_is_not_reused(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        state["a.csv"]["summary"]["skipped_rows"] = [
            {"row": 2, "column": "flag", "reason": "stale"}]
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.run_tool()  # re-transformed, not failed on stale data
        self.assertEqual(report["files"]["a.csv"]["summary"]["skipped_rows"], [])

    def test_rules_file_read_once_per_run(self):
        reads = []
        real = reportgen.load_rules

        def counting(path):
            reads.append(path)
            return real(path)
        reportgen.load_rules = counting
        self.addCleanup(setattr, reportgen, "load_rules", real)
        self.run_tool()
        self.assertEqual(len(reads), 1)

    def test_rules_file_opened_once_per_run(self):
        import builtins
        opened = []
        real = builtins.open

        def counting(file, *a, **kw):
            if file == self.rules:
                opened.append(file)
            return real(file, *a, **kw)
        builtins.open = counting
        self.addCleanup(setattr, builtins, "open", real)
        self.run_tool()
        self.assertEqual(len(opened), 1)

    def test_future_cache_version_is_treated_as_empty(self):
        self.run_tool()
        for future in ({"version": 99, "entries": {}},
                       {"registry_version": "3"},):
            with open(self.cache_path, "w") as fh:
                json.dump(future, fh)
            self.assertEqual(self.cli(), 0)
            state = cache.load_state(self.cache_path)
            self.assertEqual(set(state), {"a.csv", "b.csv"})
            for entry in state.values():
                self.assertEqual(entry["registry_version"],
                                 cache.REGISTRY_VERSION)

    def test_future_entry_version_is_treated_as_empty(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        state["a.csv"]["registry_version"] = "99"
        state["a.csv"]["summary"] = {"columns": {}, "skipped_rows": []}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = self.run_tool()
        self.assertIn("flag", report["files"]["a.csv"]["summary"]["columns"])
        self.assertEqual(cache.load_state(self.cache_path)["a.csv"]
                         ["registry_version"], cache.REGISTRY_VERSION)

    def test_old_registry_version_entry_is_not_reused(self):
        self.run_tool()
        state = cache.load_state(self.cache_path)
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["rows"] = 999
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        self.assertEqual(self.run_tool()["files"]["a.csv"]["rows"], 2)

    def test_cached_run_reports_same_as_fresh_run(self):
        self.write("c.csv", "item,flag,other\n1,,x\n")
        self.write_rules('[transforms]\nitem = "round2"\nflag = "trim"\n')
        fresh = self.run_tool()
        cached = self.run_tool()
        self.assertEqual(fresh, cached)
        self.assertEqual(fresh["files"]["c.csv"]["generated_from"], 1)

    def test_html_escapes_values_and_names(self):
        self.write("x&y.csv", "co<l>,label\n1,red <b> & bold\n")
        self.run_tool()
        with open(os.path.join(self.out, "report.html")) as fh:
            page = fh.read()
        self.assertNotIn("<b>", page)
        self.assertIn("red &lt;b&gt; &amp; bold", page)
        self.assertIn("x&amp;y.csv", page)
        self.assertIn("co&lt;l&gt;", page)


if __name__ == "__main__":
    unittest.main()

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
    def test_affirmative_forms_report_one(self):
        for value in ("yes", "Yes", "YES", "true", "True", "TRUE", " yes "):
            self.assertEqual(transforms.apply("boolean", value), 1.0)

    def test_negative_forms_report_zero(self):
        for value in ("no", "No", "NO", "false", "False", "FALSE", " no "):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_any_other_input_raises(self):
        for value in ("maybe", "1", "0", "", "yess", "truthy"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)

    def test_boolean_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w") as fh:
            fh.write("id,flag\n1,YES\n2,no\n3,True\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        report = reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)


class HtmlEscapingRegressionTests(unittest.TestCase):
    def test_sample_markup_is_escaped_in_html(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,label\ni1,<script>alert('x')</script> & more\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out,
                      os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            rendered = fh.read()
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&amp; more", rendered)


class FailurePolicyTests(unittest.TestCase):
    """A transform failure of any kind (raised TransformError carried on
    from, or an unhandled crash) must exit 1, emit nothing new, and leave
    the previously good report.json, report.html and cache byte-identical."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "currency_amount"\n')
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("id,amount\n1,$1.00\n")
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("id,amount\n1,$2.00\n")
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.snapshot = {}
        for path in (os.path.join(self.out, "report.json"),
                     os.path.join(self.out, "report.html"),
                     self.cache_path):
            with open(path, "rb") as fh:
                self.snapshot[path] = fh.read()

    def assert_previous_outputs_intact(self):
        for path, data in self.snapshot.items():
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), data, "changed: %s" % path)

    def run_once(self):
        return reportgen.run(self.rules_path, self.inp, self.out,
                             self.cache_path)

    def test_caught_transform_failure_emits_nothing_and_exits_1(self):
        with open(os.path.join(self.inp, "b.csv"), "a") as fh:
            fh.write("2,not-money\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_once()
        self.assert_previous_outputs_intact()
        with self.assertRaises(SystemExit) as cm:
            reportgen.main(["--rules", self.rules_path, "--input", self.inp,
                            "--output", self.out, "--cache", self.cache_path])
        self.assertEqual(cm.exception.code, 1)
        self.assert_previous_outputs_intact()

    def test_unhandled_transform_crash_emits_nothing(self):
        def boom(value):
            raise RuntimeError("unhandled crash")
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "currency_amount"\nextra = "boom"\n')
        with open(os.path.join(self.inp, "b.csv"), "w") as fh:
            fh.write("id,amount,extra\n1,$2.00,x\n")
        with self.assertRaises(RuntimeError):
            self.run_once()
        self.assert_previous_outputs_intact()


class RulesReadOnceTests(unittest.TestCase):
    def test_rules_file_read_exactly_once_per_run(self):
        import builtins
        tmp = tempfile.mkdtemp(prefix="rg3-reads-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        for i in range(3):
            with open(os.path.join(inp, "f%d.csv" % i), "w") as fh:
                fh.write("a,b\n1,2\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\na = "trim"\n')
        reads = []
        real_open = builtins.open

        def counting_open(file, *args, **kwargs):
            if os.fspath(file) == rules_path:
                reads.append(file)
            return real_open(file, *args, **kwargs)

        builtins.open = counting_open
        try:
            reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                          os.path.join(tmp, "cache", "state.json"))
        finally:
            builtins.open = real_open
        self.assertEqual(len(reads), 1)


class GeneratedFromCoherenceTests(unittest.TestCase):
    def test_cached_run_reports_same_generated_from_as_fresh_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-genfrom-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("id,flag\n1,\n2,\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nid = "trim"\nflag = "upper"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        fresh = reportgen.run(rules_path, inp, out, cache_path)
        cached = reportgen.run(rules_path, inp, out, cache_path)
        self.assertEqual(fresh, cached)
        self.assertEqual(fresh["files"]["t.csv"]["generated_from"], 1)


class RegistryVersionLookupTests(unittest.TestCase):
    def test_entry_from_another_registry_version_is_not_reused(self):
        tmp = tempfile.mkdtemp(prefix="rg3-regver-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("id\n1\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nid = "trim"\n')
        cache_path = os.path.join(tmp, "cache", "state.json")
        reportgen.run(rules_path, inp, os.path.join(tmp, "out"), cache_path)
        state = cache.load_state(cache_path)
        state["t.csv"]["registry_version"] = "1"
        state["t.csv"]["summary"] = {
            "columns": {"id": {"non_empty": 999, "distinct": 999,
                               "sample": ["SENTINEL"]}},
            "skipped_rows": []}
        with open(cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                               cache_path)
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["id"]["distinct"], 1)
        self.assertNotIn("SENTINEL", cols["id"]["sample"])
        self.assertEqual(cache.load_state(cache_path)["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)


class FutureSchemaCacheTests(unittest.TestCase):
    def test_future_version_state_is_treated_as_empty_and_rewritten(self):
        tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("id\n1\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nid = "trim"\n')
        cache_path = os.path.join(tmp, "cache", "state.json")
        reportgen.run(rules_path, inp, os.path.join(tmp, "out"), cache_path)
        state = cache.load_state(cache_path)
        state["t.csv"]["registry_version"] = str(int(cache.REGISTRY_VERSION) + 1)
        state["t.csv"]["summary"] = {
            "columns": {"id": {"non_empty": 999, "distinct": 999,
                               "sample": ["SENTINEL"]}},
            "skipped_rows": []}
        with open(cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(rules_path, inp, os.path.join(tmp, "out"),
                               cache_path)
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["id"]["distinct"], 1)
        with open(cache_path) as fh:
            rewritten = json.load(fh)
        self.assertEqual(set(rewritten), {"t.csv"})
        entry = rewritten["t.csv"]
        self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)
        self.assertEqual(
            entry["digest"], cache.file_digest(os.path.join(inp, "t.csv")))


if __name__ == "__main__":
    unittest.main()

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
    def test_boolean_accepts_affirmative_forms(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", value), 1.0)

    def test_boolean_accepts_negative_forms(self):
        for value in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_boolean_rejects_anything_else(self):
        for value in ("", "maybe", "1", "0", "y", "n", "truthy", "yes please"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)

    def test_boolean_rule_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,No\n3,TRUE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)


class HtmlEscapingTests(unittest.TestCase):
    def test_markup_in_names_and_values_is_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-escape-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "we<i>ird.csv"), "w") as fh:
            fh.write("co<b>l,label\nx,red & <b> bold\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nco<b>l = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out,
                      os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertNotIn("<i>", html)
        self.assertIn("we&lt;i&gt;ird.csv", html)
        self.assertIn("co&lt;b&gt;l", html)
        self.assertIn("red &amp; &lt;b&gt; bold", html)


class FailurePolicyTests(unittest.TestCase):
    """A transform failure must end the same way whatever it looks like:
    no report, no cache state."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.csv = os.path.join(self.inp, "t.csv")
        self.rules = os.path.join(self.tmp, "rules.toml")
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_input(self, body):
        with open(self.csv, "w") as fh:
            fh.write("item,label\n%s" % body)

    def write_rules(self, mapping):
        with open(self.rules, "w") as fh:
            fh.write("[transforms]\n%s\n" % mapping)

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def assert_no_artifacts(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_transform_leaves_no_report_and_no_cache(self):
        self.write_input("1,alpha\nbogus,beta\n")
        self.write_rules('item = "round2"')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_crashing_transform_leaves_no_report_and_no_cache(self):
        def boom(value):
            raise RuntimeError("boom")
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        self.write_input("1,alpha\n")
        self.write_rules('item = "boom"')
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()

    def test_failed_run_removes_artifacts_of_an_earlier_run(self):
        self.write_input("1,alpha\n")
        self.write_rules('item = "round2"')
        self.run_tool()
        self.assertTrue(os.path.exists(self.cache_path))
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))
        self.write_input("1,alpha\nbogus,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            self.run_tool()
        self.assert_no_artifacts()


class CacheHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hygiene-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\n2,beta\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(self.rules, self.inp, self.out, self.cache_path)

    def future_version(self):
        return str(int(cache.REGISTRY_VERSION) + 1)

    def read_state(self):
        with open(self.cache_path) as fh:
            return json.load(fh)

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def test_future_registry_version_entries_are_not_reused(self):
        self.run_tool()
        state = self.read_state()
        for entry in state.values():
            entry["registry_version"] = self.future_version()
            entry["rows"] = 999
            entry["summary"] = {"columns": {}}
        self.write_state(state)
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        state = self.read_state()
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["rows"], 2)
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_future_schema_version_document_is_treated_as_empty(self):
        self.run_tool()
        state = self.read_state()
        self.write_state({"version": self.future_version(), "entries": state})
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        state = self.read_state()
        self.assertNotIn("version", state)
        self.assertNotIn("entries", state)
        self.assertEqual(set(state), {"t.csv"})

    def test_unreadable_cache_file_is_treated_as_empty(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            fh.write("{not json")
        report = self.run_tool()
        self.assertEqual(report["total_rows"], 2)
        self.assertEqual(set(self.read_state()), {"t.csv"})


if __name__ == "__main__":
    unittest.main()

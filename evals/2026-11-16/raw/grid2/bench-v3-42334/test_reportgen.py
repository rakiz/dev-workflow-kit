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

    def test_boolean_accepts_affirmative_and_negative_forms(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", " true "):
            self.assertEqual(transforms.apply("boolean", value), 1.0)
        for value in ("no", "NO", "No", "false", "FALSE", " false "):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_boolean_rejects_other_values(self):
        for value in ("", "maybe", "1", "0", "y", "n", "oui"):
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


class BooleanColumnTests(unittest.TestCase):
    """The boolean transform, end to end."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("name,flag\n"
                     "a,yes\n"
                     "b,No\n"
                     "c,TRUE\n"
                     "d,false\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

    def test_boolean_column_summarized_as_one_zero(self):
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
        self.assertEqual(cols["flag"]["numeric_sum"], 2.0)

    def test_boolean_column_invalid_value_fails_the_run(self):
        with open(os.path.join(self.inp, "flags.csv"), "a") as fh:
            fh.write("e,maybe\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class CacheHygieneTests(unittest.TestCase):
    """A cache written by a future schema version must not crash the run,
    and must not be reused."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def test_future_flat_state_is_treated_as_empty(self):
        future = "999"
        self.write_state({"t.csv": {"digest": "x", "rows": 99,
                                    "generated_from": 1, "rules_fp": "y",
                                    "registry_version": future,
                                    "summary": {"columns": {}, "skipped_rows": []}}})
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        state = json.load(open(self.cache_path))
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_future_versioned_state_is_treated_as_empty(self):
        self.write_state({"version": 999,
                          "entries": {"t.csv": {"digest": "x", "rows": 99,
                                                "generated_from": 1,
                                                "rules_fp": "y",
                                                "summary": {}}}})
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        state = json.load(open(self.cache_path))
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"], cache.REGISTRY_VERSION)

    def test_state_from_another_registry_version_is_not_reused(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        state = json.load(open(self.cache_path))
        state["t.csv"]["registry_version"] = "0"
        state["t.csv"]["rows"] = 999
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)
        self.assertEqual(report["files"]["t.csv"]["rows"], 1)

    def test_corrupt_state_file_does_not_crash_the_run(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            fh.write("{not json")
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 1)


class TransformFailureTests(unittest.TestCase):
    """Every way a transform can fail leaves no report and no cache state."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,label\n1,alpha\n")
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')

    def assert_no_artifacts(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))
        self.assertFalse(os.path.exists(self.cache_path + ".tmp"))

    def test_failed_cell_leaves_no_report_and_no_cache(self):
        with open(os.path.join(self.inp, "t.csv"), "a") as fh:
            fh.write("n/a,alpha\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_unexpected_transform_crash_leaves_no_report_and_no_cache(self):
        original = transforms.apply

        def boom(name, value):
            raise ValueError("boom: %r" % value)

        transforms.apply = boom
        self.addCleanup(setattr, transforms, "apply", original)
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_failure_after_a_successful_run_leaves_no_stale_artifacts(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))
        with open(os.path.join(self.inp, "t.csv"), "a") as fh:
            fh.write("n/a,alpha\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_crash_after_the_transform_pass_leaves_no_artifacts(self):
        original = cache.save_state

        def boom(*args, **kwargs):
            raise OSError("disk full")

        cache.save_state = boom
        self.addCleanup(setattr, cache, "save_state", original)
        with self.assertRaises(OSError):
            reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assert_no_artifacts()

    def test_error_before_any_transform_keeps_previous_artifacts(self):
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        bad_rules = os.path.join(self.tmp, "broken.toml")
        with open(bad_rules, "w") as fh:
            fh.write("no equals sign here\n")
        with self.assertRaises(ValueError):
            reportgen.run(bad_rules, self.inp, self.out, self.cache_path)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertTrue(os.path.exists(self.cache_path))


class NumericSumTests(unittest.TestCase):
    """The numeric sum covers every transformed cell, not only distinct
    values."""

    def test_duplicate_values_are_counted_in_the_numeric_sum(self):
        tmp = tempfile.mkdtemp(prefix="rg3-sum-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item\n1.5\n2.5\n1.5\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["item"]["distinct"], 2)
        self.assertEqual(cols["item"]["numeric_sum"], 5.5)


class HtmlEscapingTests(unittest.TestCase):
    """Cell values and column names are escaped in the HTML report."""

    def test_markup_in_values_and_column_names_is_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("<col>,label\n1,<script>alert(1)</script>\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html_text = fh.read()
        self.assertNotIn("<script>", html_text)
        self.assertIn("&lt;script&gt;", html_text)
        self.assertIn("&lt;col&gt;", html_text)


if __name__ == "__main__":
    unittest.main()

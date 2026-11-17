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
    """The `boolean` transform (added for the next release)."""

    def test_boolean_accepts_affirmative_forms(self):
        for value in ("yes", "YES", "Yes", "yEs", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", value), 1.0)

    def test_boolean_accepts_negative_forms(self):
        for value in ("no", "NO", "No", "nO", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_boolean_rejects_other_values(self):
        for value in ("maybe", "", "1", "y", "yes no"):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", value)


class BooleanEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,no\n3,TRUE\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

    def test_boolean_column_is_reported_as_numbers(self):
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        # the summary reports the distinct transformed values; the sum is
        # taken over those distinct values (0.0 + 1.0)
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])

    def test_bad_boolean_cell_fails_the_run(self):
        with open(os.path.join(self.inp, "flags.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,perhaps\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)


class ReportStabilityTests(unittest.TestCase):
    """The cache must reproduce exactly what the uncached run produced."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-stable-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def run_tool(self):
        return reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)

    def test_second_run_reproduces_the_same_report(self):
        first = self.run_tool()
        with open(os.path.join(self.out, "report.json")) as fh:
            first_json = fh.read()
        second = self.run_tool()
        with open(os.path.join(self.out, "report.json")) as fh:
            second_json = fh.read()
        self.assertEqual(first_json, second_json)
        self.assertEqual(first, second)

    def test_generated_from_matches_on_both_runs(self):
        first = self.run_tool()["files"]["small_devices.csv"]["generated_from"]
        second = self.run_tool()["files"]["small_devices.csv"]["generated_from"]
        self.assertEqual(first, second)
        self.assertEqual(first, 1)


class FailurePolicyTests(unittest.TestCase):
    """A transform failure must never leave a report or a cache state."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\n')

    def write_input(self, body):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write(body)

    def artifacts(self):
        listing = sorted(os.listdir(self.out)) if os.path.isdir(self.out) else []
        return (listing, os.path.exists(self.cache_path))

    def test_failed_transform_emits_no_report_and_no_cache(self):
        self.write_input("item,label\n1,alpha\nnope,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(self.artifacts(), ([], False))

    def test_failed_transform_removes_earlier_artifacts(self):
        self.write_input("item,label\n1,alpha\n")
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(self.artifacts(),
                         (["report.html", "report.json"], True))
        self.write_input("item,label\n1,alpha\nnope,beta\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(self.artifacts(), ([], False))

    def test_unhandled_crash_in_transform_ends_like_a_caught_failure(self):
        def boom(value):
            raise RuntimeError("boom")

        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "boom"\n')
        self.write_input("item,label\n1,alpha\n")
        with self.assertRaises(RuntimeError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertEqual(self.artifacts(), ([], False))


class CacheHygieneTests(unittest.TestCase):
    """State files that cannot be trusted are discarded, not honoured."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hyg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def write_state(self, payload):
        with open(self.cache_path, "w") as fh:
            json.dump(payload, fh)

    def stale_entry(self, **overrides):
        entry = {"digest": "stale", "rows": 999, "generated_from": 999,
                 "rules_fp": "stale", "registry_version": cache.REGISTRY_VERSION,
                 "summary": {"columns": {"tx_id": {"non_empty": 999,
                                                  "distinct": 999,
                                                  "sample": ["stale"]}},
                             "skipped_rows": []}}
        entry.update(overrides)
        return entry

    def test_future_schema_version_is_treated_as_an_empty_cache(self):
        self.write_state({"version": cache.REGISTRY_VERSION + 1,
                          "small_transactions.csv": self.stale_entry()})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(set(state), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        with open(self.cache_path) as fh:
            self.assertEqual(json.load(fh)["version"], cache.REGISTRY_VERSION)

    def test_future_schema_version_as_string_is_treated_as_an_empty_cache(self):
        self.write_state({"version": str(cache.REGISTRY_VERSION + 1),
                          "small_transactions.csv": self.stale_entry()})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)

    def test_entry_from_another_registry_version_is_not_reused(self):
        self.write_state({"version": cache.REGISTRY_VERSION,
                          "small_transactions.csv": self.stale_entry(
                              registry_version="1")})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        cols = report["files"]["small_transactions.csv"]["summary"]["columns"]
        self.assertNotEqual(cols["tx_id"]["distinct"], 999)

    def test_corrupt_state_file_is_treated_as_an_empty_cache(self):
        with open(self.cache_path, "w") as fh:
            fh.write("{not json")
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)


class HtmlEscapingTests(unittest.TestCase):
    """Markup coming from the data must not reach the page unescaped."""

    def test_markup_in_names_and_samples_is_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "<b>odd.csv"), "w") as fh:
            fh.write("a<b>,label\n1,red & bold\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\na<b> = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache",
                                                          "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertIn("&lt;b&gt;odd.csv", html)
        self.assertIn("a&lt;b&gt;", html)
        self.assertIn("red &amp; bold", html)


if __name__ == "__main__":
    unittest.main()

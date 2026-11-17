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

    def test_boolean_accepted_forms(self):
        for value in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", value), 1.0)
        for value in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", value), 0.0)

    def test_boolean_rejects_other_input(self):
        for value in ("maybe", "", "1", "0", "y"):
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


class FailurePolicyTests(unittest.TestCase):
    """A run in which any cell failed its transform must end the same way:
    no report emitted, no cache state left behind."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "round2"\n')

    def assert_no_outputs(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_caught_transform_failure_emits_no_report_or_cache(self):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("amount\n1.5\noops\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_outputs()

    def test_earlier_good_file_leaves_no_cache_when_later_file_fails(self):
        with open(os.path.join(self.inp, "a_good.csv"), "w") as fh:
            fh.write("amount\n1.5\n")
        with open(os.path.join(self.inp, "b_bad.csv"), "w") as fh:
            fh.write("amount\noops\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_outputs()

    def test_unhandled_crash_leaves_no_report_or_cache(self):
        def boom(value):
            raise RuntimeError("unhandled crash")
        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\namount = "boom"\n')
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("amount\n1.5\n")
        with self.assertRaises(RuntimeError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_outputs()


class RegistryVersionLookupTests(unittest.TestCase):
    """Cache entries stamped with a different registry version must never
    be reused (transforms.py: 'the version is compared at lookup')."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-ver-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_old_registry_version_entry_not_reused(self):
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        entry = state["small_transactions.csv"]
        entry["registry_version"] = "1"
        entry["rows"] = 999
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["files"]["small_transactions.csv"]["rows"], 4)


class GeneratedFromStabilityTests(unittest.TestCase):
    """generated_from must not depend on whether the result came from the
    cache (cache.make_entry used to count it differently from
    reportgen.generated_from)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-gen-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,note\n1,\n2,\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nitem = "round2"\nnote = "trim"\n')

    def test_generated_from_same_fresh_and_cached(self):
        run = lambda: reportgen.run(
            self.rules_path, self.inp, self.out, self.cache_path)
        first = run()
        second = run()
        self.assertEqual(first["files"]["t.csv"]["generated_from"], 1)
        self.assertEqual(second["files"]["t.csv"]["generated_from"],
                         first["files"]["t.csv"]["generated_from"])


class FutureSchemaCacheTests(unittest.TestCase):
    """A cache/state.json written by a future schema version must not
    crash the run: treat the cache as empty, do the full run, rewrite a
    valid state file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fut-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        os.makedirs(os.path.dirname(self.cache_path))

    def test_future_version_state_treated_as_empty_and_rewritten(self):
        for future in ("999", 999):
            with self.subTest(registry_version=future):
                state = {"small_transactions.csv": {
                    "digest": "0" * 64, "rows": 12345, "generated_from": 0,
                    "rules_fp": "futurefp", "registry_version": future,
                    "summary": {"columns": {}, "skipped_rows": []}}}
                with open(self.cache_path, "w") as fh:
                    json.dump(state, fh)
                report = reportgen.run(RULES, INPUT_DIR, self.out,
                                       self.cache_path)
                self.assertEqual(report["total_rows"], 12012)
                with open(self.cache_path) as fh:
                    new_state = json.load(fh)
                self.assertEqual(set(new_state), {
                    "big_transactions.csv", "small_devices.csv",
                    "small_employees.csv", "small_transactions.csv"})
                for entry in new_state.values():
                    self.assertEqual(entry["registry_version"],
                                     cache.REGISTRY_VERSION)
                digest = cache.file_digest(
                    os.path.join(INPUT_DIR, "small_transactions.csv"))
                self.assertEqual(new_state["small_transactions.csv"]["digest"],
                                 digest)


class HtmlEscapeTests(unittest.TestCase):
    """Regression for the unescaped HTML rendering (covered end-to-end by
    test_legacy_report; here for the column-name/file-name surface)."""

    def test_column_and_file_names_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "f.csv"), "w") as fh:
            fh.write("a<script>,b\n1,2\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write("[transforms]\n")
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out,
                      os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html_text = fh.read()
        self.assertNotIn("<script>", html_text)
        self.assertIn("a&lt;script&gt;", html_text)


if __name__ == "__main__":
    unittest.main()

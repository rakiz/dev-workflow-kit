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
        for raw in ("yes", "YES", "Yes", "true", "TRUE", "True"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms_report_zero(self):
        for raw in ("no", "NO", "No", "false", "FALSE", "False"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_input_raises(self):
        for raw in ("maybe", "y", "n", "1", "0", "yesno", ""):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class BooleanEndToEndTests(unittest.TestCase):
    def test_boolean_rule_summarizes_as_floats(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "flags.csv"), "w", encoding="utf-8") as fh:
            fh.write("id,flag\n1,yes\n2,NO\n3,True\n4,false\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["flags.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])


class FutureSchemaCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-future-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_state(self, obj):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)

    def raw_state(self):
        with open(self.cache_path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_future_top_level_version_is_treated_as_empty(self):
        self.write_state({"version": int(cache.REGISTRY_VERSION) + 1,
                          "entries": {"small_transactions.csv": {"rows": 999}}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        raw = self.raw_state()
        self.assertEqual(set(raw), {
            "big_transactions.csv", "small_devices.csv",
            "small_employees.csv", "small_transactions.csv"})
        for entry in raw.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_future_registry_version_entry_is_not_reused(self):
        path = os.path.join(INPUT_DIR, "small_transactions.csv")
        self.write_state({"small_transactions.csv": {
            "digest": cache.file_digest(path),
            "rows": 999,
            "generated_from": 0,
            "rules_fp": cache.rules_fingerprint(reportgen.load_rules(RULES)),
            "registry_version": str(int(cache.REGISTRY_VERSION) + 1),
            "summary": {"columns": {}, "skipped_rows": []}}})
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["files"]["small_transactions.csv"]["rows"], 4)
        raw = self.raw_state()
        self.assertEqual(raw["small_transactions.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_unrecognized_state_shape_is_treated_as_empty(self):
        self.write_state([{"not": "a mapping"}])
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        raw = self.raw_state()
        self.assertIsInstance(raw, dict)
        self.assertEqual(len(raw), 4)


class TransformFailurePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\namount = "currency_amount"\n'
                     'date = "date_iso"\n')

    def write_csv(self, name, text):
        with open(os.path.join(self.inp, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def assert_no_report_no_cache(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_raised_error_run_leaves_no_report_or_cache(self):
        self.write_csv("a_good.csv", "id,amount\n1,$1.00\n")
        self.write_csv("b_bad.csv", "id,amount\n1,see invoice\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_report_no_cache()

    def test_crashing_transform_run_ends_the_same_way(self):
        self.write_csv("a_crash.csv", "id,date\n1,1\u00b9/15/2026\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assert_no_report_no_cache()

    def test_failed_run_leaves_no_preexisting_cache_state(self):
        self.write_csv("a_good.csv", "id,amount\n1,$1.00\n")
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertTrue(os.path.exists(self.cache_path))
        self.write_csv("b_bad.csv", "id,amount\n1,see invoice\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(self.cache_path))


class GeneratedFromConsistencyTests(unittest.TestCase):
    def test_generated_from_matches_between_fresh_and_cached_run(self):
        tmp = tempfile.mkdtemp(prefix="rg3-gf-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w", encoding="utf-8") as fh:
            fh.write("a,b\nx,\ny,\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\na = "trim"\nb = "trim"\n')
        out = os.path.join(tmp, "out")
        cache_path = os.path.join(tmp, "cache", "state.json")
        fresh = reportgen.run(rules_path, inp, out, cache_path)
        cached = reportgen.run(rules_path, inp, out, cache_path)
        self.assertEqual(fresh["files"]["t.csv"]["generated_from"],
                         cached["files"]["t.csv"]["generated_from"])
        self.assertEqual(cached["files"]["t.csv"]["generated_from"], 2)


class HtmlEscapingRegressionTests(unittest.TestCase):
    def test_column_names_do_not_leak_markup(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w", encoding="utf-8") as fh:
            fh.write("item,lab<b>el\ni1,red\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w", encoding="utf-8") as fh:
            fh.write('[transforms]\nitem = "trim"\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out,
                      os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html"), encoding="utf-8") as fh:
            page = fh.read()
        self.assertNotIn("lab<b>el", page)
        self.assertIn("lab&lt;b&gt;el", page)


if __name__ == "__main__":
    unittest.main()

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
    def test_boolean_accepts_affirmative_and_negative_forms(self):
        for raw in ("yes", "Yes", "YES", "true", "True", "TRUE"):
            self.assertEqual(transforms.apply("boolean", raw), 1.0)
        for raw in ("no", "No", "NO", "false", "False", "FALSE"):
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_boolean_rejects_anything_else(self):
        for raw in ("maybe", "1", "0", "", " yesno "):
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)

    def test_boolean_column_end_to_end(self):
        tmp = tempfile.mkdtemp(prefix="rg3-bool-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "t.csv"), "w") as fh:
            fh.write("item,flag\n1,Yes\n2,no\n3,TRUE\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        out = os.path.join(tmp, "out")
        report = reportgen.run(rules_path, inp, out,
                               os.path.join(tmp, "cache", "state.json"))
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["distinct"], 2)
        self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
        for value in cols["flag"]["sample"]:
            self.assertIsInstance(value, float)


class TransformFailureTests(unittest.TestCase):
    """A failed transform must never leave a report or cache state."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-fail-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

    def write_input(self, body):
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,flag\n" + body)

    def test_failed_transform_emits_no_report_and_no_cache(self):
        self.write_input("1,yes\n2,perhaps\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_failed_transform_leaves_no_partial_cache_entry(self):
        self.write_input("1,yes\n")
        reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            before = json.load(fh)
        self.write_input("1,yes\n2,perhaps\n")
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        with open(self.cache_path) as fh:
            after = json.load(fh)
        self.assertEqual(before, after)
        for entry in after.values():
            self.assertFalse(entry["summary"]["skipped_rows"])

    def test_stale_cached_summary_cannot_mask_a_transform_failure(self):
        self.write_input("1,yes\n2,perhaps\n")
        os.makedirs(os.path.dirname(self.cache_path))
        digest = cache.file_digest(os.path.join(self.inp, "t.csv"))
        rules_fp = cache.rules_fingerprint(reportgen.load_rules(self.rules_path))
        state = {"t.csv": {"digest": digest, "rows": 2, "generated_from": 1,
                           "rules_fp": rules_fp,
                           "registry_version": "2",
                           "summary": {"columns": {}, "skipped_rows": []}}}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        with self.assertRaises(reportgen.ValidationError):
            reportgen.run(self.rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))

    def test_unhandled_transform_crash_leaves_no_report_and_no_cache(self):
        self.write_input("1,yes\n")
        rules_path = os.path.join(self.tmp, "boom.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boom"\n')

        def boom(value):
            raise RuntimeError("transform crashed: %r" % value)

        transforms.REGISTRY["boom"] = boom
        self.addCleanup(transforms.REGISTRY.pop, "boom", None)
        with self.assertRaises(RuntimeError):
            reportgen.run(rules_path, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.html")))
        self.assertFalse(os.path.exists(self.cache_path))


class CacheHygieneTests(unittest.TestCase):
    """A state file written by a future schema version must not crash
    the run and must be replaced by a valid one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-hyg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        with open(os.path.join(self.inp, "t.csv"), "w") as fh:
            fh.write("item,flag\n1,yes\n2,no\n")
        self.rules_path = os.path.join(self.tmp, "rules.toml")
        with open(self.rules_path, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')

    def write_state(self, state):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)

    def future_entry(self, registry_version):
        digest = cache.file_digest(os.path.join(self.inp, "t.csv"))
        rules_fp = cache.rules_fingerprint(reportgen.load_rules(self.rules_path))
        return {"digest": digest, "rows": 2, "generated_from": 1,
                "rules_fp": rules_fp, "registry_version": registry_version,
                "summary": {"columns": {"flag": {"non_empty": 99,
                                                 "distinct": 99,
                                                 "sample": [99.0]}},
                            "skipped_rows": []}}

    def test_future_entry_version_is_not_reused_and_is_rewritten(self):
        for future in ("4", "10", "999"):
            with self.subTest(version=future):
                self.write_state({"t.csv": self.future_entry(future)})
                report = reportgen.run(self.rules_path, self.inp, self.out,
                                       self.cache_path)
                cols = report["files"]["t.csv"]["summary"]["columns"]
                self.assertEqual(cols["flag"]["non_empty"], 2)
                self.assertEqual(cols["flag"]["sample"], [0.0, 1.0])
                with open(self.cache_path) as fh:
                    state = json.load(fh)
                self.assertEqual(state["t.csv"]["registry_version"],
                                 cache.REGISTRY_VERSION)
                self.assertEqual(state["t.csv"]["summary"]["columns"]["flag"]
                                 ["non_empty"], 2)

    def test_future_schema_state_file_is_treated_as_empty(self):
        self.write_state({"version": "999", "entries": {
            "t.csv": self.future_entry("999")}})
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        self.assertEqual(report["total_rows"], 2)
        with open(self.cache_path) as fh:
            state = json.load(fh)
        self.assertEqual(set(state), {"t.csv"})
        self.assertEqual(state["t.csv"]["registry_version"],
                         cache.REGISTRY_VERSION)

    def test_entry_from_another_registry_version_is_not_reused(self):
        self.write_state({"t.csv": self.future_entry("1")})
        report = reportgen.run(self.rules_path, self.inp, self.out,
                               self.cache_path)
        cols = report["files"]["t.csv"]["summary"]["columns"]
        self.assertEqual(cols["flag"]["numeric_sum"], 1.0)


class ReportConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-cons-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def test_report_is_identical_for_a_cold_and_a_warm_run(self):
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json")) as fh:
            cold = fh.read()
        reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.json")) as fh:
            warm = fh.read()
        self.assertEqual(cold, warm)


class HtmlEscapingTests(unittest.TestCase):
    def test_values_and_names_are_escaped(self):
        tmp = tempfile.mkdtemp(prefix="rg3-esc-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        inp = os.path.join(tmp, "in")
        os.makedirs(inp)
        with open(os.path.join(inp, "a<b>.csv"), "w") as fh:
            fh.write("i<d>,label\n1,red <b> & bold\n")
        rules_path = os.path.join(tmp, "rules.toml")
        with open(rules_path, "w") as fh:
            fh.write('[transforms]\n')
        out = os.path.join(tmp, "out")
        reportgen.run(rules_path, inp, out, os.path.join(tmp, "cache", "state.json"))
        with open(os.path.join(out, "report.html")) as fh:
            html = fh.read()
        self.assertNotIn("<b>", html)
        self.assertNotIn("a<b>.csv", html)
        self.assertNotIn("<td>i<d>", html)
        self.assertIn("a&lt;b&gt;.csv", html)
        self.assertIn("red &lt;b&gt; &amp; bold", html)


if __name__ == "__main__":
    unittest.main()

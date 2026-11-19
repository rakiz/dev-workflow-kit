"""Baseline suite for reportgen: transforms, rules loading, end-to-end
report shape, and cache state bookkeeping."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

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
    def test_affirmative_forms_map_to_one(self):
        for raw in ["yes", "YES", "Yes", "true", "TRUE"]:
            self.assertEqual(transforms.apply("boolean", raw), 1.0)

    def test_negative_forms_map_to_zero(self):
        for raw in ["no", "NO", "false", "False"]:
            self.assertEqual(transforms.apply("boolean", raw), 0.0)

    def test_other_inputs_raise(self):
        # Whitespace is not stripped: " yes" is not one of the accepted forms.
        for raw in ["", "maybe", "y", "1", "0", " yes", "yes "]:
            with self.assertRaises(transforms.TransformError):
                transforms.apply("boolean", raw)


class RegressionTests(unittest.TestCase):
    """One test per defect fixed in this release."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rg3-reg-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.inp = os.path.join(self.tmp, "in")
        os.makedirs(self.inp)
        self.rules = os.path.join(self.tmp, "rules.toml")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nflag = "boolean"\n')
        self.out = os.path.join(self.tmp, "out")
        self.cache_path = os.path.join(self.tmp, "cache", "state.json")

    def write_input(self, cell):
        with open(os.path.join(self.inp, "a.csv"), "w") as fh:
            fh.write("item,flag\n1,%s\n" % cell)

    def read_bytes(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def quiet_main(self, argv):
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return reportgen.main(argv)

    def cli_args(self):
        return ["--rules", self.rules, "--input", self.inp,
                "--output", self.out, "--cache", self.cache_path]

    def test_rules_file_read_once_per_run(self):
        # Defect: load_rules ran once per CSV file inside the loop.
        with mock.patch.object(reportgen, "load_rules",
                               wraps=reportgen.load_rules) as spy:
            reportgen.run(RULES, INPUT_DIR, os.path.join(self.tmp, "out"),
                          self.cache_path)
        self.assertEqual(spy.call_count, 1)

    def test_failed_transform_keeps_previous_outputs_and_cache(self):
        # Defect: report.html and cache entries were written before, and
        # independently of, the failure check.
        self.write_input("yes")
        self.assertEqual(self.quiet_main(self.cli_args()), 0)
        watched = [os.path.join(self.out, "report.html"),
                   os.path.join(self.out, "report.json"),
                   self.cache_path]
        before = [self.read_bytes(p) for p in watched]
        self.write_input("maybe")  # changes the digest, so a naive run rewrites
        self.assertEqual(self.quiet_main(self.cli_args()), 1)
        self.assertEqual([self.read_bytes(p) for p in watched], before)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.cache_path))),
                         ["state.json"])

    def test_failed_transform_on_first_run_emits_nothing(self):
        self.write_input("maybe")
        self.assertEqual(self.quiet_main(self.cli_args()), 1)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_unhandled_crash_in_transform_emits_nothing(self):
        self.write_input("yes")
        with mock.patch.object(transforms, "apply",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(self.cache_path))

    def test_clean_run_exit_status_zero(self):
        self.write_input("yes")
        self.assertEqual(self.quiet_main(self.cli_args()), 0)
        self.assertTrue(os.path.exists(os.path.join(self.out, "report.json")))

    def test_boolean_column_reported_as_floats(self):
        self.write_input("Yes")
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        flag = report["files"]["a.csv"]["summary"]["columns"]["flag"]
        self.assertEqual(flag["sample"], [1.0])
        self.assertEqual(flag["numeric_sum"], 1.0)

    def test_stale_registry_version_entry_not_reused(self):
        # Defect: lookup never compared the entry's registry_version.
        self.write_input("yes")
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        state = cache.load_state(self.cache_path)
        state["a.csv"]["registry_version"] = "1"
        state["a.csv"]["summary"] = {"columns": {}, "skipped_rows": [],
                                     "marker": True}
        with open(self.cache_path, "w") as fh:
            json.dump(state, fh)
        report = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        summary = report["files"]["a.csv"]["summary"]
        self.assertNotIn("marker", summary)
        self.assertEqual(summary["columns"]["flag"]["numeric_sum"], 1.0)

    def test_generated_from_same_on_cache_hit_and_miss(self):
        # Defect: a cache hit reported a different generated_from than a
        # fresh pass (header-based vs non-empty-based count).
        with open(os.path.join(self.inp, "g.csv"), "w") as fh:
            fh.write("item,flag,empty_col\n1,yes,\n2,no,\n")
        with open(self.rules, "w") as fh:
            fh.write('[transforms]\nitem = "trim"\nflag = "boolean"\n'
                     'empty_col = "trim"\n')
        miss = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        hit = reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        self.assertEqual(miss["files"]["g.csv"]["generated_from"], 2)
        self.assertEqual(hit["files"]["g.csv"]["generated_from"], 2)

    def test_future_schema_cache_is_treated_as_empty(self):
        # Future entries are never reused and the state file is rewritten.
        future = str(int(cache.REGISTRY_VERSION) + 1)
        digest = cache.file_digest(os.path.join(INPUT_DIR, "small_devices.csv"))
        fp = cache.rules_fingerprint(reportgen.load_rules(RULES))
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({"small_devices.csv": {
                "digest": digest, "rows": 3, "rules_fp": fp,
                "registry_version": future,
                "summary": {"columns": {}, "skipped_rows": [], "marker": True}}},
                fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertNotIn("marker", report["files"]["small_devices.csv"]["summary"])
        state = cache.load_state(self.cache_path)
        self.assertEqual(len(state), 4)
        for entry in state.values():
            self.assertEqual(entry["registry_version"], cache.REGISTRY_VERSION)

    def test_future_schema_version_field_is_treated_as_empty(self):
        future = str(int(cache.REGISTRY_VERSION) + 1)
        os.makedirs(os.path.dirname(self.cache_path))
        with open(self.cache_path, "w") as fh:
            json.dump({"version": future, "files": {"x": {"odd": True}}}, fh)
        report = reportgen.run(RULES, INPUT_DIR, self.out, self.cache_path)
        self.assertEqual(report["total_rows"], 12012)
        state = cache.load_state(self.cache_path)
        self.assertEqual(len(state), 4)
        self.assertNotIn("version", state)

    def test_html_escapes_file_and_column_names(self):
        # Only sample values were escaped before; names were not.
        with open(os.path.join(self.inp, "a<b>.csv"), "w") as fh:
            fh.write("x<y>\nv&w\n")
        with open(self.rules, "w") as fh:
            fh.write("[transforms]\n")
        reportgen.run(self.rules, self.inp, self.out, self.cache_path)
        with open(os.path.join(self.out, "report.html")) as fh:
            page = fh.read()
        self.assertNotIn("<y>", page)
        self.assertNotIn("<b>.csv", page)
        self.assertIn("x&lt;y&gt;", page)
        self.assertIn("a&lt;b&gt;.csv", page)


if __name__ == "__main__":
    unittest.main()
